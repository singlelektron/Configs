#!/usr/bin/env python3
"""Prepare and reversibly activate Moonlit's basic stage in the existing Niri session.

prepare never changes deployed links or services. deploy is a dry run unless
--apply is given; activation records and restores only this transaction's service
changes. The old idle, lock, notifications, polkit and compositor remain owners.
"""
import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import types

REPO = Path(__file__).resolve().parents[1]
KIND = "moonlit-basic-session-v1"
BAR = "dotfiles-niri-waybar.service"
WALLPAPER = "dotfiles-niri-wallpaper.service"
CHANGED_UNITS = (BAR, WALLPAPER)
NOTIFICATION_UNITS = ("dotfiles-niri-mako.service", "mako.service")
CAPABILITIES = ("audio", "network", "bluetooth", "calendar", "notifications", "caffeine")
TARGETS = (
    "niri/config.kdl", "niri/desktopctl.py", "niri/moonlit-session.json",
    "niri/moonlit-theme.kdl", "systemd/user/" + BAR,
    "kitty/theme.conf", "moonlit/nvim-theme.lua",
)
LEGACY_SOURCES = {
    "niri/config.kdl": "platforms/linux/niri/config.kdl",
    "niri/desktopctl.py": "config/desktop/desktopctl.py",
    "systemd/user/" + BAR: "platforms/linux/systemd/" + BAR,
}


class SessionError(RuntimeError):
    pass


def load_module(path, name):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".session-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def checked_path(path):
    path = Path(os.path.abspath(path.expanduser()))
    for item in (path, *path.parents):
        if item.is_symlink():
            raise SessionError(f"Refusing symbolic-link parent: {item}")
    return path


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def live_niri(text, notifications=False):
    for key, action in (("XF86AudioPlay", "toggle"), ("XF86AudioNext", "next"), ("XF86AudioPrev", "previous")):
        lines = [line for line in text.splitlines() if line.strip().startswith(key + " ")]
        if len(lines) != 1:
            raise SessionError("Cannot safely identify media binding: " + key)
        command = 'python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" media ' + action
        text = text.replace(lines[0], "    " + key + " allow-when-locked=true { spawn-sh " + json.dumps(command) + "; }")
    if notifications:
        lines = [line for line in text.splitlines() if line.strip().startswith("Mod+Alt+N ")]
        if len(lines) != 1:
            raise SessionError("Cannot safely identify notification binding")
        command = 'python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" notifications toggle'
        text = text.replace(lines[0], '    Mod+Alt+N hotkey-overlay-title="Toggle notifications" { spawn-sh '
                            + json.dumps(command) + '; }')
    marker = "// Includes remain outside Git."
    if text.count(marker) != 1:
        raise SessionError("Cannot locate the preserved local include boundary")
    appearance = '''include "moonlit-theme.kdl"
window-rule {
    match app-id="^(kitty|moonlit-work|moonlit-notes)$"
    background-effect { blur true; xray true; }
}

'''
    return text.replace(marker, appearance + marker)


def capability_list(values):
    if not isinstance(values, (list, tuple)) or any(value not in CAPABILITIES for value in values):
        raise SessionError("Unsupported capability; expected " + ", ".join(CAPABILITIES))
    return sorted(set(values))


