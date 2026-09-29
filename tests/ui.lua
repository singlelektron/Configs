-- Run with init.lua, installed locked plugins, isolated XDG directories and -i
-- NONE. This exercises registered mouse callbacks; graphical rendering remains
-- a separate manual check.
local temporary = vim.fn.tempname()

local function test()
  local lualine = require("lualine")
  local tree = require("nvim-tree.api")
  local ui = require("dotfiles.ui")
  ui.apply_palette()
  assert(vim.o.mouse == "a", "mouse support must be enabled")
  assert(vim.api.nvim_get_hl(0, { name = "Normal" }).bg == nil, "editing background should inherit terminal transparency")
  assert(vim.api.nvim_get_hl(0, { name = "NormalFloat" }).bg == tonumber("1b2230", 16), "float background should stay readable")

  vim.fn.mkdir(temporary, "p")
  local function git(...)
    local result = vim.system(vim.list_extend({ "git", "-C", temporary }, { ... }), { text = true }):wait(10000)
    assert(result.code == 0, result.stderr)
    return result.stdout
  end
  git("init", "--initial-branch=topic%{1+1}")
  local filename = "tracked%{1+1}.txt"
  local file = temporary .. "/" .. filename
  vim.fn.writefile({ "original" }, file)
  git("add", "--", filename)
  git("-c", "user.name=Dotfiles UI Test", "-c", "user.email=dotfiles-test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-m", "test fixture")
  vim.cmd.cd(vim.fn.fnameescape(temporary))
  vim.o.columns = 160
  vim.cmd.edit(vim.fn.fnameescape(file))
  tree.tree.close()
  local tracked_buf = vim.api.nvim_get_current_buf()

  local function rendered(raw, tabline)
    return vim.api.nvim_eval_statusline(raw, { use_tabline = tabline, maxwidth = 160 }).str
  end
  local function click_label(label, button)
    local raw = lualine.tabline()
    local pattern = "%%(%d+)@v:lua%.require'lualine%.utils%.fn_store'%.call_fn@ ([^%%]-) %%T"
    for id, text in raw:gmatch(pattern) do
      if vim.trim(text) == label then
        require("lualine.utils.fn_store").call_fn(tonumber(id), 1, button or "l", "")
        return
      end
    end
    error("Clickable label is absent: " .. label)
  end
  local function settle(condition, message)
    assert(vim.wait(5000, condition, 20), message)
  end

  local line = rendered(lualine.tabline(), true)
  assert(line:find(filename, 1, true), "buffer filename percent characters must render literally")
  assert(line:find("Files", 1, true) and line:find("Git", 1, true) and line:find("Diff", 1, true), "visible mouse actions missing")
  settle(function() return rendered(lualine.statusline(true), false):find("topic%{1+1}", 1, true) ~= nil end, "branch percent characters must render literally")

  -- Click through lualine's registered callbacks, without mocking the plugins.
  click_label("Files")
  settle(function() return tree.tree.is_visible() end, "Files click did not open the tree")
  click_label("Files")
  settle(function() return not tree.tree.is_visible() end, "Files click did not close the tree")

  -- Exercise the callback encoded in real buffer-tab output.
  vim.cmd.enew()
  local other_buf = vim.api.nvim_get_current_buf()
  assert(lualine.tabline():find("%" .. tracked_buf .. "@LualineSwitchBuffer@", 1, true), "buffer tab is not clickable")
  vim.fn.LualineSwitchBuffer(tracked_buf, 1, "l", "")
  assert(vim.api.nvim_get_current_buf() == tracked_buf and tracked_buf ~= other_buf, "buffer click did not switch files")

  local config = lualine.get_config()
  config.sections.lualine_b[1].on_click(1, "l", "")
  settle(function() return vim.bo.filetype == "fugitive" end, "branch click did not open Fugitive status")
  vim.cmd("close")
  vim.api.nvim_set_current_buf(tracked_buf)
  vim.api.nvim_buf_set_lines(0, 0, -1, false, { "unsaved working copy" })
  click_label("Diff")
  settle(function() return vim.wo.diff end, "Diff click did not open a real tracked-file diff")
  assert(vim.fn.readfile(file)[1] == "original", "Diff click must not write the file")
  vim.cmd("diffoff!")
  vim.cmd("only!")
  vim.api.nvim_set_current_buf(tracked_buf)
  vim.bo.modified = false

  -- Reject untracked files and ignore right clicks without opening new windows.
  vim.cmd.edit(vim.fn.fnameescape(temporary .. "/new.txt"))
  local notifications = {}
  local previous_notify = vim.notify
  vim.notify = function(message) notifications[#notifications + 1] = message end
  click_label("Diff")
  settle(function() return #notifications > 0 end, "untracked Diff needs a useful message")
  vim.notify = previous_notify
  assert(not vim.wo.diff and #vim.api.nvim_list_wins() == 1, "untracked Diff opened a window")
  assert(notifications[1]:find("not tracked", 1, true), "untracked Diff message is unclear")
  click_label("Files", "r")
  vim.wait(50, function() return false end)
  assert(not tree.tree.is_visible(), "right-click must not trigger the Files action")
  print("Neovim UI integration: palette, escaped labels, buffer/tree/Fugitive clicks and safe diff passed")
end

local ok, err = xpcall(test, debug.traceback)
vim.fn.delete(temporary, "rf")
if not ok then
  vim.api.nvim_err_writeln(err)
  vim.cmd("cquit 1")
else
  vim.cmd("qa!")
end
