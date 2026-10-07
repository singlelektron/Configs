-- Exercise the actual Luau widget in Neovim's Lua VM; this widget uses plain Lua.
-- Native process execution and D-Bus are replaced with controlled test doubles.
local pending, accepted, response = nil, true, nil
local text, tooltip = "", ""
noctalia = {
  setUpdateInterval = function() end,
  pluginDir = function() return "/isolated/plugin" end,
  json = { decode = function() return response end },
  runAsync = function(_, callback)
    if accepted then pending = callback end
    return accepted
  end,
}
barWidget = {
  setText = function(value) text = value end,
  setGlyph = function() end,
  setTooltip = function(value) tooltip = value end,
}

dofile(assert(os.getenv("MOONLIT_UPDATES_WIDGET")))
assert(pending, "initial status read was not scheduled")
response = {status = "ok", count = 4}
pending({exitCode = 0, stdout = "json"})
assert(text == "Updates · 4")

accepted = false
onClick()
assert(text == "Updates · !", "spawn rejection must not stick at Checking")
assert(tooltip:find("Could not start update helper", 1, true))

accepted = true
pending = nil
update()
assert(pending, "a rejected spawn must allow the next refresh")
response = nil
pending({exitCode = 0, stdout = "not json"})
assert(text == "Updates · !")
assert(tooltip:find("invalid status", 1, true))

update()
response = {status = "ok"}
pending({exitCode = 0, stdout = "json"})
assert(text == "Updates · !", "missing count must not become zero updates")

update()
response = {status = "ok", count = 0}
pending({exitCode = 1, stdout = "json", stderr = "helper crashed"})
assert(text == "Updates · !", "failed process must not show successful zero")

update()
response = {status = "ok", count = 0}
pending({exitCode = 0, stdout = "json"})
assert(text == "Updates · 0", "real successful zero must remain distinguishable")
print("Moonlit updates widget async failure and recovery: PASS")
vim.cmd("qa!")
