-- Test the terminal lifecycle with a disposable Git repo and fake CLI.
local function test()
  local temporary = vim.fn.tempname()
  vim.fn.mkdir(temporary .. "/bin", "p")
  vim.fn.mkdir(temporary .. "/project with spaces", "p")
  local root = temporary .. "/project with spaces"
  local cli = temporary .. "/bin/lazygit"
  vim.fn.writefile({
    "#!/bin/sh",
    'printf "%s\\n" "$PWD" "$@" > "$DOTFILES_GIT_TEST_LOG"',
    'printf "Git test ready\\n"',
    "read answer",
    "exit 0",
  }, cli)
  vim.fn.setfperm(cli, "rwx------")
  vim.env.DOTFILES_GIT_TEST_LOG = temporary .. "/arguments"
  vim.env.PATH = temporary .. "/bin:" .. vim.env.PATH
  vim.cmd.cd(root)
  vim.cmd.enew()
  local git = require("dotfiles.git")
  local notify = vim.notify
  local notices = {}
  vim.notify = function(message) notices[#notices + 1] = message end
  local before = #vim.api.nvim_list_tabpages()
  git.open()
  assert(#vim.api.nvim_list_tabpages() == before and #notices == 1, "non-repo must not launch or initialize")
  assert(vim.fn.isdirectory(root .. "/.git") == 0)
  assert(vim.system({ "git", "init", "-q", root }):wait().code == 0)

  git.open()
  local buffer, origin_tab = vim.api.nvim_get_current_buf(), vim.api.nvim_get_current_tabpage()
  assert(vim.bo.filetype == "lazygit" and vim.bo.buftype == "terminal")
  assert(#vim.api.nvim_list_tabpages() == before + 1)
  assert(vim.wait(5000, function() return vim.fn.filereadable(temporary .. "/arguments") == 1 end))
  local args = vim.fn.readfile(temporary .. "/arguments")
  assert(vim.uv.fs_realpath(args[1]) == vim.uv.fs_realpath(root) and args[2] == "--use-config-file", "repo/cmd arguments changed: " .. vim.inspect(args))
  assert(args[3]:match("/lazygit/config%.yml$"), "shared config was not selected")
  local first_channel = vim.b[buffer].terminal_job_id
  vim.fn.chansend(first_channel, "quit\r")
  assert(vim.wait(5000, function() return not vim.api.nvim_buf_is_valid(buffer) end), vim.inspect({
    job = vim.fn.jobwait({ first_channel }, 0), notices = notices,
    lines = vim.api.nvim_buf_is_valid(buffer) and vim.api.nvim_buf_get_lines(buffer, 0, -1, false),
  }))
  assert(#vim.api.nvim_list_tabpages() == before and not vim.api.nvim_tabpage_is_valid(origin_tab))

  -- Quitting in the background must not steal focus or erase another tab.
  git.open()
  buffer = vim.api.nvim_get_current_buf()
  local channel = vim.b[buffer].terminal_job_id
  vim.cmd.tabnew()
  local work_tab = vim.api.nvim_get_current_tabpage()
  vim.api.nvim_buf_set_lines(0, 0, -1, false, { "unsaved work" })
  vim.fn.chansend(channel, "quit\r")
  assert(vim.wait(5000, function() return not vim.api.nvim_buf_is_valid(buffer) end))
  assert(vim.api.nvim_get_current_tabpage() == work_tab)
  assert(vim.api.nvim_get_current_line() == "unsaved work")
  vim.notify = notify
  vim.fn.delete(temporary, "rf")
  print("Git terminal lifecycle tests passed")
end

local ok, err = xpcall(test, debug.traceback)
if not ok then print(err); vim.cmd("cquit 1") else vim.cmd("qa!") end
