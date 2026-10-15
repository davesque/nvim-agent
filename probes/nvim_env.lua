-- Is $NVIM set for processes nvim starts, and does it name this server?
--
-- Run inside the test nvim via client.lua:
--   nvim --clean --headless -l probes/client.lua .nvim-test.sock "$(cat probes/nvim_env.lua)"
--
-- Checks a vim.fn.system() child and a :terminal job (in a scratch tab that is
-- closed afterwards). The terminal job writes $NVIM to ~/agent-workspace.
local out = vim.fn.expand('~/agent-workspace/nvim_env_probe.txt')
os.remove(out)
local res = { servername = vim.v.servername }
res.system_child = vim.trim(vim.fn.system('echo "$NVIM"'))
vim.cmd('tabnew')
local term_buf = vim.api.nvim_get_current_buf()
vim.fn.jobstart({ 'sh', '-c', 'echo "$NVIM" > ' .. out }, { term = true })
vim.wait(2000, function() return vim.uv.fs_stat(out) ~= nil and vim.uv.fs_stat(out).size > 0 end)
local f = io.open(out)
res.terminal_child = f and vim.trim(f:read('*a')) or 'missing'
if f then f:close() end
vim.cmd('tabclose')
vim.api.nvim_buf_delete(term_buf, { force = true })
os.remove(out)
return res
