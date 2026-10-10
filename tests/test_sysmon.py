"""Exercise monitor launch boundaries without requiring desktop apps or hardware."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    import pty
except ImportError:
    pty = None


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "config/sysmon/sysmon"

# A real child process reports the arguments and filesystem it receives. It then
# behaves like apps that write their config on exit, to exercise the isolation.
FAKE_TOOL = '''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
record = {"argv": sys.argv[1:], "config_home": os.environ.get("XDG_CONFIG_HOME"),
          "state_home": os.environ.get("XDG_STATE_HOME")}
if name == "btop-view":
    config = pathlib.Path(sys.argv[sys.argv.index("--config") + 1])
    record["config"] = str(config)
    record["contents"] = config.read_text()
    config.write_text("written by btop on exit\\n")
    own = pathlib.Path(os.environ["XDG_CONFIG_HOME"]) / "btop/themes"
    own.mkdir(parents=True, exist_ok=True)
    (own / "private.theme").write_text("private app state\\n")
elif name == "nvtop":
    config = pathlib.Path(sys.argv[sys.argv.index("--config-file") + 1])
    record["config"] = str(config)
    config.write_text("written by nvtop on exit\\n")
pathlib.Path(os.environ["SYSMON_TEST_RECORD"]).write_text(json.dumps(record))
sys.exit(int(os.environ.get("SYSMON_TEST_EXIT", "0")))
'''


class SysmonLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sysmon tests 中文-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.config = self.home / "config"
        self.state = self.home / "state"
        self.tools = self.root / "tools"
        self.shared = self.root / "repository-config"
        self.record = self.root / "record.json"
        self.tools.mkdir()
        self.shared.mkdir()
        self.config.mkdir(parents=True)
        self.state.mkdir()
        (self.config / "kitty").mkdir()
        (self.config / "kitty/theme.conf").write_text("background #19151c\n")
        # A deployment uses symlinks to shared read-only starting files.
        shutil.copytree(ROOT / "config/sysmon", self.shared / "sysmon")
        themes = self.shared / "sysmon/themes"
        shutil.copyfile(ROOT / "config/moonlit/btop.theme", themes / "moonlit-bloom.theme")
        monitor = self.config / "sysmon"
        (monitor / "themes").mkdir(parents=True)
        (monitor / "btop.conf").symlink_to(self.shared / "sysmon/btop.conf")
        for theme in themes.glob("*.theme"):
            (monitor / "themes" / theme.name).symlink_to(theme)
        (self.config / "btop").mkdir()
        self.personal = self.config / "btop/btop.conf"
        self.personal.write_text("personal btop settings\n")
        self.template = self.shared / "sysmon/btop.conf"
        self.original_template = self.template.read_bytes()
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.config),
                        XDG_STATE_HOME=str(self.state), PATH=str(self.tools),
                        SYSMON_TEST_RECORD=str(self.record))

    def tool(self, name, directory=None):
        destination = (self.tools if directory is None else directory) / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"#!{sys.executable}\n" + FAKE_TOOL)
        destination.chmod(0o755)
        return destination

    def run_monitor(self, *arguments, terminal=True):
        command = [sys.executable, str(LAUNCHER), *arguments]
        if not terminal:
            return subprocess.run(command, env=self.env, capture_output=True,
                                  text=True, timeout=10)
        if pty is None:
            self.skipTest("A PTY is required for interactive terminal boundary checks")
        master, slave = pty.openpty()
        try:
            return subprocess.run(command, env=self.env, stdin=slave, stdout=slave,
                                  stderr=subprocess.PIPE, text=True, timeout=10)
        finally:
            os.close(slave)
            os.close(master)

    def launched(self):
        return json.loads(self.record.read_text())

    def assert_shared_untouched(self):
        self.assertEqual(self.personal.read_text(), "personal btop settings\n")
        self.assertEqual(self.template.read_bytes(), self.original_template)
        self.assertFalse((self.shared / "sysmon/themes/private.theme").exists())
        self.assertFalse((self.config / "btop/themes").exists())

    def test_btop_writes_are_isolated_per_invocation_and_cleaned_up(self):
        self.tool("btop-view")
        paths = []
        for view in ("all", "io"):
            result = self.run_monitor(view)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = self.launched()
            config = Path(record["config"])
            paths.append(config.parent)
            self.assertEqual(record["config_home"], str(config.parent))
            self.assertNotEqual(config.parent, self.config)
            self.assertFalse(config.parent.is_relative_to(self.shared))
            self.assertFalse(config.exists(), "The temporary app config must be removed after exit")
            self.assertEqual("io_mode = true" in record["contents"], view == "io")
            self.assert_shared_untouched()
        self.assertNotEqual(*paths, "Separate launches must never share a writable app config")

    def test_filter_is_one_literal_argument_without_shell_expansion(self):
        self.tool("btop-view")
        marker = self.root / "shell-expanded"
        literal = f'python; touch "{marker}" $(touch "{marker}") $HOME `touch "{marker}"'
        result = self.run_monitor("--filter", literal, "--interval", "750")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = self.launched()["argv"]
        self.assertEqual(argv[argv.index("--filter") + 1], literal)
        self.assertEqual(argv[argv.index("--update") + 1], "750")
        self.assertFalse(marker.exists())
        self.assert_shared_untouched()

    def test_process_collection_is_opt_in_with_three_second_default(self):
        self.tool("btop-view")
        for arguments, processes, network in (
            ((), False, True),
            (("proc",), True, False),
            (("all",), True, True),
            (("--filter", "python"), True, False),
            (("io", "--filter", "python"), True, False),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_monitor(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                record = self.launched()
                boxes = re.search(r'^shown_boxes = "([^"]+)"$', record["contents"], re.MULTILINE).group(1).split()
                self.assertEqual("proc" in boxes, processes, "The native collector runs only for visible panels")
                self.assertEqual("net" in boxes, network)
                self.assertTrue({"cpu", "gpu0", "mem"}.issubset(boxes))
                self.assertEqual(record["argv"][record["argv"].index("--update") + 1], "3000")
                self.assertEqual("io_mode = true" in record["contents"], "io" in arguments)
                self.assert_shared_untouched()

    def test_window_inherits_kitty_config_and_application_id(self):
        self.tool("kitty")
        result = self.run_monitor("io", "--window", "--filter", "my program", terminal=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.launched()
        argv = record["argv"]
        self.assertEqual(record["config_home"], str(self.config))
        self.assertEqual(record["state_home"], str(self.state))
        self.assertTrue({"--config", "-c", "--class", "--name"}.isdisjoint(argv))
        overrides = [argv[index + 1].split("=", 1)[0] for index, value in enumerate(argv) if value == "--override"]
        self.assertTrue({"font_size", "background_opacity", "tab_bar_min_tabs"}.isdisjoint(overrides))
        self.assertIn(str(LAUNCHER.resolve()), argv)
        self.assertIn("io", argv)
        self.assertEqual(argv[argv.index("--filter") + 1], "my program")

    def test_auto_theme_tracks_current_kitty_palette_and_explicit_override(self):
        self.tool("btop-view")
        kitty = self.config / "kitty/theme.conf"
        for background, arguments, expected in (
            ("#19151c", (), "dark-rose"),
            ("#18131F", (), "moonlit-bloom"),
            ("#18131f", ("--theme", "rose"), "dark-rose"),
        ):
            with self.subTest(background=background, arguments=arguments):
                kitty.write_text(f"# active terminal theme\nbackground {background}\n")
                result = self.run_monitor(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                record = self.launched()
                contents = record["contents"]
                # btop scans this directory before matching color_theme. An
                # absolute resolved filename cannot match a scanned symlink.
                selected = re.search(r'^color_theme = "([^"]+)"$', contents, re.MULTILINE).group(1)
                scanned = Path(record["argv"][record["argv"].index("--themes-dir") + 1])
                matched = [path for path in scanned.glob("*.theme")
                           if selected in (str(path), path.name, path.stem)]
                self.assertEqual(len(matched), 1, "btop must find the selected theme in its scanned paths")
                self.assertEqual(matched[0].resolve(), self.shared / "sysmon/themes" / (expected + ".theme"))

    def test_gpu_private_state_goes_to_xdg_state_outside_shared_config(self):
        self.tool("nvtop")
        result = self.run_monitor("gpu")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = Path(self.launched()["config"])
        self.assertTrue(config.is_relative_to(self.state))
        self.assertFalse(config.is_relative_to(self.shared))
        self.assertEqual(config.read_text(), "written by nvtop on exit\n")
        self.assert_shared_untouched()

    def test_sensor_command_path_with_spaces_bypasses_watch_shell(self):
        self.tool("watch")
        sensors = self.tool("sensors")
        result = self.run_monitor("sensors", "--interval", "500")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = self.launched()["argv"]
        self.assertIn("--exec", argv, "watch must execute the literal command without a shell")
        self.assertEqual(argv[-2:], [str(sensors), "-A"])
        self.assertEqual(argv[argv.index("--interval") + 1], "0.5")

    def test_noninteractive_use_reports_window_alternative_without_launching(self):
        self.tool("btop-view")
        result = self.run_monitor(terminal=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("interactive terminal", result.stderr)
        self.assertIn("sysmon --window", result.stderr)
        self.assertFalse(self.record.exists())

    def test_missing_system_tool_uses_executable_user_install_then_reports_absence(self):
        local = self.home / ".local/share/dotfiles/tools/sysmon/btop-view/usr/bin"
        tool = self.tool("btop-view", directory=local)
        result = self.run_monitor()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.record.exists())
        self.record.unlink()
        tool.chmod(0o644)
        result = self.run_monitor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Menu-free monitor is missing", result.stderr)
        self.assertIn("docs/hardware-monitor.md", result.stderr)
        self.assertFalse(self.record.exists())
        self.assert_shared_untouched()


if __name__ == "__main__":
    unittest.main()
