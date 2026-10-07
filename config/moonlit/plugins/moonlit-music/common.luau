local M = {}
local ownedRequest = nil

M.empty = {
  player = "", title = "", artist = "", album = "", status = "Stopped",
  position = 0, length = 0, art = "", players = {}, can_play = false,
  can_pause = false, can_next = false, can_previous = false, can_seek = false,
  queue_supported = false, error = "",
}

function M.current()
  return noctalia.state.get("moonlit.media") or M.empty
end

function M.text(value, fallback)
  if type(value) == "string" and value ~= "" then return value end
  return fallback
end

function M.title(data)
  if data.player == nil or data.player == "" then return noctalia.tr("state.nothing") end
  return M.text(data.title, noctalia.tr("state.no_title"))
end

function M.source(data)
  for _, source in ipairs(data.players or {}) do
    if source.bus == data.player then return M.text(source.name, source.bus) end
  end
  return M.text(data.player, noctalia.tr("state.no_player"))
end

function M.artist(data)
  if data.player == nil or data.player == "" then return noctalia.tr("state.start") end
  return M.text(data.artist, noctalia.tr("state.no_artist"))
end

function M.time(value)
  local seconds = math.max(0, math.floor(tonumber(value) or 0))
  return string.format("%d:%02d", math.floor(seconds / 60), seconds % 60)
end

function M.artPath(data)
  local path = M.text(data.art, "")
  if string.sub(path, 1, 7) == "file://" then path = noctalia.string.urlDecode(string.sub(path, 8)) end
  if string.sub(path, 1, 1) == "/" and noctalia.fileExists(path) then return path end
  return nil
end

function M.releaseCommand()
  if ownedRequest and noctalia.state.get("moonlit.command.owner") == ownedRequest then
    noctalia.state.set("moonlit.command.owner", "")
    noctalia.state.set("moonlit.command.pending", false)
  end
  ownedRequest = nil
end

function M.command(action, argument)
  if noctalia.state.get("moonlit.command.pending") == true then return end
  -- Entry-local ownership survives shared state updates, while the serial stored
  -- outside the VM prevents a reloaded entry from reusing its old request token.
  local serial = (tonumber(noctalia.state.get("moonlit.command.serial")) or 0) + 1
  local request = (M.commandOwner or "music") .. ":" .. tostring(serial)
  noctalia.state.set("moonlit.command.serial", serial)
  ownedRequest = request
  noctalia.state.set("moonlit.command.owner", request)
  local argv = { "python3", noctalia.pluginDir() .. "/media_bridge.py", action }
  if argument ~= nil then table.insert(argv, tostring(argument)) end
  noctalia.state.set("moonlit.command.pending", true)
  noctalia.state.set("moonlit.command.error", "")
  local accepted = noctalia.runAsync(argv, function(result)
    if ownedRequest ~= request or noctalia.state.get("moonlit.command.owner") ~= request then return end
    if result.exitCode ~= 0 then
      local response = noctalia.json.decode(result.stdout or "")
      local detail = type(response) == "table" and response.error or nil
      noctalia.state.set("moonlit.command.error", M.text(detail, M.text(result.stderr, "The player did not accept this action.")))
    end
    M.releaseCommand()
    noctalia.state.set("moonlit.refresh", noctalia.nowMs())
  end)
  if not accepted then
    noctalia.state.set("moonlit.command.error", "Could not start the media bridge.")
    M.releaseCommand()
  end
end

function M.canToggle(data)
  if data.status == "Playing" then return data.can_pause == true end
  return data.can_play == true
end

function M.controls(data, large)
  local pending = noctalia.state.get("moonlit.command.pending") == true
  return ui.row({ gap = large and 14 or 8, align = "center", justify = "center" }, {
    ui.button({ key = "previous", glyph = "media-prev", glyphSize = large and 23 or 18,
      width = large and 52 or 38, height = large and 52 or 38, variant = "ghost",
      enabled = data.can_previous == true and not pending, tooltip = data.can_previous and noctalia.tr("transport.previous") or noctalia.tr("transport.no_previous"),
      onClick = function() M.command("previous") end }),
    ui.button({ key = "toggle", glyph = data.status == "Playing" and "media-pause" or "media-play",
      glyphSize = large and 27 or 21, width = large and 64 or 46, height = large and 56 or 42,
      variant = "primary", enabled = M.canToggle(data) and not pending,
      tooltip = data.status == "Playing" and noctalia.tr("transport.pause") or noctalia.tr("transport.play"),
      onClick = function() M.command("toggle") end }),
    ui.button({ key = "next", glyph = "media-next", glyphSize = large and 23 or 18,
      width = large and 52 or 38, height = large and 52 or 38, variant = "ghost",
      enabled = data.can_next == true and not pending, tooltip = data.can_next and noctalia.tr("transport.next") or noctalia.tr("transport.no_next"),
      onClick = function() M.command("next") end }),
  })
end

function M.sourcePicker(data, width)
  local names, buses = {}, {}
  local selected = 0
  for index, source in ipairs(data.players or {}) do
    table.insert(names, M.text(source.name, source.bus))
    table.insert(buses, source.bus)
    if source.bus == data.player then selected = index - 1 end
  end
  if #names == 0 then names = { noctalia.tr("state.no_player") } end
  return ui.select({ key = "source", options = names, selectedIndex = selected,
    width = width, controlSize = "sm", enabled = #buses > 0,
    onChange = function(value)
      local bus = buses[(tonumber(value) or -1) + 1]
      if bus then M.command("select", bus) end
    end })
end

function M.artwork(data, size)
  local path = M.artPath(data)
  if path then
    return ui.image({ key = "album-art", path = path, width = size, height = size,
      radius = 8, fit = "contain", border = "primary/0.24", borderWidth = 1 })
  end
  return ui.column({ key = "missing-art", width = size, height = size, align = "center", justify = "center",
    gap = 18, radius = 8, fill = "surface_variant/0.5", border = "secondary/0.2", borderWidth = 1 }, {
    ui.glyph({ name = "disc", size = math.floor(size * 0.35), color = "secondary/0.7" }),
    ui.label({ text = noctalia.tr("art.none"), fontSize = size > 100 and 16 or 10, color = "on_surface_variant" }),
  })
end

function M.error(data)
  return M.text(noctalia.state.get("moonlit.command.error"), M.text(data.error, ""))
end

function M.errorRow(data, width, large)
  local err = M.error(data)
  return ui.row({ gap = 12, align = "center", visible = err ~= "" }, {
    ui.label({ text = err, fontSize = large and 12 or 11, color = "error", maxWidth = width,
      flexGrow = 1, maxLines = 2 }),
    ui.button({ text = noctalia.tr("bridge.reconnect"), visible = data.bridge_stopped == true,
      variant = "ghost", controlSize = "sm", onClick = function()
        noctalia.state.set("moonlit.restart", noctalia.nowMs())
      end }),
  })
end

function M.watch(render)
  noctalia.state.watch("moonlit.media", function() render() end)
  noctalia.state.watch("moonlit.command.pending", function() render() end)
  noctalia.state.watch("moonlit.command.error", function() render() end)
end

return M
