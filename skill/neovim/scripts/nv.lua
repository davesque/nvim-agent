-- nv: drive a running Neovim over its msgpack-rpc socket, safely.
--
-- Run as: nvim --clean --headless -l nv.lua [options] <command> [args]
-- (the `nv` shell wrapper next to this file does that).
--
-- Every command prints one JSON object on stdout. See SKILL.md for usage and
-- docs/design.md in the repo for why each safety rule exists.

local USAGE = [==[
usage: nv [options] <command> [args]

commands:
  find               list running nvim instances
  state              mode, cwd, current buffer, windows, loaded file buffers
  read [PATH [START [END]]]
                     lines of a loaded buffer (default: current), 1-based inclusive
  reload PATH...     reload loaded buffers from disk after editing the files
  lua [CODE|-]       run Lua in nvim (code from stdin if omitted or -)
  ex CMD             run an Ex command, output captured

options:
  --sock PATH        target socket (default: $NV_SOCK, then $NVIM, then find)
  --pane %N          target the instance running in this tmux pane
  --timeout MS       hard timeout for the whole call (default 5000)
  --any-mode         let lua/ex run outside normal and terminal mode
]==]

-- Stop this client's own default server socket right away. Otherwise a
-- client that exits via os.exit (the timeout path) leaves a stale socket
-- where `find` would mistake it for an editor.
local own_socket = vim.v.servername
if own_socket ~= '' then
  vim.fn.serverstop(own_socket)
  -- serverstop removes the socket but not the per-process directory nvim made
  -- for it; remove that too (fails harmlessly if it is not empty).
  vim.uv.fs_rmdir(vim.fs.dirname(own_socket))
end

local function emit(obj, code)
  io.stdout:write(vim.json.encode(obj), '\n')
  io.stdout:flush()
  os.exit(code or (obj.ok and 0 or 1))
end

local function fail(err, message, extra)
  local obj = { ok = false, error = err, message = message }
  for k, v in pairs(extra or {}) do
    obj[k] = v
  end
  emit(obj)
end

-- Argument parsing ----------------------------------------------------------

