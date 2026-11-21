"""Harness-side oracle broker for binary-recovery tasks.

A binary-recovery task hands the agent a stripped probe and lets it query that
probe as an oracle. Left alone, the probe is a free, unmeasured oracle: an
adapter can call it a thousand times and the harness would never know, which
makes "recovered the semantics" and "enumerated the input space" look the same
in a report. The protocol's oracle-budget curve cannot exist without a count.

This module puts the probe behind a broker owned by the runner::

    agent -> workspace/probe (shim) -> broker -> real probe

The broker counts every served query, enforces ``budgets.oracle_queries`` when
the manifest sets one, and distinguishes served from refused calls. The real
probe never enters the workspace; the generated shim only knows the broker's
address.

**This is accounting, not a sandbox.** An adapter that walks the filesystem can
find the artifact cache and execute the probe directly, and nothing here would
notice. Process isolation is still required for real runs; the protocol says so
and the report repeats it next to the number.

The module imports only the standard library and never opens a network
connection beyond the loopback socket the broker itself listens on.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .process import OutputLimitExceeded, ProcessCancelled, run_bounded

PROTOCOL = 1
QUERY_TIMEOUT = 30
MAX_QUERY_BYTES = 1024 * 1024
MAX_REPLY_BYTES = 1024 * 1024
_HEADER_LIMIT = 4096
REQUEST_READ_TIMEOUT = 5


class OracleError(Exception):
    """The broker could not answer a query."""


def probe_environment() -> dict[str, str]:
    """Runtime environment for trusted probes; never inherit model secrets."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "LC_ALL": "C", "LANG": "C"}
    for key in ("SYSTEMROOT", "WINDIR"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


@dataclass
class OracleStats:
    """What the broker observed, not what the adapter claims."""

    queries: int = 0
    refused: int = 0
    failed: int = 0
    budget: int | None = None
    transport: str = ""
    address: str = ""
    enforcement: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "queries": self.queries,
            "refused": self.refused,
            "failed": self.failed,
            "budget": self.budget,
            "transport": self.transport,
            "enforcement": self.enforcement,
        }


