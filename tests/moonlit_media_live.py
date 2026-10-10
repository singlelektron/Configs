#!/usr/bin/env python3
"""Opt-in real VLC/MPRIS lifecycle check in an already running private preview.

This is intentionally not an auto-discovered unit test. It never starts a desktop
session, changes the user's audio routing, or addresses the host session bus.
The generated FLAC plays through VLC's dummy audio output, not a sound device.
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
ROOM = "dotfiles/moonlit-music:room"
CONTROLS = "dotfiles/moonlit-music:controls"


def load_preview():
    spec = importlib.util.spec_from_file_location("moonlit_preview", REPO / "scripts/desktop-preview.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def rss_kib(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def timed_command(argv, env, timeout=10):
    started = time.perf_counter()
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
    elapsed = (time.perf_counter() - started) * 1000
    if result.returncode:
        raise RuntimeError(f"{argv[0]} {argv[1]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result, elapsed


def await_value(read, predicate, description, timeout=12):
    deadline = time.monotonic() + timeout
    value = None
    while time.monotonic() < deadline:
        value = read()
        if predicate(value):
            return value
        time.sleep(0.15)
    raise RuntimeError(f"Timed out waiting for {description}: {value!r}")


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {}
    return {"samples": len(ordered), "median_ms": ordered[len(ordered) // 2],
            "p95_ms": ordered[max(0, math.ceil(len(ordered) * .95) - 1)], "max_ms": ordered[-1]}


class PrivateMpris:
    def __init__(self, address):
        import gi
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.connection = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)

    def call(self, destination, path, interface, method, signature=None, values=()):
        parameters = self.GLib.Variant(signature, values) if signature else None
        return self.connection.call_sync(destination, path, interface, method, parameters,
            None, self.Gio.DBusCallFlags.NONE, 1500, None).unpack()

    def owner_pid(self, bus):
        return self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                         "GetConnectionUnixProcessID", "(s)", (bus,))[0]

    def players(self):
        names = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames")[0]
        return [name for name in names if name.startswith("org.mpris.MediaPlayer2.")]

    def snapshot(self, bus):
        p = self.call(bus, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll",
                      "(s)", ("org.mpris.MediaPlayer2.Player",))[0]
        return {"status": p.get("PlaybackStatus"), "position_seconds": p.get("Position", 0) / 1e6,
                "can_seek": p.get("CanSeek", False), "metadata": p.get("Metadata", {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, default=Path(f"/tmp/moonlit-preview-{os.getuid()}/session.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--closed-seconds", type=float, default=6)
    parser.add_argument("--keep-player", action="store_true", help="Leave only the task-owned dummy-output VLC alive for screenshots")
    args = parser.parse_args()
    if not 1 <= args.cycles <= 100 or not 2 <= args.closed_seconds <= 30:
        parser.error("cycles must be 1–100 and closed-seconds 2–30")
    preview = load_preview()
    root = preview.safe_root(args.session.expanduser().absolute().parent)
    if args.session.name != "session.json":
        parser.error("--session must name the preview's session.json")
    env = preview.nested_environment(root)
    session = json.loads(args.session.read_text())
    private_address = session.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not private_address or private_address == os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("Refusing a missing or host session bus address")
    if env.get("MOONLIT_PREVIEW") != "1" or env.get("DBUS_SESSION_BUS_ADDRESS") != private_address:
        raise RuntimeError("Preview environment isolation check failed")
    shell_identity = preview.state(root).get("shell")
    if not preview.alive(shell_identity):
        raise RuntimeError("Protected preview shell is not running")
    output = args.output.expanduser().absolute() if args.output else root / "media-lifecycle.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    artifacts = root / "media-validation"
    artifacts.mkdir(exist_ok=True)
    bridge = root / "data/noctalia/plugins/moonlit-music/media_bridge.py"
    if not bridge.is_file():
        raise RuntimeError("Prepared preview does not contain the music bridge")
    bus = PrivateMpris(private_address)
    report = {"kind": "real local VLC decode and MPRIS control on private preview bus",
              "completed": False, "audio_output": "dummy: no physical sound device",
              "track": {"title": "Local playback test", "artist": "Generated validation tone",
                        "source": "ffmpeg lavfi sine at 220 Hz, attenuated by 40 dB", "artwork": "none"},
              "timing_scope": "IPC subprocess acknowledgement latency only; not visible-content latency or frame time",
              "frame_time_measured": False, "physical_audio_routing_tested": False,
              "cycles": [], "assertions": {}, "shell_pid": shell_identity["pid"],
              "wall_clock_started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    process = None
    identity = None
    success = False

    def snapshot():
        result, _ = timed_command([sys.executable, str(bridge), "snapshot"], env)
        return json.loads(result.stdout)

    def action(name, argument=None):
        argv = [sys.executable, str(bridge), name]
        if argument is not None:
            argv.append(str(argument))
        result, elapsed = timed_command(argv, env)
        data = json.loads(result.stdout)
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data, elapsed

    def panel(action_name, panel_id):
        _, elapsed = timed_command([str(root / "bin/noctalia"), "msg", action_name, panel_id], env)
        return elapsed

    try:
        before = snapshot()
        report["initial_private_players"] = before.get("players", [])
        track = artifacts / "local-playback-test.flac"
        timed_command(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100", "-t", "600",
            "-af", "volume=-40dB", "-c:a", "flac", "-metadata", "title=Local playback test",
            "-metadata", "artist=Generated validation tone", "-metadata", "album=Desktop lifecycle validation",
            str(track)], env, timeout=45)
        vlc_argv = ["vlc", "--ignore-config", "--intf", "dummy", "--extraintf", "dbus", "--aout", "dummy",
                    "--no-video", "--no-one-instance", "--no-media-library", "--no-osd", "--loop", str(track)]
        with (artifacts / "vlc.log").open("w") as log:
            process = subprocess.Popen(vlc_argv, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, start_new_session=True)
        identity = preview.proc_identity(process.pid)
        if not identity:
            raise RuntimeError("Could not record task-owned VLC process identity")
        atomic_json(artifacts / "player.json", {**identity, "argv": vlc_argv, "session": str(args.session)})
        owned_bus = await_value(lambda: [name for name in bus.players() if bus.owner_pid(name) == process.pid],
                                bool, "task-owned VLC MPRIS registration")[0]
        report["player"] = {**identity, "bus": owned_bus, "argv": vlc_argv}
        selected = await_value(snapshot, lambda p: any(x["bus"] == owned_bus for x in p.get("players", [])),
                               "Noctalia discovering VLC")
        report["assertions"]["noctalia_auto_selected_vlc"] = selected.get("player") == owned_bus
        action("select", owned_bus)
        current = await_value(snapshot, lambda p: p.get("player") == owned_bus and p.get("status") == "Playing",
                              "selected VLC playback")
        if current.get("title") != "Local playback test" or current.get("artist") != "Generated validation tone":
            raise RuntimeError("Unexpected player metadata; refusing to control another track")
        report["assertions"]["real_test_metadata"] = True
        report["initial_playing_snapshot"] = current
        direct = bus.snapshot(owned_bus)
        report["assertions"]["direct_mpris_confirms_playing"] = direct["status"] == "Playing"

        action("toggle")
        await_value(lambda: bus.snapshot(owned_bus), lambda p: p["status"] == "Paused", "real pause")
        paused_before = bus.snapshot(owned_bus)["position_seconds"]
        time.sleep(1.3)
        paused_after = bus.snapshot(owned_bus)["position_seconds"]
        report["assertions"]["pause_holds_position"] = abs(paused_after - paused_before) < .35
        action("toggle")
        await_value(lambda: bus.snapshot(owned_bus), lambda p: p["status"] == "Playing", "real resume")
        if current.get("can_seek"):
            action("seek", 30)
            seek = await_value(lambda: bus.snapshot(owned_bus), lambda p: 29 <= p["position_seconds"] <= 34,
                               "real seek to 30 seconds", timeout=4)
            report["seek"] = {"supported": True, "observed_seconds": seek["position_seconds"]}
        else:
            report["seek"] = {"supported": False, "reason": "Player advertised CanSeek=false"}

        panel("panel-close", ROOM)
        panel("panel-close", CONTROLS)
        closed_before = bus.snapshot(owned_bus)
        time.sleep(args.closed_seconds)
        closed_after = bus.snapshot(owned_bus)
        delta = closed_after["position_seconds"] - closed_before["position_seconds"]
        report["closed_ui_playback"] = {"observation_seconds": args.closed_seconds, "position_delta_seconds": delta,
                                         "before": closed_before["status"], "after": closed_after["status"]}
        report["assertions"]["playback_continues_with_ui_closed"] = (
            closed_after["status"] == "Playing" and delta >= args.closed_seconds * .7)
        report["rss_before_cycles_kib"] = {"shell": rss_kib(shell_identity["pid"]), "vlc": rss_kib(process.pid)}
        start_position = bus.snapshot(owned_bus)["position_seconds"]
        for cycle in range(args.cycles):
            opened_ms = panel("panel-open", ROOM)
            time.sleep(.20)
            closed_ms = panel("panel-close", ROOM)
            time.sleep(.20)
            item = {"cycle": cycle + 1, "open_ack_ms": opened_ms, "close_ack_ms": closed_ms,
                    "shell_rss_kib": rss_kib(shell_identity["pid"])}
            if cycle % 5 == 0 or cycle + 1 == args.cycles:
                observation = bus.snapshot(owned_bus)
                item.update(status=observation["status"], position_seconds=observation["position_seconds"])
            report["cycles"].append(item)
        time.sleep(2)
        final = bus.snapshot(owned_bus)
        report["rss_after_cycles_kib"] = {"shell": rss_kib(shell_identity["pid"]), "vlc": rss_kib(process.pid)}
        report["rss_shell_delta_kib"] = (report["rss_after_cycles_kib"]["shell"] or 0) - (report["rss_before_cycles_kib"]["shell"] or 0)
        report["ack_latency"] = {"open": distribution([x["open_ack_ms"] for x in report["cycles"]]),
                                  "close": distribution([x["close_ack_ms"] for x in report["cycles"]])}
        report["assertions"]["playback_survives_twenty_or_requested_cycles"] = (
            final["status"] == "Playing" and final["position_seconds"] > start_position)
        report["assertions"]["original_player_process_alive"] = preview.alive(identity)
        report["assertions"]["original_shell_process_alive"] = preview.alive(shell_identity)
        report["final_snapshot"] = snapshot()
        success = all(report["assertions"].values())
        report["completed"] = True
        report["passed"] = success
    except Exception as error:
        report["error"] = str(error)
        report["passed"] = False
    finally:
        if identity and preview.alive(identity):
            if args.keep_player and success:
                report["kept_player"] = identity
            else:
                preview.signal_owned(identity, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    preview.signal_owned(identity, signal.SIGKILL)
                    process.wait(timeout=2)
                report["kept_player"] = None
        atomic_json(output, report)
    print(json.dumps({"report": str(output), "passed": report.get("passed", False),
                      "player": report.get("kept_player"), "error": report.get("error")}, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
