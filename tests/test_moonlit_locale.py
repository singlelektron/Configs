"""Native translation catalogs must stay complete without translating diagnostics."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "config/moonlit/plugins"


def flattened(value, prefix=""):
    out = {}
    for key, item in value.items():
        full = f"{prefix}.{key}" if prefix else key
        out.update(flattened(item, full) if isinstance(item, dict) else {full: item})
    return out


class LocalizationTests(unittest.TestCase):
    def test_plugin_catalog_keys_and_substitutions_match(self):
        for plugin in ("moonlit-network", "moonlit-updates"):
            path = PLUGINS / plugin / "translations"
            english = flattened(json.loads((path / "en.json").read_text()))
            chinese = flattened(json.loads((path / "zh-Hans.json").read_text()))
            self.assertEqual(english.keys(), chinese.keys(), plugin)
            for key in english:
                self.assertTrue(chinese[key], f"{plugin}:{key}")
                self.assertEqual(set(re.findall(r"\{(\w+)\}", english[key])),
                                 set(re.findall(r"\{(\w+)\}", chinese[key])), f"{plugin}:{key}")

    def test_network_panel_localized_errors_and_late_callback(self):
        nvim = shutil.which("nvim")
        if not nvim:
            self.skipTest("Neovim Lua runtime is required")
        with tempfile.TemporaryDirectory() as root:
            for language in ("en", "zh-Hans"):
                env = dict(os.environ, MOONLIT_NETWORK_PANEL=str(PLUGINS / "moonlit-network/panel.luau"),
                           MOONLIT_TEST_LANGUAGE=language, XDG_STATE_HOME=root, XDG_CACHE_HOME=root)
                result = subprocess.run([nvim, "--headless", "-u", "NONE", "-i", "NONE", "-l",
                                         str(ROOT / "tests/moonlit_network_panel.lua")],
                                        env=env, capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("lifecycle: PASS", result.stdout + result.stderr)

    def test_terminal_uses_same_catalog_and_preserves_raw_diagnostic(self):
        spec = importlib.util.spec_from_file_location("localized_updates", PLUGINS / "moonlit-updates/updates.py")
        updates = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updates)
        data = {**updates.empty(), "error": "mirror.example: connection refused"}
        output = io.StringIO()
        with patch.object(updates, "status", return_value=data), patch.object(updates.os, "execvp"), contextlib.redirect_stdout(output):
            updates.terminal("zh-Hans")
        self.assertIn("尚未成功检查更新", output.getvalue())
        self.assertIn(data["error"], output.getvalue())
        self.assertIn("sudo pacman -Syu", output.getvalue())
        with patch.dict(updates.os.environ, NIRI_SOCKET="/test.sock"), patch.object(updates.subprocess, "run") as run:
            updates.review("zh-Hans")
        self.assertEqual(run.call_args.args[0][-3:], ["--language", "zh-Hans", "terminal"])
