"""옛 주소 그대로 — 옛 서버(ozl.pulse.serve)와 새 서버에 같은 재료로 불러 몸체와 머리를 비교한다(설계 10절, 11절).

재료는 test_pulse_serve 처럼 지어낸 기사로 임시 DB 와 now.json 을 만든다.
"""
from __future__ import annotations

import http.client
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from test_ops_support import desk, real_untouched  # noqa: F401
from test_pulse import STORY, it

from ozl.ops import auth, server
from ozl.pulse import serve as old, snapshot, store

pytestmark = pytest.mark.usefixtures("real_untouched")


@pytest.fixture()
def pair(tmp_path, desk):
    db, out = tmp_path / "p.db", tmp_path / "out"
    now = datetime.now(timezone.utc)
    con = store.connect(db)
    items = [{**it(t, o), "published": (now - timedelta(minutes=m)).isoformat()}
             for t, o, m in zip(STORY, ["가상일보", "가상경제", "가상방송"], (40, 20, 10))]
    store.add_items(con, items, now)
    con.commit()
    assert snapshot.run(fetch=False, now=now, db=db, out_dir=out, youtube=[])["ok"]
    a = old.serve(0, db=db, out_dir=out)
    tok = tmp_path / "ops" / "token"
    auth.write_token(tok)
    b = server.make_server(server.Config(port=0, token_path=tok, log_path=tmp_path / "ops" / "access.log",
                                         preview_dir=None, pulse_out=out, pulse_db=db))
    for s in (a, b):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    yield a.server_address[1], b.server_address[1], out
    for s in (a, b):
        s.shutdown()
        s.server_close()


def call(port: int, method: str, path: str):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=b"" if method == "POST" else None, headers={"Host": f"127.0.0.1:{port}"})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, r, body


def test_same_bodies_and_headers(pair):
    pa, pb, out = pair
    tid = json.loads((out / "now.json").read_text(encoding="utf-8"))["topics"][0]["topic_id"]
    for path in ("/", "/index.html", "/deck", "/api/now", f"/api/topic/{tid}", "/api/topic/999999", "/api/brief/deck-sample",
                 "/api/brief/2099-01-01-am-b01", "/api/health"):
        sa, ra, ba = call(pa, "GET", path)
        sb, rb, bb = call(pb, "GET", path)
        assert sa == sb, path
        if path == "/api/health":
            ja, jb = json.loads(ba), json.loads(bb)
            ja.pop("now"), jb.pop("now")
            assert ja == jb
        else:
            assert ba == bb, path
        for h in ("Content-Type", "Content-Security-Policy", "Cache-Control", "X-Content-Type-Options"):
            assert ra.getheader(h) == rb.getheader(h), (path, h)
    sa, ra, ba = call(pa, "HEAD", "/api/now")
    sb, rb, bb = call(pb, "HEAD", "/api/now")
    assert (sa, ba, ra.getheader("Content-Length")) == (sb, bb, rb.getheader("Content-Length"))


def test_old_writes_are_405(pair):
    pa, pb, _ = pair
    for path in ("/api/now", "/", "/api/health"):
        for m in ("POST", "PUT", "DELETE"):
            sa, _, ba = call(pa, m, path)
            sb, _, bb = call(pb, m, path)
            assert sa == sb == 405 and ba == bb


def test_host_refused_same(pair):
    pa, pb, _ = pair
    for port in (pa, pb):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/api/now", headers={"Host": "evil.example"})
        r = c.getresponse()
        assert r.status == 403 and json.loads(r.read())["error"] == "허용하지 않은 Host"
        c.close()
