#!/usr/bin/env python3
"""Opt-in native Luau state and owned stream crash/reload regression.

Only an existing protected preview and its retained dummy-output VLC are used.
The diagnostic IPC is read-only; it reports the same state used by native UI.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid
from moonlit_media_live import load_preview, PrivateMpris, atomic_json, await_value

ROOT = Path(__file__).resolve().parents[1]
ROOM = 'dotfiles/moonlit-music:room'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    preview = load_preview()
    root = preview.safe_root(args.runtime.expanduser().absolute())
    env = preview.nested_environment(root)
    address = env.get('DBUS_SESSION_BUS_ADDRESS')
    if not address or address == os.environ.get('DBUS_SESSION_BUS_ADDRESS') or env.get('MOONLIT_PREVIEW') != '1':
        raise RuntimeError('Refusing host or unprotected session')
    shell = preview.state(root)['shell']
    player = json.loads((root/'media-lifecycle.json').read_text())['player']
    bus = PrivateMpris(address)
    if not preview.alive(shell) or not preview.alive(player) or bus.owner_pid(player['bus']) != player['pid']:
        raise RuntimeError('Preview shell or retained VLC identity does not match')
    if '--aout' not in player['argv'] or player['argv'][player['argv'].index('--aout')+1] != 'dummy':
        raise RuntimeError('Retained player is not the dummy-audio fixture')
    plugin = root/'data/noctalia/plugins/moonlit-music'
    log = root/'cache/noctalia/noctalia.log'
    report = {'kind':'native Noctalia Luau state, real silent VLC, plugin-owned stream lifecycle',
              'shell':shell, 'player':player, 'assertions':{}, 'diagnostics':{}}
    disabled = False

    def ipc(*args):
        result = subprocess.run([str(root/'bin/noctalia'),'msg',*args],env=env,text=True,
                                capture_output=True,timeout=8,check=True)
        if result.stdout.startswith('error:'):
            raise RuntimeError(result.stdout.strip())
        return result.stdout

    def diagnostic():
        nonce = uuid.uuid4().hex
        offset = log.stat().st_size
        ipc('plugin','dotfiles/moonlit-music:media','all','status',nonce)
        deadline = time.monotonic()+5
        next_flush = time.monotonic()+.25
        while time.monotonic() < deadline:
            with log.open() as stream:
                stream.seek(offset)
                text = stream.read()
            for line in text.splitlines():
                marker='moonlit-media-status '
                if marker not in line:
                    continue
                data,_ = json.JSONDecoder().raw_decode(line.split(marker,1)[1])
                if data.get('request') == nonce:
                    return data
            if time.monotonic() >= next_flush:
                # Log files flush on a subsequent record after their interval;
                # another read-only IPC emits that record without changing UI.
                ipc('plugin','dotfiles/moonlit-music:media','all','status','flush-'+nonce)
                next_flush = time.monotonic()+.25
            time.sleep(.03)
        raise RuntimeError('Native service did not log the requested Luau state')

    def workers():
        found=[]
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                argv=(entry/'cmdline').read_bytes().split(b'\0')
                if str(plugin/'media_watch.py').encode() not in argv:
                    continue
                identity=preview.proc_identity(int(entry.name))
                wrapper=preview.proc_identity(identity['ppid']) if identity else None
                if not wrapper or wrapper['ppid'] != shell['pid'] or not preview.alive(identity):
                    continue
                if b'--owner-pid' not in argv or argv[argv.index(b'--owner-pid')+1] != str(shell['pid']).encode():
                    raise RuntimeError('Gio worker has incorrect Noctalia owner pid')
                found.append({'worker':identity,'wrapper':wrapper})
            except (FileNotFoundError,ProcessLookupError,PermissionError):
                continue
        return found

    def direct(method, signature=None, values=()):
        if not preview.alive(player) or bus.owner_pid(player['bus']) != player['pid']:
            raise RuntimeError('Retained player ownership changed')
        return bus.call(player['bus'],'/org/mpris/MediaPlayer2','org.mpris.MediaPlayer2.Player',method,signature,values)

    def ui_status(status):
        return await_value(diagnostic,lambda p:p.get('stream_running') and p.get('media',{}).get('player')==player['bus'] and p['media'].get('status')==status,
                           'native UI '+status,timeout=8)

    try:
        before=await_value(workers,lambda p:len(p)==1,'one initial stream')
        report['initial_processes']=before
        shutil.copyfile(ROOT/'config/moonlit/plugins/moonlit-music/media_watch.py', plugin/'media_watch.py')
        for name in ('common.luau','bar.luau','controls.luau','room.luau'):
            temporary=plugin/(name+'.new')
            shutil.copyfile(ROOT/'config/moonlit/plugins/moonlit-music'/name,temporary)
            temporary.replace(plugin/name)
        temporary=plugin/'service.luau.new'
        shutil.copyfile(ROOT/'config/moonlit/plugins/moonlit-music/service.luau',temporary)
        temporary.replace(plugin/'service.luau')
        current=await_value(workers,lambda p:len(p)==1 and p[0]['worker']['pid'] != before[0]['worker']['pid'],
                            'hotreload replacement stream')
        await_value(lambda:all(not preview.alive(item) for pair in before for item in pair.values()),bool,'old stream cleanup')
        report['assertions']['hotreload_reaps_old_wrapper_and_worker']=True
        report['reloaded_processes']=current
        report['diagnostics']['initial']=ui_status('Paused')
        report['assertions']['native_ui_contains_real_vlc']=report['diagnostics']['initial']['media']['title']=='Local playback test'
        target=current[0]['worker']
        if not preview.signal_owned(target,signal.SIGKILL):
            raise RuntimeError('Owned worker was not live for crash validation')
        failed=await_value(diagnostic,lambda d:not d['stream_running'] and d['media'].get('bridge_stopped') is True,
                           'native UI worker exit state')
        report['diagnostics']['after_worker_sigkill']=failed
        report['assertions']['worker_crash_clears_ui_state']=not failed['media'].get('player') and not failed['media'].get('players') and not failed['media'].get('can_play')
        await_value(lambda:all(not preview.alive(x) for x in current[0].values()),bool,'crashed worker wrapper exit')
        time.sleep(.6)
        report['assertions']['worker_exit_does_not_autorestart']=not workers()
        ipc('panel-close',ROOM)
        ipc('panel-open',ROOM)
        report['diagnostics']['reconnected']=ui_status('Paused')
        current=await_value(workers,lambda p:len(p)==1,'one reconnected stream')
        report['assertions']['panel_open_reconnects_same_real_vlc']=True
        direct('Play')
        report['diagnostics']['playing']=ui_status('Playing')
        first=report['diagnostics']['playing']['media']['position']
        time.sleep(1.25)
        progressed=diagnostic()
        report['assertions']['visible_playing_ui_position_advances']=progressed['media']['position']>first+.4
        track=bus.snapshot(player['bus'])['metadata']['mpris:trackid']
        direct('SetPosition','(ox)',(str(track),90000000))
        seeked=await_value(diagnostic,lambda d:89<=d['media'].get('position',0)<=96,'seek reflected by native UI')
        report['diagnostics']['seeked']=seeked
        report['assertions']['real_seek_updates_native_ui']=True
        direct('Pause')
        report['diagnostics']['paused']=ui_status('Paused')
        # Native MPRIS debounces property bursts: final UI state must still settle.
        direct('Play')
        time.sleep(.025)
        direct('Pause')
        time.sleep(.25)
        report['diagnostics']['burst_paused']=ui_status('Paused')
        report['assertions']['rapid_status_burst_settles_to_real_status']=True
        ipc('panel-close',ROOM)
        closed=await_value(diagnostic,lambda d:not d['visible_room'] and not d['visible_controls'],'both panels closed')
        report['diagnostics']['closed']=closed
        time.sleep(1.2)
        stable=diagnostic()
        report['assertions']['closed_paused_ui_state_is_stable']=stable['media']==closed['media']
        before_disable=workers()
        ipc('plugins','disable','dotfiles/moonlit-music')
        disabled=True
        await_value(lambda:all(not preview.alive(x) for pair in before_disable for x in pair.values()),bool,'disable cleanup')
        report['assertions']['plugin_disable_reaps_wrapper_and_worker']=not workers()
        ipc('plugins','enable','dotfiles/moonlit-music')
        disabled=False
        enabled=ui_status('Paused')
        report['diagnostics']['reenabled']=enabled
        report['assertions']['reenable_has_no_stuck_pending_command']=enabled['command_pending'] is False
        report['final_processes']=await_value(workers,lambda p:len(p)==1,'one enabled stream')
        report['assertions']['one_worker_after_reconnect']=len(report['final_processes'])==1
        report['passed']=all(report['assertions'].values())
    except Exception as error:
        report['passed']=False
        report['error']=str(error)
    finally:
        try:
            if disabled:
                ipc('plugins','enable','dotfiles/moonlit-music')
            direct('Pause')
            ipc('panel-close',ROOM)
            ipc('panel-close','dotfiles/moonlit-music:controls')
            report['final_real_player']=bus.snapshot(player['bus'])
        except Exception as error:
            report['cleanup_error']=str(error)
            report['passed']=False
        args.output.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(args.output,report)
    print(json.dumps({'passed':report['passed'],'assertions':report['assertions'],'error':report.get('error'),
                      'report':str(args.output)},ensure_ascii=False,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
