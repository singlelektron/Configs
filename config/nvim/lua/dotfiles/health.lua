local M = {}

function M.check()
  local health = vim.health
  health.start("Dotfiles")
  if vim.fn.has("nvim-0.11.3") == 1 then
    health.ok("Neovim >= 0.11.3")
  else
    health.error("Neovim >= 0.11.3 is required for native LSP configuration")
  end
  local root = vim.fn.stdpath("data") .. "/dotfiles-lazy"
  for _, name in ipairs({ "lazy.nvim", "nvim-lspconfig", "mini.pick", "gitsigns.nvim", "vim-fugitive", "vimtex", "nvim-tree.lua", "lualine.nvim" }) do
    if vim.uv.fs_stat(root .. "/" .. name .. "/.git") then
      health.ok(name .. " installed")
    else
      health.warn(name .. " missing; run :DotfilesInstall when online")
    end
  end
  health.start("External tools (install outside Neovim)")
  for _, tool in ipairs({ "git", "lazygit", "rg", "fd", "rust-analyzer", "basedpyright-langserver", "ruff", "texlab", "latexmk" }) do
    if vim.fn.executable(tool) == 1 then
      if tool == "rust-analyzer" then
        local result = vim.system({ tool, "--version" }, { text = true }):wait(5000)
        if result.code ~= 0 then
          health.warn("rust-analyzer is on PATH but cannot run; install its rustup component or system package")
        else
          health.ok(vim.trim(result.stdout))
        end
      else
        health.ok(tool .. " available")
      end
    else
      health.warn(tool .. " missing; the corresponding feature will be unavailable")
    end
  end
  if vim.fn.executable("marksman") == 1 then
    health.ok("Optional Markdown server marksman available")
  else
    health.info("Optional marksman absent; Markdown editing, spelling and search still work")
  end
  if vim.env.SSH_CONNECTION or vim.env.SSH_TTY then
    health.info("SSH: <Space>y copies via OSC 52; paste using the local terminal's paste key")
  end
end

return M
