#!/usr/bin/env python3
"""Read selected EDS calendars into a private, disposable Noctalia vdir.

No credentials, account setup, refresh, or calendar write APIs are used. EDS
continues to own synchronization. Event data never goes to stdout or logs.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import tempfile

# EDS owns its settings; this reader never persists application preferences.
os.environ.setdefault('GSETTINGS_BACKEND', 'memory')
import gi
gi.require_version('EDataServer', '1.2')
gi.require_version('ECal', '2.0')
gi.require_version('ICalGLib', '4.0')
from gi.repository import EDataServer, ECal, ICalGLib as ICal, Gio, GLib, GLibUnix, GObject

MARKER = '.moonlit-eds-v1'
MARKER_CONTENT = 'Moonlit EDS read-only export v1\n'
FILES = frozenset(('calendar.ics', 'displayname', 'color'))


def atomic_write(path, content):
    if path.is_symlink():
        raise ValueError('Refusing output symlink')
    data = content.encode()
    if path.is_file() and path.read_bytes() == data:
        return
    fd, temporary = tempfile.mkstemp(prefix='.calendar-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def private_root(path):
    path = path.absolute()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Calendar output must be a private owned directory')
    marker = path/MARKER
    if any(path.iterdir()) and (marker.is_symlink() or not marker.is_file()
                               or marker.read_text() != MARKER_CONTENT):
        raise ValueError('Refusing unrelated calendar output directory')
    def clean_temporary(directory):
        for item in directory.iterdir():
            if re.fullmatch(r'\.calendar-[a-zA-Z0-9_-]+', item.name):
                info = item.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise ValueError('Refusing unsafe interrupted export')
                item.unlink()
    if marker.is_file():
        clean_temporary(path)
    for child in path.iterdir():
        if child.is_symlink():
            raise ValueError('Refusing output symlink')
        if child.name in (MARKER, 'status.json') and child.is_file():
            continue
        if not re.fullmatch('[a-f0-9]{32}', child.name) or not child.is_dir():
            raise ValueError('Refusing unrelated calendar output entry')
        clean_temporary(child)
        if any(item.is_symlink() or not item.is_file() or item.name not in FILES for item in child.iterdir()):
            raise ValueError('Refusing unrelated calendar collection entry')
    atomic_write(marker, MARKER_CONTENT)
    return path


class CalendarExport:
    """Keep recurrence masters/exceptions intact; libical owns serialization."""
    def __init__(self):
        self.components = {}
        self.timezones = {}

    def update(self, components):
        for component in components:
            if component.isa() != ICal.ComponentKind.VEVENT_COMPONENT:
                continue
            wrapped = ECal.Component.new_from_icalcomponent(component.clone())
            ident = wrapped.get_id()
            if ident.get_uid():
                self.components[(ident.get_uid(), ident.get_rid() or '')] = component.clone()

    def remove(self, identifiers):
        for ident in identifiers:
            uid, rid = ident.get_uid(), ident.get_rid() or ''
            for key in list(self.components):
                if key[0] == uid and (not rid or key[1] == rid):
                    del self.components[key]

    def needed_timezones(self):
        zones = set()
        for component in self.components.values():
            component.foreach_tzid(lambda parameter, _: zones.add(parameter.get_tzid()), None)
        return zones - self.timezones.keys()

    def serialize(self):
        if self.needed_timezones():
            raise ValueError('A referenced timezone has not been resolved')
        calendar = ICal.Component.new(ICal.ComponentKind.VCALENDAR_COMPONENT)
        calendar.add_property(ICal.Property.new_version('2.0'))
        calendar.add_property(ICal.Property.new_prodid('-//Moonlit//GNOME Calendar read-only//EN'))
        for name in sorted(self.timezones):
            calendar.add_component(self.timezones[name].clone())
        for key in sorted(self.components):
            calendar.add_component(self.components[key].clone())
        return calendar.as_ical_string()


class Bridge:
    def __init__(self, output=None, probe=False):
        self.output, self.probe = output, probe
        self.loop = GLib.MainLoop()
        self.cancel = Gio.Cancellable()
        self.registry = None
        self.entries = {}
        self.stopping = False
        self.failed = False
        self.reported = False
        now = datetime.now(timezone.utc)
        self.start = (now-timedelta(days=365)).strftime('%Y%m%dT%H%M%SZ')
        self.end = (now+timedelta(days=365)).strftime('%Y%m%dT%H%M%SZ')
        self.query = f'(occur-in-time-range? (make-time "{self.start}") (make-time "{self.end}"))'

    def status(self):
        pending = any(not entry['settled'] for entry in self.entries.values())
        errors = sum(entry['error'] for entry in self.entries.values()) + int(self.failed)
        value = dict(ready=self.registry is not None and not pending and not self.stopping,
                     running=not self.stopping, degraded=bool(errors), error_count=errors,
                     source_count=len(self.entries),
                     component_count=sum(len(entry['model'].components) for entry in self.entries.values()),
                     range_start=self.start, range_end=self.end,
                     updated_at=datetime.now(timezone.utc).isoformat())
        if self.output:
            atomic_write(self.output/'status.json', json.dumps(value, sort_keys=True)+'\n')
        if self.probe and not self.reported and (value['ready'] or self.failed):
            self.reported = True
            print(json.dumps(value, sort_keys=True), flush=True)
            self.loop.quit()

    def begin(self):
        self.status()
        self.registry_timeout = GLib.timeout_add_seconds(20, self.registry_failed)
        EDataServer.SourceRegistry.new(self.cancel, self.registry_ready, None)

    def registry_failed(self):
        self.registry_timeout = 0
        self.failed = True
        self.cancel.cancel()
        self.status()
        self.loop.quit()
        return False

    def registry_ready(self, _source, result, _data):
        if self.stopping or self.failed:
            return
        GLib.source_remove(self.registry_timeout)
        self.registry_timeout = 0
        try:
            self.registry = EDataServer.SourceRegistry.new_finish(result)
        except GLib.Error:
            self.failed = True
            self.status()
            self.loop.quit()
            return
        for event in ('source-added', 'source-removed', 'source-changed'):
            self.registry.connect(event, lambda *_: self.reconcile())
        self.reconcile()

    def remove_entry(self, uid):
        entry = self.entries.pop(uid)
        entry['cancel'].cancel()
        if entry.get('timer'):
            GLib.source_remove(entry['timer'])
        if entry.get('view'):
            try:
                entry['view'].stop()
            except GLib.Error:
                pass
            for handler in entry.get('view_handlers', ()):
                entry['view'].disconnect(handler)
        if entry.get('client_handler'):
            GObject.Object.disconnect(entry['client'], entry['client_handler'])
        entry.pop('view', None)
        entry.pop('client', None)
        if self.output:
            directory = self.output/entry['folder']
            if directory.exists():
                for name in FILES:
                    (directory/name).unlink(missing_ok=True)
                directory.rmdir()

    def reconcile(self):
        if self.stopping:
            return
        selected = {}
        for source in self.registry.list_sources(EDataServer.SOURCE_EXTENSION_CALENDAR):
            extension = source.get_extension(EDataServer.SOURCE_EXTENSION_CALENDAR)
            if self.registry.check_enabled(source) and extension.get_selected():
                selected[source.get_uid()] = source
        for uid in list(self.entries):
            if uid not in selected or self.entries[uid]['error']:
                self.remove_entry(uid)
        for uid, source in selected.items():
            if uid not in self.entries:
                entry = dict(source=source, cancel=Gio.Cancellable(), settled=False, error=False,
                             model=CalendarExport(), zones=set(), complete=False,
                             folder=hashlib.sha256(uid.encode()).hexdigest()[:32])
                self.entries[uid] = entry
                entry['timer'] = GLib.timeout_add_seconds(20, self.fail_entry, uid, entry)
                ECal.Client.connect(source, ECal.ClientSourceType.EVENTS, 2, entry['cancel'],
                                    lambda _s, result, _d, u=uid, e=entry: self.client_ready(u, e, result), None)
            elif self.entries[uid]['settled']:
                self.publish(uid, self.entries[uid])
        if self.output:
            folders = {entry['folder'] for entry in self.entries.values()}
            for child in self.output.iterdir():
                if child.is_dir() and child.name not in folders:
                    for name in FILES:
                        (child/name).unlink(missing_ok=True)
                    child.rmdir()
        self.status()

    def current(self, uid, entry):
        return not self.stopping and self.entries.get(uid) is entry and not entry['error']

    def fail_entry(self, uid, entry):
        if not self.current(uid, entry):
            return False
        entry['error'] = entry['settled'] = True
        entry['cancel'].cancel()
        if entry.get('timer'):
            GLib.source_remove(entry['timer'])
            entry['timer'] = 0
        if entry.get('view'):
            try:
                entry['view'].stop()
            except GLib.Error:
                pass
        self.status()
        return False

    def client_ready(self, uid, entry, result):
        if not self.current(uid, entry):
            return
        try:
            entry['client'] = ECal.Client.connect_finish(result)
            entry['client_handler'] = GObject.Object.connect(
                entry['client'], 'backend-died', lambda *_: self.fail_entry(uid, entry))
            entry['client'].get_view(self.query, entry['cancel'],
                                     lambda _c, res, _d: self.view_ready(uid, entry, res), None)
        except GLib.Error:
            self.fail_entry(uid, entry)

    def view_ready(self, uid, entry, result):
        if not self.current(uid, entry):
            return
        try:
            ok, view = entry['client'].get_view_finish(result)
            if not ok:
                self.fail_entry(uid, entry)
                return
            entry['view'] = view
            entry['view_handlers'] = []
            for event in ('objects-added', 'objects-modified'):
                entry['view_handlers'].append(view.connect(event, lambda _v, objects: self.changed(uid, entry, objects)))
            entry['view_handlers'].append(view.connect('objects-removed', lambda _v, ids: self.removed(uid, entry, ids)))
            entry['view_handlers'].append(view.connect('complete', lambda _v, error: self.complete(uid, entry, error)))
            view.start()
        except GLib.Error:
            self.fail_entry(uid, entry)

    def changed(self, uid, entry, objects):
        if not self.current(uid, entry):
            return
        entry['model'].update(objects)
        for name in entry['model'].needed_timezones()-entry['zones']:
            entry['zones'].add(name)
            entry['client'].get_timezone(name, entry['cancel'],
                lambda _c, res, _d, tz=name: self.timezone_ready(uid, entry, tz, res), None)
        self.publish(uid, entry)

    def timezone_ready(self, uid, entry, name, result):
        if not self.current(uid, entry):
            return
        try:
            ok, zone = entry['client'].get_timezone_finish(result)
            if not ok or zone is None:
                self.fail_entry(uid, entry)
                return
            entry['model'].timezones[name] = zone.get_component().clone()
            entry['zones'].discard(name)
            self.publish(uid, entry)
        except GLib.Error:
            self.fail_entry(uid, entry)

    def removed(self, uid, entry, identifiers):
        if self.current(uid, entry):
            entry['model'].remove(identifiers)
            self.publish(uid, entry)

    def complete(self, uid, entry, error):
        if not self.current(uid, entry):
            return
        if error:
            self.fail_entry(uid, entry)
            return
        entry['complete'] = True
        self.publish(uid, entry)

    def publish(self, uid, entry):
        if not self.current(uid, entry) or not entry['complete'] or entry['zones']:
            return
        try:
            if self.output:
                directory = self.output/entry['folder']
                directory.mkdir(mode=0o700, exist_ok=True)
                atomic_write(directory/'calendar.ics', entry['model'].serialize())
                atomic_write(directory/'displayname', entry['source'].get_display_name()+' · read-only\n')
                extension = entry['source'].get_extension(EDataServer.SOURCE_EXTENSION_CALENDAR)
                color = extension.get_color() or ''
                if re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?', color):
                    atomic_write(directory/'color', color+'\n')
        except (OSError, ValueError):
            self.fail_entry(uid, entry)
            return
        entry['settled'] = True
        if entry.get('timer'):
            GLib.source_remove(entry['timer'])
            entry['timer'] = 0
        self.status()

    def stop(self, *_):
        self.stopping = True
        self.cancel.cancel()
        for uid in list(self.entries):
            self.remove_entry(uid)
        self.status()
        self.loop.quit()
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='private owned vdir output directory')
    parser.add_argument('--parent', type=int, help='exit when this parent exits (Linux pidfd)')
    parser.add_argument('--probe', action='store_true', help='only count selected calendar components; no export')
    args = parser.parse_args()
    if not args.probe and args.output is None:
        parser.error('--output is required unless --probe is used')
    fd = None
    bridge = None
    try:
        root = None if args.probe else private_root(args.output)
        bridge = Bridge(root, args.probe)
        if args.parent:
            fd = os.pidfd_open(args.parent)
            GLibUnix.fd_add_full(GLib.PRIORITY_DEFAULT, fd, GLib.IOCondition.IN, bridge.stop, None)
        for number in (signal.SIGTERM, signal.SIGINT):
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, number, bridge.stop)
        bridge.begin()
        bridge.loop.run()
        return int(bridge.failed)
    except (OSError, ValueError, GLib.Error) as error:
        # An EDS error message may contain account names or URLs.
        print('Calendar bridge unavailable: '+type(error).__name__, file=__import__('sys').stderr)
        return 1
    finally:
        if bridge and not bridge.stopping:
            bridge.stop()
        if fd is not None:
            os.close(fd)


if __name__ == '__main__':
    raise SystemExit(main())
