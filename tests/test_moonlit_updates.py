"""Update checks must not mutate pacman's live DB or hide failed checks as zero."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("updates", Path(__file__).resolve().parents[1] / "config/moonlit/plugins/moonlit-updates/updates.py")
updates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updates)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_check(self, code, output=""):
        with patch.object(updates.shutil, "which", return_value="/usr/bin/checkupdates"), patch.object(
                updates, "run_checkupdates", return_value=subprocess.CompletedProcess([], code, output, "")) as run:
            value = updates.check(self.root)
        self.assertEqual(run.call_args.args[0], ["checkupdates", "--nocolor"])
        self.assertEqual(run.call_args.args[1]["CHECKUPDATES_DB"], str(self.root / "db"))
        return value

    def test_success_and_empty_have_distinct_count(self):
        self.assertIsNone(updates.status(self.root)["count"])
        value = self.run_check(0, "linux 6.1 -> 6.2\nkitty 0.1 -> 0.2\n")
        self.assertEqual(value["count"], 2)
        self.assertEqual(value["status"], "ok")
        self.assertIsInstance(value["checked_at"], int)
        self.assertEqual(self.run_check(2)["count"], 0)

    def test_failed_check_keeps_last_good_data_and_marks_error(self):
        previous = self.run_check(0, "linux 6.1 -> 6.2\n")
        value = self.run_check(1)
        self.assertEqual(value["status"], "error")
        self.assertEqual(value["count"], 1)
        self.assertEqual(value["checked_at"], previous["checked_at"])
        self.assertEqual(value["packages"], previous["packages"])
        self.assertTrue(value["error"])

    def test_missing_tool_is_unknown_count_not_zero(self):
        with patch.object(updates.shutil, "which", return_value=None):
            value = updates.check(self.root)
        self.assertEqual(value["status"], "error")
        self.assertIsNone(value["count"])

    def test_timeout_is_recorded(self):
        with patch.object(updates.shutil, "which", return_value="checkupdates"), patch.object(
                updates, "run_checkupdates", side_effect=subprocess.TimeoutExpired("checkupdates", 90)):
            value = updates.check(self.root)
        self.assertEqual(value["status"], "error")
        self.assertIn("timed out", value["error"])

    def test_timeout_terminates_descendant_even_after_parent_exits(self):
        child_pid = self.root / "child.pid"
        child = ("import os,signal,time,pathlib; "
                 "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                 f"pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid())); "
                 "time.sleep(30)")
        parent = ("import subprocess,sys; "
                  f"p=subprocess.Popen([sys.executable,'-c',{child!r}], "
                  "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); p.wait()")
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                updates.run_checkupdates([sys.executable, "-c", parent], os.environ.copy(),
                                         timeout=0.5, grace=0.1)
            pid = int(child_pid.read_text())
            proc = Path(f"/proc/{pid}/stat")
            # An orphan can briefly remain a zombie until PID 1 reaps it.
            for _ in range(50):
                if not proc.exists() or proc.read_text().split()[2] == "Z":
                    break
                time.sleep(0.01)
            if proc.exists():
                self.assertEqual(proc.read_text().split()[2], "Z")
        finally:
            if child_pid.exists():
                try:
                    os.kill(int(child_pid.read_text()), 9)
                except ProcessLookupError:
                    pass

    def test_timeout_allows_shell_exit_trap_to_clean_its_lock(self):
        marker = self.root / "cleaned"
        script = self.root / "checkupdates-fixture"
        script.write_text('#!/bin/sh\ntrap \'printf cleaned > "$1"; exit\' TERM\nsleep 30 &\nwait\n')
        with self.assertRaises(subprocess.TimeoutExpired):
            updates.run_checkupdates(["/bin/sh", str(script), str(marker)], os.environ.copy(),
                                     timeout=0.2, grace=0.2)
        self.assertEqual(marker.read_text(), "cleaned")

    def test_bad_cache_recovers(self):
        for value in ("bad JSON", "[]", json.dumps({"status": "ok", "count": 1, "packages": []})):
            (self.root / "status.json").write_text(value)
            self.assertEqual(updates.status(self.root), updates.empty())

    def test_review_spawns_without_shell_interpolation(self):
        with patch.dict(updates.os.environ, {"NIRI_SOCKET": "/session.sock"}), patch.object(updates.subprocess, "run") as run:
            updates.review()
        args = run.call_args.args[0]
        self.assertEqual(args[:6], ["niri", "msg", "action", "spawn", "--", "kitty"])
        self.assertEqual(args[-1], "terminal")

    def test_widget_spawn_failure_invalid_data_and_recovery(self):
        nvim = updates.shutil.which("nvim")
        if not nvim:
            self.skipTest("Neovim Lua runtime is required for the actual widget regression")
        repo = Path(__file__).resolve().parents[1]
        env = dict(os.environ, XDG_STATE_HOME=str(self.root / "state"),
                   XDG_CACHE_HOME=str(self.root / "cache"),
                   MOONLIT_UPDATES_WIDGET=str(repo / "config/moonlit/plugins/moonlit-updates/widget.luau"))
        for language in ("en", "zh-Hans"):
            with self.subTest(language=language):
                result = subprocess.run([nvim, "--headless", "-u", "NONE", "-i", "NONE", "-l",
                                         str(repo / "tests/moonlit_updates_widget.lua")],
                                        env=dict(env, MOONLIT_TEST_LANGUAGE=language),
                                        capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("async failure and recovery: PASS", result.stdout + result.stderr)
