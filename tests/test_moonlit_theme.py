"""Contract checks for the opt-in theme generator and readable semantic colors."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "moonlit-theme.py"
SPEC = importlib.util.spec_from_file_location("moonlit_theme", SCRIPT)
THEME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(THEME)
PALETTE = json.loads((ROOT / "config" / "moonlit" / "palette.json").read_text())


class MoonlitThemeTests(unittest.TestCase):
    def run_generator(self, root, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args],
                              capture_output=True, text=True, check=False)

    def make_root(self, root, palette=None):
        destination = root / "config" / "moonlit"
        destination.mkdir(parents=True)
        (destination / "palette.json").write_text(json.dumps(PALETTE if palette is None else palette))
        return destination

    def test_contrast_uses_linear_srgb(self):
        self.assertAlmostEqual(THEME.contrast("#ffffff", "#000000"), 21.0)
        self.assertAlmostEqual(THEME.contrast("#777777", "#ffffff"), 4.47809, places=4)
        self.assertAlmostEqual(THEME.contrast("#777777", "#777777"), 1.0)
        ratios = THEME.validate_palette(PALETTE)
        self.assertGreaterEqual(ratios["secondary text on surface"], 4.5)
        self.assertGreaterEqual(ratios["body on surface"], 7.0)

    def test_unreadable_palette_is_rejected_before_writing(self):
        bad = dict(PALETTE, foreground=PALETTE["background"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = self.make_root(root, bad)
            sentinel = destination / "kitty-theme.conf"
            sentinel.write_text("original working theme\n")
            result = self.run_generator(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Contrast", result.stderr)
            self.assertEqual(sentinel.read_text(), "original working theme\n")
            self.assertEqual(sorted(p.name for p in destination.iterdir()), ["kitty-theme.conf", "palette.json"])

    def test_diagnostic_semantics_cannot_collapse_to_one_accent(self):
        with self.assertRaisesRegex(ValueError, "Semantic colors"):
            THEME.validate_palette(dict(PALETTE, error=PALETTE["success"]))

    def test_generation_is_scoped_and_inherits_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = self.make_root(root)
            (root / "existing-shared-config").write_text("keep this\n")
            result = self.run_generator(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            created = {str(p.relative_to(destination)) for p in destination.rglob("*") if p.is_file()}
            self.assertEqual(created, set(THEME.OUTPUTS) | {"palette.json"})
            self.assertEqual((root / "existing-shared-config").read_text(), "keep this\n")
            kitty = (destination / "kitty-theme.conf").read_text()
            directives = [line for line in kitty.splitlines() if line and not line.startswith("#")]
            self.assertFalse(any(line.startswith(("map ", "font_size ", "font_family ")) for line in directives))
            self.assertIn("background_opacity 0.86", directives)
            self.assertEqual(self.run_generator(root, "--check").returncode, 0)

    def test_check_detects_drift_without_overwriting_it(self):
        for name in ("nvim-theme.lua", "btop.theme"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                destination = self.make_root(root)
                self.assertEqual(self.run_generator(root).returncode, 0)
                changed = destination / name
                changed.write_text("# handwritten preview change\n")
                result = self.run_generator(root, "--check")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                self.assertEqual(changed.read_text(), "# handwritten preview change\n")

    def test_checked_in_theme_has_no_drift(self):
        result = self.run_generator(ROOT, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("nvim"), "Linux Neovim required")
    def test_deployed_editor_palette_is_optional_and_personal_override_loads_last(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config"
            (config / "moonlit").mkdir(parents=True)
            (config / "dotfiles-local").mkdir()
            theme = config / "moonlit/nvim-theme.lua"
            shutil.copyfile(ROOT / "config/moonlit/nvim-theme.lua", theme)
            (config / "dotfiles-local/nvim.lua").write_text(
                'vim.g.desktop_seen = vim.api.nvim_get_hl(0, {name="NormalFloat"}).bg\n'
                'vim.api.nvim_set_hl(0, "NormalFloat", {bg="#123456"})\n')
            env = dict(os.environ, XDG_CONFIG_HOME=str(config), XDG_DATA_HOME=str(root / "data"),
                       XDG_STATE_HOME=str(root / "state"), XDG_CACHE_HOME=str(root / "cache"),
                       DOTFILES_NVIM_NO_PLUGINS="1")
            for expected in ("251d30", "241d29"):
                result = subprocess.run(["nvim", "--headless", "-i", "NONE", "-u", str(ROOT / "config/nvim/init.lua"),
                    "+lua assert(vim.g.desktop_seen == tonumber('" + expected + "', 16)); "
                    "assert(vim.api.nvim_get_hl(0, {name='NormalFloat'}).bg == tonumber('123456',16)); "
                    "assert(vim.o.clipboard == '' and vim.fn.maparg('<CR>', 'i') == '')", "+qa"],
                    env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Error", result.stderr)
                theme.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
