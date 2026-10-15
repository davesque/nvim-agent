# nvim-agent

A cross-agent skill that lets coding agents (Claude Code, Codex, and others) drive a running Neovim session over its RPC socket.

With it, an agent can see what you have open (current file, cursor, unsaved changes, diagnostics), run Lua or Ex commands in your editor, and make Neovim show files it just edited on disk. It refuses to act while you are typing or while the editor shows a prompt, and every call has a hard timeout, so it cannot freeze your editor.

Requires only `nvim` (tested with 0.12).

## Install

```bash
make install
```

This symlinks `skill/neovim` into `~/.claude/skills/neovim` (Claude Code) and `~/.agents/skills/neovim` (Codex). `make uninstall` removes the links.

## Try it

From a shell next to a running Neovim:

```bash
skill/neovim/scripts/nv find
skill/neovim/scripts/nv state
```

## Development

```bash
make check
```

runs lint and the test suite. Tests start their own headless Neovim instances and never touch a running editor.
