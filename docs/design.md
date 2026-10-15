# nvim-agent Skill Design

> **Last updated:** 2026-10-14
>
> Tested against NVIM v0.12.3 (API level 14) on macOS, inside tmux, with the user's config loaded in the test instance. Claim tags follow `docs/AGENTS.md`:
> - **Verified (probe)**: observed with the named script in `probes/`.
> - **Verified (docs)**: read in current vendor docs on 2026-10-14 (URL given). Not yet exercised end to end.
> - **Recalled**: from memory, unchecked.
>
> Status: design only. Nothing under `skill/` exists yet.

## Summary

- **Container:** one `SKILL.md` skill plus one bundled dependency-free client (`nvim --clean --headless -l`). The Lua that runs inside the editor ships inside the client and is sent with each request, so nothing is installed into the user's nvim. No MCP server (ruled out by the user).
- **Commands (7):** `find`, `state`, `read`, `edit`, `lua`, `ex`, `diag`.
- **Safety:** a client-side timeout that exits the process (which provably cancels the queued request), a `nvim_get_mode` preflight that refuses when `blocking`, a mode gate and old-text check that run *inside* the same request as the edit (so they are atomic), and output capture so the agent's own messages never raise a hit-enter prompt.
- **Undo:** one `edit` call is one undo step. Never use `undojoin` across requests.
- **Tests:** pytest drives the real client against a throwaway `nvim --clean --headless --listen` per test. Attaching a UI over RPC reproduces the hit-enter prompt headlessly, so blocking behavior is testable in CI without tmux.

## 1. Container

### Options

| Option | For | Against |
|---|---|---|
| **SKILL.md + bundled client** (chosen) | One directory works for Claude Code and Codex. No extra process, no per-harness server config. The client needs only `nvim`, which is already on the machine. | A skill is instructions, not enforcement: nothing stops the agent from bypassing the client and calling `nvim --remote-expr` with no guards. |
| MCP server | Typed tools, schema-checked arguments, timeouts enforced by the server, the agent cannot route around them. | A long-lived process per harness, separate config for each harness, a runtime dependency (Python or Node). The user does not want this route. |
| Lua module installed in nvim, called via `nvim_exec_lua("require('nvim_agent')...")` | Can keep state across calls (autocmds, change tracking). | The user must install a plugin into their editor. Skill and plugin versions can drift. The same code can simply be sent with each request instead. |

### Decision: SKILL.md plus a client that ships its Lua payload

The client is a Lua script run as `nvim --clean --headless -l nv.lua <command> ...`. It connects with `sockconnect(..., {rpc = true})` and calls `nvim_exec_lua(payload, args)`, where `payload` is the server-side half of the command, embedded in the client. This gets the main benefit of the in-editor module (structured operations written in Lua, run atomically in the editor) without installing anything. Per-call cost is about 20 ms wall time for a round trip (**Verified (probe)**, `time` around `probes/client.lua`), which is negligible next to an agent turn.

### Strongest case against

The guards only exist in the client. An agent that forgets the skill, or decides `nvim --server "$NVIM" --remote-expr` is quicker, gets no timeout, no blocking check, and no output capture. A multi-line `print` from such a call blocks the user's editor *and* hangs the agent (see section 3). An MCP server would make the guarded path the only path. Mitigations, none of them complete:

- `SKILL.md` states plainly that raw `--remote-*` calls can freeze the user's editor, and gives the one command to use instead.
- In Claude Code, `allowed-tools` in frontmatter can pre-approve the client's Bash pattern so the guarded path is also the least-friction path (**Verified (docs)**, [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)). Codex has no equivalent field in its skill docs.
- `lua` and `ex` remain escape hatches inside the guarded client, so the agent never needs to leave it.

### How each harness finds skills

