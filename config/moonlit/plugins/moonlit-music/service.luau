local M = require("./common.luau")
local running = false
local repeatAfter = false
local alive = true

local function poll()
  if not alive then return end
  if running then repeatAfter = true; return end
  running = true
  local accepted = noctalia.runAsync({ "python3", noctalia.pluginDir() .. "/media_bridge.py", "snapshot" }, function(result)
    running = false
    if not alive then return end
    local data = noctalia.json.decode(result.stdout or "")
    if type(data) ~= "table" then
      data = table.clone(M.empty)
      data.error = result.exitCode ~= 0 and M.text(result.stderr, "Media connection unavailable") or "Media bridge returned invalid data"
    elseif result.exitCode ~= 0 then
      data.error = M.text(data.error, M.text(result.stderr, "Media connection unavailable"))
    end
    noctalia.state.set("moonlit.media", data)
    if repeatAfter then repeatAfter = false; poll() end
  end)
  if not accepted then
    running = false
    local data = table.clone(M.empty)
    data.error = "Could not start media bridge"
    noctalia.state.set("moonlit.media", data)
  end
end

local function cadence()
  local visible = noctalia.state.get("moonlit.visible.controls") == true or noctalia.state.get("moonlit.visible.room") == true
  noctalia.setUpdateInterval(visible and 1000 or 2000)
end

noctalia.state.watch("moonlit.visible.controls", function() cadence() end)
noctalia.state.watch("moonlit.visible.room", function() cadence() end)
noctalia.state.watch("moonlit.refresh", function() poll() end)
cadence()
poll()
function update() poll() end
function onExit() alive = false end
