"""
find and target resolution, confined to test socket directories via NV_SOCKET_DIRS.
"""

import socket
import tempfile
from pathlib import Path

from conftest import Editor, run_nv


def scan(*dirs: Path) -> dict:
    return {"NV_SOCKET_DIRS": ":".join(str(d) for d in dirs)}


def test_find_lists_instance(editor: Editor, workdir: Path):
    r = run_nv("find", env=scan(workdir))
    assert r.data["ok"]
    [inst] = r.data["instances"]
    assert inst["servername"] == editor.sock
    assert inst["pid"] == editor.proc.pid
    assert inst["mode"] == "n"
    assert Path(inst["cwd"]).resolve() == workdir.resolve()


def test_find_skips_stale_sockets(editor: Editor, workdir: Path):
    stale = socket.socket(socket.AF_UNIX)
    stale.bind(str(workdir / "nvim.99999.0"))
    stale.close()
    r = run_nv("find", env=scan(workdir))
    assert [i["servername"] for i in r.data["instances"]] == [editor.sock]


def test_find_dedupes_extra_sockets_of_one_server(editor: Editor, workdir: Path):
    editor.rpc.lua("vim.fn.serverstart(...)", str(workdir / "extra.sock"))
    r = run_nv("find", env=scan(workdir))
    assert len(r.data["instances"]) == 1


def test_find_reports_blocked_instance(editor: Editor, workdir: Path):
    editor.attach_ui()
    editor.rpc.call("nvim_input", ':echo "a\\nb\\nc"<CR>')
    r = run_nv("find", env=scan(workdir))
    [inst] = r.data["instances"]
    assert inst["blocked"] is True
    assert inst["mode"] == "r"
    assert r.elapsed < 3


def test_blocked_instance_pid_comes_from_socket_name(editor: Editor):
    sockdir = editor.workdir / "d"
    sockdir.mkdir()
    editor.rpc.lua("vim.fn.serverstart(...)", str(sockdir / f"nvim.{editor.proc.pid}.0"))
    editor.attach_ui()
    editor.rpc.call("nvim_input", ':echo "a\\nb\\nc"<CR>')
    [inst] = run_nv("find", env=scan(sockdir)).data["instances"]
    assert inst["blocked"] is True
    assert inst["pid"] == editor.proc.pid


def test_find_and_target_by_pane(editor: Editor, workdir: Path):
    editor.rpc.lua("vim.env.TMUX_PANE = '%77'")
    r = run_nv("find", "--pane", "%77", env=scan(workdir))
    assert len(r.data["instances"]) == 1
    assert run_nv("find", "--pane", "%78", env=scan(workdir)).data["instances"] == []
    r = run_nv("--pane", "%77", "state", env=scan(workdir))
    assert r.data["socket"] == editor.sock
    assert run_nv("--pane", "%78", "state", env=scan(workdir)).data["error"] == "no_instance"


def test_single_instance_is_picked_automatically(editor: Editor, workdir: Path):
    r = run_nv("state", env=scan(workdir))
    assert r.data["ok"]
    assert r.data["socket"] == editor.sock


def test_no_instance(workdir: Path):
    r = run_nv("state", env=scan(workdir))
    assert r.code == 1
    assert r.data["error"] == "no_instance"


def test_ambiguous_instances(editor: Editor, workdir: Path):
    other_dir = Path(tempfile.mkdtemp(prefix="nv"))
    other = Editor(other_dir)
    try:
        r = run_nv("state", env=scan(workdir, other_dir))
        assert r.data["error"] == "ambiguous"
        assert len(r.data["instances"]) == 2
    finally:
        other.close()
