"""Run as Niri's child inside dbus-run-session, using a disposable Niri config.

Starts real Quickshell and two fake MPRIS services, verifies player priority,
transport calls, seeking, hot removal, Niri events and layer keyboard focus.
Never run on the user's D-Bus session. Does not touch real music playback.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    if '/tmp/dbus-' not in os.environ.get('DBUS_SESSION_BUS_ADDRESS', '') or not os.environ.get('NIRI_SOCKET'):
        raise SystemExit('Requires a disposable dbus-run-session and nested Niri')
    # Make every run's evidence unambiguous, including an early startup failure.
    for evidence in ('/tmp/island-mpris-result.json', '/tmp/island-mpris-error.txt'):
        Path(evidence).unlink(missing_ok=True)
    source = Path(__file__).resolve().parents[1] / 'desktop-island'
    fixture = Path(__file__).with_name('mock_mpris.py')
    with tempfile.TemporaryDirectory(prefix='island-mpris-') as directory:
        root = Path(directory)
        (root / 'niri').mkdir()
        (root / 'niri/updates.py').write_text('import json\nprint(json.dumps({"status":"ok","count":0,"checked_at":1,"packages":[],"error":""}))\n')
        env = dict(os.environ, XDG_CONFIG_HOME=str(root), XDG_CACHE_HOME=str(root / 'cache'),
                   DOTFILES_SHELL_PREVIEW='0', QT_QPA_PLATFORM='wayland')
        log = root / 'transport.jsonl'
        output = (root / 'quickshell.log').open('w+')
        mock = subprocess.Popen(['/usr/bin/python3', str(fixture), str(log)], env=env, stdout=output, stderr=output)
        shell = subprocess.Popen(['quickshell', '--path', str(source), '--no-color'], env=env, stdout=output, stderr=output)

        def call(method, *args):
            result = subprocess.run(['quickshell', 'ipc', '--path', str(source), 'call', 'island', method, *map(str, args)],
                                    env=env, capture_output=True, text=True, timeout=4)
            if result.returncode:
                raise RuntimeError(result.stderr)
            return result.stdout

        def state():
            return json.loads(call('snapshot'))

        def wait_for(predicate):
            deadline = time.monotonic() + 12
            last = None
            while time.monotonic() < deadline:
                try:
                    value = state()
                    last = value
                    if predicate(value):
                        return value
                except (RuntimeError, ValueError) as error:
                    last = str(error)
                time.sleep(.15)
            raise AssertionError('Expected state not reached: ' + str(last))

        try:
            value = wait_for(lambda value: value['player'] == 'org.mpris.MediaPlayer2.NeteaseCloudMusicGtk4')
            assert value['playing'] is False, value
            assert value['seekable'] is True, value
            assert value['title'] == '<b>春 & music</b>', value
            call('togglePlayback')
            wait_for(lambda value: value['playing'] is True)
            call('nextTrack')
            call('previousTrack')
            call('seekTo', 120)
            time.sleep(.3)
            actions = [json.loads(line) for line in log.read_text().splitlines()]
            assert all(entry['player'] == 'NeteaseCloudMusicGtk4' for entry in actions), actions
            action_names = {entry['action'] for entry in actions}
            assert action_names >= {'Next', 'Previous', 'SetPosition'}, actions
            assert action_names.intersection({'Play', 'PlayPause'}), actions
            assert next(entry for entry in actions if entry['action'] == 'SetPosition')['value'] == 120000000

            call('open', 'music')
            time.sleep(.3)
            layers = json.loads(subprocess.check_output(['niri', 'msg', '--json', 'layers'], env=env, text=True))
            assert any(layer['namespace'] == 'dotfiles-island' and layer['keyboard_interactivity'] == 'Exclusive' for layer in layers)
            call('close')
            time.sleep(.3)
            layers = json.loads(subprocess.check_output(['niri', 'msg', '--json', 'layers'], env=env, text=True))
            assert all(layer['keyboard_interactivity'] == 'None' for layer in layers if layer['namespace'] == 'dotfiles-island')

            subprocess.run(['niri', 'msg', 'action', 'focus-workspace', 'code'], env=env, check=True)
            wait_for(lambda value: any(w['name'] == 'code' and w['is_focused'] for w in value['workspaces']))
            mock.terminate(); mock.wait(timeout=3)
            value = wait_for(lambda value: value['player'] is None)
            assert value['title'] == 'Music' and value['playing'] is False, value
            output.flush(); output.seek(0)
            logs = output.read()
            assert 'ReferenceError' not in logs and 'TypeError' not in logs and 'Failed to load configuration' not in logs, logs
            result = {'result': 'PASS', 'transport': actions, 'no_player': value,
                      'checks': ['NetEase preference over playing browser', 'plain hostile metadata', 'playback', 'next/previous', 'seek in microseconds', 'hot removal', 'Niri workspace events', 'expanded/folded layer focus']}
            Path('/tmp/island-mpris-result.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        except Exception:
            import traceback
            Path('/tmp/island-mpris-error.txt').write_text(traceback.format_exc())
            raise
        finally:
            for process in (shell, mock):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
            output.seek(0)
            Path('/tmp/island-mpris-quickshell.log').write_text(output.read())
            output.close()
            subprocess.run(['niri', 'msg', 'action', 'quit', '--skip-confirmation'], env=env)


if __name__ == '__main__':
    main()
