"""Harness-owned token metering.

Token cost is the benchmark's primary metric and, until a run goes through
here, it is whatever the adapter says it is. This module puts the harness in
the network path: a per-run loopback reverse proxy in front of the model
endpoint that

* forwards each request unchanged except for one addition -- for a streaming
  request it sets ``stream_options.include_usage``, so the provider reports
  token usage in the terminal chunk whether or not the adapter asked for it;
* parses the response it is already copying for that usage;
* counts requests, statuses and bytes itself.

What the proxy records is the *provider's* attestation of usage, not a
recomputation. Estimating tokens from characters and calling it measured
would be worse than the self-report this replaces: it would look like
evidence while being a guess.

Three limits worth stating next to any number that comes from here:

1. **It is not a sandbox.** An adapter that reaches the upstream directly
   bypasses the meter. Such a run has ``requests: 0`` and keeps the
   self-reported label; a run that both uses and bypasses the proxy is
   undercounted and nothing here can detect it.
2. **A provider may ignore ``include_usage``.** Then the request is counted
   but carries no usage, and ``requests_without_usage`` says how many. The
   block is still useful (it bounds the request count from below) but its
   token totals no longer describe the whole run.
3. **Metered and self-reported totals are two independent measurements of
   the same thing, so they are kept apart and compared.** Agreement is a
   cross-check; the adapter reporting more than the proxy saw means traffic
   left the proxy, which is the one direction that is detectable.
4. **The meter does not keep a call alive that the agent abandoned.** When
   the client disconnects mid-stream (a reasoning watchdog firing, a step the
   adapter gave up on), the proxy closes the upstream connection too, exactly
   as the client would have. Draining the rest of the stream instead would
   make the provider generate tokens nobody reads and then charge them to the
   run: an earlier version did that and inflated completion by ~18% on one
   arm, in a direction that depended on how often that arm aborted. Such
   requests are counted in ``client_disconnects`` and carry no usage, so the
   metered total is a floor, never an overstatement.

The handler speaks HTTP/1.0 and closes the connection at end of body. That
makes a streamed response close-delimited, which is what every SSE client
already handles, and avoids re-chunking (and mis-chunking) the upstream body
on the way through. ``Content-Length`` is passed through when the upstream
sent one.
"""

from __future__ import annotations

import json
import http.client
import threading
import urllib.error
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

#: Request headers that must not be forwarded: they describe the client's
#: connection to *this* proxy or the encoding it asked for. Dropping
#: ``Accept-Encoding`` keeps the upstream body readable, which is the whole
#: point of standing in the middle.
_DROP_REQUEST = {
    "host", "content-length", "connection", "accept-encoding",
    "transfer-encoding", "keep-alive", "proxy-connection", "te",
}

#: Response headers that must not be forwarded verbatim.
_DROP_RESPONSE = {"transfer-encoding", "connection", "keep-alive",
                  "proxy-connection", "content-encoding"}

#: How many bytes of the request body to keep for the fallback byte count.
_MAX_BODY = 64 * 1024 * 1024


class _Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests = 0
        self.statuses: Counter[int] = Counter()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.usage_requests = 0
        self.requests_without_usage = 0
        self.client_disconnects = 0
        self.injected_usage = 0
        self.bytes_in = 0
        self.bytes_out = 0
        self.errors: list[str] = []

    def note_request(self, body: int) -> None:
        with self.lock:
            self.requests += 1
            self.bytes_in += body

    def note_usage(self, usage: dict[str, Any] | None) -> None:
        with self.lock:
            if not isinstance(usage, dict):
                self.requests_without_usage += 1
                return
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens")
            if not isinstance(prompt, int) or not isinstance(completion, int):
                self.requests_without_usage += 1
                return
            self.usage_requests += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion

    def note_status(self, status: int) -> None:
        with self.lock:
            self.statuses[status] += 1

    def note_disconnect(self) -> None:
        with self.lock:
            self.client_disconnects += 1

    def note_output(self, n: int) -> None:
        with self.lock:
            self.bytes_out += n

    def note_error(self, message: str) -> None:
        with self.lock:
            if len(self.errors) < 5:
                self.errors.append(message)

    def to_dict(self, *, upstream: str, injected: int,
                reported_by_adapter: int | float | None) -> dict[str, Any]:
        with self.lock:
            total = self.prompt_tokens + self.completion_tokens
            if self.usage_requests and not self.requests_without_usage:
                source = "provider usage via harness proxy (all requests)"
            elif self.usage_requests:
                source = (f"provider usage via harness proxy "
                          f"({self.usage_requests}/{self.requests} requests)")
            elif self.requests:
                source = "no usage reported by provider"
            else:
                source = "no traffic through the proxy"
            out: dict[str, Any] = {
                "kind": "proxy",
                "upstream": upstream,
                "requests": self.requests,
                "requests_with_usage": self.usage_requests,
                "requests_without_usage": self.requests_without_usage,
                "client_disconnects": self.client_disconnects,
                "include_usage_injected": injected,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": total if self.usage_requests else None,
                "usage_source": source,
                "status_counts": {str(k): v for k, v in
                                  sorted(self.statuses.items())},
                "bytes_in": self.bytes_in,
                "bytes_out": self.bytes_out,
                "errors": list(self.errors),
                "enforcement": "measured by harness proxy",
            }
            if isinstance(reported_by_adapter, (int, float)):
                # Two independent measurements of one quantity. The adapter
                # claiming *more* than the proxy saw is evidence that traffic
                # left the proxy; the reverse (adapter claims less) is not
                # meaningful, because aborted calls are legitimately
                # estimated by the adapter and never answered by the provider.
                out["reported_by_adapter"] = reported_by_adapter
                out["adapter_exceeds_metered"] = bool(
                    total and reported_by_adapter > total * 1.05)
            return out


