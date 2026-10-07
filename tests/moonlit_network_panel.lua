-- Exercise the actual panel without contacting devices or opening GUI surfaces.
local file = assert(os.getenv("MOONLIT_NETWORK_PANEL"))
local language = assert(os.getenv("MOONLIT_TEST_LANGUAGE"))
local raw = vim.json.decode(table.concat(vim.fn.readfile(vim.fs.dirname(file) .. "/translations/" .. language .. ".json"), "\n"))
local catalog = {}
local function flatten(value, prefix)
  for key, item in pairs(value) do
    local full = prefix == "" and key or prefix .. "." .. key
    if type(item) == "table" then flatten(item, full) else catalog[full] = item end
  end
end
flatten(raw, "")
local function tr(key, values)
  assert(type(catalog[key]) == "string", "missing translation: " .. key)
  return (catalog[key]:gsub("{([%w_]+)}", function(name) return tostring(assert(values[name])) end))
end
local pending, tree, renders, accepted = nil, nil, 0, true
noctalia = {
  tr = tr, pluginDir = function() return "/test" end,
  json = {decode = function(text) local ok, result = pcall(vim.json.decode, text); return ok and result or nil end},
  runAsync = function(_, callback) if accepted then pending = callback end; return accepted end,
}
ui = setmetatable({}, {__index = function(_, name) return function(props, children) return {kind = name, props = props, children = children} end end})
panel = {render = function(value) tree = value; renders = renders + 1 end, close = function() end}
local function texts(node, out)
  out = out or {}
  if node.props.text then table.insert(out, node.props.text) end
  for _, child in ipairs(node.children or {}) do texts(child, out) end
  return table.concat(out, "\n")
end
dofile(file)
onOpen()
assert(texts(tree):find(tr("reading"), 1, true))
local snapshot = vim.json.encode({devices = {{interface = "test0", type = "ethernet", state = "connected"}}, routes = {}, errors = {}, at = "12:00"})
pending({exitCode = 0, stdout = snapshot})
assert(texts(tree):find(tr("state.connected"), 1, true))
assert(texts(tree):find(tr("wifi-settings"), 1, true))
refresh()
pending({exitCode = 1, stdout = snapshot, stderr = "reader failed"})
assert(texts(tree):find(tr("read-error"), 1, true))
assert(texts(tree):find("reader failed", 1, true), "diagnostic must remain intact")
assert(not texts(tree):find("test0", 1, true), "failed helper must not claim successful device data")
refresh()
local late = pending
onClose()
local before = renders
late({exitCode = 0, stdout = snapshot})
assert(renders == before, "closed panel must ignore late completion")
accepted = false
onOpen()
assert(texts(tree):find(tr("start-error"), 1, true))
accepted = true
refresh()
pending({exitCode = 0, stdout = snapshot})
assert(texts(tree):find("test0", 1, true), "failed refresh must remain recoverable")
print("Moonlit network panel localization, errors and lifecycle: PASS")
vim.cmd("qa!")
