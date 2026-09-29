local M = {}
local initialized = false

local function specs()
  return {
    {
      "neovim/nvim-lspconfig",
      lazy = false,
      config = function()
        require("dotfiles.lsp").setup()
      end,
    },
    {
      "nvim-mini/mini.pick",
      opts = {},
      keys = {
        { "<leader>ff", function() require("mini.pick").builtin.files() end, desc = "Find files" },
        { "<leader>fg", function() require("mini.pick").builtin.grep_live() end, desc = "Search project text" },
        { "<leader>fb", function() require("mini.pick").builtin.buffers() end, desc = "Find buffer" },
        { "<leader>fh", function() require("mini.pick").builtin.help() end, desc = "Find help" },
      },
    },
    {
      "lewis6991/gitsigns.nvim",
      event = { "BufReadPre", "BufNewFile" },
      opts = {
        signs = { add = { text = "+" }, change = { text = "~" }, delete = { text = "_" }, topdelete = { text = "‾" }, changedelete = { text = "~" } },
        current_line_blame = false,
        on_attach = function(bufnr)
          local gs = require("gitsigns")
          vim.keymap.set("n", "<leader>hp", gs.preview_hunk, { buffer = bufnr, desc = "Preview Git hunk" })
          vim.keymap.set("n", "]c", function()
            if vim.wo.diff then vim.cmd.normal({ "]c", bang = true }) else gs.nav_hunk("next") end
          end, { buffer = bufnr, desc = "Next Git change" })
          vim.keymap.set("n", "[c", function()
            if vim.wo.diff then vim.cmd.normal({ "[c", bang = true }) else gs.nav_hunk("prev") end
          end, { buffer = bufnr, desc = "Previous Git change" })
        end,
      },
    },
    {
      "tpope/vim-fugitive",
      cmd = { "Git", "G", "Gdiffsplit", "Gvdiffsplit", "Gedit", "Gread", "Gwrite", "Gclog" },
      keys = { { "<leader>gs", "<cmd>Git<CR>", desc = "Git status" } },
    },
    {
      "lervag/vimtex",
      -- VimTeX handles filetype detection itself and recommends eager loading.
      lazy = false,
      init = function()
        vim.g.tex_flavor = "latex"
        -- Editing also works on hosts without the optional TeX distribution.
        vim.g.vimtex_compiler_enabled = vim.fn.executable("latexmk")
        vim.g.vimtex_compiler_latexmk = { continuous = 0 }
        vim.g.vimtex_view_automatic = 0
        vim.g.vimtex_quickfix_mode = 0
        -- Let texlab provide LSP completion; VimTeX retains LaTeX text objects.
        vim.g.vimtex_complete_enabled = 0
        vim.g.vimtex_view_method = "general"
      end,
    },
  }
end

function M.setup(config_root)
  if vim.env.DOTFILES_NVIM_NO_PLUGINS == "1" then
    return
  end
  -- Separate from the previous distribution's data so rollback stays possible.
  local plugin_root = vim.fn.stdpath("data") .. "/dotfiles-lazy"
  local lazy_path = plugin_root .. "/lazy.nvim"
  local lockfile = config_root .. "/lazy-lock.json"

  local function start()
    if initialized then return true end
    if not vim.uv.fs_stat(lazy_path .. "/lua/lazy/init.lua") then return false end
    vim.opt.rtp:prepend(lazy_path)
    local ok, err = pcall(function()
      local plugins = specs()
      local missing = {}
      for _, plugin in ipairs(plugins) do
        local name = plugin[1]:match("/([^/]+)$")
        if not vim.uv.fs_stat(plugin_root .. "/" .. name .. "/.git") then
          missing[#missing + 1] = name
          -- Missing plugins stay installable, but do not create broken startup
          -- loads, commands or mappings while offline. Restart after installing.
          plugin.lazy, plugin.event, plugin.keys, plugin.cmd = true, nil, nil, nil
        end
      end
      require("lazy").setup(plugins, {
        root = plugin_root,
        lockfile = lockfile,
        install = { missing = false },
        checker = { enabled = false },
        change_detection = { enabled = false },
        rocks = { enabled = false },
        headless = { process = false, task = false, log = false },
        ui = { border = "rounded" },
      })
      if #missing > 0 then
        vim.notify("Missing plugins: " .. table.concat(missing, ", ") .. ". Run :DotfilesInstall, then restart.", vim.log.levels.WARN)
      end
    end)
    if not ok then
      vim.notify("Plugins unavailable; base editing remains usable. " .. tostring(err), vim.log.levels.WARN)
      return false
    end
    initialized = true
    return true
  end

  vim.api.nvim_create_user_command("DotfilesInstall", function()
    -- A git pull or :Lazy update may have changed the lock since startup.
    local lock_lines = vim.fn.readfile(lockfile)
    local lock = vim.json.decode(table.concat(lock_lines, "\n"))
    if not vim.uv.fs_stat(lazy_path) then
      if vim.fn.executable("git") ~= 1 then error("Install Git before running :DotfilesInstall") end
      vim.fn.mkdir(plugin_root, "p")
      local staging = lazy_path .. ".install-" .. tostring(vim.uv.hrtime())
      local clone = vim.system({ "git", "clone", "--filter=blob:none", "--no-checkout", "https://github.com/folke/lazy.nvim.git", staging }, { text = true }):wait(120000)
      if clone.code ~= 0 then
        vim.fn.delete(staging, "rf")
        error("lazy.nvim download failed: " .. (clone.stderr or ""))
      end
      local checkout = vim.system({ "git", "-C", staging, "checkout", "--detach", lock["lazy.nvim"].commit }, { text = true }):wait(120000)
      if checkout.code ~= 0 then
        vim.fn.delete(staging, "rf")
        error("lazy.nvim checkout failed: " .. (checkout.stderr or ""))
      end
      assert(vim.uv.fs_rename(staging, lazy_path))
    end
    if not start() then error("Could not start lazy.nvim; check " .. lazy_path) end
    -- Explicitly use the committed lock on first install and on restored machines.
    require("lazy.manage.lock").lock = vim.deepcopy(lock)
    require("lazy.manage.lock")._loaded = true
    local ok, err = pcall(function()
      require("lazy").install({ wait = true, show = false, lockfile = true })
      -- lazy rewrites its lock even after a partial download. Keep the committed
      -- target in both its cache and the file so retries never drift to HEAD.
      require("lazy.manage.lock").lock = vim.deepcopy(lock)
      require("lazy").restore({ wait = true, show = false })
    end)
    vim.fn.writefile(lock_lines, lockfile)
    require("lazy.manage.lock").lock = vim.deepcopy(lock)
    if not ok then error(err) end
    for name, entry in pairs(lock) do
      local result = vim.system({ "git", "-C", plugin_root .. "/" .. name, "rev-parse", "HEAD" }, { text = true }):wait(10000)
      if result.code ~= 0 or vim.trim(result.stdout or "") ~= entry.commit then
        error("Plugin installation incomplete: " .. name .. "; retry :DotfilesInstall")
      end
    end
    vim.notify("Locked plugins installed. Restart Neovim.")
  end, { desc = "Install / restore pinned plugins (network required)" })

  if not start() then
    vim.schedule(function()
      if not initialized then
        vim.notify("Plugins are not installed. Run :DotfilesInstall when online; base editing is ready.", vim.log.levels.WARN)
      end
    end)
  end
end

return M
