-- Run with init.lua, installed locked plugins, isolated state/cache and -i NONE.
-- Real HTTP/WebSocket traffic verifies updates; no graphical browser is opened.
local temporary = vim.fn.tempname()
local original_open, original_notify = vim.ui.open, vim.notify
local sockets, urls, notices = {}, {}, {}
local markdown = require("dotfiles.markdown")
local original_config

local function socket()
  local client = assert(vim.uv.new_tcp())
  sockets[#sockets + 1] = client
  return client
end

local function close(client)
  if client and not client:is_closing() then client:close() end
end

local function settle(condition, message)
  assert(vim.wait(5000, condition, 10), message)
end

local function request(port, path)
  local client, response, complete, failure = socket(), "", false, nil
  client:connect("127.0.0.1", port, function(err)
    if err then failure, complete = err, true; return end
    client:read_start(function(read_error, data)
      if read_error then failure = read_error end
      if data then response = response .. data else complete = true; close(client) end
    end)
    client:write("GET " .. path .. " HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/html\r\n\r\n")
  end)
  settle(function() return complete end, "HTTP response did not finish")
  assert(not failure, failure)
  assert(response:find("HTTP/1.1 200 OK", 1, true), response)
  return response
end

local function test()
  vim.ui.open = function(url) urls[#urls + 1] = url end
  vim.notify = function(message) notices[#notices + 1] = message end
  vim.fn.mkdir(temporary .. "/笔记 folder", "p")
  temporary = assert(vim.uv.fs_realpath(temporary))
  local first = temporary .. "/笔记 folder/数学 note.md"
  local second = temporary .. "/second note.md"
  vim.fn.writefile({ "# Saved note", "", "$E=mc^2$" }, first)
  vim.fn.writefile({ "# Second note" }, second)
  vim.cmd.edit(vim.fn.fnameescape(first))
  assert(vim.bo.filetype == "markdown")
  local preview = require("livepreview")
  local config = require("livepreview.config")
  original_config = vim.deepcopy(config.config)

  local reservation = socket()
  assert(reservation:bind("127.0.0.1", 0))
  assert(reservation:listen(1, function() end))
  local port = reservation:getsockname().port
  local released = false
  reservation:close(function() released = true end)
  settle(function() return released end, "test port was not released")
  config.set({ address = "127.0.0.1", port = port, dynamic_root = true, browser = "default", sync_scroll = false })
  local cwd = vim.fn.getcwd()

  local url = assert(markdown.open(), "preview did not start")
  local endpoint = preview.serverObj.server:getsockname()
  assert(endpoint.ip == "127.0.0.1" and endpoint.port == port, vim.inspect(endpoint))
  assert(url == ("http://127.0.0.1:%d/%s"):format(port, vim.uri_encode(vim.fs.basename(first))), "note URL is not encoded")
  assert(urls[1] == url and #urls == 1, "browser did not receive the preview URL")
  assert(vim.fn.getcwd() == cwd, "preview changed Neovim's working directory")
  local response = request(port, url:match("http://[^/]+(/.*)"))
  assert(response:find("# Saved note", 1, true), "initial page did not read saved note")
  assert(response:find("/live-preview.nvim/static/katex/katex.min.js", 1, true), "local math script missing")
  assert(response:find("/live-preview.nvim/static/katex/katex.min.css", 1, true), "local math styles missing")
  assert(response:find("/live-preview.nvim/static/markdown/markdown-it.min.js", 1, true), "local Markdown renderer missing")

  local client, received, handshake, failure = socket(), "", false, nil
  client:connect("127.0.0.1", port, function(err)
    if err then failure = err; return end
    client:read_start(function(read_error, data)
      if read_error then failure = read_error end
      if not data then return end
      received = received .. data
      if not handshake then
        local boundary = received:find("\r\n\r\n", 1, true)
        if boundary then
          if not received:find("101 Switching Protocols", 1, true) then failure = received end
          received, handshake = received:sub(boundary + 4), true
        end
      end
    end)
    client:write("GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
      .. "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
  end)
  settle(function() return handshake or failure end, "WebSocket handshake timed out")
  assert(not failure, failure)
  local changed = { "# Unsaved live note", "", "$$\\int_0^1 x^2\\,dx=\\frac13$$" }
  vim.api.nvim_buf_set_lines(0, 0, -1, false, changed)
  vim.api.nvim_exec_autocmds("TextChanged", { buffer = 0 })
  local function payload()
    if #received < 2 then return end
    assert(received:byte(1) == 0x81, "expected a text WebSocket frame")
    local length, offset = received:byte(2), 3
    if length == 126 then
      if #received < 4 then return end
      length, offset = received:byte(3) * 256 + received:byte(4), 5
    end
    assert(length < 65536, "test message unexpectedly large or masked")
    if #received >= offset + length - 1 then return received:sub(offset, offset + length - 1) end
  end
  settle(function() return payload() ~= nil or failure end, "unsaved change was not broadcast")
  assert(not failure, failure)
  local message = vim.json.decode(payload())
  assert(message.type == "update" and message.filepath == first, vim.inspect(message))
  assert(message.content == table.concat(changed, "\n"), "WebSocket update lost Markdown content")
  assert(vim.bo.modified and vim.fn.readfile(first)[1] == "# Saved note", "live preview wrote the note")
  close(client)

  markdown.stop()
  assert(not preview.is_running(), "stop left the server running")
  vim.cmd.edit(vim.fn.fnameescape(second))
  url = assert(markdown.open(), "second note could not reuse the port")
  assert(request(port, url:match("http://[^/]+(/.*)")):find("# Second note", 1, true))
  assert(vim.fn.getcwd() == cwd, "changing the preview note changed cwd")
  markdown.stop()

  -- Call the registered mouse action rather than merely checking its label.
  local button = require("lualine").get_config().tabline.lualine_y[1]
  assert(button[1]() == "Preview" and button.cond(), "Markdown Preview button missing")
  local count = #urls
  button.on_click(1, "r", "")
  vim.wait(20, function() return false end)
  assert(#urls == count and not preview.is_running(), "right click opened preview")
  button.on_click(1, "l", "")
  settle(function() return preview.is_running() and #urls == count + 1 end, "Preview click did not start server")
  button.on_click(1, "l", "")
  settle(function() return not preview.is_running() end, "Preview click did not stop server")

  local blocker = socket()
  assert(blocker:bind("127.0.0.1", port))
  assert(blocker:listen(1, function() end))
  count = #urls
  assert(markdown.open() == nil, "occupied port was reported as a preview")
  assert(#urls == count and not preview.is_running(), "occupied port opened another service")
  assert(blocker:is_active(), "preview stopped an unrelated listening socket")
  close(blocker)

  local new_file = temporary .. "/new unsaved.md"
  vim.cmd.edit(vim.fn.fnameescape(new_file))
  vim.api.nvim_buf_set_lines(0, 0, -1, false, { "# New unsaved note" })
  assert(markdown.open() == nil and #urls == count and not preview.is_running())
  assert(vim.fn.filereadable(new_file) == 0 and vim.bo.modified, "preview saved a new note without permission")
  assert(vim.fn.getcwd() == cwd)
  print("Markdown preview integration: loopback HTTP, local assets, live WebSocket edits, note switching, mouse callbacks and occupied-port safety passed")
end

local ok, err = xpcall(test, debug.traceback)
pcall(markdown.stop)
for _, client in ipairs(sockets) do close(client) end
if original_config then require("livepreview.config").config = original_config end
vim.ui.open, vim.notify = original_open, original_notify
vim.fn.delete(temporary, "rf")
if not ok then vim.api.nvim_err_writeln(err); vim.cmd("cquit 1") else vim.cmd("qa!") end
