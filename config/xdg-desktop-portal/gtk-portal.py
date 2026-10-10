#!/usr/bin/env python3
"""Apply the Moonlit theme to the GTK portal in Niri sessions only."""
import os
from pathlib import Path
import sys

PORTAL = "/usr/lib/xdg-desktop-portal-gtk"


def main():
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    if "niri" in desktops:
        data = Path(__file__).absolute().parent / "data"
        inherited = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
        os.environ["XDG_DATA_DIRS"] = str(data) + ":" + inherited
        os.environ["GTK_THEME"] = "MoonlitPortal:dark"
    os.execv(PORTAL, [PORTAL, *sys.argv[1:]])


if __name__ == "__main__":
    main()
