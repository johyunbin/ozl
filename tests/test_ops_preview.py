"""미리보기 내주기 — 콘텐츠 종류, 경로 묶은 보안 정책, 경로 벗어나기 거부, 폴더 없음 503(설계 6절, 11절)."""
from __future__ import annotations

import http.client
import os
import re

import pytest

from test_ops_support import ROOT, desk, ops, real_untouched, start  # noqa: F401

pytestmark = pytest.mark.usefixtures("real_untouched")


def raw_get(port: int, path: str, host: str):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", host)
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, r, body


def test_files_and_types(ops):
    c = ops.client
    for path, ctype in (("/preview/", "text/html; charset=utf-8"), ("/preview/index.html", "text/html; charset=utf-8"),
                        ("/preview/pagefind/pagefind.js", "text/javascript"),
                        ("/preview/pagefind/wasm.unknown.pagefind", "application/octet-stream"),
                        ("/preview/pagefind/pagefind.ko_x.pf_meta", "application/octet-stream")):
        st, r, _ = c.get(path)
        assert st == 200 and r.getheader("Content-Type") == ctype, path
        assert r.getheader("X-Content-Type-Options") == "nosniff"
    st, r, body = c.get("/preview/")
    csp = r.getheader("Content-Security-Policy")
    assert "sha256-" not in csp and "'wasm-unsafe-eval'" in csp and "'unsafe-eval'" not in csp
    assert script_src(csp) == f"http://{c.host}/preview/ 'wasm-unsafe-eval'"
    assert f"connect-src http://{c.host}/preview/;" in csp
    assert "frame-ancestors 'none'" in csp and "'unsafe-inline'" not in csp.split("style-src")[0]
    assert r.getheader("Cache-Control") == "no-cache"
    st, r, _ = c.get("/pick")
    assert "wasm-unsafe-eval" not in r.getheader("Content-Security-Policy")
    st, r, _ = c.get("/preview")
    assert st == 301 and r.getheader("Location") == "/preview/"
    st, r, body = c.get("/preview/no-such-page")
    assert st == 404 and "미리보기 없는 쪽" in body


def script_src(csp: str) -> str:
    m = re.search(r"(?:^|;)\s*script-src ([^;]*)", csp)
    assert m, csp
    return m.group(1).strip()


def test_inline_script_not_allowed(ops):
    """빌드 자료에서 인라인 스크립트가 끼어들어도 정책이 그것을 허락하지 않는다(해시도, 'unsafe-inline' 도 없다)."""
    base = ops.srv.preview_base
    (base / "i").mkdir()
    (base / "i" / "index.html").write_text(
        '<!doctype html><script>fetch("/approve")</script><script type="module">window.open("/approve")</script>'
        '<script type="application/json">{"가상": 1}</script><p>가상 이슈</p>', encoding="utf-8")
    for path in ("/preview/i/", "/preview/", "/preview/no-such-page"):
        st, r, body = ops.client.get(path)
        csp = r.getheader("Content-Security-Policy")
        src = script_src(csp)
        assert "sha256-" not in csp and "'unsafe-inline'" not in src and "'nonce-" not in src, path
        assert src.split() == [f"http://{ops.client.host}/preview/", "'wasm-unsafe-eval'"], path
    st, r, body = ops.client.get("/preview/i/")
    assert st == 200 and 'fetch("/approve")' in body          # 본문은 그대로 내주고, 정책이 실행을 막는다


def test_cache_for_astro(ops, tmp_path):
    d = ops.srv.preview_base / "_astro"
    d.mkdir()
    (d / "a.js").write_text("1", encoding="utf-8")
    st, r, _ = ops.client.get("/preview/_astro/a.js")
    assert st == 200 and r.getheader("Cache-Control") == "max-age=86400"


