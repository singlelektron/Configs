-- Optional integration check; requires installed plugins and real language servers.
-- Load the dotfiles init.lua first and isolate XDG_STATE_HOME/XDG_CACHE_HOME.
-- Set DOTFILES_INTEGRATION_ROOT to a NEW directory inside a temporary directory.
-- Fixtures and build output are retained there for inspection; user projects are untouched.
-- DOTFILES_SKIP_TEX_BUILD=1 still verifies texlab/VimTeX without requiring TeX Live.
local function run()
  local root = assert(vim.env.DOTFILES_INTEGRATION_ROOT, "set DOTFILES_INTEGRATION_ROOT to a new fixture directory")
  assert(root:sub(1, 1) == "/" and not vim.uv.fs_stat(root), "fixture directory must be absolute and not exist")
  assert(vim.fn.mkdir(root, "p") == 1, "could not create fixtures")
  local skip_tex_build = vim.env.DOTFILES_SKIP_TEX_BUILD == "1"
  local dependencies = { "rust-analyzer", "cargo", "basedpyright-langserver", "ruff", "texlab", "python3" }
  if not skip_tex_build then dependencies[#dependencies + 1] = "latexmk" end
  for _, command in ipairs(dependencies) do
    assert(vim.fn.executable(command) == 1, "missing integration dependency: " .. command)
  end
  local function write(relative, lines)
    local path = root .. "/" .. relative
    vim.fn.mkdir(vim.fs.dirname(path), "p")
    assert(vim.fn.writefile(lines, path) == 0)
    return path
  end
  local function edit(path)
    vim.cmd.edit({ path, bang = true })
    return vim.api.nvim_get_current_buf()
  end
  local function attached(name, buffer)
    local client
    assert(vim.wait(45000, function()
      client = vim.lsp.get_clients({ bufnr = buffer, name = name })[1]
      return client and client.initialized
    end, 100), name .. " did not attach; see " .. vim.lsp.log.get_filename())
    return client
  end
  local function request(client, method, params, buffer)
    local response, err = client:request_sync(method, params, 15000, buffer)
    assert(response and not response.err, method .. ": " .. vim.inspect(response or err))
    return response.result
  end
  local function format(client, buffer)
    local edits = request(client, "textDocument/formatting", {
      textDocument = { uri = vim.uri_from_bufnr(buffer) },
      options = { tabSize = 4, insertSpaces = true },
    }, buffer)
    assert(type(edits) == "table" and #edits > 0, client.name .. " returned no formatting edits")
    vim.lsp.util.apply_text_edits(edits, buffer, client.offset_encoding)
  end

  write("rust/Cargo.toml", { '[package]', 'name = "dotfiles-integration"', 'version = "0.1.0"', 'edition = "2021"' })
  local rust_file = write("rust/src/main.rs", {
    "fn double(value: i32) -> i32 { value * 2 }",
    'fn main(){let answer=double(21);println!("{answer}");}',
  })
  local rust_buffer = edit(rust_file)
  local rust = attached("rust_analyzer", rust_buffer)
  local hover
  assert(vim.wait(60000, function()
    local response = rust:request_sync("textDocument/hover", {
      textDocument = { uri = vim.uri_from_bufnr(rust_buffer) },
      position = { line = 0, character = 4 },
    }, 1000, rust_buffer)
    hover = response and response.result
    return hover and hover ~= vim.NIL and hover.contents
  end, 200), "Rust hover was unavailable after workspace initialization")
  assert(vim.inspect(hover):find("i32", 1, true), "Rust hover omitted the function type")
  format(rust, rust_buffer)
  assert(table.concat(vim.api.nvim_buf_get_lines(rust_buffer, 0, -1, false), "\n"):find("fn main() {", 1, true))
  print("PASS: rust-analyzer attached, returned typed hover, and formatted Rust")

  write("python/pyproject.toml", {
    '[project]', 'name = "dotfiles-integration"', 'version = "0.1.0"',
    '[tool.basedpyright]', 'typeCheckingMode = "standard"',
  })
  local venv = vim.system({ vim.fn.exepath("python3"), "-m", "venv", "--without-pip", root .. "/python/.venv" }, { text = true }):wait(30000)
  assert(venv.code == 0, "fixture venv failed: " .. (venv.stderr or ""))
  local python_file = write("python/main.py", { "import os", 'count: int = "wrong"', "value=  1" })
  local python_buffer = edit(python_file)
  local basedpyright = attached("basedpyright", python_buffer)
  local ruff = attached("ruff", python_buffer)
  assert(basedpyright.config.settings.python.pythonPath == root .. "/python/.venv/bin/python", "project interpreter was not selected")
  assert(not ruff.server_capabilities.hoverProvider, "Ruff should leave hover to basedpyright")
  local diagnostics
  assert(vim.wait(45000, function()
    diagnostics = vim.diagnostic.get(python_buffer)
    local type_error, unused_import = false, false
    for _, diagnostic in ipairs(diagnostics) do
      if diagnostic.code == "reportAssignmentType" then type_error = true end
      if diagnostic.code == "F401" then unused_import = true end
    end
    return type_error and unused_import
  end, 100), "expected basedpyright type error and Ruff unused-import diagnostic: " .. vim.inspect(diagnostics))
  write("python-diagnostics.json", { vim.json.encode(diagnostics) })
  format(ruff, python_buffer)
  assert(table.concat(vim.api.nvim_buf_get_lines(python_buffer, 0, -1, false), "\n"):find("value = 1", 1, true))
  print("PASS: basedpyright + Ruff attached, selected .venv, reported type/lint errors, and formatted Python")

  write("latex/.latexmkrc", { "$pdf_mode = 1;" })
  local tex_file = write("latex/main.tex", {
    "\\documentclass{article}", "\\begin{document}",
    "A minimal integration check: $e^{i\\pi}+1=0$.", "\\end{document}",
  })
  local tex_buffer = edit(tex_file)
  attached("texlab", tex_buffer)
  assert(vim.bo.filetype == "tex", "LaTeX filetype was not detected")
  assert(vim.fn.exists(":VimtexInfo") == 2, "VimTeX did not initialize")
  assert(vim.g.vimtex_compiler_latexmk.continuous == 0, "compilation must be one-shot")
  assert(vim.g.vimtex_view_automatic == 0, "integration must not open a PDF viewer")
  assert(vim.fn.filereadable(root .. "/latex/main.pdf") == 0, "PDF existed before explicit compile")
  if skip_tex_build then
    if vim.fn.executable("latexmk") == 0 then
      assert(vim.g.vimtex_compiler_enabled == 0, "missing TeX should disable the compiler quietly")
    end
    print("PASS: texlab attached and VimTeX initialized; SKIP: explicit TeX build (DOTFILES_SKIP_TEX_BUILD=1)")
  else
    assert(vim.fn.exists(":VimtexCompile") == 2, "VimTeX compiler command unavailable")
    vim.cmd("VimtexCompile")
    assert(vim.wait(60000, function()
      local running = vim.fn.eval("b:vimtex.compiler.is_running()")
      return vim.fn.eval("get(get(b:, 'vimtex', {}), 'compiler', {}).status") == 2
        and (running == false or running == 0)
    end, 100), "VimTeX single-shot compilation failed; inspect " .. root .. "/latex")
    local pdf = vim.uv.fs_stat(root .. "/latex/main.pdf")
    assert(pdf and pdf.size > 100, "VimTeX did not produce a nonempty PDF")
    print("PASS: texlab attached and explicit VimTeX compilation produced a PDF and stopped")
  end
  print("Integration artifacts: " .. root)
end

local ok, err = xpcall(run, debug.traceback)
for _, client in ipairs(vim.lsp.get_clients()) do client:stop(true) end
if not ok then
  vim.api.nvim_err_writeln(err)
  vim.cmd("cquit 1")
else
  vim.cmd("qa!")
end
