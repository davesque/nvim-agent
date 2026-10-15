local sock, code = arg[1], arg[2]
local ch = vim.fn.sockconnect('pipe', sock, { rpc = true })
local ok, res = pcall(vim.rpcrequest, ch, 'nvim_exec_lua', code, {})
io.stdout:write(vim.json.encode({ ok = ok, result = res }), '\n')
vim.fn.chanclose(ch)
