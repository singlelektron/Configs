"""Verify monitor build provenance and atomic install boundaries without compiling."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("monitor_build", ROOT / "scripts/build-monitor.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class MonitorBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="monitor build 中文-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.destination = self.root / "install"
        self.archive = self.root / "source.tar.gz"
        self.patch = self.root / "view.patch"
        self.patch.write_text("--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-original\n+parameter-only\n")
        self.make_archive({"README.md": b"original\n", "LICENSE": b"upstream GPL license\n"})
        patcher = mock.patch.object(builder, "PATCH", self.patch)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_archive(self, files):
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, contents in files.items():
                member = tarfile.TarInfo(f"btop-{builder.VERSION}/{name}")
                member.size = len(contents)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(contents))

    def expected_archive(self):
        return mock.patch.object(builder, "SOURCE_SHA256", builder.digest(self.archive))

    def compiler(self, fail=False):
        real_run = subprocess.run
        commands = []
        destination_existed = self.destination.exists()

        def run(command, **kwargs):
            if command[0] != "make":
                return real_run(command, **kwargs)
            commands.append(command)
            source = kwargs["cwd"]
            self.assertEqual((source / "README.md").read_text(), "parameter-only\n")
            self.assertEqual(self.destination.exists(), destination_existed,
                             "Builds must finish before creating an install root")
            if fail:
                raise subprocess.CalledProcessError(2, command)
            (source / "bin").mkdir()
            binary = source / "bin/btop"
            binary.write_bytes(b"#!/bin/sh\nprintf 'btop parameter-only test build\\n'\n")
            binary.chmod(0o755)
            return subprocess.CompletedProcess(command, 0)

        return mock.patch.object(builder.subprocess, "run", side_effect=run), commands

    def build(self):
        compile_mock, _ = self.compiler()
        with self.expected_archive(), compile_mock:
            return builder.prepare(self.destination, self.archive)

    def test_source_release_and_checksum_are_pinned(self):
        self.assertEqual(builder.VERSION, "1.4.7")
        self.assertEqual(builder.SOURCE_URL, "https://codeload.github.com/aristocratos/btop/tar.gz/refs/tags/v1.4.7")
        self.assertEqual(builder.SOURCE_SHA256, "933de2e4d1b2211a638be463eb6e8616891bfba73aef5d38060bd8319baeefc6")

    def test_invalid_archive_is_refused_before_destination_writes(self):
        with mock.patch.object(builder, "download") as download, mock.patch.object(builder.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                builder.prepare(self.destination, self.archive)
        self.assertFalse(self.destination.exists())
        download.assert_not_called()
        run.assert_not_called()

    def test_failed_patch_keeps_destination_untouched(self):
        self.patch.write_text("--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-wrong base text\n+changed\n")
        compile_mock, commands = self.compiler()
        with self.expected_archive(), compile_mock:
            with self.assertRaises(subprocess.CalledProcessError):
                builder.prepare(self.destination, self.archive)
        self.assertFalse(self.destination.exists())
        self.assertEqual(commands, [])

    def test_failed_compile_keeps_destination_untouched(self):
        compile_mock, _ = self.compiler(fail=True)
        with self.expected_archive(), compile_mock:
            with self.assertRaises(subprocess.CalledProcessError):
                builder.prepare(self.destination, self.archive)
        self.assertFalse(self.destination.exists())

    def test_failed_upgrade_preserves_previous_stable_build(self):
        binary = self.build()
        stable = self.destination / "btop-view"
        original_link, original_binary = stable.readlink(), binary.read_bytes()
        self.patch.write_bytes(self.patch.read_bytes() + b"\n")
        compile_mock, _ = self.compiler(fail=True)
        with self.expected_archive(), compile_mock:
            with self.assertRaises(subprocess.CalledProcessError):
                builder.prepare(self.destination, self.archive)
        self.assertEqual(stable.readlink(), original_link)
        self.assertEqual(binary.read_bytes(), original_binary)
        self.assertEqual(len(list(self.destination.glob("btop-view-*"))), 1)

    def test_successful_build_installs_owned_binary_license_and_provenance(self):
        compile_mock, commands = self.compiler()
        with self.expected_archive(), compile_mock, mock.patch.object(builder.platform, "system", return_value="Linux"):
            binary = builder.prepare(self.destination, self.archive, jobs=2)
            self.assertEqual(builder.check(self.destination), binary)
        version = binary.parents[2]
        self.assertEqual((self.destination / "btop-view").readlink(), Path(version.name))
        data = json.loads((version / "provenance.json").read_text())
        self.assertEqual(data["owner"], builder.OWNER)
        self.assertEqual(data["source_sha256"], builder.digest(self.archive))
        self.assertEqual(data["patch_sha256"], builder.digest(self.patch))
        self.assertEqual(data["binary_sha256"], builder.digest(binary))
        self.assertEqual((version / "LICENSE").read_text(), "upstream GPL license\n")
        self.assertEqual(commands, [["make", "-j2", "RSMI_STATIC=false", "STATIC=false", "GPU_SUPPORT=true"]])
        self.assertFalse(list(self.destination.glob(".btop-view-*")))

    def test_existing_valid_version_is_reused_without_rebuilding(self):
        binary = self.build()
        before = binary.stat().st_mtime_ns
        with self.expected_archive(), mock.patch.object(builder.subprocess, "run") as run, mock.patch.object(builder, "download") as download:
            self.assertEqual(builder.prepare(self.destination), binary)
        run.assert_not_called()
        download.assert_not_called()
        self.assertEqual(binary.stat().st_mtime_ns, before)

    def test_check_is_read_only_and_detects_changed_binary(self):
        binary = self.build()
        before = {str(p): p.lstat().st_mtime_ns for p in self.destination.rglob("*")}
        with self.expected_archive(), mock.patch.object(builder.subprocess, "run") as run, mock.patch.object(builder, "download") as download:
            self.assertEqual(builder.check(self.destination), binary)
            self.assertEqual({str(p): p.lstat().st_mtime_ns for p in self.destination.rglob("*")}, before)
            binary.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "binary"):
                builder.check(self.destination)
        run.assert_not_called()
        download.assert_not_called()

    def test_check_detects_patch_change_and_preserves_current_install(self):
        binary = self.build()
        old_link = (self.destination / "btop-view").readlink()
        original = binary.read_bytes()
        self.patch.write_text("updated local patch\n")
        with self.expected_archive(), self.assertRaisesRegex(ValueError, "patch does not match"):
            builder.check(self.destination)
        self.assertEqual(binary.read_bytes(), original)
        self.assertEqual((self.destination / "btop-view").readlink(), old_link)

    def test_refuses_unrelated_stable_destination(self):
        self.destination.mkdir()
        stable = self.destination / "btop-view"
        stable.write_text("personal data")
        with mock.patch.object(builder, "download") as download, self.assertRaisesRegex(ValueError, "unrelated"):
            builder.prepare(self.destination, self.archive)
        self.assertEqual(stable.read_text(), "personal data")
        download.assert_not_called()

    def test_refuses_unrelated_existing_version_and_external_symlink(self):
        self.destination.mkdir()
        version = self.destination / f"btop-view-{builder.VERSION}-{builder.digest(self.patch)}"
        version.mkdir()
        (version / "personal").write_text("keep")
        with self.assertRaises(ValueError):
            builder.prepare(self.destination, self.archive)
        self.assertEqual((version / "personal").read_text(), "keep")
        (self.destination / "btop-view").symlink_to(self.root / "elsewhere")
        with self.assertRaisesRegex(ValueError, "inside the install root"):
            builder.prepare(self.destination, self.archive)

    def test_archive_traversal_is_refused_before_extraction(self):
        self.make_archive({"../escaped": b"do not extract"})
        with self.expected_archive(), self.assertRaisesRegex(ValueError, "Unsafe"):
            builder.prepare(self.destination, self.archive)
        self.assertFalse(self.destination.exists())
        self.assertFalse((self.root / "escaped").exists())

    def test_macos_uses_upstream_gpu_default_and_jobs_must_be_positive(self):
        with mock.patch.object(builder.platform, "system", return_value="Darwin"):
            command = builder.build_command(2)
        self.assertEqual(command, ["make", "-j2", "RSMI_STATIC=false", "STATIC=false"])
        with self.assertRaisesRegex(ValueError, "positive"):
            builder.prepare(self.destination, self.archive, jobs=0)
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
