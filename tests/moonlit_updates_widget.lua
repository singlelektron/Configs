-- Exercise the actual Luau widget in Neovim's Lua VM; this widget uses plain Lua.
-- Native process execution and D-Bus are replaced with controlled test doubles.
local pending, accepted, response = nil, true, nil
local text, tooltip = "", ""
local widget = assert(os.getenv("MOONLIT_UPDATES_WIDGET"))
local language = os.getenv("MOONLIT_TEST_LANGUAGE") or "en"
local catalogPath = vim.fs.dirname(widget) .. "/translations/" .. language .. ".json"
local catalog = vim.json.decode(table.concat(vim.fn.readfile(catalogPath), "\n"))
local function tr(key, values)
  assert(type(catalog[key]) == "string", "missing translation: " .. key)
  return (catalog[key]:gsub("{([%w_]+)}", function(name) return tostring(assert(values[name])) end))
end
noctalia = {
  setUpdateInterval = function() end,
  pluginDir = function() return "/isolated/plugin" end,
  getSetting = function() return language end,
  tr = tr,
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

dofile(widget)
assert(pending, "initial status read was not scheduled")
response = {status = "ok", count = 4}
pending({exitCode = 0, stdout = "json"})
assert(text == tr("count", {count = 4}))

accepted = false
onClick()
assert(text == tr("count", {count = "!"}), "spawn rejection must not stick at Checking")
assert(tooltip:find(tr("start-error"), 1, true))

accepted = true
pending = nil
update()
assert(pending, "a rejected spawn must allow the next refresh")
response = nil
pending({exitCode = 0, stdout = "not json"})
assert(text == tr("count", {count = "!"}))
assert(tooltip:find(tr("invalid-status"), 1, true))

update()
response = {status = "ok"}
pending({exitCode = 0, stdout = "json"})
assert(text == tr("count", {count = "!"}), "missing count must not become zero updates")

update()
response = {status = "ok", count = 0}
pending({exitCode = 1, stdout = "json", stderr = "helper crashed"})
assert(text == tr("count", {count = "!"}), "failed process must not show successful zero")

update()
response = {status = "ok", count = 0, error = ""}
pending({exitCode = 0, stdout = "json"})
assert(text == tr("count", {count = 0}), "real successful zero must remain distinguishable")
assert(tooltip:find(tr("no-upgrade"), 1, true), "empty diagnostic must not hide no-upgrade explanation")
print("Moonlit updates widget async failure and recovery: PASS")
vim.cmd("qa!")
