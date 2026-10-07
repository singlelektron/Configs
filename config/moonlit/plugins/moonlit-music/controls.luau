local M = require("./common.luau")
M.commandOwner = "controls"
local visible = false

local function render()
  if not visible then return end
  local data = M.current()
  local length = tonumber(data.length) or 0
  local position = tonumber(data.position) or 0
  panel.render(ui.column({ gap = 16, padding = 22, fill = "surface/0.94", radius = 24 }, {
    ui.row({ gap = 10, align = "center" }, {
      ui.glyph({ name = "flower", size = 20, color = "primary" }),
      ui.label({ text = noctalia.tr("controls.title"), fontSize = 18, fontWeight = "semibold", flexGrow = 1 }),
      ui.button({ glyph = "close", variant = "ghost", width = 30, height = 30, tooltip = noctalia.tr("controls.close"), onClick = function() panel.close() end }),
    }),
    ui.row({ gap = 16, align = "center" }, {
      M.artwork(data, 76),
      ui.column({ gap = 6, flexGrow = 1 }, {
        ui.label({ text = M.title(data), fontSize = 16, fontWeight = "semibold", maxWidth = 272, maxLines = 2 }),
        ui.label({ text = M.artist(data), fontSize = 13, color = "on_surface_variant", maxWidth = 272, maxLines = 1 }),
        ui.label({ text = noctalia.tr("status." .. (data.status or "Stopped")), fontSize = 11, color = "primary" }),
      }),
    }),
    ui.column({ gap = 7 }, {
      ui.progress({ progress = length > 0 and math.clamp(position / length, 0, 1) or 0, height = 3, radius = 2,
        fill = "primary", track = "primary/0.14" }),
      ui.row({ justify = "space_between" }, {
        ui.label({ text = M.time(position), fontSize = 11, color = "on_surface_variant" }),
        ui.label({ text = length > 0 and M.time(length) or noctalia.tr("state.no_duration"), fontSize = 11, color = "on_surface_variant" }),
      }),
    }),
    M.controls(data, false),
    ui.row({ gap = 10, align = "center" }, {
      M.sourcePicker(data, 213),
      ui.button({ text = noctalia.tr("room.open"), glyph = "arrow-up-right", variant = "secondary", controlSize = "sm", flexGrow = 1,
        onClick = function() noctalia.togglePanel("dotfiles/moonlit-music:room") end }),
    }),
    M.errorRow(data, 412, false),
  }))
end

M.watch(render)
function onOpen()
  visible = true
  noctalia.state.set("moonlit.visible.controls", true)
  noctalia.state.set("moonlit.refresh", noctalia.nowMs())
  render()
end
function onClose()
  visible = false
  panel.render(ui.column({}, {}))
  noctalia.state.set("moonlit.visible.controls", false)
  panel.setWantsSecondTicks(false)
  panel.setNeedsFrameTick(false)
end
function onExit()
  M.releaseCommand()
  noctalia.state.set("moonlit.visible.controls", false)
end
