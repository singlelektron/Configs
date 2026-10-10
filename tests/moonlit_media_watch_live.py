#!/usr/bin/env python3
"""Opt-in private-DBus stream/lifecycle smoke; no desktop, real player or hardware.

Run this script directly. It creates a new dbus-run-session and synthetic native
Noctalia service, and never connects to the caller's session bus.
"""
import argparse
from collections import deque
import json
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time

PLUGIN = Path(__file__).resolve().parents[1] / "config/moonlit/plugins/moonlit-music"
NAME = "dev.noctalia.Mpris"
BUS = "org.mpris.MediaPlayer2.MoonlitWatchFixture"


def fixture():
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)

    class Native(dbus.service.Object):
        def __init__(self):
            self.session_bus = dbus.SessionBus()
            self.name = dbus.service.BusName(NAME, self.session_bus)
            super().__init__(self.name, "/dev/noctalia/Mpris")
            self.playing = False
            self.base = 12.0
            self.at = time.monotonic()
            self.pin = ""
            self.counts = {"players": 0, "preferences": 0, "active": 0, "position": 0}

        def position(self):
            return int((self.base + (time.monotonic() - self.at if self.playing else 0)) * 1e6)

        def player(self):
            return {"bus_name": BUS, "identity": "Synthetic native service", "title": "Event lifecycle fixture",
                    "artists": dbus.Array(["No audio engine"], signature="s"), "album": "Validation",
                    "playback_status": "Playing" if self.playing else "Paused", "position_us": dbus.Int64(self.position()),
                    "length_us": dbus.Int64(600000000), "can_play": True, "can_pause": True,
                    "can_seek": True, "can_go_next": False, "can_go_previous": False, "art_url": ""}

        @dbus.service.method(NAME, out_signature="aa{sv}")
        def GetPlayers(self):
            self.counts["players"] += 1
            return [self.player()]

        @dbus.service.method(NAME, out_signature="bsas")
        def GetPlayerPreferences(self):
            self.counts["preferences"] += 1
            return bool(self.pin), self.pin, []

        @dbus.service.method(NAME, out_signature="ba{sv}")
        def GetActivePlayer(self):
            self.counts["active"] += 1
            return True, self.player()

        @dbus.service.method(NAME, in_signature="s", out_signature="x")
        def GetPositionPlayer(self, _bus):
            self.counts["position"] += 1
            return dbus.Int64(self.position())

        @dbus.service.method(NAME, in_signature="as", out_signature="b")
        def SetPreferredPlayers(self, _names):
            return True

        @dbus.service.method(NAME, in_signature="s", out_signature="b")
        def SetActivePlayerPreference(self, bus):
            self.pin = bus
            self.ActivePlayerChanged(True, self.player())
            return True

        @dbus.service.signal(NAME, signature="aa{sv}")
        def PlayersChanged(self, players):
            pass

        @dbus.service.signal(NAME, signature="ba{sv}")
        def ActivePlayerChanged(self, found, player):
            pass

        @dbus.service.method("test.Moonlit", in_signature="bd", out_signature="b")
        def SetFixture(self, playing, position):
            self.playing, self.base, self.at = bool(playing), position, time.monotonic()
            self.PlayersChanged([self.player()])
            return True

        @dbus.service.method("test.Moonlit", out_signature="s")
        def Counts(self):
            return json.dumps(self.counts)

    native = Native()
    GLib.MainLoop().run()


class Reader:
    def __init__(self, process):
        self.process = process
        self.buffer = b""
        self.pending = deque()
        self.all = []

    def next(self, timeout=5):
        deadline = time.monotonic() + timeout
        while not self.pending and time.monotonic() < deadline:
            if not select.select([self.process.stdout], [], [], max(0, deadline-time.monotonic()))[0]:
                break
            block = os.read(self.process.stdout.fileno(), 65536)
            if not block:
                raise RuntimeError("watcher stdout closed unexpectedly")
            self.buffer += block
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if line:
                    self.pending.append(json.loads(line))
        if not self.pending:
            raise TimeoutError("No stream message")
        result = self.pending.popleft()
        self.all.append(result)
        return result

    def until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.next(max(.01, deadline-time.monotonic()))
            if predicate(result):
                return result
        raise TimeoutError("Stream condition not reached")


def stream_command(control):
    return (shlex.join([sys.executable, "-u", str(PLUGIN / "media_watch.py"), "--control-file", str(control)])
            + ' --owner-pid "$PPID"; ' + shlex.join(["printf", "%s\\n", '{"_bridge_exit":true}']))


def child_pid(pid):
    path = Path(f"/proc/{pid}/task/{pid}/children")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = path.read_text().strip()
        if value:
            return int(value.split()[0])
        time.sleep(.01)
    raise TimeoutError("Stream shell did not spawn its worker")


def dead_process(pid):
    try:
        content = Path(f"/proc/{pid}/stat").read_text()
        return content[content.rfind(")")+2:].split()[0] == "Z"
    except FileNotFoundError:
        return True


