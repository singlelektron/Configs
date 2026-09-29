local M = {}
local active_file

local function notify(message, level)
  vim.notify(message, level or vim.log.levels.INFO, { title = "Markdown preview" })
end

function M.stop()
  local preview = package.loaded["livepreview"]
  local server = preview and preview.serverObj
  if server then
    preview.close()
    -- Release the listener before opening another note on the same port.
    vim.wait(1000, function() return server.server == nil end, 10)
  end
  active_file = nil
end

function M.open()
  local file = vim.api.nvim_buf_get_name(0)
  if vim.bo.buftype ~= "" or vim.bo.filetype ~= "markdown" then
    notify("Select a Markdown note first.")
    return
  end
  if not file:match("%.md$") and not file:match("%.markdown$") then
    notify("Save the note with a .md or .markdown extension first.")
    return
  end
  if vim.fn.filereadable(file) ~= 1 then
    notify("Save this new note once with :w before opening its preview.")
    return
  end
  local ok, preview = pcall(require, "livepreview")
  if not ok then
    notify("Run :DotfilesInstall, then restart Neovim to install Markdown preview.", vim.log.levels.WARN)
    return
  end
  local config = require("livepreview.config").config
  local utils = require("livepreview.utils")
  local relative = config.dynamic_root and vim.fs.basename(file)
    or utils.get_relative_path(file, vim.fn.getcwd())
  if not relative then
    notify("Open the note from its project directory, or enable dynamic_root.", vim.log.levels.WARN)
    return
  end
  if active_file ~= file or not preview.is_running() then
    M.stop()
    local started, err = pcall(preview.start, file, config.port)
    local server = preview.serverObj and preview.serverObj.server
    local address = server and server:getsockname()
    -- Upstream does not check bind/listen results. Never open another process's
    -- page or silently use a random port when the requested port is occupied.
    if not started or not address or address.port ~= config.port or not server:is_active() then
      M.stop()
      notify("Could not listen on port " .. config.port .. ". Stop the other preview or choose another port."
        .. (not started and (" " .. tostring(err)) or ""), vim.log.levels.WARN)
      return
    end
    active_file = file
  end
  local url = ("http://%s:%d/%s"):format(config.address, config.port, vim.uri_encode(relative))
  notify(url .. ((vim.env.SSH_CONNECTION or vim.env.SSH_TTY) and " (open locally through your SSH tunnel)" or ""))
  if vim.bo.modified then
    notify("The initial page reads the saved file. Save with :w, or keep typing to send live changes.")
  end
  utils.open_browser(url, config.browser)
  return url
end

function M.toggle()
  local preview = package.loaded["livepreview"]
  if preview and preview.is_running() and active_file == vim.api.nvim_buf_get_name(0) then
    M.stop()
  else
    return M.open()
  end
end

function M.setup()
  vim.api.nvim_create_user_command("MarkdownPreview", M.open, { desc = "Open live Markdown and math preview" })
  vim.api.nvim_create_user_command("MarkdownPreviewStop", M.stop, { desc = "Stop Markdown preview" })
  vim.keymap.set("n", "<leader>mp", M.toggle, { desc = "Toggle Markdown preview" })
  vim.keymap.set("n", "<leader>ms", M.stop, { desc = "Stop Markdown preview" })
end

return M