local opts = { timeout = 5000, any_mode = false }
local rest = {}
do
  local i = 1
  while i <= #arg do
    local a = arg[i]
    if a == '--sock' or a == '--pane' or a == '--timeout' then
      local v = arg[i + 1]
      if not v then
        fail('usage', a .. ' needs a value')
      end
      opts[a:sub(3)] = v
      i = i + 2
    elseif a == '--any-mode' then
      opts.any_mode = true
      i = i + 1
    elseif a == '-h' or a == '--help' or a == 'help' then
      io.stdout:write(USAGE)
      os.exit(0)
    else
      rest[#rest + 1] = a
      i = i + 1
    end
  end
end
opts.timeout = tonumber(opts.timeout)
if not opts.timeout or opts.timeout <= 0 then
  fail('usage', '--timeout must be a positive number of milliseconds')
end
local command = table.remove(rest, 1)
if not command then
  io.stdout:write(USAGE)
  os.exit(2)
end

-- Hard timeout ---------------------------------------------------------------
-- vim.rpcrequest has no timeout of its own, and a prompt in the editor can make
-- it wait forever. This timer fires even while rpcrequest is waiting. Exiting
-- the process closes the connection, and nvim drops a request whose client
-- has disconnected, so a timed-out call has no later side effect.

local timer = vim.uv.new_timer()
timer:start(opts.timeout, 0, function()
  io.stdout:write(
    vim.json.encode({
      ok = false,
      error = 'timeout',
      message = ('no reply within %d ms; the editor may be busy or showing a prompt'):format(
        opts.timeout
      ),
    }),
    '\n'
  )
  io.stdout:flush()
  os.exit(124)
end)

-- Connections ----------------------------------------------------------------

local function connect(path)
  local ok, ch = pcall(vim.fn.sockconnect, 'pipe', path, { rpc = true })
  if not ok or ch == 0 then
    return nil, tostring(ch)
  end
  return ch
end

local function request(ch, method, ...)
  local ok, res = pcall(vim.rpcrequest, ch, method, ...)
  if not ok then
    return nil, tostring(res)
  end
  return res
end

-- Runs inside nvim. Shared by every payload: returns an error table when the
-- editor is in a mode the command must not run in, else nil. Running it inside
-- the same request as the action makes the check atomic: keys the user types
-- while a request runs are applied only after it returns.
local GATE = [[
local function gate(strict)
  local m = vim.api.nvim_get_mode().mode
  if m:sub(1, 1) == 'r' then
    return { ok = false, error = 'blocked', mode = m,
      message = 'the editor is showing a prompt; ask the user to dismiss it' }
  end
  if strict and m ~= 'n' and m ~= 'nt' and m ~= 't' then
    return { ok = false, error = 'mode', mode = m,
      message = 'the user is in mode ' .. m .. '; try again when they are back in normal mode' }
  end
end
local function find_buf(path)
  if path == nil or path == '' then
    return vim.api.nvim_get_current_buf()
  end
  for _, b in ipairs(vim.api.nvim_list_bufs()) do
    local name = vim.api.nvim_buf_get_name(b)
    if name ~= '' and vim.api.nvim_buf_is_loaded(b)
      and (name == path or vim.uv.fs_realpath(name) == path) then
      return b
    end
  end
end
local function bufinfo(b)
  return {
    buf = b,
    path = vim.api.nvim_buf_get_name(b),
    filetype = vim.bo[b].filetype,
    modified = vim.bo[b].modified,
    changedtick = vim.b[b].changedtick,
    line_count = vim.api.nvim_buf_line_count(b),
  }
end
]]

local PAYLOAD = {}

PAYLOAD.state = GATE
  .. [[
local err = gate(false)
if err then return err end
local cur = vim.api.nvim_get_current_buf()
local windows = {}
for _, w in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
  local b = vim.api.nvim_win_get_buf(w)
  windows[#windows + 1] = {
    win = w,
    path = vim.api.nvim_buf_get_name(b),
    buftype = vim.bo[b].buftype,
    cursor = vim.api.nvim_win_get_cursor(w),
    current = w == vim.api.nvim_get_current_win(),
  }
end
local buffers = {}
for _, b in ipairs(vim.api.nvim_list_bufs()) do
  if vim.api.nvim_buf_is_loaded(b) and vim.bo[b].buftype == ''
    and vim.api.nvim_buf_get_name(b) ~= '' then
    buffers[#buffers + 1] = bufinfo(b)
  end
end
return {
  ok = true,
  mode = vim.api.nvim_get_mode().mode,
  cwd = vim.fn.getcwd(),
  current = vim.tbl_extend('force', bufinfo(cur), { buftype = vim.bo[cur].buftype }),
  cursor = vim.api.nvim_win_get_cursor(0),
  windows = windows,
  buffers = buffers,
}
]]

PAYLOAD.read = GATE
  .. [[
local path, first, last = ...
if first == vim.NIL then first = nil end
if last == vim.NIL then last = nil end
local err = gate(false)
if err then return err end
local b = find_buf(path)
if not b then
  return { ok = false, error = 'not_loaded', path = path,
    message = 'no loaded buffer for this path; read the file from disk instead' }
end
local n = vim.api.nvim_buf_line_count(b)
first = first or 1
last = last or n
if first < 1 or last > n or first > last then
  return { ok = false, error = 'usage', message = ('range %d-%d outside 1-%d'):format(first, last, n) }
end
local info = bufinfo(b)
info.ok = true
info.start = first
info.lines = vim.api.nvim_buf_get_lines(b, first - 1, last, false)
return info
]]

PAYLOAD.reload = GATE
  .. [[
local paths = ...
local err = gate(true)
if err then return err end
local results = {}
for _, path in ipairs(paths) do
  local r = { path = path }
  local b = find_buf(path)
  if not b then
    r.status = 'not_loaded'
  elseif vim.bo[b].modified then
    r.status = 'conflict'
    r.message = 'buffer has unsaved changes by the user; not reloaded'
  elseif not vim.uv.fs_stat(path) then
    r.status = 'missing'
    r.message = 'file no longer exists on disk; buffer left as is'
  else
    local ok, disk = pcall(vim.fn.readfile, path)
    if ok and vim.deep_equal(disk, vim.api.nvim_buf_get_lines(b, 0, -1, false)) then
      r.status = 'unchanged'
    else
      -- :edit, not :checktime. :checktime raises a W11/W12 dialog when
      -- 'autoread' is off, which hangs every later request.
      local eok, emsg = pcall(vim.api.nvim_buf_call, b, function()
        vim.api.nvim_exec2('edit', { output = true })
      end)
      r.status = eok and 'reloaded' or 'error'
      r.message = not eok and tostring(emsg) or nil
    end
  end
  results[#results + 1] = r
end
return { ok = true, results = results }
]]

-- Agent code runs under :lua via nvim_exec2 with output captured, because a
-- multi-line print or vim.notify from nvim_exec_lua raises a hit-enter prompt
-- that hangs both the editor and this request.
PAYLOAD.lua = GATE
  .. [[
local code, strict = ...
local err = gate(strict)
if err then return err end
local fn, cerr = loadstring(code, '=agent')
if not fn then
  return { ok = false, error = 'lua_error', message = cerr }
end
_G.__nv = { fn = fn }
local cok, cap = pcall(vim.api.nvim_exec2,
  'lua _G.__nv.res = { pcall(_G.__nv.fn) }', { output = true })
local res = _G.__nv.res
_G.__nv = nil
if not cok or not res then
  return { ok = false, error = 'lua_error', message = tostring(cap) }
end
local output = cap.output
if not res[1] then
  return { ok = false, error = 'lua_error', message = tostring(res[2]), output = output }
end
local value = res[2]
local jok, json = pcall(vim.json.encode, value == nil and vim.NIL or value)
if not jok then
  json = vim.json.encode(vim.inspect(value))
end
return { ok = true, value_json = json, output = output }
]]

PAYLOAD.ex = GATE
  .. [[
local cmd, strict = ...
local err = gate(strict)
if err then return err end
local ok, res = pcall(vim.api.nvim_exec2, cmd, { output = true })
if not ok then
  return { ok = false, error = 'ex_error', message = tostring(res) }
end
return { ok = true, output = res.output }
]]

PAYLOAD.info = [[
return {
  pid = vim.fn.getpid(),
  servername = vim.v.servername,
  tmux_pane = vim.env.TMUX_PANE,
  cwd = vim.fn.getcwd(),
  file = vim.api.nvim_buf_get_name(0),
}
]]

-- Discovery ------------------------------------------------------------------

-- Directories holding default sockets: the sibling directories of this
-- client's own default socket dir ($TMPDIR/nvim.$USER/* on macOS).
-- NV_SOCKET_DIRS (colon-separated) overrides this, mainly for tests.
local function socket_dirs()
  local env = os.getenv('NV_SOCKET_DIRS')
  if env and env ~= '' then
    return vim.split(env, ':', { trimempty = true })
  end
  if own_socket == '' then
    return {}
  end
  local own_dir = vim.fs.dirname(own_socket)
  local parent = vim.fs.dirname(own_dir)
  if not vim.fs.basename(parent):match('^nvim%.') then
    return { own_dir }
  end
  local dirs = {}
  for name, t in vim.fs.dir(parent) do
    if t == 'directory' then
      dirs[#dirs + 1] = vim.fs.joinpath(parent, name)
    end
  end
  return dirs
end

local function list_sockets()
  local socks = {}
  for _, dir in ipairs(socket_dirs()) do
    for name, t in vim.fs.dir(dir) do
      local path = vim.fs.joinpath(dir, name)
      if (t == 'socket' or t == 'fifo') and path ~= own_socket then
        socks[#socks + 1] = path
      end
    end
  end
  table.sort(socks)
  return socks
end

-- Map a server pid to its tmux pane without asking the editor: walk the
-- parent chain (server -> TUI nvim -> pane shell) until it reaches a pane's
-- pane_pid. Used for editors that are showing a prompt and cannot be asked.
local function pane_for_pid(pid)
  if not pid or vim.fn.executable('tmux') == 0 then
    return nil
  end
  -- No $TMUX check: the agent itself may run outside tmux while the editor
  -- runs inside it. Without a tmux server this prints nothing useful.
  local panes = {}
  for _, line in ipairs(vim.fn.systemlist({ 'tmux', 'list-panes', '-a', '-F', '#{pane_pid} #{pane_id}' })) do
    local ppid, id = line:match('^(%d+) (%%%d+)$')
    if ppid then
      panes[tonumber(ppid)] = id
    end
  end
  local parent = {}
  for _, line in ipairs(vim.fn.systemlist({ 'ps', '-axo', 'pid=,ppid=' })) do
    local a, b = line:match('^%s*(%d+)%s+(%d+)')
    if a then
      parent[tonumber(a)] = tonumber(b)
    end
  end
  local cur = pid
  for _ = 1, 32 do
    if panes[cur] then
      return panes[cur]
    end
    cur = parent[cur]
    if not cur or cur <= 1 then
      return nil
    end
  end
end

-- Probe one socket: mode first (answered even while a prompt is up), then
-- identity only if the editor is not prompting.
local function probe(path)
  local ch = connect(path)
  if not ch then
    return nil
  end
  local mode = request(ch, 'nvim_get_mode')
  if not mode then
    vim.fn.chanclose(ch)
    return nil
  end
  local entry = { socket = path, mode = mode.mode }
  if mode.mode:sub(1, 1) == 'r' then
    entry.blocked = true
    -- Default sockets are nvim.<pid>.0; plugin sockets often end in .<pid>.0.
    entry.pid = tonumber(vim.fs.basename(path):match('%.(%d+)%.0$'))
    entry.tmux_pane = pane_for_pid(entry.pid)
  else
    local info = request(ch, 'nvim_exec_lua', PAYLOAD.info, {})
    if info then
      entry = vim.tbl_extend('force', entry, info)
    end
  end
  vim.fn.chanclose(ch)
  return entry
end

local function find_instances()
  local seen, out = {}, {}
  for _, path in ipairs(list_sockets()) do
    local e = probe(path)
    if e then
      local key = e.pid or e.socket
      if not seen[key] then
        seen[key] = true
        out[#out + 1] = e
      end
    end
  end
  return out
end

local function abspath(p)
  local full = vim.fn.fnamemodify(p, ':p')
  return vim.uv.fs_realpath(full) or full
end

-- Target resolution -----------------------------------------------------------

local function resolve_target()
  if opts.sock then
    return opts.sock
  end
  local env = os.getenv('NV_SOCK')
  if env and env ~= '' then
    return env
  end
  if opts.pane then
    for _, e in ipairs(find_instances()) do
      if e.tmux_pane == opts.pane then
        return e.servername or e.socket
      end
    end
    fail('no_instance', 'no nvim found in tmux pane ' .. opts.pane)
  end
  local nvim_env = os.getenv('NVIM')
  if nvim_env and nvim_env ~= '' then
    return nvim_env
  end
  local found = find_instances()
  if #found == 1 then
    return found[1].servername or found[1].socket
  end
  if #found == 0 then
    fail('no_instance', 'no running nvim found; pass --sock or --pane, or ask the user')
  end
  fail('ambiguous', 'several nvim instances found; pick one with --sock or --pane, or ask the user', {
    instances = found,
  })
end

-- Commands -------------------------------------------------------------------

if command == 'find' then
  local found = find_instances()
  if opts.pane then
    found = vim.tbl_filter(function(e)
      return e.tmux_pane == opts.pane
    end, found)
  end
  emit({ ok = true, instances = found })
end

if not PAYLOAD[command] or command == 'info' then
  fail('usage', 'unknown command: ' .. command)
end

local args
if command == 'state' then
  args = {}
elseif command == 'read' then
  local first, last = tonumber(rest[2]), tonumber(rest[3])
  if (rest[2] and not first) or (rest[3] and not last) then
    fail('usage', 'START and END must be line numbers')
  end
  args = { rest[1] and abspath(rest[1]) or '', first or vim.NIL, last or vim.NIL }
elseif command == 'reload' then
  if #rest == 0 then
    fail('usage', 'reload needs at least one PATH')
  end
  args = { vim.tbl_map(abspath, rest) }
elseif command == 'lua' then
  local code = rest[1]
  if code == nil or code == '-' then
    code = io.stdin:read('*a')
  end
  args = { code, not opts.any_mode }
elseif command == 'ex' then
  if #rest == 0 then
    fail('usage', 'ex needs a command')
  end
  args = { table.concat(rest, ' '), not opts.any_mode }
end

local target = resolve_target()
local ch, cerr = connect(target)
if not ch then
  fail('no_instance', 'cannot connect to ' .. target .. ': ' .. cerr)
end

-- Preflight. nvim_get_mode is answered even while a prompt is up; most other
-- requests would hang. Any mode starting with 'r' is a prompt. The W11/W12
-- "file changed" dialogs report 'r?' with blocking = false, so checking
-- `blocking` alone is not enough.
local mode = request(ch, 'nvim_get_mode')
if mode and mode.mode:sub(1, 1) == 'r' then
  fail('blocked', 'the editor is showing a prompt; ask the user to dismiss it', { mode = mode.mode })
end

local res, rerr = request(ch, 'nvim_exec_lua', PAYLOAD[command], args)
timer:stop()
vim.fn.chanclose(ch)
if not res then
  fail('rpc_error', rerr)
end
if res.value_json then
  res.value = vim.json.decode(res.value_json)
  res.value_json = nil
end
res.socket = target
emit(res)
