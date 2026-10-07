local M = require("./common.luau")

local function openControls()
  noctalia.togglePanel("dotfiles/moonlit-music:controls")
end

local function render()
  local data = M.current()
  local path = M.artPath(data)
  local cover = path and ui.image({ path = path, width = 24, height = 24, radius = 6, fit = "cover" })
    or ui.glyph({ name = "music", size = 19, color = "primary" })
  barWidget.render(ui.row({ gap = 8, align = "center" }, {
    ui.row({ key = "open", gap = 8, align = "center", onClick = openControls, tooltip = "Open music controls" }, {
      cover,
      ui.label({ text = data.player ~= "" and M.title(data) or "Music", maxWidth = 235, maxLines = 1, fontSize = 14 }),
    }),
    ui.button({ key = "play", glyph = data.status == "Playing" and "media-pause" or "media-play",
      glyphSize = 15, width = 29, height = 27, variant = "ghost",
      enabled = M.canToggle(data) and noctalia.state.get("moonlit.command.pending") ~= true,
      tooltip = data.status == "Playing" and "Pause" or "Play", onClick = function() M.command("toggle") end }),
  }))
  barWidget.setTooltip({ { "Player", M.source(data) }, { "Status", data.status or "Stopped" }, { "Track", M.title(data) } })
end

M.watch(render)
render()
function onClick() openControls() end
