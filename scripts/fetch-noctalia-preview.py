#!/usr/bin/env python3
"""Fetch the pinned Arch Noctalia preview into an owned local folder; no install.

Default: REPO/local/noctalia-5.2.1 (ignored by Git). Requires bsdtar, pacman-key,
and Python with zstd tar support (Python 3.14 on the inspected Arch snapshot).
--check performs no download. --package-dir reuses already downloaded packages.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import posixpath
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MARKER = '.configs-noctalia-preview.json'
OWNER = {'owner': 'Configs isolated Noctalia preview', 'schema': 1, 'version': '5.2.1'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def destination(path, create=False):
    if path.is_symlink():
        raise ValueError('Destination must not be a symbolic link')
    marker = path / MARKER
    if path.exists():
        if not path.is_dir():
            raise ValueError('Destination is not a directory')
        if any(path.iterdir()):
            if marker.is_symlink() or not marker.is_file() or json.loads(marker.read_text()) != OWNER:
                raise ValueError('Refusing unrelated existing destination; choose a fresh folder')
    elif not create:
        raise ValueError('Preview destination does not exist')
    if not create and not marker.is_file():
        raise ValueError('Destination has no preview ownership marker')
    for name in ('packages', 'prefix'):
        if (path / name).is_symlink():
            raise ValueError(f'Refusing symbolic-link {name} directory')
    if create:
        path.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(OWNER, sort_keys=True) + '\n')
    return path.resolve()


def download(url, target):
    if not url.startswith('https://archive.archlinux.org/packages/'):
        raise ValueError('Package URL must use the official Arch archive')
    temporary = target.with_suffix(target.suffix + '.part')
    if target.is_symlink() or temporary.is_symlink():
        raise ValueError('Refusing symbolic-link download target')
    with urllib.request.urlopen(url, timeout=30) as response, temporary.open('wb') as output:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 64 * 1024 * 1024:
                raise ValueError('Package download exceeded 64 MiB')
            output.write(chunk)
    temporary.replace(target)


def verify(package, entry):
    if package.is_symlink() or digest(package) != entry['sha256']:
        raise ValueError('SHA-256 mismatch: ' + package.name)
    signature = Path(str(package) + '.sig')
    if signature.is_symlink():
        raise ValueError('Refusing symbolic-link signature')
    subprocess.run(['pacman-key', '--verify', str(signature), str(package)], check=True, timeout=30)


def inspect_archive(package):
    """Allow safe usr files only; inspect links before invoking bsdtar extraction."""
    with tarfile.open(package, 'r:*') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('Unsafe archive path: ' + member.name)
            if not name.parts or name.parts[0] != 'usr':
                continue  # Arch metadata and install scripts are never extracted.
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError('Special archive member: ' + member.name)
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                resolved = posixpath.normpath(str(name.parent / link) if member.issym() else str(link))
                if link.is_absolute() or not resolved.startswith('usr/'):
                    raise ValueError('Unsafe archive link: ' + member.name)


def prepare(dest, manifest, package_dir=None):
    dest = destination(dest, create=True)
    prefix, packages = dest / 'prefix', dest / 'packages'
    if prefix.exists():
        raise ValueError('Prefix already exists; use --check or choose a new destination')
    packages.mkdir(exist_ok=True)
    for entry in manifest['packages']:
        name = entry['file']
        if Path(name).name != name:
            raise ValueError('Unsafe package filename')
        target = packages / name
        for suffix, url in (('', entry['url']), ('.sig', entry['signature_url'])):
            output = Path(str(target) + suffix)
            if output.is_symlink():
                raise ValueError('Refusing symbolic-link package target')
            if package_dir:
                shutil.copyfile(package_dir / (name + suffix), output)
            else:
                download(url, output)
        verify(target, entry)
        inspect_archive(target)
    # Every package has passed both signature/hash and path checks before any extraction.
    prefix.mkdir()
    for entry in manifest['packages']:
        subprocess.run(['bsdtar', '-xf', str(packages / entry['file']), '-C', str(prefix),
                        '--no-same-owner', '--no-same-permissions', '--safe-writes', 'usr'],
                       check=True, timeout=60)
    (dest / 'runtime.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return dest


def check(dest, manifest):
    dest = destination(dest)
    for entry in manifest['packages']:
        verify(dest / 'packages' / entry['file'], entry)
    prefix = dest / 'prefix'
    binary = prefix / 'usr/bin/noctalia'
    if not binary.is_file() or binary.is_symlink():
        raise ValueError('Missing or unsafe preview binary')
    package = next(p for p in manifest['packages'] if p['name'] == 'noctalia')
    with tarfile.open(dest / 'packages' / package['file'], 'r:*') as archive:
        original = archive.extractfile('usr/bin/noctalia')
        if original is None or hashlib.file_digest(original, 'sha256').hexdigest() != digest(binary):
            raise ValueError('Extracted binary differs from verified package')
    result = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=10,
                            env=dict(os.environ, LD_LIBRARY_PATH=str(prefix / 'usr/lib')), check=True)
    if result.stdout.strip() != 'noctalia v' + manifest['upstream_version']:
        raise ValueError('Unexpected runtime version: ' + result.stdout.strip())
    print(result.stdout.strip() + ' verified at ' + str(prefix))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / 'local/noctalia-5.2.1')
    parser.add_argument('--package-dir', type=Path, help='reuse local signed package downloads')
    parser.add_argument('--check', action='store_true', help='verify existing packages and binary without downloads')
    args = parser.parse_args()
    try:
        manifest = json.loads((ROOT / 'config/moonlit/runtime.json').read_text())
        if not args.check:
            prepare(args.destination, manifest, args.package_dir)
        check(args.destination, manifest)
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Preview runtime failed: {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
