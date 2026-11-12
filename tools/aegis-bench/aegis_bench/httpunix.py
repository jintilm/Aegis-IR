"""HTTP servers over Unix domain sockets.

The network-isolated worker lives in a private network namespace with only a
loopback interface. Its broker and meter therefore cannot use the host TCP
listeners. The trusted side speaks the same HTTP protocol over a Unix socket,
and the worker exposes a loopback-only bridge to the adapter in its namespace.
"""

from __future__ import annotations

import os
import socketserver
from pathlib import Path
from typing import Any


class ThreadingUnixHTTPServer(
        socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Threaded Unix-stream server compatible with ``BaseHTTPRequestHandler``."""

    daemon_threads = True

    def __init__(self, socket_path: str | Path, handler: Any) -> None:
        self.socket_path = Path(socket_path)
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        super().__init__(str(self.socket_path), handler)
        # HTTPServer supplies these attributes normally; the base request
        # handler reads them while rendering protocol-level errors.
        self.server_name = "aegis-unix"
        self.server_port = 0
        os.chmod(self.socket_path, 0o600)

    def server_close(self) -> None:
        super().server_close()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
