local opt = vim.opt
opt.number = true
opt.relativenumber = false
opt.termguicolors = true
opt.background = "dark"
opt.signcolumn = "yes"
opt.cursorline = false
opt.scrolloff = 4
opt.sidescrolloff = 4
opt.splitbelow = true
opt.splitright = true
opt.mouse = "a"
opt.mousemodel = "popup_setpos"
opt.ignorecase = true
opt.smartcase = true
opt.expandtab = true
opt.shiftwidth = 4
opt.softtabstop = 4
opt.tabstop = 4
opt.wrap = false
opt.breakindent = true
opt.completeopt = { "menu", "menuone", "noselect" }
opt.undofile = true
opt.updatetime = 500
opt.autoread = true
opt.spelllang = "en"
opt.spell = false
-- Keep clipboard use explicit: ordinary y/d/p retain Vim register semantics.
opt.clipboard = ""
vim.cmd.colorscheme("habamax")
require("dotfiles.ui").apply_palette()
require("dotfiles.git").setup()

-- SSH copies go to the client terminal. Paste with the terminal's paste key;
-- querying the remote clipboard via OSC 52 can block or require permission.
if vim.env.SSH_CONNECTION or vim.env.SSH_TTY then
  local osc52 = require("vim.ui.clipboard.osc52")
  local function local_paste()
    return { vim.fn.getreg('"', 1, true), vim.fn.getregtype('"') }
  end
  vim.g.clipboard = {
    name = "OSC 52 (copy only)",
    copy = { ["+"] = osc52.copy("+"), ["*"] = osc52.copy("*") },
    paste = { ["+"] = local_paste, ["*"] = local_paste },
  }
end

local map = vim.keymap.set
map("n", "<Esc>", "<cmd>nohlsearch<CR>", { desc = "Clear search highlight" })
map({ "n", "x" }, "<leader>y", '"+y', { desc = "Copy to system clipboard" })
map("n", "<leader>Y", '"+Y', { desc = "Copy line to system clipboard" })
map("n", "<leader>d", vim.diagnostic.open_float, { desc = "Diagnostic details" })
map("n", "<leader>q", vim.diagnostic.setloclist, { desc = "Diagnostics to location list" })
map("n", "<leader>us", function()
  vim.wo.spell = not vim.wo.spell
end, { desc = "Toggle spelling" })

vim.diagnostic.config({
  virtual_text = false,
  virtual_lines = false,
  signs = true,
  underline = true,
  severity_sort = true,
  update_in_insert = false,
  float = { border = "rounded", source = true },
})

local group = vim.api.nvim_create_augroup("Dotfiles", { clear = true })
vim.api.nvim_create_autocmd({ "FocusGained", "BufEnter", "CursorHold", "TermClose" }, {
  group = group,
  callback = function()
    if vim.fn.mode() ~= "c" and vim.fn.getcmdwintype() == "" then
      -- checktime reloads clean files changed by agents, but protects unsaved edits.
      vim.cmd("checktime")
    end
  end,
})
vim.api.nvim_create_autocmd("TextYankPost", {
  group = group,
  callback = function()
    vim.highlight.on_yank({ timeout = 120 })
  end,
})
vim.api.nvim_create_autocmd("FileType", {
  group = group,
  pattern = { "markdown", "tex", "plaintex", "gitcommit" },
  callback = function()
    vim.opt_local.wrap = true
    vim.opt_local.linebreak = true
    -- Visual wrapping only; do not reflow prose or CJK text on insert.
    vim.opt_local.textwidth = 0
    vim.opt_local.formatoptions:remove({ "t", "a" })
  end,
})
vim.api.nvim_create_autocmd("FileType", {
  group = group,
  pattern = { "lua", "json", "yaml", "toml" },
  callback = function()
    vim.opt_local.shiftwidth = 2
    vim.opt_local.softtabstop = 2
  end,
})
