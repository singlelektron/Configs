local busy = false
local value = {status = "unknown"}
noctalia.setUpdateInterval(30000)
local function fail(message)
  busy = false
  -- Keep the last successful package data, but never present it as a fresh check.
  value.status = "error"
  value.error = type(message) == "string" and message ~= "" and message or "Could not read update status"
end
local function read(action)
  if busy then return end
  busy = true
  local accepted = noctalia.runAsync({"python3", noctalia.pluginDir() .. "/updates.py", action}, function(result)
    busy = false
    local data = noctalia.json.decode(result.stdout or "")
    if result.exitCode ~= 0 then
      fail(type(data) == "table" and data.error or result.stderr)
    elseif type(data) ~= "table" or
        (data.status ~= "unknown" and data.status ~= "checking" and data.status ~= "ok" and data.status ~= "error") or
        (data.status == "ok" and (type(data.count) ~= "number" or data.count < 0 or data.count % 1 ~= 0)) then
      fail("Update helper returned invalid status")
    else
      value = data
    end
    updateDisplay()
  end)
  if not accepted then
    fail("Could not start update helper")
    updateDisplay()
  end
end
function updateDisplay()
  local label = "Updates · ?"
  if value.status == "ok" then label = "Updates · " .. tostring(value.count) end
  if value.status == "error" then label = "Updates · !" end
  if busy then label = "Checking…" end
  barWidget.setText(label)
  barWidget.setGlyph("refresh")
  barWidget.setTooltip("Arch official repositories only · click to check · right click to review\n" .. (value.error or "No automatic upgrade"))
end
function update() read("status") end
function onClick() read("check"); updateDisplay() end
function onRightClick() noctalia.runAsync({"python3",noctalia.pluginDir().."/updates.py","review"}) end
update()
