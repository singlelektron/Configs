"""Exercise GIO using disposable desktop entries, never the user's applications."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

try:
    import gi
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GLib
except (ImportError, ValueError):
    GLib = None


BACKEND = Path(__file__).resolve().parents[1] / "config/desktop/launcher_backend.py"
RUNNER = r'''
import importlib.util, json, os, sys
from gi.repository import Gio, GLib
spec = importlib.util.spec_from_file_location("launcher_backend", sys.argv[1])
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
context = Gio.AppLaunchContext()
context.setenv("PATH", os.environ["FIXTURE_PATH"])
loop = GLib.MainLoop()
done = False
def finished(error):
    global done
    done = True
    print(json.dumps({"error": str(error) if error else None,
                      "path": GLib.environ_getenv(context.get_environment(), "PATH")}))
    loop.quit()
backend.launch_application(sys.argv[2], context, finished)
if not done:
    GLib.timeout_add_seconds(5, lambda: (finished("launch callback timed out"), False)[1])
    loop.run()
'''

RECORDER = r'''
import json, os, pathlib, sys, time
# Close inherited pipes immediately, so the launcher parent can exit first.
os.close(1)
os.close(2)
gate = os.environ.get("FIXTURE_GATE")
deadline = time.monotonic() + 3
while gate and not pathlib.Path(gate).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
pathlib.Path(os.environ["FIXTURE_OUTPUT"]).write_text(json.dumps({
    "args": sys.argv[1:], "cwd": os.getcwd(), "path": os.environ["PATH"],
    "parent": os.getppid(),
}))
'''


def quote_exec(value):
    # Desktop Entry Exec quoting; GLib.KeyFile applies the separate key escaping.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'


@unittest.skipIf(GLib is None, "GioUnix is only required by the Linux desktop")
class LauncherBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="launcher tests 中文-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin with spaces"
        self.bin.mkdir()
        self.apps = self.root / "data/applications"
        self.apps.mkdir(parents=True)
        self.output = self.root / "record.json"
        self.record = self.bin / "record app"
        self.write_executable(self.record, RECORDER)
        self.env = {
            "HOME": str(self.root), "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_DATA_DIRS": str(self.root / "empty-data"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_CURRENT_DESKTOP": "niri", "LC_ALL": "C.UTF-8",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(self.root / "no-bus"),
            "PATH": os.defpath, "FIXTURE_PATH": str(self.bin),
            "FIXTURE_OUTPUT": str(self.output),
        }

    def write_executable(self, path, body):
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o700)

    def entry(self, desktop_id="org.dotfiles.Fixture.desktop", *, command=None, **keys):
        values = {"Type": "Application", "Name": "Fixture 中文 app", "Icon": "fixture-icon",
                  "Exec": command or quote_exec(str(self.record)), **keys}
        keyfile = GLib.KeyFile()
        for key, value in values.items():
            keyfile.set_string("Desktop Entry", key, value)
        destination = self.apps / desktop_id
        destination.write_text(keyfile.to_data()[0])
        return destination

    def launch(self, desktop_id="org.dotfiles.Fixture.desktop"):
        result = subprocess.run([sys.executable, "-c", RUNNER, str(BACKEND), desktop_id],
                                env=self.env, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def recording(self):
        deadline = time.monotonic() + 3
        while not self.output.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.output.exists(), "fixture did not finish")
        return json.loads(self.output.read_text())

    def test_quotes_fields_and_working_directory_use_desktop_entry_semantics(self):
        literals = ["two words", "中文路径", "$HOME;$(touch never)", 'quote"back\\slash', "`echo never`"]
        command = " ".join([quote_exec(str(self.record)), *(quote_exec(x) for x in literals),
                            "%F", "%U", "%c", "%i", "%k", "%%"])
        desktop = self.entry(command=command, Path=str(self.root))
        result = self.launch()
        self.assertIsNone(result["error"])
        record = self.recording()
        self.assertEqual(record["args"], literals + ["Fixture 中文 app", "--icon", "fixture-icon", str(desktop), "%"])
        self.assertEqual(record["cwd"], str(self.root))
        self.assertFalse((self.root / "never").exists())

    def test_terminal_uses_kitty_and_restores_context_and_child_path(self):
        self.write_executable(self.bin / "kitty", RECORDER)
        self.entry(command=quote_exec(str(self.record)) + ' "note with spaces.md" %F', Terminal="true")
        result = self.launch()
        self.assertIsNone(result["error"])
        self.assertEqual(result["path"], str(self.bin))
        record = self.recording()
        self.assertEqual(record["args"], ["--", str(self.record), "note with spaces.md"])
        self.assertEqual(record["path"], str(self.bin))

    def test_terminal_reports_missing_kitty_before_launch(self):
        self.entry(Terminal="true")
        self.assertIn("Kitty", self.launch()["error"])
        self.assertFalse(self.output.exists())

    def test_rejects_missing_hidden_and_raw_path_entries(self):
        desktop = self.entry(NoDisplay="true")
        for desktop_id in (desktop.name, str(desktop), "not-installed.desktop", "sh -c echo bad"):
            with self.subTest(desktop_id=desktop_id):
                self.assertIsNotNone(self.launch(desktop_id)["error"])
        self.assertFalse(self.output.exists())

    def test_reports_spawn_failure_in_callback(self):
        self.entry(Path=str(self.root / "nonexistent-working-directory"))
        self.assertIsNotNone(self.launch()["error"])
        self.assertFalse(self.output.exists())

    def test_application_survives_launcher_process_exit(self):
        self.entry()
        gate = self.root / "launcher-exited"
        self.env["FIXTURE_GATE"] = str(gate)
        self.assertIsNone(self.launch()["error"])
        # The runner has exited while the detached fixture is still doing work.
        self.assertFalse(self.output.exists())
        gate.touch()
        self.assertEqual(self.recording()["args"], [])


if __name__ == "__main__":
    unittest.main()
