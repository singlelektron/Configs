"""Execute the native Keep awake shortcut without controlling the real desktop."""
import json
from pathlib import Path
import shutil
import subprocess
import tomllib
import unittest

PLUGIN = Path(__file__).resolve().parents[1] / "config/moonlit/plugins/moonlit-controls"


class KeepAwakeTests(unittest.TestCase):
    def test_manifest_and_translations(self):
        manifest = tomllib.loads((PLUGIN / "plugin.toml").read_text())
        self.assertEqual(manifest["id"], "dotfiles/moonlit-controls")
        self.assertEqual(manifest["shortcut"], [{"id": "awake", "entry": "awake.luau"}])
        self.assertEqual(manifest["service"], [{"id": "state", "entry": "state.luau"}])
        translations = [json.loads((PLUGIN / f"translations/{lang}.json").read_text())
                        for lang in ("en", "zh-Hans")]
        self.assertEqual(translations[0].keys(), translations[1].keys())
        self.assertTrue(all(value for catalog in translations for value in catalog.values()))

    @unittest.skipUnless(shutil.which("lua"), "Lua interpreter unavailable")
    def test_actual_shortcut_events_share_the_legacy_flag_without_polling(self):
        script = r'''
local root = arg[1]
local marker, accepted, capability, helperExists = false, true, true, true
local manifestPresent, runtimePresent = true, true
local calls, callbacks, logs = {}, {}, {}
local shared, watchers = {}, {}
local release = "/private/with spaces/'$literal"
local flag = "/run/user/1000/dotfiles-niri/presentation"
local api = {
  state = {
    get = function(key) return shared[key] end,
    set = function(key, value)
      shared[key] = value
      for _, callback in ipairs(watchers[key] or {}) do callback(value) end
    end,
    watch = function(key, callback)
      watchers[key] = watchers[key] or {}
      table.insert(watchers[key], callback)
    end,
  },
  setUpdateInterval = function(interval) assert(interval == 2147483647) end,
  getenv = function(name)
    if name == "MOONLIT_SESSION_MANIFEST" and manifestPresent then return "/private/manifest.json" end
    if name == "XDG_RUNTIME_DIR" and runtimePresent then return "/run/user/1000" end
  end,
  readFile = function(path) assert(path == "/private/manifest.json"); return "manifest" end,
  fileExists = function(path)
    if path == flag then return marker end
    assert(path == release .. "/managed/niri/desktopctl.py")
    return helperExists
  end,
  json = {
    decode = function(raw)
      assert(raw == "manifest")
      return {schema = 1, kind = "moonlit-live-session", phase = "basic", release = release,
        capabilities = capability and {"calendar", "caffeine"} or {"calendar"}}
    end,
    encode = function(value) return value end,
  },
  tr = function(key) return key end,
  log = function(value) table.insert(logs, value) end,
  runAsync = function(argv, callback)
    table.insert(calls, argv)
    if accepted then table.insert(callbacks, callback) end
    return accepted
  end,
}
-- Concatenating a table encodes diagnostics in this test without a JSON library.
api.json.encode = function(value)
  logs.diagnostic = value
  return "encoded"
end
local function serviceEntry()
  local env = setmetatable({noctalia = api}, {__index = _G})
  assert(loadfile(root .. "/state.luau", "t", env))()
  assert(env.update == nil, "relay must have no polling callback")
  return env
end
local service = serviceEntry()
service.onIpc("status", "before shortcut load")
assert(not logs.diagnostic.loaded, "must not claim a shortcut rendered before lazy load")
service.onIpc("refresh", "before shortcut load")
assert(#calls == 0 and shared["moonlit.awake.refresh"] == 1)
local function entry()
  local ui = {}
  local env = setmetatable({noctalia = api, shortcut = {
    setIcon = function(on, off) ui.on, ui.off = on, off end,
    setActive = function(value) ui.active = value end,
    setEnabled = function(value) ui.enabled = value end,
    setLabel = function(value) ui.label = value end,
  }}, {__index = _G})
  assert(loadfile(root .. "/awake.luau", "t", env))()
  assert(env.update == nil, "shortcut must have no polling callback")
  assert(env.onIpc == nil, "5.2.1 does not dispatch shortcut IPC; use service relay")
  return env, ui
end
local env, ui = entry()
assert(not ui.active and ui.enabled and ui.label == "awake.label")
assert(ui.on == "caffeine-on" and ui.off == "caffeine-off")
assert(#calls == 0, "loading must not spawn a process")
marker = true
service.onIpc("refresh", "shortcut")
assert(ui.active and #calls == 0, "external shortcut state must refresh without a subprocess")
service.onIpc("status", "test")
assert(logs.diagnostic.active and logs.diagnostic.available and logs.diagnostic.request == "test")
env.onClick()
assert(not ui.enabled and ui.active, "pending action must not pretend the state changed")
local argv = calls[1]
assert(#argv == 4 and argv[1] == "/usr/bin/python3"
  and argv[2] == release .. "/managed/niri/desktopctl.py"
  and argv[3] == "presentation" and argv[4] == "toggle", "must preserve literal argv")
env.onClick()
service.onIpc("refresh", "while pending")
assert(#calls == 1 and not ui.enabled, "double click/IPC must not release a pending action")
marker = false
callbacks[1]({exitCode = 0})
assert(not ui.active and ui.enabled and ui.label == "awake.label")
env.onClick()
callbacks[2]({exitCode = 1})
assert(not ui.active and ui.enabled and ui.label == "awake.failed")
marker = true
service.onIpc("refresh", "shortcut succeeded")
assert(ui.active and ui.label == "awake.label")
accepted = false
env.onClick()
assert(ui.enabled and ui.active and ui.label == "awake.failed")
accepted = true
env.onClick()
local late = callbacks[#callbacks]
env.onExit()
local oldLabel = ui.label
marker = false
late({exitCode = 0})
service.onIpc("refresh", "after reload")
assert(ui.active and ui.label == oldLabel, "late callback must not mutate a stopped entry")
service.onIpc("status", "unloaded")
assert(not logs.diagnostic.loaded, "stopped shortcut must not leave a stale rendered diagnostic")
local replacement, fresh = entry()
assert(fresh.enabled and not fresh.active and fresh.label == "awake.label", "reload must not strand pending")
service.onExit()
local revision = shared["moonlit.awake.refresh"]
service.onIpc("refresh", "stopped relay")
assert(shared["moonlit.awake.refresh"] == revision)
service = serviceEntry()
marker = true
service.onIpc("refresh", "new relay")
assert(fresh.active, "relay reload must keep updating the still-live shortcut")
service.onIpc("status", "new relay")
assert(logs.diagnostic.loaded and logs.diagnostic.active)
for _, unavailable in ipairs({"capability", "helper", "manifest", "runtime"}) do
  capability, helperExists, manifestPresent, runtimePresent = true, true, true, true
  if unavailable == "capability" then capability = false end
  if unavailable == "helper" then helperExists = false end
  if unavailable == "manifest" then manifestPresent = false end
  if unavailable == "runtime" then runtimePresent = false end
  local disabled, view = entry()
  local count = #calls
  disabled.onClick()
  assert(not view.enabled and not view.active and view.label == "awake.unavailable")
  assert(#calls == count, "unavailable preview must never control the host")
end
print("Keep awake lifecycle and event-only state: PASS")
'''
        result = subprocess.run(["lua", "-", str(PLUGIN)], input=script, text=True,
                                capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("state: PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
