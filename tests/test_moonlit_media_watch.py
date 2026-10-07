"""Event/timer regression tests for the plugin-owned media stream."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1] / "config/moonlit/plugins/moonlit-music"
sys.path.insert(0, str(PLUGIN))
spec = importlib.util.spec_from_file_location("moonlit_watch", PLUGIN / "media_watch.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sys.path.pop(0)


class Scheduler:
    def __init__(self):
        self.next = 0
        self.sources = {}

    def timeout_add(self, milliseconds, callback):
        self.next += 1
        self.sources[self.next] = (milliseconds, callback)
        return self.next

    def source_remove(self, key):
        self.sources.pop(key, None)

    def fire(self, key):
        period, callback = self.sources.pop(key)
        if callback():
            self.sources[key] = (period, callback)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "control.json"
        self.glib = Scheduler()
        self.bridge = mock.Mock()
        self.output = []
        self.watch = m.MediaWatch(self.bridge, self.glib, self.path, self.output.append)
        self.playing = {"player": "test", "title": "Test", "status": "Playing", "position": 12,
                        "players": [{"bus": "test", "name": "Fixture"}]}
        self.bridge.snapshot.side_effect = lambda: dict(self.playing)

    def control(self, visible, revision, refresh=False):
        self.path.write_text(json.dumps({"instance": "test", "revision": revision,
                                         "visible": visible, "refresh": refresh}))
        self.watch.read_control()

    def refresh(self):
        self.watch.request_refresh()
        self.glib.fire(self.watch.refresh_source)

    def test_duplicate_native_and_raw_events_are_coalesced(self):
        for _ in range(20):
            self.watch.request_refresh()
        self.assertEqual(len(self.glib.sources), 1)
        self.glib.fire(self.watch.refresh_source)
        self.bridge.snapshot.assert_called_once()
        self.assertEqual(len(self.output), 1)
        self.assertFalse(self.glib.sources)

    def test_identical_data_does_not_publish_even_after_key_order_changes(self):
        self.refresh()
        self.bridge.snapshot.side_effect = lambda: dict(reversed(list(self.playing.items())))
        self.refresh()
        self.assertEqual(len(self.output), 1)

    def test_hidden_playback_has_no_timer_or_position_refresh(self):
        self.refresh()
        self.playing["position"] = 50
        self.refresh()
        self.assertEqual(self.watch.current["position"], 12)
        self.assertEqual(len(self.output), 1)
        self.assertFalse(self.glib.sources)

    def test_position_timer_only_visible_and_playing_and_stops_on_close(self):
        self.refresh()
        self.control(True, 1)
        self.glib.fire(self.watch.refresh_source)
        timer = self.watch.position_source
        self.assertEqual(self.glib.sources[timer][0], 1000)
        self.bridge.call.return_value = (25000000,)
        self.glib.fire(timer)
        self.bridge.call.assert_called_once_with("GetPositionPlayer", "(s)", ("test",))
        self.assertEqual(self.watch.current["position"], 25)
        self.control(False, 2)
        self.assertFalse(self.watch.position_source)
        self.assertFalse(self.glib.sources)

    def test_paused_and_no_source_never_start_position_timer(self):
        self.watch.visible = True
        for data in ({"player": "test", "status": "Paused"}, {"player": "", "status": "Playing"}):
            self.watch.publish(data)
            self.assertFalse(self.watch.position_source)

    def test_reopen_requests_current_position_not_frozen_snapshot(self):
        self.refresh()
        self.playing["position"] = 80
        self.control(True, 1)
        self.glib.fire(self.watch.refresh_source)
        self.assertEqual(self.watch.current["position"], 80)

    def test_progress_error_stops_timer_and_reports_unavailable(self):
        self.watch.visible = True
        self.refresh()
        timer = self.watch.position_source
        self.bridge.call.side_effect = RuntimeError("source removed")
        self.glib.fire(timer)
        self.assertFalse(self.watch.position_source)
        self.assertFalse(self.glib.sources)
        self.assertEqual(self.output[-1]["error"], "source removed")

    def test_only_relevant_properties_and_visible_seek_trigger_refresh(self):
        def props(changes):
            value = mock.Mock()
            value.unpack.return_value = (m.PLAYER, changes, [])
            self.watch.on_properties(None, None, None, None, None, value)
        props({"Position": 20, "Volume": .5})
        self.watch.on_seeked()
        self.assertFalse(self.glib.sources)
        props({"PlaybackStatus": "Playing"})
        self.assertTrue(self.watch.refresh_source)

    def test_delayed_native_cache_settles_without_later_native_signal(self):
        self.playing["status"] = "Paused"
        self.playing["can_seek"] = False
        self.refresh()
        event = mock.Mock()
        event.unpack.return_value = (m.PLAYER, {"PlaybackStatus": "Playing", "CanSeek": True}, [])
        self.watch.on_properties(None, None, None, None, None, event)
        self.glib.fire(self.watch.refresh_source)  # 25ms: still old native cache
        self.assertEqual(self.output[-1]["status"], "Paused")
        self.playing.update(status="Playing", can_seek=True)  # native's 120ms trailing cache update
        self.glib.fire(self.watch.reconcile_source)
        self.glib.fire(self.watch.refresh_source)
        self.assertEqual(self.output[-1]["status"], "Playing")
        self.assertTrue(self.output[-1]["can_seek"])
        self.glib.fire(self.watch.reconcile_source)
        self.glib.fire(self.watch.refresh_source)
        self.assertFalse(self.glib.sources)  # finite retries, never idle polling

    def test_raw_burst_restarts_finite_reconciliation_and_shutdown_cancels_it(self):
        event = mock.Mock()
        event.unpack.return_value = (m.PLAYER, {"PlaybackStatus": "Paused"}, [])
        self.watch.on_properties(None, None, None, None, None, event)
        old = self.watch.reconcile_source
        self.watch.on_properties(None, None, None, None, None, event)
        self.assertNotIn(old, self.glib.sources)
        self.assertEqual(len(self.glib.sources), 2)
        self.watch.close()
        self.assertFalse(self.glib.sources)

    def test_owner_disappears_reports_error_and_recovery_requests_snapshot(self):
        event = mock.Mock()
        event.unpack.return_value = (m.NATIVE_NAME, ":1.2", "")
        self.watch.on_name_owner(None, None, None, None, None, event)
        self.assertIn("unavailable", self.output[-1]["error"])
        event.unpack.return_value = (m.NATIVE_NAME, "", ":1.3")
        self.watch.on_name_owner(None, None, None, None, None, event)
        self.assertTrue(self.watch.refresh_source)

    def test_same_control_revision_does_not_request_duplicate_refresh(self):
        self.control(False, 1, refresh=True)
        self.glib.fire(self.watch.refresh_source)
        self.watch.read_control()
        self.assertFalse(self.glib.sources)

    def test_shutdown_cancels_sources_and_unsubscribes(self):
        self.watch.visible = True
        self.refresh()
        self.watch.request_refresh()
        self.watch.subscriptions = [3, 4]
        self.watch.file_monitor = mock.Mock()
        self.watch.close()
        self.assertFalse(self.glib.sources)
        self.watch.file_monitor.cancel.assert_called_once()
        self.bridge.bus.signal_unsubscribe.assert_has_calls([mock.call(3), mock.call(4)])
        self.watch.request_refresh()
        self.assertFalse(self.glib.sources)


if __name__ == "__main__":
    unittest.main()
