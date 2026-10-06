"""Music selection and reversible install checks; never play audio or contact Niri."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


music = module("music", "config/desktop/music.py")
installer = module("install_music", "scripts/install-music.py")


class MusicTests(unittest.TestCase):
    def test_native_player_wins_even_when_browser_is_playing(self):
        with mock.patch.object(music, "players", return_value=["firefox.instance1", music.MPRIS_NAME]), \
                mock.patch.object(music, "command") as run:
            self.assertEqual(music.selected_player(), music.MPRIS_NAME)
            run.assert_not_called()

    def test_other_active_player_is_selected_before_idle_player(self):
        with mock.patch.object(music, "players", return_value=["mpv", "firefox.instance1"]), \
                mock.patch.object(music, "command", side_effect=lambda argv, **_: subprocess.CompletedProcess(
                    [], 0, "Playing\n" if argv[2] == "firefox.instance1" else "Paused\n")):
            self.assertEqual(music.selected_player(), "firefox.instance1")

    def test_other_netease_client_beats_playing_browser(self):
        for available in (["firefox.instance1", "netease-cloud-music"],
                          ["netease-cloud-music", "firefox.instance1"]):
            with self.subTest(available=available), \
                    mock.patch.object(music, "players", return_value=available), \
                    mock.patch.object(music, "command") as run:
                self.assertEqual(music.selected_player(), "netease-cloud-music")
                run.assert_not_called()

    def test_equal_playback_states_use_stable_name_order(self):
        for status in ("Playing\n", "Paused\n"):
            for available in (["firefox.instance2", "chromium.instance1"],
                              ["chromium.instance1", "firefox.instance2"]):
                with self.subTest(status=status, available=available), \
                        mock.patch.object(music, "players", return_value=available), \
                        mock.patch.object(music, "command", return_value=subprocess.CompletedProcess([], 0, status)):
                    self.assertEqual(music.selected_player(), "chromium.instance1")

    def test_status_selection_has_one_shared_timeout_budget(self):
        with mock.patch.object(music, "players", return_value=["chromium", "firefox"]), \
                mock.patch.object(music.time, "monotonic", side_effect=[100, 101, 106]), \
                mock.patch.object(music, "command", return_value=subprocess.CompletedProcess([], 0, "Paused\n")) as run:
            with self.assertRaisesRegex(ValueError, "及时响应"):
                music.selected_player()
            run.assert_called_once_with(["playerctl", "--player", "chromium", "status"], timeout=4)

    def test_launch_uses_niri_to_leave_bar_cgroup(self):
        desktop = mock.Mock()
        executable = "/home/test user/.local/bin/netease-cloud-music-gtk4"
        with mock.patch.object(music, "client_command", return_value=[executable]), \
                mock.patch.object(music, "command", return_value=subprocess.CompletedProcess([], 0)) as run:
            music.run(desktop)
            desktop.require_session.assert_called_once_with()
            run.assert_called_once_with(["niri", "msg", "action", "spawn", "--", executable])

    def test_missing_client_is_not_silently_replaced_by_old_qt_client(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(music.shutil, "which", return_value=None), \
                mock.patch.dict("sys.modules", {"gi": None}):
            with self.assertRaisesRegex(ValueError, "尚未安装"):
                music.client_command()

    def test_missing_desktop_entry_with_real_gio_has_clear_install_message(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(music.shutil, "which", return_value=None), \
                mock.patch.object(music, "DESKTOP_ID", "dotfiles.nonexistent.music.desktop"):
            with self.assertRaisesRegex(ValueError, "尚未安装"):
                music.client_command()

    def test_control_uses_same_selected_player_and_reports_failure(self):
        with mock.patch.object(music, "selected_player", return_value=music.MPRIS_NAME), \
                mock.patch.object(music, "command", return_value=subprocess.CompletedProcess([], 1, "", "gone")) as run:
            with self.assertRaisesRegex(ValueError, "gone"):
                music.run(mock.Mock(), "next")
            run.assert_called_once_with(["playerctl", "--player", music.MPRIS_NAME, "next"])

    def test_empty_mpris_does_not_claim_playback_or_spawn(self):
        with mock.patch.object(music, "selected_player", return_value=None), \
                mock.patch.object(music, "command") as run:
            with self.assertRaisesRegex(ValueError, "没有可控制"):
                music.run(mock.Mock(), "play-pause")
            run.assert_not_called()


class MusicInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="music-test-中文 ")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home),
            "XDG_DATA_HOME": str(self.home / "custom data"),
            "XDG_STATE_HOME": str(self.home / "state"),
            "XDG_CACHE_HOME": str(self.home / "cache")})
        env.start()
        self.addCleanup(env.stop)
        self.paths = installer.paths()
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    @staticmethod
    def fake_build(destination, *_args):
        destination.mkdir()
        (destination / "installation.json").write_text("new version")
        icon = destination / "share/icons/hicolor/scalable/apps" / (installer.APP_ID + ".svg")
        icon.parent.mkdir(parents=True)
        icon.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

    def install(self):
        with mock.patch.object(installer, "requirements"), \
                mock.patch.object(installer, "build", side_effect=self.fake_build):
            return installer.install(self.paths, apply=True)

    def test_dry_run_does_not_create_directories_or_download(self):
        with mock.patch.object(installer, "build") as build:
            installer.install(self.paths)
            build.assert_not_called()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_bad_checksum_rejected_before_archive_execution(self):
        archive = self.home / "bad.tar.gz"
        archive.write_bytes(b"untrusted archive")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            installer.verify_archive(archive)

    def test_install_restore_preserves_original_symlink_and_modified_files(self):
        original = self.home / "original"
        original.write_text("original launcher")
        self.paths["launcher"].parent.mkdir(parents=True)
        self.paths["launcher"].symlink_to(original)
        self.paths["desktop"].parent.mkdir(parents=True)
        self.paths["desktop"].write_text("original desktop")
        self.paths["version"].mkdir(parents=True)
        (self.paths["version"] / "old").write_text("original version")
        backup = self.install()
        self.paths["desktop"].write_text("post-install user modification")
        installer.restore(self.paths, backup, apply=True)
        self.assertTrue(self.paths["launcher"].is_symlink())
        self.assertEqual(self.paths["launcher"].read_text(), "original launcher")
        self.assertEqual(self.paths["desktop"].read_text(), "original desktop")
        self.assertEqual((self.paths["version"] / "old").read_text(), "original version")
        self.assertEqual((self.paths["backups"] / backup / "removed/desktop").read_text(),
                         "post-install user modification")

    def test_first_install_restore_removes_menu_entry_and_keeps_removed_files(self):
        backup = self.install()
        installer.restore(self.paths, backup, apply=True)
        for key in installer.TARGET_KEYS:
            self.assertFalse(installer.exists(self.paths[key]))
            self.assertTrue(installer.exists(self.paths["backups"] / backup / "removed" / key))

    def test_install_publishes_hicolor_icon_and_restores_original_symlink(self):
        self.paths["icon"].parent.mkdir(parents=True)
        self.paths["icon"].symlink_to("/missing/previous-icon.svg")
        backup = self.install()
        self.assertEqual(self.paths["icon"].readlink(), installer.icon_source(self.paths))
        self.assertTrue(self.paths["icon"].is_file())
        installer.restore(self.paths, backup, apply=True)
        self.assertEqual(self.paths["icon"].readlink(), Path("/missing/previous-icon.svg"))

    def legacy_install(self):
        backup = self.install()
        self.paths["icon"].unlink()
        journal = self.paths["backups"] / backup / "manifest.json"
        record = json.loads(journal.read_text())
        record["items"] = [i for i in record["items"] if i["key"] != "icon"]
        installer.write_json(journal, record)
        return backup, journal, record

    def test_refresh_icon_extends_existing_backup_without_rebuilding_or_replacing_originals(self):
        backup, journal, before = self.legacy_install()
        self.paths["icon"].write_text("original icon")
        with mock.patch.object(installer, "build") as build:
            installer.refresh_icon(self.paths, backup, apply=False)
            self.assertEqual(json.loads(journal.read_text()), before)
            self.assertEqual(self.paths["icon"].read_text(), "original icon")
            installer.refresh_icon(self.paths, backup, apply=True)
            installer.refresh_icon(self.paths, backup, apply=True)
            build.assert_not_called()
        after = json.loads(journal.read_text())
        self.assertEqual(after["items"][:-1], before["items"])
        self.assertEqual(len(list(self.paths["backups"].iterdir())), 1)
        self.assertEqual(self.paths["icon"].readlink(), installer.icon_source(self.paths))
        installer.restore(self.paths, backup, apply=True)
        self.assertEqual(self.paths["icon"].read_text(), "original icon")

    def test_failed_icon_refresh_restores_icon_and_leaves_running_install_intact(self):
        backup, journal, before = self.legacy_install()
        self.paths["icon"].write_text("original icon")
        with mock.patch.object(Path, "symlink_to", side_effect=OSError("cannot create icon")):
            with self.assertRaisesRegex(OSError, "cannot create icon"):
                installer.refresh_icon(self.paths, backup, apply=True)
        self.assertEqual(json.loads(journal.read_text()), before)
        self.assertEqual(self.paths["icon"].read_text(), "original icon")
        self.assertTrue(self.paths["launcher"].exists())
        self.assertTrue(self.paths["version"].exists())

    def test_install_failure_restores_originals(self):
        self.paths["launcher"].parent.mkdir(parents=True)
        self.paths["launcher"].write_text("old")
        move = installer.shutil.move

        def failing_move(source, destination):
            if str(destination) == str(self.paths["desktop"]):
                raise OSError("simulated disk failure")
            return move(source, destination)

        with mock.patch.object(installer.shutil, "move", side_effect=failing_move):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.install()
        self.assertEqual(self.paths["launcher"].read_text(), "old")
        self.assertFalse(self.paths["version"].exists())

    def test_restore_rejects_wrong_xdg_root(self):
        backup = self.install()
        changed = dict(self.paths, desktop=self.home / "different.desktop")
        with self.assertRaisesRegex(ValueError, "original HOME"):
            installer.restore(changed, backup, apply=True)
        self.assertTrue(self.paths["launcher"].exists())

    def test_restore_retries_after_original_symlink_move_before_journal_update(self):
        self.paths["icon"].parent.mkdir(parents=True)
        self.paths["icon"].symlink_to("/missing/original.svg")
        backup = self.install()
        write = installer.write_json

        def fail_once(path, record):
            icon = next(i for i in record["items"] if i["key"] == "icon")
            if icon.get("restore_phase") == "done":
                raise OSError("interrupted journal write")
            return write(path, record)

        with mock.patch.object(installer, "write_json", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "journal"):
                installer.restore(self.paths, backup, apply=True)
        self.assertEqual(self.paths["icon"].readlink(), Path("/missing/original.svg"))
        installer.restore(self.paths, backup, apply=True)
        self.assertEqual(self.paths["icon"].readlink(), Path("/missing/original.svg"))
        self.assertEqual((self.paths["backups"] / backup / "removed/icon").readlink(),
                         installer.icon_source(self.paths))

    def test_restore_retries_after_installed_file_move_before_journal_update(self):
        backup = self.install()
        write = installer.write_json

        def fail_once(path, record):
            icon = next(i for i in record["items"] if i["key"] == "icon")
            if icon.get("restore_phase") == "original":
                raise OSError("interrupted journal write")
            return write(path, record)

        with mock.patch.object(installer, "write_json", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "journal"):
                installer.restore(self.paths, backup, apply=True)
        installer.restore(self.paths, backup, apply=True)
        self.assertFalse(installer.exists(self.paths["icon"]))
        self.assertTrue(installer.exists(self.paths["backups"] / backup / "removed/icon"))

    def test_restore_retries_after_final_manifest_write_failure(self):
        self.paths["launcher"].parent.mkdir(parents=True)
        self.paths["launcher"].symlink_to("/missing/original-launcher")
        backup = self.install()
        write = installer.write_json

        def fail_final(path, record):
            if record.get("restored"):
                raise OSError("interrupted final write")
            return write(path, record)

        with mock.patch.object(installer, "write_json", side_effect=fail_final):
            with self.assertRaisesRegex(OSError, "final"):
                installer.restore(self.paths, backup, apply=True)
        installer.restore(self.paths, backup, apply=True)
        self.assertEqual(self.paths["launcher"].readlink(), Path("/missing/original-launcher"))
        self.assertFalse((self.paths["backups"] / backup / "removed/launcher").is_symlink())

    def test_launcher_treats_shell_metacharacters_as_path_data(self):
        prefix = self.home / "native ' $(touch forbidden) `echo wrong`"
        executable = prefix / "bin" / installer.BINARY
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nprintf '%s\\n' \"$GSETTINGS_SCHEMA_DIR\" \"$1\"\n")
        executable.chmod(0o755)
        launcher = self.home / "launcher"
        launcher.write_text(installer.launcher_text(prefix))
        launcher.chmod(0o755)
        result = subprocess.run([str(launcher), "argument with spaces"], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [str(prefix / "share/glib-2.0/schemas"), "argument with spaces"])
        self.assertFalse((self.home / "forbidden").exists())

    def test_desktop_exec_handles_percent_and_quoted_path_with_real_gio(self):
        if not installer.shutil.which("dbus-run-session") or not installer.shutil.which("gio"):
            self.skipTest("GIO and dbus-run-session are required")
        launcher = self.home / 'quote" dollar$ percent% back` slash\\'
        result_file = self.home / "launched"
        launcher.write_text("#!/bin/sh\nprintf 'launched' > " + installer.shlex.quote(str(result_file)) + "\n")
        launcher.chmod(0o755)
        desktop = self.home / "test.desktop"
        desktop.write_text(installer.desktop_text(dict(self.paths, launcher=launcher)))
        result = subprocess.run(["dbus-run-session", "--", "gio", "launch", str(desktop)],
                                capture_output=True, text=True, timeout=5)
        if "Operation not permitted" in result.stderr:
            self.skipTest("Sandbox prohibits the private test D-Bus socket")
        self.assertEqual(result.returncode, 0, result.stderr)
        for _ in range(20):
            if result_file.exists():
                break
            time.sleep(0.05)
        self.assertEqual(result_file.read_text(), "launched")


if __name__ == "__main__":
    unittest.main()
