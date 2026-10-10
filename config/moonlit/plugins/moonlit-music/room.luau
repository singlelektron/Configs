local M = require("./common.luau")
M.commandOwner = "room"
local visible = false
local seekPreview = nil

local function render()
  if not visible then return end
  local data = M.current()
  local length = tonumber(data.length) or 0
  local position = tonumber(data.position) or 0
  local seekable = data.can_seek == true and length > 0
  local artwork = M.artwork(data, 348)
  local queueText = data.queue_supported == true
    and noctalia.tr("collection.queue_preview")
    or noctalia.tr("collection.no_queue")

  panel.render(ui.column({ padding = 30, gap = 18, radius = 30, fill = "surface/0.94", border = "primary/0.2", borderWidth = 1 }, {
    ui.row({ gap = 12, align = "center" }, {
      ui.glyph({ name = "flower", size = 24, color = "primary" }),
      ui.column({ gap = 4, flexGrow = 1 }, {
        ui.label({ text = noctalia.tr("room.title"), fontSize = 24, fontWeight = "semibold" }),
        ui.label({ text = noctalia.tr("room.subtitle"), fontSize = 12, color = "on_surface_variant" }),
      }),
      ui.column({ gap = 5, width = 242 }, {
        ui.label({ text = noctalia.tr("source.status", { status = noctalia.tr("status." .. (data.status or "Stopped")) }), fontSize = 10, color = "primary" }),
        M.sourcePicker(data, 242),
      }),
      ui.button({ text = noctalia.tr("controls.light"), glyph = "music", variant = "ghost", controlSize = "sm",
        onClick = function() noctalia.togglePanel("dotfiles/moonlit-music:controls") end }),
      ui.button({ glyph = "close", variant = "ghost", width = 34, height = 34, tooltip = noctalia.tr("room.close"), onClick = function() panel.close() end }),
    }),
    ui.separator({ color = "primary/0.16", thickness = 1 }),
    ui.row({ gap = 38, align = "start" }, {
      ui.column({ width = 438, gap = 18, align = "center" }, {
        ui.row({ key = "album-case", width = 426, height = 409, padding = 18, gap = 12, align = "center",
          radius = 20, fill = "secondary/0.09", border = "primary/0.32", borderWidth = 1 }, {
          ui.column({ width = 12, height = 363, radius = 4, fill = "primary/0.13", border = "primary/0.22", borderWidth = 1 }, {}),
          ui.column({ gap = 10, align = "center" }, {
            artwork,
            ui.row({ width = 348, align = "center", justify = "space_between" }, {
              ui.label({ text = M.artPath(data) and noctalia.tr("art.source") or noctalia.tr("art.unavailable"), fontSize = 10, color = "on_surface_variant" }),
              ui.glyph({ name = "disc", size = 14, color = "secondary" }),
            }),
          }),
        }),
        ui.label({ text = M.text(data.album, noctalia.tr("state.no_album")), fontSize = 13,
          color = "on_surface_variant", maxWidth = 406, maxLines = 2, textAlign = "center" }),
      }),
      ui.column({ width = 548, gap = 24, paddingV = 8 }, {
        ui.column({ gap = 10 }, {
          ui.label({ text = M.title(data), fontSize = 30, fontWeight = "semibold", maxWidth = 536, maxLines = 2 }),
          ui.label({ text = M.artist(data), fontSize = 17, color = "on_surface_variant", maxWidth = 536, maxLines = 1 }),
        }),
        ui.column({ gap = 5 }, {
          ui.slider({ key = "seek", min = 0, max = math.max(length, 1), step = 1,
            value = seekPreview or math.min(position, math.max(length, 1)), enabled = seekable, controlSize = "sm",
            onChange = function(value) seekPreview = tonumber(value) end,
            onDragEnd = function()
              if seekPreview and seekable then M.command("seek", seekPreview) end
              seekPreview = nil
            end }),
          ui.row({ justify = "space_between" }, {
            ui.label({ text = M.time(position), fontSize = 12, color = "on_surface_variant" }),
            ui.label({ text = length > 0 and M.time(length) or noctalia.tr("state.no_duration"), fontSize = 12, color = "on_surface_variant" }),
          }),
          ui.label({ text = seekable and "" or noctalia.tr("transport.no_seek"), visible = not seekable,
            fontSize = 11, color = "on_surface_variant" }),
        }),
        M.controls(data, true),
        ui.column({ gap = 9, padding = 16, radius = 16, fill = "secondary/0.07", border = "secondary/0.15", borderWidth = 1 }, {
          ui.row({ gap = 8, align = "center" }, {
            ui.glyph({ name = "list", size = 17, color = "secondary" }),
            ui.label({ text = noctalia.tr("collection.title"), fontSize = 13, fontWeight = "semibold" }),
          }),
          ui.label({ text = queueText, fontSize = 12, color = "on_surface_variant", maxWidth = 506, maxLines = 3 }),
          ui.label({ text = noctalia.tr("collection.no_lyrics"), fontSize = 11, color = "on_surface_variant", maxWidth = 506, maxLines = 2 }),
        }),
      }),
    }),
    M.errorRow(data, 1056, true),
    ui.row({ align = "center", justify = "space_between" }, {
      ui.label({ text = noctalia.tr("room.lifecycle"), fontSize = 11, color = "on_surface_variant" }),
      ui.label({ text = noctalia.tr("room.preview"), fontSize = 11, color = "secondary" }),
    }),
  }))
end

M.watch(render)
function onOpen()
  visible = true
  seekPreview = nil
  noctalia.state.set("moonlit.visible.room", true)
  noctalia.state.set("moonlit.refresh", noctalia.nowMs())
  render()
end
function onClose()
  visible = false
  seekPreview = nil
  -- Release the large artwork node while retaining the cheap shared media service.
  panel.render(ui.column({}, {}))
  noctalia.state.set("moonlit.visible.room", false)
  panel.setWantsSecondTicks(false)
  panel.setNeedsFrameTick(false)
end
function onExit()
  M.releaseCommand()
  noctalia.state.set("moonlit.visible.room", false)
end
