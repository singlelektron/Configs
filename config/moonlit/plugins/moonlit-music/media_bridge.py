#!/usr/bin/env python3
"""Thin Noctalia v5 MPRIS adapter: the shell owns selection and playback state."""
import argparse
import json
import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, unquote


def text(value, limit=512):
    return ''.join(c for c in str(value or '') if c.isprintable())[:limit]


def preferred(players):
    """Reuse PR #3's NetEase preference without overriding an explicit user pin."""
    def rank(p):
        name = (p.get('bus_name', '') + ' ' + p.get('identity', '')).casefold()
        return (0 if 'netease' in name and 'gtk4' in name else 1 if 'netease' in name else 2,
                p.get('playback_status') != 'Playing', p.get('bus_name', ''))
    return [p['bus_name'] for p in sorted(players, key=rank)
            if 'netease' in (p.get('bus_name','')+' '+p.get('identity','')).casefold()]


def artwork(url):
    """No network fetch or arbitrary URI execution; native cached/local artwork only."""
    parsed = urlsplit(url or '')
    if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
        return ''
    path = Path(unquote(parsed.path))
    try:
        return str(path) if path.is_file() and path.stat().st_size <= 32*1024*1024 else ''
    except OSError:
        return ''


def selection_path():
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'moonlit/media-selection.json'


def selection_state():
    try:
        state=json.loads(selection_path().read_text())
        return state if isinstance(state,dict) else {}
    except (OSError,ValueError):
        return {}


def save_selection(value):
    path=selection_path();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(prefix='.media-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(value,stream)
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def auto_source(players, pinned, previous):
    # A native user selection, or an explicit choice in our UI, beats defaults.
    buses={p['bus_name'] for p in players}
    if pinned in buses and pinned != previous.get('auto'):
        return pinned
    if previous.get('explicit') in buses:
        return previous['explicit']
    wanted=preferred(players)
    return wanted[0] if wanted else ''


class Bridge:
    def __init__(self):
        import gi
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(self, method, signature=None, values=()):
        params = self.GLib.Variant(signature, values) if signature else None
        return self.bus.call_sync('dev.noctalia.Mpris', '/dev/noctalia/Mpris',
            'dev.noctalia.Mpris', method, params, None,
            self.Gio.DBusCallFlags.NONE, 1200, None).unpack()

    def accepted(self, method, signature=None, values=()):
        result = self.call(method, signature, values)
        if not result or result[0] is not True:
            raise ValueError('The player did not accept this action')

    def snapshot(self):
        players = self.call('GetPlayers')[0]
        prefs = self.call('GetPlayerPreferences')
        wanted = preferred(players)
        if list(prefs[2]) != wanted:
            self.accepted('SetPreferredPlayers', '(as)', (wanted,))
        previous=selection_state()
        pinned=prefs[1] if prefs[0] else ''
        selected=auto_source(players,pinned,previous)
        if selected and (not prefs[0] or prefs[1] != selected):
            self.accepted('SetActivePlayerPreference','(s)',(selected,))
        # A changed native pin is a newer user choice than our saved one. Record
        # it even when no write to Noctalia was needed, so hot removal cannot
        # resurrect an older explicit choice from another interface.
        buses={p['bus_name'] for p in players}
        if pinned in buses and pinned != previous.get('auto'):
            next_selection={'explicit':pinned}
        elif selected and previous.get('explicit') == selected:
            next_selection={'explicit':selected}
        else:
            next_selection={'auto':selected} if selected else {}
        if next_selection != previous:
            save_selection(next_selection)
        found, p = self.call('GetActivePlayer')
        out = {'player':'','title':'Nothing playing','artist':'Choose a source to begin',
               'album':'','status':'Stopped','position':0,'length':0,'art':'',
               'can_play':False,'can_pause':False,'can_next':False,'can_previous':False,
               'can_seek':False,'queue_supported':False,'error':'',
               'players':[{'bus':x['bus_name'],'name':text(x.get('identity') or x['bus_name'])} for x in players]}
        if not found:
            return out
        out.update(player=p['bus_name'],title=text(p.get('title')) or 'Untitled track',
                   artist=text(' · '.join(p.get('artists',[]))) or text(p.get('identity')),
                   album=text(p.get('album')),status=p.get('playback_status','Stopped'),
                   position=max(0,p.get('position_us',0)/1e6),length=max(0,p.get('length_us',0)/1e6),
                   art=artwork(p.get('art_url','')),source=text(p.get('identity')),
                   can_play=p.get('can_play',False),can_pause=p.get('can_pause',False),
                   can_next=p.get('can_go_next',False),can_previous=p.get('can_go_previous',False),
                   can_seek=p.get('can_seek',False), pinned=bool(selected or prefs[0]))
        return out

    def action(self, action, value=None):
        if action == 'select':
            buses = [p['bus_name'] for p in self.call('GetPlayers')[0]]
            if value not in buses:
                raise ValueError('This source is no longer available')
            self.accepted('SetActivePlayerPreference','(s)',(value,))
            save_selection({'explicit':value})
        elif action == 'seek':
            p=self.snapshot();seconds=float(value)
            if not p['can_seek'] or not math.isfinite(seconds) or not 0 <= seconds <= p['length']:
                raise ValueError('This source cannot seek to that position')
            if not p.get('player'):
                raise ValueError('No player is currently selected')
            self.accepted('SetPositionPlayer','(sx)',(p['player'],int(seconds*1e6)))
        else:
            p=self.snapshot()
            if not p.get('player'):
                raise ValueError('No player is currently selected')
            method={'toggle':'PlayPausePlayer','next':'NextPlayer','previous':'PreviousPlayer','stop':'StopPlayer'}[action]
            # Pin the transport target to this snapshot: another source appearing
            # between reconciliation and transport cannot receive the command.
            self.accepted(method,'(s)',(p['player'],))
        return self.snapshot()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['snapshot','toggle','next','previous','seek','select','stop'])
    parser.add_argument('value',nargs='?')
    args=parser.parse_args()
    try:
        bridge=Bridge()
        result=bridge.snapshot() if args.action=='snapshot' else bridge.action(args.action,args.value)
    except Exception as error:
        result={'error':text(error), 'player':'','title':'Player unavailable','status':'Stopped','players':[],
                'can_play':False,'can_pause':False,'can_next':False,'can_previous':False,'can_seek':False,
                'position':0,'length':0,'art':'','artist':'','album':'','queue_supported':False}
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result.get('error') else 0

if __name__=='__main__':
    raise SystemExit(main())
