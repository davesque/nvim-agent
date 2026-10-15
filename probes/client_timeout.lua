-- Can the dependency-free client enforce its own timeout?
--
-- macOS ships no `timeout` command (it comes from Homebrew coreutils), so the
-- shipped client cannot rely on it. This is client.lua plus a libuv timer that
-- exits the process if the request has not returned after TIMEOUT_MS.
-- The question is whether the timer fires while vim.rpcrequest is waiting.
--
-- It also stops its own default server socket first. Every nvim, including a
-- headless `-l` client, listens on $TMPDIR/nvim.$USER/*/nvim.<pid>.0, and
-- os.exit() or SIGKILL leaves that file behind, where discovery would find it.
--
-- Usage: nvim --clean --headless -l probes/client_timeout.lua SOCK CODE [TIMEOUT_MS]
-- Prints {ok, result} JSON, or {ok=false, error="timeout"} and exits 124.

local sock, code, ms = arg[1], arg[2], tonumber(arg[3] or '2000')
vim.fn.serverstop(vim.v.servername)
local timer = vim.uv.new_timer()
timer:start(ms, 0, function()
  io.stdout:write(vim.json.encode({ ok = false, error = 'timeout' }), '\n')
  os.exit(124)
end)
local ch = vim.fn.sockconnect('pipe', sock, { rpc = true })
local ok, res = pcall(vim.rpcrequest, ch, 'nvim_exec_lua', code, {})
timer:stop()
io.stdout:write(vim.json.encode({ ok = ok, result = res }), '\n')
vim.fn.chanclose(ch)
