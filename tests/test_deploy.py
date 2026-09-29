"""Exercise deployment against disposable homes, never the current user's files."""

import contextlib
import errno
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
        core = ("config/kitty/kitty.conf", "config/kitty/theme.conf",
                "config/nvim/init.lua", "config/lazygit/config.yml",
                "platforms/macos/kitty.conf", "platforms/linux/kitty.conf")
        for name in (*core, *(source for _, source in deploy.NIRI_FILES)):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name, encoding="utf-8")
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def install(self, apply=True, platform="linux", desktop=None):
        return deploy.install(self.repo, self.config, self.state, platform, apply, desktop)

    def original(self, relative, contents="original"):
        path = self.config / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    @contextlib.contextmanager
    def cross_device_moves(self):
        """Model split XDG filesystems while allowing local staging renames."""
        rename = Path.rename

        def cross_device(path, target):
            target = Path(target)
            between_roots = (
                deploy.within(path, self.config) and deploy.within(target, self.state)
            ) or (
                deploy.within(path, self.state) and deploy.within(target, self.config)
            )
            if between_roots:
                raise OSError(errno.EXDEV, "simulated cross-device move")
            return rename(path, target)

        with mock.patch.object(Path, "rename", cross_device):
            yield

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

    def test_desktop_is_opt_in_on_both_platforms(self):
        niri = self.original("niri/config.kdl", "personal desktop")
        for platform in ("linux", "macos"):
            with self.subTest(platform=platform):
                self.install(platform=platform)
                self.assertEqual(niri.read_text(), "personal desktop")
                self.assertFalse(niri.is_symlink())
                self.assertFalse((self.config / "systemd").exists())

    def test_niri_dry_run_creates_nothing(self):
        self.install(desktop="niri", apply=False)
        self.assertFalse(self.home.exists())

    def test_niri_apply_restore_preserves_neighboring_state_and_overrides(self):
        niri = self.original("niri/config.kdl", "old niri")
        waybar = self.original("waybar/balanced.json", "old bar")
        local = self.original("dotfiles-local/niri.kdl", "private outputs")
        state = self.original("niri/private-state.json", "private state")
        unrelated_unit = self.original("systemd/user/other.service", "other service")
        backup = self.install(desktop="niri")
        self.assertEqual(deploy.load_manifest(backup)["desktop"], "niri")
        for target, source in deploy.NIRI_FILES:
            self.assertEqual(os.readlink(self.config / target), str(self.repo / source))
        self.assertIsNone(self.install(desktop="niri"))
        deploy.restore(backup, apply=True)
        self.assertEqual(niri.read_text(), "old niri")
        self.assertEqual(waybar.read_text(), "old bar")
        self.assertEqual(local.read_text(), "private outputs")
        self.assertEqual(state.read_text(), "private state")
        self.assertEqual(unrelated_unit.read_text(), "other service")
        self.assertFalse((self.config / "niri/desktopctl.py").exists())
        self.assertFalse((self.config / "systemd/user/niri.service.wants").exists())

    def test_incremental_desktop_restore_retains_core_and_legacy_restore_works(self):
        core_backup = self.install()
        self.assertNotIn("desktop", deploy.load_manifest(core_backup))
        desktop_backup = self.install(desktop="niri")
        entries = deploy.load_manifest(desktop_backup)["entries"]
        self.assertEqual(len(entries), len(deploy.NIRI_FILES))
        deploy.restore(desktop_backup, apply=True)
        self.assertTrue((self.config / "nvim").is_symlink())
        self.assertFalse((self.config / "niri/config.kdl").exists())
        deploy.restore(core_backup, apply=True)
        self.assertFalse((self.config / "nvim").exists())

    def test_niri_rejects_macos_before_writes(self):
        with self.assertRaisesRegex(deploy.DeploymentError, "Linux-only"):
            self.install(platform="macos", desktop="niri")
        self.assertFalse(self.home.exists())

    def test_desktop_rejects_unknown_profiles_before_writes(self):
        for desktop in ("gnome", "", True, []):
            with self.subTest(desktop=desktop):
                with self.assertRaisesRegex(deploy.DeploymentError, "Unsupported desktop"):
                    self.install(desktop=desktop)
        self.assertFalse(self.home.exists())

    def test_missing_desktop_source_preflights_before_core_changes(self):
        original = self.original("kitty/kitty.conf", "original kitty")
        (self.repo / "config/waybar/performance.json").unlink()
        with self.assertRaisesRegex(deploy.DeploymentError, "Missing configuration source"):
            self.install(desktop="niri")
        self.assertEqual(original.read_text(), "original kitty")
        self.assertFalse(original.is_symlink())
        self.assertFalse(self.state.exists())

    def test_desktop_symlinked_parent_preflights_before_core_changes(self):
        outside = self.root / "external-units"
        outside.mkdir()
        (self.config / "systemd").mkdir(parents=True)
        (self.config / "systemd/user").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(deploy.DeploymentError, "symlinked parent"):
            self.install(desktop="niri")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(self.state.exists())
        self.assertFalse((self.config / "kitty").exists())

    def test_desktop_manifest_scope_tampering_is_rejected(self):
        backup = self.install(desktop="niri")
        path = backup / "manifest.json"
        manifest = json.loads(path.read_text())
        for desktop in (None, "unknown"):
            with self.subTest(desktop=desktop):
                changed = dict(manifest)
                changed["desktop"] = desktop
                path.write_text(json.dumps(changed))
                with self.assertRaises(deploy.DeploymentError):
                    deploy.restore(backup, apply=True)
                self.assertTrue((self.config / "kitty/kitty.conf").is_symlink())
        manifest["platform"] = "macos"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(deploy.DeploymentError, "Linux-only"):
            deploy.restore(backup, apply=True)

    def test_restore_desktop_conflict_leaves_all_other_links_intact(self):
        self.original("niri/config.kdl", "original niri")
        backup = self.install(desktop="niri")
        unit = self.config / "systemd/user/dotfiles-niri-waybar.service"
        unit.unlink()
        unit.write_text("new user unit")
        with self.assertRaisesRegex(deploy.DeploymentError, "intervening changes"):
            deploy.restore(backup, apply=True)
        self.assertEqual(unit.read_text(), "new user unit")
        self.assertTrue((self.config / "niri/config.kdl").is_symlink())

    def test_cli_rejects_restore_profile_argument(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                deploy.main(["--restore", str(self.root), "--desktop", "niri"])
        self.assertEqual(error.exception.code, 2)

    def test_cli_rejects_niri_on_macos(self):
        with mock.patch.object(deploy.sys, "platform", "darwin"), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deploy.main(["--desktop", "niri", "--home", str(self.home)]), 1)
        self.assertFalse(self.home.exists())

    def test_lazygit_config_restore_preserves_private_state(self):
        config = self.original("lazygit/config.yml", "personal Git UI")
        state = self.original("lazygit/state.yml", "private history")
        backup = self.install()
        self.assertTrue(config.is_symlink())
        self.assertEqual(state.read_text(), "private history")
        deploy.restore(backup, apply=True)
        self.assertEqual(config.read_text(), "personal Git UI")
        self.assertEqual(state.read_text(), "private history")

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
        save_manifest = deploy.save_manifest

        def fail_final_write(directory, manifest):
            if manifest["restored"]:
                raise OSError("simulated write failure")
            return save_manifest(directory, manifest)

        with mock.patch.object(deploy, "save_manifest", fail_final_write):
            with self.assertRaisesRegex(deploy.DeploymentError, "Restore stopped"):
                deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "original")
        deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "original")
        self.assertTrue(json.loads((backup / "manifest.json").read_text())["restored"])

    def test_cross_device_backup_and_restore_preserve_files_and_symlinks(self):
        kitty = self.original("kitty/kitty.conf", "personal Kitty")
        kitty.chmod(0o640)
        os.utime(kitty, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        kitty_before = deploy.snapshot(kitty)
        theme = self.config / "kitty/theme.conf"
        theme.symlink_to("missing-theme")
        init = self.original("nvim/init.lua", "personal Neovim")
        init.chmod(0o600)
        (init.parent / "linked.lua").symlink_to("init.lua")
        (init.parent / "missing.lua").symlink_to("missing-original")
        (init.parent / "cycle").symlink_to(".", target_is_directory=True)

        with self.cross_device_moves():
            backup = self.install()
            self.assertEqual((backup / "00-kitty.conf").read_text(), "personal Kitty")
            self.assertEqual(os.readlink(backup / "01-theme.conf"), "missing-theme")
            self.assertEqual(os.readlink(backup / "03-nvim/missing.lua"), "missing-original")
            self.assertEqual(os.readlink(backup / "03-nvim/cycle"), ".")
            deploy.restore(backup, apply=True)

        self.assertEqual(kitty.read_text(), "personal Kitty")
        self.assertEqual(stat.S_IMODE(kitty.stat().st_mode), 0o640)
        self.assertEqual(kitty.stat().st_mtime_ns, kitty_before["mtime_ns"])
        self.assertEqual(os.readlink(theme), "missing-theme")
        self.assertFalse(theme.exists())
        self.assertEqual(init.read_text(), "personal Neovim")
        self.assertEqual(stat.S_IMODE(init.stat().st_mode), 0o600)
        self.assertEqual(os.readlink(init.parent / "linked.lua"), "init.lua")
        self.assertEqual(os.readlink(init.parent / "missing.lua"), "missing-original")
        self.assertEqual(os.readlink(init.parent / "cycle"), ".")

    def test_cross_device_copy_failure_keeps_original_and_hides_partial_backup(self):
        init = self.original("nvim/init.lua", "personal Neovim")

        def partial_copy(source, target, **kwargs):
            Path(target).mkdir()
            (Path(target) / "incomplete").write_text("partial copy")
            raise OSError("simulated copy failure")

        with self.cross_device_moves(), mock.patch.object(deploy.shutil, "copytree", partial_copy):
            with self.assertRaisesRegex(deploy.DeploymentError, "simulated copy failure"):
                self.install()
        backup = next((self.state / "dotfiles/backups").iterdir())
        self.assertEqual(init.read_text(), "personal Neovim")
        self.assertIsNone(deploy.snapshot(backup / "03-nvim"))
        self.assertFalse(list(backup.glob(".dotfiles-move-*")))
        deploy.restore(backup, apply=True)
        self.assertEqual(init.read_text(), "personal Neovim")
        self.assertFalse((self.config / "kitty/kitty.conf").is_symlink())

    def test_cross_device_backup_keeps_nested_edits_during_copy(self):
        for change in ("normal-edit", "same-metadata", "added-file"):
            with self.subTest(change=change):
                fixture = self.root / change
                self.config, self.state = fixture / "config", fixture / "state"
                nested = self.original("nvim/lua/personal/settings.lua", "original")
                source = self.config / "nvim"
                root_before = deploy.snapshot(source)
                before = nested.stat()
                contents = {"normal-edit": "new user work during copy",
                            "same-metadata": "new work", "added-file": "original"}[change]
                copytree = deploy.shutil.copytree

                def edit_after_copy(path, target, *args, **kwargs):
                    result = copytree(path, target, *args, **kwargs)
                    if Path(path) == source:
                        if change == "added-file":
                            (nested.parent / "added.lua").write_text("new nested file")
                        else:
                            nested.write_text(contents)
                        if change == "same-metadata":
                            os.utime(nested, ns=(before.st_atime_ns, before.st_mtime_ns))
                            self.assertEqual(nested.stat().st_size, before.st_size)
                            self.assertEqual(nested.stat().st_mtime_ns, before.st_mtime_ns)
                        self.assertEqual(deploy.snapshot(source), root_before)
                    return result

                with self.cross_device_moves(), mock.patch.object(deploy.shutil, "copytree", edit_after_copy):
                    with self.assertRaisesRegex(deploy.DeploymentError, "Source changed during copy"):
                        self.install()
                backup = next((self.state / "dotfiles/backups").iterdir())
                self.assertEqual(nested.read_text(), contents)
                self.assertIsNone(deploy.snapshot(backup / "03-nvim"))
                self.assertFalse(list(backup.glob(".dotfiles-move-*")))
                deploy.restore(backup, apply=True)
                self.assertEqual(nested.read_text(), contents)
                if change == "added-file":
                    self.assertEqual((nested.parent / "added.lua").read_text(), "new nested file")

    def test_cross_device_backup_keeps_nested_edits_after_publication(self):
        nested = self.original("nvim/lua/personal/settings.lua", "original")
        source = self.config / "nvim"
        root_before = deploy.snapshot(source)
        with self.cross_device_moves():
            rename = Path.rename

            def edit_after_publication(path, target):
                result = rename(path, target)
                if path.name == "original" and Path(target).name == "03-nvim":
                    nested.write_text("new user work before cleanup")
                    self.assertEqual(deploy.snapshot(source), root_before)
                return result

            with mock.patch.object(Path, "rename", edit_after_publication):
                with self.assertRaisesRegex(deploy.DeploymentError, "Source changed during copy"):
                    self.install()
        backup = next((self.state / "dotfiles/backups").iterdir())
        self.assertEqual(nested.read_text(), "new user work before cleanup")
        self.assertEqual((backup / "03-nvim/lua/personal/settings.lua").read_text(), "original")

    def test_cross_device_restore_keeps_nested_backup_edits_for_retry(self):
        nested = self.original("nvim/lua/personal/settings.lua", "original")
        with self.cross_device_moves():
            backup = self.install()
        source = backup / "03-nvim"
        backup_file = source / "lua/personal/settings.lua"
        root_before = deploy.snapshot(source)
        copytree = deploy.shutil.copytree

        def edit_after_copy(path, target, *args, **kwargs):
            result = copytree(path, target, *args, **kwargs)
            if Path(path) == source:
                backup_file.write_text("new backup content during restore")
                self.assertEqual(deploy.snapshot(source), root_before)
            return result

        with self.cross_device_moves(), mock.patch.object(deploy.shutil, "copytree", edit_after_copy):
            with self.assertRaisesRegex(deploy.DeploymentError, "Source changed during copy"):
                deploy.restore(backup, apply=True)
        self.assertEqual(backup_file.read_text(), "new backup content during restore")
        self.assertIsNone(deploy.snapshot(self.config / "nvim"))
        self.assertFalse(list(self.config.glob(".dotfiles-move-*")))
        with self.cross_device_moves():
            deploy.restore(backup, apply=True)
        self.assertEqual(nested.read_text(), "new backup content during restore")
        self.assertTrue(json.loads((backup / "manifest.json").read_text())["restored"])

    def test_cross_device_nested_read_failure_keeps_original(self):
        nested = self.original("nvim/lua/personal/settings.lua", "original")
        source = self.config / "nvim"
        copytree, open_path = deploy.shutil.copytree, Path.open
        copied = False

        def finish_copy(path, target, *args, **kwargs):
            nonlocal copied
            result = copytree(path, target, *args, **kwargs)
            if Path(path) == source:
                copied = True
            return result

        def fail_nested_read(path, *args, **kwargs):
            if copied and path == nested:
                raise OSError("simulated nested read failure")
            return open_path(path, *args, **kwargs)

        with self.cross_device_moves(), mock.patch.object(deploy.shutil, "copytree", finish_copy), \
                mock.patch.object(Path, "open", fail_nested_read):
            with self.assertRaisesRegex(deploy.DeploymentError, "simulated nested read failure"):
                self.install()
        backup = next((self.state / "dotfiles/backups").iterdir())
        self.assertEqual(nested.read_text(), "original")
        self.assertIsNone(deploy.snapshot(backup / "03-nvim"))
        self.assertFalse(list(backup.glob(".dotfiles-move-*")))

    def test_cross_device_backup_cleanup_failure_can_restore_with_both_copies(self):
        init = self.original("nvim/init.lua", "personal Neovim")
        rmtree = deploy.shutil.rmtree

        def fail_original_cleanup(path, *args, **kwargs):
            if Path(path) == init.parent:
                raise OSError("simulated source cleanup failure")
            return rmtree(path, *args, **kwargs)

        with self.cross_device_moves(), mock.patch.object(deploy.shutil, "rmtree", fail_original_cleanup):
            with self.assertRaisesRegex(deploy.DeploymentError, "simulated source cleanup failure"):
                self.install()
        backup = next((self.state / "dotfiles/backups").iterdir())
        self.assertEqual(init.read_text(), "personal Neovim")
        self.assertEqual((backup / "03-nvim/init.lua").read_text(), "personal Neovim")
        deploy.restore(backup, apply=True)
        self.assertEqual(init.read_text(), "personal Neovim")
        self.assertTrue(json.loads((backup / "manifest.json").read_text())["restored"])

    def test_cross_device_restore_prepare_write_failure_keeps_backup_for_retry(self):
        kitty = self.original("kitty/kitty.conf")
        with self.cross_device_moves():
            backup = self.install()
        save_manifest = deploy.save_manifest
        backup_inode = deploy.snapshot(backup / "00-kitty.conf")["inode"]

        def fail_staging_snapshot(directory, manifest):
            candidate = manifest["entries"][0].get("restored_original")
            if candidate and candidate["inode"] != backup_inode:
                raise OSError("simulated prepare write failure")
            return save_manifest(directory, manifest)

        with self.cross_device_moves(), mock.patch.object(deploy, "save_manifest", fail_staging_snapshot):
            with self.assertRaisesRegex(deploy.DeploymentError, "simulated prepare write failure"):
                deploy.restore(backup, apply=True)
        self.assertEqual((backup / "00-kitty.conf").read_text(), "original")
        self.assertIsNone(deploy.snapshot(kitty))
        self.assertFalse(list(kitty.parent.glob(".dotfiles-move-*")))
        with self.cross_device_moves():
            deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "original")

    def test_cross_device_restore_resumes_after_final_manifest_write_failure(self):
        kitty = self.original("kitty/kitty.conf")
        before = deploy.snapshot(kitty)
        with self.cross_device_moves():
            backup = self.install()
        save_manifest = deploy.save_manifest

        def fail_final_write(directory, manifest):
            if manifest["restored"]:
                raise OSError("simulated final write failure")
            return save_manifest(directory, manifest)

        with self.cross_device_moves(), mock.patch.object(deploy, "save_manifest", fail_final_write):
            with self.assertRaisesRegex(deploy.DeploymentError, "simulated final write failure"):
                deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "original")
        self.assertNotEqual(deploy.snapshot(kitty), before)
        self.assertIsNone(deploy.snapshot(backup / "00-kitty.conf"))
        manifest = json.loads((backup / "manifest.json").read_text())
        self.assertFalse(manifest["restored"])
        self.assertEqual(manifest["entries"][0]["restored_original"], deploy.snapshot(kitty))
        with self.cross_device_moves():
            deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "original")
        self.assertTrue(json.loads((backup / "manifest.json").read_text())["restored"])

    def test_cross_device_restore_cleanup_failure_can_resume_with_both_copies(self):
        init = self.original("nvim/init.lua", "personal Neovim")
        with self.cross_device_moves():
            backup = self.install()
        rmtree = deploy.shutil.rmtree

        def fail_backup_cleanup(path, *args, **kwargs):
            if Path(path) == backup / "03-nvim":
                raise OSError("simulated backup cleanup failure")
            return rmtree(path, *args, **kwargs)

        with self.cross_device_moves(), mock.patch.object(deploy.shutil, "rmtree", fail_backup_cleanup):
            with self.assertRaisesRegex(deploy.DeploymentError, "simulated backup cleanup failure"):
                deploy.restore(backup, apply=True)
        self.assertEqual(init.read_text(), "personal Neovim")
        self.assertEqual((backup / "03-nvim/init.lua").read_text(), "personal Neovim")
        with self.cross_device_moves():
            deploy.restore(backup, apply=True)
        self.assertEqual(init.read_text(), "personal Neovim")
        self.assertTrue(json.loads((backup / "manifest.json").read_text())["restored"])

    def test_non_cross_device_rename_error_does_not_copy_original(self):
        kitty = self.original("kitty/kitty.conf")
        with mock.patch.object(Path, "rename", side_effect=OSError(errno.EACCES, "simulated denied rename")), \
                mock.patch.object(deploy.shutil, "copy2") as copy:
            with self.assertRaisesRegex(deploy.DeploymentError, "simulated denied rename"):
                self.install()
        copy.assert_not_called()
        self.assertEqual(kitty.read_text(), "original")
        backup = next((self.state / "dotfiles/backups").iterdir())
        self.assertIsNone(deploy.snapshot(backup / "00-kitty.conf"))
        deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "original")

    def test_cross_device_move_keeps_source_edited_before_cleanup(self):
        kitty = self.original("kitty/kitty.conf")
        with self.cross_device_moves():
            rename = Path.rename

            def edit_after_publication(path, target):
                result = rename(path, target)
                if path.name == "original" and Path(target).name == "00-kitty.conf":
                    kitty.write_text("new user work during copy")
                return result

            with mock.patch.object(Path, "rename", edit_after_publication):
                with self.assertRaisesRegex(deploy.DeploymentError, "Source changed during copy"):
                    self.install()
        backup = next((self.state / "dotfiles/backups").iterdir())
        self.assertEqual(kitty.read_text(), "new user work during copy")
        self.assertEqual((backup / "00-kitty.conf").read_text(), "original")
        with self.assertRaisesRegex(deploy.DeploymentError, "intervening changes"):
            deploy.restore(backup, apply=True)
        self.assertEqual(kitty.read_text(), "new user work during copy")

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
