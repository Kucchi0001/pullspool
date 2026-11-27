"""Seed the running backend with realistic demo data for screenshots.

Starts a local file server, completes a few downloads, acknowledges one,
expires another, then leaves one download active and one queued. Keeps the
file server alive until the process is terminated.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

import httpx

BASE = os.environ.get("PULLSPOOL_BASE", "http://127.0.0.1:8020")
DATA = Path(os.environ["PULLSPOOL_DATA"])
PASSWORD = os.environ.get("PULLSPOOL_PASSWORD", "Screenshot-Pass-2026")
MIOS = 1024 * 1024

FILES = {
    "pullspool-1.0.0-linux-amd64.tar.gz": 18 * MIOS,
    "ubuntu-24.04.1-live-server-amd64.iso": 42 * MIOS,
    "dataset-sample.csv": int(3.2 * MIOS),
    "photos-backup-2026-11.zip": 7 * MIOS,
    "release-notes-1.0.0.pdf": int(1.2 * MIOS),
    "app-logs-2026-11-25.tar.gz": 6 * MIOS,
    "backup-db-2026-11-26.sql.gz": 20 * MIOS,
    "archive-bundle.tar.zst": 16 * MIOS,
    "old-release-0.9.8.tar.gz": 30 * MIOS,
    "system-image-backup.img": 160 * MIOS,
    "dataset-archive-2026.tar.zst": 90 * MIOS,
}

CHUNK = 256 * 1024
ZERO = b"\0" * CHUNK


class FileHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        return

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(head=True)

    def do_GET(self) -> None:  # noqa: N802
        self._serve(head=False)

    def _serve(self, *, head: bool) -> None:
        path = unquote(urlsplit(self.path).path)
        name = path.rsplit("/", 1)[-1]
        size = FILES.get(name)
        if size is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        start, end, status = 0, size - 1, 200
        header = self.headers.get("Range", "")
        if header.lower().startswith("bytes="):
            spec = header[6:].split("-", 1)
            try:
                start = int(spec[0]) if spec[0] else 0
                end = int(spec[1]) if len(spec) > 1 and spec[1] else size - 1
            except ValueError:
                start, end = 0, size - 1
            start = max(0, min(start, size - 1))
            end = max(start, min(end, size - 1))
            status = 206

        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if head:
            return

        remaining = end - start + 1
        try:
            while remaining > 0:
                payload = ZERO[: min(CHUNK, remaining)]
                self.wfile.write(payload)
                remaining -= len(payload)
        except (BrokenPipeError, ConnectionAbortedError):
            return


def start_server() -> str:
    server = QuietServer(("127.0.0.1", 0), FileHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return f"http://127.0.0.1:{port}"


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        import sys

        exception = sys.exc_info()[1]
        if isinstance(
            exception, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)
        ):
            return
        super().handle_error(request, client_address)


def read_bootstrap(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("密码:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("bootstrap password not found")


def wait_task(client: httpx.Client, task_id: str, predicate, timeout: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.get(f"/api/tasks/{task_id}").json()["task"]
        if predicate(last):
            return last
        time.sleep(0.2)
    raise RuntimeError(f"task {task_id} did not reach expected state: {last}")


def create(client: httpx.Client, file_url: str, **extra) -> dict:
    response = client.post("/api/tasks", json={"url": file_url, **extra})
    response.raise_for_status()
    return response.json()["task"]


def main() -> None:
    files_base = start_server()
    print("file server:", files_base, flush=True)

    for _ in range(100):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.2)

    client = httpx.Client(base_url=BASE, timeout=60.0)
    password = read_bootstrap(DATA / "bootstrap-admin.txt")
    login = client.post("/api/auth/login", json={"username": "admin", "password": password})
    login.raise_for_status()
    changed = client.post(
        "/api/auth/password",
        json={"current_password": password, "new_password": PASSWORD},
    )
    changed.raise_for_status()
    client.put(
        "/api/settings",
        json={
            "max_concurrent_downloads": 1,
            "default_connections": 1,
            "default_speed_limit_kib_per_s": 15360,
            "theme": "system",
        },
    ).raise_for_status()

    completed: dict[str, str] = {}
    for name in (
        "pullspool-1.0.0-linux-amd64.tar.gz",
        "ubuntu-24.04.1-live-server-amd64.iso",
        "dataset-sample.csv",
        "photos-backup-2026-11.zip",
        "release-notes-1.0.0.pdf",
        "app-logs-2026-11-25.tar.gz",
    ):
        task = create(client, f"{files_base}/files/{name}")
        wait_task(client, task["id"], lambda item: item["status"] == "completed")
        completed[name] = task["id"]
        time.sleep(0.3)

    client.post(f"/api/tasks/{completed['pullspool-1.0.0-linux-amd64.tar.gz']}/ack", json={"confirm": True}).raise_for_status()

    database = DATA / "db" / "pullspool.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE tasks SET deleted_at = ?, deleted_reason = 'expired' WHERE id = ?",
            ("2026-11-26T09:00:00Z", completed["ubuntu-24.04.1-live-server-amd64.iso"]),
        )

        # Backfill two weeks of application-level traffic so the chart is meaningful.
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        for offset in range(1, 15):
            day = (today - timedelta(days=offset)).isoformat()
            down = (140 + (offset * 53) % 420) * MIOS
            up = (30 + (offset * 29) % 150) * MIOS
            connection.execute(
                "INSERT OR REPLACE INTO traffic_daily (day, direction, bytes) VALUES (?, 'down', ?)",
                (day, down),
            )
            connection.execute(
                "INSERT OR REPLACE INTO traffic_daily (day, direction, bytes) VALUES (?, 'up', ?)",
                (day, up),
            )
        connection.commit()
        user_id = connection.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        failed_id = str(uuid.uuid4())
        connection.execute(
            """
            INSERT INTO tasks (
                id, user_id, url, url_display, filename, status,
                file_size, downloaded_size, download_speed,
                error_code, error_message, attempts,
                download_bytes_counted, upload_bytes_counted, transfer_count,
                max_connections, speed_limit_bytes, created_at, started_at
            ) VALUES (?, ?, ?, ?, ?, 'failed', ?, ?, 0, ?, ?, 1, 0, 0, 0, 4, 0, ?, ?)
            """,
            (
                failed_id,
                user_id,
                f"{files_base}/files/legacy-installer.exe",
                f"{files_base}/files/legacy-installer.exe",
                "legacy-installer.exe",
                96 * MIOS,
                12 * MIOS,
                "TARGET_REJECTED",
                "目标地址返回 HTTP 403（链接可能已过期）",
                "2026-11-25T21:14:00Z",
                "2026-11-25T21:14:02Z",
            ),
        )
        connection.commit()

    canceled = create(
        client,
        f"{files_base}/files/old-release-0.9.8.tar.gz",
        speed_limit_kib_per_s=256,
    )
    wait_task(client, canceled["id"], lambda item: item["downloaded_size"] > 0)
    client.post(f"/api/tasks/{canceled['id']}/cancel", json={"delete_files": True}).raise_for_status()

    active = create(
        client,
        f"{files_base}/files/system-image-backup.img",
        speed_limit_kib_per_s=96,
    )
    wait_task(client, active["id"], lambda item: item["downloaded_size"] > 1 * MIOS, timeout=60)

    queued = create(
        client,
        f"{files_base}/files/dataset-archive-2026.tar.zst",
        speed_limit_kib_per_s=96,
    )
    print("active task:", active["id"], flush=True)
    print("queued task:", queued["id"], flush=True)
    print("SEED_READY", flush=True)

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
