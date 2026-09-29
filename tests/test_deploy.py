"""Exercise deployment against disposable homes, never the current user's files."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("deploy", Path(__file__).resolve().parents[1] / "scripts/deploy.py")
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "repo"
        self.home = self.root / "home"
        self.config, self.state = deploy.locations(self.home)
        for name in ("config/kitty/kitty.conf", "config/kitty/theme.conf",
                     "config/nvim/init.lua", "platforms/macos/kitty.conf", "platforms/linux/kitty.conf"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name, encoding="utf-8")
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def install(self, apply=True, platform="linux"):
        return deploy.install(self.repo, self.config, self.state, platform, apply)

    def original(self, relative, contents="original"):
        path = self.config / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def test_dry_run_creates_nothing(self):
        self.install(apply=False)
        self.assertFalse(self.home.exists())

    def test_apply_idempotence_restore_and_local_overrides(self):
        kitty = self.original("kitty/kitty.conf")
        nvim = self.original("nvim/init.lua", "personal Neovim")
        local = self.original("dotfiles-local/nvim.lua", "local")
        backup = self.install()
        self.assertEqual(os.readlink(self.config / "kitty/platform.conf"), str(self.repo / "platforms/linux/kitty.conf"))
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(backup.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((backup / "manifest.json").stat().st_mode), 0o600)
        self.assertEqual((backup / "00-kitty.conf").read_text(), "original")
        self.assertEqual((backup / "03-nvim/init.lua").read_text(), "personal Neovim")
        self.assertIsNone(self.install())
        self.assertEqual(len(list(backup.parent.iterdir())), 1)
        deploy.restore(backup)
        self.assertTrue(kitty.is_symlink())
        deploy.restore(backup, apply=True)
        self.assertFalse(kitty.is_symlink())
        self.assertEqual(kitty.read_text(), "original")
        self.assertEqual(nvim.read_text(), "personal Neovim")
        self.assertFalse((self.config / "kitty/theme.conf").exists())
        self.assertEqual(local.read_text(), "local")
        kitty.write_text("edited after restore")
        deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "edited after restore")

    def test_dangling_symlink_original_is_preserved(self):
        target = self.config / "nvim"
        target.parent.mkdir(parents=True)
        target.symlink_to("missing-original")
        backup = self.install()
        self.assertTrue((backup / "03-nvim").is_symlink())
        deploy.restore(backup, apply=True)
        self.assertEqual(os.readlink(target), "missing-original")
        self.assertFalse(target.exists())

    def test_macos_platform_selection(self):
        self.install(platform="macos")
        self.assertEqual(os.readlink(self.config / "kitty/platform.conf"), str(self.repo / "platforms/macos/kitty.conf"))

    def test_global_preflight_rejects_symlinked_parent(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "kitty.conf").write_text("untouched")
        self.config.mkdir(parents=True)
        (self.config / "kitty").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(deploy.DeploymentError, "symlinked parent"):
            self.install()
        self.assertEqual((outside / "kitty.conf").read_text(), "untouched")
        self.assertFalse(self.state.exists())
        self.assertFalse((self.config / "nvim").exists())

    def test_missing_source_stops_before_any_write(self):
        original = self.original("kitty/kitty.conf")
        (self.repo / "config/nvim/init.lua").unlink()
        (self.repo / "config/nvim").rmdir()
        with self.assertRaisesRegex(deploy.DeploymentError, "Missing configuration source"):
            self.install()
        self.assertEqual(original.read_text(), "original")
        self.assertFalse(self.state.exists())

    def test_restore_conflict_preflights_all_entries(self):
        kitty = self.original("kitty/kitty.conf")
        backup = self.install()
        nvim = self.config / "nvim"
        nvim.unlink()
        nvim.mkdir()
        (nvim / "new-work.lua").write_text("user work")
        with self.assertRaisesRegex(deploy.DeploymentError, "intervening changes"):
            deploy.restore(backup, apply=True)
        self.assertTrue(kitty.is_symlink())
        self.assertEqual((nvim / "new-work.lua").read_text(), "user work")
        self.assertEqual((backup / "00-kitty.conf").read_text(), "original")

    def test_failure_keeps_original_and_can_restore_partial_apply(self):
        kitty = self.original("kitty/kitty.conf")
        original_symlink = Path.symlink_to

        def fail_second_link(path, *args, **kwargs):
            if path.name == "theme.conf":
                raise OSError("simulated creation failure")
            return original_symlink(path, *args, **kwargs)

        with mock.patch.object(Path, "symlink_to", fail_second_link):
            with self.assertRaisesRegex(deploy.DeploymentError, "no automatic rollback"):
                self.install()
        backup = next((self.state / "dotfiles/backups").iterdir())
        self.assertTrue(kitty.is_symlink())
        self.assertEqual((backup / "00-kitty.conf").read_text(), "original")
        deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "original")
        self.assertFalse((self.config / "nvim").exists())

    def test_failure_after_backup_keeps_dangling_original(self):
        target = self.config / "kitty/kitty.conf"
        target.parent.mkdir(parents=True)
        target.symlink_to("missing-original")
        with mock.patch.object(Path, "symlink_to", side_effect=OSError("simulated failure")):
            with self.assertRaises(deploy.DeploymentError):
                self.install()
        backup = next((self.state / "dotfiles/backups").iterdir())
        self.assertFalse(target.is_symlink())
        self.assertEqual(os.readlink(backup / "00-kitty.conf"), "missing-original")
        deploy.restore(backup, apply=True)
        self.assertEqual(os.readlink(target), "missing-original")

    def test_apply_does_not_overwrite_intervening_file(self):
        kitty = self.original("kitty/kitty.conf")
        original_symlink = Path.symlink_to

        def race(path, *args, **kwargs):
            if path == kitty:
                path.write_text("intervening user work")
            return original_symlink(path, *args, **kwargs)

        with mock.patch.object(Path, "symlink_to", race):
            with self.assertRaises(deploy.DeploymentError):
                self.install()
        self.assertEqual(kitty.read_text(), "intervening user work")
        backup = next((self.state / "dotfiles/backups").iterdir())
        self.assertEqual((backup / "00-kitty.conf").read_text(), "original")
        with self.assertRaisesRegex(deploy.DeploymentError, "intervening changes"):
            deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "intervening user work")

    def test_restore_missing_backup_refuses_data_loss(self):
        self.original("kitty/kitty.conf")
        backup = self.install()
        (backup / "00-kitty.conf").unlink()
        with self.assertRaisesRegex(deploy.DeploymentError, "backup is missing"):
            deploy.restore(backup, apply=True)
        self.assertTrue((self.config / "kitty/kitty.conf").is_symlink())

    def test_restore_all_originally_missing_paths(self):
        backup = self.install()
        deploy.restore(backup, apply=True)
        for target, _ in deploy.entries_for(self.repo, self.config, "linux"):
            self.assertIsNone(deploy.snapshot(target))

    def test_restore_rejects_symlinked_parent_before_changing_other_paths(self):
        backup = self.install()
        kitty = self.config / "kitty"
        moved = self.root / "moved-kitty"
        kitty.rename(moved)
        kitty.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(deploy.DeploymentError, "symlinked parent"):
            deploy.restore(backup, apply=True)
        self.assertTrue((self.config / "nvim").is_symlink())
        self.assertTrue((moved / "kitty.conf").is_symlink())

    def test_restore_can_resume_after_interrupted_manifest_write(self):
        kitty = self.original("kitty/kitty.conf")
        backup = self.install()
        with mock.patch.object(deploy, "save_manifest", side_effect=OSError("simulated write failure")):
            with self.assertRaisesRegex(deploy.DeploymentError, "Restore stopped"):
                deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "original")
        deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "original")
        self.assertTrue(json.loads((backup / "manifest.json").read_text())["restored"])

    def test_manifest_path_traversal_is_rejected(self):
        self.original("kitty/kitty.conf")
        backup = self.install()
        path = backup / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["entries"][0]["backup"] = "../../outside"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(deploy.DeploymentError, "invalid backup path"):
            deploy.restore(backup, apply=True)
        self.assertTrue((self.config / "kitty/kitty.conf").is_symlink())

    def test_xdg_paths_and_home_isolation(self):
        env = {"XDG_CONFIG_HOME": str(self.root / "xdg-config"),
               "XDG_STATE_HOME": str(self.root / "xdg-state")}
        self.assertEqual(deploy.locations(environ=env),
                         (self.root / "xdg-config", self.root / "xdg-state"))
        self.assertEqual(deploy.locations(self.home, env),
                         (self.home / ".config", self.home / ".local/state"))
        with self.assertRaisesRegex(deploy.DeploymentError, "absolute path"):
            deploy.locations(environ={"XDG_CONFIG_HOME": "relative"})


if __name__ == "__main__":
    unittest.main()
