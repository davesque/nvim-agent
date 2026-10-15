"""
The safety rules from docs/design.md: prompts, modes, timeouts, output capture.
"""

import os
from pathlib import Path

from conftest import Editor, Rpc, run_nv


def test_hit_enter_prompt_is_reported_as_blocked(editor: Editor):
    editor.attach_ui()
    editor.rpc.call("nvim_input", ':echo "a\\nb\\nc"<CR>')
    assert editor.mode() == "r"
    for cmd in (["state"], ["read"], ["lua", "return 1"], ["ex", "ls"], ["reload", "x"]):
        r = editor.nv(*cmd)
        assert r.data["error"] == "blocked", cmd
        assert r.elapsed < 3


def test_file_changed_dialog_is_blocked_although_not_blocking(editor: Editor):
    editor.attach_ui()
    path = editor.file("a.txt", "one\n")
    editor.open(path)
    editor.rpc.call("nvim_buf_set_lines", 0, 0, -1, False, ["user edit"])
    path.write_text("agent edit\n")
    editor.rpc.call("nvim_input", ":checktime<CR>")
    probe = Rpc(editor.sock)
    mode = probe.call("nvim_get_mode")
    probe.close()
    assert mode == {"mode": "r?", "blocking": False}
    r = editor.nv("state")
    assert r.data["error"] == "blocked"
    assert r.data["mode"] == "r?"


def test_multiline_lua_output_does_not_raise_a_prompt(editor: Editor):
    editor.attach_ui()
    for code in (
        "print('p1\\np2\\np3')",
        "vim.notify('n1\\nn2\\nn3')",
        "vim.api.nvim_echo({{'x1\\nx2\\nx3'}}, true, {})",
        "vim.cmd('echo \"c1\\\\nc2\\\\nc3\"')",
    ):
        r = editor.nv("lua", code, "--timeout", "2000")
        assert r.data["ok"], (code, r.data)
        assert r.data["output"].count("\n") == 2, (code, r.data)
        assert editor.mode() == "n", code


def test_multiline_ex_output_does_not_raise_a_prompt(editor: Editor):
    editor.attach_ui()
    r = editor.nv("ex", 'echo "e1\\ne2\\ne3"')
    assert r.data["output"] == "e1\ne2\ne3"
    assert editor.mode() == "n"


def test_insert_mode_refuses_actions_but_allows_reads(editor: Editor):
    path = editor.file("a.txt", "one\n")
    editor.open(path)
    editor.rpc.call("nvim_input", "i")
    assert editor.mode() == "i"
    path.write_text("ONE\n")
    for cmd in (["reload", "a.txt"], ["lua", "return 1"], ["ex", "ls"]):
        r = editor.nv(*cmd)
        assert r.data["error"] == "mode", cmd
        assert r.data["mode"] == "i"
    assert editor.lines() == ["one"]
    assert editor.nv("state").data["mode"] == "i"
    assert editor.nv("read").data["lines"] == ["one"]
    assert editor.nv("--any-mode", "lua", "return 7").data["value"] == 7


def test_other_refused_modes(editor: Editor):
    editor.rpc.call("nvim_buf_set_lines", 0, 0, -1, False, ["one", "two"])
    for keys, expected in (("v", "v"), ("d", "no"), (":", "c")):
        editor.rpc.call("nvim_input", keys)
        assert editor.mode() == expected
        assert editor.nv("lua", "return 1").data["error"] == "mode", keys
        editor.rpc.call("nvim_input", "<Esc>")


def test_terminal_mode_allows_reload(editor: Editor):
    path = editor.file("a.txt", "one\n")
    buf = editor.open(path)
    editor.rpc.lua("vim.cmd('vsplit | terminal')")
    editor.rpc.call("nvim_input", "i")
    assert editor.mode() == "t"
    path.write_text("ONE\n")
    r = editor.nv("reload", "a.txt")
    assert [x["status"] for x in r.data["results"]] == ["reloaded"]
    assert editor.lines(buf) == ["ONE"]
    assert editor.mode() == "t"
    assert editor.rpc.lua("return vim.bo.buftype") == "terminal"


def test_timeout_exits_and_has_no_side_effect(editor: Editor):
    editor.rpc.send("nvim_exec_lua", "vim.uv.sleep(1500)", [])
    r = editor.nv("lua", "vim.g.nv_marker = 1", "--timeout", "300")
    assert r.code == 124
    assert r.data["error"] == "timeout"
    assert r.elapsed < 1.2
    late = Rpc(editor.sock, timeout=5)
    assert late.lua("return vim.g.nv_marker") is None
    late.close()


def test_client_leaves_no_socket_behind(editor: Editor, workdir: Path):
    tmp = workdir / "t"
    tmp.mkdir()
    env = {"TMPDIR": str(tmp)}
    editor.nv("state", env=env)
    editor.nv("lua", "error('x')", env=env)
    editor.rpc.send("nvim_exec_lua", "vim.uv.sleep(800)", [])
    assert editor.nv("state", "--timeout", "200", env=env).code == 124
    leftovers = [p for p in tmp.rglob("*") if p.is_socket() or p.parent != tmp]
    assert leftovers == []


def test_bad_timeout_value(editor: Editor):
    assert editor.nv("--timeout", "abc", "state").data["error"] == "usage"


def test_nvim_env_var_selects_target(editor: Editor):
    r = run_nv("state", env={"NVIM": editor.sock, "NV_SOCKET_DIRS": os.devnull})
    assert r.data["ok"]
    assert r.data["socket"] == editor.sock
