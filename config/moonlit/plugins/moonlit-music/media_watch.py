#!/usr/bin/env python3
"""Plugin-owned Noctalia MPRIS event stream; no hidden-state polling.

runStream owns this process group. stdout carries changed snapshots; a watched
control file carries visibility/explicit refresh changes from Luau.
"""
import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import sys

from media_bridge import Bridge, text

NATIVE_NAME = "dev.noctalia.Mpris"
NATIVE_PATH = "/dev/noctalia/Mpris"
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
RELEVANT_PROPERTIES = frozenset(("Metadata", "PlaybackStatus", "Rate", "CanControl", "CanPlay", "CanPause",
                                 "CanGoNext", "CanGoPrevious", "CanSeek"))


def error_state(message):
    return {"error": text(message), "player": "", "title": "Player unavailable", "status": "Stopped",
            "players": [], "can_play": False, "can_pause": False, "can_next": False,
            "can_previous": False, "can_seek": False, "position": 0, "length": 0,
            "art": "", "artist": "", "album": "", "queue_supported": False}


def emit_json(data):
    print(json.dumps(data, ensure_ascii=False, separators=(",", ":")), flush=True)


def parent_death_guard():
    """If the stream wrapper dies, its Gio worker must leave as well."""
    parent = os.getppid()
    if parent <= 1:
        raise RuntimeError("Media stream must have a live owner")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot arm media stream owner-death cleanup")
    if os.getppid() != parent:
        raise RuntimeError("Media stream owner exited during startup")


