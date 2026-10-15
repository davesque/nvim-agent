# /// script
# dependencies = ["msgpack"]
# ///
"""
Which kinds of agent output put the user's editor into a hit-enter prompt?

For each case, sends one request with a 2s timeout, reports whether it
returned, then checks ``nvim_get_mode`` on a fresh connection. If the editor
is blocked, dismisses the prompt from tmux before the next case.

Usage: uv run probes/messages.py .nvim-test.sock %9
"""

import socket
import subprocess
import sys
import time

import msgpack

SOCK, PANE = sys.argv[1], sys.argv[2]

CASES = [
    ("lua print 1 line", "nvim_exec_lua", ["print('one line')", []]),
    ("lua print 3 lines", "nvim_exec_lua", ["print('p1\\np2\\np3')", []]),
    ("lua notify 3 lines", "nvim_exec_lua", ["vim.notify('n1\\nn2\\nn3')", []]),
    ("lua error", "nvim_exec_lua", ["error('boom')", []]),
    ("exec2 echo 3 lines, output", "nvim_exec2", ['echo "e1\\ne2\\ne3"', {"output": True}]),
    ("exec2 echo 3 lines, no output", "nvim_exec2", ['echo "e1\\ne2\\ne3"', {"output": False}]),
    ("exec2 lua print 3 lines, output", "nvim_exec2", ["lua print('p1\\np2\\np3')", {"output": True}]),
    ("exec2 ls, output", "nvim_exec2", ["ls", {"output": True}]),
]

# Candidate wrapper for the skill's run-Lua command: compile the agent's code,
# run it under `:lua` via nvim_exec2 so messages are captured, and return both
# the captured output and the code's return value.
WRAPPER = """
local code = ...
local fn, err = loadstring(code, '=agent')
if not fn then return { ok = false, error = err } end
_G.__agent = { fn = fn }
local cap = vim.api.nvim_exec2(
  'lua _G.__agent.res = { pcall(_G.__agent.fn) }', { output = true })
local res = _G.__agent.res
_G.__agent = nil
return { ok = res[1], value = res[2], output = cap.output }
"""
for label, body in [
    ("wrapped print 3 lines", "print('p1\\np2\\np3'); return 42"),
    ("wrapped notify 3 lines", "vim.notify('n1\\nn2\\nn3'); return 42"),
    ("wrapped nvim_echo 3 lines", "vim.api.nvim_echo({{'x1\\nx2\\nx3'}}, true, {}); return 42"),
    ("wrapped vim.cmd echo 3 lines", "vim.cmd('echo \"c1\\\\nc2\\\\nc3\"'); return 42"),
    ("wrapped error", "error('boom')"),
    ("wrapped echoerr 3 lines", "vim.cmd('echoerr \"r1\\\\nr2\\\\nr3\"')"),
]:
    CASES.append((label, "nvim_exec_lua", [WRAPPER, [body]]))


def request(method, params, timeout=2):
    """
    Send one request on a fresh connection; return the response or 'TIMEOUT'.
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
                return m
    except socket.timeout:
        return "TIMEOUT"
    finally:
        s.close()


for label, method, params in CASES:
    resp = request(method, params)
    mode = request("nvim_get_mode", [])[3]
    if resp != "TIMEOUT":
        resp = {"error": resp[2], "result": resp[3]}
    print(f"{label:34} resp={str(resp)[:70]:72} mode={mode}")
    if mode["blocking"]:
        subprocess.run(["tmux", "send-keys", "-t", PANE, "Enter"], check=True)
        time.sleep(0.3)