def test_escape_attempts_are_404(ops, tmp_path):
    secret = "가상비밀내용"
    (tmp_path / "outside.txt").write_text(secret, encoding="utf-8")
    os.symlink(tmp_path / "outside.txt", ops.srv.preview_base / "link.txt")
    os.symlink(tmp_path, ops.srv.preview_base / "linkdir")
    host = ops.client.host
    for path in ("/preview/../ops/token", "/preview/%2e%2e/%2e%2e/private/ops/token", "/preview/..%2fx",
                 "/preview/..%2f..%2fops%2ftoken", "/preview/a\\b", "/preview/a%5cb", "/preview/.ozl-web-out",
                 "/preview/link.txt", "/preview/linkdir/outside.txt", "/preview/%00", "/preview/pagefind/%2e%2e/%2e%2e/outside.txt"):
        st, r, body = raw_get(ops.port, path, host)
        assert st == 404, path
        assert secret.encode("utf-8") not in body and ops.client.token.encode() not in body, path
        assert r.getheader("Location") is None


def test_missing_folder_503(tmp_path, desk):
    r = start(tmp_path, preview=False)
    try:
        st, _, body = r.client.get("/preview/")
        assert st == 503 and "미리보기가 아직 없다" in body and "npm run build:preview" in body
        assert "미리보기" in r.client.get("/ops")[2] and "없음" in r.client.get("/ops")[2]
    finally:
        r.srv.shutdown()
        r.srv.server_close()


REAL = ROOT / "private" / "out" / "web_preview"


@pytest.mark.skipif(not (REAL / "pagefind" / "pagefind-entry.json").exists(), reason="실제 미리보기 빌드가 없다")
def test_real_build_search_files(tmp_path, desk):
    r = start(tmp_path, preview=False)
    r.srv.preview_base = REAL.resolve()
    try:
        st, resp, _ = r.client.get("/preview/pagefind/pagefind-entry.json")
        assert st == 200 and resp.getheader("Content-Type") == "application/json"
        st, resp, body = r.client.get("/preview/")
        assert st == 200
        csp = resp.getheader("Content-Security-Policy")
        assert "sha256-" not in csp and "'unsafe-inline'" not in script_src(csp)
    finally:
        r.srv.shutdown()
        r.srv.server_close()


SCRIPT_TAG = re.compile(r"<script\b([^>]*)>", re.IGNORECASE)
DATA_TYPES = ("application/json", "application/ld+json")


def executable_inline(text: str) -> int:
    """실행되는 인라인 스크립트 수: src 가 없고 type 이 자료 블록(json·ld+json)이 아닌 <script>."""
    n = 0
    for m in SCRIPT_TAG.finditer(text):
        attrs = m.group(1)
        if re.search(r"(?:^|\s)src\s*=", attrs, re.IGNORECASE):
            continue
        t = re.search(r"""(?:^|\s)type\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", attrs, re.IGNORECASE)
        ty = (t.group(1) or t.group(2) or t.group(3) or "").strip().lower() if t else ""
        if ty not in DATA_TYPES:
            n += 1
    return n


def test_executable_inline_counter():
    assert executable_inline('<script>a()</script><script type="module">b()</script>') == 2
    assert executable_inline('<script type="application/json">{}</script><script type=\'application/ld+json\'>{}</script>'
                             '<script src="/preview/_astro/a.js"></script><script defer src=x.js></script>') == 0


@pytest.mark.skipif(not REAL.is_dir(), reason="실제 미리보기 빌드가 없다")
def test_real_build_has_no_executable_inline_script():
    """정책이 인라인 스크립트를 막으므로, 빌드에 실행되는 인라인 스크립트가 있으면 그 쪽은 미리보기에서 깨진다."""
    bad = {}
    files = list(REAL.rglob("*.html"))
    assert files
    for f in files:
        n = executable_inline(f.read_text(encoding="utf-8", errors="replace"))
        if n:
            bad[str(f.relative_to(REAL))] = n
    assert not bad, bad
