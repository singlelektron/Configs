#!/usr/bin/env python3
"""Opt-in three-state CPU/RSS sample of an already protected private preview.

Run after moonlit_media_live.py --keep-player. No sound-device or host-player
commands. Counts live descendant CPU plus reaped child CPU; percentages use one
logical CPU as 100%. The observer is outside the measured shell process tree.
/proc reads are non-atomic; use full-interval CPU means, not single-sample spikes.
Summed RSS includes shared pages more than once and is not PSS. Observed child
PIDs are sampled, not a total process-launch counter.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from moonlit_media_live import load_preview, PrivateMpris, atomic_json


def processes():
    result = {}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            raw = (p/'stat').read_text(); name = raw.split('(', 1)[1].rsplit(')', 1)[0]
            s = raw.rsplit(')', 1)[1].split()
            result[int(p.name)] = dict(pid=int(p.name), ppid=int(s[1]), start=int(s[19]),
                name=name, own=int(s[11])+int(s[12]), reaped=int(s[13])+int(s[14]),
                rss=int(s[21])*os.sysconf('SC_PAGE_SIZE')/1048576)
        except (OSError, ValueError, IndexError):
            continue
    return result


def shell_sample(identity):
    entries = processes(); root = entries.get(identity['pid'])
    if root is None or root['start'] != identity['start']:
        raise RuntimeError('Measured shell exited or its PID was reused')
    selected = {root['pid']}
    while True:
        expanded = selected | {pid for pid,p in entries.items() if p['ppid'] in selected}
        if expanded == selected:
            break
        selected = expanded
    children = [entries[pid] for pid in selected if pid != root['pid']]
    return dict(own_ticks=root['own'], tree_ticks=sum(entries[p]['own']+entries[p]['reaped'] for p in selected),
                rss_mib=root['rss'], tree_rss_mib=sum(entries[p]['rss'] for p in selected),
                children=[dict(pid=p['pid'], start=p['start'], name=p['name'], rss_mib=p['rss']) for p in children])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--include-room-playing', action='store_true', help='also measure visible progress updates')
    args = parser.parse_args()
    if not 30 <= args.seconds <= 600:
        parser.error('seconds must be 30..600')
    preview = load_preview(); root = preview.safe_root(args.runtime.expanduser().absolute())
    env = preview.nested_environment(root)
    if not env.get('DBUS_SESSION_BUS_ADDRESS') or env['DBUS_SESSION_BUS_ADDRESS'] == os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
        raise RuntimeError('Refusing host or missing bus')
    source = json.loads((root/'media-lifecycle.json').read_text())['player']; bus = PrivateMpris(env['DBUS_SESSION_BUS_ADDRESS'])
    if not preview.alive(source) or bus.owner_pid(source['bus']) != source['pid']:
        raise RuntimeError('Expected retained task-owned VLC')
    identity = preview.state(root)['shell']; output = args.output.expanduser().absolute(); output.mkdir(parents=True,exist_ok=True)
    bridge = root/'data/noctalia/plugins/moonlit-music/media_bridge.py'
    def command(*argv):
        return subprocess.run(argv, env=env, capture_output=True, text=True, check=True, timeout=10)
    def playback(wanted):
        current = bus.snapshot(source['bus'])['status']
        if current != wanted:
            command('/usr/bin/python3',str(bridge),'toggle')
        deadline = time.monotonic()+4
        while bus.snapshot(source['bus'])['status'] != wanted:
            if time.monotonic() > deadline: raise RuntimeError('Playback transition failed')
            time.sleep(.05)
    command('/usr/bin/python3',str(bridge),'select',source['bus'])
    report = dict(scope='native Noctalia + all live/reaped descendants, one CPU = 100%; not whole desktop',
        seconds_per_state=args.seconds, shell=identity, player=source, outputs=preview.status(root)['outputs'], states={})
    hz = os.sysconf('SC_CLK_TCK')
    phases = [('closed_paused',False,'Paused'),('room_paused',True,'Paused'),('closed_playing',False,'Playing')]
    if args.include_room_playing:
        phases.append(('room_playing',True,'Playing'))
    for name, opened, status in phases:
        playback(status)
        command(str(root/'bin/noctalia'),'msg','panel-open' if opened else 'panel-close','dotfiles/moonlit-music:room')
        time.sleep(10)
        first=shell_sample(identity); started=time.monotonic(); last=first; last_at=started; rows=[]; observed={}
        with (output/(name+'.csv')).open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=['elapsed_s','shell_cpu_pct','shell_tree_cpu_pct','shell_rss_mib','shell_tree_rss_mib','children'])
            writer.writeheader()
            while time.monotonic()-started < args.seconds:
                time.sleep(min(2,max(0,args.seconds-(time.monotonic()-started))))
                sample=shell_sample(identity);now=time.monotonic();interval=now-last_at
                row=dict(elapsed_s=round(now-started,3),shell_cpu_pct=(sample['own_ticks']-last['own_ticks'])/hz/interval*100,
                    shell_tree_cpu_pct=(sample['tree_ticks']-last['tree_ticks'])/hz/interval*100,
                    shell_rss_mib=sample['rss_mib'],shell_tree_rss_mib=sample['tree_rss_mib'],children=json.dumps(sample['children']))
                for child in sample['children']:observed[str(child['pid'])+':'+str(child['start'])]=child
                writer.writerow(row);stream.flush();rows.append(row);last=sample;last_at=now
        duration=last_at-started
        report['states'][name]=dict(duration_s=duration,shell_cpu_pct=(last['own_ticks']-first['own_ticks'])/hz/duration*100,
            shell_tree_cpu_pct=(last['tree_ticks']-first['tree_ticks'])/hz/duration*100,
            shell_rss_mib=statistics.mean(x['shell_rss_mib'] for x in rows),
            shell_tree_rss_mib=statistics.mean(x['shell_tree_rss_mib'] for x in rows),
            observed_children=list(observed.values()),direct_player=bus.snapshot(source['bus']))
        atomic_json(output/'summary.json',report)
        print(json.dumps({'completed_state':name,**{k:v for k,v in report['states'][name].items() if k not in ('observed_children','direct_player')} }),flush=True)
    playback('Paused')
    print(json.dumps({'report':str(output/'summary.json'),'complete':True}),flush=True)


if __name__=='__main__':main()
