"""운영 화면 시험의 공통 준비 — 시험 자료 루트, 지어낸 now.json, 지어낸 미리보기 폴더, 실제 서버와 http.client 도우미.

conftest 를 고치지 않고 여기 둔다. 다른 test_ops_* 파일이 `from test_ops_support import …` 로 가져다 쓴다.
요청은 127.0.0.1 로만 보낸다. 제목과 문구는 모두 지어낸 것이다.
"""
from __future__ import annotations

import hashlib
import html
import http.client
import json
import os
import pathlib
import re
import shutil
import sys
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.issues import paths  # noqa: E402
from ozl.ops import auth, server  # noqa: E402

REAL_DESK = ROOT / "private" / "desk"
FIX_ISSUES = ROOT / "tests" / "fixtures" / "issues"
NOW = datetime(2099, 1, 1, 3, 0, tzinfo=timezone.utc)      # KST 12:00
SENS = [{"level": "GREEN", "reasons": []}, {"level": "YELLOW", "reasons": ["가상 사유 갑"]},
        {"level": "RED", "reasons": ["가상 사유 을"]}]


def real_fingerprint() -> tuple:
    """실제 자료 루트의 발행 목록 해시, 승인 기록 수, ops 폴더 존재 여부(다른 작업이 이슈를 쓰는 중이라 폴더 전체는 비교하지 않는다)."""
    man = REAL_DESK / "issues" / "manifest.json"
    h = hashlib.sha256(man.read_bytes()).hexdigest() if man.exists() else "없음"
    n = len(list((REAL_DESK / "issues").glob("*/revisions/*/approval.json")))
    return h, n, (REAL_DESK / "ops").exists()


@pytest.fixture(scope="module", autouse=False)
def real_untouched():
    before = real_fingerprint()
    yield
    assert real_fingerprint() == before


def fake_now(n_topics: int = 15) -> dict:
    topics = []
    for i in range(n_topics):
        tid = 9000 + i
        topics.append({
            "topic_id": tid, "rank": i + 1, "title": f"가상 주제 {i + 1}번 소식", "lang": "ko",
            "score": round(3.0 - i * 0.1, 2), "on": ["보도"] + (["검색"] if i == 0 else []),
            "n_outlets": 2 + i, "first_seen": "2098-12-31T20:00:00+00:00",
            "sensitivity": SENS[i % 3],
            "items": [{"title": f"가상 기사 {i}-가", "outlet": "가상일보", "ts": "2098-12-31T21:00:00+00:00"},
                      {"title": f"가상 기사 {i}-나", "outlet": "가상방송", "ts": "2098-12-31T22:00:00+00:00"}],
        })
    return {"generated_at": "2099-01-01T11:00:00+09:00", "note": "가상 주의 문구", "feeds_failed": 0,
            "topics": topics,
            "searches": [{"title": "가상검색어", "lang": "ko", "topic_id": 9000, "sensitivity": SENS[0]},
                         {"title": "따로검색어", "lang": "ko", "topic_id": None, "sensitivity": SENS[0]}]}


def make_preview(d: pathlib.Path) -> pathlib.Path:
    (d / "pagefind").mkdir(parents=True)
    (d / "index.html").write_text('<!doctype html><html><head><script type="module">console.log("가상")</script>'
                                  '<script src="/preview/_astro/a.js"></script></head><body>미리보기 첫 화면</body></html>',
                                  encoding="utf-8")
    (d / "pagefind" / "pagefind.js").write_text("export const x = 1;", encoding="utf-8")
    (d / "pagefind" / "wasm.unknown.pagefind").write_bytes(b"\x00asm")
    (d / "pagefind" / "pagefind.ko_x.pf_meta").write_bytes(b"\x01\x02")
    (d / "404.html").write_text("<!doctype html><p>미리보기 없는 쪽</p>", encoding="utf-8")
    (d / ".ozl-web-out").write_text("표식", encoding="utf-8")
    return d


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    d = tmp_path / "desk"
    shutil.copytree(FIX_ISSUES, d / "issues")
    monkeypatch.setenv(paths.ENV, str(d))
    assert not paths.is_real_root()
    return d


