#!/usr/bin/env bash
# Install software only. Config deployment is a separate, reversible operation.
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
apply=false
desktop=""
usage() { echo 'Usage: bash scripts/install-tools.sh [--desktop niri] [--apply]'; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true; shift ;;
    --desktop)
      if [ "$#" -lt 2 ] || [ "$2" != niri ] || [ -n "$desktop" ]; then
        usage >&2; exit 2
      fi
      desktop=$2
      shift 2
      ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

system=$(uname -s)
if [ -n "$desktop" ] && [ "$system" != Linux ]; then
  echo 'The niri desktop profile is Linux-only (Arch/pacman).' >&2
  exit 1
fi

run() {
  printf '  '
  printf '%q ' "$@"
  printf '\n'
  if "$apply"; then "$@"; fi
}

# Existing Rust/uv installations may not be on a noninteractive SSH PATH.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v rustup >/dev/null 2>&1; then
  echo "Install rustup first using https://rustup.rs/ (then rerun this script)." >&2
  if "$apply"; then exit 1; fi
fi

case "$system" in
  Darwin)
    if ! command -v brew >/dev/null 2>&1; then
      echo "Install Homebrew from https://brew.sh/ and load brew shellenv first." >&2
      if "$apply"; then exit 1; fi
    fi
    # Do not upgrade existing tools as an incidental side effect of setup.
    run env HOMEBREW_NO_AUTO_UPDATE=1 brew bundle install --no-upgrade --file="$repo_dir/packages/Brewfile"
    ;;
  Linux)
    if ! command -v pacman >/dev/null 2>&1; then
      echo "Only Arch Linux (and pacman-based derivatives) is supported." >&2
      exit 1
    fi
    arch_packages=()
    while IFS= read -r package || [ -n "$package" ]; do
      case "$package" in ""|\#*) continue ;; esac
      arch_packages+=("$package")
    done < "$repo_dir/packages/arch.txt"
    if [ "$desktop" = niri ]; then
      while IFS= read -r package || [ -n "$package" ]; do
        case "$package" in ""|\#*) continue ;; esac
        arch_packages+=("$package")
      done < "$repo_dir/packages/arch-niri.txt"
    fi
    # A full upgrade is required: Arch does not support partial upgrades.
    # Leave pacman's confirmation and sudo authentication interactive.
    run sudo pacman -Syu --needed "${arch_packages[@]}"
    ;;
  *) echo "Supported systems: macOS, Arch Linux" >&2; exit 1 ;;
esac

run rustup component add rust-analyzer rustfmt clippy rust-src
while IFS= read -r package || [ -n "$package" ]; do
  case "$package" in ""|\#*) continue ;; esac
  run uv tool install "$package"
done < "$repo_dir/packages/python-tools.txt"

if "$apply"; then
  echo 'Tools installed. Ensure ~/.local/bin and ~/.cargo/bin are on your shell PATH.'
  if [ "$desktop" = niri ]; then
    echo 'Next: python3 scripts/deploy.py --desktop niri (preview), then add --apply.'
    echo 'The installer does not enable services or change your login session.'
  else
    echo 'Next: python3 scripts/deploy.py (preview), then add --apply.'
  fi
else
  echo 'Preview only. Add --apply to install tools; Arch may upgrade the system.'
fi
