-- Run with the configured plugins installed and all XDG paths isolated.
local temporary
local function test()
  local api = require("nvim-tree.api")
  assert(not api.tree.is_visible(), "headless startup must not open a sidebar")
  temporary = vim.fn.tempname()
  vim.fn.mkdir(temporary, "p")
  temporary = assert(vim.uv.fs_realpath(temporary))
  local function git(...)
    local argv = { "git", "-C", temporary }
    vim.list_extend(argv, { ... })
    local result = vim.system(argv, { text = true }):wait(10000)
    assert(result.code == 0, result.stderr)
  end
  vim.fn.writefile({ "first" }, temporary .. "/tracked.txt")
  vim.fn.writefile({ "ignored.log" }, temporary .. "/.gitignore")
  git("init", "-q")
  git("add", ".")
  git("-c", "user.name=Dotfiles Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "Fixture")
  vim.fn.writefile({ "changed" }, temporary .. "/tracked.txt")
  vim.fn.writefile({ "new" }, temporary .. "/.new-dotfile")
  vim.fn.writefile({ "ignored" }, temporary .. "/ignored.log")

  api.tree.open({ path = temporary })
  local function nodes()
    local result = {}
    for _, node in ipairs(api.tree.get_nodes().nodes) do result[node.name] = node end
    return result
  end
  assert(vim.wait(5000, function()
    local tracked = nodes()["tracked.txt"]
    return tracked and tracked.git_status and tracked.git_status.file == " M"
  end), "tree must show real unstaged Git status")
  local listed = nodes()
  assert(require("dotfiles.tree").root() == temporary, "Git actions must use the displayed tree root")
  assert(listed[".new-dotfile"] and listed[".new-dotfile"].git_status.file == "??", "untracked dotfiles must be visible")
  assert(not listed["ignored.log"], "ignored build files must be hidden initially")
  api.filter.git.ignored.toggle()
  assert(vim.wait(5000, function() return nodes()["ignored.log"] ~= nil end), "ignored-file toggle must reveal files")

  api.tree.find_file({ buf = temporary .. "/tracked.txt", focus = true })
  assert(vim.wait(5000, function()
    local node = api.tree.get_node_under_cursor()
    return node and node.name == "tracked.txt"
  end), "reveal must focus the requested file")
  local double_click = vim.fn.maparg("<2-LeftMouse>", "n", false, true)
  assert(type(double_click.callback) == "function", "double-click opening must be available")
  double_click.callback()
  assert(vim.api.nvim_buf_get_name(0) == temporary .. "/tracked.txt", "mouse opening must focus the file")
  assert(api.tree.is_visible(), "opening a file must retain the sidebar")
  require("dotfiles.tree").toggle()
  assert(not api.tree.is_visible(), "toggle must close the tree")
  require("dotfiles.tree").reveal()
  assert(api.tree.is_tree_buf(), "reveal must focus and reopen the tree")
  api.tree.close()
  print("Neovim tree: real Git status, dotfiles, ignored filter, reveal and mouse action passed")
end

local ok, err = xpcall(test, debug.traceback)
if temporary then vim.fn.delete(temporary, "rf") end
if not ok then
  vim.api.nvim_err_writeln(err)
  vim.cmd("cquit 1")
else
  vim.cmd("qa!")
end
