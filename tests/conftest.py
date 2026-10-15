"""
Fixtures: a throwaway headless nvim per test, an RPC client, and a runner for nv.
"""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import msgpack
import pytest

NV = Path(__file__).resolve().parent.parent / "skill" / "neovim" / "scripts" / "nv"


class Rpc:
    """
    Minimal msgpack-rpc client with a socket timeout, for inspecting the editor.

    Parameters
    ----------
    path : str
        Socket path of the nvim to talk to.
    timeout : float
        Seconds to wait for any reply before raising ``TimeoutError``.
    """

    def __init__(self, path: str, timeout: float = 3.0) -> None:
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(timeout)
        self.sock.connect(path)
        self.unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
        self.msgid = 0

    def call(self, method: str, *params: Any) -> Any:
        """
        Send a request and return its result.

        Parameters
        ----------
        method : str
            API method name.
        *params : Any
            Positional parameters.

        Returns
        -------
        Any
            The result, or raises ``RuntimeError`` on an API error.
        """
        self.msgid += 1
        self.sock.sendall(msgpack.packb([0, self.msgid, method, list(params)]))
        try:
            while True:
                for msg in self.unpacker:
                    if msg[0] == 1 and msg[1] == self.msgid:
                        if msg[2] is not None:
                            raise RuntimeError(msg[2])
                        return msg[3]
                self.unpacker.feed(self.sock.recv(1 << 20))
        except socket.timeout as e:
            raise TimeoutError(method) from e

    def send(self, method: str, *params: Any) -> None:
        """
        Send a request without waiting for the reply.

        Parameters
        ----------
        method : str
            API method name.
        *params : Any
            Positional parameters.
        """
        self.msgid += 1
        self.sock.sendall(msgpack.packb([0, self.msgid, method, list(params)]))

    def lua(self, code: str, *args: Any) -> Any:
        """
        Run Lua in the editor and return the result.

        Parameters
        ----------
        code : str
            Lua chunk; arguments are available as ``...``.
        *args : Any
            Arguments passed to the chunk.

        Returns
        -------
        Any
            The chunk's return value.
        """
        return self.call("nvim_exec_lua", code, list(args))

    def close(self) -> None:
        """
        Close the connection.
        """
        self.sock.close()


class FakeUi:
    """
    A UI attached over RPC, so the editor shows prompts as it would with a TUI.

    A headless nvim with no UI never enters the hit-enter prompt. Redraw
    notifications are drained on a thread so nvim never blocks writing them.

    Parameters
    ----------
    path : str
        Socket path of the nvim to attach to.
    """

    def __init__(self, path: str) -> None:
        self.rpc = Rpc(path)
        self.rpc.call("nvim_ui_attach", 80, 24, {"ext_linegrid": True})
        self.rpc.sock.settimeout(None)
        self.thread = threading.Thread(target=self.drain, daemon=True)
        self.thread.start()

    def drain(self) -> None:
        """
        Read and discard everything nvim sends to the UI.
        """
        try:
            while self.rpc.sock.recv(1 << 20):
                pass
        except OSError:
            pass

    def close(self) -> None:
        """
        Detach by closing the connection.
        """
        self.rpc.close()


@dataclass
class NvResult:
    """
    Outcome of one ``nv`` run.

    Attributes
    ----------
    code : int
        Process exit status.
    data : dict
        Parsed JSON from stdout.
    elapsed : float
        Wall time in seconds.
    """

    code: int
    data: dict
    elapsed: float


