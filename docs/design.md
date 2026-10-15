# nvim-agent Skill Design

> **Last updated:** 2026-10-14. Tested against NVIM v0.12.3 on macOS in tmux, with the user's config loaded in the test instance.
>
> Tags: **Verified (probe)** = observed with the named script in `probes/`. **Verified (docs)** = read in current vendor docs on 2026-10-14, not yet exercised. **Recalled** = unchecked.
>
> A short decision record, not a spec. Implemented in `skill/neovim/scripts/nv.lua`; each safety rule has a test in `tests/`.

## Decisions

1. **Container:** a `SKILL.md` skill plus one bundled client run as `nvim --clean --headless -l`. The Lua that runs inside the editor is embedded in the client and sent with each request, so nothing is installed into the user's nvim. No MCP server (the user ruled it out). About 20 ms per call (**Verified (probe)**, `time` around `probes/client.lua`).
2. **Edits go to disk.** The agent edits files with its own tools, then runs `reload` so nvim shows the new text. The agent never edits buffer text over RPC in the core set.
3. **Commands (6):** `find`, `state`, `read`, `reload`, `lua`, `ex`, all printing one JSON object (`{"ok": true, ...}` or `{"ok": false, "error": code, ...}`).

| Command | Does | Allowed when |
|---|---|---|
| `find [--pane %N]` | List instances: socket, server pid, tmux pane, cwd, current file, mode. | always |
| `state` | Mode, cwd, current buffer, cursor, visible windows, and every loaded file buffer with its `modified` flag. | not prompting |
| `read [PATH]` | Lines of a loaded buffer. Useful when the user has unsaved changes the disk copy lacks. | not prompting |
| `reload PATH...` | Reload the named buffers from disk (rules below). | `n`, `nt`, `t` |
| `lua` | Run Lua from stdin, output captured, returns `{value, output}`. | `n`, `nt`, `t`, or `--any-mode` |
| `ex` | Run an Ex command via `nvim_exec2(cmd, {output = true})`. | `n`, `nt`, `t`, or `--any-mode` |

Diagnostics are a `lua` one-liner (`vim.diagnostic.get`); a dedicated `diag` command can come back if agents use it often. Target selection: `--sock`, then `$NV_SOCK`, then `$NVIM`, then `find` if it finds exactly one instance; otherwise the agent asks the user.

## Why disk-first

Editing buffers over RPC needs guards against the user's in-progress edits: an RPC edit while the user is in insert mode joins their insert undo step, so one `u` undoes both (**Verified (probe)**, `probes/undo_multi.py`). Writing to disk and reloading avoids that, and the reload rules below cover the remaining conflict. What nvim does with an outside write (**Verified (probe)**, `probes/reload.py`):

| Reload method | `autoread` | Buffer | Result |
|---|---|---|---|
| none | on | unchanged | stays stale until something runs `:checktime` (focus change, entering the buffer) |
| `:checktime` | on | unchanged | reloads silently |
| `:checktime` | off | unchanged | **W11 dialog, request hangs** |
| `:checktime` | either | unsaved user changes | **W12 dialog, request hangs** |
| `:edit` in `nvim_buf_call` | either | unchanged, visible or hidden | reloads, no dialog, cursor kept |
| `:edit` in `nvim_buf_call` | either | unsaved user changes | returns an error, no dialog, buffer untouched |

In every reload case one `:undo` restores the previous text, so the user can undo an agent change (**Verified (probe)**, `reload.py`).

### `reload` rules

- Only buffers already loaded in nvim; a path that is not open is a no-op.
- Reload with `:edit` inside `nvim_buf_call`, never `:checktime`.
- Check `modified` and reload in the same `nvim_exec_lua` request. Keys typed during a request are applied after it returns, so the check cannot go stale (**Verified (probe)**, `undo_multi.py` case `atomic`).
- A buffer with unsaved changes is skipped and reported as `conflict`. The agent tells the user that their unsaved edits and the agent's disk edit now differ; it does not overwrite either.
- **Before** editing a file, the agent should check `state` for that file with `modified = true`. If the user has unsaved changes there, ask first, or read the buffer with `read` instead of trusting the disk copy.

## Safety rules