class OracleBroker:
    """Owns the probe; the workspace only gets a shim that talks to this.

    POSIX uses a Unix domain socket in a private temporary directory; Windows
    uses loopback TCP on an ephemeral port (AF_UNIX is not dependable there).
    Either way the shim is the only documented path to the probe.
    """

    def __init__(self, command: list[str], *, budget: int | None = None,
                 query_timeout: int = QUERY_TIMEOUT,
                 cwd: str | Path | None = None):
        if not command:
            raise OracleError("oracle broker needs a command")
        self.command = list(command)
        self._budget = budget
        self._query_timeout = query_timeout
        self._cwd = str(cwd) if cwd is not None else None
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connection_lock = threading.Lock()
        self._connection: socket.socket | None = None
        self.stats = OracleStats(
            budget=budget,
            enforcement=("enforced by harness broker" if budget is not None
                         else "counted by harness broker (no cap)"))
        self._address = ""
        self._transport = ""

    # -- lifecycle -------------------------------------------------------

    def start(self) -> "OracleBroker":
        if os.name == "posix":
            self._tmpdir = tempfile.mkdtemp(prefix="aegis-oracle-")
            path = os.path.join(self._tmpdir, "oracle.sock")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(path)
            self._address = path
            self._transport = "unix"
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            host, port = sock.getsockname()[:2]
            self._address = f"{host}:{port}"
            self._transport = "tcp"
        sock.listen(8)
        sock.settimeout(0.2)
        self._sock = sock
        self.stats.transport = self._transport
        self.stats.address = self._address
        self._thread = threading.Thread(
            target=self._accept_loop, name="aegis-oracle", daemon=True)
        self._thread.start()
        return self

    def cancel(self) -> None:
        """Interrupt an active query or a client that has not finished sending."""
        self._stop.set()
        with self._connection_lock:
            if self._connection is not None:
                try:
                    self._connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def stop(self) -> None:
        self.cancel()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise OracleError("oracle worker did not stop after cancellation")
            self._thread = None
        if self._transport == "unix":
            try:
                os.unlink(self._address)
            except OSError:
                pass
            try:
                os.rmdir(self._tmpdir)
            except OSError:
                pass

    def __enter__(self) -> "OracleBroker":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    @property
    def address(self) -> str:
        return self._address

    @property
    def transport(self) -> str:
        return self._transport

    # -- serving ---------------------------------------------------------

    def _accept_loop(self) -> None:
        assert self._sock is not None
        listener = self._sock
        while not self._stop.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._connection_lock:
                if self._stop.is_set():
                    conn.close()
                    break
                conn.settimeout(REQUEST_READ_TIMEOUT)
                self._connection = conn
            try:
                self._handle(conn)
            except Exception:  # noqa: BLE001 - one bad client must not stop
                self.stats.failed += 1
            finally:
                with self._connection_lock:
                    self._connection = None
                try:
                    conn.close()
                except OSError:
                    pass

    @staticmethod
    def _recv_exact(conn: socket.socket, count: int) -> bytes:
        chunks: list[bytes] = []
        remaining = count
        while remaining > 0:
            chunk = conn.recv(min(remaining, 65536))
            if not chunk:
                raise OracleError("client closed the connection mid-request")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_header(self, conn: socket.socket) -> bytes:
        header = b""
        while not header.endswith(b"\n"):
            if len(header) > _HEADER_LIMIT:
                raise OracleError("request header too long")
            chunk = conn.recv(1)
            if not chunk:
                raise OracleError("client closed the connection before a header")
            header += chunk
        return header

    def _respond(self, conn: socket.socket, *, ok: bool, exit_code: int = 125,
                 out: bytes = b"", err: bytes = b"",
                 error: str = "") -> None:
        if self._stop.is_set():
            return
        header = json.dumps({
            "ok": ok, "exit": exit_code,
            "out_len": len(out), "err_len": len(err), "error": error,
        }).encode() + b"\n"
        try:
            conn.sendall(header + out + err)
        except OSError:
            # The query itself already set its failed count. A disconnected
            # client must not count the same failed execution a second time.
            pass

    def _handle(self, conn: socket.socket) -> None:
        request = json.loads(self._read_header(conn))
        if request.get("op") != "query" or request.get("protocol") != PROTOCOL:
            self._respond(conn, ok=False, error="unsupported oracle protocol")
            return
        length = request.get("len")
        if not isinstance(length, int) or length < 0 or length > MAX_QUERY_BYTES:
            self._respond(conn, ok=False, error="bad query length")
            return
        payload = self._recv_exact(conn, length)
        if self._stop.is_set():
            return
        if self._budget is not None and self.stats.queries >= self._budget:
            self.stats.refused += 1
            self._respond(conn, ok=False,
                          error=f"oracle budget exhausted "
                                f"({self._budget} queries)")
            return
        self.stats.queries += 1
        try:
            proc = run_bounded(
                self.command, input=payload, timeout=self._query_timeout,
                max_stdout_bytes=MAX_REPLY_BYTES,
                max_stderr_bytes=MAX_REPLY_BYTES,
                cwd=self._cwd, env=probe_environment(), cancel_event=self._stop)
        except (OSError, subprocess.TimeoutExpired, OutputLimitExceeded,
                ProcessCancelled) as exc:
            self.stats.failed += 1
            self._respond(conn, ok=False, error=f"probe failed: {exc}")
            return
        self._respond(conn, ok=True, exit_code=proc.returncode,
                      out=proc.stdout, err=proc.stderr)


def query(address: str, payload: bytes, *, transport: str,
          timeout: float = QUERY_TIMEOUT) -> tuple[int, bytes, bytes]:
    """One query against a broker; mirrors what the shim does.

    Kept here (rather than only in the generated shim) so tests exercise the
    protocol without spawning a subprocess for every assertion.
    """
    if len(payload) > MAX_QUERY_BYTES:
        raise OracleError(f"query is larger than {MAX_QUERY_BYTES} bytes")
    if transport == "unix":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        target: Any = address
    else:
        host, _, port = address.rpartition(":")
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        target = None
    try:
        if target is not None:
            sock.connect(target)
        header = json.dumps({"op": "query", "protocol": PROTOCOL,
                             "len": len(payload)}).encode() + b"\n"
        sock.sendall(header)
        sock.sendall(payload)
        reply_bytes = b""
        while not reply_bytes.endswith(b"\n"):
            if len(reply_bytes) > _HEADER_LIMIT:
                raise OracleError("reply header too long")
            chunk = sock.recv(1)
            if not chunk:
                raise OracleError("broker closed the connection")
            reply_bytes += chunk
        reply = json.loads(reply_bytes)
        if not reply.get("ok"):
            raise OracleError(str(reply.get("error") or "query refused"))
        out = OracleBroker._recv_exact(sock, int(reply["out_len"]))
        err = OracleBroker._recv_exact(sock, int(reply["err_len"]))
        return int(reply["exit"]), out, err
    finally:
        sock.close()


