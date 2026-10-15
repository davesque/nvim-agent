---
name: neovim
license: Apache-2.0
description: Work with the user's running Neovim editor over its RPC socket. Use when the user refers to what is open in their editor (current file, cursor, unsaved changes, diagnostics), asks you to show or run something in Neovim, or when you edit files they have open in Neovim and the editor should pick up your changes. Also use when running inside a Neovim :terminal ($NVIM is set).
---

# Neovim

Talk to the user's running Neovim with the `nv` client in this skill's `scripts/` directory. Always call it by its absolute path, built from the directory that contains this `SKILL.md`:

```bash
<skill-dir>/scripts/nv state
```

Every call prints one JSON object. Check `ok`; on failure, `error` holds a code (listed below) and `message` explains it.

**Never talk to Neovim any other way.** Raw `nvim --server ... --remote-expr`, `--remote-send`, or your own socket scripts skip the timeout and prompt checks. They can freeze the user's editor and hang your own shell.

## Which editor

`nv` picks the target in this order: `--sock PATH`, `$NV_SOCK`, `--pane %N`, `$NVIM` (set when you run inside a Neovim terminal), then the only running instance. If several are running you get `ambiguous` with a list. Ask the user which one, or use `--pane` with the tmux pane they name. `nv find` lists every instance with its tmux pane, cwd, current file, and mode.

## Commands

| Command                        | Use it to                                                                                                                                                             |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nv find`                      | List running instances.                                                                                                                                               |
| `nv state`                     | See mode, cwd, current file, cursor, windows, and every open file with its `modified` flag.                                                                           |
| `nv read [PATH [START [END]]]` | Read a buffer as it is in the editor, including unsaved changes. Lines are 1-based, inclusive.                                                                        |
| `nv reload PATH...`            | Make the editor show files you changed on disk.                                                                                                                       |
| `nv lua [CODE]`                | Run Lua inside Neovim. Pass code as an argument, or on stdin (omit CODE or use `-`). `return` a value to get it back as `value`; printed text comes back as `output`. |
| `nv ex CMD`                    | Run an Ex command, for example `nv ex 'edit src/main.py'` or `nv ex 'write'`. Output comes back as `output`.                                                          |

Options: `--timeout MS` (default 5000), `--any-mode` (let `lua`/`ex` run when the user is not in normal or terminal mode; only for read-only code).

Diagnostics: `nv lua 'return vim.diagnostic.get()'` (or `vim.diagnostic.get(0)` for the current buffer).

## Editing files the user has open

Edit files on disk with your normal file tools, not through Neovim. Then:

1. **Before editing**, run `nv state` and look at `buffers`. If the file is open with `"modified": true`, the user has unsaved changes there. Ask before editing it, and use `nv read` to see what they have, since the disk copy is out of date.
2. **After editing**, run `nv reload` with the files you changed. Neovim does not notice outside writes on its own.
3. Check each result's `status`:
   - `reloaded`: the editor now shows your change. The user can undo it with `u`.
   - `unchanged`: the buffer already matched the file.
   - `not_loaded`: the file is not open; nothing to do.
   - `conflict`: the user has unsaved changes in that buffer, so it was not reloaded. Tell the user that their unsaved edits and your edit on disk now differ, and let them decide.
   - `missing`: the file no longer exists on disk; the buffer was left alone.

Do not save the user's buffers (`nv ex write`) unless they ask.

## Errors

| `error`                     | Meaning                                                            | What to do                                                                  |
| --------------------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `blocked`                   | The editor is showing a prompt or dialog.                          | Tell the user and ask them to dismiss it. Do not dismiss it yourself.       |
| `mode`                      | The user is typing (insert, visual, command line, or mid-command). | Wait and retry later, or tell the user. Reads (`state`, `read`) still work. |
| `timeout`                   | No reply in time. Nothing was applied.                             | Retry once; if it repeats, tell the user the editor seems busy.             |
| `no_instance` / `ambiguous` | No editor found, or several.                                       | Ask the user which editor, or pass `--sock` / `--pane`.                     |
| `not_loaded`                | `read` on a file that is not open.                                 | Read the file from disk instead.                                            |
| `lua_error` / `ex_error`    | Your code failed.                                                  | Fix the code. `message` has the error.                                      |

## Lua tips

- Code runs in the user's editor with their config and plugins. Keep it short and avoid changing their settings, keymaps, or layout unless asked.
- Return plain data (tables, strings, numbers). Anything else comes back as a string.
- Avoid code that waits a long time (sleeps, synchronous LSP requests): the editor freezes until it returns.

## Call stack walkthroughs

For an ordered source walkthrough with highlighted call sites and inline notes,
read [references/call-stack-annotations.md](references/call-stack-annotations.md).
It covers temporary extmarks, annotation cleanup, and refreshing the trace after
source edits.
