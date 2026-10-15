"""
Happy paths and error shapes for each nv command.
"""

from conftest import NV, Editor, run_nv


def test_no_args_prints_usage():
    import subprocess

    proc = subprocess.run([str(NV)], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 2
    assert proc.stdout.startswith("usage: nv")


def test_unknown_command(editor: Editor):
    r = editor.nv("frobnicate")
    assert r.code == 1
    assert r.data["error"] == "usage"


def test_state_reports_mode_cwd_and_buffers(editor: Editor):
    path = editor.file("a.txt", "one\ntwo\n")
    editor.open(path)
    editor.rpc.call("nvim_buf_set_lines", 0, 0, 1, False, ["ONE"])
    r = editor.nv("state")
    assert r.code == 0 and r.data["ok"]
    assert r.data["mode"] == "n"
    assert r.data["current"]["line_count"] == 2
    assert r.data["current"]["modified"] is True
    assert [b["modified"] for b in r.data["buffers"]] == [True]
    assert r.data["buffers"][0]["path"].endswith("a.txt")
    assert len(r.data["windows"]) == 1


def test_read_whole_buffer_and_range(editor: Editor):
    editor.open(editor.file("a.txt", "one\ntwo\nthree\n"))
    r = editor.nv("read")
    assert r.data["lines"] == ["one", "two", "three"]
    assert r.data["start"] == 1
    r = editor.nv("read", "a.txt", "2", "3")
    assert r.data["lines"] == ["two", "three"]
    assert r.data["start"] == 2


def test_read_sees_unsaved_changes(editor: Editor):
    editor.open(editor.file("a.txt", "one\n"))
    editor.rpc.call("nvim_buf_set_lines", 0, 0, -1, False, ["unsaved"])
    assert editor.nv("read", "a.txt").data["lines"] == ["unsaved"]


def test_read_resolves_relative_path_against_client_cwd(editor: Editor):
    editor.open(editor.file("a.txt", "one\n"))
    sub = editor.workdir / "sub"
    sub.mkdir()
    r = run_nv("--sock", editor.sock, "read", "../a.txt", cwd=sub)
    assert r.data["lines"] == ["one"]


def test_read_errors(editor: Editor):
    editor.open(editor.file("a.txt", "one\n"))
    assert editor.nv("read", "missing.txt").data["error"] == "not_loaded"
    assert editor.nv("read", "a.txt", "1", "5").data["error"] == "usage"
    assert editor.nv("read", "a.txt", "x").data["error"] == "usage"


def test_lua_returns_value_and_captured_output(editor: Editor):
    r = editor.nv("lua", "print('a\\nb'); return {x = 1}")
    assert r.data["ok"]
    assert r.data["value"] == {"x": 1}
    assert r.data["output"] == "a\nb"


def test_lua_reads_code_from_stdin(editor: Editor):
    assert editor.nv("lua", stdin="return 1 + 1").data["value"] == 2
    assert editor.nv("lua", "-", stdin="return 'x'").data["value"] == "x"


def test_lua_nil_and_unserializable_values(editor: Editor):
    assert editor.nv("lua", "local x = 1").data["value"] is None
    value = editor.nv("lua", "return print").data["value"]
    assert isinstance(value, str) and "function" in value


def test_lua_errors(editor: Editor):
    r = editor.nv("lua", "error('boom')")
    assert r.code == 1
    assert r.data["error"] == "lua_error"
    assert "boom" in r.data["message"]
    assert editor.nv("lua", "this is not lua").data["error"] == "lua_error"


def test_lua_leaves_no_global(editor: Editor):
    editor.nv("lua", "return 1")
    assert editor.rpc.lua("return _G.__nv == nil") is True


def test_ex_captures_output(editor: Editor):
    r = editor.nv("ex", "echo", "'hi'")
    assert r.data == {"ok": True, "output": "hi", "socket": editor.sock}


def test_ex_error(editor: Editor):
    r = editor.nv("ex", "notacommand")
    assert r.code == 1
    assert r.data["error"] == "ex_error"
