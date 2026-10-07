local visible, busy, generation = false, false, 0
local data = {devices = {}, routes = {}, errors = {}}
local deviceStates = {connected = "connected", disconnected = "disconnected", unavailable = "unavailable",
  unmanaged = "unmanaged", connecting = "connecting", disconnecting = "disconnecting",
  ["connected (externally)"] = "connected-external", ["connecting (prepare)"] = "connecting",
  ["connecting (configuring)"] = "connecting", ["connecting (need authentication)"] = "auth",
  ["connecting (getting IP configuration)"] = "connecting", failed = "failed"}
local function label(text, color, size)
  return ui.label({text = text, color = color or "on_surface", fontSize = size or 14, maxLines = 3})
end
local function render()
  local rows = {label(noctalia.tr("title"), "primary", 25), label(noctalia.tr("subtitle"), "on_surface_variant")}
  for _, device in ipairs(data.devices or {}) do
    table.insert(rows, ui.row({gap = 12, padding = 14, radius = 12, fill = "surface_variant/0.65", align = "center"}, {
      ui.glyph({name = device.type == "wifi" and "wifi" or "ethernet", size = 22, color = "secondary"}),
      ui.column({gap = 3, flexGrow = 1}, {label(device.interface), label(noctalia.tr("type." .. device.type), "on_surface_variant", 12)}),
      label(deviceStates[device.state] and noctalia.tr("state." .. deviceStates[device.state]) or device.state, "on_surface_variant")
    }))
  end
  if #(data.devices or {}) == 0 then table.insert(rows, label(noctalia.tr("no-devices"), "on_surface_variant")) end
  table.insert(rows, label(noctalia.tr("routes-title"), "secondary", 17))
  for _, route in ipairs(data.routes or {}) do
    local metric = route.metric ~= nil and tostring(route.metric) or noctalia.tr("implicit")
    local flags = #(route.flags or {}) > 0 and " · " .. table.concat(route.flags, ", ") or ""
    table.insert(rows, label(route.family .. " · " .. route.interface .. " → " .. route.gateway ..
      "\n" .. noctalia.tr("route", {metric = metric, routeTable = tostring(route.table)}) .. flags, "on_surface_variant"))
  end
  if #(data.routes or {}) == 0 then table.insert(rows, label(noctalia.tr("no-routes"), "on_surface_variant")) end
  for _, err in ipairs(data.errors or {}) do table.insert(rows, label(err, "error", 12)) end
  table.insert(rows, label(noctalia.tr("footnote", {at = data.at or noctalia.tr("not-refreshed")}), "on_surface_variant", 12))
  table.insert(rows, ui.row({gap = 10}, {
    ui.button({text = noctalia.tr(busy and "reading" or "refresh"), glyph = "refresh", enabled = not busy, onClick = "refresh"}),
    ui.button({text = noctalia.tr("wifi-settings"), glyph = "wifi", variant = "primary", onClick = "openSettings"}),
    ui.button({text = noctalia.tr("close"), variant = "ghost", onClick = "close"})
  }))
  panel.render(ui.scroll({gap = 14, padding = 24}, rows))
end
function refresh()
  if busy then return end
  busy = true
  local token = generation
  local accepted = noctalia.runAsync({"python3", noctalia.pluginDir() .. "/network.py"}, function(result)
    if token ~= generation or not visible then return end
    busy = false
    local ok, parsed = pcall(noctalia.json.decode, result.stdout or "")
    if result.exitCode ~= 0 or result.timedOut or result.stdoutTruncated or not ok or type(parsed) ~= "table" then
      local detail = type(result.stderr) == "string" and result.stderr ~= "" and " · " .. result.stderr or ""
      data = {devices = {}, routes = {}, errors = {noctalia.tr("read-error") .. detail}}
    else
      data = parsed
    end
    render()
  end)
  if not accepted then busy = false; data.errors = {noctalia.tr("start-error")} end
  render()
end
function onOpen() visible = true; generation = generation + 1; busy = false; refresh() end
function onClose() visible = false; generation = generation + 1; busy = false end
function openSettings() noctalia.runAsync({"noctalia", "msg", "panel-open", "control-center", "network"}) end
function close() panel.close() end
