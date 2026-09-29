#!/usr/bin/env python3
"""Read-only checks: never print credentials, shell history or environment dumps."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


def main():
    missing = []
    home = Path.home()
    repo = Path(__file__).resolve().parent.parent
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print("Required tools (PATH in the current shell):")
    for name, args in (
        ("git", ["--version"]),
        ("kitty", ["--version"]),
        ("nvim", ["--version"]),
        ("rg", ["--version"]),
        ("fd", ["--version"]),
        ("gh", ["--version"]),
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
            result = subprocess.run([executable, *args], capture_output=True, text=True, timeout=15)
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
    system = "macos" if platform.system() == "Darwin" else "linux"
    links = {
        "kitty/kitty.conf": repo / "config/kitty/kitty.conf",
        "kitty/theme.conf": repo / "config/kitty/theme.conf",
        "kitty/platform.conf": repo / "platforms" / system / "kitty.conf",
        "nvim": repo / "config/nvim",
    }
    for relative, source in links.items():
        target = config / relative
        ok = target.is_symlink() and target.resolve() == source.resolve()
        print(f"  {'OK' if ok else 'UNMANAGED'} {target}")
        if not ok:
            missing.append(relative)

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
