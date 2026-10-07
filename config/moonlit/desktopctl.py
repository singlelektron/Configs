#!/usr/bin/env python3
"""Reversible Moonlit entry points and a guarded, main-session shell runner.

Deployment owns the manifest. This bridge never installs/enables a service and
keeps legacy lock, idle and presentation commands on their pinned helper.
Noctalia gets filtered D-Bus; devices and notifications require capabilities.
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
DEVICE_CAPABILITIES = frozenset(('audio', 'network', 'bluetooth', 'calendar', 'notifications', 'caffeine'))
KEEP_UNITS = tuple('dotfiles-niri-' + name + '.service' for name in ('mako', 'idle', 'session-events', 'polkit'))
MAKO_UNITS = ('dotfiles-niri-mako.service', 'mako.service')
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


def capabilities(value):
    selected = value.get('capabilities', [])
    if (not isinstance(selected, list) or any(not isinstance(item, str) for item in selected)
            or len(set(selected)) != len(selected) or not set(selected) <= DEVICE_CAPABILITIES):
        raise DesktopError('Unsupported Moonlit device capabilities')
    return frozenset(selected)


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
    capabilities(value)
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
    if 'calendar' in capabilities(value):
        if not isinstance(value.get('calendar_dir'),str):
            raise DesktopError('Calendar output must be the private live vdir directory')
        calendar = Path(value['calendar_dir'])
        expected_calendar = root/'data/noctalia/calendar-vdir'
        if (calendar != expected_calendar or calendar.resolve() != expected_calendar
                or not calendar.is_dir() or calendar.stat().st_uid != os.getuid()
                or calendar.stat().st_mode & 0o077):
            raise DesktopError('Calendar output must be the private live vdir directory')
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
               GSETTINGS_BACKEND='memory',
               MOONLIT_SESSION_MANIFEST=str(Path(value['release'])/'managed/niri/moonlit-session.json'),
               TERMINAL=shlex.join(['/usr/bin/python3',str(fixed_helper(value)),'terminal']))
    if 'audio' not in capabilities(value):
        env['PIPEWIRE_REMOTE'] = 'moonlit-basic-unavailable'
    if value.get('library_path'):
        env['LD_LIBRARY_PATH'] = value['library_path']
        # Packaged libqalculate otherwise looks in the system /usr/share.
        env.pop('QALCULATE_DEFINITIONS_DIR', None)
        definitions = Path(value['binary']).parent.parent/'share/qalculate'
        if definitions.is_dir():
            env['QALCULATE_DEFINITIONS_DIR'] = str(definitions)
    return env


def manager_environment():
    env = dict(os.environ)
    env.pop('DBUS_SESSION_BUS_ADDRESS', None)
    return env


def notification_mask_paths(value):
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    if runtime.is_symlink() or runtime.stat().st_uid != os.getuid():
        raise DesktopError('Invalid user runtime directory')
    return Path(value['live_root'])/'notification-mask.json', runtime/'systemd/user/mako.service'


def notifications_cleanup(value):
    """Also used by ExecStopPost after Niri is gone; never require its socket."""
    marker, target = notification_mask_paths(value)
    if not marker.exists():
        return
    if marker.is_symlink():
        raise DesktopError('Invalid notification mask ownership record')
    record = json.loads(marker.read_text())
    if record.get('release') != value['release'] or record.get('target') != str(target):
        raise DesktopError('Notification mask belongs to another release')
    changed = False
    if record.get('created'):
        candidate = Path(record['candidate'])
        if candidate.parent != target.parent or not candidate.name.startswith('.moonlit-mako-'):
            raise DesktopError('Invalid notification mask candidate')
        for path in (target, candidate):
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            # A changed mask belongs to whoever replaced it. Preserve it.
            if (stat.S_ISLNK(info.st_mode) and os.readlink(path) == '/dev/null'
                    and (info.st_dev, info.st_ino) == (record.get('device'), record.get('inode'))):
                path.unlink()
                changed = True
    marker.unlink()
    if changed:
        run(['systemctl','--user','daemon-reload'],env=manager_environment(),timeout=6)


def notifications_mask(value):
    if 'notifications' not in capabilities(value):
        raise DesktopError('Notification ownership has not been enabled')
    marker, target = notification_mask_paths(value)
    if marker.is_symlink():
        raise DesktopError('Invalid notification mask ownership record')
    if marker.exists():
        record = json.loads(marker.read_text())
        if (record.get('release') == value['release'] and record.get('target') == str(target)
                and target.is_symlink() and os.readlink(target) == '/dev/null'):
            info = target.lstat()
            if not record.get('created') or (info.st_dev, info.st_ino) == (record.get('device'), record.get('inode')):
                verify_notification_mask()
                return
        notifications_cleanup(value)
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if any(path.is_symlink() for path in (target.parent, target.parent.parent)):
        raise DesktopError('Refusing a symlinked user unit directory')
    record = {'release':value['release'],'target':str(target),'created':False}
    if target.is_symlink() and os.readlink(target) == '/dev/null':
        atomic_json(marker,record)  # Already masked by the user; never unmask it.
        run(['systemctl','--user','daemon-reload'],env=manager_environment(),timeout=6)
        verify_notification_mask()
        return
    if target.exists() or target.is_symlink():
        raise DesktopError('Refusing to replace an existing runtime mako unit')
    # Reserve the inode before publishing its ownership record, then link it
    # without replacement. ExecStopPost can recover any interrupted step.
    fd, name = tempfile.mkstemp(prefix='.moonlit-mako-',dir=target.parent)
    os.close(fd)
    candidate = Path(name)
    candidate.unlink()
    candidate.symlink_to('/dev/null')
    info = candidate.lstat()
    record.update(created=True,candidate=str(candidate),device=info.st_dev,inode=info.st_ino)
    atomic_json(marker,record)
    try:
        os.link(candidate,target,follow_symlinks=False)
        candidate.unlink()
        run(['systemctl','--user','daemon-reload'],env=manager_environment(),timeout=6)
        verify_notification_mask()
    except Exception:
        notifications_cleanup(value)
        raise


def verify_notification_mask():
    result = run(['systemctl','--user','show','mako.service','--property=LoadState','--value'],
                 env=manager_environment(),capture_output=True,text=True,timeout=4)
    if result.stdout.strip() != 'masked':
        raise DesktopError('The runtime mask is shadowed by another mako unit; refusing takeover')


def notification_owner(address):
    base = ['busctl','--auto-start=no','--address='+address,'call','org.freedesktop.DBus',
            '/org/freedesktop/DBus','org.freedesktop.DBus']
    result = run([*base,'NameHasOwner','s','org.freedesktop.Notifications'],capture_output=True,text=True,timeout=3)
    if result.stdout.strip() == 'b false':
        return None
    name = shlex.split(run([*base,'GetNameOwner','s','org.freedesktop.Notifications'],
                          capture_output=True,text=True,timeout=3).stdout)
    if len(name) != 2 or name[0] != 's' or not name[1].startswith(':'):
        raise DesktopError('Invalid notification owner reply')
    pid = run([*base,'GetConnectionUnixProcessID','s',name[1]],capture_output=True,text=True,timeout=3).stdout.split()
    if len(pid) != 2 or pid[0] != 'u' or int(pid[1]) <= 0:
        raise DesktopError('Invalid notification owner process reply')
    return {'name':name[1],'pid':int(pid[1])}


def notifications_prepare(value):
    if 'notifications' not in capabilities(value):
        raise DesktopError('Notification ownership has not been enabled')
    require_session()
    # Repeating session-start must preserve this exact release's live owner.
    # Validate its process identities, proxy paths and IPC peer before trusting it.
    try:
        live_environment(value)
        session = json.loads((Path(value['live_root'])/'session.json').read_text())
        already_running = notification_status(value,session)['ready']
    except (DesktopError,OSError,ValueError,subprocess.SubprocessError):
        already_running = False
    notifications_mask(value)
    if already_running:
        return
    try:
        env = manager_environment()
        address = 'unix:path='+str(Path(os.environ['XDG_RUNTIME_DIR'])/'bus')
        owner = notification_owner(address)
        if owner is None:
            return
        pids = {}
        for unit in MAKO_UNITS:
            result = run(['systemctl','--user','show',unit,'--property=MainPID','--value'],
                         env=env,capture_output=True,text=True,timeout=4)
            pids[unit] = int(result.stdout.strip())
        if owner['pid'] not in pids.values():
            raise DesktopError('Another notification daemon owns this session; refusing to replace it')
        archive = Path(value['live_root'])/'notification-archive'
        if archive.is_symlink():
            raise DesktopError('Refusing a symlinked notification archive')
        archive.mkdir(mode=0o700,exist_ok=True)
        archive.chmod(0o700)
        destination = Path(tempfile.mkdtemp(prefix=time.strftime('%Y%m%dT%H%M%S-'),dir=archive))
        env['DBUS_SESSION_BUS_ADDRESS'] = address
        for command in ('list','history'):
            result = run(['makoctl',command,'-j'],env=env,capture_output=True,text=True,timeout=5)
            json.loads(result.stdout)  # Preserve raw JSON, but reject a failed export.
            fd = os.open(destination/(command+'.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:
                stream.write(result.stdout)
        mode = run(['makoctl','mode'],env=env,capture_output=True,text=True,timeout=5).stdout
        fd = os.open(destination/'mode.txt',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            stream.write(mode)
        state_file = Path(value['live_root'])/'notification-state.json'
        if not state_file.exists():
            atomic_json(state_file,{'dnd':'do-not-disturb' in mode.split()})
        for unit, pid in pids.items():
            if pid:
                run(['systemctl','--user','stop',unit],env=env,timeout=10)
        if notification_owner(address) is not None:
            raise DesktopError('Notification owner changed during takeover')
    except Exception:
        notifications_cleanup(value)
        raise


def save_notification_dnd(value, env=None):
    if env is None:
        answer = ipc(value,['notification-dnd-status']).strip()
    else:
        answer = run([value['binary'],'msg','notification-dnd-status'],env=env,
                     capture_output=True,text=True,timeout=2).stdout.strip()
    if answer not in ('on','off'):
        raise DesktopError('Invalid notification DND state')
    atomic_json(Path(value['live_root'])/'notification-state.json',{'dnd':answer == 'on'})


def restore_mako_dnd(value):
    require_session()
    state = json.loads((Path(value['live_root'])/'notification-state.json').read_text())
    if not isinstance(state.get('dnd'),bool):
        raise DesktopError('Invalid notification DND recovery state')
    env = manager_environment()
    address = 'unix:path='+str(Path(os.environ['XDG_RUNTIME_DIR'])/'bus')
    deadline = time.monotonic()+5
    while True:
        owner = notification_owner(address)
        pids = [int(run(['systemctl','--user','show',unit,'--property=MainPID','--value'],
                        env=env,capture_output=True,text=True,timeout=4).stdout.strip()) for unit in MAKO_UNITS]
        if owner and owner['pid'] in pids:
            break
        if owner or time.monotonic() >= deadline:
            raise DesktopError('Refusing DND recovery on an unrelated or absent notification owner')
        time.sleep(.05)
    env['DBUS_SESSION_BUS_ADDRESS'] = address
    run(['makoctl','mode','-a' if state['dnd'] else '-r','do-not-disturb'],env=env,timeout=5)


def notification_status(value, session):
    if 'notifications' not in capabilities(value):
        return None
    address = 'unix:path='+str(Path(os.environ['XDG_RUNTIME_DIR'])/'bus')
    try:
        owner = notification_owner(address)
        if not owner or owner['pid'] != session['session_proxy']['pid']:
            return {'ready':False,'reason':'Noctalia does not own the notification service'}
        info = run(['busctl','--auto-start=no','--address='+address,'call',owner['name'],
                    '/org/freedesktop/Notifications','org.freedesktop.Notifications','GetServerInformation'],
                   capture_output=True,text=True,timeout=3)
        fields = shlex.split(info.stdout)
        ready = len(fields) == 5 and fields[:3] == ['ssss','noctalia','noctalia-dev']
        return {'ready':ready,'owner_pid':owner['pid'],'server':fields[1] if len(fields)>1 else ''}
    except (DesktopError,OSError,ValueError,subprocess.SubprocessError):
        return {'ready':False,'reason':'Notification owner validation failed'}


def presentation_lock():
    root = Path(os.environ['XDG_RUNTIME_DIR'])/'dotfiles-niri'
    if root.is_symlink():
        raise DesktopError('Refusing a symlinked presentation directory')
    root.mkdir(mode=0o700,exist_ok=True)
    fd = os.open(root/'moonlit-presentation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        return os.fdopen(fd,'w')
    except BaseException:
        os.close(fd)
        raise


def release_presentation(value):
    """Caller holds the flag lock. Recover only our reserved inode and idle."""
    marker = Path(value['live_root'])/'presentation-owner.json'
    flag = Path(os.environ['XDG_RUNTIME_DIR'])/'dotfiles-niri/presentation'
    if not marker.exists():
        return
    if marker.is_symlink():
        raise DesktopError('Invalid presentation ownership record')
    record = json.loads(marker.read_text())
    candidate = Path(record['candidate'])
    if (record.get('release') != value['release'] or record.get('target') != str(flag)
            or candidate.parent != flag.parent or not candidate.name.startswith('.moonlit-presentation-')):
        raise DesktopError('Invalid presentation ownership record')
    def owned(path):
        try:
            info = path.lstat()
            return stat.S_ISREG(info.st_mode) and (info.st_dev,info.st_ino) == (record.get('device'),record.get('inode'))
        except FileNotFoundError:
            return False
    flag_owned, pending = owned(flag), owned(candidate)
    # An interrupted stop before publication is recoverable. A replaced or
    # externally removed published flag no longer authorizes starting idle.
    if (flag_owned or (pending and not flag.exists() and not flag.is_symlink())) and alive(record.get('niri')):
        pid = run(['systemctl','--user','show','niri.service','--property=MainPID','--value'],
                  env=manager_environment(),capture_output=True,text=True,timeout=4).stdout.strip()
        if pid == str(record['niri']['pid']):
            run(['systemctl','--user','start','dotfiles-niri-idle.service'],env=manager_environment(),timeout=8)
    for path in (flag,candidate):
        if owned(path): path.unlink()
    marker.unlink()


def presentation_cleanup(value):
    # ExecStopPost may run after the compositor/socket disappeared.
    with presentation_lock():
        release_presentation(value)


def presentation(value, action):
    if action not in ('status','on','off','toggle'):
        raise DesktopError('Unknown keep-awake action')
    env = manager_environment()
    env.pop('DBUS_SYSTEM_BUS_ADDRESS',None)
    legacy = ['/usr/bin/python3',value['legacy_desktopctl'],'presentation']
    if action == 'status':
        return run([*legacy,'status'],env=env,timeout=5).returncode
    niri = require_session()
    flag = Path(os.environ['XDG_RUNTIME_DIR'])/'dotfiles-niri/presentation'
    marker = Path(value['live_root'])/'presentation-owner.json'
    with presentation_lock():
        if flag.is_symlink():
            raise DesktopError('Refusing a symlinked presentation flag')
        enabled = flag.exists()
        desired = not enabled if action == 'toggle' else action == 'on'
        if not desired:
            release_presentation(value)
            if flag.exists():  # Explicit user action keeps legacy flag semantics.
                run([*legacy,'off'],env=env,timeout=10)
        elif not enabled:
            release_presentation(value)
            state = run(['systemctl','--user','show','dotfiles-niri-idle.service','--property=ActiveState','--value'],
                        env=env,capture_output=True,text=True,timeout=4).stdout.strip()
            if state != 'active':
                raise DesktopError('Keep awake requires the existing idle service to be active')
            fd,name = tempfile.mkstemp(prefix='.moonlit-presentation-',dir=flag.parent)
            candidate = Path(name)
            with os.fdopen(fd,'w') as stream: stream.write('on\n')
            info = candidate.stat()
            atomic_json(marker,{'release':value['release'],'target':str(flag),'candidate':str(candidate),
                                'device':info.st_dev,'inode':info.st_ino,'niri':niri})
            try:
                run(['systemctl','--user','stop','dotfiles-niri-idle.service'],env=env,timeout=8)
                os.link(candidate,flag,follow_symlinks=False)
                candidate.unlink()
                run(['niri','msg','action','power-on-monitors'],env=env,timeout=5)
            except BaseException:
                release_presentation(value)
                raise
    try:
        ipc(value,['plugin','dotfiles/moonlit-controls:awake','all','refresh'])
    except (DesktopError,OSError,ValueError,subprocess.SubprocessError):
        pass  # The backend succeeded; panel reload also reads the real flag.
    return 0


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


def proxy_commands(root, session_address, system_address, allowed=frozenset()):
    allowed = capabilities({'capabilities':list(allowed)})
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
    if 'network' in allowed:
        # TALK also permits NetworkManager's callbacks to the secret agent.
        system += ['--talk=org.freedesktop.NetworkManager']
    if 'bluetooth' in allowed:
        # Native BlueZ startup reconnects paired, trusted devices automatically.
        # This capability explicitly permits that behavior and pairing callbacks.
        system += ['--talk=org.bluez']
    session = ['xdg-dbus-proxy', session_address, str(root/'session-bus'), '--filter', '--log',
               '--own=dev.noctalia.Mpris', '--own=dev.noctalia.Debug', '--see=org.mpris.MediaPlayer2.*',
               '--broadcast=org.mpris.MediaPlayer2.*=*', '--see=org.freedesktop.Notifications',
               '--see=org.freedesktop.ScreenSaver']
    if 'notifications' in allowed:
        session.append('--own=org.freedesktop.Notifications')
    session += ['--call=org.mpris.MediaPlayer2.*=' + method + '@/org/mpris/MediaPlayer2' for method in READ_INTERFACES[:2]]
    # Native repeat/shuffle controls write player properties, not PipeWire or
    # system devices. Keep that permission confined to the standard MPRIS path.
    session += ['--call=org.mpris.MediaPlayer2.*=org.freedesktop.DBus.Properties.Set@/org/mpris/MediaPlayer2']
    session += ['--call=org.mpris.MediaPlayer2.*=org.mpris.MediaPlayer2.Player.' + method + '@/org/mpris/MediaPlayer2'
                for method in ('Play', 'Pause', 'PlayPause', 'Stop', 'Next', 'Previous', 'Seek', 'SetPosition')]
    # ScreenSaver and StatusNotifierWatcher remain outside this shell's scope.
    return system, session


def verify_proxy(address, session=False):
    if session:
        args = ['org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'RequestName',
                'su', f'org.freedesktop.ScreenSaver.MoonlitDeniedProbe.p{os.getpid()}_{time.monotonic_ns()}', '4']
    else:
        # Device capabilities never grant login/session writes. The nonexistent
        # object and property also make this harmless if filtering was broken.
        args = ['org.freedesktop.login1', '/org/freedesktop/login1/moonlit_denied_probe',
                'org.freedesktop.DBus.Properties', 'Set', 'ssv',
                'org.freedesktop.login1.Manager', 'MoonlitDeniedProbe', 'b', 'false']
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


def calendar_command(value):
    return ['/usr/bin/python3',str(Path(value['release'])/'source/config/moonlit/calendar_bridge.py'),
            '--output',value['calendar_dir'],'--parent',str(os.getpid())]


def calendar_status(value, session):
    if 'calendar' not in capabilities(value):
        return None
    running = alive(session.get('calendar_bridge'))
    result = {'running':running,'ready':False,'degraded':False}
    try:
        state = json.loads((Path(value['calendar_dir'])/'status.json').read_text())
        if not isinstance(state,dict):
            raise ValueError('Invalid calendar bridge status')
        for key in ('source_count','event_count','component_count','error_count','updated_at','degraded'):
            if key in state: result[key] = state[key]
        result['ready'] = running and state.get('ready') is True
    except (OSError,ValueError,TypeError):
        result['reason'] = 'Waiting for the calendar bridge status'
    if not running:
        result['reason'] = 'Calendar bridge stopped; restart the shell to reconnect. See calendar_bridge.log'
    return result


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
    calendar_child = None
    published_session = False
    notifications_prepared = False
    presentation_started = False
    def interrupted(_number, _frame):
        raise InterruptedError('Moonlit runner stopped')
    previous = {number: signal.signal(number, interrupted) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        existing = json.loads((root/'processes.json').read_text()) if (root/'processes.json').exists() else {}
        if any(alive(existing.get(key)) for key in ('runner', 'shell', 'system_proxy', 'session_proxy', 'calendar_bridge')):
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
        if 'caffeine' in capabilities(value):
            presentation_cleanup(value)
            presentation_started = True
        if 'notifications' in capabilities(value):
            notifications_prepare(value)
            notifications_prepared = True
        records = {'runner': identity(os.getpid()), 'niri': niri}
        for name, command in zip(('system_proxy', 'session_proxy'),
                                 proxy_commands(root, original_session, original_system, capabilities(value))):
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
        if 'calendar' in capabilities(value):
            # Only this read-only EDS adapter gets the genuine session bus. It
            # owns no EDS process; Noctalia keeps using its filtered bus below.
            calendar_env = dict(os.environ)
            calendar_env['DBUS_SESSION_BUS_ADDRESS'] = original_session
            (Path(value['calendar_dir'])/'status.json').unlink(missing_ok=True)
            with (root/'calendar_bridge.log').open('a') as log:
                calendar_child = subprocess.Popen(calendar_command(value),env=calendar_env,stdout=log,stderr=log)
            children.append(calendar_child)
            records['calendar_bridge'] = identity(calendar_child.pid)
            atomic_json(root/'processes.json',records)
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
        if 'notifications' in capabilities(value):
            state_file = root/'notification-state.json'
            dnd = json.loads(state_file.read_text()).get('dnd',False) if state_file.exists() else False
            if not isinstance(dnd,bool):
                raise DesktopError('Invalid notification DND state')
            deadline = time.monotonic()+8
            while True:
                try:
                    ipc(value,['notification-dnd-set','on' if dnd else 'off'])
                    break
                except (DesktopError,OSError,subprocess.SubprocessError):
                    if time.monotonic() >= deadline or child.poll() is not None:
                        raise DesktopError('Noctalia could not restore notification DND')
                    time.sleep(.05)
        pidfds=[os.pidfd_open(p.pid) for p in children]
        calendar_fd = pidfds[children.index(calendar_child)] if calendar_child else None
        shell_fd = pidfds[-1]
        while True:
            readable,_,_=select.select(pidfds,[],[])
            if shell_fd in readable:
                return children[-1].wait()
            if any(fd in readable for fd in pidfds[:2]):
                raise DesktopError('A D-Bus safety proxy exited; stopping Noctalia')
            if calendar_fd in readable:
                code = calendar_child.wait()
                print(f'Moonlit calendar bridge exited ({code}); shell remains running. '
                      'See calendar_bridge.log; restart the shell to reconnect.',file=sys.stderr,flush=True)
                pidfds.remove(calendar_fd)
                os.close(calendar_fd)
                calendar_fd = None
    except InterruptedError:
        return 0
    finally:
        for number, handler in previous.items():
            signal.signal(number, signal.SIG_IGN)
        if published_session and 'notifications' in capabilities(value):
            try:
                save_notification_dnd(value,env)
            except (DesktopError,OSError,ValueError,subprocess.SubprocessError):
                pass  # Retain the last validated state if the shell already died.
        for child in reversed(children):
            stop_process(child)
        if notifications_prepared:
            try:
                notifications_cleanup(value)
            except (DesktopError,OSError,ValueError,subprocess.SubprocessError) as error:
                print('Moonlit notification mask cleanup needs attention: '+str(error),file=sys.stderr)
        if presentation_started:
            try:
                presentation_cleanup(value)
            except (DesktopError,OSError,ValueError,subprocess.SubprocessError) as error:
                print('Moonlit presentation cleanup needs attention: '+str(error),file=sys.stderr)
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
    if argv==['notifications-cleanup']:
        notifications_cleanup(value)
        return 0
    if argv==['presentation-cleanup']:
        presentation_cleanup(value)
        return 0
    if argv[0]=='presentation' and 'caffeine' in capabilities(value):
        if len(argv) != 2:
            raise DesktopError('Provide one keep-awake action')
        return presentation(value,argv[1])
    if argv==['notifications-mask']:
        require_session()
        notifications_mask(value)
        return 0
    if argv==['notifications-prepare']:
        notifications_prepare(value)
        return 0
    if argv==['notifications-restore-dnd']:
        restore_mako_dnd(value)
        return 0
    if argv==['notifications','toggle']:
        if 'notifications' in capabilities(value):
            ipc(value,['notification-dnd-toggle'])
            save_notification_dnd(value)
            return 0
        require_session()
        return run(['makoctl','mode','-t','do-not-disturb'],env=manager_environment(),timeout=5).returncode
    if argv==['session-start']:
        require_session()
        if 'notifications' in capabilities(value):
            notifications_prepare(value)
        run(['systemctl','--user','daemon-reload'])
        kept = [unit for unit in KEEP_UNITS if 'notifications' not in capabilities(value) or unit not in MAKO_UNITS]
        if 'caffeine' in capabilities(value) and (Path(os.environ['XDG_RUNTIME_DIR'])/'dotfiles-niri/presentation').exists():
            try:
                live_environment(value)
            except (DesktopError,OSError,ValueError,subprocess.SubprocessError):
                pass  # A new runner clears its old lease; normal idle startup follows.
            else:
                kept.remove('dotfiles-niri-idle.service')
        run(['systemctl','--user','start',BAR_UNIT,*kept])
        return 0
    if argv==['status']:
        state=json.loads(ipc(value,['status']))
        if not isinstance(state,dict) or not state:
            raise DesktopError('Noctalia returned invalid status')
        session=json.loads((Path(value['live_root'])/'session.json').read_text())
        calendar=calendar_status(value,session)
        notifications=notification_status(value,session)
        processes={key:session[key] for key in ('runner','niri','shell','system_proxy','session_proxy','calendar_bridge') if key in session}
        print(json.dumps({'ready':(calendar is None or calendar['ready']) and (notifications is None or notifications['ready']),
              'phase':value['phase'],'capabilities':sorted(capabilities(value)),'processes':processes,
              'calendar':calendar,'notifications':notifications,'noctalia':state}))
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