_SHIM_TEMPLATE = '''#!/usr/bin/env python3
"""Oracle shim generated by Aegis-Bench.

This is not the probe. It forwards stdin to the harness-owned broker, which
counts the query against the task's budget and runs the real binary on the
harness side. Do not edit: it is regenerated per run.
"""

import json
import socket
import sys

SOCKET_PATH = __SOCKET_PATH__
TCP_ADDRESS = __TCP_ADDRESS__
PROTOCOL = __PROTOCOL__
MAX_QUERY_BYTES = __MAX_QUERY_BYTES__


def _connect():
    if SOCKET_PATH is not None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(SOCKET_PATH)
        return sock
    host, _, port = TCP_ADDRESS.rpartition(":")
    return socket.create_connection((host, int(port)), timeout=60)


def _recv_exact(sock, count):
    chunks = []
    while count > 0:
        chunk = sock.recv(min(count, 65536))
        if not chunk:
            raise SystemExit("oracle: broker closed the connection")
        chunks.append(chunk)
        count -= len(chunk)
    return b"".join(chunks)


def main():
    payload = sys.stdin.buffer.read()
    if len(payload) > MAX_QUERY_BYTES:
        sys.stderr.write("oracle: input exceeds the query size limit\\n")
        return 2
    sock = _connect()
    try:
        header = json.dumps({"op": "query", "protocol": PROTOCOL,
                             "len": len(payload)}).encode() + b"\\n"
        sock.sendall(header)
        sock.sendall(payload)
        raw = b""
        while not raw.endswith(b"\\n"):
            chunk = sock.recv(1)
            if not chunk:
                sys.stderr.write("oracle: broker closed the connection\\n")
                return 125
            raw += chunk
        reply = json.loads(raw)
        if not reply.get("ok"):
            sys.stderr.write("oracle: " + str(reply.get("error")) + "\\n")
            return 125
        out = _recv_exact(sock, reply["out_len"])
        err = _recv_exact(sock, reply["err_len"])
    finally:
        sock.close()
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(err)
    sys.stderr.buffer.flush()
    return reply["exit"]


if __name__ == "__main__":
    sys.exit(main())
'''


def shim_source(broker: OracleBroker) -> str:
    """Render the workspace shim for ``broker``."""
    unix_path = repr(broker.address) if broker.transport == "unix" else "None"
    tcp_address = repr(broker.address) if broker.transport != "unix" else "None"
    return (_SHIM_TEMPLATE
            .replace("__SOCKET_PATH__", unix_path)
            .replace("__TCP_ADDRESS__", tcp_address)
            .replace("__PROTOCOL__", str(PROTOCOL))
            .replace("__MAX_QUERY_BYTES__", str(MAX_QUERY_BYTES)))


def install_shim(broker: OracleBroker, workspace: Path,
                 name: str = "probe") -> Path:
    """Write the shim into the agent workspace.

    On Windows the shim is a Python file with a ``.cmd`` launcher beside it,
    because nothing executes a shebang there. Windows runs are incidental;
    reported numbers come from Linux, where ``probe`` is directly executable.
    """
    workspace = Path(workspace)
    shim = workspace / name
    shim.write_text(shim_source(broker), encoding="utf-8", newline="\n")
    os.chmod(shim, 0o755)
    if os.name == "nt":
        launcher = workspace / f"{name}.cmd"
        launcher.write_text(
            '@echo off\r\npython "%~dp0' + name + '" %*\r\n',
            encoding="utf-8", newline="")
    return shim
