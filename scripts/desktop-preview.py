#!/usr/bin/env python3
"""Disposable native Noctalia + nested Niri preview; never deploy to the user's home.

The shell owns a private session bus and reads system devices through a mandatory
method-filtered D-Bus proxy. Network/Bluetooth/power writes are denied. PipeWire
audio is real: volume and routing gestures affect the current audio session.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib

REPO = Path(__file__).resolve().parents[1]
MARKER = "moonlit-disposable-preview-v1"
DEFAULT_BINARY = REPO / "local/noctalia-5.2.1/prefix/usr/bin/noctalia"
PRIVATE_BUS_CONFIG = '''<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <keep_umask/>
  <listen>unix:tmpdir=/tmp</listen>
  <auth>EXTERNAL</auth>
  <!-- No service directories: do not auto-start a keyring, notifications or portals. -->
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
'''
SYSTEM_READ_METHODS = {
    "org.freedesktop.NetworkManager": (
        "org.freedesktop.NetworkManager.GetDevices", "org.freedesktop.NetworkManager.GetAllDevices",
        "org.freedesktop.NetworkManager.GetDeviceByIpIface", "org.freedesktop.NetworkManager.GetPermissions",
        "org.freedesktop.NetworkManager.Device.Wireless.GetAccessPoints",
        "org.freedesktop.NetworkManager.Device.Wireless.GetAllAccessPoints",
        "org.freedesktop.NetworkManager.Settings.ListConnections",
        "org.freedesktop.NetworkManager.Settings.Connection.GetSettings"),
    "org.bluez": (),
    "org.freedesktop.UPower": ("org.freedesktop.UPower.EnumerateDevices",
                              "org.freedesktop.UPower.GetDisplayDevice",
                              "org.freedesktop.UPower.EnumerateKbdBacklights"),
    "org.freedesktop.login1": ("org.freedesktop.login1.Manager.GetSession",
                              "org.freedesktop.login1.Manager.GetSessionByPID",
                              "org.freedesktop.login1.Manager.ListSessions",
                              "org.freedesktop.login1.Manager.ListInhibitors"),
}
COMMON_READ_METHODS = ("org.freedesktop.DBus.Properties.Get", "org.freedesktop.DBus.Properties.GetAll",
                       "org.freedesktop.DBus.ObjectManager.GetManagedObjects",
                       "org.freedesktop.DBus.Introspectable.Introspect")


def proxy_command(root, address):
    if not shutil.which("xdg-dbus-proxy"):
        raise PreviewError("xdg-dbus-proxy is required; refusing an unfiltered system bus")
    command = ["xdg-dbus-proxy", address, str(root / "system-bus"), "--filter", "--log"]
    for name, methods in SYSTEM_READ_METHODS.items():
        command.append("--see=" + name)
        command.extend("--call=" + name + "=" + method for method in COMMON_READ_METHODS + methods)
        # Receiving state-change signals grants no permission to send method calls.
        command.append("--broadcast=" + name + "=*")
    return command


class PreviewError(RuntimeError):
    pass


def write_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".preview-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def safe_root(path, create=False):
    path = Path(os.path.abspath(path.expanduser()))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise PreviewError("Preview path must not contain symlinks")
    for protected in (Path.home(), REPO, Path("/"), Path("/tmp")):
        if path == protected or path in protected.parents:
            raise PreviewError("Refusing protected preview directory")
    for protected in (Path.home() / ".config", Path.home() / ".local", REPO):
        if protected in path.parents:
            raise PreviewError("Preview must stay outside user configuration and repository directories")
    if path.exists():
        if path.stat().st_uid != os.getuid():
            raise PreviewError("Preview directory belongs to another user")
        if not (path / ".preview-owner").is_file():
            raise PreviewError("Existing directory is not owned by this preview")
        if (path / ".preview-owner").read_text().strip() != MARKER:
            raise PreviewError("Invalid preview ownership marker")
    elif create:
        path.mkdir(parents=True, mode=0o700)
        (path / ".preview-owner").write_text(MARKER + "\n")
    else:
        raise PreviewError("Prepare the preview directory first")
    return path


def proc_identity(pid):
    """Linux start ticks distinguish an owned process from a recycled PID."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        fields = stat[stat.rfind(")") + 2:].split()
        if Path(f"/proc/{pid}").stat().st_uid != os.getuid():
            return None
        return {"pid": int(pid), "start": int(fields[19]), "ppid": int(fields[1]),
                "session": int(fields[3]), "state": fields[0]}
    except (OSError, ValueError, IndexError):
        return None


