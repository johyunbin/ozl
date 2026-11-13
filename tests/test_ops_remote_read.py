"""이 기기 밖(tailnet 이름 Host)에서 들어온 읽기는 로그인을 거친다(설계 9절, 16절)."""
from __future__ import annotations

import pytest

from test_ops_support import desk, ops, real_untouched, start  # noqa: F401

pytestmark = pytest.mark.usefixtures("real_untouched")

TS = "macmini.tail0000.ts.net"
GATED = ("/ops", "/pick", "/approve", "/preview/", "/preview/index.html", "/preview", "/no-such-page")
OPEN = ("/login", "/ops/static/ops.css", "/", "/deck", "/api/now", "/api/health")


@pytest.fixture()
def remote(tmp_path, desk):
    r = start(tmp_path, allow_hosts=(TS,))
    r.client.host = f"{TS}:{r.port}"
    yield r
    r.srv.shutdown()
    r.srv.server_close()


def test_remote_without_session_goes_to_login(remote):
    c = remote.client
    for method in ("GET", "HEAD"):
        for path, nxt in (("/pick", "/pick"), ("/approve", "/approve"), ("/ops", "/ops"), ("/preview/", "/ops"),
                          ("/preview/index.html", "/ops"), ("/preview", "/ops"), ("/no-such-page", "/ops")):
            st, r, body = c.req(method, path)
            assert st == 303 and r.getheader("Location") == f"/login?next={nxt}", (method, path, st)
            assert "미리보기 첫 화면" not in body and "가상" not in body
    st, r, _ = c.get("/pick?next=/approve")
    assert st == 303 and r.getheader("Location") == "/login?next=/pick"


def test_remote_open_paths_stay_open(remote):
    c = remote.client
    for path in OPEN:
        st, r, _ = c.get(path)
        assert st in (200, 503), (path, st)       # /api/now 는 자료가 있어 200
        assert r.getheader("Location") is None, path
    st, r, _ = c.get("/ops/static/ops.css")
    assert st == 200 and r.getheader("Content-Type").startswith("text/css")
    st, r, _ = c.get("/api/now")
    assert st == 200 and r.getheader("Content-Type").startswith("application/json")


def test_remote_after_login_is_200(remote):
    c = remote.client
    c.login()                                  # Host·Origin 모두 tailnet 이름으로
    for path in GATED[:5]:
        st, r, _ = c.get(path)
        assert st == 200, (path, st)
    assert c.req("HEAD", "/approve")[0] == 200
    st, r, body = c.get("/preview/")
    assert "미리보기 첫 화면" in body
    c.cookie = c.cookie.split("=")[0] + "=0.0.0"   # 망가진 쿠키는 세션이 아니다
    assert c.get("/pick")[0] == 303


def test_local_host_without_session_is_200(ops):
    c = ops.client
    for host in (f"127.0.0.1:{ops.port}", f"localhost:{ops.port}", f"[::1]:{ops.port}", "127.0.0.1"):
        for path in ("/ops", "/pick", "/approve", "/preview/"):
            st, r, _ = c.get(path, headers={"Host": host})
            assert st == 200, (host, path, st)


@pytest.mark.parametrize("listed", [TS, TS.upper() + "."])
def test_open_read_hosts_lets_name_read_without_login(tmp_path, desk, listed):
    r = start(tmp_path, allow_hosts=(TS,), open_read_hosts=(listed,))
    try:
        c = r.client
        c.host = f"{TS}:{r.port}"
        for path in ("/ops", "/pick", "/approve", "/preview/"):
            assert c.get(path)[0] == 200, path
        assert c.get("/pick", headers={"Host": f"other.tail0000.ts.net:{r.port}"})[0] == 303
    finally:
        r.srv.shutdown()
        r.srv.server_close()


def test_post_check_unchanged_for_remote(remote):
    """쓰기 검사는 그대로: 세션 없는 tailnet POST 는 로그인 화면이 아니라 401."""
    c = remote.client
    st, r, _ = c.req("POST", "/pick/make", form={"key": "t:9000", "request_id": "0" * 32, "csrf": "x"})
    assert st == 401 and r.getheader("Location") is None


def test_server_json_open_read_hosts(tmp_path):
    from ozl.ops import __main__ as M
    assert M._names(None) == () and M._names("a.ts.net") == () and M._names([TS, 3, " "]) == (TS,)
