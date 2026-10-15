-- How do RPC edits land in the undo tree?
--
-- Run inside the test nvim via client.lua:
--   nvim --clean --headless -l probes/client.lua .nvim-test.sock "$(cat probes/undo.lua)"
--
-- Uses a scratch buffer so the user's buffers are untouched. Each case resets
-- the buffer, makes edits, then runs `:undo` once and reports what is left.
-- Cases:
--   one_call:  two nvim_buf_set_text calls inside one nvim_exec_lua request
--   undojoin:  same, but the second edit is preceded by `:undojoin`
--   seq_tick:  changedtick and undotree seq after each edit (one request)
-- The multi-request cases (separate RPC requests per edit) are driven from
-- undo_multi.sh because they need more than one request.

local buf = vim.api.nvim_create_buf(true, false)
vim.bo[buf].undolevels = 1000
local out = {}

local function reset()
  vim.api.nvim_buf_call(buf, function()
    vim.bo[buf].undolevels = -1
    vim.api.nvim_buf_set_lines(buf, 0, -1, false, { 'aaa', 'bbb' })
    vim.bo[buf].undolevels = 1000
  end)
end

local function lines()
  return table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), '|')
end

local function undo_once()
  vim.api.nvim_buf_call(buf, function() vim.cmd('silent undo') end)
end

reset()
vim.api.nvim_buf_set_text(buf, 0, 0, 0, 3, { 'AAA' })
vim.api.nvim_buf_set_text(buf, 1, 0, 1, 3, { 'BBB' })
local after = lines()
undo_once()
out.one_call = { after = after, after_one_undo = lines() }

reset()
vim.api.nvim_buf_set_text(buf, 0, 0, 0, 3, { 'AAA' })
vim.api.nvim_buf_call(buf, function() vim.cmd('undojoin') end)
vim.api.nvim_buf_set_text(buf, 1, 0, 1, 3, { 'BBB' })
after = lines()
undo_once()
out.undojoin = { after = after, after_one_undo = lines() }

reset()
local seq = {}
local function snap(label)
  local t = vim.api.nvim_buf_call(buf, function() return vim.fn.undotree() end)
  seq[#seq + 1] = { label, vim.b[buf].changedtick, t.seq_cur }
end
snap('start')
vim.api.nvim_buf_set_text(buf, 0, 0, 0, 3, { 'AAA' })
snap('edit1')
vim.api.nvim_buf_set_text(buf, 1, 0, 1, 3, { 'BBB' })
snap('edit2')
out.seq_tick = seq

vim.api.nvim_buf_delete(buf, { force = true })
return out
