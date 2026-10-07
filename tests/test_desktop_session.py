"""Production-stage orchestration tests: temporary Git/home, mocked user services."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("desktop_session", REPO / "scripts/desktop-session.py")
session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="moonlit-session-test-")
        self.addCleanup(self.cleanup)
        self.root = Path(self.tmp.name)
        self.repo, self.old = self.root / "repo", self.root / "baseline"
        self.release, self.live = self.root / "release", self.root / "live"
        self.home = self.root / "home"
        self.wallpapers = self.root / "wallpapers"
        self.libs = self.root / "libs"
        self.wallpapers.mkdir()
        self.libs.mkdir()
        self.niri = '''binds {
    Mod+D { spawn "legacy-launcher"; }
    Mod+H { focus-column-left; }
    XF86AudioPlay allow-when-locked=true { spawn "playerctl" "play-pause"; }
    XF86AudioNext allow-when-locked=true { spawn "playerctl" "next"; }
    XF86AudioPrev allow-when-locked=true { spawn "playerctl" "previous"; }
}
// Includes remain outside Git. Do not change personal settings.
include optional=true "../dotfiles-local/niri.kdl"
'''
        old_files = {"platforms/linux/niri/config.kdl": self.niri,
                     "config/desktop/desktopctl.py": "# preserved legacy helper\n",
                     "platforms/linux/systemd/" + session.BAR: "# preserved legacy bar\n"}
        inventory = {}
        for name, text in old_files.items():
            path = self.write(self.old, name, text)
            path.chmod(0o444)
            inventory[name] = {"sha256": session.sha(path), "mode": 0o444}
        self.write(self.old, ".desktop-baseline.json", json.dumps({"schema": 1,
            "recipe": "current-preserving-no-override-gtk-v1", "commit": "a" * 40, "files": inventory}))
        # Baseline verify requires its recovery script as part of the fixed source.
        script = self.write(self.old, "scripts/deploy.py", (REPO / "scripts/deploy.py").read_text())
        script.chmod(0o444)
        inventory["scripts/deploy.py"] = {"sha256": session.sha(script), "mode": 0o444}
        (self.old / ".desktop-baseline.json").write_text(json.dumps({"schema": 1,
            "recipe": "current-preserving-no-override-gtk-v1", "commit": "a" * 40, "files": inventory}))
        for name in ("deploy.py", "desktop-session.py", "desktop-preview.py", "desktop-baseline.py"):
            self.write(self.repo, "scripts/" + name, (REPO / "scripts" / name).read_text())
        for name, text in {
            "config/moonlit/desktopctl.py": 'import json\nprint(json.dumps({"ready": True}))\n',
            "config/moonlit/calendar_bridge.py": '# private read-only calendar fixture\n',
            "config/moonlit/settings.toml": '[shell]\nlang="zh-Hans"\n',
            "config/moonlit/niri-theme.kdl": 'layout { background-color "#18131f"; }\n',
            "config/moonlit/kitty-theme.conf": "background #18131f\n",
            "config/moonlit/nvim-theme.lua": '-- isolated theme\n',
            "config/moonlit/palettes/MoonlitBloom.json": '{}\n',
            "config/moonlit/plugins/test/plugin.toml": 'name="test"\n',
            "config/kitty/theme.conf": "# existing terminal theme\n",
        }.items():
            self.write(self.repo, name, text)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=test", "-c", "user.email=test@invalid", "commit", "-qm", "fixture")
        for target, source in session.LEGACY_SOURCES.items():
            path = self.home / ".config" / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(self.old / source)
        kitty = self.home / ".config/kitty/theme.conf"
        kitty.parent.mkdir()
        kitty.symlink_to(self.repo / "config/kitty/theme.conf")
        self.write(self.home, ".config/dotfiles-local/niri.kdl", "personal display\n")
        self.write(self.home, ".config/dotfiles-local/nvim.lua", "personal editor\n")
        (self.home / ".config/nvim").symlink_to("/untouched/editor")
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.unit_states = {session.BAR: "active", session.WALLPAPER: "active"}
        self.commands = []
        self.real_run = subprocess.run
        niri_mock = mock.patch.object(session.subprocess, "run", side_effect=self.run_command)
        niri_mock.start()
        self.addCleanup(niri_mock.stop)

    def cleanup(self):
        for parent, _, _ in os.walk(self.tmp.name):
            Path(parent).chmod(0o700)
        self.tmp.cleanup()

    def write(self, root, name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def prepare(self, **kwargs):
        session.prepare(self.repo, "HEAD", self.old, self.release, self.live,
                        Path("/usr/bin/true"), self.libs, self.wallpapers, self.home, **kwargs)
        self.commands.clear()
        return self.live / "transaction.json"

    def run_command(self, argv, **kwargs):
        if argv[0] == "niri":
            self.commands.append(tuple(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")
        return self.real_run(argv, **kwargs)

    def control(self, *args):
        self.commands.append(args)
        if args[0] == "show":
            text = f"ActiveState={self.unit_states[args[1]]}\nSubState=running\nMainPID=12\n"
        else:
            text = ""
            if args[0] in ("start", "stop"):
                self.unit_states[args[1]] = "active" if args[0] == "start" else "inactive"
        return subprocess.CompletedProcess(args, 0, text, "")

    def test_prepare_is_commit_pinned_and_preserves_keys_personal_configuration(self):
        transaction = self.prepare()
        manifest = session.verify(self.release)
        self.assertEqual(len(manifest["commit"]), 40)
        generated = (self.release / "managed/niri/config.kdl").read_text()
        self.assertIn('Mod+H { focus-column-left; }', generated)
        self.assertIn('Mod+D { spawn "legacy-launcher"; }', generated)
        self.assertLess(generated.index('include "moonlit-theme.kdl"'), generated.index('// Includes remain'))
        self.assertIn('media toggle', generated)
        self.assertEqual(os.readlink(self.home / ".config/nvim"), "/untouched/editor")
        self.assertEqual(session.journal(transaction)["phase"], "prepared")
        safety = tomllib.loads((self.live / "config/noctalia/zz-basic-safety.toml").read_text())
        self.assertEqual(safety["shell"]["launch_apps_custom_command"],
                         shlex.join(["/usr/bin/python3", str(self.release / "managed/niri/desktopctl.py"),
                                     "launch", "--"]) + " $CMD")
        self.assertFalse(safety["notification"]["enable_daemon"])
        self.assertFalse(safety["lockscreen"]["enabled"])
        self.assertFalse(safety["calendar"]["enabled"])
        self.assertFalse((self.live / "data/noctalia/calendar-vdir").exists())

    def test_dirty_source_is_rejected_before_creating_release(self):
        (self.repo / "config/moonlit/settings.toml").write_text("dirty")
        with self.assertRaisesRegex(session.SessionError, "clean committed"):
            self.prepare()
        self.assertFalse(self.release.exists())

    def test_dry_run_has_no_service_or_deployment_state_mutation(self):
        transaction = self.prepare()
        with mock.patch.object(session, "control") as control:
            result = session.deploy(transaction)
        self.assertTrue(result["dry_run"])
        control.assert_not_called()
        self.assertFalse((self.home / ".local/state").exists())
        self.assertEqual(session.journal(transaction)["phase"], "prepared")

    def test_activation_and_restore_manage_only_bar_wallpaper_and_exact_links(self):
        transaction = self.prepare()
        old = os.readlink(self.home / ".config/niri/config.kdl")
        with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control):
            self.assertEqual(session.deploy(transaction, apply=True)["phase"], "active")
            value = session.journal(transaction)
            backup = Path(value["backup"])
            self.assertEqual(len(json.loads((backup / "manifest.json").read_text())["entries"]), 7)
            self.assertEqual(self.unit_states[session.WALLPAPER], "inactive")
            self.assertEqual(session.restore(transaction, apply=True)["phase"], "restored")
        self.assertEqual(os.readlink(self.home / ".config/niri/config.kdl"), old)
        self.assertFalse((self.home / ".config/moonlit/nvim-theme.lua").exists())
        self.assertEqual(self.unit_states, {session.BAR: "active", session.WALLPAPER: "active"})
        self.assertTrue(all(cmd[1] in session.CHANGED_UNITS for cmd in self.commands if cmd[0] in ("start", "stop")))
        self.assertEqual((self.home / ".config/dotfiles-local/nvim.lua").read_text(), "personal editor\n")
        niri_calls = [cmd for cmd in self.commands if cmd[0] == "niri"]
        deployed = str(self.home / ".config/niri/config.kdl")
        expected = [("niri", "validate", "--config", deployed),
                    ("niri", "msg", "action", "load-config-file", "--path", deployed)]
        self.assertEqual(niri_calls, expected * 2)
        self.assertLess(self.commands.index(expected[1]), self.commands.index(("start", session.BAR)))

    def test_new_shell_failure_restores_links_and_only_previously_active_services(self):
        transaction = self.prepare()
        self.unit_states[session.WALLPAPER] = "inactive"
        with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control), \
                mock.patch.object(session, "start", side_effect=session.SessionError("launch failed")):
            with self.assertRaisesRegex(session.SessionError, "launch failed"):
                session.deploy(transaction, apply=True)
        self.assertEqual(session.journal(transaction)["phase"], "restored")
        self.assertEqual(self.unit_states[session.WALLPAPER], "inactive")
        self.assertEqual(os.readlink(self.home / ".config/niri/desktopctl.py"), str(self.old / "config/desktop/desktopctl.py"))

    def test_unknown_file_refused_before_stopping_any_service(self):
        transaction = self.prepare()
        target = self.home / ".config/niri/desktopctl.py"
        target.unlink()
        target.write_text("personal")
        with mock.patch.object(session, "control") as control:
            with self.assertRaisesRegex(session.SessionError, "Unknown existing"):
                session.deploy(transaction, apply=True)
        control.assert_not_called()
        self.assertEqual(target.read_text(), "personal")

    def test_transitioning_service_refused_before_any_live_mutation(self):
        transaction = self.prepare()
        for transitional in ("activating", "deactivating", "reloading"):
            self.unit_states[session.WALLPAPER] = transitional
            with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control):
                with self.assertRaisesRegex(session.SessionError, "changing state"):
                    session.deploy(transaction, apply=True)
            self.assertEqual(session.journal(transaction)["phase"], "prepared")
            self.assertFalse(any(cmd[0] in ("start", "stop", "daemon-reload") for cmd in self.commands))

    def test_restore_conflict_keeps_new_shell_running_and_reports_clear_error(self):
        transaction = self.prepare()
        with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control):
            session.deploy(transaction, apply=True)
            target = self.home / ".config/kitty/theme.conf"
            target.unlink()
            target.write_text("personal edit after migration")
            self.commands.clear()
            with self.assertRaisesRegex(session.SessionError, "Restore conflict"):
                session.restore(transaction, apply=True)
        self.assertEqual(target.read_text(), "personal edit after migration")
        self.assertEqual(self.unit_states[session.BAR], "active")
        self.assertEqual(self.commands, [])

    def test_journal_cannot_expand_service_restore_scope(self):
        transaction = self.prepare()
        value = session.journal(transaction)
        value["services_before"] = {"unrelated.service": {"ActiveState": "active"}}
        session.atomic_json(transaction, value)
        with mock.patch.object(session, "control") as control:
            with self.assertRaisesRegex(session.SessionError, "service recovery scope"):
                session.restore(transaction, apply=True)
        control.assert_not_called()

    def test_invalid_deployed_config_restores_links_before_reloading_old_config(self):
        transaction = self.prepare()
        validations = []
        def run(argv, **kwargs):
            if argv[:2] == ["niri", "validate"]:
                validations.append(os.readlink(self.home / ".config/niri/config.kdl"))
                if len(validations) == 1:
                    raise subprocess.CalledProcessError(1, argv, stderr="invalid machine include")
            return self.run_command(argv, **kwargs)
        with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control), \
                mock.patch.object(session.subprocess, "run", side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                session.deploy(transaction, apply=True)
        self.assertEqual(validations, [str(self.release / "managed/niri/config.kdl"),
                                       str(self.old / "platforms/linux/niri/config.kdl")])
        self.assertEqual(session.journal(transaction)["phase"], "restored")
        # A rejected config is never sent to the compositor. Only the restored
        # baseline gets an explicit reload, before the old bar returns.
        reloads = [cmd for cmd in self.commands if cmd[:4] == ("niri", "msg", "action", "load-config-file")]
        self.assertEqual(len(reloads), 1)
        self.assertLess(self.commands.index(reloads[0]), self.commands.index(("start", session.BAR)))

    def test_release_tampering_and_concurrent_transaction_are_rejected(self):
        transaction = self.prepare()
        with session.transaction_lock(transaction):
            with self.assertRaisesRegex(session.SessionError, "Another command"):
                with session.transaction_lock(transaction):
                    pass
        source = self.release / "managed/niri/desktopctl.py"
        source.chmod(0o644)
        source.write_text("tampered")
        with self.assertRaisesRegex(session.SessionError, "content changed"):
            session.deploy(transaction, apply=True)

    def test_capabilities_are_explicit_and_only_one_new_permission_is_allowed(self):
        with self.assertRaisesRegex(session.SessionError, "Unsupported capability"):
            self.prepare(capabilities=["notifications"])
        with self.assertRaisesRegex(session.SessionError, "only one new"):
            self.prepare(capabilities=["audio", "network"])
        self.assertFalse(self.release.exists())
        self.assertEqual(session.capability_list(["network", "audio", "audio"]), ["audio", "network"])

    def test_upgrade_restores_previous_moonlit_without_restarting_old_wallpaper(self):
        old_transaction = self.prepare()
        old_release, old_live = self.release, self.live
        wallpaper = self.wallpapers / "quiet-street.png"
        wallpaper.write_bytes(b"wallpaper fixture")
        self.write(old_live, "state/noctalia/settings.toml", '[shell]\npolkit_agent=true\n'
                   '[notification]\nenable_daemon=true\n[wallpaper.default]\npath=' + json.dumps(str(wallpaper)) + '\n')
        self.write(old_live, "state/noctalia/plugins/data/dotfiles/moonlit-music/media-control.json",
                   '{"selected":"org.mpris.MediaPlayer2.fixture"}\n')
        with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control):
            session.deploy(old_transaction, apply=True)
            self.release, self.live = self.root / "audio-release", self.root / "audio-live"
            transaction = self.prepare(capabilities=["audio"], inherit_transaction=old_transaction)
            manifest = session.verify(self.release)
            self.assertEqual(manifest["predecessor"]["release"], str(old_release))
            runtime = json.loads((self.release / "managed/niri/moonlit-session.json").read_text())
            self.assertEqual(runtime["capabilities"], ["audio"])
            self.assertEqual((self.release / "managed/niri/config.kdl").read_text().count('include "moonlit-theme.kdl"'), 1)
            preferences = tomllib.loads((self.live / "state/noctalia/settings.toml").read_text())
            self.assertEqual(preferences, {"wallpaper": {"default": {"path": str(wallpaper)}}})
            self.assertTrue((self.live / "state/noctalia/plugins/data/dotfiles/moonlit-music/media-control.json").is_file())
            safety = tomllib.loads((self.live / "config/noctalia/zz-basic-safety.toml").read_text())
            self.assertIn("volume", safety["bar"]["default"]["end"])
            self.assertNotIn("audio", safety["control_center"]["hidden_tabs"])
            self.assertFalse(safety["notification"]["enable_daemon"])
            self.assertEqual(session.deploy(transaction, apply=True)["phase"], "active")
            self.commands.clear()
            session.restore(transaction, apply=True)
        for name in session.TARGETS:
            self.assertEqual(os.readlink(self.home / ".config" / name), str(old_release / "managed" / name))
        self.assertNotIn(("start", session.WALLPAPER), self.commands)
        self.assertEqual(self.unit_states[session.WALLPAPER], "inactive")
        self.assertEqual(session.journal(old_transaction)["phase"], "active")

    def test_upgrade_cannot_inherit_an_inactive_or_displaced_release(self):
        old_transaction = self.prepare()
        self.release, self.live = self.root / "new-release", self.root / "new-live"
        with self.assertRaisesRegex(session.SessionError, "previously active"):
            self.prepare(capabilities=["audio"], inherit_transaction=old_transaction)
        with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control):
            session.deploy(old_transaction, apply=True)
        target = self.home / ".config/kitty/theme.conf"
        target.unlink()
        target.write_text("personal")
        with self.assertRaisesRegex(session.SessionError, "no longer the deployed release"):
            self.prepare(capabilities=["audio"], inherit_transaction=old_transaction)
        self.assertFalse(self.release.exists())

    def test_failed_upgrade_rolls_back_to_previous_moonlit_release(self):
        old_transaction = self.prepare()
        old_release = self.release
        with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control):
            session.deploy(old_transaction, apply=True)
            self.release, self.live = self.root / "new-release", self.root / "new-live"
            transaction = self.prepare(capabilities=["network"], inherit_transaction=old_transaction)
            with mock.patch.object(session, "start", side_effect=session.SessionError("new stage failed")):
                with self.assertRaisesRegex(session.SessionError, "new stage failed"):
                    session.deploy(transaction, apply=True)
        self.assertEqual(session.journal(transaction)["phase"], "restored")
        self.assertEqual(os.readlink(self.home / ".config/niri/config.kdl"), str(old_release / "managed/niri/config.kdl"))
        self.assertEqual(self.unit_states, {session.BAR: "active", session.WALLPAPER: "inactive"})

    def test_each_following_stage_explicitly_retains_previous_capabilities(self):
        transaction = self.prepare()
        with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control):
            session.deploy(transaction, apply=True)
            for index, caps in enumerate((["audio"], ["audio", "network"], ["audio", "network", "bluetooth"],
                                          ["audio", "network", "bluetooth", "calendar"]), 1):
                self.release, self.live = self.root / f"release-{index}", self.root / f"live-{index}"
                transaction = self.prepare(capabilities=caps, inherit_transaction=transaction)
                session.deploy(transaction, apply=True)
                self.assertEqual(session.status(transaction)["capabilities"], sorted(caps))

    def test_calendar_is_an_explicit_private_local_account_with_reminders_disabled(self):
        transaction = self.prepare(capabilities=["calendar"])
        runtime = json.loads((self.release / "managed/niri/moonlit-session.json").read_text())
        directory = self.live / "data/noctalia/calendar-vdir"
        self.assertEqual(runtime["calendar_dir"], str(directory))
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        safety = tomllib.loads((self.live / "config/noctalia/zz-basic-safety.toml").read_text())
        self.assertTrue(safety["calendar"]["enabled"])
        self.assertFalse(safety["calendar"]["reminders"]["enabled"])
        self.assertEqual(safety["calendar"]["account"], {"gnome_calendar": {
            "type": "vdir", "name": "GNOME Calendar · read-only", "path": str(directory), "calendars": []}})
        self.assertNotIn("calendar", safety["control_center"]["hidden_tabs"])
        self.assertFalse(safety["notification"]["enable_daemon"])
        self.assertEqual(session.journal(transaction)["phase"], "prepared")

    def test_interrupted_install_discovers_backup_before_standalone_restore(self):
        transaction = self.prepare()
        module, manifest = session.guarded_deployer(self.release)
        install = module.install
        def interrupted(*args, **kwargs):
            result = install(*args, **kwargs)
            if kwargs.get("apply"):
                raise KeyboardInterrupt("interrupted before backup returned")
            return result
        module.install = interrupted
        with mock.patch.object(session, "require_host"), mock.patch.object(session, "control", side_effect=self.control):
            with mock.patch.object(session, "guarded_deployer", return_value=(module, manifest)):
                with self.assertRaises(KeyboardInterrupt):
                    session.deploy(transaction, apply=True)
            self.assertIsNone(session.journal(transaction)["backup"])
            self.assertEqual(session.journal(transaction)["phase"], "deploying")
            preview = session.restore(transaction)
            self.assertIsNotNone(preview["backup"])
            self.assertIsNone(session.journal(transaction)["backup"])
            session.restore(transaction, apply=True)
        self.assertEqual(session.journal(transaction)["phase"], "restored")
        self.assertEqual(os.readlink(self.home / ".config/niri/config.kdl"), str(self.old / "platforms/linux/niri/config.kdl"))
        self.assertEqual(self.unit_states, {session.BAR: "active", session.WALLPAPER: "active"})


if __name__ == "__main__":
    unittest.main()
