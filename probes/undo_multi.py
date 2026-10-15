# /// script
# dependencies = ["msgpack"]
# ///
"""
How do RPC edits interact with undo and with a user typing in insert mode?

Edits the current buffer of the test nvim (in a tmux pane). Cases:

- ``separate``: two edits in two separate RPC requests, then one ``:undo``.
- ``joined``: same, but the second request runs ``undojoin`` first.
- ``insert_other_line``: user is mid-insert on line 1, RPC edits line 2, user
  keeps typing, then ``u`` twice from the keyboard.
- ``insert_same_line``: user is mid-insert at the end of line 1, RPC lengthens
  the start of line 1, user keeps typing. Where does the typed text land?
- ``atomic``: one ``nvim_exec_lua`` reads changedtick, sleeps 1s, edits, reads
  changedtick again, while tmux types into the editor during the sleep.

Usage: uv run probes/undo_multi.py .nvim-test.sock %9
"""

import socket
import subprocess
import sys
import threading
import time

import msgpack

SOCK, PANE = sys.argv[1], sys.argv[2]


def call(method, *params):
    """
    Send one request on a fresh connection and return the result (2s timeout).
    """
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(3)
    s.connect(SOCK)
    s.sendall(msgpack.packb([0, 1, method, list(params)]))
    u = msgpack.Unpacker(raw=False, strict_map_key=False)
    while True:
        u.feed(s.recv(65536))
        for m in u:
            s.close()
            if m[2] is not None:
                raise RuntimeError(m[2])
            return m[3]


def lua(code):
    """
    Run Lua in the test nvim and return the result.
    """
    return call("nvim_exec_lua", code, [])


def keys(*k, literal=False):
    """
    Send keys to the test nvim's tmux pane.
    """
    cmd = ["tmux", "send-keys", "-t", PANE] + (["-l"] if literal else []) + list(k)
    subprocess.run(cmd, check=True)
    time.sleep(0.3)


def reset():
    """
    Put ['aaa', 'bbb'] in the current buffer with no undo history, cursor on 1:1.
    """
    keys("Escape")
    lua(
        "vim.bo.undolevels = -1;"
        "vim.api.nvim_buf_set_lines(0, 0, -1, false, {'aaa', 'bbb'});"
        "vim.bo.undolevels = 1000;"
        "vim.api.nvim_win_set_cursor(0, {1, 0})"
    )


def lines():
    """
    Return the current buffer as one '|'-joined string.
    """
    return "|".join(call("nvim_buf_get_lines", 0, 0, -1, False))


def case_separate(join):
    """
    Two edits in two requests, optionally joined, then one undo.
    """
    reset()
    lua("vim.api.nvim_buf_set_text(0, 0, 0, 0, 3, {'AAA'})")
    pre = "vim.cmd('undojoin');" if join else ""
    lua(pre + "vim.api.nvim_buf_set_text(0, 1, 0, 1, 3, {'BBB'})")
    after = lines()
    lua("vim.cmd('silent undo')")
    return {"after": after, "after_one_undo": lines()}


def case_insert(same_line):
    """
    RPC edit while the user is in insert mode, then keyboard undo.
    """
    reset()
    keys("A")
    keys("XX", literal=True)
    mode = call("nvim_get_mode")["mode"]
    if same_line:
        lua("vim.api.nvim_buf_set_text(0, 0, 0, 0, 3, {'AAAAAA'})")
    else:
        lua("vim.api.nvim_buf_set_text(0, 1, 0, 1, 3, {'BBB'})")
    cursor_after_rpc = call("nvim_win_get_cursor", 0)
    keys("YY", literal=True)
    keys("Escape")
    out = {"mode_during": mode, "cursor_after_rpc": cursor_after_rpc, "after": lines()}
    keys("u")
    out["after_u1"] = lines()
    keys("u")
    out["after_u2"] = lines()
    return out


def case_atomic():
    """
    Check that keys typed during a long nvim_exec_lua cannot land mid-request.
    """
    reset()
    keys("A")
    code = (
        "local t0 = vim.b.changedtick;"
        "local l0 = vim.api.nvim_buf_get_lines(0, 0, -1, false);"
        "vim.uv.sleep(1000);"
        "local l1 = vim.api.nvim_buf_get_lines(0, 0, -1, false);"
        "vim.api.nvim_buf_set_text(0, 1, 0, 1, 3, {'BBB'});"
        "return {t0, vim.b.changedtick, table.concat(l0, '|'), table.concat(l1, '|')}"
    )
    result = {}
    worker = threading.Thread(target=lambda: result.update(r=lua(code)))
    worker.start()
    time.sleep(0.3)
    subprocess.run(["tmux", "send-keys", "-t", PANE, "-l", "ZZ"], check=True)
    worker.join()
    time.sleep(0.3)
    keys("Escape")
    t0, t1, before_sleep, after_sleep = result["r"]
    return {
        "tick_before": t0,
        "tick_after": t1,
        "lines_before_sleep": before_sleep,
        "lines_after_sleep": after_sleep,
        "final": lines(),
    }


for name, fn in [
    ("separate", lambda: case_separate(False)),
    ("joined", lambda: case_separate(True)),
    ("insert_other_line", lambda: case_insert(False)),
    ("insert_same_line", lambda: case_insert(True)),
    ("atomic", case_atomic),
]:
    print(f"{name:18} {fn()}")
reset()
