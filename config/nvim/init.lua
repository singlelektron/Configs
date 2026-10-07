-- Shared macOS / Linux configuration. Machine-specific choices load last.
vim.g.mapleader = " "
vim.g.maplocalleader = "\\"

-- GUI launches / non-interactive SSH may omit user tool directories. Preserve
-- the existing PATH order, adding only the usual uv/rustup locations at the end.
local paths = vim.split(vim.env.PATH or "", ":", { plain = true })
for _, directory in ipairs({ vim.fn.expand("~/.local/bin"), vim.fn.expand("~/.cargo/bin") }) do
  if not vim.tbl_contains(paths, directory) then
    paths[#paths + 1] = directory
  end
end
vim.env.PATH = table.concat(paths, ":")

local root = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h")
vim.opt.runtimepath:prepend(root)
require("dotfiles.base")

if vim.fn.has("nvim-0.11.3") == 1 then
  require("dotfiles.plugins").setup(root)
else
  vim.notify("Dotfiles plugins require Neovim 0.11.3 or newer; base editing is available.", vim.log.levels.WARN)
end

-- Optional deployed desktop palette; personal overrides still load last.
local desktop_theme = vim.fs.joinpath(vim.fs.dirname(vim.fn.stdpath("config")), "moonlit", "nvim-theme.lua")
if vim.uv.os_uname().sysname == "Linux" and vim.uv.fs_stat(desktop_theme) then
  local ok, err = pcall(dofile, desktop_theme)
  if not ok then
    vim.notify("Desktop theme: " .. tostring(err), vim.log.levels.ERROR)
  end
end

local local_config = vim.fs.joinpath(vim.fs.dirname(vim.fn.stdpath("config")), "dotfiles-local", "nvim.lua")
if vim.uv.fs_stat(local_config) then
  local ok, err = pcall(dofile, local_config)
  if not ok then
    vim.notify("Local Neovim configuration: " .. tostring(err), vim.log.levels.ERROR)
  end
end
