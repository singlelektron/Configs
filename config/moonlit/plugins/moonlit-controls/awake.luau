local alive = true
local pending = false
local failed = false
local active = false
local helper = nil
local flag = nil

-- The runner validates this pinned manifest before loading any plugins. The
-- capability check also leaves an isolated preview unable to control host idle.
local manifestPath = noctalia.getenv("MOONLIT_SESSION_MANIFEST")
local runtime = noctalia.getenv("XDG_RUNTIME_DIR")
if type(manifestPath) == "string" and string.sub(manifestPath, 1, 1) == "/"
  and type(runtime) == "string" and string.sub(runtime, 1, 1) == "/" then
  local raw = noctalia.readFile(manifestPath)
  local manifest = raw and noctalia.json.decode(raw) or nil
  if type(manifest) == "table" and manifest.schema == 1
    and manifest.kind == "moonlit-live-session" and manifest.phase == "basic"
    and type(manifest.release) == "string" and string.sub(manifest.release, 1, 1) == "/"
    and type(manifest.capabilities) == "table" then
    for _, capability in ipairs(manifest.capabilities) do
      if capability == "caffeine" then
        local path = manifest.release .. "/managed/niri/desktopctl.py"
        if noctalia.fileExists(path) then
          helper = path
          flag = runtime .. "/dotfiles-niri/presentation"
        end
        break
      end
    end
  end
end

local function refresh()
  if not alive then return end
  active = flag ~= nil and noctalia.fileExists(flag)
  shortcut.setActive(active)
  shortcut.setEnabled(helper ~= nil and not pending)
  shortcut.setLabel(noctalia.tr(helper == nil and "awake.unavailable"
    or (failed and "awake.failed" or "awake.label")))
  noctalia.state.set("moonlit.awake.tile", {
    loaded = true, active = active, available = helper ~= nil,
    pending = pending, failed = failed,
  })
end

-- Noctalia 5.2.1 shortcuts have no IPC endpoint. The tiny service relays explicit
-- helper events to this VM, including while the control center is closed.
noctalia.state.watch("moonlit.awake.refresh", function()
  if not alive then return end
  failed = false
  refresh()
end)
-- The host always arms a timer; suppress its default one-second empty dispatch.
-- There is no update() handler and no periodic file read or subprocess.
noctalia.setUpdateInterval(2147483647)
shortcut.setIcon("caffeine-on", "caffeine-off")
refresh()

function onClick()
  if not alive or not helper or pending then return end
  pending = true
  failed = false
  refresh()
  local accepted = noctalia.runAsync({"/usr/bin/python3", helper, "presentation", "toggle"}, function(result)
    if not alive then return end
    pending = false
    failed = result.exitCode ~= 0
    if failed then noctalia.log("Keep awake: presentation command failed") end
    refresh()
  end)
  if not accepted then
    pending = false
    failed = true
    noctalia.log("Keep awake: could not start presentation command")
    refresh()
  end
end

function onExit()
  if not alive then return end
  alive = false
  noctalia.state.set("moonlit.awake.tile", {loaded = false})
end
