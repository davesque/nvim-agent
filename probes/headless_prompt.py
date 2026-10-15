# /// script
# dependencies = ["msgpack"]
# ///
"""
Can a headless nvim reproduce the hit-enter prompt, for automated tests?

Starts its own ``nvim --clean --headless --listen`` (socket under
~/agent-workspace), triggers a multi-line message, and checks
``nvim_get_mode``. Then repeats with a UI attached from a second connection via
``nvim_ui_attach``, the way a TUI would attach. Kills the nvim afterwards.

Usage: uv run probes/headless_prompt.py
"""

import os
import socket
import subprocess
import time
from pathlib import Path

import msgpack

WORK = Path.home() / "agent-workspace"
WORK.mkdir(exist_ok=True)
SOCK = str(WORK / "headless-probe.sock")


class Conn:
    """
    Raw msgpack-rpc connection that skips notifications.
    """

    def __init__(self):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.settimeout(2)
        self.s.connect(SOCK)
        self.u = msgpack.Unpacker(raw=False, strict_map_key=False)
        self.msgid = 0

    def call(self, method, *params):
        """
        Send a request; return its result or 'TIMEOUT'.
        """
        self.msgid += 1
        self.s.sendall(msgpack.packb([0, self.msgid, method, list(params)]))
        try:
            while True:
                for m in self.u:
                    if m[0] == 1 and m[1] == self.msgid:
                        return m[3] if m[2] is None else f"ERROR {m[2]}"
                self.u.feed(self.s.recv(1 << 20))
        except socket.timeout:
            return "TIMEOUT"


def trial(label, ui):
    """
    Trigger a multi-line message and report the mode, with or without a UI.
    """
    if os.path.exists(SOCK):
        os.remove(SOCK)
    proc = subprocess.Popen(["nvim", "--clean", "--headless", "--listen", SOCK])
    for _ in range(50):
        if os.path.exists(SOCK):
            break
        time.sleep(0.05)
    try:
        if ui:
            ui_conn = Conn()
            ui_conn.call("nvim_ui_attach", 80, 24, {"ext_linegrid": True})
        c = Conn()
        c.call("nvim_input", ':echo "a\\nb\\nc"<CR>')
        time.sleep(0.3)
        mode = Conn().call("nvim_get_mode")
        count = Conn().call("nvim_buf_line_count", 0)
        print(f"{label:16} mode={mode} buf_line_count={count}")
    finally:
        proc.kill()
        proc.wait()
        if os.path.exists(SOCK):
            os.remove(SOCK)


trial("headless, no UI", ui=False)
trial("headless + UI", ui=True)
