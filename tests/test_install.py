"""Exercise installer plans and guards with harmless tool replacements."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("doctor", REPO / "scripts/doctor.py")
doctor = importlib.util.module_from_spec(SPEC)
with mock.patch.object(sys, "path", [str(REPO / "scripts"), *sys.path]):
    SPEC.loader.exec_module(doctor)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls"
        self.env = {**os.environ, "HOME": str(self.root / "home"),
                    "PATH": f"{self.bin}:/usr/bin:/bin", "DOTFILES_TEST_LOG": str(self.log),
                    "DOTFILES_TEST_SYSTEM": "Linux"}
        self.executable("uname", '#!/bin/sh\nprintf "%s\\n" "$DOTFILES_TEST_SYSTEM"\n')
        for name in ("sudo", "pacman", "brew", "rustup", "uv"):
            self.executable(name, '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$DOTFILES_TEST_LOG"\n')

    def executable(self, name, contents):
        path = self.bin / name
        path.write_text(contents)
        path.chmod(0o755)

    def run_installer(self, *args, system="Linux"):
        return subprocess.run(["/usr/bin/bash", str(REPO / "scripts/install-tools.sh"), *args],
                              env={**self.env, "DOTFILES_TEST_SYSTEM": system},
                              capture_output=True, text=True, timeout=15)

    def test_default_preview_excludes_desktop_and_runs_no_tools(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pacman -Syu --needed", result.stdout)
        self.assertNotIn(" niri ", result.stdout)
        self.assertFalse(self.log.exists())

    def test_desktop_preview_includes_official_packages_without_execution(self):
        result = self.run_installer("--desktop", "niri")
        self.assertEqual(result.returncode, 0, result.stderr)
        for package in ("niri", "waybar", "swaylock", "xwayland-satellite", "fcitx5",
                        "xdg-desktop-portal-gnome", "pipewire-pulse"):
            self.assertIn(f" {package} ", result.stdout)
        self.assertNotIn(" steam ", result.stdout)
        self.assertFalse(self.log.exists())

    def test_desktop_apply_runs_single_full_package_transaction_without_services(self):
        result = self.run_installer("--apply", "--desktop", "niri")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text().splitlines()
        installs = [line for line in calls if "/sudo pacman" in line]
        self.assertEqual(len(installs), 1)
        self.assertIn("pacman -Syu --needed", installs[0])
        self.assertIn(" niri ", installs[0])
        self.assertFalse(any("systemctl" in line for line in calls))
        self.assertIn("deploy.py --desktop niri", result.stdout)

    def test_desktop_rejects_macos_before_any_installation(self):
        result = self.run_installer("--desktop", "niri", "--apply", system="Darwin")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Linux-only", result.stderr)
        self.assertFalse(self.log.exists())

    def test_invalid_arguments_fail_before_execution(self):
        for args in (("--desktop",), ("--desktop", "gnome"),
                     ("--desktop", "niri", "--desktop", "niri"), ("unexpected",)):
            with self.subTest(args=args):
                result = self.run_installer(*args)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.log.exists())

    def test_default_macos_preview_keeps_brew_behavior(self):
        result = self.run_installer(system="Darwin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("brew bundle install --no-upgrade", result.stdout)
        self.assertNotIn("pacman", result.stdout)
        self.assertFalse(self.log.exists())


class DoctorDesktopTests(unittest.TestCase):
    def test_main_keeps_parsed_options_through_core_version_checks(self):
        for args in ([], ["--desktop", "niri"]):
            with self.subTest(args=args):
                with mock.patch.object(doctor.platform, "system", return_value="Linux"), \
                        mock.patch.object(doctor, "locations", return_value=(Path("/tmp/config"), Path("/tmp/state"))), \
                        mock.patch.object(doctor, "entries_for", return_value=[]), \
                        mock.patch.object(doctor.shutil, "which", side_effect=lambda name: "/usr/bin/" + name), \
                        mock.patch.object(doctor.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "v0.11.3\n", "")), \
                        mock.patch.object(doctor, "check_desktop") as desktop_check, \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(doctor.main(args), 0)
                if args:
                    desktop_check.assert_called_once_with(Path("/tmp/config"), [])
                else:
                    desktop_check.assert_not_called()

    def test_macos_desktop_request_does_not_probe_tools(self):
        with mock.patch.object(doctor.platform, "system", return_value="Darwin"), \
                mock.patch.object(doctor.shutil, "which") as which, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(doctor.main(["--desktop", "niri"]), 1)
        which.assert_not_called()

    def test_desktop_minimum_version_and_validation_are_checked(self):
        def run(args, **kwargs):
            if args[:2] == ["niri", "--version"]:
                return subprocess.CompletedProcess(args, 0, "niri 25.11 (test)\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        missing = []
        with mock.patch.object(doctor.shutil, "which", side_effect=lambda name: "/usr/bin/" + name), \
                mock.patch.object(doctor.os, "access", return_value=True), \
                mock.patch.object(doctor.subprocess, "run", side_effect=run) as runner, \
                contextlib.redirect_stdout(io.StringIO()):
            doctor.check_desktop(Path("/tmp/custom-config"), missing)
        self.assertEqual(missing, ["Niri >= 26.04"])
        self.assertTrue(any(call.args[0] == ["niri", "validate", "--config", "/tmp/custom-config/niri/config.kdl"]
                            for call in runner.call_args_list))


if __name__ == "__main__":
    unittest.main()
