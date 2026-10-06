"""Two controlled MPRIS peers. Run only on a disposable dbus-run-session bus.

Usage: mock_mpris.py /tmp/transport-log.jsonl
No network, account, or playback access. Used to verify Quickshell's real D-Bus
integration rather than only mocking the player-selection function.
"""
import json
import os
from pathlib import Path
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

ROOT = 'org.mpris.MediaPlayer2'
PLAYER = ROOT + '.Player'
PROPERTIES = 'org.freedesktop.DBus.Properties'
DBusGMainLoop(set_as_default=True)
if '/tmp/dbus-' not in os.environ.get('DBUS_SESSION_BUS_ADDRESS', ''):
    raise SystemExit('Use a private dbus-run-session bus for this fixture')
log = Path(sys.argv[1])


class Player(dbus.service.Object):
    def __init__(self, name, playing):
        self.name = name
        # Each player needs its own connection because their object paths match.
        self.player_bus = dbus.SessionBus(private=True)
        self.bus_name = dbus.service.BusName(ROOT + '.' + name, bus=self.player_bus)
        super().__init__(self.bus_name, '/org/mpris/MediaPlayer2')
        self.props = {
            'PlaybackStatus': 'Playing' if playing else 'Paused', 'LoopStatus': 'None',
            'Rate': dbus.Double(1), 'Shuffle': False, 'Volume': dbus.Double(.5),
            'Position': dbus.Int64(20000000), 'MinimumRate': dbus.Double(1), 'MaximumRate': dbus.Double(1),
            'CanGoNext': True, 'CanGoPrevious': True, 'CanPlay': True, 'CanPause': True,
            'CanSeek': True, 'CanControl': True,
            'Metadata': dbus.Dictionary({
                'mpris:trackid': dbus.ObjectPath('/track/one'), 'mpris:length': dbus.Int64(240000000),
                'xesam:title': '<b>春 & music</b>', 'xesam:artist': dbus.Array(['Artist'], signature='s'),
            }, signature='sv'),
        }

    def record(self, action, value=None):
        with log.open('a') as stream:
            stream.write(json.dumps({'player': self.name, 'action': action, 'value': value}) + '\n')

    @dbus.service.method(PROPERTIES, in_signature='ss', out_signature='v')
    def Get(self, interface, name):
        return self.GetAll(interface)[name]

    @dbus.service.method(PROPERTIES, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == PLAYER:
            return self.props
        return {'CanQuit': False, 'CanRaise': False, 'HasTrackList': False,
                'Identity': self.name, 'DesktopEntry': self.name,
                'SupportedUriSchemes': dbus.Array([], signature='s'),
                'SupportedMimeTypes': dbus.Array([], signature='s')}

    @dbus.service.method(PROPERTIES, in_signature='ssv')
    def Set(self, interface, name, value):
        self.props[name] = value
        self.PropertiesChanged(PLAYER, {name: value}, [])

    @dbus.service.signal(PROPERTIES, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    @dbus.service.method(PLAYER)
    def PlayPause(self):
        self.record('PlayPause')
        self.props['PlaybackStatus'] = 'Paused' if self.props['PlaybackStatus'] == 'Playing' else 'Playing'
        self.PropertiesChanged(PLAYER, {'PlaybackStatus': self.props['PlaybackStatus']}, [])

    @dbus.service.method(PLAYER)
    def Play(self):
        self.record('Play')
        self.props['PlaybackStatus'] = 'Playing'
        self.PropertiesChanged(PLAYER, {'PlaybackStatus': 'Playing'}, [])

    @dbus.service.method(PLAYER)
    def Pause(self):
        self.record('Pause')
        self.props['PlaybackStatus'] = 'Paused'
        self.PropertiesChanged(PLAYER, {'PlaybackStatus': 'Paused'}, [])

    @dbus.service.method(PLAYER)
    def Next(self):
        self.record('Next')

    @dbus.service.method(PLAYER)
    def Previous(self):
        self.record('Previous')

    @dbus.service.method(PLAYER, in_signature='ox')
    def SetPosition(self, track, position):
        self.record('SetPosition', int(position))
        self.props['Position'] = position

    @dbus.service.method(PLAYER, in_signature='x')
    def Seek(self, offset):
        self.record('Seek', int(offset))


players = [Player('firefox.instance42', True), Player('NeteaseCloudMusicGtk4', False)]
GLib.MainLoop().run()
