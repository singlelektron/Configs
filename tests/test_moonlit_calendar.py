"""Calendar export tests use synthetic events, never a real account or bus."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
try:
    SPEC = importlib.util.spec_from_file_location('moonlit_calendar', ROOT/'config/moonlit/calendar_bridge.py')
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
except (ImportError, ValueError):
    module = None

EVENT = '''BEGIN:VEVENT
UID:synthetic-series
DTSTART;TZID=Test/Zone:20261007T090000
DTEND;TZID=Test/Zone:20261007T100000
RRULE:FREQ=WEEKLY;COUNT=4
EXDATE;TZID=Test/Zone:20261014T090000
SUMMARY:Synthetic fixture
END:VEVENT
'''
EXCEPTION = '''BEGIN:VEVENT
UID:synthetic-series
RECURRENCE-ID;TZID=Test/Zone:20261021T090000
DTSTART;TZID=Test/Zone:20261021T110000
DTEND;TZID=Test/Zone:20261021T120000
SUMMARY:Synthetic changed occurrence
END:VEVENT
'''
ZONE = '''BEGIN:VTIMEZONE
TZID:Test/Zone
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:+0800
TZOFFSETTO:+0800
TZNAME:Fixture
END:STANDARD
END:VTIMEZONE
'''


@unittest.skipIf(module is None, 'EDataServer/ECal/libical GI bindings unavailable')
class CalendarTests(unittest.TestCase):
    def component(self, text):
        return module.ICal.Component.new_from_string(text)

    def model(self):
        model = module.CalendarExport()
        model.update([self.component(EVENT), self.component(EXCEPTION)])
        model.timezones['Test/Zone'] = self.component(ZONE)
        return model

    def test_recurring_master_exception_exdate_and_timezone_survive_roundtrip(self):
        model = self.model()
        text = model.serialize()
        for value in ('RRULE:FREQ=WEEKLY;COUNT=4', 'EXDATE;TZID=Test/Zone:20261014T090000',
                      'RECURRENCE-ID;TZID=Test/Zone:20261021T090000', 'BEGIN:VTIMEZONE',
                      'TZOFFSETTO:+0800'):
            self.assertIn(value, text)
        loaded = self.component(text)
        kind = module.ICal.ComponentKind.VEVENT_COMPONENT
        restored = module.CalendarExport()
        event = loaded.get_first_component(kind)
        while event:
            restored.update([event])
            event = loaded.get_next_component(kind)
        self.assertEqual(set(restored.components), set(model.components))
        self.assertEqual(restored.needed_timezones(), {'Test/Zone'})
        restored.timezones['Test/Zone'] = loaded.get_first_component(module.ICal.ComponentKind.VTIMEZONE_COMPONENT)
        self.assertEqual(restored.serialize(), text)

    def test_modification_replaces_same_occurrence_and_removal_respects_series(self):
        model = self.model()
        model.update([self.component(EXCEPTION.replace('110000', '130000'))])
        self.assertEqual(len(model.components), 2)
        self.assertIn('20261021T130000', model.serialize())
        model.remove([module.ECal.ComponentId.new('synthetic-series', '20261021T090000')])
        self.assertEqual(len(model.components), 1)
        self.assertNotIn('RECURRENCE-ID', model.serialize())
        model.update([self.component(EXCEPTION)])
        model.remove([module.ECal.ComponentId.new('synthetic-series', None)])
        self.assertEqual(model.components, {})

    def test_missing_timezone_refuses_misleading_export(self):
        model = module.CalendarExport()
        model.update([self.component(EVENT)])
        with self.assertRaisesRegex(ValueError, 'timezone'):
            model.serialize()

    def test_private_output_refuses_unrelated_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'export'
            root.mkdir(mode=0o700)
            (root/'unrelated').write_text('keep')
            with self.assertRaises(ValueError):
                module.private_root(root)
            (root/'unrelated').unlink()
            module.private_root(root)
            (root/'status.json').symlink_to(Path(tmp)/'outside')
            with self.assertRaises(ValueError):
                module.private_root(root)
            self.assertFalse((Path(tmp)/'outside').exists())

    def test_atomic_export_private_unchanged_content_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = module.private_root(Path(tmp)/'export')
            path = root/'status.json'
            module.atomic_write(path, 'fixture')
            before = path.stat()
            module.atomic_write(path, 'fixture')
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_late_callbacks_cannot_republish_removed_source(self):
        bridge = module.Bridge()
        entry = {'error':False}
        bridge.entries['uid'] = entry
        replacement = {'error':False}
        bridge.entries['uid'] = replacement
        self.assertFalse(bridge.current('uid', entry))
        self.assertTrue(bridge.current('uid', replacement))
        bridge.stopping = True
        self.assertFalse(bridge.current('uid', replacement))

    def test_deselect_cancels_view_and_removes_derived_collection_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = module.private_root(Path(tmp)/'export')
            bridge = module.Bridge(root)
            directory = root/('a'*32)
            directory.mkdir(mode=0o700)
            module.atomic_write(directory/'calendar.ics', self.model().serialize())
            cancel, view = mock.Mock(), mock.Mock()
            entry = dict(cancel=cancel, view=view, view_handlers=[1,2], folder=directory.name)
            bridge.entries['source'] = entry
            bridge.remove_entry('source')
            cancel.cancel.assert_called_once()
            view.stop.assert_called_once()
            self.assertEqual(view.disconnect.call_args_list, [mock.call(1),mock.call(2)])
            self.assertFalse(directory.exists())
            self.assertTrue((root/module.MARKER).is_file())

    def test_interrupted_atomic_export_recovers_only_marked_private_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = module.private_root(Path(tmp)/'export')
            interrupted = root/'.calendar-interrupted'
            interrupted.write_text('synthetic incomplete data')
            interrupted.chmod(0o600)
            module.private_root(root)
            self.assertFalse(interrupted.exists())
            (root/module.MARKER).write_text('unrelated owner')
            with self.assertRaises(ValueError):
                module.private_root(root)


if __name__ == '__main__':
    unittest.main()
