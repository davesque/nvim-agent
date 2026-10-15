# /// script
# dependencies = ["msgpack"]
# ///
"""
Can the agent safely edit a file buffer while the user is typing in a :terminal?

This is the common setup when the agent runs inside nvim's own terminal. Opens a
scratch buffer and a terminal split in the test nvim, enters terminal mode,
makes an RPC edit to the scratch buffer, types into the terminal, then checks
the mode the RPC saw, whether focus moved, and whether one undo in the scratch
buffer reverts exactly the agent's edit. Cleans up both buffers afterwards.

Usage: uv run probes/terminal_mode.py .nvim-test.sock %9
"""

import socket
import subprocess
import sys
import time

import msgpack

SOCK, PANE = sys.argv[1], sys.argv[2]


def lua(code, *args):
    """
    Run Lua in the test nvim on a fresh connection (3s timeout).
    """
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(3)
    s.connect(SOCK)
    s.sendall(msgpack.packb([0, 1, "nvim_exec_lua", [code, list(args)]]))
    u = msgpack.Unpacker(raw=False, strict_map_key=False)
    while True:
        u.feed(s.recv(65536))
        for m in u:
            s.close()
            if m[2] is not None:
                raise RuntimeError(m[2])
            return m[3]


def keys(*k, literal=False):
    """
    Send keys to the test nvim's tmux pane.
    """
    cmd = ["tmux", "send-keys", "-t", PANE] + (["-l"] if literal else []) + list(k)
    subprocess.run(cmd, check=True)
    time.sleep(0.4)


scratch = lua(
    "vim.cmd('tabnew');"
    "local b = vim.api.nvim_get_current_buf();"
    "vim.bo[b].undolevels = -1;"
    "vim.api.nvim_buf_set_lines(b, 0, -1, false, {'aaa', 'bbb'});"
    "vim.bo[b].undolevels = 1000;"
    "vim.cmd('vsplit | terminal');"
    "return b"
)
keys("i")
mode_before = lua("return vim.api.nvim_get_mode()")
lua("vim.api.nvim_buf_set_text(..., 1, 0, 1, 3, {'BBB'})", scratch)
after_rpc = lua(
    "return {vim.api.nvim_get_mode().mode, vim.bo.buftype, vim.api.nvim_get_current_buf() == ...}",
    scratch,
)
keys("echo typed-into-terminal", literal=True)
keys("Enter")
lines_after = lua("return table.concat(vim.api.nvim_buf_get_lines(..., 0, -1, false), '|')", scratch)
undone = lua(
    "local b = ...;"
    "vim.api.nvim_buf_call(b, function() vim.cmd('silent undo') end);"
    "return table.concat(vim.api.nvim_buf_get_lines(b, 0, -1, false), '|')",
    scratch,
)
print(f"mode before edit:        {mode_before}")
print(f"after rpc [mode, buftype of current, focus on scratch?]: {after_rpc}")
print(f"scratch after edit:      {lines_after}")
print(f"scratch after one undo:  {undone}")
keys("C-\\", "C-n")
lua(
    "local b = ...;"
    "local term = vim.api.nvim_get_current_buf();"
    "vim.cmd('tabclose');"
    "vim.api.nvim_buf_delete(term, {force = true});"
    "vim.api.nvim_buf_delete(b, {force = true})",
    scratch,
)
