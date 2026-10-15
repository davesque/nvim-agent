"""
reload: pick up files the agent changed on disk without touching the user's edits.
"""

from conftest import Editor


def status(r):
    return [x["status"] for x in r.data["results"]]


def test_reload_unchanged_buffer(editor: Editor):
    path = editor.file("a.txt", "one\ntwo\n")
    editor.open(path)
    path.write_text("ONE\ntwo\nthree\n")
    r = editor.nv("reload", "a.txt")
    assert status(r) == ["reloaded"]
    assert editor.lines() == ["ONE", "two", "three"]
    assert editor.rpc.lua("return vim.bo.modified") is False


def test_reload_is_undoable(editor: Editor):
    path = editor.file("a.txt", "one\n")
    editor.open(path)
    path.write_text("ONE\n")
    editor.nv("reload", "a.txt")
    editor.rpc.lua("vim.cmd('silent undo')")
    assert editor.lines() == ["one"]


def test_reload_with_autoread_off(editor: Editor):
    editor.rpc.lua("vim.o.autoread = false")
    path = editor.file("a.txt", "one\n")
    editor.open(path)
    path.write_text("ONE\n")
    assert status(editor.nv("reload", "a.txt")) == ["reloaded"]
    assert editor.lines() == ["ONE"]


def test_reload_hidden_buffer_keeps_layout(editor: Editor):
    path = editor.file("a.txt", "one\n")
    buf = editor.open(path)
    editor.rpc.lua("vim.bo.bufhidden = 'hide'; vim.cmd('enew')")
    current = editor.rpc.call("nvim_get_current_buf")
    path.write_text("ONE\n")
    assert status(editor.nv("reload", str(path))) == ["reloaded"]
    assert editor.lines(buf) == ["ONE"]
    assert editor.rpc.call("nvim_get_current_buf") == current


def test_reload_keeps_cursor(editor: Editor):
    path = editor.file("a.txt", "one\ntwo\nthree\n")
    editor.open(path)
    editor.rpc.call("nvim_win_set_cursor", 0, [3, 2])
    path.write_text("one\ntwo\nthree\nfour\n")
    editor.nv("reload", "a.txt")
    assert editor.rpc.call("nvim_win_get_cursor", 0) == [3, 2]


def test_reload_skips_buffer_with_unsaved_changes(editor: Editor):
    path = editor.file("a.txt", "one\n")
    editor.open(path)
    editor.rpc.call("nvim_buf_set_lines", 0, 0, -1, False, ["user edit"])
    path.write_text("agent edit\n")
    r = editor.nv("reload", "a.txt")
    assert status(r) == ["conflict"]
    assert editor.lines() == ["user edit"]
    assert editor.mode() == "n"


def test_reload_reports_unchanged_not_loaded_and_missing(editor: Editor):
    a = editor.file("a.txt", "one\n")
    gone = editor.file("gone.txt", "x\n")
    editor.open(a)
    editor.open(gone)
    gone.unlink()
    editor.file("other.txt", "y\n")
    r = editor.nv("reload", "a.txt", "other.txt", "gone.txt")
    assert status(r) == ["unchanged", "not_loaded", "missing"]
    assert editor.lines() == ["x"]


def test_reload_needs_a_path(editor: Editor):
    assert editor.nv("reload").data["error"] == "usage"
