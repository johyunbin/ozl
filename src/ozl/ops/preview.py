"""미리보기 정적 파일 `/preview/…`(설계 6절).

경로 벗어나기를 막고(NUL·역슬래시·`..`·점으로 시작하는 조각·폴더 밖 resolve 는 404), 이 경로 전용 콘텐츠 보안 정책을 붙인다.
스크립트·연결·워커 출처를 `<출처>/preview/` 로 묶고, 인라인 스크립트는 어떤 것도 허락하지 않는다(해시도 넣지 않는다).
미리보기는 운영 화면과 같은 출처라, 빌드 자료에서 끼어든 인라인 스크립트가 돌면 새 창으로 `/approve` 를 열어 누를 수 있기 때문이다.
웹 빌드는 실행되는 인라인 스크립트가 0개다(`apps/web/scripts/check-html.mjs` 가 빌드 때 검사한다).
`/preview/` 아래에서는 경로 밖으로 넘기는 응답(30x)을 만들지 않는다.
"""
from __future__ import annotations

import pathlib
import urllib.parse
from dataclasses import dataclass

PREFIX = "/preview/"
BUILD_CMD = (".venv/bin/python -m ozl.issues export --preview --out private/out/site_data && cd apps/web && "
             "OZL_SITE_DATA=../../private/out/site_data npm run build:preview")
CTYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
    ".json": "application/json", ".wasm": "application/wasm",
    ".pagefind": "application/octet-stream", ".pf_meta": "application/octet-stream", ".pf_index": "application/octet-stream",
    ".pf_fragment": "application/octet-stream", ".pf_filter": "application/octet-stream",
    ".woff2": "font/woff2", ".woff": "font/woff", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".webp": "image/webp", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8", ".xml": "application/xml",
}
@dataclass
class Reply:
    code: int
    body: bytes
    ctype: str
    headers: dict


def csp(host: str) -> str:
    p = f"http://{host}{PREFIX}"
    return (f"default-src 'none'; script-src {p} 'wasm-unsafe-eval'; worker-src {p}; connect-src {p}; style-src {p} 'unsafe-inline'; "
            f"font-src {p}; img-src {p} data:; manifest-src {p}; base-uri 'none'; form-action 'none'; frame-src 'none'; "
            "frame-ancestors 'none'; object-src 'none'")


def resolve(base: pathlib.Path, url_path: str) -> pathlib.Path | None:
    """`/preview/` 뒤의 경로를 폴더 안의 파일로. 벗어나면 None."""
    rest = urllib.parse.unquote(url_path[len(PREFIX):])
    if "\x00" in rest or "\\" in rest:
        return None
    parts = [s for s in rest.split("/") if s]
    if any(s == ".." or s.startswith(".") for s in parts):
        return None
    try:
        p = (base / "/".join(parts)).resolve() if parts else base
    except (OSError, ValueError, RuntimeError):
        return None
    if not (p == base or base in p.parents):
        return None
    return p


def _cache_control(base: pathlib.Path, p: pathlib.Path) -> str:
    if p.suffix == ".html":
        return "no-cache"
    rel = p.relative_to(base).parts
    return "max-age=86400" if rel and rel[0] in ("_astro", "fonts") else "no-cache"


def _file(base: pathlib.Path, p: pathlib.Path, host: str, code: int = 200) -> Reply:
    body = p.read_bytes()
    ctype = CTYPES.get(p.suffix.lower(), "application/octet-stream")
    return Reply(code, body, ctype, {"Cache-Control": _cache_control(base, p), "Content-Security-Policy": csp(host)})


def not_found(base: pathlib.Path, host: str) -> Reply:
    p = base / "404.html"
    if p.is_file():
        return _file(base, p, host, 404)
    return Reply(404, "없는 쪽이다.".encode("utf-8"), "text/plain; charset=utf-8",
                 {"Cache-Control": "no-cache", "Content-Security-Policy": csp(host)})


def serve(base: pathlib.Path | None, url_path: str, host: str) -> Reply:
    """GET·HEAD `/preview/…`. base 는 서버 시작 때 resolve 한 절대 경로(없으면 None)."""
    if base is None or not base.is_dir():
        return Reply(503, b"", "missing", {})
    p = resolve(base, url_path)
    if p is None:
        return not_found(base, host)
    if p.is_dir():
        p = p / "index.html"
    elif not p.exists() and not p.suffix:
        p = p / "index.html"
    try:
        ok = p.is_file() and (p.resolve() == base or base in p.resolve().parents)
    except OSError:
        ok = False
    if not ok:
        return not_found(base, host)
    return _file(base, p.resolve(), host)
