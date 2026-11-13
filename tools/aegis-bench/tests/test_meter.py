"""Tests for harness-owned token metering.

No network and no model: the "upstream" here is a loopback server that speaks
the same wire format as a real relay, including the part that matters --
whether a provider reports ``usage``, and whether it reports it only when it
was asked.

Run with::

    python3 -m unittest discover -s tests -k Meter -v
"""

from __future__ import annotations

import json
import http.client
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.adapters.fake import ReplayAgent  # noqa: E402
from aegis_bench.meter import (  # noqa: E402
    MeterProxy, _prepare_request, _read_some, ledger_source_for)
from aegis_bench.report import _token_kind  # noqa: E402
from aegis_bench.runner import METER_ENV, Runner  # noqa: E402
from aegis_bench.schema import load_task  # noqa: E402

REPO_ROOT = TOOL_ROOT.parents[1]
BINARY_DIR = REPO_ROOT / "benchmarks" / "tasks-public" / "rolling-token-v2"


def _ground_truth_source(task) -> dict[str, str]:
    return {"target.cpp": task.path(task.ground_truth).read_text(
        encoding="utf-8")}


class _Upstream:
    """A loopback relay stand-in with selectable behaviour."""

    def __init__(self, mode: str = "usage") -> None:
        self.mode = mode
        self.seen: list[dict] = []
        self.aborted = False
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                upstream.seen.append(json.loads(body))
                if upstream.mode == "error":
                    payload = b'{"error":{"message":"capacity_full"}}'
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if upstream.mode == "json":
                    payload = json.dumps({
                        "choices": [{"message": {"content": "hi"}}],
                        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                # SSE. A provider that honours include_usage puts the usage
                # block on the terminal chunk and nowhere else.
                wants_usage = bool(upstream.seen[-1].get(
                    "stream_options", {}).get("include_usage"))
                if upstream.mode == "slow":
                    # A long generation that reports usage only at the end --
                    # the shape of a call the adapter's watchdog abandons.
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    try:
                        for _ in range(200):
                            self.wfile.write(
                                b'data: {"choices":[{"delta":'
                                b'{"content":"x"}}]}\n\n')
                            self.wfile.flush()
                            time.sleep(0.01)
                        self.wfile.write(
                            b'data: {"choices":[],"usage":'
                            b'{"prompt_tokens":1,"completion_tokens":9999}}'
                            b"\n\n")
                    except OSError:
                        # The proxy closed the upstream call after the client
                        # hung up. That is the behaviour under test.
                        upstream.aborted = True
                    return
                chunks = [b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n']
                if upstream.mode == "usage" and wants_usage:
                    chunks.append(
                        b'data: {"choices":[],"usage":{"prompt_tokens":11,'
                        b'"completion_tokens":5}}\n\n')
                elif upstream.mode == "double_usage" and wants_usage:
                    chunks.append(
                        b'data: {"choices":[],"usage":{"prompt_tokens":11,'
                        b'"completion_tokens":5}}\n\n')
                    chunks.append(
                        b'data: {"choices":[],"usage":{"prompt_tokens":11,'
                        b'"completion_tokens":5}}\n\n')
                chunks.append(b"data: [DONE]\n\n")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(chunk)
                    self.wfile.flush()

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="fake-upstream", daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}/v1"

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def _post(url: str, *, stream: bool = True) -> bytes:
    body = json.dumps({"model": "test", "messages": [], "stream": stream}
                      ).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _post_unix(path: Path, request_path: str, *,
               stream: bool = True) -> bytes:
    body = json.dumps({"model": "test", "messages": [], "stream": stream}
                      ).encode()
    request = (
        f"POST {request_path} HTTP/1.0\r\n"
        f"Host: aegis-test\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode() + body
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(30)
        sock.connect(str(path))
        sock.sendall(request)
        response = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                return bytes(response)
            response += chunk
    finally:
        sock.close()


def _proxied(test: unittest.TestCase, mode: str, *,
             stream: bool = True) -> tuple[bytes, dict]:
    """Send one request through a fresh proxy in front of a fake upstream."""
    upstream = _Upstream(mode)
    test.addCleanup(upstream.stop)
    proxy = MeterProxy(upstream.url).start()
    try:
        body = _post(proxy.base_url + "/chat/completions", stream=stream)
    finally:
        stats = proxy.stop()
    return body, stats


class PrepareRequestTests(unittest.TestCase):
    def test_streaming_request_gains_include_usage(self):
        body = json.dumps({"stream": True, "model": "m"}).encode()
        out, injected = _prepare_request(body)
        self.assertTrue(injected)
        self.assertTrue(json.loads(out)["stream_options"]["include_usage"])

    def test_second_pass_is_idempotent(self):
        body = json.dumps({"stream": True}).encode()
        once, _ = _prepare_request(body)
        twice, injected = _prepare_request(once)
        self.assertFalse(injected)
        self.assertEqual(once, twice)

    def test_non_streaming_request_is_untouched(self):
        body = json.dumps({"stream": False, "temperature": 0.2}).encode()
        out, injected = _prepare_request(body)
        self.assertFalse(injected)
        self.assertEqual(out, body)

    def test_non_json_body_is_passed_through(self):
        self.assertEqual(_prepare_request(b"not json"), (b"not json", False))

    def test_torn_chunk_preserves_partial_bytes(self):
        class Torn:
            def read1(self, _size):
                raise http.client.IncompleteRead(b"partial", 100)

        self.assertEqual(_read_some(Torn()), b"partial")


class LedgerSourceTests(unittest.TestCase):
    def test_no_traffic_keeps_the_self_report_label(self):
        source = ledger_source_for({"requests": 0})
        self.assertIn("self-reported", source)
        self.assertIn("no traffic", source)

    def test_every_request_with_usage_is_fully_metered(self):
        self.assertIn("metered by harness",
                      ledger_source_for({"requests": 4,
                                         "requests_with_usage": 4}))

    def test_partial_usage_says_how_partial(self):
        source = ledger_source_for({"requests": 4, "requests_with_usage": 3})
        self.assertIn("3/4", source)

    def test_no_usage_at_all_is_not_called_partly_metered(self):
        source = ledger_source_for({"requests": 2, "requests_with_usage": 0})
        self.assertIn("self-reported", source)
        self.assertNotIn("partly", source)


class MeterProxyTests(unittest.TestCase):
    def test_unix_socket_listener_meters_the_same_protocol(self):
        if not hasattr(socket, "AF_UNIX"):
            self.skipTest("Unix sockets unavailable")
        upstream = _Upstream("usage")
        self.addCleanup(upstream.stop)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meter.sock"
            proxy = MeterProxy(upstream.url).start(unix_path=path)
            try:
                response = _post_unix(path, "/v1/chat/completions")
            finally:
                stats = proxy.stop()
        self.assertIn(b"data:", response)
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["total_tokens"], 16)

    def test_stream_is_forwarded_byte_for_byte(self):
        body, _ = _proxied(self, "usage")
        self.assertIn(b'data: {"choices":[{"delta":{"content":"hi"}}]}', body)
        self.assertIn(b"data: [DONE]", body)

    def test_harness_asks_for_usage_so_the_adapter_does_not_have_to(self):
        # The adapter's request never mentions stream_options; the proxy adds
        # it, and the fake provider answers with usage only because it did.
        # That is the point: measurement must not depend on the measured
        # party's cooperation.
        _, stats = _proxied(self, "usage")
        self.assertEqual(stats["include_usage_injected"], 1)
        self.assertEqual(stats["prompt_tokens"], 11)
        self.assertEqual(stats["completion_tokens"], 5)
        self.assertEqual(stats["total_tokens"], 16)
        self.assertEqual(stats["requests_with_usage"], 1)
        self.assertEqual(stats["requests_without_usage"], 0)

    def test_provider_ignoring_include_usage_is_reported_not_hidden(self):
        _, stats = _proxied(self, "no_usage")
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["requests_with_usage"], 0)
        self.assertIsNone(stats["total_tokens"])
        self.assertIn("no usage", stats["usage_source"])

    def test_repeated_usage_block_is_counted_once(self):
        _, stats = _proxied(self, "double_usage")
        self.assertEqual(stats["requests_with_usage"], 1)
        self.assertEqual(stats["total_tokens"], 16)

    def test_non_streaming_usage_is_read_from_the_json_body(self):
        _, stats = _proxied(self, "json", stream=False)
        self.assertEqual(stats["total_tokens"], 10)
        self.assertEqual(stats["include_usage_injected"], 0)

    def test_upstream_error_status_is_forwarded_not_rewritten(self):
        upstream = _Upstream("error")
        self.addCleanup(upstream.stop)
        proxy = MeterProxy(upstream.url).start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                _post(proxy.base_url + "/chat/completions")
        finally:
            stats = proxy.stop()
        # A 503 must reach the adapter as a 503: its retry ladder is part of
        # the agent under measurement, and turning it into a 502 would change
        # what the run costs.
        self.assertEqual(caught.exception.code, 503)
        self.assertEqual(stats["status_counts"], {"503": 1})

    def test_adapter_claiming_more_than_the_proxy_saw_is_flagged(self):
        upstream = _Upstream("usage")
        self.addCleanup(upstream.stop)
        proxy = MeterProxy(upstream.url).start()
        try:
            _post(proxy.base_url + "/chat/completions")
        finally:
            stats = proxy.stop(reported_by_adapter=500)
        self.assertTrue(stats["adapter_exceeds_metered"])

    def test_adapter_claiming_less_is_not_flagged(self):
        # Aborted calls are legitimately estimated by the adapter and never
        # answered by the provider, so under-reporting is not evidence.
        upstream = _Upstream("usage")
        self.addCleanup(upstream.stop)
        proxy = MeterProxy(upstream.url).start()
        try:
            _post(proxy.base_url + "/chat/completions")
        finally:
            stats = proxy.stop(reported_by_adapter=4)
        self.assertFalse(stats["adapter_exceeds_metered"])

    def test_client_disconnect_stops_the_upstream_call(self):
        # The decisive property: an abandoned call must not be kept alive by
        # the meter. Draining it would make the provider generate tokens
        # nobody reads and charge them to the run -- inflating the protected
        # arm by however often its agent aborts, which is exactly the kind of
        # arm-dependent bias the ratio must not have.
        upstream = _Upstream("slow")
        self.addCleanup(upstream.stop)
        proxy = MeterProxy(upstream.url).start()
        body = json.dumps({"model": "test", "messages": [],
                           "stream": True}).encode()
        request = urllib.request.Request(
            proxy.base_url + "/chat/completions", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            response = urllib.request.urlopen(request, timeout=30)
            response.readline()          # a client that reads one event
            response.close()             # ...then gives up on the step
            deadline = time.time() + 10
            while not upstream.aborted and time.time() < deadline:
                time.sleep(0.05)
        finally:
            stats = proxy.stop()
        self.assertTrue(upstream.aborted,
                        "the proxy drained a call the client abandoned")
        self.assertEqual(stats["client_disconnects"], 1)
        self.assertEqual(stats["requests_without_usage"], 1)
        self.assertIsNone(stats["total_tokens"])

    def test_two_proxies_do_not_share_counters(self):
        upstream_a, upstream_b = _Upstream("usage"), _Upstream("usage")
        self.addCleanup(upstream_a.stop)
        self.addCleanup(upstream_b.stop)
        first = MeterProxy(upstream_a.url).start()
        second = MeterProxy(upstream_b.url).start()
        try:
            _post(first.base_url + "/chat/completions")
        finally:
            one, two = first.stop(), second.stop()
        self.assertEqual(one["requests"], 1)
        self.assertEqual(two["requests"], 0)
        self.assertIsNone(two["total_tokens"])


class _CallingAgent(ReplayAgent):
    """Replays the ground truth, but first makes one model call."""

    name = "replay-metered"

    def __init__(self, sources: dict[str, str], *, use_meter: bool) -> None:
        super().__init__(sources)
        self.use_meter = use_meter

    def solve(self, task, workspace):
        base = os.environ.get(METER_ENV)
        if self.use_meter and base:
            _post(base + "/chat/completions")
        return super().solve(task, workspace)


class MeterRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(BINARY_DIR)

    def _record(self, *, use_meter: bool):
        upstream = _Upstream("usage")
        self.addCleanup(upstream.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        agent = _CallingAgent(_ground_truth_source(self.task),
                              use_meter=use_meter)
        return Runner(repo_root=REPO_ROOT, out_dir=Path(tmp.name),
                      meter_upstream=upstream.url
                      ).run([self.task], [agent], profile="baseline")[0]

    def test_run_through_the_meter_is_labelled_metered(self):
        record = self._record(use_meter=True)
        self.assertEqual(record.metering["requests"], 1)
        self.assertEqual(record.metering["total_tokens"], 16)
        self.assertIn("metered by harness", record.ledger["ledger_source"])
        self.assertNotIn(METER_ENV, os.environ)

    def test_run_that_bypasses_the_meter_says_so(self):
        record = self._record(use_meter=False)
        self.assertEqual(record.metering["requests"], 0)
        self.assertIsNone(record.metering["total_tokens"])
        self.assertIn("no traffic", record.ledger["ledger_source"])

    def test_record_survives_a_round_trip_through_json(self):
        record = self._record(use_meter=True)
        row = json.loads(json.dumps(record.to_dict()))
        self.assertEqual(row["metering"]["total_tokens"], 16)
        self.assertEqual(row["budgets"]["enforcement"]["tokens"],
                         "measured by harness (provider usage via proxy)")

    def test_partial_provider_usage_is_called_a_floor(self):
        record = self._record(use_meter=True)
        record.metering["requests_with_usage"] = 0
        self.assertEqual(_token_kind([record]), "partly-metered")


if __name__ == "__main__":
    unittest.main()
