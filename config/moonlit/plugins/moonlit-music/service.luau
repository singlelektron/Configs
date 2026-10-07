local M = require("./common.luau")
local alive = true
local lastPublished = noctalia.state.get("moonlit.media")
local instance = tostring(noctalia.nowMs())
local revision = 0
local streamRunning = false
local startStream = nil
local directory = noctalia.pluginDataDir()
local controlPath = directory and (directory .. "/media-control.json") or nil

local function equal(left, right)
  if type(left) ~= type(right) then return false end
  if type(left) ~= "table" then return left == right end
  for key, value in pairs(left) do
    if not equal(value, right[key]) then return false end
  end
  for key in pairs(right) do
    if left[key] == nil then return false end
  end
  return true
end

local function publish(data)
  if not equal(data, lastPublished) then
    lastPublished = data
    noctalia.state.set("moonlit.media", data)
  end
end

local function fail(message, stopped)
  local data = table.clone(M.empty)
  data.error = message
  data.bridge_stopped = stopped == true
  publish(data)
end

local function control(refresh)
  if not alive or not controlPath then return end
  revision = revision + 1
  local visible = noctalia.state.get("moonlit.visible.controls") == true or noctalia.state.get("moonlit.visible.room") == true
  local encoded = noctalia.json.encode({ instance = instance, revision = revision, visible = visible, refresh = refresh == true })
  local temporary = controlPath .. "." .. instance .. ".tmp"
  if not noctalia.writeFile(temporary, encoded) or not noctalia.renameFile(temporary, controlPath) then
    noctalia.removeFile(temporary)
    fail("Could not update the media bridge state")
  end
  if not streamRunning and startStream and (visible or refresh) then startStream() end
end

-- API32 runStream only accepts a shell string and has no exit callback.
-- Quote paths as data. The sleeping shell emits one terminal record on worker
-- exit; the worker watches the shell owner by pidfd to cover owner SIGKILL.
local function shellQuote(value)
  return "'" .. string.gsub(value, "'", "'\\''") .. "'"
end

startStream = function()
  if not alive or streamRunning or not controlPath then return end
  streamRunning = true
  local command = "python3 -u " .. shellQuote(noctalia.pluginDir() .. "/media_watch.py")
    .. " --control-file " .. shellQuote(controlPath) .. ' --owner-pid "$PPID"; '
    .. "printf '%s\\n' " .. shellQuote('{"_bridge_exit":true}')
  local accepted = noctalia.runStream(command, function(line)
    if not alive then return end
    local data = noctalia.json.decode(line)
    if type(data) ~= "table" then
      fail("Media bridge returned invalid data")
    elseif data._bridge_exit == true then
      streamRunning = false
      fail(noctalia.tr("bridge.stopped"), true)
    else
      publish(data)
    end
  end)
  if not accepted then
    streamRunning = false
    fail("Could not start the media bridge", true)
  end
end

noctalia.state.watch("moonlit.visible.controls", function() control(false) end)
noctalia.state.watch("moonlit.visible.room", function() control(false) end)
noctalia.state.watch("moonlit.refresh", function() control(true) end)
noctalia.state.watch("moonlit.restart", function() control(true) end)
-- Host timers cannot be disabled through API32. There is no update() callback;
-- this long interval avoids its default one-second dispatch. All work is event driven.
noctalia.setUpdateInterval(2147483647)

if controlPath then
  control(true)
else
  fail("Media bridge data directory is unavailable", true)
end

-- API32 IPC returns only an acknowledgement. Explicit diagnostic requests log
-- the exact state consumed by our UI; reading it has no transport/timer effects.
function onIpc(event, payload)
  if event ~= "status" then return end
  noctalia.log("moonlit-media-status " .. noctalia.json.encode({
    diagnostic = "moonlit-media-status", request = payload, stream_running = streamRunning,
    visible_controls = noctalia.state.get("moonlit.visible.controls") == true,
    visible_room = noctalia.state.get("moonlit.visible.room") == true,
    media = M.current(),
    command_pending = noctalia.state.get("moonlit.command.pending") == true,
    command_owner = noctalia.state.get("moonlit.command.owner") or "",
    command_serial = noctalia.state.get("moonlit.command.serial") or 0,
  }))
end

function onExit()
  alive = false
  -- runStream is owned and cancelled by the Noctalia entry runtime itself.
end
