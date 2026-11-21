"""Harness-owned tool broker.

The broker is the single mediated path for workspace operations when an
adapter opts in. It validates workspace-relative paths, enforces the task's
declared tool policy and call budget, executes probe/disassembly requests, and
records authoritative counters in the run row.

This is a process-local loopback service, not a sandbox. An in-process adapter
can still perform tools directly or open the workspace itself. The broker
makes mediated calls measurable now and becomes enforceable when the adapter
worker is mounted without direct access to repositories or artifact caches.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .httpunix import ThreadingUnixHTTPServer
from .oracle import OracleError, probe_environment
from .policy import check_candidate
from .process import OutputLimitExceeded, ProcessCancelled, run_bounded
from .schema import Task, ToolPolicy

BROKER_ENV_URL = "AEGIS_TOOL_BROKER_URL"
BROKER_ENV_TOKEN = "AEGIS_TOOL_BROKER_TOKEN"
PROTOCOL = 1
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024
MAX_TOOL_CHARS = 64 * 1024
MAX_PROBE_INPUT = 1024 * 1024
MAX_PROBE_OUTPUT = 1024 * 1024
PROBE_TIMEOUT = 60
DISASSEMBLY_TIMEOUT = 120
MAX_DISASSEMBLY_BYTES = 16 * 1024 * 1024
REQUEST_READ_TIMEOUT = 5


class ToolError(Exception):
    """A tool request failed in a way the adapter can recover from."""


class ToolDenied(ToolError):
    """A tool request violated policy, budget or workspace containment."""


class ToolStats:
    def __init__(self, *, max_calls: int | None) -> None:
        self.lock = threading.Lock()
        self.requests = 0
        self.allowed = 0
        self.denied = 0
        self.failed = 0
        self.calls_by_tool: Counter[str] = Counter()
        self.denials: list[dict[str, str]] = []
        self.bytes_in = 0
        self.bytes_out = 0
        self.max_calls = max_calls

    def note_attempt(self, tool: str, bytes_in: int) -> None:
        with self.lock:
            self.requests += 1
            self.calls_by_tool[tool] += 1
            self.bytes_in += bytes_in

    def note_allowed(self) -> None:
        with self.lock:
            self.allowed += 1

    def note_denied(self, tool: str, reason: str) -> None:
        with self.lock:
            self.denied += 1
            if len(self.denials) < 20:
                self.denials.append({"tool": tool, "reason": reason})

    def note_failed(self) -> None:
        with self.lock:
            self.failed += 1

    def note_output(self, size: int) -> None:
        with self.lock:
            self.bytes_out += size

    def to_dict(self, *, reported_by_adapter: int | float | None = None
                ) -> dict[str, Any]:
        with self.lock:
            out: dict[str, Any] = {
                "protocol": PROTOCOL,
                "requests": self.requests,
                "allowed": self.allowed,
                "denied": self.denied,
                "failed": self.failed,
                "calls_by_tool": dict(sorted(self.calls_by_tool.items())),
                "denials": list(self.denials),
                "bytes_in": self.bytes_in,
                "bytes_out": self.bytes_out,
                "max_tool_calls": self.max_calls,
                "source": ("harness tool broker" if self.requests
                           else "no broker traffic"),
                "enforcement": (
                    "measured and capped by harness broker"
                    if self.max_calls is not None
                    else "measured by harness broker (no cap)"),
            }
            if isinstance(reported_by_adapter, (int, float)):
                out["reported_by_adapter"] = reported_by_adapter
                out["adapter_exceeds_broker"] = bool(
                    reported_by_adapter > self.requests)
            return out


class ToolBroker:
    """Loopback JSON broker for one run's workspace tools."""

    def __init__(self, *, workspace: Path, task: Task, access: str,
                 max_calls: int | None = None,
                 enable_disassembly: bool = False,
                 trusted_probe: Path | None = None,
                 probe_command: list[str] | None = None,
                 oracle_query: Callable[[bytes], tuple[int, bytes, bytes]]
                 | None = None,
                 oracle_cancel: Callable[[], None] | None = None) -> None:
        self.workspace = Path(workspace)
        self.root = self.workspace.resolve()
        self.task = task
        self.access = access
        self.enable_disassembly = enable_disassembly
        # These are control-plane inputs. Never infer an executable or a
        # disassembly target from the adapter's writable workspace.
        self._trusted_probe = (
            Path(trusted_probe).resolve() if trusted_probe is not None
            else None)
        if self._trusted_probe is not None and (
                self._trusted_probe == self.root
                or self.root in self._trusted_probe.parents):
            raise ValueError("trusted probe must be outside the workspace")
        if probe_command is not None and self._trusted_probe is None:
            raise ValueError("probe command requires a trusted artifact")
        self._command = list(probe_command) if probe_command else None
        self._oracle_query = oracle_query
        self._oracle_cancel = oracle_cancel
        self.token = secrets.token_urlsafe(32)
        self.stats = ToolStats(max_calls=max_calls)
        self.policy: ToolPolicy = task.tool_policy
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._disassembly: str | None = None
        self._unix_path: str | None = None
        self._stop = threading.Event()
        self._connection_lock = threading.Lock()
        self._connections: set[socket.socket] = set()

    # -- lifecycle -------------------------------------------------------

    def start(self, *, unix_path: str | Path | None = None) -> "ToolBroker":
        broker = self

        class DrainableServer:
            # server_close joins these threads after cancel() has interrupted
            # socket reads and child processes. Do not delete run artifacts
            # or publish final counters while a handler is still using them.
            daemon_threads = False
            block_on_close = True

            def process_request(self, request, client_address):
                with broker._connection_lock:
                    if broker._stop.is_set():
                        self.shutdown_request(request)
                        return
                    request.settimeout(REQUEST_READ_TIMEOUT)
                    broker._connections.add(request)
                try:
                    super().process_request(request, client_address)
                except BaseException:
                    with broker._connection_lock:
                        broker._connections.discard(request)
                    raise

            def process_request_thread(self, request, client_address):
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    with broker._connection_lock:
                        broker._connections.discard(request)

            def handle_error(self, request, client_address):
                if not broker._stop.is_set():
                    super().handle_error(request, client_address)

        class TCPServer(DrainableServer, ThreadingHTTPServer):
            pass

        class UnixServer(DrainableServer, ThreadingUnixHTTPServer):
            pass

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            server_version = "AegisToolBroker/1"

            def log_message(self, *args: Any) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    self._reply(400, {"ok": False, "error": "invalid length"})
                    return
                if length < 0 or length > MAX_REQUEST_BYTES:
                    self._reply(413, {"ok": False, "error": "request too large"})
                    return
                body = self.rfile.read(length) if length else b""
                if broker._stop.is_set():
                    return
                try:
                    request = json.loads(body)
                except ValueError:
                    self._reply(400, {"ok": False, "error": "invalid JSON"})
                    return
                if self.path != "/call":
                    self._reply(404, {"ok": False, "error": "not found"})
                    return
                if self.headers.get("X-Aegis-Token") != broker.token:
                    self._reply(403, {"ok": False, "error": "bad broker token"})
                    return
                if not isinstance(request, dict):
                    self._reply(400, {"ok": False, "error": "invalid request"})
                    return
                if request.get("protocol") != PROTOCOL:
                    self._reply(
                        400, {"ok": False, "error": "unsupported protocol"})
                    return
                tool = str(request.get("tool", ""))
                args = request.get("args")
                if not isinstance(args, dict):
                    args = {}
                try:
                    result = broker.dispatch(tool, args, bytes_in=len(body))
                    response = {"ok": True, "result": result}
                except ToolDenied as exc:
                    response = {"ok": False, "denied": True, "error": str(exc)}
                except ToolError as exc:
                    response = {"ok": False, "error": str(exc)}
                self._reply(200, response)

            def _reply(self, status: int, response: dict[str, Any]) -> None:
                if broker._stop.is_set():
                    return
                payload = json.dumps(
                    response, sort_keys=True).encode("utf-8")
                broker.stats.note_output(len(payload))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        if unix_path is None:
            self._httpd = TCPServer(("127.0.0.1", 0), Handler)
        else:
            self._unix_path = str(Path(unix_path))
            self._httpd = UnixServer(self._unix_path, Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="aegis-tool-broker", daemon=True)
        self._thread.start()
        return self

    @property
    def url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("tool broker is not started")
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("tool broker is not started")
        return int(self._httpd.server_address[1])

    @property
    def unix_path(self) -> str | None:
        return self._unix_path

    def stop(self, *, reported_by_adapter: int | float | None = None
             ) -> dict[str, Any]:
        self.cancel()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._unix_path = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        return self.stats.to_dict(reported_by_adapter=reported_by_adapter)

    def cancel(self) -> None:
        """Interrupt active tools and incomplete requests before draining."""
        self._stop.set()
        if self._oracle_cancel is not None:
            self._oracle_cancel()
        with self._connection_lock:
            for connection in self._connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    # -- dispatch --------------------------------------------------------

    def _allowed(self, tool: str) -> bool:
        allowed = set(self.policy.allowed_tools)
        return not allowed or tool in allowed

    def _deny(self, tool: str, reason: str) -> None:
        self.stats.note_denied(tool, reason)
        raise ToolDenied(reason)

    def dispatch(self, tool: str, args: dict[str, Any], *,
                 bytes_in: int = 0) -> str:
        if self._stop.is_set():
            raise ToolError("tool broker is stopping")
        self.stats.note_attempt(tool, bytes_in)
        if not self._allowed(tool):
            self._deny(tool, f"tool {tool!r} is not allowed by task policy")
        if (self.stats.max_calls is not None
                and self.stats.requests > self.stats.max_calls):
            self._deny(
                tool,
                f"tool-call budget exhausted ({self.stats.max_calls} calls)")
        self.stats.note_allowed()
        try:
            if tool == "list_files":
                return self._list_files()
            if tool == "read_file":
                return self._read_file(str(args.get("path", "")))
            if tool == "run_probe":
                return self._run_probe(args)
            if tool == "disassemble":
                return self._disassemble(args)
            if tool == "submit_solution":
                return self._submit_solution(str(args.get("source", "")))
            self.stats.note_failed()
            raise ToolError(f"unknown tool {tool!r}")
        except ToolDenied:
            raise
        except ToolError:
            self.stats.note_failed()
            raise
        except BaseException as exc:
            self.stats.note_failed()
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    def _resolve(self, relative: str) -> Path:
        if not relative or "\0" in relative:
            self._deny("read_file", "empty or invalid path")
        raw = Path(relative)
        if raw.is_absolute():
            self._deny("read_file", f"path escapes the workspace: {relative}")
        candidate = (self.workspace / raw).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            self._deny("read_file", f"path escapes the workspace: {relative}")
        return candidate

    def _list_files(self) -> str:
        files: list[str] = []
        for path in self.workspace.rglob("*"):
            if self._stop.is_set():
                raise ToolError("tool broker is stopping")
            if path.is_symlink():
                continue
            if path.is_file():
                files.append(path.relative_to(self.workspace).as_posix())
        return "\n".join(sorted(files)) or "(empty)"

    def _read_file(self, relative: str) -> str:
        target = self._resolve(relative)
        if not target.is_file():
            raise ToolError(f"no such file: {relative}")
        with target.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ToolError(
                f"{relative} exceeds the {MAX_FILE_BYTES} byte limit")
        if b"\0" in data[:4096]:
            raise ToolError(f"{relative} looks binary ({len(data)} bytes)")
        text = data.decode("utf-8", errors="replace")
        if len(text) > MAX_TOOL_CHARS:
            return text[:MAX_TOOL_CHARS] + "\n... (truncated)"
        return text

    def _probe(self) -> Path:
        probe = self._trusted_probe
        if probe is None or not probe.is_file():
            raise ToolError("no trusted probe is configured for this task")
        return probe

    def _run_probe(self, args: dict[str, Any]) -> str:
        if args.get("input_hex"):
            try:
                payload = bytes.fromhex(str(args["input_hex"]))
            except ValueError as exc:
                raise ToolError(f"bad hex: {exc}") from exc
        else:
            payload = str(args.get("input", "")).encode("utf-8")
        if len(payload) > MAX_PROBE_INPUT:
            raise ToolError(
                f"probe input exceeds {MAX_PROBE_INPUT} bytes")
        try:
            if self.access == "oracle":
                if self._oracle_query is None:
                    raise ToolError("no harness oracle is configured for this task")
                code, stdout, stderr = self._oracle_query(payload)
            elif self.access == "binary":
                probe = self._probe()
                proc = run_bounded(
                    self._command or [str(probe)], input=payload,
                    timeout=PROBE_TIMEOUT,
                    max_stdout_bytes=MAX_PROBE_OUTPUT,
                    max_stderr_bytes=MAX_PROBE_OUTPUT,
                    cwd=probe.parent, env=probe_environment(),
                    cancel_event=self._stop)
                code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
            else:
                raise ToolError("probe is not present in this task")
        except (OSError, subprocess.TimeoutExpired, OutputLimitExceeded,
                ProcessCancelled, OracleError) as exc:
            raise ToolError(f"probe failed: {exc}") from exc
        out = stdout.decode(
            "utf-8", errors="replace")[:MAX_TOOL_CHARS]
        err = stderr.decode(
            "utf-8", errors="replace")[:MAX_TOOL_CHARS]
        return f"exit={code}\nstdout:\n{out}\nstderr:\n{err}"

    def _full_disassembly(self) -> str:
        if not self.enable_disassembly or self.access != "binary":
            self._deny(
                "disassemble",
                "disassembly is available only with binary access")
        if self._disassembly is not None:
            return self._disassembly
        probe = self._probe()
        tool = next((found for name in (
            "llvm-objdump-23", "llvm-objdump", "objdump")
            if (found := shutil.which(name))), None)
        if tool is None:
            raise ToolError("no disassembler available")
        try:
            proc = run_bounded(
                [tool, "-d", "--no-show-raw-insn", str(probe)],
                timeout=DISASSEMBLY_TIMEOUT,
                max_stdout_bytes=MAX_DISASSEMBLY_BYTES,
                max_stderr_bytes=MAX_PROBE_OUTPUT,
                cwd=probe.parent, env=probe_environment(),
                cancel_event=self._stop)
        except (OSError, subprocess.TimeoutExpired, OutputLimitExceeded,
                ProcessCancelled) as exc:
            raise ToolError(f"disassembly failed: {exc}") from exc
        text = (proc.stdout or proc.stderr).decode(
            "utf-8", errors="replace")
        self._disassembly = text.replace(str(probe), "probe")
        return self._disassembly

    def _disassemble(self, args: dict[str, Any]) -> str:
        text = self._full_disassembly()
        try:
            length = int(args.get("length") or 8000)
        except (TypeError, ValueError):
            length = 8000
        length = max(500, min(length, MAX_TOOL_CHARS))
        symbol = str(args.get("symbol") or "").strip()
        if symbol:
            token = symbol.lstrip("*$@ ").strip()
            if re.fullmatch(r"(0x)?[0-9a-fA-F]+", token):
                addr = int(token, 16)
                addrs = [
                    (int(match.group(1), 16), match.start())
                    for match in re.finditer(r"^\s*([0-9a-f]+):", text, re.M)]
                start = next((pos for value, pos in addrs if value >= addr),
                             None)
                if start is None:
                    span = (f"0x{addrs[0][0]:x}-0x{addrs[-1][0]:x}"
                            if addrs else "no instructions")
                    raise ToolError(
                        f"no instruction at or after {symbol}; listing "
                        f"covers {span}")
                return f"[from address {symbol}]\n{text[start:start + length]}"
            if not re.fullmatch(r"[A-Za-z_.$][\w.$@]*", symbol):
                raise ToolError(f"bad symbol name: {symbol!r}")
            header = re.compile(
                rf"^[0-9a-f]+ <{re.escape(symbol)}>:$", re.M)
            match = header.search(text)
            if match is None:
                raise ToolError(f"symbol {symbol} not found")
            nxt = header.search(text, match.end())
            body = text[match.start():nxt.start() if nxt else len(text)]
            return body[:length]
        try:
            offset = max(0, int(args.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        chunk = text[offset:offset + length]
        if not chunk:
            raise ToolError(
                f"offset {offset} is past the end of the listing")
        return (f"[listing chars {offset}-{offset + len(chunk)} of "
                f"{len(text)}]\n{chunk}")

    def _submit_solution(self, source: str) -> str:
        if not source.strip():
            raise ToolError("empty source")
        name = self.task.candidate_sources[0]
        reason = check_candidate(
            {name: source}, [Path(self.task.interface).name])
        if reason:
            self._deny("submit_solution", reason)
        return "solution accepted"


def call_tool(name: str, args: dict[str, Any], *,
              url: str | None = None, token: str | None = None,
              timeout: float = PROBE_TIMEOUT) -> str:
    """Call the run's broker, raising ``ToolError`` on a rejected request."""
    base = url or os.environ.get(BROKER_ENV_URL)
    secret = token or os.environ.get(BROKER_ENV_TOKEN)
    if not base or not secret:
        raise ToolError("harness tool broker is not configured")
    payload = json.dumps({
        "protocol": PROTOCOL,
        "tool": name,
        "args": args,
    }).encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + "/call", data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Aegis-Token": secret,
        },
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read())
        except (ValueError, OSError):
            body = {}
        raise ToolError(str(body.get("error") or f"HTTP {exc.code}")) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ToolError(f"broker connection failed: {exc}") from exc
    try:
        reply = json.loads(raw)
    except ValueError as exc:
        raise ToolError("broker returned invalid JSON") from exc
    if not reply.get("ok"):
        error = str(reply.get("error") or "tool request failed")
        if reply.get("denied"):
            raise ToolDenied(error)
        raise ToolError(error)
    result = reply.get("result")
    if not isinstance(result, str):
        raise ToolError("broker returned a non-text tool result")
    return result
