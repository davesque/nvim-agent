# skill/

The shipped skill. `neovim/` is the skill directory that gets symlinked into `~/.claude/skills/` and `~/.agents/skills/` (`make install`).

## Files

- `neovim/SKILL.md`: instructions the agent reads. Frontmatter follows the Agent Skills spec strictly (`name` must match the directory name; `description` up to 1024 chars) so Claude Code and Codex both load it.
- `neovim/scripts/nv`: POSIX sh wrapper that runs `nv.lua` with `nvim --clean --headless -l`.
- `neovim/scripts/nv.lua`: the client. Connects with `sockconnect`, runs a preflight `nvim_get_mode`, then sends one embedded Lua payload via `nvim_exec_lua`.

## Conventions

- No dependencies beyond `nvim` itself. Nothing is installed into the user's editor; server-side Lua lives in `PAYLOAD` strings and is sent per call.
- Every safety rule in `docs/design.md` has a test in `tests/`. When you change a rule, change its test and the design doc together.
- Do not use `${CLAUDE_SKILL_DIR}` in `SKILL.md`: Codex does not expand it.
- `SKILL.md` is agent-facing prose: no em-dashes, describe what to do rather than how the client works.
- Run `make check` (lint + tests) before committing.
