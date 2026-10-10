local alive = true

-- Only service, panel and widget entries expose actual IPC endpoints in 5.2.1.
-- This relay has no update handler, file watcher, subprocess or polling loop.
-- The host cannot disable its timer through API24; avoid its one-second default.
noctalia.setUpdateInterval(2147483647)

function onIpc(event, payload)
  if not alive then return end
  if event == "refresh" then
    local revision = tonumber(noctalia.state.get("moonlit.awake.refresh")) or 0
    noctalia.state.set("moonlit.awake.refresh", revision + 1)
  elseif event == "status" then
    local tile = noctalia.state.get("moonlit.awake.tile") or {}
    -- Report what the shortcut actually rendered, not another read of the flag.
    noctalia.log("moonlit-awake-status " .. noctalia.json.encode({
      request = payload, loaded = tile.loaded == true,
      active = tile.active == true, available = tile.available == true,
      pending = tile.pending == true, failed = tile.failed == true,
    }))
  end
end

function onExit()
  alive = false
end