class MediaWatch:
    def __init__(self, bridge, glib, control_path, emit=emit_json):
        self.bridge = bridge
        self.GLib = glib
        self.control_path = Path(control_path)
        self.emit = emit
        self.current = None
        self.visible = False
        self.control_revision = None
        self.refresh_source = 0
        self.position_source = 0
        self.reconcile_source = 0
        self.reconcile_remaining = 0
        self.closed = False
        self.subscriptions = []
        self.file_monitor = None

    def publish(self, data):
        if data != self.current:
            self.current = data
            self.emit(data)
        self.sync_position_timer()

    def request_refresh(self, *_):
        if not self.closed and not self.refresh_source:
            # Let native caches consume the source event and coalesce duplicate
            # native/raw notifications. This is a one-shot, not a poll timer.
            self.refresh_source = self.GLib.timeout_add(25, self.refresh)

    def refresh(self):
        self.refresh_source = 0
        if self.closed:
            return False
        try:
            data = self.bridge.snapshot()
            if (not self.visible and self.current and data.get("player") == self.current.get("player")
                    and data.get("title") == self.current.get("title")
                    and data.get("status") == self.current.get("status") == "Playing"):
                data["position"] = self.current.get("position", 0)
            self.publish(data)
        except Exception as error:
            self.publish(error_state(error))
        return False

    def sync_position_timer(self):
        wanted = bool(not self.closed and self.visible and self.current
                      and self.current.get("player") and self.current.get("status") == "Playing")
        if wanted and not self.position_source:
            self.position_source = self.GLib.timeout_add(1000, self.position_tick)
        elif not wanted and self.position_source:
            self.GLib.source_remove(self.position_source)
            self.position_source = 0

    def position_tick(self):
        if self.closed or not self.visible or not self.current or self.current.get("status") != "Playing":
            self.position_source = 0
            return False
        try:
            # The existing connection queries Noctalia's authoritative/projected
            # position; source and transport reconciliation stays event driven.
            value = self.bridge.call("GetPositionPlayer", "(s)", (self.current["player"],))[0]
            data = dict(self.current)
            data["position"] = max(0, value / 1e6)
            self.publish(data)
        except Exception as error:
            self.position_source = 0
            self.publish(error_state(error))
            return False
        return True

    def read_control(self, *_):
        try:
            with self.control_path.open() as stream:
                control = json.load(stream)
            revision = (control.get("instance"), control.get("revision"))
            if revision == self.control_revision:
                return
            self.control_revision = revision
            visible = control.get("visible") is True
            opening = visible and not self.visible
            self.visible = visible
            self.sync_position_timer()
            if opening or control.get("refresh") is True:
                self.request_refresh()
        except (OSError, ValueError, TypeError, AttributeError):
            self.visible = False
            self.sync_position_timer()

    def on_file_changed(self, _monitor, changed, other, _event):
        paths = [file.get_path() for file in (changed, other) if file is not None]
        if str(self.control_path) in paths:
            self.read_control()

    def on_native_signal(self, _connection, _sender, _path, _interface, _signal, _parameters):
        self.request_refresh()

    def reconcile_tick(self):
        self.reconcile_source = 0
        if self.closed:
            return False
        self.reconcile_remaining -= 1
        self.request_refresh()
        if self.reconcile_remaining > 0:
            self.reconcile_source = self.GLib.timeout_add(600, self.reconcile_tick)
        return False

    def reconcile_property_burst(self):
        # Noctalia 5.2.1 trails raw property bursts by 120ms, then does async
        # GetAll without a public signal for status/capability-only updates.
        # Two bounded reconciliations after the latest event cover that cache
        # delay and a slow round trip. These stop completely after each burst.
        if self.reconcile_source:
            self.GLib.source_remove(self.reconcile_source)
        self.reconcile_remaining = 2
        self.reconcile_source = self.GLib.timeout_add(200, self.reconcile_tick)

    def on_properties(self, _connection, _sender, _path, _interface, _signal, parameters):
        interface, changed, invalidated = parameters.unpack()
        if interface == PLAYER and RELEVANT_PROPERTIES.intersection(set(changed) | set(invalidated)):
            self.request_refresh()
            self.reconcile_property_burst()

    def on_seeked(self, *_):
        if self.visible:
            self.request_refresh()

    def on_name_owner(self, _connection, _sender, _path, _interface, _signal, parameters):
        name, _old, new = parameters.unpack()
        if name == NATIVE_NAME:
            if new:
                self.request_refresh()
            else:
                self.publish(error_state("Noctalia media service is unavailable"))
        elif name.startswith("org.mpris.MediaPlayer2."):
            self.request_refresh()

    def start(self):
        Gio = self.bridge.Gio
        connection = self.bridge.bus
        for sender, interface, name, path, callback in (
            (NATIVE_NAME, NATIVE_NAME, None, NATIVE_PATH, self.on_native_signal),
            (None, "org.freedesktop.DBus.Properties", "PropertiesChanged", MPRIS_PATH, self.on_properties),
            (None, PLAYER, "Seeked", MPRIS_PATH, self.on_seeked),
            ("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus", self.on_name_owner),
        ):
            self.subscriptions.append(connection.signal_subscribe(sender, interface, name, path, None,
                Gio.DBusSignalFlags.NONE, callback))
        self.file_monitor = Gio.File.new_for_path(str(self.control_path.parent)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.file_monitor.connect("changed", self.on_file_changed)
        self.read_control()
        self.request_refresh()

    def close(self):
        self.closed = True
        for source in (self.refresh_source, self.position_source, self.reconcile_source):
            if source:
                self.GLib.source_remove(source)
        self.refresh_source = self.position_source = self.reconcile_source = 0
        self.reconcile_remaining = 0
        if self.file_monitor:
            self.file_monitor.cancel()
        for subscription in self.subscriptions:
            self.bridge.bus.signal_unsubscribe(subscription)
        self.subscriptions.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-file", type=Path, required=True)
    parser.add_argument("--owner-pid", type=int, help="Owning Noctalia process, above the stream shell")
    args = parser.parse_args()
    parent_death_guard()
    owner_fd = os.pidfd_open(args.owner_pid) if args.owner_pid is not None else None
    control = args.control_file.expanduser().absolute()
    info = control.parent.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("Media control directory must belong to this user")
    # Hot reload can briefly overlap streams while the old process group exits.
    lock_fd = os.open(str(control) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    if os.fstat(lock_fd).st_uid != os.getuid():
        raise RuntimeError("Media stream lock belongs to another user")
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    # Only a local control file is monitored; never activate GVfs helpers.
    os.environ["GIO_USE_VFS"] = "local"
    bridge = Bridge()
    GLib = bridge.GLib
    loop = GLib.MainLoop()
    watcher = MediaWatch(bridge, GLib, control)

    def quit_loop(*_):
        loop.quit()
        return False

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, number, quit_loop)
    GLib.io_add_watch(sys.stdout.fileno(), GLib.IO_ERR | GLib.IO_HUP, quit_loop)
    bridge.bus.connect("closed", quit_loop)
    if owner_fd is not None:
        GLib.io_add_watch(owner_fd, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, quit_loop)
    try:
        watcher.start()
        loop.run()
    finally:
        watcher.close()
        os.close(lock_fd)
        if owner_fd is not None:
            os.close(owner_fd)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        raise SystemExit(0)
    except Exception as error:
        try:
            emit_json(error_state(error))
        except BrokenPipeError:
            pass
        raise SystemExit(1)
