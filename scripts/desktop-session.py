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
import types

REPO = Path(__file__).resolve().parents[1]
KIND = "moonlit-basic-session-v1"
BAR = "dotfiles-niri-waybar.service"
WALLPAPER = "dotfiles-niri-wallpaper.service"
CHANGED_UNITS = (BAR, WALLPAPER)
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


def live_niri(text):
    for key, action in (("XF86AudioPlay", "toggle"), ("XF86AudioNext", "next"), ("XF86AudioPrev", "previous")):
        lines = [line for line in text.splitlines() if line.strip().startswith(key + " ")]
        if len(lines) != 1:
            raise SessionError("Cannot safely identify media binding: " + key)
        command = 'python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" media ' + action
        text = text.replace(lines[0], "    " + key + " allow-when-locked=true { spawn-sh " + json.dumps(command) + "; }")
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


def basic_config(wallpapers, key_file, source=REPO):
    # Device permissions are independently enforced by the bridge's two proxies.
    preview = load_module(source / "scripts/desktop-preview.py", "session_preview_config")
    return preview.safety_config(wallpapers, key_file) + '''
[shell.launcher]
fetch_exchange_rates = false
[bar.default]
end = ["launcher", "moonlit_updates", "date", "clock"]
[control_center]
show_session_button = false
hidden_tabs = ["audio", "monitor", "system", "weather", "calendar", "notifications", "screen-time", "power"]
shortcuts = [{type="dotfiles/moonlit-network:network"}, {type="bluetooth"}, {type="media"}, {type="wallpaper"}]
'''


