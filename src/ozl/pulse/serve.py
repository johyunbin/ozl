"""Pulse 읽기 전용 서버 — 표준 라이브러리만 쓴다. 127.0.0.1 에만 열고, 밖(tailnet)으로는 `tailscale serve` 가 잇는다.

    python -m ozl.pulse serve [--port 8765]

    GET /                  대시보드(web/index.html)
    GET /api/now           private/pulse/out/now.json 그대로
    GET /api/topic/<id>    주제 하나의 지난 24시간 추이(실행마다 순위·점수·매체 수) + now.json 의 그 주제
    GET /api/health        마지막 실행 시각·성공 여부 — 앱이 "갱신 멈춤"을 표시하는 데 쓴다

DB 는 읽기 전용 모드로 연다. 쓰는 일은 매시 실행(snapshot)만 한다.
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import snapshot, store

WEB = pathlib.Path(__file__).resolve().parent / "web"
STALE_MIN = 90   # 마지막 성공 실행이 이보다 오래되면 health.stale
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "macmini"}


def host_ok(host: str | None) -> bool:
    """DNS rebinding 막기 — 이 기기 주소와 tailnet 이름(*.ts.net)으로 들어온 요청만 받는다."""
    if not host:
        return False
    name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    name = name.lower().rstrip(".")
    return name in LOCAL_HOSTS or name.endswith(".ts.net")


def ro_connect(db: pathlib.Path) -> sqlite3.Connection | None:
    if not db.exists():
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def read_now(out_dir: pathlib.Path) -> dict | None:
    p = out_dir / "now.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def topic_payload(topic_id: int, db: pathlib.Path, out_dir: pathlib.Path, now: datetime) -> dict | None:
    con = ro_connect(db)
    if con is None:
        return None
    try:
        row = con.execute("SELECT topic_id, lang, title, first_seen, last_seen FROM topics WHERE topic_id=?", (topic_id,)).fetchone()
        if row is None:
            return None
        hist = store.history(con, topic_id, now)
    finally:
        con.close()
    cur = next((t for t in (read_now(out_dir) or {}).get("topics", []) if t["topic_id"] == topic_id), None)
    return {"topic": dict(row), "history": hist, "current": cur}


def health(db: pathlib.Path, out_dir: pathlib.Path, now: datetime) -> dict:
    last_ok = last_any = None
    db_error = None
    try:   # DB 를 못 읽어도 health 는 200 으로 "멈춤"을 알린다(화면이 상태를 보여 줄 수 있게)
        con = ro_connect(db)
        if con is not None:
            try:
                last_any = con.execute("SELECT at, error FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
                last_ok = con.execute("SELECT at FROM runs WHERE error IS NULL ORDER BY run_id DESC LIMIT 1").fetchone()
            finally:
                con.close()
    except sqlite3.Error as e:
        db_error = type(e).__name__
    ok_at = last_ok["at"] if last_ok else None
    stale = ok_at is None or datetime.fromisoformat(ok_at) < now - timedelta(minutes=STALE_MIN)
    return {"now": now.isoformat(), "last_ok": ok_at, "last_run": dict(last_any) if last_any else None,
            "stale": stale or db_error is not None, "db_error": db_error, "has_now_json": (out_dir / "now.json").exists()}


def make_handler(db: pathlib.Path, out_dir: pathlib.Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ozl-pulse"

        def log_message(self, fmt, *args):   # 요청 로그는 남기지 않는다(launchd 로그가 불어나지 않게)
            pass

        def send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def json(self, obj, code: int = 200) -> None:
            self.send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            now = datetime.now(timezone.utc)
            if not host_ok(self.headers.get("Host")):
                return self.json({"error": "허용하지 않은 Host"}, 403)
            try:
                if path in ("/", "/index.html"):
                    return self.send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
                if path == "/api/now":
                    d = read_now(out_dir)
                    return self.json(d) if d is not None else self.json({"error": "now.json 없음 — 아직 실행 전"}, 503)
                if path == "/api/health":
                    return self.json(health(db, out_dir, now))
                m = re.fullmatch(r"/api/topic/(\d{1,12})", path)
                if m:
                    d = topic_payload(int(m.group(1)), db, out_dir, now)
                    return self.json(d) if d is not None else self.json({"error": "없는 주제"}, 404)
                return self.json({"error": "없는 경로"}, 404)
            except ConnectionError:   # 받는 쪽이 끊었다 — 다시 쓸 곳이 없다
                return None
            except Exception as e:  # noqa: BLE001 — 내부 경로·값을 응답에 싣지 않는다
                try:
                    return self.json({"error": type(e).__name__}, int(HTTPStatus.INTERNAL_SERVER_ERROR))
                except ConnectionError:
                    return None

        def do_POST(self):
            self.json({"error": "읽기 전용"}, 405)

        do_PUT = do_DELETE = do_PATCH = do_POST

    return Handler


def serve(port: int = 8765, host: str = "127.0.0.1", db: pathlib.Path | None = None, out_dir: pathlib.Path | None = None) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(db or store.DB, out_dir or snapshot.OUT))
    httpd.daemon_threads = True
    return httpd