| | Claude Code | Codex |
|---|---|---|
| User location | `~/.claude/skills/<name>/SKILL.md` | `$HOME/.agents/skills/<name>/` |
| Project location | `.claude/skills/` in cwd and parents up to repo root | `.agents/skills/` in cwd and parents up to repo root |
| Required frontmatter | none (`description` recommended; `name` defaults to dir name) | `name` and `description` |
| Loading | descriptions up front, body on invocation | name and description up front, body on use |
| Skill dir at runtime | `${CLAUDE_SKILL_DIR}` substituted into the skill text | the listing includes each skill's file path; no variable documented |
| Extras | `allowed-tools`, `disable-model-invocation`, etc. | optional `agents/openai.yaml` |

All **Verified (docs)**: Claude Code from [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills); Codex from [developers.openai.com/codex/skills](https://developers.openai.com/codex/skills) (redirects to learn.chatgpt.com/docs/build-skills). Both say they follow the Agent Skills standard ([agentskills.io/specification](https://agentskills.io/specification)), which requires `name` (1 to 64 chars, lowercase, digits, single hyphens, must match the directory) and `description` (1 to 1024 chars), and recommends relative paths from the skill root.

**One layout for both:** write frontmatter to the strict spec (`name`, `description`, optional `license`/`compatibility`/`metadata`), so both parse it. Claude Code ignores unknown fields (**Verified (docs)**); whether Codex ignores `allowed-tools` is untested. Install by symlinking one checkout into both `~/.claude/skills/<name>` and `~/.agents/skills/<name>`. Codex documents following symlinks; Claude Code's docs are silent, so test it.

**Locating the client:** do not write `${CLAUDE_SKILL_DIR}` in the shared `SKILL.md`. Codex would pass it to the shell unexpanded, where it becomes an empty string. Instead, tell the agent to run `scripts/nv` relative to the directory containing `SKILL.md`, which both harnesses show the model. Claude Code's working directory can move with `cd`, so the instruction must say "the absolute path of this skill's directory", not a bare relative path. Verify in both harnesses during implementation.

### Proposed layout

```
skill/
  AGENTS.md            Conventions for skill code
  neovim/              Skill directory; name must match frontmatter `name`
    SKILL.md
    scripts/
      nv               POSIX sh wrapper: exec nvim --clean --headless -l "$dir/nv.lua" "$@"
      nv.lua           Client + embedded server-side payloads
tests/                 pytest suite (section 4)
```

The skill name is undecided (`neovim` vs `nvim`); see open questions.

## 2. Command surface

Every command prints one JSON object on stdout: `{"ok": true, ...}` or `{"ok": false, "error": "<code>", "message": "..."}`. Error codes the agent must handle: `blocked`, `timeout`, `mode`, `conflict`, `no_instance`, `ambiguous`, `lua_error`.

Target selection, in order: `--sock PATH`, then `$NV_SOCK`, then `$NVIM`, then `find` if it yields exactly one instance. Zero or several give `no_instance` / `ambiguous` with the candidates listed, and the agent asks the user.

| Command | What it does | Mode gate |
|---|---|---|
| `find [--pane %N]` | List reachable instances: socket, server pid, tmux pane, cwd, current file, mode. | none (read-only) |
| `state` | Mode, blocking, cwd, current buffer (path, filetype, modified, changedtick), cursor, visible windows and their buffers. | any non-blocking |
| `read [PATH] [START END]` | Lines of a loaded buffer (default current), with `changedtick`. 1-based inclusive range. | any non-blocking |
| `edit` | Apply hunks to a loaded buffer. JSON on stdin (below). | `n`, `nt`, `t` only |
| `lua` | Run Lua from stdin with output captured. Returns `{value, output}`. | `n`, `nt`, `t`, or `--any-mode` |
| `ex` | Run an Ex command via `nvim_exec2(cmd, {output = true})`. Returns `{output}`. | `n`, `nt`, `t`, or `--any-mode` |
| `diag [PATH]` | `vim.diagnostic.get` for a buffer (default all), as `{path, lnum, col, severity, message, source}`. | any non-blocking |

Out of the core set on purpose: keystroke injection (`nvim_input`), file open, save, LSP actions. `ex` and `lua` cover them (`ex edit foo.py`, `ex write`), and keeping them out avoids encouraging agents to type into the user's editor.

### `edit` input

```json
{
  "path": "src/foo.py",
  "tick": 42,
  "hunks": [
    {"start": 10, "end": 12, "old": ["a", "b", "c"], "new": ["A", "B"]}
  ],
  "write": false
}
```

- `path` optional (default current buffer). Must already be loaded; the command does not open files.
- `old` is required per hunk. All hunks are checked against the buffer before any is applied; a mismatch returns `conflict` with the current text of that range. This lets the user keep typing elsewhere in the same buffer.
- `tick` optional. If given, any change since the agent's `read` is a `conflict` (strict mode).
- Hunks apply bottom-up so earlier line numbers stay valid.
- `write: true` writes the buffer afterwards, but only if it was unmodified before the edit, so the agent never saves the user's own unsaved changes along with its edit.
- Returns the new `changedtick` and the line delta.

## 3. Safety rules

### Rule 1: every call has a hard timeout, and timing out means exiting

Default 5 s, `--timeout MS` to change. The client enforces it with a libuv timer that fires during `vim.rpcrequest` and exits the process (**Verified (probe)**, `probes/client_timeout.lua`). macOS has no `timeout` command outside Homebrew coreutils (**Verified**, `which timeout` resolves to `/opt/homebrew/bin`), so the client cannot rely on it.

Exiting is the important part. A request that nvim has queued behind a hit-enter prompt is **dropped if the client disconnects** and **run later if the client stays connected**:

| Client behavior after 1 s timeout | Trials | Request ran after prompt cleared? |
|---|---|---|
| Raw socket closed | 5 | no (0/5) |
| `nvim -l` client killed by `timeout 1` | 5 | no (0/5) |
| Socket left open, client stopped waiting | 5 | **yes (5/5)**, with a late response |

**Verified (probe)**, `probes/dropped.py`. So "timed out" means "not applied" only if the client hangs up. The client must never keep a connection open after a timeout, and must never retry on the same channel.

### Rule 2: preflight with `nvim_get_mode`, refuse when blocking

`nvim_get_mode` is answered during a hit-enter prompt; most other requests are not (**Verified (probe)**, protocol notes). The client calls it first on the same connection and returns `blocked` without sending the real request. The agent tells the user; it does not dismiss the prompt itself, even though `nvim_input("<CR>")` would (**Verified (probe)**, protocol notes), because the prompt may hold output the user needs to read.

The preflight is not atomic with the request; a prompt can appear in between. Rule 1 covers that window.

### Rule 3: gates run inside the same request as the edit

Keys typed while an `nvim_exec_lua` request runs are applied after it finishes, never in the middle (**Verified (probe)**, `probes/undo_multi.py` case `atomic`: a request that slept 1 s while tmux typed saw an unchanged buffer and a changedtick that rose by exactly 1). So the `edit` payload checks mode, `old` text, and optional `tick`, then applies, all in one `nvim_exec_lua`. This is a real compare-and-swap; the client-side preflight is only there to avoid hanging.

### Rule 4: no edits while the user is in insert, visual, or command-line mode

An RPC edit made while the user is in insert mode joins the user's in-progress insert undo step: one `u` afterwards undoes both the user's typing and the agent's edit, whether the edit is on another line or the same line (**Verified (probe)**, `undo_multi.py` cases `insert_other_line`, `insert_same_line`). The cursor is adjusted correctly, so the user's typing lands in the right place; the harm is to undo.

While the user is in terminal mode (`t`, typing into the agent's `:terminal`), an edit to a file buffer does not move focus, and one undo in that buffer reverts exactly the agent's edit (**Verified (probe)**, `probes/terminal_mode.py`). Since running the agent inside nvim's terminal is the main `$NVIM` setup, `t` must be allowed.

Allowed modes for `edit`, `lua`, `ex`: `n`, `nt`, `t`. Everything else (`i`, `R`, `v`, `V`, `^V`, `s`, `c`, `no*`, `r*`) returns `mode`. Operator-pending (`no`) is refused because the user is mid-command.

### Rule 5: the agent's own output must never raise a prompt

Multi-line output from agent code puts the user's editor into a hit-enter prompt **and** hangs the agent's own request (**Verified (probe)**, `probes/messages.py`):

| Request | Returned? | Editor afterwards |
|---|---|---|
| `nvim_exec_lua("print('one line')")` | yes | normal |
| `nvim_exec_lua` with 3-line `print` | **timeout** | **hit-enter** |
| `nvim_exec_lua` with 3-line `vim.notify` | **timeout** | **hit-enter** |
| `nvim_exec2('echo "3 lines"', {output = false})` | **timeout** | **hit-enter** |
| `nvim_exec2(..., {output = true})` (echo, `:lua print`, `:ls`) | yes, output captured | normal |
| Lua `error()` | yes, error returned | normal |

So `ex` always uses `output = true`, and `lua` runs agent code through a wrapper: compile with `loadstring`, call it under `:lua` via `nvim_exec2(..., {output = true})`, return `{ok, value, output}`. The wrapper captured 3-line `print`, `vim.notify`, `nvim_echo`, `vim.cmd('echo')`, `error()`, and `echoerr` with the editor left in normal mode every time (**Verified (probe)**, `messages.py` "wrapped" cases). `vim.notify` results depend on the user's config: a plugin that overrides it (a notification popup) may behave differently. The test instance had the user's config loaded.

### Rule 6: one `edit` is one undo step

Edits made within one `nvim_exec_lua` request form a single undo step; edits in separate requests form separate steps; `:undojoin` before the second request merges them (**Verified (probe)**, `probes/undo.lua`, `undo_multi.py` cases `separate`, `joined`). Design: one `edit` call carries all its hunks in one request, so the user undoes it with one `u`. Do not use `undojoin` across requests: if the user changed the buffer in between, the agent's edit would be glued to the user's change.

### Rule 7: discovery must not mistake clients for editors

Every nvim, including a headless `-l` client, listens on `$TMPDIR/nvim.$USER/*/nvim.<pid>.0`. The socket is removed on normal exit and on SIGTERM, but left behind on `os.exit()` and SIGKILL (**Verified (probe)**, `probes/stale_socket.sh`). The client's own timeout path uses `os.exit`, and during development a stale socket from it was found next to the real ones. The client therefore calls `vim.fn.serverstop(vim.v.servername)` first thing, which removes its socket immediately (**Verified (probe)**, `client_timeout.lua`: no socket left on success or on timeout).

`find` must also skip stale sockets (connect refused, owning pid dead) and deduplicate servers: plugins open extra sockets in the same directory, for example `fzf-lua.<ts>.<pid>.0` belonging to the test instance (**Verified**, `ls` of the socket dir). Dedupe by asking each socket for `vim.fn.getpid()`, after a `nvim_get_mode` check so a blocked editor is reported rather than hung on.

Mapping to tmux without sending any request: the server pid is in the socket name, and its parent chain reaches the tmux `pane_pid` (server → TUI `nvim` → pane shell) (**Verified**, `ps` and `tmux list-panes`, also in protocol notes). Use this first, and fall back to asking for `vim.env.TMUX_PANE` for instances started with `--listen PATH`, whose socket name has no pid.

`$NVIM` is set in `:terminal` jobs, naming the server socket, but **not** in `vim.fn.system()` children (**Verified (probe)**, `probes/nvim_env.lua`). It is the zero-discovery path when the agent runs in nvim's terminal; agents launched any other way need `find`.

## 4. Testing

### Fixture

Each test starts `nvim --clean --headless --listen <sock>` with the socket under a per-test temp dir, waits for the socket, and kills the process afterwards (**Verified (probe)**, `probes/headless_prompt.py` does exactly this). `--clean` keeps the user's config out of tests; one separate test class runs with a fixture config that overrides `vim.notify`, to cover Rule 5's config dependence.

### Reproducing blocking headlessly

A headless nvim with no UI attached does **not** enter hit-enter: the message goes to stderr and the mode stays `n`. With a UI attached over RPC (`nvim_ui_attach(80, 24, {ext_linegrid = true})` from a second connection), the same `:echo` of three lines puts it in mode `r`, `blocking`, and `nvim_buf_line_count` times out (**Verified (probe)**, `headless_prompt.py`). So the fixture has an optional fake-UI connection, and blocking tests need no tmux.

### What to test

Tests call the real `scripts/nv` via subprocess (black box) and inspect the editor through a separate pytest-side msgpack connection.

- Each command's happy path and JSON shape.
- Rule 1: under a fake-UI hit-enter prompt, every command returns `timeout` or `blocked` within budget; after dismissing, a marker set by the timed-out call is still unset.
- Rule 2: preflight returns `blocked` without sending the payload.
- Rule 3: `edit` with stale `old` returns `conflict` and changes nothing; with stale `tick` likewise; concurrent `nvim_input` during a slow payload lands after it.
- Rule 4: put the editor in each refused mode via `nvim_input` (`i`, `v`, `:`, `d`) and assert `mode`; `t` with a terminal buffer is allowed.
- Rule 5: `lua` with multi-line `print`/`notify`/`echo` returns captured output, and mode afterwards is `n` with the fake UI attached.
- Rule 6: a multi-hunk `edit` followed by one `:undo` restores the original text exactly.
- Rule 7: `find` ignores a stale socket file and a second socket of the same server; the client leaves no socket behind after success, timeout, and `lua_error`.

Harness integration (does Claude Code and Codex each find the skill through a symlink and resolve `scripts/nv`) is a manual checklist, not automated.

The tmux-driven probes stay as the way to check behavior against a real TUI when a headless test and reality disagree.

## Open questions

Carried forward from `docs/protocol-notes.md`, with what is now settled moved into the sections above (stomping on edits: Rules 3 and 4; single undo: Rule 6; `nvim_exec_lua` versus a loaded module: section 1; skill packaging: section 1).

1. **LSP actions over RPC.** Hover, rename, and code actions are async. Running `vim.lsp.buf_request_sync` inside the payload blocks the user's editor for up to its timeout. Untested: no language server was available for the test instance. Leave LSP out of the core set until probed.
2. **Edits to another buffer while the user is in insert mode.** Rule 4 refuses all insert-mode edits. The undo merge was observed only for the buffer being typed in; an edit to a *different* buffer may be safe. Probe before relaxing the rule.
3. **Does Codex ignore unknown frontmatter like `allowed-tools`?** Claude Code documents ignoring unknown fields; Codex does not say.
4. **Does Claude Code follow a symlinked skill directory?** Codex documents it; Claude Code does not.
5. **Skill and repo name.** The spec requires the skill `name` to match its directory; candidates are `neovim` or `nvim`. Whether to rename the repo from `nvim-agent` is undecided (it reads like an AI agent living inside Neovim).
6. **Unloaded files.** `edit` only touches loaded buffers. If the agent edits a file on disk that is open and modified in nvim, the user gets a conflict warning later. Should `SKILL.md` tell the agent to check `find`/`state` for open buffers before using its own file tools? Probably yes; decide when writing `SKILL.md`.
7. **Other blocking prompts.** Only the hit-enter prompt has been tested. Others (`confirm()`, swap-file `ATTENTION`, `more` prompt for long output) may block differently.
