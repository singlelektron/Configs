#!/usr/bin/env python3
"""Install NetEase GTK4 2.5.4 locally; dry-run by default, --restore ID to undo.

The upstream AppImage bundles a libc incompatible with this Arch loader and
hardcodes /usr/share resources. Build the verified official source with a local
prefix instead. Uses system GTK4/GStreamer; no FUSE, root, or account credentials.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

VERSION = "2.5.4"
COMMIT = "d94c5f4ea1f1d03aa0b6d542d3f5a51e9551c007"
SOURCE_URL = "https://codeload.github.com/gmg137/netease-cloud-music-gtk/tar.gz/" + COMMIT
SOURCE_SHA256 = "b449de06ae76d11b8d1a4164350532247d65703ea3fb364c906ea82cf1f7c85e"
APP_ID = "com.gitee.gmg137.NeteaseCloudMusicGtk4"
BINARY = "netease-cloud-music-gtk4"
TARGET_KEYS = ("version", "launcher", "desktop", "icon")
TOOLS = ("cargo", "pkg-config", "glib-compile-resources", "glib-compile-schemas", "msgfmt")
LIBRARIES = ("gtk4 >= 4.14", "libadwaita-1 >= 1.6", "gstreamer-play-1.0 >= 1.24", "openssl", "dbus-1")


def xdg(name, fallback):
    path = Path(os.environ.get(name) or Path.home() / fallback).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    return path


def paths():
    data = xdg("XDG_DATA_HOME", ".local/share")
    return {"version": data / "dotfiles/music" / (VERSION + "-native"),
            "launcher": Path.home() / ".local/bin" / BINARY,
            "desktop": data / "applications" / (APP_ID + ".desktop"),
            "icon": data / "icons/hicolor/scalable/apps" / (APP_ID + ".svg"),
            "backups": xdg("XDG_STATE_HOME", ".local/state") / "dotfiles/music/backups",
            "cache": xdg("XDG_CACHE_HOME", ".cache") / "dotfiles/music/build"}


def exists(path):
    return path.exists() or path.is_symlink()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def verify_archive(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Official source SHA-256 mismatch; nothing was installed")


def requirements():
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise ValueError("This installer is validated for x86_64 Linux only")
    missing = [name for name in TOOLS if not shutil.which(name)]
    if missing:
        raise ValueError("Install native build dependencies first: " + ", ".join(missing))
    for dependency in LIBRARIES:
        if subprocess.run(["pkg-config", "--exists", dependency], check=False).returncode:
            raise ValueError("Missing native library: " + dependency)


def build(destination, prefix, cache, archive=None):
    """Build from fresh verified source; cache Cargo objects, never account state."""
    requirements()
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="source-", dir=cache) as temporary:
        work = Path(temporary)
        source_archive = work / "source.tar.gz"
        if archive:
            shutil.copyfile(archive, source_archive)
        else:
            request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "dotfiles-music/1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read(16 * 1024 * 1024 + 1)
            if len(payload) > 16 * 1024 * 1024:
                raise ValueError("Source archive exceeds 16 MiB")
            source_archive.write_bytes(payload)
        verify_archive(source_archive)
        with tarfile.open(source_archive) as bundle:
            bundle.extractall(work, filter="data")
        source = work / ("netease-cloud-music-gtk-" + COMMIT)
        values = {"VERSION": VERSION, "GETTEXT_PACKAGE": BINARY,
                  "LOCALEDIR": str(prefix / "share/locale"),
                  "PKGDATADIR": str(prefix / "share" / BINARY)}
        # Match upstream src/meson.build while avoiding global Meson installation.
        (source / "src/config.rs").write_text("".join(
            f"pub static {key}: &str = {json.dumps(value, ensure_ascii=False)};\n"
            for key, value in values.items()))
        env = os.environ | {"CARGO_TARGET_DIR": str(cache / "target")}
        env.setdefault("CARGO_BUILD_JOBS", "4")
        # Upstream 2.5.4 ships no Cargo.lock. Resolve once, build that exact
        # resolution, and retain it with the installation (not a historical lock).
        subprocess.run(["cargo", "generate-lockfile", "--manifest-path", str(source / "Cargo.toml")],
                       env=env, check=True)
        subprocess.run(["cargo", "build", "--locked", "--release", "--manifest-path", str(source / "Cargo.toml")],
                       env=env, check=True)
        (destination / "bin").mkdir(parents=True)
        shutil.copy2(cache / "target/release" / BINARY, destination / "bin" / BINARY)
        resource = destination / "share" / BINARY
        resource.mkdir(parents=True)
        subprocess.run(["glib-compile-resources", str(source / "data/netease_cloud_music_gtk4.gresource.xml"),
                        "--sourcedir", str(source / "data"), "--target", str(resource / (BINARY + ".gresource"))], check=True)
        schemas = destination / "share/glib-2.0/schemas"
        schemas.mkdir(parents=True)
        shutil.copy2(source / "data" / (APP_ID + ".gschema.xml"), schemas)
        subprocess.run(["glib-compile-schemas", "--strict", str(schemas)], check=True)
        shutil.copytree(source / "data/icons", destination / "share/icons")
        for po in (source / "po").glob("*.po"):
            target = destination / "share/locale" / po.stem / "LC_MESSAGES" / (BINARY + ".mo")
            target.parent.mkdir(parents=True)
            subprocess.run(["msgfmt", "-o", str(target), str(po)], check=True)
        shutil.copy2(source / "Cargo.lock", destination / "Cargo.lock")
        write_json(destination / "installation.json", {"version": VERSION, "commit": COMMIT,
                   "source_sha256": SOURCE_SHA256, "source_url": SOURCE_URL, "prefix": str(prefix)})


def launcher_text(prefix):
    # No shell interpolation of user-controlled paths; shlex handles spaces/quotes.
    return ("#!/bin/sh\n" +
            "export GSETTINGS_SCHEMA_DIR=" + shlex.quote(str(prefix / "share/glib-2.0/schemas")) + "\n" +
            "export XDG_DATA_DIRS=" + shlex.quote(str(prefix / "share")) + ':"${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"\n' +
            "exec " + shlex.quote(str(prefix / "bin" / BINARY)) + ' "$@"\n')


def desktop_quote(value):
    # Desktop Exec has its own quoting/field-code rules, separate from shell.
    return '"' + str(value).replace("\\", "\\\\\\\\").replace('"', '\\\\"').replace("`", "\\\\`").replace("$", "\\\\$").replace("%", "%%") + '"'


def desktop_text(targets):
    icon = icon_source(targets)
    return ("[Desktop Entry]\nType=Application\nName=NetEase Cloud Music Gtk4\nName[zh_CN]=网易云音乐\n"
            # env keeps GLib's pre-expansion executable lookup independent of a
            # user home containing '%' while passing the path as a single argv.
            "Comment=网易云音乐 GTK4 客户端\nExec=/usr/bin/env " + desktop_quote(targets["launcher"]) + "\nIcon=" + str(icon) +
            "\nTerminal=false\nStartupNotify=true\nStartupWMClass=" + APP_ID +
            "\nCategories=AudioVideo;Audio;Player;GTK;\nKeywords=Music;NetEase;网易云;音乐;\n")


def icon_source(targets):
    return targets["version"] / "share/icons/hicolor/scalable/apps" / (APP_ID + ".svg")


def backup_record(targets, backup):
    # IDs are local names, never arbitrary paths supplied by a downloaded file.
    if Path(backup).name != backup or backup in (".", ".."):
        raise ValueError("Restore requires a backup ID, not a path")
    root = targets["backups"] / backup
    journal = root / "manifest.json"
    record = json.loads(journal.read_text())
    if record.get("restored"):
        raise ValueError("This backup was already restored")
    for item in record["items"]:
        key = item["key"]
        if key not in TARGET_KEYS or str(targets[key]) != item["target"]:
            raise ValueError("Restore paths differ; use the original HOME and XDG directories")
    return root, journal, record


def restore(targets, backup, apply=False):
    root, journal, record = backup_record(targets, backup)
    # Preflight all entries before moving anything. Older completed installs have
    # no phases; interrupted restores created by this version are resumable.
    for item in record["items"]:
        phase = item.get("restore_phase")
        if phase not in (None, "remove", "original", "done"):
            raise ValueError("Invalid restore journal phase")
        if phase is None:
            if exists(root / "removed" / item["key"]):
                raise ValueError("An older unjournaled restore was interrupted; preserved files need manual review")
            if item.get("installed") and item.get("had_original") and not exists(root / (item["key"] + ".original")):
                raise ValueError("Original backup is missing; refusing to change installed files")
    print(f"Restore {backup}; current installed files are retained under that backup's removed/ directory")
    if not apply:
        return
    (root / "removed").mkdir(exist_ok=True)
    for item in reversed(record["items"]):
        if item.get("restore_phase") == "done":
            continue
        target = targets[item["key"]]
        previous = root / (item["key"] + ".original")
        removed = root / "removed" / item["key"]
        if item.get("restore_phase") is None:
            item["restore_had_original"] = exists(previous)
            item["restore_phase"] = "remove"
            write_json(journal, record)
        if item["restore_phase"] == "remove":
            if exists(removed) and exists(target):
                raise ValueError(f"{target} changed during restore; both copies were preserved")
            if exists(target):
                # Unattempted install entries still point at their original and
                # have no separate backup; leave those untouched.
                if item.get("installed") or exists(previous):
                    shutil.move(str(target), str(removed))
            item["restore_phase"] = "original"
            write_json(journal, record)
        if item["restore_phase"] == "original":
            if item["restore_had_original"]:
                if exists(previous):
                    if exists(target):
                        raise ValueError(f"{target} appeared during restore; original backup preserved")
                    shutil.move(str(previous), str(target))
                elif not exists(target):
                    raise ValueError("Original backup and restored target are both missing")
                # previous missing + target present means its move completed
                # before the journal was written. Never move it a second time.
            item["restore_phase"] = "done"
            write_json(journal, record)
    record["restored"] = True
    write_json(journal, record)


def refresh_icon(targets, backup, apply=False):
    """Extend an existing install's journal without rebuilding/restarting the app."""
    root, journal, record = backup_record(targets, backup)
    source = icon_source(targets)
    target = targets["icon"]
    if not source.is_file() or not any(i["key"] == "version" and i.get("installed") for i in record["items"]):
        raise ValueError("No installed native icon associated with this backup")
    previous_item = next((i for i in record["items"] if i["key"] == "icon"), None)
    if previous_item:
        if target.is_symlink() and target.readlink() == source:
            print("The managed hicolor icon is already installed")
            return
        raise ValueError("The managed icon changed or an icon update was interrupted; restore this backup first")
    print(f"Register hicolor icon: {target} -> {source}; extend backup {backup}")
    if not apply:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    item = {"key": "icon", "target": str(target), "installed": False,
            "had_original": exists(target)}
    record["items"].append(item)
    write_json(journal, record)
    try:
        if exists(target):
            shutil.move(str(target), str(root / "icon.original"))
        item["installed"] = True
        write_json(journal, record)
        target.symlink_to(source)
    except Exception:
        # Roll back only this addition; the logged-in running client is untouched.
        original = root / "icon.original"
        if exists(original):
            if exists(target):
                shutil.move(str(target), str(root / "icon.failed"))
            shutil.move(str(original), str(target))
        record["items"].remove(item)
        write_json(journal, record)
        raise