def alive(identity):
    current = proc_identity(identity["pid"]) if identity else None
    return bool(current and current["start"] == identity["start"] and current["state"] != "Z")


def signal_owned(identity, number):
    """Use a pidfd where available; recheck identity before signalling."""
    if not alive(identity):
        return False
    try:
        fd = os.pidfd_open(identity["pid"])
    except (AttributeError, OSError):
        raise PreviewError("pidfd_open is required for safe preview cleanup")
    try:
        if not alive(identity):
            return False
        signal.pidfd_send_signal(fd, number)
        return True
    except ProcessLookupError:
        return False
    finally:
        os.close(fd)


def state(root):
    try:
        return json.loads((root / "processes.json").read_text())
    except (OSError, ValueError):
        return {}


def registered_processes(root):
    """Include the explicitly retained diagnostic player, which has its own session."""
    values = state(root)
    try:
        player = json.loads((root / "media-validation/player.json").read_text())
        # A player retained for another preview is not ours to stop. Only PID and
        # birth ticks are needed; the test's `session` field is its session.json path.
        if (Path(player["session"]).expanduser().absolute() == root / "session.json"
                and isinstance(player["pid"], int) and isinstance(player["start"], int)):
            values["retained_player"] = {"pid": player["pid"], "start": player["start"]}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return values


def profile(root):
    return json.loads((root / "profile.json").read_text())