class Client:
    """http.client 로 Host·Origin 을 지정해 보내는 도우미. 로그인하면 쿠키와 요청 토큰을 쥔다."""

    def __init__(self, port: int, token: str) -> None:
        self.port, self.token = port, token
        self.host = f"127.0.0.1:{port}"
        self.cookie: str | None = None
        self.csrf: str | None = None
        self.locations: list[str] = []

    def req(self, method: str, path: str, body: bytes | str | None = None, headers: dict | None = None,
            form: dict | None = None):
        h = {"Host": self.host}
        if method == "POST":
            h["Origin"] = f"http://{self.host}"
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if self.cookie:
            h["Cookie"] = self.cookie
        if form is not None:
            body = urllib.parse.urlencode(form)
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        b = body.encode("utf-8") if isinstance(body, str) else body
        if b is not None and "Content-Length" not in h:
            h["Content-Length"] = str(len(b))
        for k, v in h.items():
            c.putheader(k, v)
        c.endheaders()
        if b:
            c.send(b)
        r = c.getresponse()
        data = r.read()
        loc = r.getheader("Location")
        if loc:
            self.locations.append(loc)
        c.close()
        return r.status, r, data.decode("utf-8", "replace")

    def get(self, path: str, **kw):
        return self.req("GET", path, **kw)

    def login(self) -> None:
        st, r, text = self.get("/login")
        pre_cookie = r.getheader("Set-Cookie").split(";")[0]
        pre = hidden(text, "pre")
        self.cookie = pre_cookie
        st, r, _ = self.req("POST", "/login", form={"token": self.token, "pre": pre, "next": "/pick"})
        assert st == 303, st
        self.cookie = [c for c in r.headers.get_all("Set-Cookie") if c.startswith("ozl_ops=")][0].split(";")[0]
        st, r, text = self.get("/pick")
        self.csrf = hidden(text, "csrf")
        self.pre = pre

    def post(self, path: str, fields: dict, **kw):
        f = {"request_id": os.urandom(16).hex(), "csrf": self.csrf, **fields}
        f = {k: v for k, v in f.items() if v is not None}
        return self.req("POST", path, form=f, **kw)


def hidden(text: str, name: str) -> str:
    m = re.search(r'<input type="hidden" name="' + re.escape(name) + r'" value="([^"]*)"', text)
    assert m, name
    return html.unescape(m.group(1))


class Running:
    def __init__(self, srv, client, tmp) -> None:
        self.srv, self.client, self.tmp = srv, client, tmp
        self.port = srv.server_address[1]

    @property
    def ops(self) -> pathlib.Path:
        return paths.desk_root() / "ops"

    def lines(self, name: str = "actions.jsonl") -> list[dict]:
        p = self.ops / name
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def state(self, name: str) -> dict:
        p = self.ops / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"items": []}


def start(tmp_path, *, preview: bool = True, now_json: dict | None = None, clock=lambda: NOW, **cfg_kw) -> Running:
    tok_path = tmp_path / "ops" / "token"
    auth.write_token(tok_path)
    out = tmp_path / "pulse_out"
    out.mkdir(exist_ok=True)
    (out / "now.json").write_text(json.dumps(now_json if now_json is not None else fake_now(), ensure_ascii=False),
                                  encoding="utf-8")
    pv = make_preview(tmp_path / "preview") if preview else tmp_path / "no_preview"
    cfg = server.Config(port=0, token_path=tok_path, log_path=tmp_path / "ops" / "access.log", preview_dir=pv,
                        pulse_out=out, pulse_db=tmp_path / "none.db", clock=clock, **cfg_kw)
    srv = server.make_server(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return Running(srv, Client(srv.server_address[1], auth.read_token(tok_path)), tmp_path)


@pytest.fixture()
def ops(tmp_path, desk):
    r = start(tmp_path)
    yield r
    r.srv.shutdown()
    r.srv.server_close()


def tomorrow_clock():
    return NOW + timedelta(days=1)


def test_fake_now_shape():
    d = fake_now()
    assert len(d["topics"]) == 15 and {t["sensitivity"]["level"] for t in d["topics"]} == {"GREEN", "YELLOW", "RED"}
    assert len(d["searches"]) == 2
