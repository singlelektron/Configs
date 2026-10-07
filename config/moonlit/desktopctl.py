#!/usr/bin/env python3
"""Reversible Moonlit entry points and a guarded, main-session shell runner.

Deployment owns the manifest. This bridge never installs/enables a service and
keeps legacy lock, idle, notification and presentation commands on their pinned
helper. Noctalia alone gets filtered D-Bus and an unavailable PipeWire remote.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time

BAR_UNIT = 'dotfiles-niri-waybar.service'
KEEP_UNITS = tuple('dotfiles-niri-' + name + '.service' for name in ('mako', 'idle', 'session-events', 'polkit'))
SYSTEM_READ = {
    'org.freedesktop.NetworkManager': ('GetDevices', 'GetAllDevices', 'GetDeviceByIpIface', 'GetPermissions'),
    'org.bluez': (), 'org.freedesktop.UPower': ('EnumerateDevices', 'GetDisplayDevice', 'EnumerateKbdBacklights'),
    'org.freedesktop.login1': ('GetSession', 'GetSessionByPID', 'ListSessions', 'ListInhibitors'),
}
READ_INTERFACES = ('org.freedesktop.DBus.Properties.Get', 'org.freedesktop.DBus.Properties.GetAll',
                   'org.freedesktop.DBus.ObjectManager.GetManagedObjects', 'org.freedesktop.DBus.Introspectable.Introspect')


class DesktopError(RuntimeError):
    pass


def run(argv, **kwargs):
    result = subprocess.run(argv, check=False, **kwargs)
    if result.returncode:
        raise DesktopError(f'Command failed ({result.returncode}): {argv[0]}')
    return result


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.moonlit-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def identity(pid):
    try:
        path = Path('/proc') / str(pid)
        if path.stat().st_uid != os.getuid():
            return None
        value = (path/'stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': int(pid), 'start': int(value[19]), 'ppid': int(value[1]),
                'session': int(value[3]), 'state': value[0]}
    except (OSError, ValueError, IndexError):
        return None


def alive(value):
    if not isinstance(value, dict) or not isinstance(value.get('pid'), int) or not isinstance(value.get('start'), int):
        return False
    current = identity(value['pid'])
    return bool(current and current['start'] == value['start'] and current['state'] != 'Z')


def peer_pid(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(path)
        pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
        if uid != os.getuid():
            raise DesktopError('Niri socket belongs to another user')
        return pid


def require_session():
    path = os.environ.get('NIRI_SOCKET')
    if not path or not os.environ.get('WAYLAND_DISPLAY') or not os.environ.get('XDG_RUNTIME_DIR'):
        raise DesktopError('A main Niri session is required')
    manager_env = dict(os.environ)
    # A launcher helper inherits Noctalia's filtered bus. Query the user manager
    # on its normal XDG_RUNTIME_DIR bus without granting that bus to the shell.
    manager_env.pop('DBUS_SESSION_BUS_ADDRESS', None)
    result = run(['systemctl', '--user', 'show', '--property=MainPID', '--value', 'niri.service'],
                 capture_output=True, text=True, timeout=4, env=manager_env)
    try:
        pid = int(result.stdout.strip())
        if pid <= 0 or peer_pid(path) != pid or not alive(identity(pid)):
            raise DesktopError('Refusing a nested or unowned compositor')
    except (ValueError, OSError) as error:
        raise DesktopError('Cannot identify the main Niri session') from error
    return identity(pid)


def manifest_path():
    explicit = os.environ.get('MOONLIT_SESSION_MANIFEST')
    root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')
    path = Path(explicit) if explicit else root/'niri/moonlit-session.json'
    if not path.is_absolute():
        raise DesktopError('Moonlit manifest path must be absolute')
    return path


def read_manifest(path=None):
    path = path or manifest_path()
    target = path.resolve(strict=True)
    info = target.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise DesktopError('Moonlit manifest must be a user-owned, non-writable-by-others regular file')
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or (value.get('schema'), value.get('kind'), value.get('phase')) != (1, 'moonlit-live-session', 'basic'):
        raise DesktopError('Unsupported Moonlit session manifest')
    if value.get('bar_unit') != BAR_UNIT:
        raise DesktopError('Unexpected shell service in Moonlit manifest')
    for key in ('legacy_desktopctl', 'live_root', 'binary', 'config_dir', 'state_dir', 'data_dir', 'cache_dir', 'release', 'transaction'):
        raw = value.get(key)
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise DesktopError('Invalid manifest path: ' + key)
    release = Path(value['release'])
    expected = release/'managed/niri/moonlit-session.json'
    if target != expected or any(p.is_symlink() for p in (expected, *expected.parents)):
        raise DesktopError('Moonlit manifest must resolve to its fixed release')
    index_path = release/'manifest.json'
    index_info = index_path.lstat()
    if (not stat.S_ISREG(index_info.st_mode) or index_info.st_uid != os.getuid()
            or index_info.st_mode & 0o022):
        raise DesktopError('Invalid release integrity manifest')
    index = json.loads(index_path.read_text())
    expected_hash = index.get('files', {}).get('managed/niri/moonlit-session.json')
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
        raise DesktopError('Moonlit manifest differs from its fixed release')
    root = Path(value['live_root'])
    if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
        raise DesktopError('Live runtime directory must belong to this user')
    for key in ('config_dir', 'state_dir', 'data_dir', 'cache_dir'):
        resolved = Path(value[key]).resolve()
        if root.resolve() not in resolved.parents:
            raise DesktopError('Noctalia directories must stay within the live runtime')
    helper = Path(value['legacy_desktopctl'])
    if helper.resolve() == Path(__file__).resolve() or not helper.is_file():
        raise DesktopError('Legacy helper is missing or loops back to Moonlit')
    if hashlib.sha256(helper.read_bytes()).hexdigest() != value.get('legacy_sha256'):
        raise DesktopError('Pinned legacy helper changed; restore or re-stage before continuing')
    if not Path(value['binary']).is_file():
        raise DesktopError('Pinned Noctalia binary is missing')
    library = value.get('library_path', '')
    if not isinstance(library, str) or (library and not Path(library).is_absolute()):
        raise DesktopError('Invalid Noctalia library path')
    return value


def shell_environment(value, session_address, system_address):
    env = dict(os.environ)
    # Keep genuine HOME/XDG/Niri/Wayland. Apps use native `niri ... spawn` so
    # these shell-only restrictions are not inherited by the launched app.
    env.update(NOCTALIA_CONFIG_HOME=value['config_dir'], NOCTALIA_STATE_HOME=value['state_dir'],
               NOCTALIA_DATA_HOME=value['data_dir'], XDG_CACHE_HOME=value['cache_dir'],
               DBUS_SESSION_BUS_ADDRESS=session_address, DBUS_SYSTEM_BUS_ADDRESS=system_address,
               PIPEWIRE_REMOTE='moonlit-basic-unavailable', GSETTINGS_BACKEND='memory',
               MOONLIT_SESSION_MANIFEST=str(Path(value['release'])/'managed/niri/moonlit-session.json'),
               TERMINAL=shlex.join(['/usr/bin/python3',str(fixed_helper(value)),'terminal']))
    if value.get('library_path'):
        env['LD_LIBRARY_PATH'] = value['library_path']
    return env


def fixed_helper(value):
    return Path(value['release'])/'managed/niri/desktopctl.py'


def launcher_prefix(value):
    return shlex.join(['/usr/bin/python3',str(fixed_helper(value)),'launch','--'])+' '


def host_launch(arguments):
    require_session()
    if not arguments or not arguments[0]:
        raise DesktopError('An application command is required')
    # Niri owns both the application's environment and lifetime. The fixed shell
    # script only carries the desktop entry's working directory as an argument.
    return run(['niri','msg','action','spawn','--','/bin/sh','-c',
                'cd -- "$1" && shift && exec "$@"','moonlit-app',os.getcwd(),*arguments],timeout=6).returncode


def terminal_launch(value, arguments):
    # Noctalia wraps Terminal=true after applying launch_apps_custom_command.
    # Unwrap our exact prefix, retaining the original command's shell quoting.
    if len(arguments)==4 and arguments[:3]==['-e','sh','-lc']:
        command=arguments[3]
        prefix=launcher_prefix(value)
        if command.startswith(prefix):
            command=command[len(prefix):]
        if not command.strip():
            raise DesktopError('An application command is required')
        return host_launch(['kitty','-e','sh','-lc',command])
    if not arguments:
        return host_launch(['kitty'])
    if arguments[0]!='-e' or len(arguments)<2:
        raise DesktopError('Unsupported terminal invocation')
    return host_launch(['kitty',*arguments])


def proxy_commands(root, session_address, system_address):
    system = ['xdg-dbus-proxy', system_address, str(root/'system-bus'), '--filter', '--log']
    for name, methods in SYSTEM_READ.items():
        interface = name + '.Manager' if name == 'org.freedesktop.login1' else name
        system += ['--see=' + name, '--broadcast=' + name + '=*']
        system += ['--call=' + name + '=' + method for method in READ_INTERFACES]
        system += ['--call=' + name + '=' + interface + '.' + method for method in methods]
    system += ['--call=org.freedesktop.NetworkManager=org.freedesktop.NetworkManager.Device.Wireless.GetAccessPoints',
               '--call=org.freedesktop.NetworkManager=org.freedesktop.NetworkManager.Device.Wireless.GetAllAccessPoints',
               '--call=org.freedesktop.NetworkManager=org.freedesktop.NetworkManager.Settings.ListConnections',
               '--call=org.freedesktop.NetworkManager=org.freedesktop.NetworkManager.Settings.Connection.GetSettings']
    session = ['xdg-dbus-proxy', session_address, str(root/'session-bus'), '--filter', '--log',
               '--own=dev.noctalia.Mpris', '--own=dev.noctalia.Debug', '--see=org.mpris.MediaPlayer2.*',
               '--broadcast=org.mpris.MediaPlayer2.*=*', '--see=org.freedesktop.Notifications',
               '--see=org.freedesktop.ScreenSaver']
    session += ['--call=org.mpris.MediaPlayer2.*=' + method + '@/org/mpris/MediaPlayer2' for method in READ_INTERFACES[:2]]
    # Native repeat/shuffle controls write player properties, not PipeWire or
    # system devices. Keep that permission confined to the standard MPRIS path.
    session += ['--call=org.mpris.MediaPlayer2.*=org.freedesktop.DBus.Properties.Set@/org/mpris/MediaPlayer2']
    session += ['--call=org.mpris.MediaPlayer2.*=org.mpris.MediaPlayer2.Player.' + method + '@/org/mpris/MediaPlayer2'
                for method in ('Play', 'Pause', 'PlayPause', 'Stop', 'Next', 'Previous', 'Seek', 'SetPosition')]
    # No ownership of Notifications, ScreenSaver or StatusNotifierWatcher. The
    # existing services remain their owners. Native text-input uses Wayland.
    return system, session


def verify_proxy(address, session=False):
    if session:
        args = ['org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'RequestName',
                'su', f'org.freedesktop.ScreenSaver.MoonlitDeniedProbe.p{os.getpid()}_{time.monotonic_ns()}', '4']
    else:
        args = ['org.bluez', '/org/bluez/moonlit_denied_probe', 'org.bluez.Device1', 'Connect']
    result = subprocess.run(['busctl', '--address=' + address, 'call', *args], capture_output=True, text=True, timeout=4)
    # A name hidden by the proxy is rewritten to ServiceUnknown even though
    # RequestName itself targets the bus; a real bus accepts this unique name.
    if session and result.returncode != 0 and 'org.freedesktop.DBus.Error.ServiceUnknown' in result.stderr:
        return
    if result.returncode == 0 or not any(word in result.stderr.lower() for word in ('accessdenied', 'not allowed', 'denied')):
        raise DesktopError('D-Bus proxy did not deny the harmless safety probe: '
                           + (result.stdout.strip() or result.stderr.strip()))


def stop_process(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def noctalia_socket():
    return Path(os.environ['XDG_RUNTIME_DIR'])/('noctalia-'+os.environ['WAYLAND_DISPLAY']+'.sock')


def shell(value):
    niri = require_session()
    root = Path(value['live_root'])
    original_session = os.environ.get('DBUS_SESSION_BUS_ADDRESS', '')
    original_system = os.environ.get('DBUS_SYSTEM_BUS_ADDRESS', 'unix:path=/run/dbus/system_bus_socket')
    if not original_session or str(root) in original_session:
        raise DesktopError('A genuine session bus address is required')
    lockfd = os.open(root/'runner.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lockfd)
        raise DesktopError('Moonlit already has a session runner')
    children, pidfds = [], []
    published_session = False
    def interrupted(_number, _frame):
        raise InterruptedError('Moonlit runner stopped')
    previous = {number: signal.signal(number, interrupted) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        existing = json.loads((root/'processes.json').read_text()) if (root/'processes.json').exists() else {}
        if any(alive(existing.get(key)) for key in ('runner', 'shell', 'system_proxy', 'session_proxy')):
            raise DesktopError('A previous Moonlit child is still alive; recover that session first')
        if noctalia_socket().exists():
            try:
                peer_pid(str(noctalia_socket()))
            except ConnectionRefusedError:
                pass  # Noctalia can remove its own stale socket at startup.
            else:
                raise DesktopError('Another Noctalia IPC server already owns this display')
        owner = run(['busctl', '--address='+original_session, 'call', 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                     'org.freedesktop.DBus', 'NameHasOwner', 's', 'dev.noctalia.Mpris'], capture_output=True, text=True, timeout=4)
        if owner.stdout.strip() != 'b false':
            raise DesktopError('Another Noctalia media owner is already running')
        records = {'runner': identity(os.getpid()), 'niri': niri}
        for name, command in zip(('system_proxy', 'session_proxy'), proxy_commands(root, original_session, original_system)):
            socket_path = root/('system-bus' if name=='system_proxy' else 'session-bus')
            socket_path.unlink(missing_ok=True)
            with (root/(name+'.log')).open('a') as log:
                child = subprocess.Popen(command, stdout=log, stderr=log)
            children.append(child)
            records[name] = identity(child.pid)
            atomic_json(root/'processes.json', records)
            deadline = time.monotonic()+4
            while not socket_path.exists() and time.monotonic()<deadline:
                if child.poll() is not None:
                    raise DesktopError(name+' exited before it was ready')
                time.sleep(.025)
            if not socket_path.exists():
                raise DesktopError(name+' did not become ready')
            verify_proxy('unix:path='+str(socket_path), session=name=='session_proxy')
        system_address='unix:path='+str(root/'system-bus')
        session_address='unix:path='+str(root/'session-bus')
        env=shell_environment(value,session_address,system_address)
        with (root/'shell.log').open('a') as log:
            child=subprocess.Popen([value['binary']],env=env,stdout=log,stderr=log)
        children.append(child)
        records['shell']=identity(child.pid)
        atomic_json(root/'processes.json',records)
        atomic_json(root/'session.json',{**records, 'NIRI_SOCKET':os.environ['NIRI_SOCKET'],
                    'WAYLAND_DISPLAY':os.environ['WAYLAND_DISPLAY'],
                    'DBUS_SESSION_BUS_ADDRESS':session_address,'DBUS_SYSTEM_BUS_ADDRESS':system_address})
        published_session = True
        pidfds=[os.pidfd_open(p.pid) for p in children]
        readable,_,_=select.select(pidfds,[],[])
        if pidfds[-1] in readable:
            return children[-1].wait()
        raise DesktopError('A D-Bus safety proxy exited; stopping Noctalia')
    except InterruptedError:
        return 0
    finally:
        for number, handler in previous.items():
            signal.signal(number, signal.SIG_IGN)
        for child in reversed(children):
            stop_process(child)
        if published_session:
            (root/'session.json').unlink(missing_ok=True)
        for fd in pidfds:
            os.close(fd)
        os.close(lockfd)
        for number, handler in previous.items():
            signal.signal(number, handler)


def live_environment(value):
    niri=require_session()
    root=Path(value['live_root'])
    session=json.loads((root/'session.json').read_text())
    if (not all(alive(session.get(key)) for key in ('shell','runner','system_proxy','session_proxy'))
        or session.get('niri',{}).get('pid')!=niri['pid'] or session['niri'].get('start')!=niri['start']
        or session.get('NIRI_SOCKET')!=os.environ.get('NIRI_SOCKET')
        or session.get('WAYLAND_DISPLAY')!=os.environ.get('WAYLAND_DISPLAY')):
        raise DesktopError('Noctalia does not belong to the current main Niri session')
    expected_session='unix:path='+str(root/'session-bus')
    expected_system='unix:path='+str(root/'system-bus')
    if session.get('DBUS_SESSION_BUS_ADDRESS')!=expected_session or session.get('DBUS_SYSTEM_BUS_ADDRESS')!=expected_system:
        raise DesktopError('Invalid Moonlit safety proxy addresses')
    if peer_pid(str(noctalia_socket())) != session['shell']['pid']:
        raise DesktopError('Noctalia IPC belongs to another process')
    return shell_environment(value,expected_session,expected_system)


def ipc(value, arguments):
    result=run([value['binary'],'msg',*arguments],env=live_environment(value),
               capture_output=True,text=True,timeout=6)
    if result.stdout.lstrip().startswith('error:'):
        raise DesktopError(result.stdout.strip())
    return result.stdout


def dispatch(argv, value):
    if not argv:
        raise DesktopError('Provide a desktop action')
    if argv in (['shell'],['waybar']):
        return shell(value)
    if argv[0]=='launch':
        if len(argv)<3 or argv[1]!='--':
            raise DesktopError('Use launch -- application arguments')
        return host_launch(argv[2:])
    if argv[0]=='terminal':
        return terminal_launch(value,argv[1:])
    if argv==['session-start']:
        require_session()
        run(['systemctl','--user','daemon-reload'])
        run(['systemctl','--user','start',BAR_UNIT,*KEEP_UNITS])
        return 0
    if argv==['status']:
        state=json.loads(ipc(value,['status']))
        if not isinstance(state,dict) or not state:
            raise DesktopError('Noctalia returned invalid status')
        session=json.loads((Path(value['live_root'])/'session.json').read_text())
        print(json.dumps({'ready':True,'phase':value['phase'],
              'processes':{key:session[key] for key in ('runner','niri','shell','system_proxy','session_proxy')},
              'noctalia':state}))
        return 0
    mapping={('applications',):('panel-toggle','launcher'),('launcher',):('panel-toggle','launcher'),
             ('menu',):('panel-toggle','control-center'),('panel',):('panel-toggle','control-center'),
             ('bar','menu'):('settings-open','bar'),('wallpaper','choose'):('panel-toggle','wallpaper'),
             ('music',):('panel-toggle','dotfiles/moonlit-music:room'),
             ('music','room'):('panel-toggle','dotfiles/moonlit-music:room'),
             ('music','controls'):('panel-toggle','dotfiles/moonlit-music:controls')}
    if tuple(argv) in mapping:
        output=ipc(value,mapping[tuple(argv)])
        if output: print(output,end='' if output.endswith('\n') else '\n')
        return 0
    if argv[0]=='media':
        if len(argv)<2 or argv[1] not in ('toggle','next','previous','stop','seek','select','snapshot'):
            raise DesktopError('Unknown media action')
        expected=3 if argv[1] in ('seek','select') else 2
        if len(argv)!=expected:
            raise DesktopError('Incorrect media arguments')
        env=live_environment(value)
        bridge=Path(value['data_dir'])/'noctalia/plugins/moonlit-music/media_bridge.py'
        return subprocess.run(['/usr/bin/python3',str(bridge),*argv[1:]],env=env,check=False).returncode
    if argv==['wallpaper-run']:
        raise DesktopError('Noctalia owns wallpaper in this session; the old swaybg service must remain stopped')
    os.execv('/usr/bin/python3',['/usr/bin/python3',value['legacy_desktopctl'],*argv])
    return 0


def main():
    try:
        return dispatch(sys.argv[1:],read_manifest())
    except (DesktopError,OSError,ValueError,subprocess.SubprocessError) as error:
        print('Moonlit: '+str(error),file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