def basic_config(wallpapers, key_file, source=REPO, capabilities=(), calendar_dir=None):
    # Device permissions are independently enforced by the bridge's two proxies.
    capabilities = capability_list(capabilities)
    preview = load_module(source / "scripts/desktop-preview.py", "session_preview_config")
    end = ["launcher", "moonlit_updates", "date", "clock"]
    hidden = ["audio", "monitor", "system", "weather", "calendar", "notifications", "screen-time", "power"]
    shortcuts = ["dotfiles/moonlit-network:network", "bluetooth", "media", "wallpaper"]
    if "audio" in capabilities:
        end.insert(2, "volume")
        hidden.remove("audio")
        shortcuts.insert(2, "audio")
    if "calendar" in capabilities:
        if calendar_dir is None:
            raise SessionError("Calendar capability requires a private calendar directory")
        hidden.remove("calendar")
    if "notifications" in capabilities:
        hidden.remove("notifications")
        end.insert(2, "notifications")
    if "caffeine" in capabilities:
        shortcuts.append("dotfiles/moonlit-controls:awake")
    safety = preview.safety_config(wallpapers, key_file)
    if "notifications" in capabilities:
        safety = safety.replace("[notification]\nenable_daemon = false", "[notification]\nenable_daemon = true")
    text = safety + '''
[shell.launcher]
fetch_exchange_rates = false
[bar.default]
end = ''' + json.dumps(end) + '''
[control_center]
show_session_button = false
hidden_tabs = ''' + json.dumps(hidden) + '\nshortcuts = [' + ', '.join(
        '{type=' + json.dumps(name) + '}' for name in shortcuts) + ']\n'
    text += '\n[calendar]\nenabled = ' + str("calendar" in capabilities).lower() + '\n'
    text += '[calendar.reminders]\nenabled = false\n'
    if "calendar" in capabilities:
        text += '[calendar.account.gnome_calendar]\ntype = "vdir"\nname = "GNOME Calendar · read-only"\npath = '
        text += json.dumps(str(calendar_dir)) + '\ncalendars = []\n'
    if "caffeine" in capabilities:
        enabled = tomllib.loads((source / "config/moonlit/settings.toml").read_text()).get("plugins", {}).get("enabled", [])
        enabled = list(dict.fromkeys([*enabled, "dotfiles/moonlit-controls"]))
        text += '\n[plugins]\nenabled = ' + json.dumps(enabled) + '\n'
    return text


def predecessor(path, baseline, config, state):
    path = checked_path(path)
    value = journal(path)
    release = Path(value["release"])
    manifest = verify(release)
    if value["phase"] != "active":
        raise SessionError("Only a previously active transaction can be inherited")
    if (manifest["baseline"], manifest["config"], manifest["state"]) != (str(baseline), str(config), str(state)):
        raise SessionError("Inherited transaction must use the same baseline and XDG deployment roots")
    for name in TARGETS:
        target = config / name
        if not target.is_symlink() or os.readlink(target) != str(release / "managed" / name):
            raise SessionError("Inherited transaction is no longer the deployed release: " + str(target))
    runtime = json.loads((release / "managed/niri/moonlit-session.json").read_text())
    capability_list(runtime.get("capabilities", []))
    return {"release": str(release), "transaction": str(path)}, runtime


def inherit_preferences(runtime, live_root, wallpapers):
    # Carry only the manually selected wallpaper and music choice. Never import
    # old settings tables, which could override this stage's safety profile.
    old = checked_path(Path(runtime["state_dir"])) / "noctalia"
    settings = old / "settings.toml"
    if settings.is_file() and not settings.is_symlink():
        wallpaper = tomllib.loads(settings.read_text()).get("wallpaper", {})
        entries = [("wallpaper." + name, wallpaper.get(name, {})) for name in ("default", "last")]
        entries.extend(("wallpaper.monitors." + json.dumps(name), choice)
                       for name, choice in wallpaper.get("monitors", {}).items())
        text = []
        for table, choice in entries:
            raw = choice.get("path") if isinstance(choice, dict) else None
            if not isinstance(raw, str):
                continue
            image = Path(raw).resolve()
            if image.is_file() and wallpapers in image.parents:
                text.append("[" + table + "]\npath = " + json.dumps(str(image)) + "\n")
        if text:
            (live_root / "state/noctalia/settings.toml").write_text("\n".join(text))
    music = old / "plugins/data/dotfiles/moonlit-music/media-control.json"
    if music.is_file() and not music.is_symlink():
        target = live_root / "state/noctalia/plugins/data/dotfiles/moonlit-music/media-control.json"
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json(target, json.loads(music.read_text()))


