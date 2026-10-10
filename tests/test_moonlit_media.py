import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
S=importlib.util.spec_from_file_location('bridge',Path(__file__).resolve().parents[1]/'config/moonlit/plugins/moonlit-music/media_bridge.py')
m=importlib.util.module_from_spec(S);S.loader.exec_module(m)
class MediaTests(unittest.TestCase):
 def test_paused_netease_preferred_without_pinning_browser(self):
  players=[{'bus_name':'org.mpris.MediaPlayer2.chromium','playback_status':'Playing'}, {'bus_name':'org.mpris.MediaPlayer2.netease','playback_status':'Playing'}, {'bus_name':'org.mpris.MediaPlayer2.netease_gtk4','playback_status':'Paused'}]
  self.assertEqual(m.preferred(players),['org.mpris.MediaPlayer2.netease_gtk4','org.mpris.MediaPlayer2.netease'])
 def test_metadata_control_characters_plain_text(self):
  self.assertEqual(m.text('hello\x00\x1b<script>'),'hello<script>')
 def test_artwork_only_local_regular_files(self):
  self.assertEqual(m.artwork('https://example.com/art.jpg'),'')
  self.assertEqual(m.artwork('file://remote/etc/passwd'),'')
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'cover 空格.png';p.write_bytes(b'preview')
   self.assertEqual(m.artwork(p.as_uri()),str(p))
 def test_seek_rejects_unsupported_nan_and_out_of_range(self):
  b=object.__new__(m.Bridge);b.snapshot=lambda:{'can_seek':False,'length':120}
  with self.assertRaises(ValueError): b.action('seek','60')
  b.snapshot=lambda:{'can_seek':True,'length':120}
  for v in ['nan','inf','-1','121']:
   with self.assertRaises(ValueError): b.action('seek',v)
 def test_selection_rejects_removed_player(self):
  b=object.__new__(m.Bridge);b.call=lambda *args:([],)
  with self.assertRaises(ValueError): b.action('select','org.mpris.MediaPlayer2.gone')

class AutoSelectionTests(unittest.TestCase):
 def test_browser_cannot_override_automatic_netease(self):
  players=[{'bus_name':'netease_gtk4','playback_status':'Paused'},{'bus_name':'browser','playback_status':'Playing'}]
  self.assertEqual(m.auto_source(players,'netease_gtk4',{'auto':'netease_gtk4'}),'netease_gtk4')
 def test_explicit_browser_wins(self):
  players=[{'bus_name':'netease_gtk4'},{'bus_name':'browser'}]
  self.assertEqual(m.auto_source(players,'browser',{'explicit':'browser'}),'browser')
 def test_native_choice_and_hot_removal(self):
  players=[{'bus_name':'netease_gtk4'},{'bus_name':'browser'}]
  self.assertEqual(m.auto_source(players,'browser',{'auto':'netease_gtk4'}),'browser')
  self.assertEqual(m.auto_source(players,'gone',{'explicit':'gone'}),'netease_gtk4')

 def test_new_native_choice_beats_older_custom_explicit_choice(self):
  players=[{'bus_name':'netease_gtk4'},{'bus_name':'browser'}]
  self.assertEqual(m.auto_source(players,'netease_gtk4',{'explicit':'browser'}),'netease_gtk4')

 def test_custom_explicit_choice_survives_matching_native_pin(self):
  players=[{'bus_name':'netease_gtk4'},{'bus_name':'browser'}]
  self.assertEqual(m.auto_source(players,'browser',{'explicit':'browser'}),'browser')


class TransportTests(unittest.TestCase):
 def bridge(self):
  return object.__new__(m.Bridge)

 def test_transport_reconciles_first_and_addresses_original_selected_bus(self):
  for action,method in [('toggle','PlayPausePlayer'),('next','NextPlayer'),('previous','PreviousPlayer'),('stop','StopPlayer')]:
   with self.subTest(action=action):
    b=self.bridge();order=[]
    def snapshot():
     order.append('snapshot')
     return {'player':'netease_gtk4' if len(order)==1 else 'browser'}
    def call(name,signature=None,values=()):
     order.append((name,signature,values));return (True,)
    b.snapshot=snapshot;b.call=call
    b.action(action)
    self.assertEqual(order[:2],['snapshot',(method,'(s)',('netease_gtk4',))])

 def test_seek_addresses_resolved_source_and_converts_seconds_to_microseconds(self):
  b=self.bridge()
  b.snapshot=mock.Mock(return_value={'player':'netease_gtk4','can_seek':True,'length':120})
  b.call=mock.Mock(return_value=(True,))
  b.action('seek','30.25')
  b.call.assert_called_once_with('SetPositionPlayer','(sx)',('netease_gtk4',30250000))

 def test_rejected_transport_or_seek_reports_error_without_success_snapshot(self):
  for action,value in [('toggle',None),('seek','30')]:
   with self.subTest(action=action):
    b=self.bridge();b.snapshot=mock.Mock(return_value={'player':'netease_gtk4','can_seek':True,'length':120})
    b.call=mock.Mock(return_value=(False,))
    with self.assertRaisesRegex(ValueError,'did not accept'):
     b.action(action,value)
    b.snapshot.assert_called_once()

 def test_rejected_select_does_not_persist_or_claim_success(self):
  b=self.bridge();b.call=mock.Mock(side_effect=[([{'bus_name':'browser'}],),(False,)])
  b.snapshot=mock.Mock()
  with mock.patch.object(m,'save_selection') as save:
   with self.assertRaisesRegex(ValueError,'did not accept'):
    b.action('select','browser')
  save.assert_not_called();b.snapshot.assert_not_called()

 def test_no_player_transport_fails_without_sending(self):
  b=self.bridge();b.snapshot=lambda:{'player':''};b.call=mock.Mock()
  with self.assertRaisesRegex(ValueError,'No player'):
   b.action('toggle')
  b.call.assert_not_called()


class ReconciliationTests(unittest.TestCase):
 def test_native_selection_replaces_old_saved_explicit_choice(self):
  b=object.__new__(m.Bridge)
  players=[{'bus_name':'netease_gtk4'},{'bus_name':'browser'}]
  def call(method,*args):
   return {'GetPlayers':(players,), 'GetPlayerPreferences':(True,'netease_gtk4',['netease_gtk4']),
           'GetActivePlayer':(True,{'bus_name':'netease_gtk4'})}[method]
  b.call=mock.Mock(side_effect=call)
  with mock.patch.object(m,'selection_state',return_value={'explicit':'browser'}),mock.patch.object(m,'save_selection') as save:
   self.assertEqual(b.snapshot()['player'],'netease_gtk4')
  save.assert_called_once_with({'explicit':'netease_gtk4'})
  self.assertFalse(any(c.args[0]=='SetActivePlayerPreference' for c in b.call.call_args_list))

 def test_hot_removal_discards_old_explicit_selection_and_uses_netease(self):
  b=object.__new__(m.Bridge)
  def call(method,*args):
   return {'GetPlayers':([{'bus_name':'netease_gtk4'}],),
           'GetPlayerPreferences':(False,'',['netease_gtk4']),
           'SetActivePlayerPreference':(True,),
           'GetActivePlayer':(True,{'bus_name':'netease_gtk4'})}[method]
  b.call=mock.Mock(side_effect=call)
  with mock.patch.object(m,'selection_state',return_value={'explicit':'browser'}),mock.patch.object(m,'save_selection') as save:
   b.snapshot()
  save.assert_called_once_with({'auto':'netease_gtk4'})
  self.assertIn(mock.call('SetActivePlayerPreference','(s)',('netease_gtk4',)),b.call.call_args_list)