def install(targets, apply=False, archive=None, cache=None):
    print(f"NetEase GTK4 {VERSION}: official source {COMMIT}")
    print("Native build; system GTK4, libadwaita and GStreamer; login/cache stay outside Git.")
    for key in TARGET_KEYS:
        print(f"{key}: {targets[key]}")
    if not apply:
        print("Dry run. Add --apply to build/install; --restore ID --apply restores originals.")
        return None
    requirements()
    targets["backups"].mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"),
                                   dir=targets["backups"]))
    record = {"version": VERSION, "restored": False, "items": []}
    journal = backup / "manifest.json"
    write_json(journal, record)
    print("Backup ID: " + backup.name, flush=True)
    print("Restore: python3 scripts/install-music.py --restore " + backup.name + " --apply", flush=True)
    with tempfile.TemporaryDirectory(prefix="staging-", dir=backup) as temporary:
        stage = Path(temporary)
        build(stage / "version", targets["version"], cache or targets["cache"], archive)
        (stage / "launcher").write_text(launcher_text(targets["version"]))
        (stage / "launcher").chmod(0o755)
        (stage / "desktop").write_text(desktop_text(targets))
        (stage / "icon").symlink_to(icon_source(targets))
        try:
            for key in TARGET_KEYS:
                target = targets[key]
                target.parent.mkdir(parents=True, exist_ok=True)
                item = {"key": key, "target": str(target), "installed": False,
                        "had_original": exists(target)}
                record["items"].append(item)
                write_json(journal, record)
                if exists(target):
                    shutil.move(str(target), str(backup / (key + ".original")))
                # Journal intent before mutation, so a killed install is restorable.
                item["installed"] = True
                write_json(journal, record)
                shutil.move(str(stage / key), str(target))
        except Exception:
            restore(targets, backup.name, apply=True)
            raise
    print("Installed. Open NetEase GTK4 from the application menu; login is performed in the app.")
    return backup.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--restore", metavar="ID")
    action.add_argument("--refresh-icon", metavar="ID", help="register the installed icon using an existing backup ID")
    parser.add_argument("--archive", type=Path, help="use a local official source archive (SHA-256 still checked)")
    parser.add_argument("--build-cache", type=Path, help="reuse a Cargo build cache outside this repository")
    args = parser.parse_args()
    try:
        if args.restore:
            restore(paths(), args.restore, args.apply)
        elif args.refresh_icon:
            refresh_icon(paths(), args.refresh_icon, args.apply)
        else:
            install(paths(), args.apply, args.archive, args.build_cache)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        print("NetEase installation: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
