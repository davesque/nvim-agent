# Display and annotate a call stack

Use this workflow when the user wants to follow a source-level call chain in
Neovim. Highlight calls and add inline notes that explain how execution reaches
a chosen operation or result, without inserting comments into source files.
Distinguish a source-derived path from an observed runtime trace, and label
conditional or inferred edges accordingly.

## Arrange the source

1. Inspect `nv state` and read the relevant buffers with `nv read`. Trace the
   actual caller-to-callee expressions between the requested starting point and
   endpoint. Include indirect calls, callbacks, or initialization when they are
   part of that path; identify unresolved targets rather than guessing.
2. If the user requests an ordered view, arrange one file per tab from entrypoint
   to the chosen endpoint. Use `nv ex 'tabedit /absolute/path/to/file'` for missing views
   and `nv lua` with `nvim_list_tabpages`, `nvim_tabpage_list_wins`, and
   `nvim_win_get_buf` to inspect existing tabs. Reuse existing views where possible.
   Do not close unrelated tabs or change the layout unless requested. Never use
   forced close commands to discard unsaved buffers.
3. Number the call sites along the selected path, even when several occur in
   one file. Explain branches, argument transformations, or return paths only
   where they help connect the steps. For async or concurrent paths, describe
   scheduling and callback relationships without implying a single synchronous
   stack. For repeated or recursive calls, identify the relevant occurrence.
   Error and exception annotations are optional, for failure investigations.

Run commands through this skill's absolute `scripts/nv` path. The examples below
use `<skill-dir>` as a placeholder. Keep the same explicit socket or pane selector
on each call when several editors exist.

## Add highlights and inline notes

Use `nv lua` to create buffer extmarks in a dedicated named namespace. Each mark
combines a line highlight with end-of-line virtual text. Suggested built-in groups:

| Meaning                                 | Highlight group   |
| --------------------------------------- | ----------------- |
| Call to the next step                   | `DiffText`        |
| Relevant branch or value transformation | `Search`          |
| Chosen endpoint or result               | `Visual`          |
| Changed behavior, when comparing edits  | `DiffAdd`         |
| Error site, when tracing a failure      | `DiagnosticError` |
| Explanatory note text                   | `Comment`         |

Colors depend on the user's theme. Keep notes short enough to remain useful in
narrow windows. Namespace names should identify the walkthrough, such as
`agent_example_callstack`; reuse that name when refreshing the same annotations.

This example assumes `/tmp/stack-example/entry.py` and
`/tmp/stack-example/worker.py` are already loaded. Replace the paths, anchors, and
notes with the source being explained. Anchors are literal substrings and must
match exactly one line within their optional 1-based bounds. Narrow the bounds or
use a more distinctive expression when a file repeats the same call.

```sh
<skill-dir>/scripts/nv lua - <<'LUA'
local namespace = vim.api.nvim_create_namespace('agent_example_callstack')
local specs = {
  {path='/tmp/stack-example/entry.py', anchor='worker.process()',
   group='DiffText', note='1: entrypoint -> process'},
  {path='/tmp/stack-example/worker.py', anchor='self.transform()',
   group='DiffText', note='2: process -> transform'},
  {path='/tmp/stack-example/worker.py', anchor='return result',
   group='Visual', note='3: transform returns the result'},
}
local resolved, buffers = {}, {}
-- Resolve every anchor before replacing any existing annotations.
for _, spec in ipairs(specs) do
  local buf = vim.fn.bufnr(spec.path)
  assert(buf ~= -1 and vim.api.nvim_buf_is_loaded(buf),
    'Buffer must already be loaded: ' .. spec.path)
  local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
  local matches = {}
  for line, text in ipairs(lines) do
    if line >= (spec.first or 1) and line <= (spec.last or #lines)
        and text:find(spec.anchor, 1, true) then
      table.insert(matches, line)
    end
  end
  assert(#matches == 1,
    'Expected one anchor match in ' .. spec.path .. ': ' .. spec.anchor)
  table.insert(resolved, {buf=buf, row=matches[1]-1, spec=spec})
  buffers[buf] = true
end
-- Clear only this walkthrough's marks, including files dropped from the trace.
for _, buf in ipairs(vim.api.nvim_list_bufs()) do
  if vim.api.nvim_buf_is_loaded(buf) then
    vim.api.nvim_buf_clear_namespace(buf, namespace, 0, -1)
  end
end
for _, mark in ipairs(resolved) do
  vim.api.nvim_buf_set_extmark(mark.buf, namespace, mark.row, 0, {
    line_hl_group=mark.spec.group,
    virt_text={{'  ' .. mark.spec.note, 'Comment'}},
    virt_text_pos='eol',
    priority=150,
  })
end
local result = {}
for buf in pairs(buffers) do
  local marks = vim.api.nvim_buf_get_extmarks(buf, namespace, 0, -1,
    {details=true})
  for _, mark in ipairs(marks) do
    table.insert(result, {
      path=vim.api.nvim_buf_get_name(buf), line=mark[2]+1,
      text=vim.api.nvim_buf_get_lines(buf, mark[2], mark[2]+1, false)[1],
      note=mark[4].virt_text,
    })
  end
end
return result
LUA
```

Check `ok` and inspect the returned source text beside each note. Human line
numbers are 1-based; extmark rows are 0-based. Do not use `--any-mode` for these
mutating calls. Extmarks are editor decorations; creating them does not edit or
save buffer text. They are temporary, so rerun the recipe if the session or
buffers are recreated.

## Refresh after edits

Follow the skill's disk-edit and `nv reload` workflow first. Extmarks can move with
buffer edits, but their position alone does not prove that a note still describes
the correct statement. Insertions, deletions, and reloads can leave annotations
attached to unrelated lines.

Read the current buffers, resolve the anchors again, then rebuild the namespace.
Recheck each note's meaning as well as its position: edits can change the callee,
branch condition, inputs, or result. Revise the path and numbering if the chain
changes. Verify all annotated files against their current buffer contents,
including caller files that were not edited.

To remove this walkthrough's annotations without altering other decorations:

```sh
<skill-dir>/scripts/nv lua - <<'LUA'
local ns = vim.api.nvim_get_namespaces()['agent_example_callstack']
if ns then
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.api.nvim_buf_is_loaded(buf) then
      vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
    end
  end
end
return {cleared=ns ~= nil}
LUA
```
