# nvim-agent

A cross-agent skill (Claude Code, Codex, and other harnesses that read `SKILL.md` skills) for driving a running Neovim session over its msgpack-rpc socket.

Do not add `CLAUDE.md` files to this repo. Claude Code (v2.1.277+) reads `AGENTS.md` directly, and a `CLAUDE.md` anywhere on the path would stop it from doing so.

## Status

First version implemented in `skill/neovim/`, with tests in `tests/`. Not yet tried end to end in Claude Code or Codex. Read `docs/protocol-notes.md` and `docs/design.md` before changing behavior; they record what has been verified against a live nvim and why each safety rule exists.

## Layout

```
AGENTS.md          Agent instructions (this file)
Makefile           test, lint, format, check, install, uninstall
docs/              Protocol notes and design docs
probes/            Throwaway scripts used to verify protocol behavior
skill/neovim/      The shipped skill: SKILL.md and scripts/nv
tests/             pytest suite; each test starts its own headless nvim
```

Give every new subdirectory with its own conventions its own `AGENTS.md`. `make check` runs lint and tests; the tests never touch running editors (discovery is confined with `NV_SOCKET_DIRS`).

## Testing against a live nvim

- Use a dedicated instance, never the user's working editor. Start one in a tmux pane from the repo root:
  ```bash
  nvim --listen .nvim-test.sock
  ```
  `*.sock` is gitignored.
- Drive the pane with `tmux send-keys -t <pane>` to put the editor into specific states, and read it back with `tmux capture-pane -p -t <pane>`.
- Any nvim found under `$TMPDIR/nvim.$USER/` may be the user's real editing session. Do not send requests to those sockets unless the user asks.
- Wrap every RPC call in a timeout (`timeout 3 ...`, or a socket timeout in Python). A hit-enter prompt makes most requests hang indefinitely; see "Blocking behavior" in `docs/protocol-notes.md`.

## Conventions

- Prefer the dependency-free client (`nvim -l` + `sockconnect`) for anything the skill ships. Python is fine for probes and tests.
- Subdirectories have their own `AGENTS.md` covering local conventions: `docs/` for claim tagging, `probes/` for how to write and run probes.
- Commit messages start with a capital letter (`Add ...`, `Fix ...`).
- No em-dashes in user-facing prose (README, SKILL.md).
