"""Execute actual music entries: reload must not strand or steal command ownership."""
from pathlib import Path
import shutil
import subprocess
import unittest

PLUGIN = Path(__file__).resolve().parents[1] / "config/moonlit/plugins/moonlit-music"


class PendingCommandTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("lua"), "Lua interpreter unavailable")
    def test_entry_exit_releases_only_its_request_and_late_callbacks_are_ignored(self):
        script = r'''
local root = arg[1]
local state, callbacks, accepted = {}, {}, true
local api = {
  state = {get = function(key) return state[key] end,
    set = function(key, value) state[key] = value end, watch = function() end},
  pluginDir = function() return root end,
  nowMs = function() return 100 end, -- reloads in the same millisecond still need unique tokens
  tr = function(key) return key end,
  fileExists = function() return false end,
  json = {decode = function(raw) return raw == "error" and {error = "player rejected command"} or nil end},
  runAsync = function(_, callback)
    if accepted then table.insert(callbacks, callback) end
    return accepted
  end,
}
local function entry(name)
  local env = setmetatable({noctalia = api}, {__index = _G})
  env.ui = setmetatable({}, {__index = function() return function(...) return {...} end end})
  env.barWidget = {render = function() end, setTooltip = function() end}
  env.panel = {render = function() end, setWantsSecondTicks = function() end, setNeedsFrameTick = function() end}
  local module = assert(loadfile(root .. "/common.luau", "t", env))()
  env.require = function() return module end
  assert(loadfile(root .. "/" .. name .. ".luau", "t", env))()
  assert(type(env.onExit) == "function", name .. " has no lifecycle cleanup")
  return module, env
end
for _, name in ipairs({"bar", "controls", "room"}) do
  local old, oldEntry = entry(name)
  old.command("toggle")
  local oldToken, late = state["moonlit.command.owner"], callbacks[#callbacks]
  assert(state["moonlit.command.pending"] == true)
  assert(oldToken:match("^" .. name .. ":"), "entry owner missing")
  local foreign, foreignEntry = entry(name == "bar" and "room" or "bar")
  foreign.command("next")
  assert(callbacks[#callbacks] == late, "another entry must not overlap a pending command")
  foreignEntry.onExit()
  assert(state["moonlit.command.owner"] == oldToken and state["moonlit.command.pending"] == true,
    "unrelated exit must not release the active request")
  if oldEntry.onClose then
    oldEntry.onClose()
    assert(state["moonlit.command.pending"] == true, "merely closing a panel must retain its pending command")
  end
  oldEntry.onExit()
  assert(state["moonlit.command.pending"] == false and state["moonlit.command.owner"] == "")
  local replacement = entry(name)
  replacement.command("toggle")
  local newToken = state["moonlit.command.owner"]
  assert(newToken ~= oldToken, "reloaded entry reused a token")
  late({exitCode = 1, stdout = "error"})
  oldEntry.onExit()
  assert(state["moonlit.command.owner"] == newToken and state["moonlit.command.pending"] == true)
  assert(state["moonlit.command.error"] == "", "late failure overwrote the new command")
  callbacks[#callbacks]({exitCode = 0, stdout = ""})
  assert(state["moonlit.command.pending"] == false and state["moonlit.command.owner"] == "")
  replacement.command("toggle")
  callbacks[#callbacks]({exitCode = 1, stdout = "error"})
  assert(state["moonlit.command.pending"] == false)
  assert(state["moonlit.command.error"] == "player rejected command")
  accepted = false
  replacement.command("toggle")
  assert(state["moonlit.command.pending"] == false and state["moonlit.command.owner"] == "")
  accepted = true
end
print("Music command ownership across bar/controls/room reloads: PASS")
'''
        result = subprocess.run(["lua", "-", str(PLUGIN)], input=script, text=True,
                                capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("reloads: PASS", result.stdout)
