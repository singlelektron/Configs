#!/usr/bin/env python3
"""Link this checkout's configs; keep recoverable originals outside the repo."""

import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile
from datetime import datetime, timezone


class DeploymentError(Exception):
    pass


def snapshot(path):
    """lstat also observes dangling symlinks without following them."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    kind = ("symlink" if stat.S_ISLNK(info.st_mode) else
            "directory" if stat.S_ISDIR(info.st_mode) else
            "file" if stat.S_ISREG(info.st_mode) else "unsupported")
    if kind == "unsupported":
        raise DeploymentError(f"Refusing special file: {path}")
    result = {"kind": kind, "device": info.st_dev, "inode": info.st_ino,
              "mode": info.st_mode, "size": info.st_size,
              "mtime_ns": info.st_mtime_ns}
    if kind == "symlink":
        result["destination"] = os.readlink(path)
    return result


def check_parents(path):
    for parent in reversed(path.parents):
        if parent.is_symlink():
            raise DeploymentError(f"Refusing symlinked parent directory: {parent}")
        if parent.exists() and not parent.is_dir():
            raise DeploymentError(f"Parent is not a directory: {parent}")


def owns_link(target, source):
    return target.is_symlink() and os.readlink(target) == str(source)


def within(path, parent):
    return path == parent or parent in path.parents


def absolute_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise DeploymentError(f"Expected an absolute path: {value}")
    return Path(os.path.abspath(path))


def locations(home=None, environ=None):
    environ = os.environ if environ is None else environ
    root = Path(home).expanduser().resolve() if home else Path.home().resolve()
    # Explicit --home is also useful for testing: never inherit the host's XDG paths.
    config = root / ".config"
    state = root / ".local/state"
    if home is None:
        config = absolute_path(environ.get("XDG_CONFIG_HOME") or config)
        state = absolute_path(environ.get("XDG_STATE_HOME") or state)
    return config, state


def entries_for(repo, config, platform):
    if platform not in ("macos", "linux"):
        raise DeploymentError("Only macOS and Linux are supported.")
    return [
        (config / "kitty/kitty.conf", repo / "config/kitty/kitty.conf"),
        (config / "kitty/theme.conf", repo / "config/kitty/theme.conf"),
        (config / "kitty/platform.conf", repo / f"platforms/{platform}/kitty.conf"),
        (config / "nvim", repo / "config/nvim"),
    ]


def save_manifest(directory, manifest):
    temporary = directory / "manifest.json.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    temporary.replace(directory / "manifest.json")


def install(repo, config, state, platform, apply=False):
    repo = repo.resolve()
    pairs = entries_for(repo, config, platform)
    backup_root = state / "dotfiles/backups"
    changed = []
    # Preflight every entry before any directories, links, or backups are created.
    check_parents(backup_root / "placeholder")
    if within(backup_root, repo):
        raise DeploymentError("Backups must be stored outside the repository.")
    for target, source in pairs:
        check_parents(target)
        expected_directory = target.name == "nvim"
        if not (source.is_dir() if expected_directory else source.is_file()):
            raise DeploymentError(f"Missing configuration source: {source}")
        if within(source, target) or within(target, source):
            raise DeploymentError(f"Source and destination overlap: {target}")
        if within(backup_root, target) or within(target, backup_root):
            raise DeploymentError(f"Backup location overlaps a managed path: {target}")
        original = snapshot(target)
        if owns_link(target, source):
            continue
        changed.append({"target": str(target), "link": str(source),
                        "backup": f"{len(changed):02d}-{target.name}" if original else None,
                        "original": original})
    if not changed:
        print("Already linked to this checkout; no changes.")
        return None
    for entry in changed:
        action = "back up existing; link" if entry["original"] else "link"
        print(f"{action}: {entry['target']} -> {entry['link']}")
    if not apply:
        print("Dry run. Use --apply to make these changes.")
        return None

    (state / "dotfiles").mkdir(parents=True, mode=0o700, exist_ok=True)
    backup_root.mkdir(mode=0o700, exist_ok=True)
    backup_root.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
    directory = Path(tempfile.mkdtemp(prefix=stamp, dir=backup_root))
    manifest = {"version": 1, "repo": str(repo), "config": str(config),
                "platform": platform, "entries": changed, "restored": False}
    save_manifest(directory, manifest)
    try:
        for entry in changed:
            target, source = Path(entry["target"]), Path(entry["link"])
            check_parents(target)
            if snapshot(target) != entry["original"]:
                raise DeploymentError(f"Destination changed during deployment: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry["backup"]:
                target.rename(directory / entry["backup"])
            # Exclusive creation: an intervening file is never overwritten.
            target.symlink_to(source, target_is_directory=source.is_dir())
    except (OSError, DeploymentError) as error:
        command = shlex.join([sys.executable, str(repo / "scripts/deploy.py"),
                              "--restore", str(directory)])
        raise DeploymentError(
            f"Deployment stopped: {error}\nOriginals are preserved; no automatic rollback.\n"
            f"Inspect or restore with: {command} [--apply]") from error
    print(f"Applied. Backup manifest: {directory / 'manifest.json'}")
    return directory


def load_manifest(directory):
    check_parents(directory / "manifest.json")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink():
        raise DeploymentError("Refusing a symlinked backup manifest.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["version"] != 1 or not isinstance(manifest["restored"], bool):
            raise ValueError("unsupported manifest version or status")
        repo = absolute_path(manifest["repo"])
        config = absolute_path(manifest["config"])
        expected = {str(target): str(source) for target, source in
                    entries_for(repo, config, manifest["platform"])}
        seen = set()
        for index, entry in enumerate(manifest["entries"]):
            target = entry["target"]
            if target in seen or expected.get(target) != entry["link"]:
                raise ValueError("unexpected or duplicate managed path")
            seen.add(target)
            original = entry["original"]
            if original is not None and (not isinstance(original, dict) or
                                         original.get("kind") not in ("file", "directory", "symlink")):
                raise ValueError("invalid original snapshot")
            expected_backup = f"{index:02d}-{Path(target).name}" if original else None
            if entry["backup"] != expected_backup:
                raise ValueError("invalid backup path")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise DeploymentError(f"Invalid backup manifest: {manifest_path}: {error}") from error
    return manifest


def restore_action(directory, entry):
    target, source = Path(entry["target"]), Path(entry["link"])
    check_parents(target)
    original = entry["original"]
    backup = directory / entry["backup"] if entry["backup"] else None
    current = snapshot(target)
    if backup is not None and snapshot(backup) is not None:
        if current is not None and not owns_link(target, source):
            raise DeploymentError(f"Restore conflict; destination contains intervening changes: {target}")
        return "restore"
    if original is None:
        if current is None:
            return "none"
        if owns_link(target, source):
            return "remove"
        raise DeploymentError(f"Restore conflict; destination contains intervening changes: {target}")
    if current == original:
        # Not reached during a failed install, or already restored before an interruption.
        return "none"
    raise DeploymentError(f"Restore conflict; original backup is missing: {target}")


def restore(directory, apply=False):
    directory = absolute_path(directory)
    manifest = load_manifest(directory)
    if manifest["restored"]:
        print("This backup has already been restored; no changes.")
        return
    actions = [(entry, restore_action(directory, entry)) for entry in manifest["entries"]]
    for entry, action in actions:
        if action != "none":
            print(f"{action}: {entry['target']}")
    if not apply:
        print("Dry run. Use --apply to restore these paths.")
        return
    try:
        for entry, planned in actions:
            action = restore_action(directory, entry)
            if action != planned:
                raise DeploymentError(f"Destination changed during restore: {entry['target']}")
            if action == "none":
                continue
            target = Path(entry["target"])
            if owns_link(target, Path(entry["link"])):
                target.unlink()
            if action == "restore":
                target.parent.mkdir(parents=True, exist_ok=True)
                # Refuse an intervening path instead of replacing user data.
                if snapshot(target) is not None:
                    raise DeploymentError(f"Destination changed during restore: {target}")
                (directory / entry["backup"]).rename(target)
        manifest["restored"] = True
        save_manifest(directory, manifest)
    except (OSError, DeploymentError) as error:
        raise DeploymentError(f"Restore stopped: {error}\nRemaining backups are preserved in {directory}") from error
    print(f"Restored. Manifest retained at {directory / 'manifest.json'}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the planned changes (default: dry run)")
    parser.add_argument("--home", type=Path, help="use HOME/.config and HOME/.local/state, ignoring XDG variables")
    parser.add_argument("--restore", type=Path, metavar="BACKUP_DIR", help="restore a deployment from its backup directory")
    args = parser.parse_args(argv)
    if args.restore and args.home:
        parser.error("--restore reads destinations from its manifest; omit --home")
    try:
        if args.restore:
            restore(args.restore, args.apply)
        else:
            platform = "macos" if sys.platform == "darwin" else "linux" if sys.platform.startswith("linux") else "unsupported"
            config, state = locations(args.home)
            install(Path(__file__).resolve().parents[1], config, state, platform, args.apply)
    except (DeploymentError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
