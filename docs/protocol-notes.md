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
- `$NVIM` is set inside `:terminal` buffers and child processes of nvim (**Recalled**), which lets an agent running inside nvim's terminal find its parent editor with no discovery at all.

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
- Requests from a client that disconnected while waiting were **not** executed after the prompt cleared (a `vim.g` marker set by the timed-out request stayed `nil`). **Verified** for one case; worth re-testing before relying on it.
- `nvim_input("<CR>")` dismisses the prompt from RPC. **Verified.** Whether the agent should do that without asking is a design question.

Implication: every skill command should first call `nvim_get_mode`, and refuse (or report) when `blocking` is true instead of hanging. Callers also need a hard timeout.

## Open questions

1. How should the agent avoid stomping on the user's in-progress edits? Options: check `mode` is `n`, check `changedtick` before and after, use `nvim_buf_set_text` only on ranges the agent read.
2. Should edits go through undo-joinable chunks so the user can undo an agent change with one `u`?
3. How do LSP actions (rename, code actions, hover) behave over RPC when they are async?
4. Is `nvim_exec_lua` as the single primitive enough, or do we want a small Lua module loaded into the editor (`nvim_exec_lua("require('nvim_agent').op(...)")`)?
5. Codex and Claude Code skill packaging: confirm both read the same `SKILL.md` frontmatter format (**Recalled** that they do; unverified).
