#!/usr/bin/env python3
"""Pin the existing Niri desktop to a versioned source archive, without restarting it.

prepare writes only a new versioned archive. deploy and restore are dry runs unless
--apply is supplied. Deployment uses the pinned scripts/deploy.py's backup/restore
transaction, restricted to its NIRI_FILES; Kitty, Neovim and LazyGit are untouched.
No service command is run. Config watchers may reload files when links change.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import types

REPO = Path(__file__).resolve().parents[1]
LEGACY_COMMIT = "7fc7f157e260583f7221353e103c14d0e08c8972"
MARKER = ".desktop-baseline.json"
RECIPE = "current-preserving-no-override-gtk-v1"


class BaselineError(RuntimeError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_path(path):
    path = Path(os.path.abspath(path.expanduser()))
    for item in (path, *path.parents):
        if item.is_symlink():
            raise BaselineError(f"Refusing a symbolic-link path: {item}")
    return path


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True).stdout


def compatibility_overlay(old, current):
    """Restore only the two entry points still called by the loaded island shell."""
    old_tree = ast.parse(old)
    desktop = next(node for node in old_tree.body if isinstance(node, ast.ClassDef) and node.name == "Desktop")
    methods = {node.name: "\n".join(old.splitlines()[node.lineno - 1:node.end_lineno]) + "\n"
               for node in desktop.body if isinstance(node, ast.FunctionDef)}
    anchor = "    @staticmethod\n    def filter_hardware"
    actions = 'for action in ("session-start", "waybar",'
    if current.count(anchor) != 1 or current.count(actions) != 1:
        raise BaselineError("Current helper layout changed; compatibility patch requires review")
    # Music UI calls only `music` (open); existing hardware keys keep playerctl.
    current = current.replace(anchor, methods["shell"] + "\n" + methods["music"] + "\n" + anchor)
    current = current.replace(actions, 'for action in ("session-start", "shell", "music", "waybar",')
    compile(current, "desktopctl-baseline.py", "exec")
    return current


def prepare(repo, revision, destination, preserve_revision="HEAD"):
    """Materialize only tracked source from one commit, never the live checkout."""
    repo = repo.expanduser().resolve(strict=True)
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode().strip()
    preserve = git(repo, "rev-parse", "--verify", "--end-of-options", preserve_revision + "^{commit}").decode().strip()
    destination = checked_path(destination)
    if destination.exists():
        existing = verify(destination)
        if existing["commit"] != commit or existing.get("preserve_commit") != preserve:
            raise BaselineError("Existing baseline is a different commit; choose a fresh destination")
        return destination
    if destination == repo or repo in destination.parents or destination in repo.parents:
        raise BaselineError("Baseline must be outside the mutable source checkout")
    if destination == Path.home() or destination in Path.home().parents:
        raise BaselineError("Refusing protected home or ancestor destination")
    archive_bytes = git(repo, "archive", "--format=tar", commit)
    old_deploy = git(repo, "show", commit + ":scripts/deploy.py").decode()
    pairs = next(ast.literal_eval(node.value) for node in ast.parse(old_deploy).body
                 if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "NIRI_FILES" for t in node.targets))
    current_paths = set(git(repo, "ls-tree", "-r", "--name-only", preserve).decode().splitlines())
    for _, source in pairs:
        path = repo / source
        if source not in current_paths and (path.exists() or path.is_symlink()):
            raise BaselineError("Legacy dependency has untracked or ignored local content; review before freezing: " + source)
    overlays = {source: git(repo, "show", preserve + ":" + source) for _, source in pairs if source in current_paths}
    changed = git(repo, "diff", "--name-only", preserve, "--", *overlays).decode().splitlines()
    if changed:
        raise BaselineError("Preserved desktop files differ from the working checkout; review before freezing: " + ", ".join(changed))
    helper = "config/desktop/desktopctl.py"
    unit = "platforms/linux/systemd/dotfiles-niri-waybar.service"
    if helper not in overlays or unit not in overlays:
        raise BaselineError("Current revision lacks the helper or bar unit to preserve")
    overlays[helper] = compatibility_overlay(git(repo, "show", commit + ":" + helper).decode(), overlays[helper].decode()).encode()
    bar = overlays[unit].decode()
    if bar.count('"%E/niri/desktopctl.py" waybar') != 1:
        raise BaselineError("Current bar unit changed; startup compatibility requires review")
    overlays[unit] = bar.replace('"%E/niri/desktopctl.py" waybar', '"%E/niri/desktopctl.py" shell').encode()
    neutral_gtk = {source for _, source in pairs
                   if source in ("config/gtk-3.0/settings.ini", "config/gtk-4.0/settings.ini") and source not in current_paths}
    for source in neutral_gtk:
        # A dangling settings.ini currently inherits the desktop's settings.
        # Restoring legacy theme/font values would change that effective behavior.
        overlays[source] = b"# No overrides: preserve the previously missing file's inherited GTK settings.\n[Settings]\n"
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.name == MARKER:
                raise BaselineError(f"Unsafe archive path: {member.name}")
            if not (member.isdir() or member.isfile()):
                raise BaselineError(f"Links and special archive files are unsupported: {member.name}")
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".desktop-baseline-", dir=destination.parent) as temporary:
            staging = Path(temporary) / "source"
            staging.mkdir(mode=0o700)
            for member in members:
                target = staging / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                data = overlays.get(member.name, archive.extractfile(member).read())
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                mode = 0o555 if member.mode & 0o111 else 0o444
                target.chmod(mode)
                files[member.name] = {"sha256": digest(data), "mode": mode,
                                      "origin_commit": preserve if member.name in overlays else commit}
                if member.name in (helper, unit):
                    files[member.name]["compatibility"] = "existing Quickshell shell/music entry points from " + commit
                elif member.name in neutral_gtk:
                    files[member.name]["origin_commit"] = None
                    files[member.name]["compatibility"] = "generated no-override GTK settings; preserve missing-file inheritance at " + preserve
            if "scripts/deploy.py" not in files:
                raise BaselineError("Commit has no deployment script")
            manifest = {"schema": 1, "recipe": RECIPE, "commit": commit, "preserve_commit": preserve,
                        "source_repo": str(repo), "files": files,
                        "scope": "legacy NIRI_FILES only; current valid desktop sources preserved; shared links excluded"}
            (staging / MARKER).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            (staging / MARKER).chmod(0o444)
            # No mutable branch, index, worktree registration or whole-home copy.
            # Exclusive directory publication refuses an intervening destination.
            destination.mkdir(mode=0o700)
            try:
                for child in staging.iterdir():
                    child.rename(destination / child.name)
                for parent, dirs, _ in os.walk(destination, topdown=False):
                    Path(parent).chmod(0o555)
            except BaseException:
                # Leave recoverable partial files; never remove an unexpected destination.
                raise BaselineError(f"Baseline publication interrupted; inspect {destination}")
    verify(destination)
    return destination


def verify(baseline):
    baseline = checked_path(baseline)
    if not baseline.is_dir() or baseline.stat().st_uid != os.getuid():
        raise BaselineError("Baseline is absent or belongs to another user")
    marker = baseline / MARKER
    if marker.is_symlink():
        raise BaselineError("Baseline marker must be a regular file")
    try:
        manifest = json.loads(marker.read_text())
        if (manifest["schema"] != 1 or manifest.get("recipe") != RECIPE or len(manifest["commit"]) != 40
                or any(c not in "0123456789abcdef" for c in manifest["commit"])
                or not isinstance(manifest["files"], dict)):
            raise ValueError("invalid manifest structure")
        expected = set(manifest["files"])
        found = set()
        for parent, dirs, names in os.walk(baseline, followlinks=False):
            for name in dirs + names:
                path = Path(parent) / name
                if path.is_symlink():
                    raise BaselineError(f"Unexpected link in baseline: {path}")
            for name in names:
                path = Path(parent) / name
                relative = path.relative_to(baseline).as_posix()
                if relative == MARKER:
                    continue
                found.add(relative)
                item = manifest["files"].get(relative)
                if (not item or not path.is_file() or digest(path.read_bytes()) != item["sha256"]
                        or stat.S_IMODE(path.stat().st_mode) != item["mode"]):
                    raise BaselineError(f"Baseline content or permissions changed: {relative}")
        if found != expected or "scripts/deploy.py" not in expected:
            raise BaselineError("Baseline is incomplete or contains unexpected files")
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise BaselineError(f"Invalid baseline: {baseline}: {error}") from error


def load_deployer(baseline):
    verify(baseline)
    source = baseline / "scripts/deploy.py"
    module = types.ModuleType("pinned_desktop_deploy")
    module.__file__ = str(source)
    # Avoid writing __pycache__ into the read-only versioned tree.
    exec(compile(source.read_bytes(), str(source), "exec"), module.__dict__)
    original_entries = module.entries_for

    def desktop_entries(repo, config, platform, desktop=None):
        original_entries(repo, config, platform, desktop)  # retain platform/profile validation
        if platform != "linux" or desktop != "niri":
            raise module.DeploymentError("The pinned desktop baseline is Linux/Niri only")
        return [(config / target, repo / source) for target, source in module.NIRI_FILES]

    # install() still owns preflight, race checks, originals, private backup manifest,
    # and interrupted-restore recovery. Its manifest is a valid subset of the
    # unmodified pinned deploy.py's Niri profile, so that file can restore it alone.
    module.entries_for = desktop_entries
    return module


def deploy(baseline, home=None, apply=False):
    baseline = checked_path(baseline)
    manifest = verify(baseline)
    module = load_deployer(baseline)
    config, state = module.locations(home)
    try:
        allowed = {config / target: {str(Path(manifest["source_repo"]) / source), str(baseline / source)}
                   for target, source in module.NIRI_FILES}
        original_snapshot = module.snapshot

        def managed_snapshot(path):
            value = original_snapshot(path)
            if path in allowed and value is not None:
                if value["kind"] != "symlink" or value["destination"] not in allowed[path]:
                    raise module.DeploymentError(f"Unknown existing desktop path; manual review required: {path}")
            return value

        for target in allowed:
            module.check_parents(target)
            managed_snapshot(target)
        # Repeat the narrow ownership check inside install's own preflight and
        # race checks, so an intervening regular file can never become a backup
        # merely because it appeared between our preflight and the transaction.
        module.snapshot = managed_snapshot
        return module.install(baseline, config, state, "linux", apply=apply, desktop="niri")
    except module.DeploymentError as error:
        raise BaselineError(str(error)) from error


def restore(baseline, backup, apply=False):
    baseline = checked_path(baseline)
    module = load_deployer(baseline)
    try:
        manifest = module.load_manifest(backup)
        if Path(manifest["repo"]) != baseline:
            raise BaselineError("Backup belongs to a different source baseline")
        module.restore(backup, apply=apply)
    except module.DeploymentError as error:
        raise BaselineError(str(error)) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", "deploy", "restore"))
    parser.add_argument("--source-repo", type=Path, default=REPO)
    parser.add_argument("--revision", default=LEGACY_COMMIT)
    parser.add_argument("--preserve-revision", default="HEAD", help="commit supplying existing desktop files and Niri keys")
    parser.add_argument("--baseline", type=Path, help="versioned destination/source; default uses XDG_DATA_HOME")
    parser.add_argument("--home", type=Path, help="explicit disposable/home target, ignoring inherited XDG paths")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    baseline = args.baseline or data / "dotfiles/deployments" / ("legacy-" + LEGACY_COMMIT)
    try:
        if args.action == "prepare":
            print(prepare(args.source_repo, args.revision, baseline, args.preserve_revision))
        elif args.action == "verify":
            manifest = verify(baseline)
            print(json.dumps({"baseline": str(baseline), "commit": manifest["commit"], "preserve_commit": manifest["preserve_commit"],
                              "verified_files": len(manifest["files"])}))
        elif args.action == "deploy":
            backup = deploy(baseline, args.home, args.apply)
            if backup:
                print("Restore with: " + shlex.join([sys.executable, str(baseline / "scripts/deploy.py"),
                                                    "--restore", str(backup), "--apply"]))
        elif args.action == "restore":
            if args.backup is None or args.home is not None:
                parser.error("restore requires --backup and reads target paths from its manifest; omit --home")
            restore(baseline, args.backup, args.apply)
        return 0
    except (BaselineError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Desktop baseline: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
