# Display and annotate a call stack

Use this workflow when the user wants to follow a source-level call chain in
Neovim. It displays numbered call sites, URL/configuration decisions, and the
failure point without inserting comments into source files. These are source
annotations, not a captured runtime stack; label inferred branches accordingly.

## Arrange the source

1. Inspect `nv state` and read the relevant buffers with `nv read`. Trace the
   actual caller-to-callee expressions, including construction and initialization
   that can fail before the intended operation runs.
2. If the user requests an ordered view, arrange one file per tab from entrypoint
   to failure site. Use `nv ex 'tabedit /absolute/path/to/file'` for missing views
   and `nv lua` with `nvim_list_tabpages`, `nvim_tabpage_list_wins`, and
   `nvim_win_get_buf` to inspect existing tabs. Reuse existing views where possible.
   Do not close unrelated tabs or change the layout unless requested. Never use
   forced close commands to discard unsaved buffers.
3. Number the call sites in execution order, even when several occur in one file.
   Add separate notes for configuration selection, normalization, and exception
   propagation back to the caller's logging statement.

Run commands through this skill's absolute `scripts/nv` path. The examples below
use `<skill-dir>` as a placeholder. Keep the same explicit socket or pane selector
on each call when several editors exist.

## Add highlights and inline notes

Use `nv lua` to create buffer extmarks in a dedicated named namespace. Each mark
combines a line highlight with end-of-line virtual text. Suggested built-in groups:

| Meaning                       | Highlight group   |
| ----------------------------- | ----------------- |
| Call to the next frame        | `DiffText`        |
| Configuration or URL decision | `Search`          |
| Newly added mitigation        | `DiffAdd`         |
| Original exception site       | `DiagnosticError` |
| Explanatory note text         | `Comment`         |

Colors depend on the user's theme. Keep notes short enough to remain useful in
narrow windows. Namespace names should identify the investigation, such as
`agent_example_callstack`; reuse that name when refreshing the same annotations.

This example assumes `/tmp/stack-example/entry.py` and
`/tmp/stack-example/client.py` are already loaded. Replace the paths, anchors, and
notes with the source being explained. Anchors are literal substrings and must
match exactly one line within their optional 1-based bounds. Narrow the bounds or
use a more distinctive expression when a file repeats the same call.

```sh
<skill-dir>/scripts/nv lua - <<'LUA'
local namespace = vim.api.nvim_create_namespace('agent_example_callstack')
local specs = {
  {path='/tmp/stack-example/entry.py', anchor='client.publish()',
   group='DiffText', note='1: entrypoint -> publish'},
  {path='/tmp/stack-example/client.py', anchor='self.load_schema()',
   group='DiffText', note='2: publish -> load_schema'},
  {path='/tmp/stack-example/client.py', anchor='raise RuntimeError(',
   group='DiagnosticError', note='3: original failure site'},
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
-- Clear only this investigation's marks, including files dropped from the trace.
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
the correct statement. In this investigation, an import and a normalization block
shifted the call sites while old notes remained on unrelated lines after reload.

Read the current buffers, resolve the anchors again, then rebuild the namespace.
Update the wording too: a note saying a metadata URL is used verbatim becomes
misleading once a later step normalizes its path. Preserve the original failure
site, and annotate the mitigation before the request that it changes. Verify all
frames, including unchanged caller files, against their current buffer contents.

To remove this investigation's annotations without altering other decorations:

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
