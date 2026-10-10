#!/usr/bin/env python3
"""Opt-in native Noctalia source-selection regression on a private preview bus.

The old PR's controlled MPRIS fixture is extracted at run time, then instantiated
as clearly labelled synthetic peers. No audio is generated and no GUI opens.
Only task-owned fixture PIDs are stopped. The retained real VLC is restored.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from moonlit_media_live import PrivateMpris, atomic_json, await_value, load_preview, timed_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, default=Path(f"/tmp/moonlit-preview-{os.getuid()}/session.json"))
    parser.add_argument("--legacy-repo", type=Path, default=Path.home() / "GIT_repository/Configs")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    preview = load_preview()
    root = preview.safe_root(args.session.expanduser().absolute().parent)
    if args.session.name != "session.json":
        parser.error("--session must name session.json")
    env = preview.nested_environment(root)
    address = env.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not address or address == os.environ.get("DBUS_SESSION_BUS_ADDRESS") or env.get("MOONLIT_PREVIEW") != "1":
        raise RuntimeError("Refusing missing/private-bus isolation")
    shell = preview.state(root).get("shell")
    if not preview.alive(shell):
        raise RuntimeError("Private preview shell is not alive")
    bus = PrivateMpris(address)
    bridge = root / "data/noctalia/plugins/moonlit-music/media_bridge.py"
    selection = Path(env["XDG_STATE_HOME"]) / "moonlit/media-selection.json"
    output = args.output.expanduser().absolute() if args.output else root / "media-selection-live.json"
    directory = root / "media-selection-validation"
    directory.mkdir(exist_ok=True)
    log = directory / "transport.jsonl"
    log.write_text("")
    processes = []
    report = {"kind": "native Noctalia selection/transport against synthetic MPRIS peers",
              "synthetic": True, "real_audio_or_account_validation": False,
              "passed": False, "assertions": {}, "observations": [], "fixture_processes": [],
              "panels_opened": False, "host_hardware_changed": False}

    def bridge_call(action="snapshot", value=None, expect_error=False):
        argv = [sys.executable, str(bridge), action]
        if value is not None:
            argv.append(str(value))
        result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=8)
        data = json.loads(result.stdout)
        if expect_error:
            return result.returncode, data
        if result.returncode or data.get("error"):
            raise RuntimeError(data.get("error") or result.stderr)
        return data

    def native(method, signature=None, values=()):
        result = bus.call("dev.noctalia.Mpris", "/dev/noctalia/Mpris", "dev.noctalia.Mpris", method, signature, values)
        if not result or result[0] is not True:
            raise RuntimeError(f"Native {method} returned failure")

    def selected(expected):
        return await_value(bridge_call, lambda p: p["player"] == expected, "active source " + expected, timeout=6)

    def remember(name, data):
        report["observations"].append({"test": name, "selected": data["player"], "status": data["status"],
                                       "saved_choice": json.loads(selection.read_text()) if selection.exists() else {}})

    def stop(entry):
        process, identity = entry
        if preview.alive(identity):
            preview.signal_owned(identity, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                preview.signal_owned(identity, signal.SIGKILL)
                process.wait(timeout=2)

    original = bridge_call()
    vlc = original.get("player", "")
    lifecycle = json.loads((root / "media-lifecycle.json").read_text())
    vlc_identity = lifecycle["player"]
    if vlc != vlc_identity["bus"] or "vlc" not in vlc.lower() or bus.owner_pid(vlc) != vlc_identity["pid"]:
        raise RuntimeError("Expected retained task-owned VLC as original source")
    if not preview.alive(vlc_identity):
        raise RuntimeError("Retained task-owned VLC is not alive")
    report["original_vlc"] = {"bus": vlc, "pid": vlc_identity["pid"], "status": original["status"]}

    try:
        revision = subprocess.check_output(["git", "-C", str(args.legacy_repo), "rev-parse", "codex/desktop-island-music"], text=True).strip()
        source = subprocess.check_output(["git", "-C", str(args.legacy_repo), "show",
            revision + ":config/quickshell/tests/mock_mpris.py"], text=True)
        if source.count("\nplayers = [") != 1:
            raise RuntimeError("Unexpected legacy fixture layout")
        source = source.split("\nplayers = [", 1)[0]
        source = source.replace("'<b>春 & music</b>'", "'Synthetic source-selection fixture'")
        source = source.replace("dbus.Array(['Artist'], signature='s')", "dbus.Array(['Test fixture - no audio engine'], signature='s')")
        source += "\nplayer = Player(sys.argv[2], sys.argv[3] == 'playing')\nplayer.props['CanSeek'] = False\nGLib.MainLoop().run()\n"
        fixture = directory / "mock_mpris.py"
        fixture.write_text(source)
        report["fixture_origin"] = {"revision": revision, "path": "config/quickshell/tests/mock_mpris.py",
                                    "adaptations": "one peer per owned PID, explicit synthetic metadata, CanSeek=false"}
        peers = {}
        for name, status in (("NeteaseCloudMusicGtk4.MoonlitTest", "paused"),
                             ("firefox.MoonlitTest", "playing"), ("MoonlitNativeFixture", "paused")):
            with (directory / (name + ".log")).open("w") as stream:
                process = subprocess.Popen([sys.executable, str(fixture), str(log), name, status],
                    env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, start_new_session=True)
            identity = preview.proc_identity(process.pid)
            if not identity:
                raise RuntimeError("Could not record owned fixture identity")
            entry = (process, identity)
            processes.append(entry)
            full_name = "org.mpris.MediaPlayer2." + name
            await_value(bus.players, lambda names: full_name in names, "fixture registration")
            if bus.owner_pid(full_name) != process.pid:
                raise RuntimeError("Fixture bus owner PID does not match")
            peers[name] = (full_name, entry)
            report["fixture_processes"].append({**identity, "bus": full_name, "role": status})
        netease, _ = peers["NeteaseCloudMusicGtk4.MoonlitTest"]
        browser, _ = peers["firefox.MoonlitTest"]
        native_choice, native_entry = peers["MoonlitNativeFixture"]
        await_value(bridge_call, lambda p: len(p["players"]) >= 4, "all peers discovered")

        # Reset only the disposable private preview's existing VLC pin.
        native("ClearActivePlayerPreference")
        selection.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(selection, {})
        native("ClearActivePlayerPreference")
        chosen = selected(netease)
        time.sleep(2.2)
        stable = bridge_call()
        report["assertions"]["paused_netease_beats_playing_browser"] = stable["player"] == netease and stable["status"] == "Paused"
        remember("automatic paused NetEase preference", stable)
        bridge_call("next")
        events = [json.loads(line) for line in log.read_text().splitlines()]
        report["assertions"]["transport_targets_selected_netease"] = bool(events and events[-1]["player"].startswith("Netease") and events[-1]["action"] == "Next")
        code, failed = bridge_call("seek", 10, expect_error=True)
        report["unsupported_seek"] = {"exit_code": code, "error": failed.get("error")}
        events_after = [json.loads(line) for line in log.read_text().splitlines()]
        report["assertions"]["unsupported_seek_is_error_without_transport"] = code != 0 and bool(failed.get("error")) and len(events_after) == len(events)

        bridge_call("select", browser)
        time.sleep(2.2)
        chosen = selected(browser)
        report["assertions"]["explicit_browser_selection_beats_netease"] = chosen["player"] == browser
        remember("custom explicit browser selection", chosen)
        native("SetActivePlayerPreference", "(s)", (native_choice,))
        chosen = selected(native_choice)
        saved = json.loads(selection.read_text())
        report["assertions"]["new_native_pin_replaces_old_custom_choice"] = saved.get("explicit") == native_choice
        remember("new native pin replaces custom browser choice", chosen)
        stop(native_entry)
        chosen = selected(netease)
        report["assertions"]["removed_native_pin_does_not_resurrect_old_browser_choice"] = chosen["player"] == netease
        remember("removed native source falls back to preferred NetEase", chosen)
        stop(peers["NeteaseCloudMusicGtk4.MoonlitTest"][1])
        chosen = selected(browser)
        report["assertions"]["removed_preferred_source_falls_back_to_playing_browser"] = chosen["player"] == browser
        remember("removed NetEase falls back to playing browser", chosen)
        report["transport_log"] = [json.loads(line) for line in log.read_text().splitlines()]
        report["passed"] = all(report["assertions"].values())
    except Exception as error:
        report["error"] = str(error)
    finally:
        for entry in reversed(processes):
            stop(entry)
        report["assertions"]["all_owned_fixtures_stopped"] = all(not preview.alive(identity) for _, identity in processes)
        try:
            fixture_buses = {entry["bus"] for entry in report["fixture_processes"]}
            await_value(bridge_call, lambda p: not any(x["bus"] in fixture_buses for x in p["players"]), "fixtures removed")
            restored = bridge_call("select", vlc)
            if restored["status"] == "Playing":
                bridge_call("toggle")
            restored = selected(vlc)
            report["restored_vlc"] = {"bus": restored["player"], "status": restored["status"], "pid": vlc_identity["pid"]}
            report["assertions"]["vlc_restored_selected_paused"] = restored["player"] == vlc and restored["status"] == "Paused"
        except Exception as error:
            report["restore_error"] = str(error)
            report["passed"] = False
        report["assertions"]["original_shell_alive"] = preview.alive(shell)
        report["passed"] = report["passed"] and all(report["assertions"].values())
        atomic_json(output, report)
    print(json.dumps({"report": str(output), "passed": report["passed"], "assertions": report["assertions"],
                      "error": report.get("error"), "restored_vlc": report.get("restored_vlc")}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
