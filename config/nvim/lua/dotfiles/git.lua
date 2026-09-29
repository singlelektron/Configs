local M = {}

function M.root()
  local directory = vim.fn.getcwd()
  if vim.bo.filetype == "NvimTree" then
    local ok, tree = pcall(require, "dotfiles.tree")
    if ok and tree.root then directory = tree.root() or directory end
  elseif vim.bo.buftype == "" then
    local path = vim.api.nvim_buf_get_name(0)
    if path ~= "" then directory = vim.fs.dirname(path) end
  end
  local result = vim.system({ "git", "-C", directory, "rev-parse", "--show-toplevel" }, { text = true }):wait(2000)
  if result.code == 0 then return vim.trim(result.stdout) end
end

function M.open()
  if vim.fn.executable("lazygit") ~= 1 then
    vim.notify("Install lazygit with the repository's tools installer first.", vim.log.levels.WARN)
    return
  end
  local root = M.root()
  if not root then
    vim.notify("Open a Git project before opening LazyGit.", vim.log.levels.INFO)
    return
  end
  local config = vim.fs.joinpath(vim.fs.dirname(vim.fn.stdpath("config")), "lazygit", "config.yml")
  if vim.fn.filereadable(config) == 0 then
    vim.notify("Deploy the LazyGit config with scripts/deploy.py --apply first.", vim.log.levels.WARN)
    return
  end
  local previous = vim.api.nvim_get_current_win()
  vim.cmd.tabnew()
  local tab, buffer = vim.api.nvim_get_current_tabpage(), vim.api.nvim_get_current_buf()
  vim.bo.bufhidden = "wipe"
  local job = vim.fn.jobstart({ "lazygit", "--use-config-file", config }, {
    term = true,
    cwd = root,
    on_exit = function(_, code)
      vim.schedule(function()
        if code ~= 0 then
          vim.notify("LazyGit exited with code " .. code .. "; terminal output retained.", vim.log.levels.WARN)
          return
        end
        if not vim.api.nvim_buf_is_valid(buffer) then return end
        local current = vim.api.nvim_get_current_tabpage()
        if vim.api.nvim_tabpage_is_valid(tab) and #vim.api.nvim_list_tabpages() > 1 then
          local windows = vim.api.nvim_tabpage_list_wins(tab)
          if #windows == 1 and vim.api.nvim_win_get_buf(windows[1]) == buffer then
            vim.api.nvim_set_current_tabpage(tab)
            vim.cmd.tabclose()
            if vim.api.nvim_buf_is_valid(buffer) then
              vim.api.nvim_buf_delete(buffer, { force = true })
            end
            if current ~= tab and vim.api.nvim_tabpage_is_valid(current) then
              vim.api.nvim_set_current_tabpage(current)
            elseif vim.api.nvim_win_is_valid(previous) then
              vim.api.nvim_set_current_win(previous)
            end
            return
          end
        end
        -- The user may have reused this tab; remove only our finished terminal.
        vim.api.nvim_buf_delete(buffer, { force = true })
      end)
    end,
  })
  if job <= 0 then
    vim.cmd.tabclose()
    vim.notify("Could not start LazyGit.", vim.log.levels.ERROR)
    return
  end
  vim.bo[buffer].filetype = "lazygit"
  vim.bo[buffer].bufhidden = "wipe"
  vim.cmd.startinsert()
end

function M.setup()
  vim.api.nvim_create_user_command("DotfilesGit", M.open, { desc = "Open mouse-enabled LazyGit" })
  vim.keymap.set("n", "<leader>gg", M.open, { desc = "Git manager (LazyGit)" })
end

return M
