#!/usr/bin/env python3
"""Build the pinned parameter-only btop view locally, without root or startup downloads.

Requires a C++20 compiler, make and patch. --archive reuses a verified source
archive; --check only verifies the installed binary and its local provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "config/sysmon/btop-view.patch"
VERSION = "1.4.7"
SOURCE_URL = f"https://codeload.github.com/aristocratos/btop/tar.gz/refs/tags/v{VERSION}"
SOURCE_SHA256 = "933de2e4d1b2211a638be463eb6e8616891bfba73aef5d38060bd8319baeefc6"
OWNER = "Configs parameter-only btop view"
STABLE = "btop-view"
PROVENANCE = "provenance.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def install_root(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError("Install root must be a directory, not a symbolic link")
    return path


def verify_version(path: Path, expected_patch: str | None = None) -> dict:
    """Existing destinations must be owned, pinned and internally intact."""
    marker, binary, license_file = path / PROVENANCE, path / "usr/bin/btop-view", path / "LICENSE"
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Refusing unrelated version destination: {path}")
    for item in (marker, path / "usr", path / "usr/bin", binary, license_file):
        if item.is_symlink() or not item.exists():
            raise ValueError(f"Missing or symbolic-link install content: {item}")
    data = json.loads(marker.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Refusing unrelated provenance: {marker}")
    patch_hash = data.get("patch_sha256", "")
    if (data.get("owner") != OWNER or data.get("schema") != 1
            or data.get("version") != VERSION or data.get("source_url") != SOURCE_URL
            or data.get("source_sha256") != SOURCE_SHA256
            or not isinstance(patch_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", patch_hash)
            or path.name != f"{STABLE}-{VERSION}-{patch_hash}"):
        raise ValueError(f"Refusing unrelated or unpinned install: {path}")
    if expected_patch is not None and patch_hash != expected_patch:
        raise ValueError("Installed monitor patch does not match this checkout; rebuild the monitor")
    if expected_patch is not None and (data.get("system") != platform.system()
                                       or data.get("machine") != platform.machine()):
        raise ValueError("Installed monitor was built for another platform; rebuild it locally")
    if not binary.is_file() or not os.access(binary, os.X_OK) or digest(binary) != data.get("binary_sha256"):
        raise ValueError("Installed monitor binary is missing, changed or not executable")
    if not license_file.is_file() or digest(license_file) != data.get("license_sha256"):
        raise ValueError("Installed upstream LICENSE is missing or changed")
    return data


def stable_version(root: Path) -> Path | None:
    link = root / STABLE
    if not link.is_symlink():
        if link.exists():
            raise ValueError(f"Refusing unrelated existing destination: {link}")
        return None
    target = Path(os.readlink(link))
    if target.is_absolute() or len(target.parts) != 1:
        raise ValueError("Stable monitor link must point to an owned version inside the install root")
    version = root / target
    verify_version(version)
    return version


def check(root: Path) -> Path:
    root = install_root(root)
    version = stable_version(root)
    if version is None:
        raise ValueError("Parameter-only monitor is not installed; run scripts/build-monitor.py")
    verify_version(version, digest(PATCH))
    return version / "usr/bin/btop-view"


def download(path: Path) -> None:
    print(f"Fetching pinned btop {VERSION} source...", flush=True)
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as response, path.open("wb") as output:
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > 32 * 1024 * 1024:
                raise ValueError("Source download exceeded 32 MiB")
            output.write(block)


def extract(archive_path: Path, workspace: Path) -> Path:
    if digest(archive_path) != SOURCE_SHA256:
        raise ValueError("Source archive SHA-256 does not match the pinned btop release")
    # The pinned source has no links; reject links/special files and traversal
    # before extraction instead of relying on Python-version-specific filters.
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts
                    or path.parts[0] != f"btop-{VERSION}"
                    or not (member.isfile() or member.isdir())):
                raise ValueError(f"Unsafe source archive member: {member.name}")
        archive.extractall(workspace, members=members)
    return workspace / f"btop-{VERSION}"


def build_command(jobs: int) -> list[str]:
    command = ["make", f"-j{jobs}", "RSMI_STATIC=false", "STATIC=false"]
    if platform.system() == "Linux":
        command.append("GPU_SUPPORT=true")
    # macOS chooses the upstream platform defaults, including Apple GPU support.
    return command


def prepare(root: Path, archive: Path | None = None, jobs: int = 2) -> Path:
    if jobs < 1:
        raise ValueError("Build jobs must be a positive integer")
    root = install_root(root)
    stable_version(root)  # Refuse unrelated destinations before downloads/builds.
    patch_bytes = PATCH.read_bytes()
    patch_hash = hashlib.sha256(patch_bytes).hexdigest()
    version = root / f"{STABLE}-{VERSION}-{patch_hash}"
    if version.exists() or version.is_symlink():
        verify_version(version, patch_hash)
    else:
        with tempfile.TemporaryDirectory(prefix="configs-monitor-build-") as temporary:
            workspace = Path(temporary)
            source_archive = archive
            if source_archive is None:
                source_archive = workspace / "btop.tar.gz"
                download(source_archive)
            source = extract(source_archive, workspace)
            subprocess.run(["patch", "-p1", "--batch", "--forward"], cwd=source,
                           input=patch_bytes, check=True)
            command = build_command(jobs)
            print(f"Building btop {VERSION} parameter-only view with {jobs} jobs...", flush=True)
            subprocess.run(command, cwd=source, check=True)
            binary = source / "bin/btop"
            license_file = source / "LICENSE"
            if not binary.is_file() or not os.access(binary, os.X_OK) or not license_file.is_file():
                raise ValueError("Build did not produce an executable monitor and upstream LICENSE")
            data = {"schema": 1, "owner": OWNER, "version": VERSION, "source_url": SOURCE_URL,
                    "source_sha256": SOURCE_SHA256, "patch_sha256": patch_hash,
                    "binary_sha256": digest(binary), "license_sha256": digest(license_file),
                    "system": platform.system(), "machine": platform.machine(), "build_command": command}
            # Keep the build outside the destination. Only complete outputs are
            # staged there, then published as a new version in one rename.
            stable_version(root)
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".btop-view-install-", dir=root) as staging:
                package = Path(staging) / "package"
                (package / "usr/bin").mkdir(parents=True)
                shutil.copyfile(binary, package / "usr/bin/btop-view")
                (package / "usr/bin/btop-view").chmod(0o755)
                shutil.copyfile(license_file, package / "LICENSE")
                (package / PROVENANCE).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
                if version.exists() or version.is_symlink():
                    raise ValueError("Version destination appeared during the build; refusing to overwrite it")
                package.rename(version)
    verify_version(version, patch_hash)
    stable_version(root)
    temporary_link = root / f".btop-view-link-{uuid.uuid4().hex}"
    try:
        temporary_link.symlink_to(version.name)
        temporary_link.replace(root / STABLE)
    finally:
        temporary_link.unlink(missing_ok=True)
    return version / "usr/bin/btop-view"


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="reuse the pinned local btop source tar.gz")
    parser.add_argument("--destination", type=Path,
                        default=Path.home() / ".local/share/dotfiles/tools/sysmon",
                        help="user install root (default: ~/.local/share/dotfiles/tools/sysmon)")
    parser.add_argument("--jobs", type=positive_integer, default=2, help="parallel build jobs (default: 2)")
    parser.add_argument("--check", action="store_true", help="verify the installed build without downloading or writing")
    args = parser.parse_args(argv)
    try:
        result = check(args.destination) if args.check else prepare(args.destination, args.archive, args.jobs)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(f"build-monitor: {error}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
