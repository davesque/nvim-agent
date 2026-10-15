# nvim-agent

A cross-agent skill (Claude Code, Codex, and other harnesses that read `SKILL.md` skills) for driving a running Neovim session over its msgpack-rpc socket.

`CLAUDE.md` is a symlink to this file. Edit `AGENTS.md`, never the symlink.

## Status

Early research phase. Read `docs/protocol-notes.md` before designing or changing anything; it records what has been verified against a live nvim and what is still a guess.

## Layout

```
AGENTS.md          Agent instructions (this file)
docs/              Protocol notes and design docs
probes/            Throwaway scripts used to verify protocol behavior
```

Planned, not yet created: a `skill/` directory holding `SKILL.md` plus its helper scripts. When a subdirectory grows its own conventions (e.g. the skill's Lua client), give it its own `AGENTS.md` and a `CLAUDE.md` symlink next to it.

## Testing against a live nvim

- Use a dedicated instance, never the user's working editor. Start one in a tmux pane from the repo root:
  ```bash
  nvim --listen .nvim-test.sock
  ```
  `*.sock` is gitignored.
- Drive the pane with `tmux send-keys -t <pane>` to put the editor into specific states, and read it back with `tmux capture-pane -p -t <pane>`.
- Any nvim found under `$TMPDIR/nvim.$USER/` may be the user's real editing session. Do not send requests to those sockets unless the user asks.
- Wrap every RPC call in a timeout (`timeout 3 ...`, or a socket timeout in Python). A hit-enter prompt makes most requests hang indefinitely; see "Blocking behavior" in `docs/protocol-notes.md`.

## Running the probes

```bash
uv run probes/probe.py .nvim-test.sock          # raw msgpack-rpc tour
uv run probes/fast.py .nvim-test.sock nvim_get_mode '[]'
nvim --clean --headless -l probes/client.lua .nvim-test.sock 'return vim.api.nvim_get_mode()'
```

Python scripts declare dependencies inline (PEP 723), so `uv run` needs no project setup.

## Conventions

- Prefer the dependency-free client (`nvim -l` + `sockconnect`) for anything the skill ships. Python is fine for probes and tests.
- Tag claims in docs as **Verified** (observed with a probe) or **Recalled** (from memory, unchecked). Add a probe when you verify something new.
- Commit messages start with a capital letter (`Add ...`, `Fix ...`).
- No em-dashes in user-facing prose (README, SKILL.md).
