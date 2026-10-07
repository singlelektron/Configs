local visible, busy, generation = false, false, 0
local data = {devices = {}, routes = {}, errors = {}, at = "Not refreshed"}
local function label(text, color, size)
  return ui.label({text = text, color = color or "on_surface", fontSize = size or 14, maxLines = 3})
end
local function render()
  local rows = {label("Network overview", "primary", 25), label("Ethernet · Wi-Fi · default routes", "on_surface_variant")}
  for _, device in ipairs(data.devices or {}) do
    table.insert(rows, ui.row({gap = 12, padding = 14, radius = 12, fill = "surface_variant/0.65", align = "center"}, {
      ui.glyph({name = device.type == "wifi" and "wifi" or "ethernet", size = 22, color = "secondary"}),
      ui.column({gap = 3, flexGrow = 1}, {label(device.interface), label(device.type, "on_surface_variant", 12)}),
      label(device.state, "on_surface_variant")
    }))
  end
  if #(data.devices or {}) == 0 then table.insert(rows, label("No Ethernet / Wi-Fi state reported", "on_surface_variant")) end
  table.insert(rows, label("Default routes · all routing tables", "secondary", 17))
  for _, route in ipairs(data.routes or {}) do
    local metric = route.metric ~= nil and tostring(route.metric) or "implicit"
    local flags = #(route.flags or {}) > 0 and " · " .. table.concat(route.flags, ", ") or ""
    table.insert(rows, label(route.family .. " · " .. route.interface .. " → " .. route.gateway ..
      "\nmetric " .. metric .. " · table " .. tostring(route.table) .. flags, "on_surface_variant"))
  end
  if #(data.routes or {}) == 0 then table.insert(rows, label("No default route reported", "on_surface_variant")) end
  for _, err in ipairs(data.errors or {}) do table.insert(rows, label(err, "error", 12)) end
  table.insert(rows, label("Routing policy may choose a different table for a specific destination.\nRead-only snapshot · " .. (data.at or ""), "on_surface_variant", 12))
  table.insert(rows, ui.row({gap = 10}, {
    ui.button({text = busy and "Reading…" or "Refresh", glyph = "refresh", enabled = not busy, onClick = "refresh"}),
    ui.button({text = "Wi-Fi settings", glyph = "wifi", variant = "primary", onClick = "openSettings"}),
    ui.button({text = "Close", variant = "ghost", onClick = "close"})
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
    data = ok and type(parsed) == "table" and parsed or {devices = {}, routes = {}, errors = {"Unable to read network state"}}
    render()
  end)
  if not accepted then busy = false; data.errors = {"Could not start network reader"} end
  render()
end
function onOpen() visible = true; generation += 1; busy = false; refresh() end
function onClose() visible = false; generation += 1; busy = false end
function openSettings() noctalia.runAsync({"noctalia", "msg", "panel-open", "control-center", "network"}) end
function close() panel.close() end
