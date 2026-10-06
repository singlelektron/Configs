#!/usr/bin/env python3
"""Apply or restore six shared GTK/portal appearance preferences, with a backup."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

SCHEMA = "org.gnome.desktop.interface"
SETTINGS = {
    "color-scheme": "'prefer-light'", "gtk-theme": "'Adwaita'", "icon-theme": "'Adwaita'",
    "font-name": "'Noto Sans 11'", "monospace-font-name": "'JetBrainsMonoNL Nerd Font Mono 11'",
    "accent-color": "'pink'",
}


def gsettings(*args):
    result = subprocess.run(["gsettings", *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def apply(backup, write=False, restore=False):
    supported = gsettings("list-keys", SCHEMA).splitlines()
    if restore:
        value = json.loads(backup.read_text())
        entries = value["settings"]
        current = {}
        for key, record in entries.items():
            current[key] = gsettings("get", SCHEMA, key)
            if current[key] not in (record["applied"], record["original"]):
                raise ValueError(f"{key} changed after deployment; refusing to overwrite your newer preference")
        for key, record in entries.items():
            print(f"Restore {key}: {record['original']}")
            if write and current[key] != record["original"]:
                gsettings("set", SCHEMA, key, record["original"])
        if write:
            backup.unlink()
        return
    entries = {key: {"original": gsettings("get", SCHEMA, key), "applied": value}
               for key, value in SETTINGS.items() if key in supported}
    if write and not backup.exists():
        backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".appearance-", dir=backup.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"schema": SCHEMA, "settings": entries}, stream, indent=2)
                stream.write("\n")
            os.replace(name, backup)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    for key, record in entries.items():
        print(f"Set {key}: {record['applied']}")
        if write:
            gsettings("set", SCHEMA, key, record["applied"])
    if write:
        print(f"Original preferences: {backup}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    if not state.is_absolute():
        parser.error("XDG_STATE_HOME must be absolute")
    try:
        apply(state / "dotfiles/appearance/original.json", args.apply, args.restore)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Appearance: {error}\n")
    if not args.apply:
        print("Dry run; use --apply to make changes. These app preferences are shared by GNOME and Niri.")


if __name__ == "__main__":
    main()
