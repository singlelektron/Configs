local M = {}

-- A project's .venv takes precedence over an unrelated activated environment.
function M.python_path(root)
  local candidates = {}
  if type(root) == "string" and root ~= "" then
    candidates[#candidates + 1] = vim.fs.joinpath(root, ".venv", "bin", "python")
  end
  if vim.env.VIRTUAL_ENV and vim.env.VIRTUAL_ENV ~= "" then
    candidates[#candidates + 1] = vim.fs.joinpath(vim.env.VIRTUAL_ENV, "bin", "python")
  end
  candidates[#candidates + 1] = vim.fn.exepath("python3")
  for _, path in ipairs(candidates) do
    if path ~= "" and vim.fn.executable(path) == 1 then
      return path
    end
  end
end

function M.setup()
  local group = vim.api.nvim_create_augroup("DotfilesLsp", { clear = true })
  vim.api.nvim_create_autocmd("LspAttach", {
    group = group,
    callback = function(event)
      local client = vim.lsp.get_client_by_id(event.data.client_id)
      if not client then
        return
      end
      if client.name == "ruff" then
        client.server_capabilities.hoverProvider = false
      end
      if client:supports_method("textDocument/completion") then
        vim.lsp.completion.enable(true, client.id, event.buf, { autotrigger = false })
      end
      vim.keymap.set("n", "gd", vim.lsp.buf.definition, { buffer = event.buf, desc = "LSP definition" })
      vim.keymap.set("n", "<leader>cf", function()
        local clients = vim.lsp.get_clients({ bufnr = event.buf, method = "textDocument/formatting" })
        -- Ruff owns Python formatting; basedpyright owns types and navigation.
        local formatter
        for _, candidate in ipairs(clients) do
          if candidate.name == "ruff" or not formatter then
            formatter = candidate
          end
        end
        if formatter then
          vim.lsp.buf.format({ bufnr = event.buf, id = formatter.id, timeout_ms = 3000 })
        else
          vim.notify("No formatter attached to this buffer.", vim.log.levels.INFO)
        end
      end, { buffer = event.buf, desc = "Format buffer explicitly" })
      -- K, grn, gra, grr, gri, gO and [d / ]d use Neovim's own mappings.
    end,
  })

  vim.lsp.config("basedpyright", {
    before_init = function(params, config)
      config.settings = config.settings or {}
      config.settings.python = config.settings.python or {}
      -- Standalone files use JSON null (vim.NIL), which is truthy in Lua.
      local root = type(params.rootUri) == "string" and vim.uri_to_fname(params.rootUri) or config.root_dir
      if not config.settings.python.pythonPath then
        config.settings.python.pythonPath = M.python_path(root)
      end
    end,
    settings = {
      basedpyright = {
        disableOrganizeImports = true,
        analysis = { diagnosticMode = "openFilesOnly" },
      },
    },
  })
  vim.lsp.config("texlab", {
    settings = { texlab = { build = { onSave = false, forwardSearchAfter = false } } },
  })
  -- Preserve Rust's standard cargo-check diagnostics, proc macros and build-script
  -- analysis. These may run Cargo; formatting and LaTeX builds remain explicit.
  for _, name in ipairs({ "rust_analyzer", "basedpyright", "ruff", "texlab", "marksman" }) do
    local config = vim.lsp.config[name]
    if config and config.cmd and vim.fn.executable(config.cmd[1]) == 1 then
      vim.lsp.enable(name)
    end
  end
end

return M
