"""Subprocess capture with limits enforced while reading, using only stdlib."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any


class OutputLimitExceeded(subprocess.SubprocessError):
    def __init__(self, stream: str, limit: int, stdout: bytes, stderr: bytes):
        super().__init__(f"{stream} output exceeds {limit} bytes")
        self.stream = stream
        self.limit = limit
        self.stdout = stdout
        self.stderr = stderr


class ProcessCancelled(subprocess.SubprocessError):
    """The owning service stopped while a command was running."""


def run_bounded(
        args: list[str], *, input: bytes = b"", timeout: float,
        max_stdout_bytes: int, max_stderr_bytes: int,
        cwd: Any = None, env: dict[str, str] | None = None,
        preexec_fn: Any = None,
        cancel_event: threading.Event | None = None
        ) -> subprocess.CompletedProcess[bytes]:
    """Capture complete output or raise; never return truncated success.

    Each pipe has a bounded reader. Input is spooled before starting the child
    so a child that writes before reading stdin cannot deadlock the caller.
    POSIX children get their own session, allowing timeouts/output limits to
    kill the process group, including descendants that still hold pipe ends.
    Windows kills the direct child; the project's supported runtime is Linux.
    A descendant that creates another session is outside this process group;
    containing it requires the caller's sandbox/container boundary. Pipe
    readers still stop at the deadline even when such a descendant holds a
    write end open.
    """
    if timeout <= 0 or max_stdout_bytes < 0 or max_stderr_bytes < 0:
        raise ValueError("timeout must be positive and output limits non-negative")
    deadline = time.monotonic() + timeout
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    overflow: list[tuple[str, int]] = []
    read_errors: list[OSError] = []
    lock = threading.Lock()
    stop_reading = threading.Event()
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCancelled("command cancelled before starting")

    with tempfile.TemporaryFile() as stdin:
        stdin.write(input)
        stdin.seek(0)
        proc = subprocess.Popen(
            args, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, cwd=cwd, env=env, preexec_fn=preexec_fn,
            start_new_session=os.name == "posix")

        def terminate() -> None:
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass

        def read_pipe(stream: str, pipe: Any, limit: int) -> None:
            selector = None
            try:
                if os.name == "posix":
                    os.set_blocking(pipe.fileno(), False)
                    selector = selectors.DefaultSelector()
                    selector.register(pipe, selectors.EVENT_READ)
                with pipe:
                    while not stop_reading.is_set():
                        if selector is not None and not selector.select(0.05):
                            continue
                        chunk = pipe.read(65536)
                        if chunk is None:
                            continue
                        if not chunk:
                            break
                        remaining = limit - len(buffers[stream])
                        buffers[stream].extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            with lock:
                                if not overflow:
                                    overflow.append((stream, limit))
                            terminate()
                            break
            except OSError as exc:
                with lock:
                    read_errors.append(exc)
                terminate()
            finally:
                if selector is not None:
                    selector.close()

        readers = [
            threading.Thread(target=read_pipe,
                             args=("stdout", proc.stdout, max_stdout_bytes),
                             name="aegis-capture-stdout",
                             daemon=True),
            threading.Thread(target=read_pipe,
                             args=("stderr", proc.stderr, max_stderr_bytes),
                             name="aegis-capture-stderr",
                             daemon=True),
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        was_cancelled = False
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    was_cancelled = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    proc.wait(timeout=(min(remaining, 0.05)
                                       if cancel_event is not None else remaining))
                    break
                except subprocess.TimeoutExpired:
                    if cancel_event is None:
                        timed_out = True
                        break
            for reader in readers:
                while reader.is_alive() and not (timed_out or was_cancelled):
                    if cancel_event is not None and cancel_event.is_set():
                        was_cancelled = True
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        break
                    reader.join(timeout=min(remaining, 0.05))
        finally:
            # Clean up the original process group and cancel pipe reads even
            # when an independently sessioned process still holds a pipe open.
            stop_reading.set()
            terminate()
            proc.wait()
            for reader in readers:
                reader.join(timeout=None if os.name == "posix" else 1)
        stdout, stderr = bytes(buffers["stdout"]), bytes(buffers["stderr"])
        if overflow:
            stream, limit = overflow[0]
            raise OutputLimitExceeded(stream, limit, stdout, stderr)
        if was_cancelled:
            raise ProcessCancelled("command cancelled by the owning service")
        if timed_out:
            raise subprocess.TimeoutExpired(args, timeout, stdout, stderr)
        if read_errors:
            raise read_errors[0]
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
