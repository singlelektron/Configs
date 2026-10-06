"""Interrupted preference changes must remain recoverable without losing newer choices."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("appearance", Path(__file__).resolve().parents[1] / "scripts/desktop-appearance.py")
appearance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(appearance)


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.backup = Path(temp.name) / "original.json"
        self.original = {key: "'old-" + key + "'" for key in appearance.SETTINGS}
        self.values = dict(self.original)
        self.fail_key = None
        self.setter_calls = []
        mock = patch.object(appearance, "gsettings", side_effect=self.gsettings)
        mock.start()
        self.addCleanup(mock.stop)

    def gsettings(self, action, schema, *args):
        if action == "list-keys":
            return "\n".join(self.values)
        if action == "get":
            return self.values[args[0]]
        key, value = args
        self.setter_calls.append(key)
        if key == self.fail_key:
            raise subprocess.CalledProcessError(1, "gsettings")
        self.values[key] = value
        return ""

    def test_partial_apply_can_restore(self):
        self.fail_key = "gtk-theme"
        with self.assertRaises(subprocess.CalledProcessError):
            appearance.apply(self.backup, write=True)
        self.assertNotEqual(self.values, self.original)
        self.fail_key = None
        appearance.apply(self.backup, write=True, restore=True)
        self.assertEqual(self.values, self.original)
        self.assertFalse(self.backup.exists())

    def test_partial_restore_can_retry(self):
        appearance.apply(self.backup, write=True)
        self.fail_key = "gtk-theme"
        with self.assertRaises(subprocess.CalledProcessError):
            appearance.apply(self.backup, write=True, restore=True)
        self.assertTrue(self.backup.exists())
        self.fail_key = None
        appearance.apply(self.backup, write=True, restore=True)
        self.assertEqual(self.values, self.original)
        self.assertFalse(self.backup.exists())

    def test_newer_user_value_blocks_all_restoration(self):
        appearance.apply(self.backup, write=True)
        self.values["font-name"] = "'My font 12'"
        before = dict(self.values)
        self.setter_calls.clear()
        with self.assertRaisesRegex(ValueError, "newer preference"):
            appearance.apply(self.backup, write=True, restore=True)
        self.assertEqual(self.values, before)
        self.assertEqual(self.setter_calls, [])
        self.assertTrue(self.backup.exists())

    def test_reapply_retains_original_and_dry_run_does_not_write(self):
        appearance.apply(self.backup)
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.values, self.original)
        appearance.apply(self.backup, write=True)
        before = self.backup.read_bytes()
        appearance.apply(self.backup, write=True)
        self.assertEqual(self.backup.read_bytes(), before)
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
        appearance.apply(self.backup, write=True, restore=True)
        self.assertEqual(self.values, self.original)
