local busy = false
local value = {status = "unknown"}
noctalia.setUpdateInterval(30000)
local function fail(message)
  busy = false
  -- Keep the last successful package data, but never present it as a fresh check.
  value.status = "error"
  value.error = type(message) == "string" and message ~= "" and message or noctalia.tr("read-error")
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
      fail(noctalia.tr("invalid-status"))
    else
      value = data
    end
    updateDisplay()
  end)
  if not accepted then
    fail(noctalia.tr("start-error"))
    updateDisplay()
  end
end
function updateDisplay()
  local label = noctalia.tr("count", {count = "?"})
  if value.status == "ok" then label = noctalia.tr("count", {count = value.count}) end
  if value.status == "error" then label = noctalia.tr("count", {count = "!"}) end
  if busy then label = noctalia.tr("checking") end
  barWidget.setText(label)
  barWidget.setGlyph("refresh")
  local detail = type(value.error) == "string" and value.error ~= "" and value.error or noctalia.tr("no-upgrade")
  barWidget.setTooltip(noctalia.tr("tooltip") .. "\n" .. detail)
end
function update() read("status") end
function onClick() read("check"); updateDisplay() end
function onRightClick()
  local accepted = noctalia.runAsync({"python3", noctalia.pluginDir() .. "/updates.py", "review",
    "--language", noctalia.getSetting("shell.lang") or "en"})
  if not accepted then fail(noctalia.tr("review-error")); updateDisplay() end
end
update()
