# probes/

Throwaway scripts that verify how Neovim's RPC API behaves. They back the **Verified** claims in `docs/protocol-notes.md`. Nothing here ships with the skill.

## Files

- `probe.py`: raw msgpack-rpc tour (API info, buffer read/write, cursor, `nvim_exec_lua`, `nvim_exec2`, buffer-change notifications). Note it **edits the current buffer**.
- `fast.py`: sends one request with a 2s socket timeout and prints the response or `TIMEOUT`. Use it to check which methods are served while nvim is blocked.
- `client.lua`: dependency-free client run via `nvim --clean --headless -l`. Calls `nvim_exec_lua` and prints `{ok, result}` as JSON. The prototype for the skill's real client.
- `client_timeout.lua`: `client.lua` plus a self-enforced timeout (libuv timer, exits 124) and `serverstop` of its own socket.
- `dropped.py`: is a request queued behind a hit-enter prompt run after the prompt clears? Tries disconnect, abandon, and kill. Needs the tmux pane id.
- `messages.py`: which kinds of output raise a hit-enter prompt, and whether the capture wrapper prevents it. Needs the tmux pane id.
- `undo.lua`: undo grouping of edits within one request (run through `client.lua`).
- `undo_multi.py`: undo across requests, edits while the user is in insert mode, and atomicity of a request. **Edits the current buffer.** Needs the tmux pane id.
- `terminal_mode.py`: editing a file buffer while the user is in terminal mode. Needs the tmux pane id.
- `nvim_env.lua`: is `$NVIM` set for `system()` children and `:terminal` jobs (run through `client.lua`).
- `stale_socket.sh`: which exit paths leave a headless nvim's default socket behind. Starts its own nvims; touches no running editor.
- `headless_prompt.py`: can a headless nvim reproduce the hit-enter prompt (yes, with a UI attached over RPC). Starts its own nvim.

## Running

Run from the repo root against the dedicated test instance, never the user's editor:

```bash
uv run probes/probe.py .nvim-test.sock
uv run probes/fast.py .nvim-test.sock nvim_get_mode '[]'
nvim --clean --headless -l probes/client.lua .nvim-test.sock 'return vim.api.nvim_get_mode()'
uv run probes/dropped.py .nvim-test.sock %9
nvim --clean --headless -l probes/client.lua .nvim-test.sock "$(cat probes/undo.lua)"
```

## Conventions

- Python probes declare dependencies inline (PEP 723 `# /// script` block) so `uv run` works with no project setup. Use plain `msgpack` rather than `pynvim` when the point is to see the wire protocol.
- Every probe that waits on a response needs a timeout. Without one, a hit-enter prompt in the test nvim hangs the probe forever.
- To test an editor state (operator-pending, prompts, insert mode), put the test nvim into it with `tmux send-keys`, run the probe, then reset with `Escape` or `Enter`.
- Each new probe should answer one question. Add a line for it under "Files" and cite it from the doc claim it verifies.