class Editor:
    """
    A headless nvim started for one test.

    Parameters
    ----------
    workdir : Path
        Short private directory holding the socket and test files.
    """

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.sock = str(workdir / "nvim.sock")
        self.proc = subprocess.Popen(
            ["nvim", "--clean", "--headless", "--listen", self.sock],
            cwd=workdir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 5
        while not os.path.exists(self.sock):
            if time.monotonic() > deadline:
                raise RuntimeError("nvim did not create its socket")
            time.sleep(0.02)
        self.rpc = Rpc(self.sock)
        self.uis: list[FakeUi] = []

    def attach_ui(self) -> FakeUi:
        """
        Attach a fake UI so prompts behave as they do in a terminal.

        Returns
        -------
        FakeUi
            The attached UI.
        """
        ui = FakeUi(self.sock)
        self.uis.append(ui)
        return ui

    def file(self, name: str, text: str) -> Path:
        """
        Write a file in the work directory.

        Parameters
        ----------
        name : str
            File name relative to the work directory.
        text : str
            File contents.

        Returns
        -------
        Path
            Path of the written file.
        """
        path = self.workdir / name
        path.write_text(text)
        return path

    def open(self, path: Path) -> int:
        """
        Edit a file in the editor and return its buffer number.

        Parameters
        ----------
        path : Path
            File to open.

        Returns
        -------
        int
            Buffer number.
        """
        return self.rpc.lua(
            "vim.cmd.edit(vim.fn.fnameescape(...)); return vim.api.nvim_get_current_buf()",
            str(path),
        )

    def lines(self, buf: int = 0) -> list[str]:
        """
        Return a buffer's lines.

        Parameters
        ----------
        buf : int
            Buffer number, 0 for current.

        Returns
        -------
        list of str
            The lines.
        """
        return self.rpc.call("nvim_buf_get_lines", buf, 0, -1, False)

    def mode(self) -> str:
        """
        Return the current mode on a fresh connection.

        Returns
        -------
        str
            Mode string from ``nvim_get_mode``.
        """
        rpc = Rpc(self.sock)
        try:
            return rpc.call("nvim_get_mode")["mode"]
        finally:
            rpc.close()

    def nv(self, *args: str, stdin: str | None = None, env: dict | None = None) -> NvResult:
        """
        Run the real ``nv`` client against this editor.

        Parameters
        ----------
        *args : str
            Command and arguments (``--sock`` is added).
        stdin : str, optional
            Text to feed on stdin.
        env : dict, optional
            Extra environment variables.

        Returns
        -------
        NvResult
            Exit code, parsed JSON, and elapsed time.
        """
        return run_nv("--sock", self.sock, *args, stdin=stdin, env=env, cwd=self.workdir)

    def close(self) -> None:
        """
        Stop the editor and drop connections.
        """
        for ui in self.uis:
            ui.close()
        self.rpc.close()
        self.proc.kill()
        self.proc.wait()


def run_nv(
    *args: str,
    stdin: str | None = None,
    env: dict | None = None,
    cwd: Path | None = None,
) -> NvResult:
    """
    Run ``nv`` and parse its JSON output.

    Parameters
    ----------
    *args : str
        Arguments for ``nv``.
    stdin : str, optional
        Text to feed on stdin.
    env : dict, optional
        Extra environment variables. ``NVIM`` and ``NV_SOCK`` are cleared
        unless given here, so the host environment cannot pick the target.
    cwd : Path, optional
        Working directory for the client.

    Returns
    -------
    NvResult
        Exit code, parsed JSON, and elapsed time.
    """
    full_env = {k: v for k, v in os.environ.items() if k not in ("NVIM", "NV_SOCK", "TMUX_PANE")}
    full_env.update(env or {})
    start = time.monotonic()
    proc = subprocess.run(
        [str(NV), *args],
        input=stdin if stdin is not None else "",
        capture_output=True,
        text=True,
        env=full_env,
        cwd=cwd,
        timeout=20,
    )
    elapsed = time.monotonic() - start
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise AssertionError(f"nv printed non-JSON: {proc.stdout!r} stderr={proc.stderr!r}") from e
    return NvResult(proc.returncode, data, elapsed)


@pytest.fixture
def workdir() -> Iterator[Path]:
    """
    Yield a short private temp directory (Unix socket paths are limited to ~104 bytes).
    """
    path = Path(tempfile.mkdtemp(prefix="nv"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def editor(workdir: Path) -> Iterator[Editor]:
    """
    Yield a fresh headless nvim listening in ``workdir``.
    """
    ed = Editor(workdir)
    try:
        yield ed
    finally:
        ed.close()
