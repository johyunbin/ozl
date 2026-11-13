"""쓰기 요청 검사 — 토큰 없는 요청, 다른 출처의 요청, 다른 사이트가 대신 보낸 요청 거부, 토큰이 주소와 로그에 없음(설계 3절, 11절).

등록된 모든 POST 주소를 `server.POST_ROUTES` 에서 꺼내 돌린다. 검사를 거치지 않는 POST 주소가 생기면 여기서 실패한다.
"""
from __future__ import annotations

import http.client
import os
import re
import time

import pytest

from test_ops_support import desk, hidden, ops, real_untouched, start  # noqa: F401

from ozl.issues import style
from ozl.ops import auth, server

pytestmark = pytest.mark.usefixtures("real_untouched")


def ops_files(o) -> dict:
    d = o.ops
    return {p.name: p.read_bytes() for p in d.glob("*") if p.is_file() and p.name != ".lock"} if d.exists() else {}


def valid_form(path: str) -> dict:
    return {"/pick/make": {"key": "t:9000"}, "/pick/later": {"key": "t:9000"}, "/pick/discard": {"key": "t:9000"},
            "/pick/restore": {"key": "t:9000"}, "/pick/keyword": {"text": "가상"},
            "/pick/cancel": {"job_id": "m20990101-0001"}}.get(path, {})


def test_every_post_route_needs_session_and_csrf(ops):
    c = ops.client
    assert server.POST_ROUTES, "POST 주소 표가 비었다"
    for path, (kind, _) in server.POST_ROUTES.items():
        before = ops_files(ops)
        st, _, _ = c.req("POST", path, form={**valid_form(path), "request_id": os.urandom(16).hex()})
        assert st == (403 if kind == "login" else 401), path
        assert ops_files(ops) == before, path
    c.login()
    for path, (kind, _) in server.POST_ROUTES.items():
        if kind == "login":
            continue
        before = ops_files(ops)
        for bad in (None, "0" * 64, c.csrf[:-1] + ("0" if c.csrf[-1] != "0" else "1")):
            st, _, _ = c.req("POST", path, form={**valid_form(path), "request_id": os.urandom(16).hex(),
                                                 **({"csrf": bad} if bad else {})})
            assert st == 403, (path, bad)
        # 다른 사이트가 쿠키를 실어 보낸 경우: Origin 이 다르면 403
        st, _, _ = c.post(path, valid_form(path), headers={"Origin": "http://evil.example"})
        assert st == 403, path
        assert ops_files(ops) == before, path
    assert all(k == "login" or k == "session" for k, _ in server.POST_ROUTES.values())


def test_cookie_missing_is_401_and_nothing_written(ops):
    c = ops.client
    st, _, text = c.req("POST", "/pick/make", form={"key": "t:9000", "request_id": os.urandom(16).hex(), "csrf": "x"})
    assert st == 401 and "로그인이 필요하다" in text
    assert ops_files(ops) == {}


