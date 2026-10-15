# probes/

Throwaway scripts that verify how Neovim's RPC API behaves. They back the **Verified** claims in `docs/protocol-notes.md`. Nothing here ships with the skill.

## Files

- `probe.py`: raw msgpack-rpc tour (API info, buffer read/write, cursor, `nvim_exec_lua`, `nvim_exec2`, buffer-change notifications). Note it **edits the current buffer**.
- `fast.py`: sends one request with a 2s socket timeout and prints the response or `TIMEOUT`. Use it to check which methods are served while nvim is blocked.
- `client.lua`: dependency-free client run via `nvim --clean --headless -l`. Calls `nvim_exec_lua` and prints `{ok, result}` as JSON. The prototype for the skill's real client.

## Running

Run from the repo root against the dedicated test instance, never the user's editor:

```bash
uv run probes/probe.py .nvim-test.sock
uv run probes/fast.py .nvim-test.sock nvim_get_mode '[]'
nvim --clean --headless -l probes/client.lua .nvim-test.sock 'return vim.api.nvim_get_mode()'
```

## Conventions

- Python probes declare dependencies inline (PEP 723 `# /// script` block) so `uv run` works with no project setup. Use plain `msgpack` rather than `pynvim` when the point is to see the wire protocol.
- Every probe that waits on a response needs a timeout. Without one, a hit-enter prompt in the test nvim hangs the probe forever.
- To test an editor state (operator-pending, prompts, insert mode), put the test nvim into it with `tmux send-keys`, run the probe, then reset with `Escape` or `Enter`.
- Each new probe should answer one question. Add a line for it under "Files" and cite it from the doc claim it verifies.
