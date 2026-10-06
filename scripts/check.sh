#!/usr/bin/env bash
# Offline checks. All editor state is confined to a disposable directory.
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_dir"
python3 -m unittest discover -s tests -p 'test_*.py' -v
if command -v node >/dev/null 2>&1; then
  node --test config/quickshell/tests/logic.test.cjs
else
  echo 'SKIP Quickshell state helper tests: Node.js is not installed.'
fi
python3 config/quickshell/tests/run_volume_ui.py
bash -n scripts/install-tools.sh scripts/check.sh
sh -n config/desktop/terminal-bin/xdg-terminal-exec

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
assert options.background_opacity == 0.86
assert options.dynamic_background_opacity
assert options.background == type(options.background)(27, 23, 34)
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

if [[ "$(uname -s)" == Linux ]] && command -v niri >/dev/null 2>&1; then
  if [[ -x /usr/lib/qt6/bin/qmllint ]] && command -v quickshell >/dev/null 2>&1; then
    # Quickshell's shipped qtypes omit two native metatypes; runtime tests cover them.
    /usr/lib/qt6/bin/qmllint -I /usr/lib/qt6/qml -W 0 \
      --signal-handler-parameters info --uncreatable-type info \
      config/quickshell/desktop-island/*.qml
    echo 'Quickshell QML static analysis: PASS'
  else
    echo 'SKIP QML static analysis: Quickshell or qmllint is not installed.'
  fi
  python3 scripts/deploy.py --home "$test_root" --desktop niri --apply

  check_niri_config() {
    local isolated_home="$1" isolated_config="$2" label="$3"
    local -a isolated_env=(env HOME="$isolated_home"
      XDG_CONFIG_HOME="$isolated_config"
      XDG_DATA_HOME="$isolated_home/.local/share"
      XDG_STATE_HOME="$isolated_home/.local/state"
      XDG_CACHE_HOME="$isolated_home/.cache")
    # Parse the deployed symlink, so relative includes must find this XDG root.
    "${isolated_env[@]}" niri validate --config "$isolated_config/niri/config.kdl"
    mkdir -p "$isolated_config/dotfiles-local"
    printf 'layout { gaps 12; }\n' > "$isolated_config/dotfiles-local/niri.kdl"
    "${isolated_env[@]}" niri validate --config "$isolated_config/niri/config.kdl"
    printf 'dotfiles-invalid-option true\n' > "$isolated_config/dotfiles-local/niri.kdl"
    if "${isolated_env[@]}" niri validate --config "$isolated_config/niri/config.kdl" \
      > "$test_root/niri-invalid-$label.log" 2>&1; then
      echo "FAIL: Niri ignored the invalid local include ($label)." >&2
      exit 1
    fi
    # A malformed local override must fail visibly rather than be silently ignored.
    printf 'layout { gaps 12; }\n' > "$isolated_config/dotfiles-local/niri.kdl"
    echo "Niri deployed config and absent/valid/invalid local include ($label): PASS"
  }

  check_niri_config "$test_root" "$test_root/.config" default
  custom_home="$test_root/xdg-home"
  custom_config="$test_root/custom config"
  mkdir -p "$custom_home"
  env HOME="$custom_home" XDG_CONFIG_HOME="$custom_config" \
    XDG_STATE_HOME="$test_root/custom state" \
    python3 scripts/deploy.py --desktop niri --apply
  check_niri_config "$custom_home" "$custom_config" custom-xdg

  if command -v fuzzel >/dev/null 2>&1; then
    env HOME="$test_root" XDG_CONFIG_HOME="$test_root/.config" \
      fuzzel --check-config --config "$test_root/.config/fuzzel/fuzzel.ini"
    echo 'Fuzzel configuration parsing: PASS'
  else
    echo 'SKIP Fuzzel parser check: fuzzel is not installed.'
  fi
  python3 - "$test_root/.config/waybar/style.css" "$test_root/.config/gtklock/style.css" \
    "$test_root/.config/niri/settings-theme/themes/DotfilesSettings/gtk-3.0/gtk.css" <<'PY'
import sys
try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except (ImportError, ValueError):
    print("SKIP Waybar CSS parsing: Python GObject / GTK 3 is not installed.")
    sys.exit(0)

for path in sys.argv[1:]:
    errors = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _, section, error: errors.append(str(error)))
    provider.load_from_path(path)
    assert not errors, path + ": " + "; ".join(errors)
print("Waybar, GTKLock and settings GTK 3 CSS parsing: PASS")
PY

  python3 - "$test_root/.config/niri/panel.css" \
    "$test_root/.config/niri/settings-theme/themes/DotfilesSettings/gtk-4.0/gtk.css" <<'PY'
import sys
try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except (ImportError, ValueError):
    print("SKIP control panel CSS parsing: Python GObject / GTK 4 is not installed.")
    sys.exit(0)

for path in sys.argv[1:]:
    errors = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _, section, error: errors.append(str(error)))
    provider.load_from_path(path)
    assert not errors, path + ": " + "; ".join(errors)
print("Control panel and settings GTK 4 CSS parsing: PASS")
PY

  if command -v systemd-analyze >/dev/null 2>&1; then
    # Static parsing only: never enable/start units or contact the user manager.
    env HOME="$test_root" XDG_CONFIG_HOME="$test_root/.config" \
      systemd-analyze --user --man=no --recursive-errors=no verify \
      "$test_root/.config/systemd/user/"dotfiles-niri-*.service
    echo 'Niri user services static verification: PASS'
  else
    echo 'SKIP systemd unit validation: systemd-analyze is not installed.'
  fi
else
  echo 'SKIP desktop parser checks: Niri is not installed on this Linux host, or this is macOS.'
fi
echo 'Offline checks passed. This does not verify a graphical session or live LSP attachment.'