def prepare(source_repo, commit, baseline, release, live_root, binary, library_path, wallpapers, home=None,
            capabilities=(), inherit_transaction=None):
    capabilities = capability_list(capabilities)
    source_repo = checked_path(source_repo)
    baseline, release, live_root = map(checked_path, (baseline, release, live_root))
    for path in (release, live_root):
        if path.exists():
            raise SessionError(f"Choose a fresh owned destination: {path}")
        if path == Path.home() or path in Path.home().parents or source_repo == path or source_repo in path.parents:
            raise SessionError("Release and live state must stay outside the mutable checkout and protected roots")
    if release in live_root.parents or live_root in release.parents or release == live_root:
        raise SessionError("Release and mutable live state must be separate")
    if git(source_repo, "status", "--porcelain", "--untracked-files=normal").strip():
        raise SessionError("Production release requires a clean committed source checkout")
    commit = git(source_repo, "rev-parse", "--verify", "--end-of-options", commit + "^{commit}").decode().strip()
    baseline_tool = load_module(REPO / "scripts/desktop-baseline.py", "session_baseline")
    baseline_tool.verify(baseline)
    deployer = load_module(REPO / "scripts/deploy.py", "session_deploy_locations")
    config, state = deployer.locations(home)
    previous, old_runtime = predecessor(inherit_transaction, baseline, config, state) if inherit_transaction else (None, None)
    previous_capabilities = set(old_runtime.get("capabilities", [])) if old_runtime else set()
    if len(set(capabilities) - previous_capabilities) > 1:
        raise SessionError("Enable only one new device capability per stage")
    binary = binary.expanduser().resolve(strict=True)
    library_path = Path(library_path).expanduser().resolve(strict=True)
    wallpapers = wallpapers.expanduser().resolve(strict=True)
    if not os.access(binary, os.X_OK) or not library_path.is_dir() or not wallpapers.is_dir():
        raise SessionError("Executable runtime, library directory and wallpaper directory are required")
    archive_bytes = git(source_repo, "archive", "--format=tar", commit)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise SessionError("Unsafe release archive member: " + member.name)
        release.mkdir(parents=True, mode=0o700)
        source = release / "source"
        source.mkdir()
        archive.extractall(source, filter="data")
    required = ("scripts/deploy.py", "scripts/desktop-session.py", "config/moonlit/desktopctl.py",
                "config/moonlit/settings.toml", "config/moonlit/niri-theme.kdl",
                "config/moonlit/kitty-theme.conf", "config/moonlit/nvim-theme.lua")
    if "calendar" in capabilities:
        required += ("config/moonlit/calendar_bridge.py",)
    if "caffeine" in capabilities:
        required += ("config/moonlit/plugins/moonlit-controls/plugin.toml",)
    for name in required:
        if not (source / name).is_file():
            raise SessionError("Committed release lacks required file: " + name)
    live_root.mkdir(parents=True, mode=0o700)
    for name in ("config/noctalia", "state/noctalia", "data/noctalia/plugins", "cache"):
        (live_root / name).mkdir(parents=True, mode=0o700, exist_ok=True)
    calendar_dir = live_root / "data/noctalia/calendar-vdir"
    if "calendar" in capabilities:
        calendar_dir.mkdir(mode=0o700)
    config_source = source / "config/moonlit"
    shutil.copy2(config_source / "settings.toml", live_root / "config/noctalia/settings.toml")
    shutil.copytree(config_source / "palettes", live_root / "config/noctalia/palettes")
    shutil.copytree(config_source / "plugins", live_root / "data/noctalia/plugins", dirs_exist_ok=True)
    key_file = live_root / "state/storage-key"
    fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(os.urandom(32).hex() + "\n")
    safety = basic_config(wallpapers, key_file, source, capabilities, calendar_dir)
    # Put supported launcher fields in the existing shell table, not a duplicate table.
    launcher = shlex.join(["/usr/bin/python3", str(release / "managed/niri/desktopctl.py"), "launch", "--"]) + " $CMD"
    safety = safety.replace("[shell]\n", '[shell]\nlaunch_apps_custom_command = ' + json.dumps(launcher)
                            + '\nlaunch_apps_as_systemd_services = false\n', 1)
    (live_root / "config/noctalia/zz-basic-safety.toml").write_text(safety)
    if old_runtime:
        inherit_preferences(old_runtime, live_root, wallpapers)
    transaction = live_root / "transaction.json"
    legacy_helper = baseline / "config/desktop/desktopctl.py"
    runtime = {"schema": 1, "kind": "moonlit-live-session", "phase": "basic",
               "capabilities": capabilities,
               "legacy_desktopctl": str(legacy_helper), "legacy_sha256": sha(legacy_helper),
               "live_root": str(live_root), "binary": str(binary), "binary_sha256": sha(binary),
               "library_path": str(library_path), "config_dir": str(live_root / "config"),
               "state_dir": str(live_root / "state"), "data_dir": str(live_root / "data"),
               "cache_dir": str(live_root / "cache"), "bar_unit": BAR,
               "release": str(release), "transaction": str(transaction)}
    if "calendar" in capabilities:
        runtime["calendar_dir"] = str(calendar_dir)
    generated = {
        "niri/config.kdl": live_niri((baseline / "platforms/linux/niri/config.kdl").read_text(), "notifications" in capabilities),
        "niri/desktopctl.py": (config_source / "desktopctl.py").read_text(),
        "niri/moonlit-session.json": json.dumps(runtime, indent=2) + "\n",
        "niri/moonlit-theme.kdl": (config_source / "niri-theme.kdl").read_text(),
        "kitty/theme.conf": (config_source / "kitty-theme.conf").read_text(),
        "moonlit/nvim-theme.lua": (config_source / "nvim-theme.lua").read_text(),
        "systemd/user/" + BAR: '''[Unit]
Description=Moonlit basic desktop shell
PartOf=niri.service graphical-session.target
After=niri.service graphical-session.target
Requisite=niri.service graphical-session.target

[Service]
Type=simple
UnsetEnvironment=GDK_BACKEND
ExecStart=/usr/bin/python3 "%E/niri/desktopctl.py" shell
Restart=no
KillMode=mixed
TimeoutStopSec=30
Slice=session.slice
''',
    }
    if set(capabilities) & {"notifications", "caffeine"}:
        # Cleanup remains bound to this release even after the deployed helper
        # link changes; systemd also invokes it when the runner is killed.
        fixed_manifest = json.dumps("MOONLIT_SESSION_MANIFEST=" + str(release / "managed/niri/moonlit-session.json")).replace("%", "%%")
        fixed_helper = json.dumps(str(release / "managed/niri/desktopctl.py")).replace("%", "%%")
        unit = "systemd/user/" + BAR
        cleanup = ["notifications-cleanup"] if "notifications" in capabilities else []
        if "caffeine" in capabilities:
            cleanup.append("presentation-cleanup")
        commands = ''.join("ExecStopPost=:/usr/bin/python3 " + fixed_helper + " " + action + "\n" for action in cleanup)
        generated[unit] = generated[unit].replace("Type=simple\n", "Type=simple\nEnvironment=" + fixed_manifest
                          + "\n" + commands, 1)
    for name, contents in generated.items():
        path = release / "managed" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    subprocess.run(["niri", "validate", "--config", str(release / "managed/niri/config.kdl")], check=True, capture_output=True)
    files = {}
    for parent, dirs, names in os.walk(release):
        for name in names:
            path = Path(parent) / name
            path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
            files[path.relative_to(release).as_posix()] = sha(path)
    manifest = {"version": 1, "kind": KIND, "commit": commit, "source_repo": str(source_repo),
                "baseline": str(baseline), "live_root": str(live_root), "transaction": str(transaction),
                "config": str(config), "state": str(state), "files": files, "predecessor": previous,
                "capabilities": capabilities,
                "changed_units": list(CHANGED_UNITS + (NOTIFICATION_UNITS if "notifications" in
                                  (set(capabilities) | previous_capabilities) else ()))}
    atomic_json(release / "manifest.json", manifest)
    (release / "manifest.json").chmod(0o444)
    for parent, _, _ in os.walk(release, topdown=False):
        Path(parent).chmod(0o555)
    atomic_json(transaction, {"version": 1, "kind": KIND, "phase": "prepared", "release": str(release),
                              "live_root": str(live_root), "backup": None, "services_before": None})
    return {"release": str(release), "transaction": str(transaction), "phase": "prepared"}