def materialize_links(config):
    """Unlink only disposable deployment links, then copy their source contents."""
    for directory, dirs, files in os.walk(config, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if not path.is_symlink():
                continue
            source = path.resolve(strict=True)
            if REPO not in source.parents:
                raise PreviewError("Disposable deployment points outside the repository")
            path.unlink()
            if source.is_dir():
                shutil.copytree(source, path, symlinks=False)
            else:
                shutil.copy2(source, path)


def safety_config(wallpapers=None, key_file=None):
    text = '''# Generated isolation overrides; never copy into the user's profile.
[shell]
polkit_agent = false
offline_mode = true
telemetry_enabled = false
screen_time_enabled = false
clipboard_enabled = false
[shell.greeter_sync]
auto_sync = false
[theme.templates]
enable_builtin_templates = false
enable_community_templates = false
builtin_ids = []
community_ids = []
[lockscreen]
enabled = false
lock_before_suspend = false
[notification]
enable_daemon = false
[shell.session]
actions = [
  { action = "lock", label = "Lock · unavailable in preview", command = "/usr/bin/true", enabled = false },
  { action = "logout", label = "Log out · unavailable in preview", command = "/usr/bin/true", enabled = false },
  { action = "suspend", label = "Suspend · unavailable in preview", command = "/usr/bin/true", enabled = false },
  { action = "lock_and_suspend", command = "/usr/bin/true", enabled = false },
  { action = "reboot", label = "Restart · unavailable in preview", command = "/usr/bin/true", enabled = false },
  { action = "shutdown", label = "Shut down · unavailable in preview", command = "/usr/bin/true", enabled = false }
]
[shell.session.power]
suspend = "/usr/bin/true"
reboot = "/usr/bin/true"
shutdown = "/usr/bin/true"
[idle.behavior.lock]
enabled = false
[idle.behavior.lock-and-suspend]
enabled = false
[idle.behavior.screen-off]
enabled = false
[weather]
enabled = false
[wallpaper.automation]
enabled = false
[hooks]
started = []
logging_out = []
rebooting = []
shutting_down = []
'''
    if wallpapers:
        text += "\n[wallpaper]\ndirectory = " + json.dumps(str(wallpapers)) + "\n"
    if key_file:
        text += '\n[storage]\nkey_source = "file"\nkey_file = ' + json.dumps(str(key_file)) + '\n'
    return text


def prepare(root, binary, library_path=None, wallpapers=None):
    root = safe_root(root, create=True)
    if any(alive(v) for v in registered_processes(root).values() if isinstance(v, dict) and "pid" in v):
        raise PreviewError("Stop the running preview before preparing it again")
    binary = binary.expanduser().resolve(strict=True)
    if not os.access(binary, os.X_OK):
        raise PreviewError("Noctalia binary is not executable")
    if wallpapers:
        wallpapers = wallpapers.expanduser().resolve(strict=True)
        if not wallpapers.is_dir():
            raise PreviewError("Wallpapers must be a directory")
    library_path = library_path or str(binary.parents[1] / "lib")
    home = root / "home"
    # First preparation uses the project's recoverable deployment path. Repeated
    # prepares reuse those disposable files instead of backing up our own copies.
    if not (root / "profile.json").exists():
        subprocess.run([sys.executable, str(REPO / "scripts/deploy.py"), "--home", str(home),
                        "--desktop", "niri", "--apply"], check=True, capture_output=True, text=True)
        materialize_links(home / ".config")
    for child in ("bin", "screenshots", "config/noctalia", "state/noctalia", "data", "cache"):
        (root / child).mkdir(parents=True, exist_ok=True)
    source = REPO / "config/moonlit"
    settings = source / "settings.toml"
    if not settings.is_file():
        raise PreviewError("Missing config/moonlit/settings.toml")
    tomllib.loads(settings.read_text())
    shutil.copy2(settings, root / "config/noctalia/settings.toml")
    for name in ("palettes",):
        if (source / name).is_dir():
            shutil.copytree(source / name, root / "config/noctalia" / name, dirs_exist_ok=True)
    if (source / "plugins").is_dir():
        shutil.copytree(source / "plugins", root / "data/noctalia/plugins", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    key_file = root / "state/storage-key"
    if not key_file.exists():
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(os.urandom(32).hex() + "\n")
    (root / "config/noctalia/zz-preview-safety.toml").write_text(safety_config(wallpapers, key_file))
    (root / "dbus-session.conf").write_text(PRIVATE_BUS_CONFIG)
    # Reset only this preview's generated state so it cannot outrank safety.
    (root / "state/noctalia/settings.toml").unlink(missing_ok=True)
    niri = (source / "niri-preview.kdl").read_text()
    niri = niri.replace('screenshot-path "preview-%Y-%m-%d_%H-%M-%S.png"',
                        "screenshot-path " + json.dumps(str(root / "screenshots/%Y-%m-%d_%H-%M-%S.png")))
    if (source / "niri-theme.kdl").is_file():
        shutil.copy2(source / "niri-theme.kdl", home / ".config/niri/moonlit-theme.kdl")
        niri += '\ninclude "moonlit-theme.kdl"\n'
    for theme in ("kitty-theme.conf", "kitty.conf"):
        if (source / theme).is_file():
            destination = home / ".config/kitty" / ("theme.conf" if theme == "kitty-theme.conf" else theme)
            shutil.copy2(source / theme, destination)
    if (source / "nvim-theme.lua").is_file():
        nvim = home / ".config/nvim"
        shutil.copy2(source / "nvim-theme.lua", nvim / "moonlit-theme.lua")
        init = nvim / "init.lua"
        include = '\n-- Isolated Moonlit preview palette.\ndofile(vim.fn.stdpath("config") .. "/moonlit-theme.lua")\n'
        current = init.read_text()
        if include not in current:
            init.write_text(current + include)
    bridge = root / "data/noctalia/plugins/moonlit-music/media_bridge.py"
    if bridge.is_file():
        for key, action in (("XF86AudioPlay", "toggle"), ("XF86AudioNext", "next"), ("XF86AudioPrev", "previous")):
            old = next((line for line in niri.splitlines() if line.strip().startswith(key + " ")), None)
            if old:
                niri = niri.replace(old, '    ' + key + ' allow-when-locked=true { spawn "/usr/bin/python3" '
                                    + json.dumps(str(bridge)) + ' ' + json.dumps(action) + '; }')
    (home / ".config/niri/config.kdl").write_text(niri)
    wrapper = root / "bin/noctalia"
    wrapper.write_text("#!/usr/bin/python3\nimport os,sys\nos.environ['LD_LIBRARY_PATH'] = "
                       + repr(library_path) + "\nos.execv(" + repr(str(binary)) + ", ["
                       + repr(str(binary)) + "] + sys.argv[1:])\n")
    wrapper.chmod(0o700)
    write_json(root / "profile.json", {"repo": str(REPO), "binary": str(binary),
               "library_path": library_path, "wallpapers": str(wallpapers) if wallpapers else None})
    subprocess.run(["niri", "validate", "--config", str(home / ".config/niri/config.kdl")],
                   check=True, capture_output=True, text=True)
    return root


def preview_environment(root):
    env = dict(os.environ)
    # HOME remains the real home; the explicit XDG roots contain disposable state.
    env.update(XDG_CONFIG_HOME=str(root / "home/.config"), XDG_STATE_HOME=str(root / "home/.local/state"),
               XDG_DATA_HOME=str(root / "home/.local/share"), XDG_CACHE_HOME=str(root / "cache"),
               NOCTALIA_CONFIG_HOME=str(root / "config"), NOCTALIA_STATE_HOME=str(root / "state"),
               NOCTALIA_DATA_HOME=str(root / "data"), GSETTINGS_BACKEND="memory",
               PATH=str(root / "bin") + os.pathsep + env.get("PATH", os.defpath),
               MOONLIT_PREVIEW="1", DOTFILES_NVIM_NO_PLUGINS="1")
    env.pop("NIRI_SOCKET", None)
    env.pop("NIRI_CONFIG", None)
    env.pop("GNOME_KEYRING_CONTROL", None)
    env.pop("GNOME_KEYRING_PID", None)
    return env


def start(root):
    root = safe_root(root)
    if any(alive(v) for v in registered_processes(root).values() if isinstance(v, dict) and "pid" in v):
        raise PreviewError("Preview has running owned processes; run stop before starting it again")
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise PreviewError("A host Wayland session is required for a nested preview")
    proxy_command(root, os.environ.get("DBUS_SYSTEM_BUS_ADDRESS", "unix:path=/run/dbus/system_bus_socket"))
    command = [sys.executable, str(REPO / "scripts/desktop-preview.py"), "_supervise", "--runtime", str(root)]
    env = preview_environment(root)
    env.pop("MOONLIT_HOST_DBUS_ADDRESS", None)
    with (root / "preview.log").open("a") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=log,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
    write_json(root / "processes.json", {"supervisor": proc_identity(process.pid)})
    deadline = time.monotonic() + 18
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise PreviewError("Nested Niri exited; inspect " + str(root / "preview.log"))
        if (root / "session.json").is_file() and alive(state(root).get("shell")):
            return status(root)
        time.sleep(0.1)
    raise PreviewError("Preview startup timed out; status/logs retained for cleanup")


def supervise(root):
    root = safe_root(root)
    address = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS", "unix:path=/run/dbus/system_bus_socket")
    socket_path = root / "system-bus"
    if socket_path.exists():
        socket_path.unlink()
    processes = []
    try:
        with (root / "system-proxy.log").open("a") as log:
            proxy = subprocess.Popen(proxy_command(root, address), stdout=log, stderr=log)
        processes.append(proxy)
        # Parent registers its supervisor immediately after Popen; keep this child
        # registration sequential so neither writer can discard the proxy identity.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if proxy.poll() is not None:
                raise PreviewError("System bus proxy exited; refusing to launch Noctalia")
            if socket_path.exists() and state(root).get("supervisor"):
                break
            time.sleep(0.05)
        if not socket_path.exists():
            raise PreviewError("System bus proxy did not become ready")
        values = state(root)
        values["proxy"] = proc_identity(proxy.pid)
        write_json(root / "processes.json", values)
        proxy_address = "unix:path=" + str(socket_path)
        probe = subprocess.run(["busctl", "--address=" + proxy_address, "call", "org.bluez",
                                "/org/bluez/moonlit_denied_probe", "org.bluez.Device1", "Connect"],
                               capture_output=True, text=True, timeout=4)
        # An impossible path makes this check harmless even under a broken rule.
        if probe.returncode == 0 or not any(s in probe.stderr.lower() for s in ("accessdenied", "not allowed", "denied")):
            raise PreviewError("System bus proxy did not deny Connect; refusing to launch Noctalia: " + probe.stderr.strip())
        write_json(root / "proxy-verification.json", {"connect_denied": True, "probe": probe.stderr.strip()})
        env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=proxy_address)
        command = ["dbus-run-session", "--config-file", str(root / "dbus-session.conf"), "--", "niri",
                   "--config", str(root / "home/.config/niri/config.kdl"), "--", sys.executable,
                   str(REPO / "scripts/desktop-preview.py"), "_child", "--runtime", str(root)]
        desktop = subprocess.Popen(command, env=env)
        processes.append(desktop)
        values = state(root)
        values["desktop"] = proc_identity(desktop.pid)
        write_json(root / "processes.json", values)
        return desktop.wait()
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)


