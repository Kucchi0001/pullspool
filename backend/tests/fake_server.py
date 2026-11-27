"""A tiny threaded HTTP file server for download tests.

stdlib only, so the async test loop is untouched. Supports HEAD, Range,
throttled streaming and a toggle endpoint used to simulate a source that
becomes unavailable after the preflight succeeded.
"""

from __future__ import annotations

import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB
SLOW_CHUNK = 64 * 1024
SLOW_TOTAL = 40 * SLOW_CHUNK  # 2.5 MiB, ~2s with the delay
SLOW_DELAY = 0.05
LARGE_TOTAL = 64 * 1024 * 1024
LARGE_CHUNK = 256 * 1024


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PullSpoolTest/1.0"

    def log_message(self, *args) -> None:  # silence test output
        return

    def do_HEAD(self) -> None:
        self._respond(head=True)

    def do_GET(self) -> None:
        self._respond(head=False)

    # ------------------------------------------------------------------ #
    def _respond(self, *, head: bool) -> None:
        path = urlsplit(self.path).path
        server: TestFileServer = self.server  # type: ignore[assignment]

        if path == "/file.bin":
            self._send_bytes(PAYLOAD, head=head)
        elif path == "/slow.bin":
            self._send_slow(head=head)
        elif path == "/large.bin":
            self._send_large(head=head)
        elif path == "/toggle.bin":
            if server.toggle_ok.is_set():
                self._send_bytes(PAYLOAD, head=head)
            else:
                self._send_error(404)
        else:
            self._send_error(404)

    def _send_bytes(self, data: bytes, *, head: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", '"test-payload"')
        self.end_headers()
        if not head:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionAbortedError):
                return


    def _send_large(self, *, head: bool) -> None:
        total = LARGE_TOTAL
        start, end, status = 0, total - 1, 200
        range_header = self.headers.get("Range", "")
        if range_header.lower().startswith("bytes="):
            spec = range_header[6:].split("-", 1)
            try:
                start = int(spec[0]) if spec[0] else 0
                end = int(spec[1]) if len(spec) > 1 and spec[1] else total - 1
            except ValueError:
                start, end = 0, total - 1
            start = max(0, min(start, total - 1))
            end = max(start, min(end, total - 1))
            status = 206

        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", '"large-payload"')
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if head:
            return

        block = b"L" * LARGE_CHUNK
        remaining = end - start + 1
        try:
            while remaining > 0:
                payload = block[: min(LARGE_CHUNK, remaining)]
                self.wfile.write(payload)
                remaining -= len(payload)
        except (BrokenPipeError, ConnectionAbortedError):
            return
    def _send_slow(self, *, head: bool) -> None:
        total = SLOW_TOTAL
        start, end, status = 0, total - 1, 200
        range_header = self.headers.get("Range", "")
        if range_header.lower().startswith("bytes="):
            spec = range_header[6:].split("-", 1)
            try:
                start = int(spec[0]) if spec[0] else 0
                end = int(spec[1]) if len(spec) > 1 and spec[1] else total - 1
            except ValueError:
                start, end = 0, total - 1
            start = max(0, min(start, total - 1))
            end = max(start, min(end, total - 1))
            status = 206

        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if head:
            return

        position = start
        try:
            while position <= end:
                chunk = b"z" * min(SLOW_CHUNK, end - position + 1)
                self.wfile.write(chunk)
                self.wfile.flush()
                position += len(chunk)
                time.sleep(SLOW_DELAY)
        except (BrokenPipeError, ConnectionAbortedError):
            return

    def _send_error(self, status: int) -> None:
        body = b"not found"
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            return


class TestFileServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.toggle_ok = threading.Event()
        self.toggle_ok.set()

    def handle_error(self, request, client_address) -> None:
        exception = sys.exc_info()[1]
        if isinstance(exception, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


class ServerThread:
    def __init__(self) -> None:
        self.server = TestFileServer()
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> TestFileServer:
        self._thread.start()
        return self.server

    def __exit__(self, *exc_info: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)
