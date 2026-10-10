"""Exercise immutable desktop sources and deployment using disposable Git repos/homes."""
import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("desktop_baseline", REPO / "scripts/desktop-baseline.py")
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="desktop-baseline-test-")
        self.addCleanup(self.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.home = self.root / "home"
        self.release = self.root / "versions/baseline"
        self.pairs = (("niri/config.kdl", "platforms/linux/niri/config.kdl"),
                      ("niri/desktopctl.py", "config/desktop/desktopctl.py"),
                      ("quickshell/desktop-island/shell.qml", "config/quickshell/desktop-island/shell.qml"),
                      ("gtk-3.0/settings.ini", "config/gtk-3.0/settings.ini"),
                      ("gtk-4.0/settings.ini", "config/gtk-4.0/settings.ini"),
                      ("systemd/user/dotfiles-niri-waybar.service", "platforms/linux/systemd/dotfiles-niri-waybar.service"))
        deploy = (REPO / "scripts/deploy.py").read_text()
        node = next(n for n in ast.parse(deploy).body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "NIRI_FILES" for t in n.targets))
        lines = deploy.splitlines(keepends=True)
        deploy = "".join(lines[:node.lineno - 1]) + "NIRI_FILES = " + repr(self.pairs) + "\n" + "".join(lines[node.end_lineno:])
        self.write("scripts/deploy.py", deploy)
        self.current_helper = (REPO / "config/desktop/desktopctl.py").read_text()
        legacy_methods = '''class Desktop:
    def shell(self):
        if os.environ.get("DOTFILES_BAR_BACKEND") == "waybar" or not shutil.which("quickshell"):
            self.waybar()
            return
        os.environ["DOTFILES_BAR_PROFILE"] = self.settings()["bar_profile"]
        os.execvp("quickshell", ["quickshell", "--path", str(self.config / "quickshell/desktop-island/shell.qml")])

    def music(self, action="open"):
        self.interface_module("music").run(self, action)
'''
        self.write("config/desktop/desktopctl.py", legacy_methods)
        self.write("platforms/linux/niri/config.kdl", 'binds { XF86AudioPlay { spawn "old"; } }\n')
        self.write("config/quickshell/desktop-island/shell.qml", "legacy verified shell\n")
        for version in (3, 4):
            self.write(f"config/gtk-{version}.0/settings.ini", "[Settings]\ngtk-application-prefer-dark-theme=false\ngtk-font-name=Legacy 10\n")
        self.write("platforms/linux/systemd/dotfiles-niri-waybar.service", 'ExecStart=/usr/bin/python3 "%E/niri/desktopctl.py" shell\n')
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=baseline-test", "-c", "user.email=test@invalid", "commit", "-qm", "legacy")
        self.legacy = self.git("rev-parse", "HEAD").strip()
        self.write("config/desktop/desktopctl.py", self.current_helper)
        self.current_niri = 'binds { XF86AudioPlay { spawn "playerctl" "play-pause"; } }\ninclude optional=true "../dotfiles-local/niri.kdl"\n'
        self.write("platforms/linux/niri/config.kdl", self.current_niri)
        self.write("platforms/linux/systemd/dotfiles-niri-waybar.service", 'ExecStart=/usr/bin/python3 "%E/niri/desktopctl.py" waybar\n')
        (self.repo / "config/quickshell/desktop-island/shell.qml").unlink()
        for version in (3, 4):
            (self.repo / f"config/gtk-{version}.0/settings.ini").unlink()
        self.git("add", "-A")
        self.git("-c", "user.name=baseline-test", "-c", "user.email=test@invalid", "commit", "-qm", "current")
        self.current = self.git("rev-parse", "HEAD").strip()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def cleanup(self):
        for parent, dirs, _ in os.walk(self.temp.name):
            Path(parent).chmod(0o700)
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def write(self, relative, text):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def prepare(self):
        return baseline.prepare(self.repo, self.legacy, self.release, self.current)

    def test_prepare_is_fixed_to_commits_and_preserves_current_niri_verbatim(self):
        self.prepare()
        manifest = baseline.verify(self.release)
        self.assertEqual(manifest["preserve_commit"], self.current)
        self.assertEqual((self.release / "platforms/linux/niri/config.kdl").read_text(), self.current_niri)
        self.assertEqual((self.release / "config/quickshell/desktop-island/shell.qml").read_text(), "legacy verified shell\n")
        self.write("platforms/linux/niri/config.kdl", "uncommitted branch change")
        self.assertEqual((self.release / "platforms/linux/niri/config.kdl").read_text(), self.current_niri)
        self.assertFalse((self.release / ".git").exists())
        self.assertFalse(self.home.exists())
        self.assertEqual(self.prepare(), self.release)

    def test_only_missing_compatibility_methods_are_added_and_existing_workflow_preserved(self):
        self.prepare()
        text = (self.release / "config/desktop/desktopctl.py").read_text()
        old_tree, new_tree = ast.parse(self.current_helper), ast.parse(text)
        old = next(n for n in old_tree.body if isinstance(n, ast.ClassDef) and n.name == "Desktop")
        new = next(n for n in new_tree.body if isinstance(n, ast.ClassDef) and n.name == "Desktop")
        new_methods = {n.name: n for n in new.body if isinstance(n, ast.FunctionDef)}
        for method in old.body:
            if isinstance(method, ast.FunctionDef):
                self.assertEqual(ast.dump(method), ast.dump(new_methods[method.name]), method.name)
        module = types.ModuleType("baseline_helper_test")
        module.__file__ = str(self.release / "config/desktop/desktopctl.py")
        exec(compile(text, module.__file__, "exec"), module.__dict__)
        desktop = module.Desktop()
        with mock.patch.object(desktop, "settings", return_value={"bar_profile": "performance"}), \
                mock.patch.object(module.shutil, "which", return_value="/usr/bin/quickshell"), \
                mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(module.os, "execvp") as launch:
            desktop.shell()
            self.assertEqual(os.environ["DOTFILES_BAR_PROFILE"], "performance")
            self.assertEqual(launch.call_args.args[0], "quickshell")
        music = mock.Mock()
        with mock.patch.object(desktop, "interface_module", return_value=music) as interface:
            desktop.music()
        interface.assert_called_once_with("music")
        music.run.assert_called_once_with(desktop, "open")
        with mock.patch.object(module, "Desktop", return_value=desktop), \
                mock.patch.object(desktop, "music") as open_music, \
                mock.patch.object(module.sys, "argv", ["desktopctl", "music"]):
            self.assertEqual(module.main(), 0)
        open_music.assert_called_once_with()

    def test_deploy_dry_run_then_dangling_link_repair_and_exact_restore(self):
        self.prepare()
        config = self.home / ".config"
        for target, source in self.pairs:
            path = config / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(self.repo / source)
        shared = config / "nvim"
        shared.symlink_to("/unrelated/editor")
        local = config / "dotfiles-local/niri.kdl"
        local.parent.mkdir()
        local.write_text("local display remains")
        before = {target: os.readlink(config / target) for target, _ in self.pairs}
        baseline.deploy(self.release, self.home)
        self.assertFalse((self.home / ".local/state").exists())
        backup = baseline.deploy(self.release, self.home, apply=True)
        self.assertEqual(len(json.loads((backup / "manifest.json").read_text())["entries"]), len(self.pairs))
        self.assertTrue(all((config / target).exists() for target, _ in self.pairs))
        self.assertEqual(os.readlink(shared), "/unrelated/editor")
        self.assertEqual(local.read_text(), "local display remains")
        self.assertIsNone(baseline.deploy(self.release, self.home, apply=True))
        baseline.restore(self.release, backup)
        self.assertTrue((config / "quickshell/desktop-island/shell.qml").exists())
        # An unmodified pinned deploy.py independently restores the subset manifest.
        subprocess.run([sys.executable, str(self.release / "scripts/deploy.py"), "--restore", str(backup), "--apply"],
                       check=True, capture_output=True)
        self.assertEqual({target: os.readlink(config / target) for target, _ in self.pairs}, before)
        self.assertFalse((config / "quickshell/desktop-island/shell.qml").exists())

    def test_tampered_baseline_and_symlink_ancestors_are_rejected_before_deploy(self):
        self.prepare()
        path = self.release / "platforms/linux/niri/config.kdl"
        path.chmod(0o644)
        path.write_text("tampered")
        with self.assertRaises(baseline.BaselineError):
            baseline.deploy(self.release, self.home, apply=True)
        self.assertFalse(self.home.exists())
        alias = self.root / "alias"
        alias.symlink_to(self.release.parent, target_is_directory=True)
        with self.assertRaises(baseline.BaselineError):
            baseline.prepare(self.repo, self.legacy, alias / "other", self.current)

    def test_existing_unrelated_destination_is_never_overwritten(self):
        self.release.mkdir(parents=True)
        (self.release / "precious").write_text("keep")
        with self.assertRaises(baseline.BaselineError):
            self.prepare()
        self.assertEqual((self.release / "precious").read_text(), "keep")

    def test_uncommitted_desktop_edits_are_not_silently_replaced_by_commit_content(self):
        self.write("platforms/linux/niri/config.kdl", "personal uncommitted change")
        with self.assertRaisesRegex(baseline.BaselineError, "differ from the working checkout"):
            self.prepare()
        self.assertFalse(self.release.exists())

    def test_restore_refuses_intervening_user_edit_and_preserves_backups(self):
        self.prepare()
        backup = baseline.deploy(self.release, self.home, apply=True)
        target = self.home / ".config/niri/config.kdl"
        target.unlink()
        target.write_text("user changed after deployment")
        with self.assertRaisesRegex(baseline.BaselineError, "Restore conflict"):
            baseline.restore(self.release, backup, apply=True)
        self.assertEqual(target.read_text(), "user changed after deployment")
        self.assertFalse(json.loads((backup / "manifest.json").read_text())["restored"])

    def test_unknown_regular_file_or_external_symlink_is_rejected_without_backups(self):
        self.prepare()
        target = self.home / ".config/niri/config.kdl"
        target.parent.mkdir(parents=True)
        for kind in ("file", "external link"):
            with self.subTest(kind=kind):
                if kind == "file":
                    target.write_text("personal configuration")
                else:
                    target.symlink_to("/elsewhere/personal.kdl")
                with self.assertRaisesRegex(baseline.BaselineError, "manual review required"):
                    baseline.deploy(self.release, self.home, apply=True)
                self.assertFalse((self.home / ".local/state").exists())
                self.assertEqual(target.read_text() if kind == "file" else os.readlink(target),
                                 "personal configuration" if kind == "file" else "/elsewhere/personal.kdl")
                target.unlink()

    def test_unknown_file_appearing_after_preflight_is_never_backed_up(self):
        self.prepare()
        module = baseline.load_deployer(self.release)
        install = module.install
        target = self.home / ".config/niri/config.kdl"

        def intervening(*args, **kwargs):
            target.parent.mkdir(parents=True)
            target.write_text("arrived during deployment")
            return install(*args, **kwargs)

        module.install = intervening
        with mock.patch.object(baseline, "load_deployer", return_value=module):
            with self.assertRaisesRegex(baseline.BaselineError, "manual review required"):
                baseline.deploy(self.release, self.home, apply=True)
        self.assertEqual(target.read_text(), "arrived during deployment")
        self.assertFalse((self.home / ".local/state").exists())

    def test_untracked_ignored_or_dangling_source_is_not_a_missing_legacy_dependency(self):
        path = self.repo / "config/quickshell/desktop-island/shell.qml"
        for kind in ("untracked", "ignored", "symlink"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    path.symlink_to("/missing/personal-shell.qml")
                else:
                    path.write_text("personal shell")
                if kind == "ignored":
                    (self.repo / ".git/info/exclude").write_text("config/quickshell/desktop-island/shell.qml\n")
                with self.assertRaisesRegex(baseline.BaselineError, "untracked or ignored local content"):
                    self.prepare()
                self.assertFalse(self.release.exists())
                path.unlink()

    def test_missing_gtk_settings_inherit_without_theme_font_or_dark_overrides(self):
        self.prepare()
        manifest = baseline.verify(self.release)
        for version in (3, 4):
            source = f"config/gtk-{version}.0/settings.ini"
            settings = (self.release / source).read_text()
            active = [line for line in settings.splitlines() if line and not line.startswith("#")]
            self.assertEqual(active, ["[Settings]"])
            self.assertNotIn("gtk-", settings)
            self.assertIsNone(manifest["files"][source]["origin_commit"])
            self.assertIn("no-override", manifest["files"][source]["compatibility"])


if __name__ == "__main__":
    unittest.main()
