"""Preview isolation regressions; no GUI, user-manager, hardware or network calls."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

SPEC = importlib.util.spec_from_file_location("desktop_preview", Path(__file__).resolve().parents[1] / "scripts/desktop-preview.py")
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="moonlit-preview-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "runtime"

    def test_refuses_unowned_nonempty_or_symlink_runtime(self):
        self.root.mkdir()
        (self.root / "precious").write_text("keep")
        with self.assertRaises(preview.PreviewError):
            preview.safe_root(self.root, create=True)
        self.assertEqual((self.root / "precious").read_text(), "keep")
        target = self.base / "link"
        target.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(preview.PreviewError):
            preview.safe_root(target, create=True)

    def test_refuses_user_configuration_and_repo(self):
        for path in (Path.home(), Path.home() / ".config/new-preview", preview.REPO,
                     preview.REPO / "preview", Path("/tmp")):
            with self.subTest(path=path), self.assertRaises(preview.PreviewError):
                preview.safe_root(path, create=True)

    def test_environment_preserves_home_but_isolates_state_and_compositor(self):
        with mock.patch.dict(os.environ, {"HOME": "/actual/home", "NIRI_SOCKET": "/host/niri.sock",
                                         "NIRI_CONFIG": "/host/config.kdl", "PATH": "/usr/bin"}):
            env = preview.preview_environment(self.root)
        self.assertEqual(env["HOME"], "/actual/home")
        self.assertNotIn("NIRI_SOCKET", env)
        self.assertNotIn("NIRI_CONFIG", env)
        self.assertEqual(env["GSETTINGS_BACKEND"], "memory")
        for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                    "NOCTALIA_CONFIG_HOME", "NOCTALIA_STATE_HOME", "NOCTALIA_DATA_HOME"):
            self.assertTrue(Path(env[key]).is_relative_to(self.root))

    def test_materialization_removes_only_disposable_links(self):
        repo = self.base / "repo"
        repo.mkdir()
        (repo / "config").mkdir()
        original = repo / "config/theme.conf"
        original.write_text("original")
        config = self.base / "home/.config"
        config.mkdir(parents=True)
        (config / "theme.conf").symlink_to(original)
        (config / "nvim").symlink_to(repo / "config", target_is_directory=True)
        with mock.patch.object(preview, "REPO", repo):
            preview.materialize_links(config)
        (config / "theme.conf").write_text("preview edit")
        (config / "nvim/theme.conf").write_text("nested preview edit")
        self.assertEqual(original.read_text(), "original")
        self.assertFalse((config / "nvim").is_symlink())

    def test_refuses_copying_unexpected_external_link(self):
        config = self.base / "config"
        config.mkdir()
        (config / "external").symlink_to("/etc/passwd")
        with self.assertRaises(preview.PreviewError):
            preview.materialize_links(config)
        self.assertTrue((config / "external").is_symlink())

    def test_recycled_pid_is_never_signalled(self):
        expected = {"pid": 12345, "start": 77}
        with mock.patch.object(preview, "proc_identity", return_value={"pid": 12345, "start": 78, "state": "S"}), \
                mock.patch.object(preview.os, "pidfd_open") as opener:
            self.assertFalse(preview.signal_owned(expected, signal.SIGTERM))
        opener.assert_not_called()

    def test_pid_reuse_between_check_and_pidfd_open_is_not_signalled(self):
        expected = {"pid": 12345, "start": 77}
        original = {**expected, "state": "S"}
        replacement = {"pid": 12345, "start": 78, "state": "S"}
        with mock.patch.object(preview, "proc_identity", side_effect=[original, replacement]), \
                mock.patch.object(preview.os, "pidfd_open", return_value=99), \
                mock.patch.object(preview.os, "close") as close, \
                mock.patch.object(preview.signal, "pidfd_send_signal") as send:
            self.assertFalse(preview.signal_owned(expected, signal.SIGTERM))
        send.assert_not_called()
        close.assert_called_once_with(99)

    def test_cleanup_owns_only_registered_tree_and_its_session(self):
        leader = {"pid": 100, "start": 10, "ppid": 1, "session": 100, "state": "S"}
        processes = {
            100: leader,
            101: {"pid": 101, "start": 11, "ppid": 100, "session": 100, "state": "S"},
            102: {"pid": 102, "start": 12, "ppid": 1, "session": 100, "state": "S"},
            200: {"pid": 200, "start": 15, "ppid": 1, "session": 200, "state": "S"},
        }
        with mock.patch.object(preview, "proc_identity", side_effect=processes.get), \
                mock.patch.object(preview.Path, "iterdir", return_value=[Path('/proc') / str(p) for p in processes]):
            owned = preview.owned_processes({"supervisor": leader})
        self.assertEqual({p["pid"] for p in owned}, {100, 101, 102})
        self.assertEqual(owned[-1]["pid"], 100)

    def test_start_refuses_any_registered_survivor_without_overwriting_state(self):
        preview.safe_root(self.root, create=True)
        leader = {"pid": 100, "start": 10, "state": "Z"}
        survivor = {"pid": 101, "start": 11, "state": "S"}
        for role in ("shell", "proxy", "desktop", "child"):
            with self.subTest(role=role):
                values = {"supervisor": leader, role: survivor}
                preview.write_json(self.root / "processes.json", values)
                with mock.patch.object(preview, "proc_identity", side_effect={100: leader, 101: survivor}.get), \
                        mock.patch.object(preview.subprocess, "Popen") as launch:
                    with self.assertRaisesRegex(preview.PreviewError, "run stop"):
                        preview.start(self.root)
                launch.assert_not_called()
                self.assertEqual(preview.state(self.root), values)

    def test_cleanup_does_not_adopt_a_recycled_supervisor_session(self):
        leader = {"pid": 100, "start": 10, "ppid": 1, "session": 100, "state": "S"}
        recycled = {**leader, "start": 99}
        # Both preliminary identity checks pass; PID 100 is reused before /proc enumeration.
        with mock.patch.object(preview, "proc_identity", side_effect=[leader, leader, recycled]), \
                mock.patch.object(preview.Path, "iterdir", return_value=[Path('/proc/100')]):
            self.assertEqual(preview.owned_processes({"supervisor": leader}), [])

    def test_stop_includes_retained_player_in_its_independent_session(self):
        preview.safe_root(self.root, create=True)
        leader = {"pid": 100, "start": 10, "ppid": 1, "session": 100, "state": "S"}
        player = {"pid": 200, "start": 20, "ppid": 1, "session": 200, "state": "S"}
        unrelated = {"pid": 300, "start": 30, "ppid": 1, "session": 300, "state": "S"}
        (self.root / "media-validation").mkdir()
        preview.write_json(self.root / "processes.json", {"supervisor": leader})
        preview.write_json(self.root / "session.json", {})
        preview.write_json(self.root / "media-validation/player.json",
                           {**player, "session": str(self.root / "session.json")})
        processes = {100: leader, 200: player, 300: unrelated}
        signalled = []

        def terminate(identity, number):
            signalled.append((identity["pid"], number))
            processes.pop(identity["pid"], None)

        with mock.patch.object(preview, "proc_identity", side_effect=processes.get), \
                mock.patch.object(preview.Path, "iterdir", return_value=[Path('/proc') / str(p) for p in processes]), \
                mock.patch.object(preview, "signal_owned", side_effect=terminate):
            result = preview.stop(self.root)
        self.assertEqual(signalled, [(200, signal.SIGTERM), (100, signal.SIGTERM)])
        self.assertEqual(result["stopped_owned_processes"], 2)
        self.assertIn(300, processes)
        self.assertFalse((self.root / "session.json").exists())

    def test_retained_player_blocks_restart_even_after_supervisor_exits(self):
        preview.safe_root(self.root, create=True)
        (self.root / "media-validation").mkdir()
        player = {"pid": 200, "start": 20, "state": "S"}
        preview.write_json(self.root / "media-validation/player.json",
                           {**player, "session": str(self.root / "session.json")})
        with mock.patch.object(preview, "proc_identity", return_value=player), \
                mock.patch.object(preview.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(preview.PreviewError, "run stop"):
                preview.start(self.root)
        launch.assert_not_called()

    def test_cleanup_rejects_other_preview_or_recycled_retained_player(self):
        preview.safe_root(self.root, create=True)
        (self.root / "media-validation").mkdir()
        player = {"pid": 200, "start": 20}
        for session, actual in ((self.base / "other/session.json", {**player, "state": "S"}),
                                (self.root / "session.json", {**player, "start": 21, "state": "S"})):
            with self.subTest(session=session, start=actual["start"]):
                preview.write_json(self.root / "media-validation/player.json", {**player, "session": str(session)})
                with mock.patch.object(preview, "proc_identity", return_value=actual), \
                        mock.patch.object(preview, "signal_owned") as send:
                    self.assertEqual(preview.stop(self.root)["stopped_owned_processes"], 0)
                send.assert_not_called()

    def test_power_rows_and_idle_cannot_affect_real_session(self):
        data = preview.tomllib.loads(preview.safety_config(self.base / "wall papers", self.root / "key"))
        for row in data["shell"]["session"]["actions"]:
            self.assertFalse(row["enabled"])
            self.assertEqual(row["command"], "/usr/bin/true")
        self.assertEqual(set(data["shell"]["session"]["power"].values()), {"/usr/bin/true"})
        self.assertTrue(all(not row["enabled"] for row in data["idle"]["behavior"].values()))
        self.assertFalse(data["wallpaper"]["automation"]["enabled"])
        self.assertEqual(data["storage"], {"key_source": "file", "key_file": str(self.root / "key")})

    def test_private_bus_cannot_activate_user_daemons(self):
        root = ET.fromstring(preview.PRIVATE_BUS_CONFIG)
        self.assertEqual(root.findtext("auth"), "EXTERNAL")
        for node in ("standard_session_servicedirs", "servicedir", "include", "includedir"):
            self.assertIsNone(root.find(node))

    def test_system_proxy_only_grants_explicit_read_methods(self):
        with mock.patch.object(preview.shutil, "which", return_value="/usr/bin/xdg-dbus-proxy"):
            args = preview.proxy_command(self.root, "unix:path=/real/system_bus")
        self.assertIn("--filter", args)
        self.assertFalse(any(arg.startswith(("--talk=", "--own=")) for arg in args))
        calls = [arg.split("=", 2)[2] for arg in args if arg.startswith("--call=")]
        self.assertIn("org.freedesktop.DBus.Properties.GetAll", calls)
        self.assertIn("org.freedesktop.NetworkManager.GetDevices", calls)
        for method in calls:
            self.assertNotIn("*", method)
            self.assertNotIn(method.rsplit(".", 1)[-1],
                             ("Connect", "Pair", "RequestScan", "Set", "Delete", "GetSecrets", "Inhibit", "RegisterAgent"))

    def test_missing_proxy_fails_closed(self):
        with mock.patch.object(preview.shutil, "which", return_value=None):
            with self.assertRaisesRegex(preview.PreviewError, "refusing an unfiltered"):
                preview.proxy_command(self.root, "unix:path=/real/system_bus")

    def test_preview_preserves_navigation_but_has_no_service_or_private_include(self):
        source = (preview.REPO / "config/moonlit/niri-preview.kdl").read_text()
        for forbidden in ("spawn-sh-at-startup", "systemctl", "dotfiles-local", "playerctl", "wpctl", "brightnessctl"):
            self.assertNotIn(forbidden, source)
        for binding in ("Mod+Q repeat=false { close-window; }", "Mod+H { focus-column-left; }",
                        "Mod+R hotkey-overlay-title=", "Mod+F { maximize-column; }",
                        "Mod+Shift+F hotkey-overlay-title=", "Mod+O repeat=false { toggle-overview; }"):
            self.assertIn(binding, source)
        self.assertNotIn("{ quit; }", source)

    def test_capture_never_uses_host_socket(self):
        preview.safe_root(self.root, create=True)
        write = preview.write_json
        write(self.root / "processes.json", {"supervisor": {"pid": 123, "start": 5}})
        write(self.root / "session.json", {"NIRI_SOCKET": "/nested/niri.sock", "WAYLAND_DISPLAY": "wayland-42",
                                          "DBUS_SESSION_BUS_ADDRESS": "unix:path=/private/bus"})
        with mock.patch.object(preview, "alive", return_value=True), \
                mock.patch.dict(os.environ, {"NIRI_SOCKET": "/host/niri.sock"}):
            env = preview.nested_environment(self.root)
        self.assertEqual(env["NIRI_SOCKET"], "/nested/niri.sock")
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/private/bus")


if __name__ == "__main__":
    unittest.main()
