local M = require("./common.luau")
M.commandOwner = "bar"

local function openControls()
  noctalia.togglePanel("dotfiles/moonlit-music:controls")
end

local function render()
  local data = M.current()
  local path = M.artPath(data)
  local cover = path and ui.image({ path = path, width = 24, height = 24, radius = 6, fit = "cover" })
    or ui.glyph({ name = "music", size = 19, color = "primary" })
  barWidget.render(ui.row({ gap = 8, align = "center" }, {
    ui.row({ key = "open", gap = 8, align = "center", onClick = openControls, tooltip = noctalia.tr("controls.open") }, {
      cover,
      ui.label({ text = data.player ~= "" and M.title(data) or noctalia.tr("music"), maxWidth = 235, maxLines = 1, fontSize = 14 }),
    }),
    ui.button({ key = "play", glyph = data.status == "Playing" and "media-pause" or "media-play",
      glyphSize = 15, width = 29, height = 27, variant = "ghost",
      enabled = M.canToggle(data) and noctalia.state.get("moonlit.command.pending") ~= true,
      tooltip = data.status == "Playing" and noctalia.tr("transport.pause") or noctalia.tr("transport.play"), onClick = function() M.command("toggle") end }),
  }))
  barWidget.setTooltip({ { noctalia.tr("field.player"), M.source(data) }, { noctalia.tr("field.status"), noctalia.tr("status." .. (data.status or "Stopped")) }, { noctalia.tr("field.track"), M.title(data) } })
end

M.watch(render)
render()
function onClick() openControls() end
function onExit() M.releaseCommand() end
