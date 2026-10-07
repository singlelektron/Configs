"""Luau service contract: no poll/spawn loop, safe stream args and state dedup."""
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import unittest

PLUGIN = Path(__file__).resolve().parents[1] / "config/moonlit/plugins/moonlit-music"


class ServiceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("lua"), "Lua interpreter unavailable")
    def test_service_stream_ownership_dedup_control_and_quoted_paths(self):
        script = r'''
local service = arg[1]
local state, watchers, published = {}, {}, {}
local updates, streams, callback, command = 0, 0, nil, nil
local controls, diagnostics, logs = {}, {}, {}
table.clone = function(t) local r = {}; for k,v in pairs(t) do r[k]=v end; return r end
require = function() return {empty={player="",status="Stopped"},current=function() return state["moonlit.media"] end} end
noctalia = {
 state={get=function(k) return state[k] end,
   watch=function(k,cb) watchers[k]=cb end,
   set=function(k,v) state[k]=v; if k=="moonlit.media" then table.insert(published,v) end end},
 nowMs=function() return 100 end,
 tr=function(key) return key end,
 log=function(value) table.insert(logs,value) end,
 pluginDir=function() return "/tmp/plugin ' $cash ; literal" end,
 pluginDataDir=function() return "/tmp/data ' $cash ; literal" end,
 writeFile=function(path,text) table.insert(controls,text); return true end,
 renameFile=function() return true end,
 removeFile=function() return true end,
 setUpdateInterval=function(value) updates=value end,
 runAsync=function() error("Service must not spawn short-lived polling processes") end,
 runStream=function(cmd,cb) streams=streams+1;command=cmd;callback=cb;return true end,
 json={encode=function(value) if value.diagnostic then table.insert(diagnostics,value);return "encoded" end;return value end,
   decode=function(value)
     if value=="initial" then return {player="one",status="Paused",position=5,players={{bus="one"}}} end
     if value=="same" then return {players={{bus="one"}},position=5,status="Paused",player="one"} end
     if value=="position" then return {player="one",status="Paused",position=6,players={{bus="one"}}} end
     if value=="exit" then return {_bridge_exit=true} end
     return nil
   end}
}
dofile(service)
assert(streams==1 and updates>60000 and update==nil)
assert(#controls==1 and controls[1].visible==false and controls[1].refresh==true)
callback("initial"); callback("same"); assert(#published==1)
callback("position"); assert(#published==2 and published[2].position==6)
state["moonlit.visible.room"]=true;watchers["moonlit.visible.room"]()
assert(controls[#controls].visible==true and controls[#controls].refresh==false)
watchers["moonlit.refresh"]();assert(controls[#controls].refresh==true)
assert(streams==1)
callback("exit");assert(#published==3 and published[3].player=="" and published[3].bridge_stopped==true)
local written=#controls
onIpc("status","check-dead")
assert(#diagnostics==1 and diagnostics[1].stream_running==false and diagnostics[1].media==published[3])
assert(diagnostics[1].request=="check-dead" and diagnostics[1].visible_room==true)
assert(diagnostics[1].command_pending==false and diagnostics[1].command_owner=="")
assert(#logs==1 and #controls==written and #published==3 and streams==1)
onIpc("unsupported", "ignored");assert(#logs==1)
assert(streams==1)
watchers["moonlit.restart"]();assert(streams==2)
callback("initial");assert(#published==4 and published[4].player=="one")
onIpc("status","check-alive");assert(diagnostics[2].stream_running==true and diagnostics[2].media.player=="one")
onExit(); callback("exit");assert(#published==4)
print(command)
'''
        result = subprocess.run(["lua", "-", str(PLUGIN / "service.luau")], input=script,
                                text=True, capture_output=True, check=True)
        # shlex with whitespace_split preserves punctuation within literal paths.
        lexer = shlex.shlex(result.stdout.strip(), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
        self.assertEqual(tokens, ["python3", "-u", "/tmp/plugin ' $cash ; literal/media_watch.py",
            "--control-file", "/tmp/data ' $cash ; literal/media-control.json", "--owner-pid", "$PPID", ";",
            "printf", "%s\\n", '{"_bridge_exit":true}'])


    def test_music_catalogs_cover_all_static_and_status_keys(self):
        en = json.loads((PLUGIN / "translations/en.json").read_text())
        zh = json.loads((PLUGIN / "translations/zh-Hans.json").read_text())
        self.assertEqual(set(en), set(zh))
        keys = set()
        for path in PLUGIN.glob("*.luau"):
            keys.update(re.findall(r'noctalia\.tr\("([^"\n]+)"\)', path.read_text()))
        keys.update("status." + status for status in ("Playing", "Paused", "Stopped"))
        keys.add("source.status")
        self.assertTrue(keys <= set(en), keys-set(en))
        for key in keys:
            self.assertEqual(set(re.findall(r"\{\w+\}", en[key])), set(re.findall(r"\{\w+\}", zh[key])))


if __name__ == "__main__":
    unittest.main()
