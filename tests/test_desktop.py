"""Offline controls regression tests; never contact a compositor/user manager."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "desktopctl", Path(__file__).resolve().parents[1] / "config/desktop/desktopctl.py")
desktopctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desktopctl)
try:
    from PIL import Image
except ImportError:
    Image = None


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="desktop-tests-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            "HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root / "custom config"),
            "XDG_STATE_HOME": str(self.root / "custom state"),
            "XDG_DATA_HOME": str(self.root / "custom data"),
            "XDG_RUNTIME_DIR": str(self.root / "runtime"),
            "NIRI_SOCKET": str(self.root / "niri.sock"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.desktop = desktopctl.Desktop()
        self.commands = []
        self.systemctl = mock.patch.object(desktopctl, "systemctl", side_effect=self.control)
        self.systemctl.start()
        self.addCleanup(self.systemctl.stop)
        self.peer = mock.patch.object(desktopctl, "niri_peer_pid", return_value=42)
        self.peer.start()
        self.addCleanup(self.peer.stop)

    def control(self, *args, **kwargs):
        self.commands.append(args)
        return subprocess.CompletedProcess(args, 0, "42\n")

    def image(self, name="壁纸 with spaces.png"):
        if Image is None:
            self.skipTest("Pillow only required by the optional desktop profile")
        path = self.root / name
        Image.new("RGB", (32, 18), "pink").save(path)
        return path

    def test_invalid_settings_recover_without_changing_other_files(self):
        for value in ("not json", "[]", '{"bar_profile": "unknown", "wallpaper": 42}'):
            desktopctl.atomic_write(self.desktop.state, value)
            self.assertEqual(self.desktop.settings(), {"bar_profile": "balanced", "wallpaper": None})
        self.desktop.save(bar_profile="focus")
        self.assertEqual(self.desktop.state.stat().st_mode & 0o777, 0o600)

    def test_profile_persists_and_only_restarts_owned_bar(self):
        for profile in desktopctl.PROFILES:
            self.desktop.bar(profile)
            self.assertEqual(desktopctl.Desktop().settings()["bar_profile"], profile)
        self.assertEqual(self.commands, [("--no-block", "try-restart", "dotfiles-niri-waybar.service")] * 3)

    def test_invalid_profile_is_rejected_without_writes(self):
        with self.assertRaises(desktopctl.DesktopError):
            self.desktop.bar("bad; command")
        self.assertFalse(self.desktop.state.exists())
        self.assertFalse(self.commands)

    def test_cancelled_profile_menu_has_no_side_effect(self):
        with mock.patch.object(self.desktop, "menu_select", return_value=None):
            self.desktop.bar("menu")
        self.assertFalse(self.desktop.state.exists())
        self.assertFalse(self.commands)

    def test_wallpaper_filename_is_data_not_a_command(self):
        path = self.image("中文 ' $(touch pwned); wallpaper.png")
        self.desktop.wallpaper("set", str(path))
        self.assertEqual(self.desktop.selected_wallpaper(), path)
        self.assertEqual(self.desktop.settings()["wallpaper"], str(path))
        self.assertEqual(self.commands, [("--no-block", "try-restart", "dotfiles-niri-wallpaper.service")])
        self.assertFalse((self.root / "pwned").exists())

    def test_bad_wallpaper_does_not_replace_previous_selection(self):
        self.desktop.wallpaper("set", str(self.image()))
        previous = self.desktop.state.read_bytes()
        invalid = self.root / "broken.png"
        invalid.write_text("this is not an image")
        with self.assertRaises(desktopctl.DesktopError):
            self.desktop.wallpaper("set", str(invalid))
        self.assertEqual(self.desktop.state.read_bytes(), previous)

    def test_truncated_jpeg_is_rejected_before_selection(self):
        self.desktop.wallpaper("set", str(self.image()))
        previous = self.desktop.state.read_bytes()
        broken = self.root / "truncated.jpg"
        Image.new("RGB", (100, 100), "pink").save(broken)
        broken.write_bytes(broken.read_bytes()[:-20])
        with self.assertRaises(desktopctl.DesktopError):
            self.desktop.wallpaper("set", str(broken))
        self.assertEqual(self.desktop.state.read_bytes(), previous)

    def test_wallpaper_missing_selection_default_then_solid(self):
        selected = self.image()
        self.desktop.wallpaper("set", str(selected))
        self.desktop.data.mkdir(parents=True)
        fallback = self.desktop.data / "default.jpg"
        Image.new("RGB", (32, 18), "black").save(fallback)
        selected.unlink()
        self.assertEqual(self.desktop.selected_wallpaper(), fallback)
        fallback.unlink()
        self.assertIsNone(self.desktop.selected_wallpaper())

    def test_reset_preserves_profile(self):
        self.desktop.save(bar_profile="performance", wallpaper="/missing/image.png")
        self.desktop.wallpaper("reset")
        self.assertEqual(self.desktop.settings(), {"bar_profile": "performance", "wallpaper": None})

    def test_cancelled_file_chooser_preserves_selection(self):
        self.desktop.save(wallpaper="/old.png")
        with mock.patch.object(desktopctl, "command", return_value=subprocess.CompletedProcess([], 1, "")):
            self.desktop.wallpaper("choose")
        self.assertEqual(self.desktop.settings()["wallpaper"], "/old.png")
        self.assertFalse(self.commands)

    def download_metadata(self, payload):
        path = self.desktop.config / "niri/wallpaper.json"
        desktopctl.atomic_write(path, json.dumps({
            "url": "https://example.invalid/wallpaper.png", "width": 32, "height": 18,
            "sha256": hashlib.sha256(payload).hexdigest()}))

    def test_default_download_verifies_pixels_hash_and_uses_cache(self):
        payload = self.image().read_bytes()
        self.download_metadata(payload)
        with mock.patch.object(desktopctl.urllib.request, "urlopen", return_value=io.BytesIO(payload)) as download:
            with contextlib.redirect_stdout(io.StringIO()):
                self.desktop.fetch_wallpaper()
                self.desktop.fetch_wallpaper()
            self.assertEqual(download.call_count, 1)
        self.assertEqual((self.desktop.data / "default.jpg").read_bytes(), payload)

    def test_changed_remote_image_preserves_existing_cache(self):
        payload = self.image().read_bytes()
        self.download_metadata(payload)
        self.desktop.data.mkdir(parents=True)
        target = self.desktop.data / "default.jpg"
        target.write_bytes(b"old cached content")
        with mock.patch.object(desktopctl.urllib.request, "urlopen", return_value=io.BytesIO(b"wrong download")):
            with self.assertRaisesRegex(desktopctl.DesktopError, "checksum"):
                self.desktop.fetch_wallpaper()
        self.assertEqual(target.read_bytes(), b"old cached content")
        self.assertEqual(list(self.desktop.data.iterdir()), [target])

    def test_hardware_modules_only_appear_on_supported_hardware(self):
        sysfs = self.root / "sysfs"
        modules = {"modules-right": ["clock", "battery", "backlight", "cpu"]}
        self.desktop.filter_hardware(modules, sysfs)
        self.assertEqual(modules["modules-right"], ["clock", "cpu"])
        battery = sysfs / "power_supply/BAT9/type"
        battery.parent.mkdir(parents=True)
        battery.write_text("Battery\n")
        (sysfs / "backlight/intel_backlight").mkdir(parents=True)
        modules = {"modules-right": ["battery", "backlight"]}
        self.desktop.filter_hardware(modules, sysfs)
        self.assertEqual(modules["modules-right"], ["battery", "backlight"])

    def test_session_guard_does_not_start_niri_from_gnome(self):
        with mock.patch.dict(os.environ, {"NIRI_SOCKET": ""}):
            with self.assertRaises(desktopctl.DesktopError):
                self.desktop.session_start()
        self.assertFalse(self.commands)
        self.assertFalse(self.desktop.runtime().exists())

    def test_nested_niri_cannot_modify_main_session_services(self):
        with mock.patch.object(desktopctl, "niri_peer_pid", return_value=900):
            with self.assertRaisesRegex(desktopctl.DesktopError, "nested"):
                self.desktop.session_start()
        self.assertEqual(self.commands, [("show", "--property=MainPID", "--value", "niri.service")])
        self.assertFalse(self.desktop.runtime().exists())

    def test_new_session_resets_lecture_but_not_saved_preferences(self):
        self.desktop.save(bar_profile="focus", wallpaper="/custom.png")
        flag = self.desktop.runtime() / "presentation"
        desktopctl.atomic_write(flag, "on\n")
        self.desktop.session_start()
        self.assertFalse(flag.exists())
        self.assertEqual(self.desktop.settings()["bar_profile"], "focus")
        started = self.commands[-1]
        self.assertEqual(started[0], "start")
        self.assertIn("dotfiles-niri-idle.service", started)
        self.assertIn("dotfiles-niri-session-events.service", started)
        self.assertNotIn("dotfiles-niri-lock.service", started)

    def test_lecture_survives_bar_restart_and_keeps_sleep_lock_events(self):
        with mock.patch.object(desktopctl, "command", return_value=subprocess.CompletedProcess([], 0)):
            self.desktop.presentation("toggle")
        flag = self.desktop.runtime() / "presentation"
        self.assertTrue(flag.exists())
        self.desktop.bar("focus")
        self.assertTrue(flag.exists())
        self.desktop.presentation("toggle")
        self.assertFalse(flag.exists())
        self.assertEqual(self.desktop.settings()["bar_profile"], "focus")
        mutations = [c for c in self.commands if c[0] != "show"]
        self.assertEqual(mutations, [("stop", "dotfiles-niri-idle.service"),
                                    ("--no-block", "try-restart", "dotfiles-niri-waybar.service"),
                                    ("start", "dotfiles-niri-idle.service")])

    def test_failed_idle_stop_does_not_claim_lecture_is_active(self):
        def fail(*args, **kwargs):
            if args[0] == "stop":
                raise desktopctl.DesktopError("service failed")
            return subprocess.CompletedProcess(args, 0, "42\n")
        with mock.patch.object(desktopctl, "systemctl", side_effect=fail):
            with self.assertRaises(desktopctl.DesktopError):
                self.desktop.presentation("toggle")
        self.assertFalse((self.desktop.runtime() / "presentation").exists())

    def test_sleep_events_use_independent_lock_service(self):
        with mock.patch.object(desktopctl.os, "execvp") as execute:
            self.desktop.idle(events=True)
        argv = execute.call_args.args[1]
        self.assertIn("before-sleep", argv)
        self.assertIn("lock", argv)
        self.assertIn("systemctl --user start dotfiles-niri-lock.service", argv)
        self.assertNotIn("timeout", argv)
        self.assertNotIn("swaylock", " ".join(argv))

    def test_missing_or_failing_gpu_is_hidden(self):
        for executable, result in ((None, None), ("/usr/bin/nvidia-smi", subprocess.CompletedProcess([], 1, ""))):
            output = io.StringIO()
            with mock.patch.object(desktopctl.shutil, "which", return_value=executable), \
                    mock.patch.object(desktopctl, "command", return_value=result), \
                    contextlib.redirect_stdout(output):
                desktopctl.metrics("gpu")
            self.assertEqual(json.loads(output.getvalue())["text"], "")


if __name__ == "__main__":
    unittest.main()
