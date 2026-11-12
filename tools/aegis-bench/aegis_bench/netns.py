"""Linux network-namespace helpers for the adapter worker.

The worker runs in a private network namespace with only loopback. Trusted
broker and meter services stay in the host namespace and expose Unix sockets;
the worker bridges those sockets to loopback TCP ports for ordinary HTTP
clients. A connect to any host address has no route and fails.
"""

from __future__ import annotations

import errno
import os
import select
import shutil
import socket
import struct
import subprocess
import threading
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]

SIOCGIFFLAGS = 0x8913
SIOCSIFFLAGS = 0x8914
IFF_UP = 0x1
IFF_RUNNING = 0x40


class NetnsError(Exception):
    """The worker could not enter or configure its network namespace."""


class LoopbackBridge:
    """Expose one host Unix HTTP socket on loopback inside the namespace."""

    def __init__(self, unix_path: str | Path) -> None:
        self.unix_path = Path(unix_path)
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(32)
        self.port = int(self._listener.getsockname()[1])
        self._thread = threading.Thread(
            target=self._accept, name="aegis-netns-bridge", daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "LoopbackBridge":
        self._thread.start()
        return self

    def close(self) -> None:
        try:
            self._listener.close()
        except OSError:
            pass

    def _accept(self) -> None:
        while True:
            try:
                client, _address = self._listener.accept()
            except OSError:
                return
            threading.Thread(
                target=self._relay, args=(client,),
                name="aegis-netns-bridge-connection", daemon=True).start()

    def _relay(self, client: socket.socket) -> None:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            upstream.connect(str(self.unix_path))
            sockets = [client, upstream]
            while sockets:
                readable, _, errors = select.select(
                    sockets, [], sockets, 60.0)
                if errors:
                    break
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        sockets.remove(source)
                        target = upstream if source is client else client
                        try:
                            target.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass
                        continue
                    target = upstream if source is client else client
                    target.sendall(data)
        except OSError:
            pass
        finally:
            client.close()
            upstream.close()


def _probe(command: list[str]) -> bool:
    try:
        return subprocess.run(
            command, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def unshare_options() -> list[str]:
    """Return a working unshare mode, preferring an unprivileged user netns."""
    tool = shutil.which("unshare")
    if tool is None:
        raise NetnsError("util-linux 'unshare' is not installed")
    for options in (["-Urn"], ["-n"]):
        if _probe([tool, *options, "true"]):
            return [tool, *options]
    raise NetnsError(
        "this host cannot create a network namespace; run the worker with "
        "CAP_SYS_ADMIN/NET_ADMIN or enable unprivileged user namespaces")


def bring_up_loopback() -> None:
    """Set the per-namespace loopback interface administratively up."""
    if fcntl is None or not hasattr(fcntl, "ioctl"):
        raise NetnsError("loopback configuration needs Linux fcntl.ioctl")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        request = struct.pack("16sH", b"lo", 0)
        result = fcntl.ioctl(sock.fileno(), SIOCGIFFLAGS, request)
        flags = struct.unpack("16sH", result)[1]
        request = struct.pack(
            "16sH", b"lo", flags | IFF_UP | IFF_RUNNING)
        fcntl.ioctl(sock.fileno(), SIOCSIFFLAGS, request)
    except OSError as exc:
        raise NetnsError(
            f"cannot bring loopback up in the worker namespace: {exc}"
        ) from exc
    finally:
        sock.close()


def namespace_inode() -> int:
    """Return the current network-namespace inode for provenance/tests."""
    try:
        return os.stat("/proc/self/ns/net").st_ino
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return 0
        raise