def verify(release):
    release = checked_path(release)
    if release.stat().st_uid != os.getuid() or (release / "manifest.json").is_symlink():
        raise SessionError("Release ownership or manifest is unsafe")
    manifest = json.loads((release / "manifest.json").read_text())
    if manifest.get("kind") != KIND or manifest.get("version") != 1:
        raise SessionError("Unsupported session release")
    found = {}
    for parent, dirs, files in os.walk(release, followlinks=False):
        for name in dirs + files:
            if (Path(parent) / name).is_symlink():
                raise SessionError("Unexpected release symlink")
        for name in files:
            path = Path(parent) / name
            relative = path.relative_to(release).as_posix()
            if relative != "manifest.json":
                found[relative] = sha(path)
    if found != manifest["files"]:
        raise SessionError("Release content changed; refusing activation or restore")
    return manifest


def deployer_for(release):
    manifest = verify(release)
    module = load_module(release / "source/scripts/deploy.py", "moonlit_session_deploy")

    def entries(repo, config, platform, desktop=None):
        if platform != "linux" or desktop != "niri" or repo != release:
            raise module.DeploymentError("Unexpected session deployment scope")
        return [(config / name, release / "managed" / name) for name in TARGETS]

    module.entries_for = entries
    return module, manifest


def journal(path):
    path = checked_path(path)
    value = json.loads(path.read_text())
    if value.get("kind") != KIND or value.get("version") != 1:
        raise SessionError("Unsupported session transaction")
    manifest = verify(Path(value["release"]))
    if path != Path(manifest["transaction"]) or value["live_root"] != manifest["live_root"]:
        raise SessionError("Transaction does not belong to this release")
    before = value.get("services_before")
    if before is not None and (not isinstance(before, dict) or set(before) != set(changed_units(manifest))
                               or any(not isinstance(state, dict) or state.get("ActiveState") not in
                                      ("active", "inactive", "failed") for state in before.values())):
        raise SessionError("Invalid service recovery scope in transaction")
    return value


