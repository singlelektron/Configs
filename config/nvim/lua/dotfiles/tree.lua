local M = {}

function M.toggle()
  require("nvim-tree.api").tree.toggle({ find_file = true })
end

function M.reveal()
  require("nvim-tree.api").tree.find_file({ open = true, focus = true, update_root = true })
end

function M.root()
  if vim.g.NvimTreeSetup ~= 1 then return nil end
  local root = require("nvim-tree.api").tree.get_nodes()
  return root and root.absolute_path or nil
end

function M.setup()
  local api = require("nvim-tree.api")
  local group = vim.api.nvim_create_augroup("DotfilesTree", { clear = true })
  local stdin_read = false
  -- Directory hijacking can replace the original argument's buffer name.
  local first = vim.fn.argv(0)
  local startup_directory = type(first) == "string" and first ~= "" and vim.fn.isdirectory(first) == 1
    and vim.fn.fnamemodify(first, ":p") or nil
  vim.api.nvim_create_autocmd("StdinReadPre", {
    group = group,
    callback = function() stdin_read = true end,
  })

  require("nvim-tree").setup({
    -- Only disable netrw once the installed tree can replace it. The offline
    -- base configuration keeps Neovim's bundled directory browser available.
    disable_netrw = true,
    hijack_netrw = true,
    hijack_directories = { enable = true, auto_open = #vim.api.nvim_list_uis() > 0 },
    on_attach = function(bufnr)
      -- Includes Enter / double-left-click to open, a/r/d, and g? for help.
      api.config.mappings.default_on_attach(bufnr)
    end,
    view = { side = "left", width = 30, signcolumn = "no" },
    renderer = {
      root_folder_label = ":t",
      group_empty = true,
      highlight_git = "name",
      indent_markers = { enable = true },
      icons = {
        web_devicons = { file = { enable = false }, folder = { enable = false } },
        show = { file = false, folder = false, folder_arrow = true, git = true },
        git_placement = "after",
        glyphs = {
          folder = { arrow_closed = "›", arrow_open = "⌄" },
          git = { unstaged = "~", staged = "+", unmerged = "!", renamed = "→", untracked = "?", deleted = "−", ignored = "·" },
        },
      },
    },
    update_focused_file = { enable = true },
    git = { enable = true, timeout = 1000 },
    filters = { dotfiles = false, git_ignored = true },
    modified = { enable = true },
    actions = {
      -- Browsing must not silently change the cwd used by terminals and :Git.
      change_dir = { enable = false },
      open_file = {
        quit_on_open = false,
        -- A mouse double-click opens in the last editing window, without a
        -- keyboard-only window-selection prompt when multiple splits exist.
        window_picker = { enable = false },
      },
    },
    ui = { confirm = { remove = true, trash = true, default_yes = false } },
  })

  vim.api.nvim_create_autocmd("VimEnter", {
    group = group,
    once = true,
    callback = function()
      -- Keep Git editors, pipes, session layouts and noninteractive commands
      -- focused on their original job. The tree remains available on demand.
      if #vim.api.nvim_list_uis() == 0 or stdin_read or vim.v.this_session ~= "" then return end
      if vim.tbl_contains(vim.v.argv, "-") then return end
      for _, win in ipairs(vim.api.nvim_list_wins()) do
        if vim.wo[win].diff then return end
      end
      local ft = vim.bo.filetype
      if ft == "gitcommit" or ft == "gitrebase" then return end
      if vim.bo.buftype ~= "" and ft ~= "NvimTree" then return end

      if startup_directory then
        -- Directory startup may already have been caught by nvim-tree. Give
        -- it a genuine sidebar and an empty editing window in either case.
        api.tree.close()
        vim.cmd.enew()
        api.tree.open({ path = startup_directory })
      elseif vim.api.nvim_buf_get_name(0) ~= "" then
        api.tree.find_file({ open = true, focus = false, update_root = true })
      else
        api.tree.open()
      end
    end,
  })
end

return M