def run_child(root):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    control = root / "media-control.json"
    revision = 0
    env = dict(os.environ, XDG_STATE_HOME=str(root / "state"), PYTHONDONTWRITEBYTECODE="1", GIO_USE_VFS="local")
    owned = []
    output = {"kind": "synthetic private-DBus event/lifecycle test", "assertions": {}, "measurements": {}}

    def command(method, signature=None, values=(), interface="test.Moonlit"):
        parameters = GLib.Variant(signature, values) if signature else None
        return bus.call_sync(NAME, "/dev/noctalia/Mpris", interface, method, parameters, None,
                             Gio.DBusCallFlags.NONE, 1500, None).unpack()

    def counts():
        return json.loads(command("Counts")[0])

    def set_control(visible, refresh=False):
        nonlocal revision
        revision += 1
        temporary = control.with_suffix(".tmp")
        temporary.write_text(json.dumps({"instance": "smoke", "revision": revision, "visible": visible, "refresh": refresh}))
        temporary.replace(control)

    def start_native():
        with (root / "native.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, __file__, "--fixture"], env=env, stdout=log, stderr=log)
        owned.append(process)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                counts()
                return process
            except Exception:
                if process.poll() is not None:
                    raise RuntimeError((root / "native.log").read_text())
                time.sleep(.05)
        raise TimeoutError("Synthetic native service did not start")

    def start_watch():
        with (root / "watch.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, "-u", str(PLUGIN / "media_watch.py"), "--control-file", str(control)],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log)
        owned.append(process)
        return process, Reader(process)

    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    try:
        set_control(False, True)
        worker, reader = start_watch()
        reader.until(lambda value: bool(value.get("error")))
        native = start_native()
        reader.until(lambda value: value.get("player") == BUS and not value.get("error"))
        output["assertions"]["service_appearance_recovers_without_restart"] = True
        time.sleep(.15)
        before = counts()
        time.sleep(2.2)
        output["assertions"]["hidden_paused_makes_zero_calls"] = counts() == before
        command("SetFixture", "(bd)", (True, 20.0))
        reader.until(lambda value: value.get("status") == "Playing")
        time.sleep(.15)
        before = counts()
        time.sleep(2.2)
        output["assertions"]["hidden_playing_makes_zero_calls"] = counts() == before
        set_control(True)
        reader.until(lambda value: value.get("position", 0) > 21)
        time.sleep(.1)
        before = counts()
        time.sleep(2.2)
        after = counts()
        output["measurements"]["visible_playing_call_delta"] = {key: after[key]-before[key] for key in before}
        output["assertions"]["visible_playing_only_queries_position"] = after["position"]-before["position"] >= 2 and all(after[key] == before[key] for key in ("players", "preferences", "active"))
        set_control(False)
        time.sleep(.1)
        before = counts()
        time.sleep(1.2)
        output["assertions"]["closing_stops_position_queries"] = counts() == before
        command("SetFixture", "(bd)", (False, 30.0))
        reader.until(lambda value: value.get("status") == "Paused")
        set_control(True)
        time.sleep(.15)
        before = counts()
        time.sleep(1.2)
        output["assertions"]["visible_paused_has_no_position_timer"] = counts() == before
        stop(native)
        reader.until(lambda value: "unavailable" in value.get("error", ""))
        native = start_native()
        reader.until(lambda value: value.get("player") == BUS and not value.get("error"))
        output["assertions"]["service_loss_and_return_recovers_same_worker"] = worker.poll() is None
        worker.stdout.close()
        worker.wait(timeout=3)
        output["assertions"]["stdout_reader_loss_exits_worker"] = worker.returncode == 0

        # Graceful stream replacement must release its lock and leave no worker.
        for _ in range(3):
            replacement, replacement_reader = start_watch()
            replacement_reader.until(lambda value: value.get("player") == BUS)
            stop(replacement)
        output["assertions"]["three_reload_equivalents_leave_no_workers"] = all(p.poll() is not None for p in owned if p is not native)

        # The actual shell wrapper supplies the exit notification API32 lacks.
        with (root / "watch.log").open("ab") as log:
            wrapper = subprocess.Popen(["/bin/sh", "-c", stream_command(control)], env=env,
                                       stdout=subprocess.PIPE, stderr=log)
        owned.append(wrapper)
        wrapped_reader = Reader(wrapper)
        wrapped_reader.until(lambda value: value.get("player") == BUS)
        os.kill(child_pid(wrapper.pid), signal.SIGKILL)
        wrapped_reader.until(lambda value: value.get("_bridge_exit") is True)
        wrapper.wait(timeout=3)
        output["assertions"]["worker_sigkill_emits_exit_record_without_poll"] = True

        set_control(False, True)
        with (root / "owner.log").open("ab") as log:
            owner = subprocess.Popen([sys.executable, __file__, "--owner", str(control)], env=env,
                                     stdout=subprocess.PIPE, stderr=log)
        owned.append(owner)
        owner_reader = Reader(owner)
        owner_reader.until(lambda value: value.get("player") == BUS)
        wrapper_pid = int((root / "owner-child.pid").read_text())
        worker_pid = child_pid(wrapper_pid)
        owner.kill()
        owner.wait(timeout=2)
        deadline = time.monotonic() + 3
        dead = False
        while time.monotonic() < deadline:
            dead = dead_process(wrapper_pid) and dead_process(worker_pid)
            if dead:
                break
            time.sleep(.05)
        output["assertions"]["sigkill_owner_leaves_no_live_wrapper_or_worker"] = dead
        output["passed"] = all(output["assertions"].values())
    except Exception as error:
        output["error"] = str(error)
        output["passed"] = False
    finally:
        for process in reversed(owned):
            stop(process)
        (root / "report.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
    return 0 if output["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--owner", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.fixture:
        fixture()
        return 0
    if args.owner:
        process = subprocess.Popen(["/bin/sh", "-c", stream_command(args.owner)])
        (args.owner.parent / "owner-child.pid").write_text(str(process.pid))
        return process.wait()
    if args.child:
        return run_child(args.child)
    with tempfile.TemporaryDirectory(prefix="moonlit-watch-smoke-") as directory:
        root = Path(directory)
        config = root / "dbus.conf"
        config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen>'
                          '<auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/>'
                          '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
        result = subprocess.run(["dbus-run-session", "--config-file", str(config), "--", sys.executable,
                                 __file__, "--child", str(root)], check=False)
        if args.output and (root / "report.json").exists():
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes((root / "report.json").read_bytes())
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
