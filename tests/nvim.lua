-- Run after loading init.lua with all XDG directories redirected to a temporary
-- directory and -i NONE. Set DOTFILES_NVIM_NO_PLUGINS=1 for the offline test.
local function test()
  assert(vim.g.mapleader == " ", "dotfiles init.lua was not loaded")
  assert(vim.fn.has("nvim-0.11.3") == 1, "Neovim 0.11.3+ required")
  assert(vim.o.clipboard == "", "ordinary Vim registers should stay independent")
  assert(vim.fn.maparg("<CR>", "i") == "", "Enter must retain its native behavior")
  local tab = vim.fn.maparg("<Tab>", "i", false, true)
  assert(vim.tbl_isempty(tab) or tab.desc == "vim.snippet.jump if active, otherwise <Tab>", "Tab must retain its native behavior")
  assert(not vim.diagnostic.config().virtual_text, "diagnostics should avoid inline noise")

  local temporary = vim.fn.tempname()
  vim.fn.mkdir(temporary, "p")
  local file = temporary .. "/agent-edit.txt"
  vim.fn.writefile({ "initial" }, file)
  vim.cmd.edit(vim.fn.fnameescape(file))
  vim.fn.writefile({ "external change with a different size" }, file)
  vim.cmd("checktime")
  assert(vim.api.nvim_get_current_line() == "external change with a different size", "clean agent edit was not reloaded")
  vim.api.nvim_buf_set_lines(0, 0, -1, false, { "unsaved local work" })
  vim.fn.writefile({ "second external change" }, file)
  -- Avoid an interactive conflict prompt while verifying Neovim preserves edits.
  local conflict_seen = false
  local autocmd = vim.api.nvim_create_autocmd("FileChangedShell", {
    callback = function()
      conflict_seen = true
      vim.v.fcs_choice = ""
    end,
  })
  vim.cmd("checktime")
  vim.api.nvim_del_autocmd(autocmd)
  assert(conflict_seen, "external/local conflict was not detected")
  assert(vim.api.nvim_get_current_line() == "unsaved local work", "unsaved local edits were overwritten")
  vim.cmd("enew!")

  vim.bo.filetype = "markdown"
  assert(vim.wo.wrap and vim.wo.linebreak, "prose should wrap visually")
  assert(vim.bo.textwidth == 0 and not vim.bo.formatoptions:find("t", 1, true), "prose must not reflow automatically")
  assert(not vim.wo.spell, "spelling should be opt-in")
  vim.bo.filetype = "lua"
  assert(vim.bo.shiftwidth == 2, "Lua indentation")

  local lsp = require("dotfiles.lsp")
  lsp.setup()
  local python = vim.fn.exepath("python3")
  if python ~= "" then
    vim.fn.mkdir(temporary .. "/.venv/bin", "p")
    assert(vim.uv.fs_symlink(python, temporary .. "/.venv/bin/python"))
    local old_env = vim.env.VIRTUAL_ENV
    vim.env.VIRTUAL_ENV = "/not-this-project"
    assert(lsp.python_path(temporary) == temporary .. "/.venv/bin/python", "project venv must win")
    local config = { root_dir = temporary, settings = {} }
    vim.lsp.config.basedpyright.before_init({ rootUri = vim.uri_from_fname(temporary) }, config)
    assert(config.settings.python.pythonPath == temporary .. "/.venv/bin/python", "venv not passed to basedpyright")
    config.settings.python.pythonPath = "/explicit/override"
    vim.lsp.config.basedpyright.before_init({}, config)
    assert(config.settings.python.pythonPath == "/explicit/override", "explicit Python override overwritten")
    local standalone = { settings = {} }
    vim.lsp.config.basedpyright.before_init({ rootUri = vim.NIL }, standalone)
    assert(standalone.settings.python.pythonPath == python, "standalone Python JSON null root must use PATH fallback")
    vim.env.VIRTUAL_ENV = old_env
  end
  assert(vim.lsp.config.texlab.settings.texlab.build.onSave == false, "LaTeX build on save must be disabled")

  -- Exercise attach behavior without launching a real server or accessing a repo.
  local get_client = vim.lsp.get_client_by_id
  local enable_completion = vim.lsp.completion.enable
  local fake = { id = 4242, name = "ruff", server_capabilities = { hoverProvider = true }, supports_method = function() return true end }
  local completion_options
  vim.lsp.get_client_by_id = function() return fake end
  vim.lsp.completion.enable = function(_, _, _, options) completion_options = options end
  vim.api.nvim_exec_autocmds("LspAttach", { buffer = 0, group = "DotfilesLsp", data = { client_id = fake.id } })
  vim.lsp.get_client_by_id = get_client
  vim.lsp.completion.enable = enable_completion
  assert(not fake.server_capabilities.hoverProvider, "Ruff must defer hover to basedpyright")
  assert(completion_options.autotrigger == false, "completion must be explicit")
  assert(vim.fn.maparg("<Space>cf", "n") ~= "", "explicit formatting mapping absent")

  if vim.env.DOTFILES_NVIM_NO_PLUGINS ~= "1" then
    local plugins = require("lazy.core.config").plugins
    local count = 0
    for _, plugin in pairs(plugins) do
      count = count + 1
      assert(plugin._.installed, plugin.name .. " missing")
    end
    assert(count == 6, "expect five functional plugins and lazy.nvim")
    assert(type(require("mini.pick").builtin.files) == "function", "picker failed to load")
    assert(vim.g.vimtex_compiler_latexmk.continuous == 0, "LaTeX must compile only on request")
    assert(vim.g.vimtex_view_automatic == 0, "PDF viewer must open only on request")
  end
  vim.cmd("enew!")
  vim.fn.delete(temporary, "rf")
  print("Neovim smoke tests passed")
end

local ok, err = xpcall(test, debug.traceback)
if not ok then
  vim.api.nvim_err_writeln(err)
  vim.cmd("cquit 1")
else
  vim.cmd("qa!")
end
