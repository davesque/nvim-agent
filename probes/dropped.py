# /// script
# dependencies = ["msgpack"]
# ///
"""
Is a request that arrives during a hit-enter prompt run once the prompt clears?

Puts the test nvim (in a tmux pane) into a hit-enter prompt, sends a request
that sets a ``vim.g`` marker, gives up on it, dismisses the prompt, and checks
the marker. Three ways of giving up are tried, several times each:

- ``disconnect``: raw socket closed after a 1s timeout.
- ``abandon``: socket left open after the timeout (client stopped waiting but
  did not hang up). Also reports whether the late response arrives.
- ``killed``: the ``nvim -l`` client from ``client.lua`` killed by ``timeout 1``.

Usage: uv run probes/dropped.py .nvim-test.sock %9 [trials]
"""

import socket
import subprocess
import sys
import time

import msgpack

SOCK, PANE = sys.argv[1], sys.argv[2]
TRIALS = int(sys.argv[3]) if len(sys.argv) > 3 else 5


def connect():
    """
    Open a raw socket to the test nvim.
    """
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(1)
    s.connect(SOCK)
    return s


def call(method, params):
    """
    Send one request on a fresh connection and return the result.
    """
    s = connect()
    s.sendall(msgpack.packb([0, 1, method, params]))
    u = msgpack.Unpacker(raw=False)
    while True:
        u.feed(s.recv(65536))
        for m in u:
            s.close()
            return m[3]


def lua(code):
    """
    Run Lua in the test nvim and return the result.
    """
    return call("nvim_exec_lua", [code, []])


def keys(*k):
    """
    Send keys to the test nvim's tmux pane.
    """
    subprocess.run(["tmux", "send-keys", "-t", PANE, *k], check=True)
    time.sleep(0.3)


def enter_prompt():
    """
    Put the test nvim into a hit-enter prompt and confirm it is blocking.
    """
    keys(':echo "a\\nb\\nc"', "Enter")
    mode = call("nvim_get_mode", [])
    assert mode["blocking"], f"expected a blocking prompt, got {mode}"


def leave_prompt():
    """
    Dismiss the prompt from tmux and confirm the editor is back in normal mode.
    """
    keys("Enter")
    mode = call("nvim_get_mode", [])
    assert not mode["blocking"], f"prompt still up: {mode}"


def send_marker(s, tag):
    """
    Send the marker-setting request and wait 1s for a reply that should not come.
    """
    s.sendall(msgpack.packb([0, 7, "nvim_exec_lua", [f"vim.g.probe_marker = '{tag}'", []]]))
    try:
        data = s.recv(65536)
        return f"unexpected reply {msgpack.unpackb(data, raw=False)}"
    except socket.timeout:
        return "timeout"


def trial(variant, i):
    """
    Run one trial and return (variant, i, marker after prompt, notes).
    """
    tag = f"{variant}{i}"
    lua("vim.g.probe_marker = nil")
    enter_prompt()
    notes = ""
    if variant == "disconnect":
        s = connect()
        notes = send_marker(s, tag)
        s.close()
        leave_prompt()
    elif variant == "abandon":
        s = connect()
        notes = send_marker(s, tag)
        leave_prompt()
        s.settimeout(1)
        try:
            late = msgpack.unpackb(s.recv(65536), raw=False)
            notes += f", late reply {late}"
        except socket.timeout:
            notes += ", no late reply"
        s.close()
    elif variant == "killed":
        code = f"vim.g.probe_marker = '{tag}'"
        r = subprocess.run(
            ["timeout", "1", "nvim", "--clean", "--headless", "-l", "probes/client.lua", SOCK, code],
            capture_output=True,
            text=True,
        )
        notes = f"exit {r.returncode}"
        leave_prompt()
    time.sleep(0.3)
    return variant, i, lua("return vim.g.probe_marker"), notes


for variant in ("disconnect", "abandon", "killed"):
    for i in range(TRIALS):
        v, n, marker, notes = trial(variant, i)
        print(f"{v:10} {n}  marker={marker!r:16} {notes}")