def prepare(source_repo, commit, baseline, release, live_root, binary, library_path, wallpapers, home=None):
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
    for name in required:
        if not (source / name).is_file():
            raise SessionError("Committed release lacks required file: " + name)
    live_root.mkdir(parents=True, mode=0o700)
    for name in ("config/noctalia", "state/noctalia", "data/noctalia/plugins", "cache"):
        (live_root / name).mkdir(parents=True, mode=0o700, exist_ok=True)
    config_source = source / "config/moonlit"
    shutil.copy2(config_source / "settings.toml", live_root / "config/noctalia/settings.toml")
    shutil.copytree(config_source / "palettes", live_root / "config/noctalia/palettes")
    shutil.copytree(config_source / "plugins", live_root / "data/noctalia/plugins", dirs_exist_ok=True)
    key_file = live_root / "state/storage-key"
    fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(os.urandom(32).hex() + "\n")
    safety = basic_config(wallpapers, key_file, source)
    # Put supported launcher fields in the existing shell table, not a duplicate table.
    launcher = shlex.join(["/usr/bin/python3", str(release / "managed/niri/desktopctl.py"), "launch", "--"]) + " $CMD"
    safety = safety.replace("[shell]\n", '[shell]\nlaunch_apps_custom_command = ' + json.dumps(launcher)
                            + '\nlaunch_apps_as_systemd_services = false\n', 1)
    (live_root / "config/noctalia/zz-basic-safety.toml").write_text(safety)
    deployer = load_module(source / "scripts/deploy.py", "session_deploy_locations")
    config, state = deployer.locations(home)
    transaction = live_root / "transaction.json"
    legacy_helper = baseline / "config/desktop/desktopctl.py"
    runtime = {"schema": 1, "kind": "moonlit-live-session", "phase": "basic",
               "legacy_desktopctl": str(legacy_helper), "legacy_sha256": sha(legacy_helper),
               "live_root": str(live_root), "binary": str(binary), "binary_sha256": sha(binary),
               "library_path": str(library_path), "config_dir": str(live_root / "config"),
               "state_dir": str(live_root / "state"), "data_dir": str(live_root / "data"),
               "cache_dir": str(live_root / "cache"), "bar_unit": BAR,
               "release": str(release), "transaction": str(transaction)}
    generated = {
        "niri/config.kdl": live_niri((baseline / "platforms/linux/niri/config.kdl").read_text()),
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
KillMode=control-group
TimeoutStopSec=10
Slice=session.slice
''',
    }
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
                "config": str(config), "state": str(state), "files": files}
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
    if before is not None and (not isinstance(before, dict) or set(before) != set(CHANGED_UNITS)
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


def services():
    result = {}
    for unit in CHANGED_UNITS:
        values = control("show", unit, "--property=ActiveState,SubState,MainPID").stdout
        result[unit] = dict(line.split("=", 1) for line in values.splitlines() if "=" in line)
    return result


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
    for target, source in LEGACY_SOURCES.items():
        allowed[config / target].add(str(baseline / source))
    allowed[config / "kitty/theme.conf"].add(str(source_repo / "config/kitty/theme.conf"))
    original = module.snapshot

    def snapshot(path):
        current = original(path)
        if path in allowed and current is not None:
            if current["kind"] != "symlink" or current["destination"] not in allowed[path]:
                raise module.DeploymentError("Unknown existing configuration; review required: " + str(path))
        return current

    module.snapshot = snapshot
    return module, manifest


def deploy(transaction, apply=False):
    value = journal(transaction)
    release = Path(value["release"])
    module, manifest = guarded_deployer(release)
    try:
        # The original transaction checks every source/target before any mutation.
        module.install(release, Path(manifest["config"]), Path(manifest["state"]), "linux", desktop="niri")
        if not apply:
            return {"phase": value["phase"], "dry_run": True, "stop_only": list(CHANGED_UNITS)}
        if value["phase"] == "active":
            return status(transaction)
        if value["phase"] != "prepared":
            raise SessionError("Transaction already started; use start or restore")
        require_host()
        before = services()
        if any(state.get("ActiveState") not in ("active", "inactive", "failed") for state in before.values()):
            raise SessionError("Managed services are changing state; retry when they are stable")
        value.update(services_before=before, phase="stopping")
        atomic_json(transaction, value)
        try:
            for unit, before in value["services_before"].items():
                if before.get("ActiveState") == "active":
                    control("stop", unit)
            value["phase"] = "deploying"
            atomic_json(transaction, value)
            backup = module.install(release, Path(manifest["config"]), Path(manifest["state"]), "linux", apply=True, desktop="niri")
            value.update(backup=str(backup) if backup else None, phase="deployed")
            atomic_json(transaction, value)
            control("daemon-reload")
            return start(transaction)
        except Exception:
            # A partial install's manifest is discoverable even if install raised
            # before returning it; recovery never restores the baseline repair.
            candidates = []
            for p in (Path(manifest["state"]) / "dotfiles/backups").glob("*/manifest.json"):
                try:
                    if json.loads(p.read_text()).get("repo") == str(release):
                        candidates.append(p)
                except (OSError, ValueError):
                    continue
            if not value.get("backup") and candidates:
                value["backup"] = str(max(candidates, key=lambda p: p.stat().st_mtime_ns).parent)
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
    deadline = time.monotonic() + 15
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
    backup = Path(value["backup"]) if value.get("backup") else None
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
    control("stop", BAR)
    try:
        if backup:
            module.restore(backup, apply=True)
    except module.DeploymentError as error:
        raise SessionError(str(error)) from error
    reload_niri(Path(release_manifest["config"]))
    control("daemon-reload")
    for unit, before in value["services_before"].items():
        if before.get("ActiveState") == "active":
            control("start", unit)
    value["phase"] = "restored"
    atomic_json(transaction, value)
    return {"phase": "restored", "transaction": str(transaction)}


def status(transaction):
    value = journal(transaction)
    return {"phase": value["phase"], "transaction": str(transaction), "release": value["release"],
            "backup": value["backup"], "services": services()}


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
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            if not all((args.baseline, args.release, args.live_root, args.binary, args.library_path, args.wallpapers)):
                parser.error("prepare requires --baseline --release --live-root --binary --library-path --wallpapers")
            result = prepare(args.source_repo, args.commit, args.baseline, args.release, args.live_root,
                             args.binary, args.library_path, args.wallpapers, args.home)
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