1. **Hard timeout, and timing out means exiting.** Default 5 s. The client enforces it with a libuv timer that exits the process (**Verified (probe)**, `probes/client_timeout.lua`; macOS has no `timeout` command outside Homebrew). Exiting is what cancels the request: a request queued behind a prompt was dropped every time the client disconnected (10/10) and ran later every time the connection stayed open (5/5) (**Verified (probe)**, `probes/dropped.py`). Never keep a timed-out connection open or retry on it.
2. **Preflight: refuse on any `r*` mode, not just `blocking`.** `nvim_get_mode` is answered while a prompt is up. The hit-enter prompt reports `r` with `blocking = true`, but the W11/W12 confirm dialogs report `r?` with **`blocking = false`** while still hanging other requests (**Verified (probe)**, `reload.py`, and protocol notes). The client returns `blocked` for any mode starting with `r`. It never dismisses a prompt itself.
3. **Mode gate.** `reload`, `lua`, and `ex` refuse unless the mode is `n`, `nt`, or `t`. Terminal mode must be allowed: it is what the user is in while typing to an agent in nvim's `:terminal`, and RPC actions on file buffers there neither move focus nor touch the user's undo (**Verified (probe)**, `probes/terminal_mode.py`).
4. **The agent's output must never raise a prompt.** Captured output also includes errors from the user's own autocommands (seen in the smoke test: a FileType plugin's mapping errors when `ex edit` opened a Python file). Multi-line `print` or `vim.notify` from `nvim_exec_lua`, or `nvim_exec2` without `output = true`, puts the editor into hit-enter and hangs the agent's own request (**Verified (probe)**, `probes/messages.py`). `ex` always captures output; `lua` runs the agent's code through a wrapper (compile with `loadstring`, call under `:lua` via `nvim_exec2(..., {output = true})`), which captured `print`, `vim.notify`, `nvim_echo`, `:echo`, `error()`, and `:echoerr` with the editor left in normal mode (**Verified (probe)**, `messages.py`). A plugin that overrides `vim.notify` may behave differently.
5. **The client must not look like an editor.** Every nvim, including a headless client, listens on `$TMPDIR/nvim.$USER/*/nvim.<pid>.0`, and `os.exit()` or SIGKILL leaves the socket behind (**Verified (probe)**, `probes/stale_socket.sh`). The client calls `vim.fn.serverstop(vim.v.servername)` at startup and removes the per-process directory too, since `serverstop` leaves it (**Verified**, `tests/test_safety.py::test_client_leaves_no_socket_behind`). `find` skips dead sockets and dedupes servers that plugins gave extra sockets (seen: `fzf-lua.<ts>.<pid>.0`) by asking each for `vim.fn.getpid()` after a mode check.

## Discovery

- `$NVIM` is set for `:terminal` jobs and names the server socket, but not for `vim.fn.system()` children (**Verified (probe)**, `probes/nvim_env.lua`). It is the zero-discovery path when the agent runs in nvim's terminal.
- Otherwise `find` asks each socket for `vim.env.TMUX_PANE` after a mode check. An editor showing a prompt cannot be asked, so for those `find` takes the server pid from the socket name (`nvim.<pid>.0`, or `<anything>.<pid>.0` for plugin sockets) and walks its parent chain to a tmux `pane_pid` (server, then TUI `nvim`, then the pane shell) (**Verified**, `ps` and `tmux list-panes`, and in the smoke test against pane %9). This works when the agent itself runs outside tmux.

## Packaging

Both harnesses follow the Agent Skills standard and load only name and description up front (**Verified (docs)**: [Claude Code](https://code.claude.com/docs/en/skills), [Codex](https://developers.openai.com/codex/skills), [spec](https://agentskills.io/specification)).

- Claude Code looks in `~/.claude/skills/` and `.claude/skills/`; Codex looks in `~/.agents/skills/` and `.agents/skills/`. Install one checkout and symlink it into both. Codex documents following symlinks. Claude Code's docs say nothing, but it does follow them: after `make install`, a running Claude Code session listed the `neovim` skill without a restart, and its `Base directory for this skill` was the symlink path, from which `scripts/nv` ran correctly (**Verified**, 2026-10-14). Codex loading is untested (Codex is not installed on the dev machine).
- Write frontmatter to the strict spec (`name` matching the directory, `description` up to 1024 chars). Claude Code ignores unknown fields; Codex's docs do not say.
- Do not use `${CLAUDE_SKILL_DIR}` in `SKILL.md`: Codex would pass it to the shell unexpanded. Tell the agent to run `scripts/nv` from the absolute path of the skill's directory, which both harnesses show the model.
- `SKILL.md` must warn that raw `nvim --remote-*` calls skip every rule above and can freeze the user's editor. That warning is the only defense: a skill cannot force the agent onto the guarded client, which is the strongest argument against this container.

```
skill/neovim/SKILL.md
skill/neovim/scripts/nv        sh wrapper: exec nvim --clean --headless -l "$dir/nv.lua" "$@"
skill/neovim/scripts/nv.lua    client + embedded Lua payloads
tests/                          pytest suite
```

## Testing

- Each test starts `nvim --clean --headless --listen <tmp>/sock` and kills it afterwards. Tests run the real `scripts/nv` via subprocess and inspect the editor over a separate msgpack connection.
- Prompts are testable without tmux: a headless nvim shows the hit-enter prompt only once a UI is attached, which a test can do over RPC with `nvim_ui_attach` (**Verified (probe)**, `probes/headless_prompt.py`). The W11/W12 dialogs under a fake UI are untested.
- Cover each safety rule: timeouts leave no side effect, `r*` modes return `blocked`, refused modes return `mode`, `lua` with multi-line output leaves the editor in `n`, `reload` reloads unchanged buffers (visible and hidden) and reports `conflict` for modified ones without changing them, and the client leaves no socket behind.
- Harness loading (symlinks, script path) is a manual checklist.

## Open questions

1. **LSP actions** (hover, rename, code actions) are async. `vim.lsp.buf_request_sync` inside a request blocks the editor for its timeout. Untested; no language server was available.
2. **Other dialogs.** Hit-enter, W11, and W12 are tested. Swap-file `ATTENTION`, `confirm()`, and the more-prompt are not.
3. **Does Codex ignore unknown frontmatter** such as Claude Code's `allowed-tools`?
4. **Names.** Skill `name` (`neovim` or `nvim`), and whether to rename the repo from `nvim-agent`.
5. **Buffer edits as a fallback.** If agents often hit `conflict`, consider an opt-in `edit` command that patches the buffer over RPC (one request = one undo step, refused in insert mode; both **Verified (probe)**, `probes/undo.lua`, `undo_multi.py`).
