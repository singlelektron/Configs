local M = {}

-- Keep these colors aligned with Kitty; future desktop components can use the
-- same restrained slate / cyan palette without depending on a theme plugin.
local colors = {
  background = "#161b26",
  surface = "#1b2230",
  selection = "#25364a",
  border = "#344155",
  foreground = "#d6deeb",
  muted = "#8a97ad",
  cyan = "#67d4e8",
  blue = "#82aaff",
  green = "#9ece6a",
  yellow = "#e0af68",
  red = "#f7768e",
}

function M.apply_palette()
  local groups = {
    -- NONE inherits the terminal background, including Kitty's transparency.
    Normal = { fg = colors.foreground, bg = "NONE" },
    NormalNC = { fg = colors.foreground, bg = "NONE" },
    SignColumn = { bg = "NONE" },
    EndOfBuffer = { fg = colors.muted, bg = "NONE" },
    LineNr = { fg = colors.muted, bg = "NONE" },
    CursorLineNr = { fg = colors.cyan, bold = true },
    CursorLine = { bg = colors.surface },
    WinSeparator = { fg = colors.border, bg = "NONE" },
    Visual = { bg = colors.selection },
    Search = { fg = colors.background, bg = colors.yellow },
    IncSearch = { fg = colors.background, bg = colors.cyan },
    NormalFloat = { fg = colors.foreground, bg = colors.surface },
    FloatBorder = { fg = colors.border, bg = colors.surface },
    FloatTitle = { fg = colors.cyan, bg = colors.surface, bold = true },
    Pmenu = { fg = colors.foreground, bg = colors.surface },
    PmenuSel = { fg = colors.background, bg = colors.cyan },
    PmenuSbar = { bg = colors.surface },
    PmenuThumb = { bg = colors.muted },
    StatusLine = { fg = colors.foreground, bg = colors.surface },
    StatusLineNC = { fg = colors.muted, bg = colors.surface },
    TabLineFill = { bg = colors.surface },
    Comment = { fg = colors.muted },
    String = { fg = colors.green },
    Function = { fg = colors.blue },
    Identifier = { fg = colors.foreground },
    Statement = { fg = colors.cyan },
    Type = { fg = colors.blue },
    Special = { fg = colors.cyan },
    DiagnosticError = { fg = colors.red },
    DiagnosticWarn = { fg = colors.yellow },
    DiagnosticInfo = { fg = colors.blue },
    DiagnosticHint = { fg = colors.cyan },
    GitSignsAdd = { fg = colors.green },
    GitSignsChange = { fg = colors.blue },
    GitSignsDelete = { fg = colors.red },
    NvimTreeNormal = { fg = colors.foreground, bg = colors.surface },
    NvimTreeNormalNC = { fg = colors.foreground, bg = colors.surface },
    NvimTreeEndOfBuffer = { fg = colors.surface, bg = colors.surface },
    NvimTreeWinSeparator = { fg = colors.border, bg = colors.surface },
    NvimTreeCursorLine = { bg = colors.selection },
    NvimTreeRootFolder = { fg = colors.cyan, bold = true },
    NvimTreeFolderName = { fg = colors.blue },
    NvimTreeOpenedFolderName = { fg = colors.cyan },
    NvimTreeFolderIcon = { fg = colors.muted },
    NvimTreeIndentMarker = { fg = colors.selection },
    NvimTreeGitDirtyIcon = { fg = colors.yellow },
    NvimTreeGitNewIcon = { fg = colors.green },
    NvimTreeGitDeletedIcon = { fg = colors.red },
  }
  for name, value in pairs(groups) do
    vim.api.nvim_set_hl(0, name, value)
  end
end

local function notify(message)
  vim.notify(message, vim.log.levels.WARN, { title = "Dotfiles" })
end

-- Schedule actions outside status/tabline evaluation. Non-left clicks have no
-- side effects; all normal Vim navigation and Git commands remain available.
local function click(action)
  return function(_, button)
    if button ~= "l" then return end
    vim.schedule(function()
      local ok, err = pcall(action)
      if not ok then notify(tostring(err)) end
    end)
  end
end

local function open_diff()
  local name = vim.api.nvim_buf_get_name(0)
  if vim.bo.buftype ~= "" or name == "" then
    notify("Diff: select a tracked file in an editing window first.")
    return
  end
  -- Validate the exact file without shell interpolation or glob pathspecs.
  -- This happens only on a click, never on a statusline refresh.
  local tracked = vim.system({
    "git", "-C", vim.fs.dirname(name), "--literal-pathspecs", "ls-files", "--error-unmatch", "--", name,
  }, { text = true }):wait(1500)
  if tracked.code ~= 0 then
    notify("Diff: this file is not tracked by Git. Use Git to inspect new files.")
    return
  end
  vim.cmd("Gdiffsplit")
end

function M.setup()
  local theme = {
    normal = {
      a = { fg = colors.background, bg = colors.cyan, gui = "bold" },
      b = { fg = colors.foreground, bg = colors.surface },
      c = { fg = colors.muted, bg = colors.surface },
    },
    insert = { a = { fg = colors.background, bg = colors.green, gui = "bold" } },
    visual = { a = { fg = colors.background, bg = colors.blue, gui = "bold" } },
    replace = { a = { fg = colors.background, bg = colors.red, gui = "bold" } },
    command = { a = { fg = colors.background, bg = colors.yellow, gui = "bold" } },
    inactive = {
      a = { fg = colors.muted, bg = colors.surface },
      b = { fg = colors.muted, bg = colors.surface },
      c = { fg = colors.muted, bg = colors.surface },
    },
  }
  require("lualine").setup({
    options = {
      icons_enabled = false,
      theme = theme,
      component_separators = "",
      section_separators = "",
      globalstatus = true,
      always_show_tabline = true,
    },
    sections = {
      lualine_a = { "mode" },
      lualine_b = {
        { "branch", on_click = click(function() vim.cmd("Git") end) },
        { "diff", symbols = { added = "+", modified = "~", removed = "-" } },
      },
      lualine_c = { { "filename", path = 1 } },
      lualine_x = {
        { "diagnostics", sources = { "nvim_diagnostic" }, symbols = { error = "E:", warn = "W:", info = "I:", hint = "H:" } },
        { "filetype", cond = function() return vim.o.columns >= 100 end },
      },
      lualine_y = {},
      lualine_z = { "location" },
    },
    tabline = {
      lualine_a = {
        {
          function() return "Files" end,
          on_click = click(function() require("dotfiles.tree").toggle() end),
        },
      },
      lualine_b = {
        {
          "buffers",
          show_filename_only = true,
          mode = 0,
          max_length = function() return math.max(10, vim.o.columns - 27) end,
          symbols = { modified = " +", alternate_file = "", directory = "/" },
          filetype_names = { NvimTree = "Files", fugitive = "Git status", lazygit = "Git" },
          buffers_color = {
            active = { fg = colors.cyan, bg = colors.selection, gui = "bold" },
            inactive = { fg = colors.muted, bg = colors.surface },
          },
        },
      },
      lualine_c = {},
      lualine_x = {},
      lualine_y = {
        { function() return "Git" end, on_click = click(function() require("dotfiles.git").open() end) },
        { function() return "Diff" end, on_click = click(open_diff) },
      },
      lualine_z = {},
    },
  })
end

return M
