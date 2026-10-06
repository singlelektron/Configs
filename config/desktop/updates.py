#!/usr/bin/env python3
"""Arch update discovery using checkupdates' separate database; never upgrades."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time


def cache_root():
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    if not root.is_absolute():
        raise ValueError("XDG_CACHE_HOME must be absolute")
    return root / "dotfiles/arch-updates"


def empty():
    return {"status": "unknown", "count": None, "checked_at": None,
            "packages": [], "error": ""}


def status(root=None):
    root = cache_root() if root is None else root
    try:
        value = json.loads((root / "status.json").read_text())
        if not isinstance(value, dict) or value.get("status") not in (
                "unknown", "checking", "ok", "error"):
            return empty()
        packages = value.get("packages")
        if not isinstance(packages, list) or not all(isinstance(p, str) for p in packages):
            return empty()
        count = value.get("count")
        if count is not None and (type(count) is not int or count != len(packages)):
            return empty()
        stamp = value.get("checked_at")
        if stamp is not None and (type(stamp) not in (int, float) or stamp < 0):
            return empty()
        return {**empty(), **value}
    except (OSError, ValueError):
        return empty()


def save(root, value):
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".status-", dir=root)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.write("\n")
        os.replace(name, root / "status.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def stop_process_group(process, grace=2):
    """checkupdates is a shell spawning fakeroot/pacman; stop its whole group."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        process.poll()  # Reap the group leader if it has already exited.
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    # Children can ignore TERM, or outlive their exited shell with closed pipes.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_checkupdates(argv, env, timeout=90, grace=2):
    with subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            stop_process_group(process, grace)
            process.communicate()
            raise
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def check(root=None):
    root = cache_root() if root is None else root
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "check.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return status(root)
        value = status(root)
        value.update(status="checking", error="")
        save(root, value)
        try:
            if not shutil.which("checkupdates"):
                raise RuntimeError("Install pacman-contrib to check Arch updates")
            env = {**os.environ, "CHECKUPDATES_DB": str(root / "db"), "LC_ALL": "C"}
            result = run_checkupdates(["checkupdates", "--nocolor"], env)
            if result.returncode not in (0, 2):
                raise RuntimeError("Could not refresh the separate update database; check network/mirrors")
            # Exit 2 is checkupdates' documented no-updates result, not a failure.
            packages = [] if result.returncode == 2 else [
                re.sub(r"[\x00-\x1f\x7f]", "", line) for line in result.stdout.splitlines() if line.strip()]
            value.update(status="ok", count=len(packages), packages=packages,
                         checked_at=int(time.time()), error="")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            value.update(status="error", error=("Update check timed out" if isinstance(
                error, subprocess.TimeoutExpired) else str(error)))
        save(root, value)
        return value


def review():
    """Niri owns the terminal, so a bar restart cannot terminate its shell."""
    if not os.environ.get("NIRI_SOCKET"):
        raise RuntimeError("Open update review from the Niri desktop")
    subprocess.run(["niri", "msg", "action", "spawn", "--", "kitty", "--title", "Arch updates",
                    sys.executable, str(Path(__file__).resolve()), "terminal"], check=True)


def terminal():
    value = status()
    print("Arch Linux · official repository updates\n")
    if value["checked_at"]:
        print("Last successful check:", time.strftime("%Y-%m-%d %H:%M", time.localtime(value["checked_at"])))
    if value["error"]:
        print(value["error"])
    if value["count"] is None:
        print("No successful check yet.")
    else:
        print(f"{value['count']} packages available\n")
        print("\n".join(value["packages"]))
    print("\nTo update the full system, run: sudo pacman -Syu\nAUR packages are not included.\n", flush=True)
    shell = os.environ.get("SHELL") or "/bin/bash"
    os.execvp(shell, [shell])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "check", "review", "terminal"))
    args = parser.parse_args()
    try:
        if args.action in ("status", "check"):
            print(json.dumps(status() if args.action == "status" else check()))
        elif args.action == "review":
            review()
        else:
            terminal()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
