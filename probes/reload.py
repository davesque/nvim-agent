# /// script
# dependencies = ["msgpack"]
# ///
"""
How should the agent make nvim pick up a file it changed on disk?

For each case: open a file in a new tab of the test nvim (in a tmux pane),
optionally make the buffer modified, optionally hide it, change the file on
disk, then try a reload method with a 2s timeout. Reports whether the request
returned, the mode afterwards (dismissing any dialog from tmux with ``o``,
which keeps the buffer as is), the buffer text, the cursor, and what one
``:undo`` gives. Restores 'autoread' and wipes the buffer after each case.

Methods:
- ``checktime``: ``:checktime <buf>`` via nvim_exec2 with output captured.
- ``edit``: ``:edit`` inside ``nvim_buf_call`` (fails with E37 on a modified
  buffer rather than prompting, if the docs are right).

Usage: uv run probes/reload.py .nvim-test.sock %9
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import msgpack

SOCK, PANE = sys.argv[1], sys.argv[2]
WORK = Path.home() / "agent-workspace"
WORK.mkdir(exist_ok=True)

RELOAD = {
    "checktime": "local b = ...; return vim.api.nvim_exec2('checktime ' .. b, {output = true}).output",
    "edit": "local b = ...; vim.api.nvim_buf_call(b, function() vim.cmd('edit') end); return 'ok'",
}


def request(method, params, timeout=2):
    """
    Send one request on a fresh connection; return (error, result) or 'TIMEOUT'.
    """
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    s.connect(SOCK)
    s.sendall(msgpack.packb([0, 1, method, params]))
    u = msgpack.Unpacker(raw=False, strict_map_key=False)
    try:
        while True:
            u.feed(s.recv(65536))
            for m in u:
                return m[2], m[3]
    except socket.timeout:
        return "TIMEOUT"
    finally:
        s.close()


def lua(code, *args):
    """
    Run Lua and return its result, raising on error or timeout.
    """
    r = request("nvim_exec_lua", [code, list(args)])
    if r == "TIMEOUT" or r[0] is not None:
        raise RuntimeError(r)
    return r[1]


def case(label, method, autoread, modified, hidden):
    """
    Run one reload case and print the outcome.
    """
    path = WORK / f"reload-{label.replace(' ', '-')}.txt"
    path.write_text("one\ntwo\nthree\n")
    saved_autoread = lua("return vim.o.autoread")
    buf = lua(
        "local path, autoread, modified, hidden = ...;"
        "vim.o.autoread = autoread;"
        "vim.cmd('tabnew ' .. vim.fn.fnameescape(path));"
        "local b = vim.api.nvim_get_current_buf();"
        "vim.api.nvim_win_set_cursor(0, {3, 2});"
        "if modified then vim.api.nvim_buf_set_lines(b, 0, 1, false, {'user-edit'}) end;"
        "if hidden then vim.bo[b].bufhidden = 'hide'; vim.cmd('enew') end;"
        "return b",
        str(path), autoread, modified, hidden,
    )
    time.sleep(1.1)  # make sure the mtime differs
    path.write_text("ONE\ntwo\nthree\nfour\n")
    resp = request("nvim_exec_lua", [RELOAD[method], [buf]])
    mode = request("nvim_get_mode", [])[1]
    if mode["mode"].startswith("r"):
        subprocess.run(["tmux", "send-keys", "-t", PANE, "o"], check=True)
        time.sleep(0.4)
    state = lua(
        "local b = ...;"
        "local lines = table.concat(vim.api.nvim_buf_get_lines(b, 0, -1, false), '|');"
        "local cur = vim.fn.win_findbuf(b)[1] and vim.api.nvim_win_get_cursor(vim.fn.win_findbuf(b)[1]) or 'hidden';"
        "local undone = vim.api.nvim_buf_call(b, function()"
        "  local ok = pcall(vim.cmd, 'silent undo');"
        "  return ok and table.concat(vim.api.nvim_buf_get_lines(b, 0, -1, false), '|') or 'undo failed' end);"
        "return {lines, cur, undone, vim.bo[b].modified}",
        buf,
    )
    lua(
        "local b, ar = ...; vim.o.autoread = ar;"
        "local scratch = vim.api.nvim_get_current_buf();"
        "if #vim.api.nvim_list_tabpages() > 1 then vim.cmd('tabclose!') end;"
        "for _, x in ipairs({b, scratch}) do"
        "  if x ~= vim.api.nvim_get_current_buf() and vim.api.nvim_buf_is_valid(x) then vim.api.nvim_buf_delete(x, {force = true}) end end",
        buf, saved_autoread,
    )
    path.unlink()
    if resp != "TIMEOUT":
        resp = f"error={str(resp[0])[:50]!r}" if resp[0] else f"ok {str(resp[1])[:30]!r}"
    lines, cursor, undone, still_modified = state
    print(
        f"{label:34} resp={resp:58} mode={mode['mode']:3} lines={lines:22} "
        f"cursor={cursor} undo->{undone} modified={still_modified}"
    )


for method in ("checktime", "edit"):
    for autoread in (True, False):
        for modified in (False, True):
            label = f"{method} ar={'on' if autoread else 'off'} {'modified' if modified else 'clean'}"
            case(label, method, autoread, modified, hidden=False)
    case(f"{method} ar=on clean hidden", method, True, False, hidden=True)