def child(root):
    root = safe_root(root)
    # Niri supplies these child-only sockets; IPC and screenshots never use the
    # host compositor's socket. Private DBus cannot replace its notification daemon.
    needed = ("NIRI_SOCKET", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")
    if not all(os.environ.get(key) for key in needed):
        raise PreviewError("Preview child must be launched by nested Niri")
    write_json(root / "session.json", {key: os.environ[key] for key in (*needed, "XDG_RUNTIME_DIR", "DBUS_SYSTEM_BUS_ADDRESS")})
    process = subprocess.Popen([str(root / "bin/noctalia")])
    values = state(root)
    values.update(child=proc_identity(os.getpid()), shell=proc_identity(process.pid))
    write_json(root / "processes.json", values)
    return process.wait()


def nested_environment(root):
    if not alive(state(root).get("supervisor")):
        raise PreviewError("Preview is not running")
    env = preview_environment(root)
    env.update(json.loads((root / "session.json").read_text()))
    return env


def owned_processes(values):
    leader = values.get("supervisor")
    registered = [v for v in values.values() if isinstance(v, dict) and "pid" in v and alive(v)]
    if not alive(leader):
        return registered
    identities = [identity for entry in Path("/proc").iterdir() if entry.name.isdigit()
                  if (identity := proc_identity(int(entry.name))) is not None]
    births = {(p["pid"], p["start"]) for p in registered}
    selected = {p["pid"] for p in identities if (p["pid"], p["start"]) in births}
    leader_is_current = any(p["pid"] == leader["pid"] and p["start"] == leader["start"] for p in identities)
    for _ in identities:
        extra = {p["pid"] for p in identities if p["ppid"] in selected or
                 (leader_is_current and p["session"] == leader["pid"] and p["start"] >= leader["start"])}
        if extra <= selected:
            break
        selected |= extra
    # Descendants first, supervisor last, each guarded by PID + start ticks.
    return sorted((p for p in identities if p["pid"] in selected),
                  key=lambda p: (p["pid"] != leader["pid"], p["start"]), reverse=True)


def stop(root):
    root = safe_root(root)
    processes = owned_processes(registered_processes(root))
    for process in processes:
        signal_owned(process, signal.SIGTERM)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(alive(p) for p in processes):
        time.sleep(0.05)
    for process in processes:
        if alive(process):
            signal_owned(process, signal.SIGKILL)
    (root / "session.json").unlink(missing_ok=True)
    return {"stopped_owned_processes": len(processes), "runtime": str(root)}


def status(root):
    root = safe_root(root)
    values = registered_processes(root)
    result = {"runtime": str(root), "running": alive(values.get("supervisor")),
              "processes": {k: {**v, "alive": alive(v)} for k, v in values.items() if isinstance(v, dict)},
              "log": str(root / "preview.log"), "bus": "private",
              "system_devices": "real read-only through method-filtered proxy", "audio": "real writable PipeWire",
              "session_actions": "disabled"}
    if result["running"] and (root / "session.json").is_file():
        command = subprocess.run(["niri", "msg", "--json", "outputs"],
                                 env=nested_environment(root), capture_output=True, text=True, timeout=3)
        if command.returncode == 0:
            result["outputs"] = json.loads(command.stdout)
    return result


def capture(root, output):
    root = safe_root(root)
    output = output.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["niri", "msg", "action", "screenshot-screen", "--show-pointer", "false", "--path", str(output)],
                   env=nested_environment(root), check=True, capture_output=True, text=True, timeout=10)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline and not output.is_file():
        time.sleep(0.05)
    from PIL import Image
    with Image.open(output) as image:
        dimensions = list(image.size)
        image.verify()
    return {"path": str(output), "pixels": dimensions,
            "kind": "native nested-Niri capture", "physical_4k_acceptance": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "start", "status", "stop", "capture", "_child", "_supervise"))
    parser.add_argument("--runtime", type=Path, default=Path(f"/tmp/moonlit-preview-{os.getuid()}"))
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--library-path")
    parser.add_argument("--wallpapers", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = {"prepared": str(prepare(args.runtime, args.binary, args.library_path, args.wallpapers))}
        elif args.action == "start":
            result = start(args.runtime)
        elif args.action == "stop":
            result = stop(args.runtime)
        elif args.action == "status":
            result = status(args.runtime)
        elif args.action == "capture":
            if not args.output:
                parser.error("capture requires --output")
            result = capture(args.runtime, args.output)
        elif args.action == "_supervise":
            return supervise(args.runtime)
        else:
            return child(args.runtime)
        print(json.dumps(result, indent=2))
        return 0
    except (PreviewError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("Preview: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
