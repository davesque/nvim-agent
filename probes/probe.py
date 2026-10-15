# /// script
# dependencies = ["msgpack"]
# ///
"""
Raw msgpack-rpc probe against a running nvim socket.
"""

import json
import socket
import sys

import msgpack


class Rpc:
    """
    Minimal msgpack-rpc client that records notifications.
    """

    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(path)
        self.unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
        self.msgid = 0
        self.notes = []

    def read_msg(self):
        while True:
            for msg in self.unpacker:
                return msg
            self.unpacker.feed(self.sock.recv(65536))

    def call(self, method, *args):
        self.msgid += 1
        self.sock.sendall(msgpack.packb([0, self.msgid, method, list(args)]))
        while True:
            msg = self.read_msg()
            if msg[0] == 1 and msg[1] == self.msgid:
                if msg[2] is not None:
                    raise RuntimeError(msg[2])
                return msg[3]
            if msg[0] == 2:
                self.notes.append(msg)


def ext_default(o):
    if isinstance(o, msgpack.ExtType):
        return f"Ext({o.code},{o.data.hex()})"
    return repr(o)


def show(label, val):
    print(f"## {label}\n{json.dumps(val, default=ext_default)[:800]}\n")


r = Rpc(sys.argv[1])
chan, info = r.call("nvim_get_api_info")
show("channel id / version", [chan, info["version"]])
show("num functions / ui_events / types", [len(info["functions"]), len(info["ui_events"]), info["types"]])
show("mode", r.call("nvim_get_mode"))
buf = r.call("nvim_get_current_buf")
show("current buf (ext type)", buf)
show("buf name", r.call("nvim_buf_get_name", buf))
show("set lines", r.call("nvim_buf_set_lines", buf, 0, -1, False, ["hello from the agent", "line two", "line three"]))
show("get lines", r.call("nvim_buf_get_lines", buf, 0, -1, False))
show("set cursor", r.call("nvim_win_set_cursor", 0, [2, 5]))
show("cursor", r.call("nvim_win_get_cursor", 0))
show("exec_lua", r.call("nvim_exec_lua", "return {vim.fn.getcwd(), vim.bo.filetype, #vim.api.nvim_list_bufs()}", []))
show("exec2 ex cmd w/ output", r.call("nvim_exec2", "echo 'hi' | ls", {"output": True}))
# attach to buffer change events, then make a change and collect the notification
show("buf_attach", r.call("nvim_buf_attach", buf, False, {}))
r.call("nvim_buf_set_text", buf, 0, 0, 0, 5, ["HELLO"])
r.call("nvim_get_mode")  # round trip to flush notifications
show("notifications after edit", r.notes)
show("diagnostics", r.call("nvim_exec_lua", "return vim.diagnostic.get(0)", []))
show("eval", r.call("nvim_eval", "[line('$'), &modified, mode()]"))
