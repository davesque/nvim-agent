# Neovim RPC Protocol Notes

> **Last updated:** 2026-10-14
>
> Tested against NVIM v0.12.3 (API level 14) on macOS, inside tmux. Every claim below marked **Verified** was observed with the scripts in `probes/`. Claims marked **Recalled** come from memory of the Neovim docs and still need checking against `:help api` / `:help RPC`.

## Wire protocol

- Neovim speaks [msgpack-rpc](https://github.com/msgpack-rpc/msgpack-rpc/blob/master/spec.md) over a socket (Unix domain socket or named pipe; TCP if `--listen host:port`). **Verified** (raw socket + `msgpack` in `probes/probe.py`).
- Three message shapes:
  - Request: `[0, msgid, method, params]`
  - Response: `[1, msgid, error, result]`
  - Notification: `[2, method, params]`
- `Buffer`, `Window`, `Tabpage` handles arrive as msgpack EXT types (ids 0, 1, 2, per `nvim_get_api_info()[1].types`). **Verified.** Passing `0` for any handle argument means "current". **Verified** (`nvim_win_set_cursor(0, ...)`).
- `nvim_get_api_info` reports 261 functions and 69 UI events on 0.12.3. **Verified.**

## Discovering a running instance

- `--listen <path>` sets the socket explicitly; `v:servername` reports it. **Verified.**
- Without `--listen`, every nvim still listens on a default socket under `$TMPDIR/nvim.$USER/<random>/nvim.<pid>.0`. **Verified.**
- On 0.12 the TUI is a separate process from the server: the pid in the socket name belongs to the server, which is a child of the `nvim` process tmux launched. **Verified** (pane pid 38597 → TUI `nvim` → server 38598 → `nvim.38598.0`).
- The server inherits the launching shell's environment, so `vim.env.TMUX_PANE` identifies which tmux pane an instance lives in. **Verified.** This is the simplest way to map "the nvim in pane %9" to a socket: enumerate sockets, ask each for `TMUX_PANE`.
- `$NVIM` is set for `:terminal` jobs and names the server socket, but is **not** set for `vim.fn.system()` children. **Verified** (`probes/nvim_env.lua`). An agent running inside nvim's terminal can find its parent editor with no discovery at all; agents started any other way cannot rely on it.
- Headless `nvim -l` clients also listen on a default socket. It is removed on normal exit and SIGTERM, but left behind after `os.exit()` or SIGKILL, so discovery can find stale sockets. `vim.fn.serverstop(vim.v.servername)` at client startup removes it. **Verified** (`probes/stale_socket.sh`, `probes/client_timeout.lua`).
- Plugins can open extra sockets for the same server in the same directory (seen: `fzf-lua.<ts>.<pid>.0`). **Verified** (`ls` of the socket dir).

## Client options (no dependencies needed)

| Client | How | Notes |
|---|---|---|
| `nvim --server S --remote-expr EXPR` | Built in | Evaluates a Vimscript expression; wrap Lua with `luaeval("...")` and return JSON via `vim.json.encode`. Quoting gets painful fast. **Verified.** |
| `nvim --clean --headless -l client.lua S CODE` | Built in | `vim.fn.sockconnect('pipe', S, {rpc=true})` + `vim.rpcrequest(ch, 'nvim_exec_lua', CODE, {})`. Returns JSON with `ok`/`result`, surfaces Lua errors with traceback. **Verified.** Best default for the skill. |
| Python `msgpack` / `pynvim` | `uv run` script deps | Needed for subscribing to notifications (buffer change events) and for timeouts on the raw socket. **Verified** with `msgpack`. |

## What works

All **Verified** unless noted:

- Read/write buffer text: `nvim_buf_get_lines`, `nvim_buf_set_lines`, `nvim_buf_set_text`.
- Cursor: `nvim_win_get_cursor`, `nvim_win_set_cursor` (1-based row, 0-based col).
- Arbitrary Lua: `nvim_exec_lua(code, args)` returns Lua values as msgpack.
- Ex commands with captured output: `nvim_exec2(cmd, {output = true})`.
- Mode inspection: `nvim_get_mode()` returns `{mode, blocking}`.
- Change subscriptions: after `nvim_buf_attach(buf, false, {})`, edits arrive as `nvim_buf_lines_event` and `nvim_buf_changedtick_event` notifications on the same channel.
- Diagnostics/LSP state via Lua: `vim.diagnostic.get(0)` (empty in the test buffer; LSP queries are untested).

## Blocking behavior (the main hazard)

| Editor state | `nvim_get_mode` | Other requests |
|---|---|---|
| Normal mode | `n`, not blocking | served |
| Operator pending (`d` typed) | `no`, not blocking | served |
| `input()` prompt | `c`, not blocking | served, including `vim.cmd("enew")` |
| Hit-enter prompt ("Press ENTER") | `r`, **blocking** | **hang until the user dismisses the prompt** |

- During a hit-enter prompt, `nvim_get_mode`, `nvim_get_api_info`, and `nvim_input` are still answered immediately; `nvim_buf_line_count` and `nvim_exec_lua` are not. **Verified.** `--remote-expr` hangs too, since it goes through `nvim_eval`.
- A request queued behind the prompt is **dropped if its client disconnects** (raw socket closed: 0/5 ran; `nvim -l` client killed by `timeout`: 0/5 ran) and **run after the prompt clears if the client stays connected** (5/5 ran, and the late response arrived). **Verified** (`probes/dropped.py`). A client that times out must close its connection.
- Multi-line output from a request (`print` or `vim.notify` in `nvim_exec_lua`, or `nvim_exec2` with `output = false`) raises a hit-enter prompt and hangs that same request. `nvim_exec2(..., {output = true})` captures the output instead, including for `:lua` code. **Verified** (`probes/messages.py`).
- A headless nvim with no UI never shows the prompt; with a UI attached over RPC via `nvim_ui_attach`, it does. **Verified** (`probes/headless_prompt.py`).
- `nvim_input("<CR>")` dismisses the prompt from RPC. **Verified.** Whether the agent should do that without asking is a design question.

Implication: every skill command should first call `nvim_get_mode`, and refuse (or report) when `blocking` is true instead of hanging. Callers also need a hard timeout.

## Undo and concurrency

All **Verified** (`probes/undo.lua`, `probes/undo_multi.py`, `probes/terminal_mode.py`):

- Edits within one `nvim_exec_lua` request form one undo step. Edits in separate requests form separate steps; `:undojoin` in the second request merges them.
- An RPC edit while the user is in insert mode joins the user's insert undo step (one `u` undoes both), on the same or another line. The user's cursor is adjusted correctly.
- An RPC edit to a file buffer while the user is in terminal mode does not move focus and undoes on its own.
- Keys typed during a running `nvim_exec_lua` are applied after it returns, never mid-request, so checks and edits inside one request are atomic.

## Open questions

Questions about stomping on user edits, single-step undo, `nvim_exec_lua` versus a loaded module, and skill packaging are settled in `docs/design.md`.

1. How do LSP actions (rename, code actions, hover) behave over RPC when they are async?
2. Does an RPC edit to a *different* buffer while the user is in insert mode also join an undo step?
3. Do other prompts (`confirm()`, swap-file `ATTENTION`, the more-prompt) block requests the way hit-enter does?