def ledger_source_for(metering: dict[str, Any]) -> str:
    """How much of a row's token figure the harness can vouch for.

    Only ``requests_with_usage == requests`` earns the unqualified label. A
    run with no traffic through the proxy keeps the adapter's own word for it:
    the meter existing is not the same as the meter having seen anything.
    """
    requests = metering.get("requests") or 0
    if not requests:
        return "self-reported by adapter (no traffic through the meter)"
    with_usage = metering.get("requests_with_usage") or 0
    if with_usage == requests:
        return "metered by harness (provider usage, every request)"
    if not with_usage:
        return ("self-reported by adapter (provider reported no usage for "
                f"{requests} request(s))")
    return (f"partly metered by harness ({with_usage}/{requests} requests "
            f"carried provider usage); remainder self-reported")


def _usage_from_sse_line(line: bytes) -> dict[str, Any] | None:
    """``data: {...}`` -> the usage object inside, if this chunk carries one."""
    if not line.startswith(b"data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == b"[DONE]":
        return None
    try:
        obj = json.loads(payload)
    except ValueError:
        return None
    usage = obj.get("usage") if isinstance(obj, dict) else None
    return usage if isinstance(usage, dict) else None


class MeterProxy:
    """A loopback reverse proxy that measures what passes through it.

    Usage::

        proxy = MeterProxy("https://relay.example/v1").start()
        # point the adapter at proxy.base_url
        ...
        block = proxy.stop()

    One proxy per run: attribution is by port, so two cells cannot be
    confused for each other, and a run that starts no requests is visibly a
    run the meter did not see.
    """

    def __init__(self, upstream: str, *, timeout: float = 300.0) -> None:
        parts = urlsplit(upstream)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"upstream must be an http(s) base URL, "
                             f"got {upstream!r}")
        self.upstream_url = upstream.rstrip("/")
        self.upstream_origin = f"{parts.scheme}://{parts.netloc}"
        self.upstream_prefix = parts.path.rstrip("/")
        self._timeout = timeout
        self.stats = _Stats()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- lifecycle -------------------------------------------------------

    def start(self) -> "MeterProxy":
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            server_version = "AegisBenchMeter/1"

            def log_message(self, *args: Any) -> None:  # noqa: D102
                return  # the adapter's console output is the run log

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                proxy._handle(self, b"")

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(min(length, _MAX_BODY)) if length else b""
                proxy._handle(self, body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="aegis-meter", daemon=True)
        self._thread.start()
        return self

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("meter proxy is not started")
        return self._httpd.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.upstream_prefix}"

    def stop(self, *, reported_by_adapter: int | float | None = None
             ) -> dict[str, Any]:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        return self.stats.to_dict(upstream=self.upstream_url,
                                  injected=self.stats.injected_usage,
                                  reported_by_adapter=reported_by_adapter)

    # -- forwarding ------------------------------------------------------

    def _handle(self, handler: BaseHTTPRequestHandler, body: bytes) -> None:
        self.stats.note_request(len(body))
        out_body, injected = _prepare_request(body)
        if injected:
            self.stats.injected_usage += 1
        url = self.upstream_origin + handler.path
        headers = {k: v for k, v in handler.headers.items()
                   if k.lower() not in _DROP_REQUEST}
        request = urllib.request.Request(url, data=out_body or None,
                                         headers=headers,
                                         method=handler.command)
        try:
            response = urllib.request.urlopen(request,
                                              timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            # The upstream's status is part of the measurement -- an adapter
            # retries on 429/503/52x, and swallowing it into a 502 would
            # change the agent's behaviour and so the cost being measured.
            self.stats.note_status(exc.code)
            self._relay(handler, exc, streamed=False)
            return
        except (urllib.error.URLError, OSError) as exc:
            self.stats.note_error(f"{type(exc).__name__}: {exc}")
            payload = json.dumps({"error": {"message":
                                            f"aegis meter: upstream failed: {exc}"}}
                                 ).encode()
            try:
                handler.send_response(502)
                handler.send_header("Content-Type", "application/json")
                handler.send_header("Content-Length", str(len(payload)))
                handler.end_headers()
                handler.wfile.write(payload)
            except OSError:
                pass
            return

        with response:
            self.stats.note_status(getattr(response, "status", 200))
            self._relay(handler, response, streamed=True)

    def _relay(self, handler: BaseHTTPRequestHandler, response: Any, *,
               streamed: bool) -> None:
        """Copy the upstream response through, parsing usage on the way."""
        try:
            status = getattr(response, "code", None) or getattr(
                response, "status", 200)
            content_type = response.headers.get("Content-Type", "")
            is_sse = "text/event-stream" in (content_type or "")
            try:
                handler.send_response(status)
                for key, value in response.headers.items():
                    if key.lower() in _DROP_RESPONSE:
                        continue
                    handler.send_header(key, value)
                handler.end_headers()
            except OSError:
                return

            buffer = bytearray()
            pending = bytearray()
            found_usage = False
            abandoned = False
            while True:
                chunk = _read_some(response)
                if not chunk:
                    break
                try:
                    handler.wfile.write(chunk)
                    handler.wfile.flush()
                except OSError:
                    # The adapter hung up -- its own reasoning watchdog fired,
                    # or it gave up on a slow step. **Stop reading and close
                    # the upstream connection**, which is what the adapter
                    # would have done itself: continuing to drain the stream
                    # makes the provider generate tokens nobody will read and
                    # then bills them to the run. A meter that changes the
                    # cost it measures is not a meter (this is what an earlier
                    # version did, inflating completion by ~18% on one arm).
                    abandoned = True
                    self.stats.note_disconnect()
                    break
                self.stats.note_output(len(chunk))
                if is_sse:
                    pending += chunk
                    *lines, rest = bytes(pending).split(b"\n")
                    pending = bytearray(rest)
                    for line in lines:
                        usage = _usage_from_sse_line(line)
                        # Some relays repeat the terminal usage block. One
                        # request has one bill; count the first block and
                        # ignore duplicates rather than doubling the run.
                        if usage is not None and not found_usage:
                            self.stats.note_usage(usage)
                            found_usage = True
                else:
                    if len(buffer) < _MAX_BODY:
                        buffer += chunk
            if is_sse:
                # A final chunk with no trailing newline still counts, and a
                # stream that never reported usage is counted as such rather
                # than dropped: every request must be accounted exactly once.
                if not found_usage:
                    usage = _usage_from_sse_line(bytes(pending))
                    if usage is not None:
                        self.stats.note_usage(usage)
                    else:
                        self.stats.note_usage(None)
            else:
                try:
                    payload = json.loads(bytes(buffer))
                except ValueError:
                    payload = None
                usage = payload.get("usage") if isinstance(payload, dict) else None
                self.stats.note_usage(usage)
        except (urllib.error.URLError, OSError) as exc:
            self.stats.note_error(f"{type(exc).__name__}: {exc}")


def _read_some(response: Any) -> bytes:
    """One incremental read, so SSE chunks reach the client as they arrive."""
    for name in ("read1", "read"):
        reader = getattr(response, name, None)
        if reader is None:
            continue
        try:
            data = reader(65536)
        except http.client.IncompleteRead as exc:
            # A relay can close a chunked SSE stream between chunks. Preserve
            # any partial bytes for the client, then treat the next read as
            # EOF rather than letting a meter thread traceback escape.
            return exc.partial
        except TypeError:  # a reader that takes no size
            data = reader()
        if data:
            return data
        if name == "read":
            return b""
    return b""


def _prepare_request(body: bytes) -> tuple[bytes, bool]:
    """Ask the provider for usage, and return whether we had to.

    Only the streaming case is touched: ``include_usage`` is what makes a
    provider emit a usage block on the terminal SSE chunk. A non-streaming
    response carries usage already. Nothing else in the request is altered --
    not the model, not the sampling parameters, not the tools -- because any
    of those would change the cost being measured.
    """
    if not body:
        return body, False
    try:
        obj = json.loads(body)
    except ValueError:
        return body, False
    if not isinstance(obj, dict) or not obj.get("stream"):
        return body, False
    options = obj.get("stream_options")
    if not isinstance(options, dict):
        options = {}
    if options.get("include_usage") is True:
        return body, False
    options["include_usage"] = True
    obj["stream_options"] = options
    return json.dumps(obj, separators=(",", ":")).encode(), True
