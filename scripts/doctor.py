#!/usr/bin/env python3
"""Read-only checks: never print credentials, shell history or environment dumps."""
import argparse
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from deploy import DeploymentError, entries_for, locations


def check_desktop(config, missing):
    """Check the optional desktop without starting services or a compositor."""
    print("Niri desktop tools:")
    for name in ("niri", "waybar", "fuzzel", "mako", "swaybg", "swayidle", "swaylock",
                 "xwayland-satellite", "wpctl", "pactl", "brightnessctl", "playerctl",
                 "zenity", "blueman-manager", "pavucontrol", "nm-applet", "nmcli", "nm-connection-editor",
                 "jq", "xdg-open", "notify-send", "gnome-keyring-daemon", "nautilus",
                 "fcitx5", "fcitx5-config-qt", "firefox", "wl-copy", "wl-paste"):
        available = shutil.which(name)
        print(f"  {'OK' if available else 'MISSING'} {name}")
        if not available:
            missing.append(name)
    for path in ("/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1",
                 "/usr/lib/xdg-desktop-portal-gnome", "/usr/lib/xdg-desktop-portal-gtk"):
        available = os.access(path, os.X_OK)
        print(f"  {'OK' if available else 'MISSING'} {Path(path).name}")
        if not available:
            missing.append(Path(path).name)

    if shutil.which("niri"):
        for args, label in ((["niri", "--version"], "Niri >= 26.04"),
                            (["niri", "validate", "--config", str(config / "niri/config.kdl")],
                             "deployed Niri configuration")):
            try:
                result = subprocess.run(args, capture_output=True, text=True, timeout=15)
                ok = result.returncode == 0
                if args[1] == "--version":
                    match = re.search(r"\b(\d+)\.(\d+)(?:\.\d+)?\b", result.stdout)
                    ok = ok and bool(match) and tuple(map(int, match.groups())) >= (26, 4)
                print(f"  {'OK' if ok else 'FAIL'} {label}")
                if not ok:
                    missing.append(label)
                    print("    " + (result.stderr or result.stdout).strip()[:1000])
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f"  FAIL {label}: {type(error).__name__}")
                missing.append(label)
    try:
        result = subprocess.run(
            ["/usr/bin/python3", "-c", "import gi; from PIL import Image; gi.require_version('GdkPixbuf', '2.0'); "
             "gi.require_version('Gtk', '4.0'); gi.require_version('GioUnix', '2.0'); "
             "from gi.repository import GdkPixbuf, Gtk, GioUnix; "
             "assert any('svg' in f.get_extensions() for f in GdkPixbuf.Pixbuf.get_formats())"],
            capture_output=True, text=True, timeout=15)
        ok = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    print(f"  {'OK' if ok else 'FAIL'} Pillow, Python GObject, GTK 4, GioUnix and SVG image loader")
    if not ok:
        missing.append("Pillow/Python GObject/GTK 4/GioUnix/SVG loader")
    print("Session checks: select Niri manually to verify lock, portals, input method and sound.")
    print("This command does not start services or switch the desktop session.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", choices=("niri",), help="also check the optional Arch Linux desktop")
    args = parser.parse_args(argv)
    system = "macos" if platform.system() == "Darwin" else "linux" if platform.system() == "Linux" else "unsupported"
    missing = []
    home = Path.home()
    repo = Path(__file__).resolve().parent.parent
    try:
        config, _ = locations()
        links = entries_for(repo, config, system, args.desktop)
    except DeploymentError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Platform: {platform.system()} {platform.machine()}")
    print("Required tools (PATH in the current shell):")
    for name, version_args in (
        ("git", ["--version"]),
        ("kitty", ["--version"]),
        ("nvim", ["--version"]),
        ("rg", ["--version"]),
        ("fd", ["--version"]),
        ("gh", ["--version"]),
        ("lazygit", ["--version"]),
        ("uv", ["--version"]),
        ("rustc", ["--version"]),
        ("rust-analyzer", ["--version"]),
        ("basedpyright", ["--version"]),
        ("ruff", ["--version"]),
        ("texlab", ["--version"]),
    ):
        executable = shutil.which(name)
        if not executable:
            candidates = [home / ".cargo/bin" / name, home / ".local/bin" / name]
            hint = next((str(p) for p in candidates if p.is_file()), None)
            print(f"  MISSING {name}" + (f" (exists outside PATH: {hint})" if hint else ""))
            missing.append(name)
            continue
        try:
            result = subprocess.run([executable, *version_args], capture_output=True, text=True, timeout=15)
            lines = (result.stdout or result.stderr).strip().splitlines()
            first = lines[0] if lines else "no version output"
            ok = result.returncode == 0
            if name == "nvim":
                match = re.search(r"v(\d+)\.(\d+)\.(\d+)", first)
                ok = ok and bool(match) and tuple(map(int, match.groups())) >= (0, 11, 3)
            print(f"  {'OK' if ok else 'FAIL'} {name}: {first}")
            if not ok:
                missing.append(name)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"  FAIL {name}: {type(error).__name__}")
            missing.append(name)

    print("Config links:")
    for target, source in links:
        ok = target.is_symlink() and target.resolve() == source.resolve()
        print(f"  {'OK' if ok else 'UNMANAGED'} {target}")
        if not ok:
            missing.append(str(target.relative_to(config)))

    if args.desktop:
        check_desktop(config, missing)

    print("Optional tools:")
    for name in ("marksman", "latexmk", "xelatex", "pandoc", "wl-copy", "xclip"):
        print(f"  {name}: {'available' if shutil.which(name) else 'not installed/on PATH'}")
    print("Plugin/LSP details: open Neovim and run :checkhealth dotfiles")
    if missing:
        print("Incomplete: " + ", ".join(missing))
        print("See README.md for tools, shell PATH, deployment and optional writing tools.")
        return 1
    print("Core tools and configuration links are ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