@contextlib.contextmanager
def transaction_lock(path):
    journal(path)
    fd = os.open(path.parent / ".session-lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SessionError("Another command owns this session transaction") from error
        yield
    finally:
        os.close(fd)


def control(*args):
    return subprocess.run(["systemctl", "--user", *args], check=True, capture_output=True, text=True, timeout=20)


def changed_units(manifest):
    units = manifest.get("changed_units", list(CHANGED_UNITS))
    if units not in (list(CHANGED_UNITS), list(CHANGED_UNITS + NOTIFICATION_UNITS)):
        raise SessionError("Unsupported service scope in release")
    return tuple(units)


def services(units=CHANGED_UNITS):
    result = {}
    for unit in units:
        values = control("show", unit, "--property=ActiveState,SubState,MainPID").stdout
        result[unit] = dict(line.split("=", 1) for line in values.splitlines() if "=" in line)
    return result


def notification_action(release, action):
    env = dict(os.environ, MOONLIT_SESSION_MANIFEST=str(release / "managed/niri/moonlit-session.json"))
    subprocess.run([sys.executable, str(release / "managed/niri/desktopctl.py"), action], env=env,
                   check=True, capture_output=True, text=True, timeout=40)


def notification_controller(release, manifest):
    if "notifications" in manifest.get("capabilities", []):
        return release
    previous = manifest.get("predecessor")
    if previous and "notifications" in verify(Path(previous["release"])).get("capabilities", []):
        return Path(previous["release"])
    return None


def carry_native_notifications(source_release, target_release):
    """Preserve this pinned Noctalia's own state after its old process exits.

    Mako exports are kept separately and are never converted into native history.
    """
    runtimes = [json.loads((release / "managed/niri/moonlit-session.json").read_text())
                for release in (source_release, target_release)]
    if not all("notifications" in runtime.get("capabilities", []) for runtime in runtimes):
        return
    if runtimes[0]["binary_sha256"] != runtimes[1]["binary_sha256"]:
        raise SessionError("Notification history transfer requires the same pinned runtime")
    old, new = (Path(runtime["live_root"]) for runtime in runtimes)
    dnd = checked_path(old / "notification-state.json")
    if dnd.is_file():
        value = json.loads(dnd.read_text())
        if not isinstance(value.get("dnd"), bool):
            raise SessionError("Invalid private DND state")
        atomic_json(new / "notification-state.json", {"dnd": value["dnd"]})
    source, target = (Path(runtime["state_dir"]) / "noctalia" for runtime in runtimes)
    history = checked_path(source / "notification_history.json")
    if history.is_file():
        atomic_json(target / history.name, json.loads(history.read_text()))
    assets = checked_path(source / "notification_history_assets")
    if assets.is_dir():
        for item in assets.rglob("*"):
            checked_path(item)
            if item.is_file():
                destination = target / assets.name / item.relative_to(assets)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(item, destination)
                destination.chmod(0o600)


def require_host():
    niri_socket = os.environ.get("NIRI_SOCKET")
    if not niri_socket:
        raise SessionError("A real logged-in Niri session is required")
    pid = int(control("show", "niri.service", "--property=MainPID", "--value").stdout.strip())
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(2)
        connection.connect(niri_socket)
        peer_pid, peer_uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
    if pid <= 0 or pid != peer_pid or peer_uid != os.getuid():
        raise SessionError("Refusing a nested or unrelated compositor")


def guarded_deployer(release):
    module, manifest = deployer_for(release)
    config = Path(manifest["config"])
    source_repo, baseline = Path(manifest["source_repo"]), Path(manifest["baseline"])
    allowed = {config / name: {str(release / "managed" / name)} for name in TARGETS}
    previous = manifest.get("predecessor")
    if previous:
        previous_release = Path(previous["release"])
        verify(previous_release)
        for name in TARGETS:
            allowed[config / name].add(str(previous_release / "managed" / name))
    else:
        for target, source in LEGACY_SOURCES.items():
            allowed[config / target].add(str(baseline / source))
        allowed[config / "kitty/theme.conf"].add(str(source_repo / "config/kitty/theme.conf"))
    original = module.snapshot

    def snapshot(path):
        current = original(path)
        if path in allowed:
            if current is None and previous:
                raise module.DeploymentError("Inherited configuration disappeared; review required: " + str(path))
            if current is not None and (current["kind"] != "symlink" or current["destination"] not in allowed[path]):
                raise module.DeploymentError("Unknown existing configuration; review required: " + str(path))
        return current

    module.snapshot = snapshot
    return module, manifest


def discover_backup(release, state):
    candidates = []
    for path in (state / "dotfiles/backups").glob("*/manifest.json"):
        try:
            if json.loads(path.read_text()).get("repo") == str(release):
                candidates.append(path)
        except (OSError, ValueError):
            continue
    return max(candidates, key=lambda path: path.stat().st_mtime_ns).parent if candidates else None


def deploy(transaction, apply=False):
    value = journal(transaction)
    release = Path(value["release"])
    module, manifest = guarded_deployer(release)
    try:
        # The original transaction checks every source/target before any mutation.
        module.install(release, Path(manifest["config"]), Path(manifest["state"]), "linux", desktop="niri")
        if not apply:
            return {"phase": value["phase"], "dry_run": True, "stop_only": list(changed_units(manifest))}
        if value["phase"] == "active":
            return status(transaction)
        if value["phase"] != "prepared":
            raise SessionError("Transaction already started; use start or restore")
        require_host()
        before = services(changed_units(manifest))
        if any(state.get("ActiveState") not in ("active", "inactive", "failed") for state in before.values()):
            raise SessionError("Managed services are changing state; retry when they are stable")
        value.update(services_before=before, phase="stopping")
        atomic_json(transaction, value)
        try:
            for unit, before in value["services_before"].items():
                # Notification ownership is archived and handed off only after
                # its runtime activation mask is held by the fixed helper.
                if unit in CHANGED_UNITS and before.get("ActiveState") == "active":
                    control("stop", unit)
            previous = manifest.get("predecessor")
            if previous:
                carry_native_notifications(Path(previous["release"]), release)
            controller = notification_controller(release, manifest)
            if controller:
                notification_action(controller, "notifications-prepare")
            value["phase"] = "deploying"
            atomic_json(transaction, value)
            backup = module.install(release, Path(manifest["config"]), Path(manifest["state"]), "linux", apply=True, desktop="niri")
            value.update(backup=str(backup) if backup else None, phase="deployed")
            atomic_json(transaction, value)
            control("daemon-reload")
            if "notifications" not in manifest.get("capabilities", []) and NOTIFICATION_UNITS[0] in value["services_before"]:
                control("start", NOTIFICATION_UNITS[0])
            result = start(transaction)
            if controller and "notifications" not in manifest.get("capabilities", []):
                notification_action(controller, "notifications-restore-dnd")
                notification_action(controller, "notifications-cleanup")
            return result
        except Exception:
            # A partial install's manifest is discoverable even if install raised
            # before returning it; recovery never restores the baseline repair.
            backup = discover_backup(release, Path(manifest["state"]))
            if not value.get("backup") and backup:
                value["backup"] = str(backup)
            value["phase"] = "failed"
            atomic_json(transaction, value)
            restore(transaction, apply=True)
            raise
    except module.DeploymentError as error:
        raise SessionError(str(error)) from error


def start(transaction):
    value = journal(transaction)
    if value["phase"] not in ("deployed", "active"):
        raise SessionError("Only a deployed transaction can start")
    require_host()
    manifest = verify(Path(value["release"]))
    reload_niri(Path(manifest["config"]))
    control("start", BAR)
    helper = Path(manifest["config"]) / "niri/desktopctl.py"
    # E-D-S asynchronously enumerates enabled sources and their cached views on
    # the calendar's first startup; ordinary shell stages keep the shorter wait.
    deadline = time.monotonic() + (45 if "calendar" in manifest.get("capabilities", []) else 15)
    last_error = "bridge not ready"
    while time.monotonic() < deadline:
        result = subprocess.run([sys.executable, str(helper), "status"], capture_output=True, text=True, timeout=4)
        if result.returncode == 0:
            try:
                health = json.loads(result.stdout)
                if health.get("ready") is True:
                    value["phase"] = "active"
                    atomic_json(transaction, value)
                    return {"phase": "active", "transaction": str(transaction), "health": health}
            except (ValueError, AttributeError):
                pass
        last_error = result.stderr.strip()
        time.sleep(.2)
    raise SessionError("New shell did not become ready: " + last_error)


def reload_niri(config):
    # A symlink replacement need not notify a watcher on its old target. Parse
    # the deployed path (including machine overrides) before explicitly loading.
    path = str(config / "niri/config.kdl")
    subprocess.run(["niri", "validate", "--config", path], check=True, capture_output=True, text=True, timeout=10)
    subprocess.run(["niri", "msg", "action", "load-config-file", "--path", path],
                   check=True, capture_output=True, text=True, timeout=10)


def restore(transaction, apply=False):
    value = journal(transaction)
    release = Path(value["release"])
    module, release_manifest = deployer_for(release)
    backup = Path(value["backup"]) if value.get("backup") else discover_backup(release, Path(release_manifest["state"]))
    try:
        if backup:
            manifest = module.load_manifest(backup)
            if manifest["repo"] != str(release):
                raise SessionError("Refusing a backup from another deployment")
            module.restore(backup)  # conflict preflight before stopping a working shell
    except module.DeploymentError as error:
        raise SessionError(str(error)) from error
    if not apply or value["phase"] == "restored":
        return {"phase": value["phase"], "dry_run": not apply, "backup": str(backup) if backup else None}
    if value["services_before"] is None:
        raise SessionError("This transaction has not changed the live session")
    require_host()
    if backup and not value.get("backup"):
        value["backup"] = str(backup)
        atomic_json(transaction, value)
    control("stop", BAR)
    controller = notification_controller(release, release_manifest)
    previous = release_manifest.get("predecessor")
    transferred_to = None
    completed = False
    try:
        if previous:
            carry_native_notifications(release, Path(previous["release"]))
        if controller:
            # ExecStopPost released the old lease. Reacquire while restoring so
            # D-Bus activation cannot race the original notification provider.
            notification_action(controller, "notifications-prepare")
        if backup:
            module.restore(backup, apply=True)
        reload_niri(Path(release_manifest["config"]))
        control("daemon-reload")
        if (controller and previous and value["services_before"][BAR].get("ActiveState") == "active"
                and "notifications" in verify(Path(previous["release"])).get("capabilities", [])):
            # Do not let the previous runner mistake this release's mask for a
            # user-owned preexisting mask. Its own prepare closes any activation
            # race and creates the lease its stop hooks must later release.
            notification_action(controller, "notifications-cleanup")
            transferred_to = Path(previous["release"])
            notification_action(transferred_to, "notifications-prepare")
        # Let the original notification owner acquire its name while the
        # package provider is still masked, then bring back the prior shell.
        ordered = (*NOTIFICATION_UNITS, *CHANGED_UNITS) if controller else CHANGED_UNITS
        if controller and value["services_before"].get("mako.service", {}).get("ActiveState") == "active":
            # Its prior provider was the package unit itself; releasing our
            # temporary mask lets systemd start that exact provider again.
            notification_action(controller, "notifications-cleanup")
        for unit in ordered:
            if value["services_before"].get(unit, {}).get("ActiveState") == "active":
                control("start", unit)
        if controller and any(value["services_before"].get(unit, {}).get("ActiveState") == "active"
                              for unit in NOTIFICATION_UNITS):
            notification_action(controller, "notifications-restore-dnd")
        if controller and previous and value["services_before"][BAR].get("ActiveState") == "active":
            start(Path(previous["transaction"]))
        completed = True
    except module.DeploymentError as error:
        raise SessionError(str(error)) from error
    finally:
        if controller and controller != transferred_to:
            notification_action(controller, "notifications-cleanup")
        if transferred_to and not completed:
            notification_action(transferred_to, "notifications-cleanup")
    value["phase"] = "restored"
    atomic_json(transaction, value)
    return {"phase": "restored", "transaction": str(transaction)}


def status(transaction):
    value = journal(transaction)
    manifest = verify(Path(value["release"]))
    return {"phase": value["phase"], "transaction": str(transaction), "release": value["release"],
            "backup": value["backup"], "services": services(changed_units(manifest)),
            "capabilities": manifest.get("capabilities", [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "deploy", "start", "status", "restore"))
    parser.add_argument("--source-repo", type=Path, default=REPO)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--live-root", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--library-path", type=Path)
    parser.add_argument("--wallpapers", type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--transaction", type=Path)
    parser.add_argument("--inherit-transaction", type=Path,
                        help="upgrade the currently deployed active Moonlit transaction")
    parser.add_argument("--capability", choices=CAPABILITIES, action="append", default=[],
                        help="complete desired capability set; repeat for retained capabilities, at most one new capability")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            if not all((args.baseline, args.release, args.live_root, args.binary, args.library_path, args.wallpapers)):
                parser.error("prepare requires --baseline --release --live-root --binary --library-path --wallpapers")
            result = prepare(args.source_repo, args.commit, args.baseline, args.release, args.live_root,
                             args.binary, args.library_path, args.wallpapers, args.home,
                             args.capability, args.inherit_transaction)
        else:
            if not args.transaction:
                parser.error("--transaction is required")
            path = checked_path(args.transaction)
            with transaction_lock(path) if args.action != "status" else contextlib.nullcontext():
                if args.action == "deploy":
                    result = deploy(path, args.apply)
                elif args.action == "restore":
                    result = restore(path, args.apply)
                elif args.action == "start":
                    result = start(path)
                else:
                    result = status(path)
        print(json.dumps(result, indent=2))
        return 0
    except (SessionError, OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, "Desktop session: " + str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
