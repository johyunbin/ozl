"""Pulse 읽기 전용 서버 테스트 — 임시 DB·now.json 으로 서버를 띄워 경로별 응답을 본다. 제목은 지어낸 것이다."""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.pulse import serve, snapshot, store  # noqa: E402
from test_pulse import STORY, it  # noqa: E402


@pytest.fixture()
def server(tmp_path):
    db, out = tmp_path / "p.db", tmp_path / "out"
    now = datetime.now(timezone.utc)
    con = store.connect(db)
    items = [{**it(t, o), "published": (now - timedelta(minutes=m)).isoformat()} for t, o, m in zip(STORY, ["가상일보", "가상경제", "가상방송"], (40, 20, 10))]
    store.add_items(con, items, now)
    con.commit()
    r = snapshot.run(fetch=False, now=now, db=db, out_dir=out, youtube=[])
    assert r["ok"]
    httpd = serve.serve(0, db=db, out_dir=out)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", db, out
    httpd.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_index_and_now(server):
    base, _, _ = server
    code, h, body = get(base + "/")
    assert code == 200 and b"OZL Pulse" in body and "no-store" in h["Cache-Control"]
    code, _, body = get(base + "/api/now")
    d = json.loads(body)
    assert code == 200 and d["topics"] and d["topics"][0]["title"] in STORY


def test_topic_history_and_unknown(server):
    base, _, _ = server
    tid = json.loads(get(base + "/api/now")[2])["topics"][0]["topic_id"]
    code, _, body = get(f"{base}/api/topic/{tid}")
    d = json.loads(body)
    assert code == 200 and len(d["history"]) == 1 and d["current"]["topic_id"] == tid
    assert get(base + "/api/topic/999999")[0] == 404
    assert get(base + "/api/topic/abc")[0] == 404
    assert get(base + "/../private/pulse/pulse.db")[0] == 404   # 정적 파일 경로를 따라 밖으로 나가지 않는다


def test_health_fresh_then_stale(server, monkeypatch):
    base, _, _ = server
    assert json.loads(get(base + "/api/health")[2])["stale"] is False
    monkeypatch.setattr(serve, "STALE_MIN", -1)
    assert json.loads(get(base + "/api/health")[2])["stale"] is True


def test_read_only(server):
    base, db, _ = server
    req = urllib.request.Request(base + "/api/now", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 405


def test_missing_now_json(tmp_path):
    httpd = serve.serve(0, db=tmp_path / "none.db", out_dir=tmp_path / "out")
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        assert get(base + "/api/now")[0] == 503
        h = json.loads(get(base + "/api/health")[2])
        assert h["stale"] is True and h["last_ok"] is None
    finally:
        httpd.shutdown()


def test_foreign_host_rejected(server):
    base, _, _ = server
    req = urllib.request.Request(base + "/api/now", headers={"Host": "evil.example:8765"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403
    for ok in ("pulse-host.example-tailnet.ts.net:8765", "localhost:8765", "macmini:8765"):
        req = urllib.request.Request(base + "/api/health", headers={"Host": ok})
        assert urllib.request.urlopen(req, timeout=5).status == 200


def test_health_survives_unreadable_db(server, monkeypatch):
    base, _, _ = server
    def boom(db):
        raise serve.sqlite3.OperationalError("attempt to write a readonly database")
    monkeypatch.setattr(serve, "ro_connect", boom)
    code, _, body = get(base + "/api/health")
    h = json.loads(body)
    assert code == 200 and h["stale"] is True and h["db_error"] == "OperationalError"


def test_db_is_wal(server):
    _, db, _ = server
    assert store.connect(db).execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_brief_path_guard(server, tmp_path):
    base, _, _ = server
    assert get(base + "/brief")[0] == 404   # 접은 긴 글 시안 경로는 없다
    assert get(base + "/api/brief/sample")[0] == 404
    assert get(base + "/api/brief/2026-11-11-am-b99")[0] == 404
    assert get(base + "/api/brief/..%2Fpulse")[0] == 404
    assert serve.read_brief("../../etc/passwd") is None
    (tmp_path / "2026-11-11").mkdir()
    (tmp_path / "2026-11-11" / "2026-11-11-am-b01.yaml").write_text("headline: 가상 제목\n", encoding="utf-8")
    assert serve.read_brief("2026-11-11-am-b01", tmp_path) == {"headline": "가상 제목"}


VERDICTS = {"확인", "일부 맞음", "사실과 다름", "근거 없음", "확인 못 함"}
SLIDE_TYPES = {"cover", "number", "claim", "bars", "cards", "text", "questions"}


def test_deck_sample_shape(server):
    base, _, _ = server
    assert get(base + "/deck")[0] == 200
    d = json.loads(get(base + "/api/brief/deck-sample")[2])
    assert d["format"] == "deck" and d["slides"][0]["type"] == "cover"
    ids = {s["id"] for s in d["sources"]}
    for s in d["slides"]:
        assert s["type"] in SLIDE_TYPES
        if s["type"] != "cover":
            assert s.get("title")   # 제목은 문장 — 제목만 넘겨 읽어도 줄거리가 되게
        if s["type"] == "claim":
            assert s["verdict"] in VERDICTS and s.get("why")
        assert set(s.get("sources", [])) <= ids   # 근거는 출처 목록 안에서만