@pytest.mark.parametrize("headers", [
    {"Origin": None}, {"Origin": "http://evil.example"}, {"Origin": "https://127.0.0.1"},
    {"Host": "evil.example:80"}, {"Host": "macmini.tail0000.ts.net"}, {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
def test_other_origin_is_403(ops, headers):
    c = ops.client
    c.login()
    st, _, _ = c.post("/pick/make", {"key": "t:9000"}, headers=headers)
    assert st == 403
    assert not (ops.ops / "actions.jsonl").exists()


def test_allow_host_exact(tmp_path, desk):
    r = start(tmp_path, allow_hosts=("macmini.tail0000.ts.net",))
    try:
        c = r.client
        c.login()
        h = f"macmini.tail0000.ts.net:{r.port}"
        st, _, _ = c.post("/pick/make", {"key": "t:9000"}, headers={"Host": h, "Origin": f"http://{h}"})
        assert st == 303
        st, _, _ = c.post("/pick/make", {"key": "t:9001"}, headers={"Host": h, "Origin": "http://other.ts.net"})
        assert st == 403
    finally:
        r.srv.shutdown()
        r.srv.server_close()


def test_login_pre_token_and_rate_limit(ops):
    c = ops.client
    st, r, text = c.get("/login")
    cookie = r.getheader("Set-Cookie")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/login" in cookie
    pre = hidden(text, "pre")
    c.cookie = cookie.split(";")[0]
    assert c.req("POST", "/login", form={"token": c.token, "pre": "다른값", "next": "/pick"})[0] == 403
    c.cookie = None
    assert c.req("POST", "/login", form={"token": c.token, "pre": pre, "next": "/pick"})[0] == 403
    c.cookie = cookie.split(";")[0]
    for _ in range(5):
        assert c.req("POST", "/login", form={"token": "틀린토큰", "pre": pre})[0] == 401
    # 잠긴 뒤: 틀린 토큰은 429, 맞는 토큰은 느리게라도 받는다(남이 틀린 토큰으로 주인을 막지 못한다)
    auth.LOCKED_DELAY = 0.3
    try:
        assert c.req("POST", "/login", form={"token": "틀린토큰", "pre": pre})[0] == 429
        t0 = time.monotonic()
        assert c.req("POST", "/login", form={"token": c.token, "pre": pre})[0] == 303
        assert time.monotonic() - t0 >= 0.3
    finally:
        auth.LOCKED_DELAY = 2.0


def test_login_next_allowlist(ops):
    c = ops.client
    st, r, text = c.get("/login?next=http://evil.example/")
    assert hidden(text, "next") == "/ops"
    c.cookie = r.getheader("Set-Cookie").split(";")[0]
    st, r, _ = c.req("POST", "/login", form={"token": c.token, "pre": hidden(text, "pre"), "next": "//evil.example"})
    assert st == 303 and r.getheader("Location") == "/ops?m=10"
    sc = [x for x in r.headers.get_all("Set-Cookie") if x.startswith("ozl_ops=")][0]
    assert "HttpOnly" in sc and "SameSite=Strict" in sc and "Max-Age=43200" in sc and "Secure" not in sc


@pytest.mark.parametrize("q", ["token", "t", "key", "csrf", "TOKEN", "a=1&token"])
def test_token_in_query_is_400(ops, q):
    c = ops.client
    for path in ("/login", "/pick", "/api/now", "/preview/"):
        st, r, _ = c.get(f"{path}?{q}={c.token}")
        assert st == 400, path
        assert not any(x.startswith("ozl_ops=") for x in (r.headers.get_all("Set-Cookie") or []))
    st, _, _ = c.req("POST", f"/login?{q}={c.token}", form={"token": c.token})
    assert st == 400


def test_length_and_type(ops):
    c = ops.client
    c.login()
    big = {"key": "t:9000", "pad": "a" * 9 * 1024}
    assert c.post("/pick/make", big)[0] == 413
    form = f"key=t%3A9000&request_id={os.urandom(16).hex()}&csrf={c.csrf}"
    conn = http.client.HTTPConnection("127.0.0.1", ops.port, timeout=5)
    conn.putrequest("POST", "/pick/make", skip_host=True)
    for k, v in (("Host", c.host), ("Origin", f"http://{c.host}"), ("Content-Type", "application/x-www-form-urlencoded"),
                 ("Cookie", c.cookie)):
        conn.putheader(k, v)
    conn.endheaders()
    assert conn.getresponse().status == 411
    conn.close()
    assert c.req("POST", "/pick/make", body=form, headers={"Transfer-Encoding": "chunked", "Content-Length": None})[0] == 411
    assert c.req("POST", "/pick/make", body=form, headers={"Content-Type": "application/json"})[0] == 415
    assert c.req("POST", "/pick/make", body=form, headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"})[0] == 303
    dup = form + "&key=t%3A9001"
    assert c.req("POST", "/pick/make", body=dup)[0] == 400
    assert not [x for x in ops.lines() if x["key"] == "t:9001"]


def test_tampered_and_old_cookie_401(ops):
    c = ops.client
    c.login()
    ts, rnd, sig = c.cookie.split("=", 1)[1].split(".")
    bad = f"ozl_ops={ts}.{rnd}.{sig[:-1]}{'0' if sig[-1] != '0' else '1'}"
    key = auth.session_key(c.token)
    old_val = auth.make_session(key, time.time() - 15 * 24 * 3600)
    old_rnd = old_val.split(".")[1]
    for cookie, csrf in ((bad, c.csrf), (f"ozl_ops={old_val}", auth.csrf_for(key, old_rnd))):
        st, _, _ = c.req("POST", "/pick/make", form={"key": "t:9000", "request_id": os.urandom(16).hex(), "csrf": csrf},
                         headers={"Cookie": cookie})
        assert st == 401
    assert auth.check_session(key, c.cookie.split("=", 1)[1]) == rnd


def test_rotate_ends_sessions(ops):
    c = ops.client
    c.login()
    assert c.post("/pick/later", {"key": "t:9000"})[0] == 303
    auth.write_token(ops.srv.cfg.token_path)
    assert c.post("/pick/later", {"key": "t:9001"})[0] == 401


def test_token_file_mode_644_refuses_start(tmp_path, desk):
    p = tmp_path / "t" / "token"
    auth.write_token(p)
    os.chmod(p, 0o644)
    with pytest.raises(RuntimeError):
        server.make_server(server.Config(port=0, token_path=p, log_path=tmp_path / "a.log"))
    os.chmod(p, 0o600)
    with pytest.raises(ValueError):
        server.make_server(server.Config(port=0, host="0.0.0.0", token_path=p, log_path=tmp_path / "a.log"))


def test_methods_and_unknown(ops):
    c = ops.client
    assert c.req("PUT", "/pick/make", body="")[0] == 405
    assert c.req("DELETE", "/ops", body="")[0] == 405
    assert c.get("/pick/make")[0] == 405
    assert c.get("/nowhere")[0] == 404
    st, r, _ = c.get("/pick")
    for h, v in (("X-Frame-Options", "DENY"), ("Cross-Origin-Opener-Policy", "same-origin"),
                 ("Referrer-Policy", "same-origin"), ("X-Content-Type-Options", "nosniff"), ("Cache-Control", "no-store")):
        assert r.getheader(h) == v
    csp = r.getheader("Content-Security-Policy")
    assert "script-src 'none'" in csp and "frame-ancestors 'none'" in csp and "wasm-unsafe-eval" not in csp
    assert c.get("/pick", headers={"Host": "evil.example"})[0] == 403


def test_secrets_never_in_logs_or_locations(ops, capfd):
    c = ops.client
    c.login()
    secrets_seen = {c.token, c.cookie.split("=", 1)[1], c.csrf, c.pre, c.cookie.split("=", 1)[1].split(".")[1]}
    c.post("/pick/make", {"key": "t:9000"})
    c.post("/pick/keyword", {"text": "가상 키워드"})
    c.post("/pick/discard", {"key": "t:9001"})
    c.post("/pick/make", {"key": "t:9002"}, headers={"Origin": "http://evil.example"})
    c.get(f"/login?token={c.token}")
    c.get(f"/pick?csrf={c.csrf}")
    c.req("POST", "/login", form={"token": c.token, "pre": "x"})
    c.post("/logout", {})
    out, err = capfd.readouterr()
    blobs = [out, err, "\n".join(c.locations)]
    for p in [ops.srv.cfg.log_path, *ops.ops.rglob("*")]:
        if p.is_file():
            blobs.append(p.read_text(encoding="utf-8", errors="replace"))
    log = ops.srv.cfg.log_path.read_text(encoding="utf-8")
    assert re.search(r"^\S+ POST /pick/make 303 \d+$", log, re.M) and "?" not in log
    for s in secrets_seen:
        assert len(s) >= 16
        for b in blobs:
            assert s not in b
    assert ops.srv.last_error is None


def test_screen_text_has_no_internal_notation(ops):
    c = ops.client
    pages = [c.get(p)[2] for p in ("/ops", "/login", "/pick", "/nowhere")]
    c.login()
    c.post("/pick/make", {"key": "t:9000"})
    pages += [c.get(p)[2] for p in ("/ops", "/pick?m=1")]
    for text in pages:
        visible = re.sub(r"<[^>]+>", "\n", text)
        for chunk in visible.split("\n"):
            chunk = chunk.strip()
            if chunk and "python -m ozl.ops" not in chunk:
                errs = style.text_errors("ops", chunk)
                assert not errs, (chunk, errs)
