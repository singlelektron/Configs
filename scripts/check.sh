#!/usr/bin/env bash
# Offline checks. All editor state is confined to a disposable directory.
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_dir"
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash -n scripts/install-tools.sh scripts/check.sh

test_root=$(python3 -c 'import tempfile,pathlib; print(pathlib.Path(tempfile.mkdtemp(prefix="dotfiles-check-")).resolve())')
trap 'rm -rf -- "$test_root"' EXIT
python3 scripts/deploy.py --home "$test_root" --apply
env XDG_CONFIG_HOME="$test_root/.config" \
  XDG_DATA_HOME="$test_root/.local/share" \
  XDG_STATE_HOME="$test_root/.local/state" \
  XDG_CACHE_HOME="$test_root/.cache" \
  DOTFILES_NVIM_NO_PLUGINS=1 \
  nvim --headless -i NONE -u config/nvim/init.lua '+lua dofile("tests/nvim.lua")'

if command -v kitty >/dev/null 2>&1; then
  mkdir -p "$test_root/.config/dotfiles-local"
  # Prove the local override is read after the shared config through the symlink.
  printf 'font_size 17.0\n' > "$test_root/.config/dotfiles-local/kitty.conf"
  env DOTFILES_KITTY_TEST_CONFIG="$test_root/.config/kitty/kitty.conf" kitty +runpy '
import os
import sys
from kitty.config import load_config
from kitty.options.utils import parse_key_action
bad = []
options = load_config(os.environ["DOTFILES_KITTY_TEST_CONFIG"], accumulate_bad_lines=bad)
assert not bad, bad
assert options.font_size == 17.0, "Local override did not load"
assert options.background_opacity == 0.88
assert options.dynamic_background_opacity
assert options.background == type(options.background)(22, 27, 38)
assert os.path.expanduser("~/.local/bin") in options.env["PATH"].split(":")
assert os.path.expanduser("~/.cargo/bin") in options.env["PATH"].split(":")
if sys.platform == "darwin":
    assert "/opt/homebrew/bin" in options.env["PATH"].split(":")
    assert "/usr/local/bin" in options.env["PATH"].split(":")
git_keys = [d.definition for definitions in options.keyboard_modes[""].keymap.values()
            for d in definitions if "lazygit" in d.definition]
assert len(git_keys) == 1
git_action = parse_key_action(git_keys[0])
assert git_action.args[-3:-1] == ("sh", "-c")
assert "${XDG_CONFIG_HOME:-$HOME/.config}/lazygit/config.yml" in git_action.args[-1]
print("Kitty parsing, shared theme and local override: PASS")
'
else
  echo 'SKIP Kitty parser check: kitty is not installed.'
fi
echo 'Offline checks passed. This does not verify a graphical session or live LSP attachment.'
