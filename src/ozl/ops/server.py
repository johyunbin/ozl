"""운영 서버 — 경로 나누기, 응답 머리, 접근 로그(설계 3·6·9절).

모든 POST 는 `POST_ROUTES` 에 등록되고, `_dispatch` 한 곳에서 `auth.check_write` 를 거친 뒤에만 처리기에 닿는다.
처리기마다 따로 검사하지 않는다. 시험은 `POST_ROUTES` 를 돌며 토큰 없는 요청이 모두 거부되는지 본다.
접근 로그에는 `시각 메서드 경로(질의 뺌) 상태 밀리초` 만 쓴다. 머리·쿠키·본문·질의·원격 주소는 쓰지 않는다.

읽기(GET·HEAD)는 Host 의 이름이 이 기기 주소(`LOCAL_NAMES`)이거나 `Config.open_read_hosts` 에 적힌 이름일 때만
로그인 없이 연다. 그 밖(tailnet 이름)으로 들어온 읽기는 옛 주소·`/login`·CSS(`OPEN_READ`) 말고는 세션이 있어야 하고,
없으면 `/login?next=…` 로 303. Host 는 요청하는 쪽이 적는 값이라, 서버가 127.0.0.1 에만 묶여 이 기기 밖에서는
프록시(tailscale serve)를 거쳐 tailnet 이름으로만 닿는다는 전제에 기댄다(설계 16절).
"""
from __future__ import annotations

import pathlib
import re
import secrets
import socket
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from ozl.issues import paths
from ozl.pulse import serve as P
from ozl.pulse import snapshot as pulse_snapshot
from ozl.pulse import store as pulse_store

from . import actions, approvals, approve_view, auth, candidates, compat, preview, queue, store, templates

PRIVATE_OPS = paths.ROOT / "private" / "ops"
STATIC = pathlib.Path(__file__).resolve().parent / "static"
OPS_CSP = ("default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'; "
           "frame-ancestors 'none'; script-src 'none'")
LOG_MAX = 5 * 1024 * 1024
# 리퍼러 정책은 same-origin 이다. no-referrer 로 두면 브라우저가 폼 제출(POST)의 Origin 머리를 `null` 로 보내고(Fetch 표준),
# 쓰기 검사가 그 요청을 다른 출처로 보고 403 으로 막는다 — 직접 Origin 을 적어 보내는 시험은 통과하는데 실제 브라우저에서는
# 로그인부터 안 됐다(2026-11-14 브라우저로 눌러 보고 찾음). same-origin 이면 같은 출처에는 Origin 이 실리고 다른 사이트로는 리퍼러가 나가지 않는다.
REFERRER = "same-origin"
BIND_OK = ("127.0.0.1", "::1")
LOCAL_NAMES = ("127.0.0.1", "localhost", "[::1]")
OPEN_READ = ("/login", "/ops/static/ops.css")     # 이 기기 밖에서도 로그인 없이 여는 읽기(옛 주소는 compat 이 따로)
MESSAGES: dict[int, str] = {**actions.MSG, **approvals.MSG}   # 알림 번호 → 문장. 다른 모듈이 번호를 더할 수 있다.


@dataclass
class Config:
    port: int = 8765
    host: str = "127.0.0.1"
    allow_hosts: tuple[str, ...] = ()
    open_read_hosts: tuple[str, ...] = ()       # 이 이름으로 들어온 읽기는 로그인 없이 연다(기본 없음)
    token_path: pathlib.Path = PRIVATE_OPS / "token"
    log_path: pathlib.Path = PRIVATE_OPS / "access.log"
    preview_dir: pathlib.Path | None = paths.ROOT / "private" / "out" / "web_preview"
    pulse_out: pathlib.Path = pulse_snapshot.OUT
    pulse_db: pathlib.Path = pulse_store.DB
    approver: str = "사용자"
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))


class Ctx:
    """처리기가 받는 것: 요청 처리기 h, 서버 설정, 질의."""

    def __init__(self, h: "Handler", query: dict[str, str]) -> None:
        self.h, self.query = h, query
        self.srv: OpsServer = h.server  # type: ignore[assignment]
        self.cfg = self.srv.cfg

    def session(self) -> tuple[bytes, str] | None:
        return auth.session_of(self.h.headers, self.cfg.token_path, self.srv.sessions)

    def csrf(self) -> str | None:
        s = self.session()
        return auth.csrf_for(*s) if s else None

    def note(self) -> str | None:
        m = self.query.get("m", "")
        return MESSAGES.get(int(m)) if re.fullmatch(r"[0-9]{1,3}", m) else None


GET_ROUTES: dict[str, Callable[[Ctx], None]] = {}
POST_ROUTES: dict[str, tuple[str, Callable[[Ctx, auth.WriteOK], None]]] = {}


def register_get(path: str, fn: Callable[[Ctx], None]) -> None:
    GET_ROUTES[path] = fn


def register_post(path: str, fn: Callable[[Ctx, auth.WriteOK], None], kind: str = "session") -> None:
    """kind: "session"(세션 쿠키 + 요청 토큰) 또는 "login"(pre 칸)."""
    POST_ROUTES[path] = (kind, fn)


# ---------- 응답 ----------

def send(h: "Handler", code: int, body: bytes, ctype: str, headers: dict | None = None, cookies=()) -> None:
    h.send_response(code)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(body)))
    base = {"Cache-Control": "no-store", "Content-Security-Policy": OPS_CSP, "X-Frame-Options": "DENY",
            "Cross-Origin-Opener-Policy": "same-origin", "Referrer-Policy": REFERRER, "X-Content-Type-Options": "nosniff"}
    base.update(headers or {})
    for k, v in base.items():
        h.send_header(k, v)
    for c in cookies:
        h.send_header("Set-Cookie", c)
    h.end_headers()
    if h.command != "HEAD":
        h.wfile.write(body)
    h.status_sent = code


def html(h, code: int, text: str, cookies=()) -> None:
    send(h, code, text.encode("utf-8"), "text/html; charset=utf-8", cookies=cookies)


def redirect(h, location: str, code: int = 303, cookies=()) -> None:
    h.send_response(code)
    h.send_header("Location", location)
    h.send_header("Content-Length", "0")
    for k, v in (("Cache-Control", "no-store"), ("Content-Security-Policy", OPS_CSP), ("Referrer-Policy", REFERRER),
                 ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY")):
        h.send_header(k, v)
    for c in cookies:
        h.send_header("Set-Cookie", c)
    h.end_headers()
    h.status_sent = code


def fail(h, code: int, msg: str, back: str = "/ops") -> None:
    html(h, code, templates.error_page(code, msg, back))


# ---------- 화면 처리기 ----------

def h_css(c: Ctx) -> None:
    send(c.h, 200, (STATIC / "ops.css").read_bytes(), "text/css; charset=utf-8", {"Cache-Control": "no-cache"})


def _pending_count() -> int | None:
    """게시 승인 화면에 오른 수(게시 대기 이슈 가운데 지금 내용으로 승인되지 않은 것 + 그날의 화제·복원판)."""
    try:
        v = approvals.build_view()
    except Exception:  # noqa: BLE001 — 첫 화면은 수를 못 세도 열린다
        return None
    return None if v.error else v.n_pending


def h_ops(c: Ctx) -> None:
    v = candidates.build_view(c.cfg.clock(), c.cfg.pulse_out)
    n_cand = None if v.src.error else v.n_candidates()
    n_queue = sum(1 for j in v.queue_items if j.get("state") in queue.ACTIVE)
    csrf = c.csrf()
    has_prev = bool(c.srv.preview_base and c.srv.preview_base.is_dir())
    html(c.h, 200, templates.ops_page(logged_in=csrf is not None, n_cand=n_cand, n_pending=_pending_count(),
                                      n_queue=n_queue, has_preview=has_prev, csrf=csrf, note=c.note()))


def h_login_get(c: Ctx) -> None:
    pre = secrets.token_urlsafe(32)
    html(c.h, 200, templates.login_page(pre, auth.safe_next(c.query.get("next")), c.note()),
         cookies=[auth.pre_cookie_header(pre)])


def h_pick(c: Ctx) -> None:
    v = candidates.build_view(c.cfg.clock(), c.cfg.pulse_out)
    html(c.h, 200, templates.pick_page(v, c.csrf(), c.note()))


def h_login_post(c: Ctx, ok: auth.WriteOK) -> None:
    lim = c.srv.limiter
    locked = lim.blocked()
    try:
        tok = auth.read_token(c.cfg.token_path)
    except (OSError, RuntimeError):
        return fail(c.h, 503, "서버 설정이 끝나지 않았다.")
    if locked:                       # 잠긴 동안에도 맞는 토큰은 받되 느리게(auth.FailLimiter 설명)
        time.sleep(auth.LOCKED_DELAY)
    if not auth.token_matches(tok, ok.form.get("token", "")):
        lim.fail()
        if locked:
            return fail(c.h, 429, "로그인을 여러 번 틀렸다. 10분 뒤에 다시 해 주세요.", "/login")
        return fail(c.h, 401, "토큰이 맞지 않는다.", "/login")
    key = auth.session_key(tok)
    value = auth.make_session(key)
    c.srv.sessions.add(value.split(".")[1])
    redirect(c.h, auth.safe_next(ok.form.get("next")) + "?m=10",
             cookies=[auth.session_cookie_header(value), "ozl_pre=; HttpOnly; SameSite=Strict; Path=/login; Max-Age=0"])


def h_logout(c: Ctx, ok: auth.WriteOK) -> None:
    c.srv.sessions.drop(ok.rnd)      # 서버 쪽에서 끝낸다. 다른 곳에 남은 같은 쿠키도 더는 받지 않는다
    redirect(c.h, "/ops?m=11", cookies=[auth.clear_session_header()])


def _pick_action(name: str):
    def fn(c: Ctx, ok: auth.WriteOK) -> None:
        try:
            out = actions.run(name, ok.form, now=c.cfg.clock(), out_dir=c.cfg.pulse_out, index=c.srv.index)
        except actions.BadForm:
            return fail(c.h, 400, "요청 모양이 맞지 않는다.", "/pick")
        except actions.Conflict:
            return fail(c.h, 409, "이미 다른 내용으로 처리했거나, 지금 바꿀 수 없는 상태다.", "/pick")
        redirect(c.h, f"/pick?m={out.m}")
    return fn


def h_approve(c: Ctx) -> None:
    html(c.h, 200, approve_view.approve_page(approvals.build_view(), c.csrf(), c.note()))


def h_approve_post(c: Ctx, ok: auth.WriteOK) -> None:
    try:
        r = approvals.handle(ok.form, now=c.cfg.clock(), index=c.srv.index, approver=c.cfg.approver)
    except actions.BadForm:
        return fail(c.h, 400, "요청 모양이 맞지 않는다.", "/approve")
    except actions.Conflict:
        return fail(c.h, 409, "같은 요청 번호로 다른 내용을 이미 보냈다. 화면을 새로 열고 다시 승인한다.", "/approve")
    if r.http == 303:
        return redirect(c.h, f"/approve?m={r.m}")
    html(c.h, r.http, approve_view.refused_page(r.http, r.lines))


def host_name(host: str | None) -> str | None:
    """Host 머리의 이름 부분(포트 뺌, 소문자). 꼴이 틀리면 None."""
    m = auth.HOST_RE.fullmatch(host or "")
    return m.group(1).lower() if m else None


def read_open(host: str | None, open_hosts: frozenset[str]) -> bool:
    """로그인 없이 읽어도 되는 Host 인가: 이 기기 주소, 또는 server.json 의 open_read_hosts 에 적힌 이름."""
    name = host_name(host)
    return name is not None and (name in LOCAL_NAMES or name in open_hosts)


def login_redirect(h, path: str) -> None:
    nxt = auth.safe_next(path)               # /preview/… 나 그 밖은 /ops 로 돌아온다
    redirect(h, "/login?next=" + urllib.parse.quote(nxt, safe="/"))


def h_preview(c: Ctx, path: str) -> None:
    host = c.h.headers.get("Host", "")
    r = preview.serve(c.srv.preview_base, path, host)
    if r.code == 503:
        return html(c.h, 503, templates.preview_missing(preview.BUILD_CMD))
    send(c.h, r.code, r.body, r.ctype, r.headers)


register_get("/ops", h_ops)
register_get("/ops/static/ops.css", h_css)
register_get("/login", h_login_get)
register_get("/pick", h_pick)
register_get("/approve", h_approve)
register_post("/login", h_login_post, kind="login")
register_post("/logout", h_logout)
register_post("/approve", h_approve_post)
for _a in ("make", "later", "discard", "restore", "keyword", "cancel"):
    register_post(f"/pick/{_a}", _pick_action(_a))


# ---------- 요청 처리기 ----------

class Handler(BaseHTTPRequestHandler):
    timeout = 15                     # 소켓 시간 제한(초). 본문을 다 보내지 않는 연결이 스레드를 붙잡지 못하게
    server_version = "ozl-ops"
    sys_version = ""
    status_sent: int | None = None

    def log_message(self, fmt, *args):   # 기본 로그(원격 주소·요청 줄)를 쓰지 않는다
        pass

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    do_DELETE = do_PATCH = do_PUT

    def _dispatch(self, method: str) -> None:
        t0 = time.monotonic()
        self.status_sent = None
        path, _, query = self.path.partition("?")
        try:
            self._route(method, path, query)
        except (ConnectionError, TimeoutError):
            self.close_connection = True      # 본문을 느리게 보내는 연결은 답 없이 끊는다(Handler.timeout)
        except (queue.QueueBroken, RuntimeError) as e:
            msg = str(e) if isinstance(e, queue.QueueBroken) or e.args and e.args[0] == store.ALIAS_MSG else None
            if msg is None:
                self._fail500(e)
            else:
                try:
                    fail(self, 503, msg)
                except (ConnectionError, TimeoutError):
                    pass
        except Exception as e:  # noqa: BLE001 — 예외 이름만. 요청·본문·머리를 찍지 않는다
            self._fail500(e)
        finally:
            self.server.access_log(method, path, self.status_sent or 0, (time.monotonic() - t0) * 1000)  # type: ignore[attr-defined]

    def _fail500(self, e: BaseException) -> None:
        self.server.last_error = type(e).__name__  # type: ignore[attr-defined]
        try:
            fail(self, 500, "서버에서 처리하지 못했다.")
        except (ConnectionError, TimeoutError):
            pass

    def _route(self, method: str, path: str, query: str) -> None:
        srv: OpsServer = self.server  # type: ignore[assignment]
        host = self.headers.get("Host")
        if method in ("PUT", "DELETE", "PATCH"):
            return compat.read_only(self) if compat.is_compat(path) else fail(self, 405, "받지 않는 요청 방법이다.")
        if method == "POST":
            if compat.is_compat(path):
                return compat.read_only(self)
            if not auth.host_exact(host, srv.allow):
                return fail(self, 403, "허용하지 않은 주소로 들어온 요청이다.")
        elif not P.host_ok(host):
            return compat.host_refused(self) if compat.is_compat(path) else fail(self, 403, "허용하지 않은 주소로 들어온 요청이다.")
        if auth.query_forbidden(query):
            return fail(self, 400, "주소에 토큰을 싣지 않는다. 로그인 화면을 써 주세요.", "/login")
        if method in ("GET", "HEAD"):
            if compat.is_compat(path):
                return compat.get(self, path, srv.cfg)
            if not auth.host_shape_ok(host):
                return fail(self, 403, "허용하지 않은 주소로 들어온 요청이다.")
            q = {k: v[0] for k, v in urllib.parse.parse_qs(query, max_num_fields=20).items()} if query else {}
            c = Ctx(self, q)
            if path not in OPEN_READ and not read_open(host, srv.open_read) and c.session() is None:
                return login_redirect(self, path)
            if path == "/preview":
                return redirect(self, "/preview/", 301)
            if path.startswith(preview.PREFIX):
                return h_preview(c, path)
            if path in GET_ROUTES:
                return GET_ROUTES[path](c)
            if path in POST_ROUTES:
                return fail(self, 405, "받지 않는 요청 방법이다.")
            return fail(self, 404, "없는 쪽이다.")
        if path not in POST_ROUTES:
            known = path in GET_ROUTES or path == "/preview" or path.startswith(preview.PREFIX)
            return fail(self, 405, "받지 않는 요청 방법이다.") if known else fail(self, 404, "없는 쪽이다.")
        kind, fn = POST_ROUTES[path]
        try:
            ok = auth.check_write(self.headers, self.rfile, token_path=srv.cfg.token_path, allow=srv.allow,
                                  login=(kind == "login"), live=srv.sessions)
        except auth.Reject as r:
            return fail(self, r.code, r.msg, "/login" if kind == "login" else "/ops")
        return fn(Ctx(self, {}), ok)


class OpsServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, cfg: Config) -> None:
        if cfg.host not in BIND_OK:
            raise ValueError("127.0.0.1 이나 ::1 에만 묶는다")
        auth.read_token(cfg.token_path)       # 권한이 600 이 아니면 여기서 멈춘다
        store.require_safe_root()             # 실제 자료 루트를 다른 철자·링크로 가리키면 띄우지 않는다
        self.address_family = socket.AF_INET6 if cfg.host == "::1" else socket.AF_INET
        super().__init__((cfg.host, cfg.port), Handler)
        self.cfg = cfg
        self.allow = auth.allowed_hosts(self.server_address[1], cfg.allow_hosts)
        self.open_read = frozenset(h.strip().lower().rstrip(".") for h in cfg.open_read_hosts if h.strip())
        self.preview_base = cfg.preview_dir.resolve() if cfg.preview_dir else None
        self.index = store.RequestIndex()
        self.limiter = auth.FailLimiter()
        self.sessions = auth.SessionTable()
        self.last_error: str | None = None
        self._log_lock = threading.Lock()

    def access_log(self, method: str, path: str, status: int, ms: float) -> None:
        p = self.cfg.log_path
        safe = "".join(ch if ch.isprintable() and ch != " " else "_" for ch in path[:200])
        line = f"{store.iso()} {method} {safe} {status} {ms:.0f}\n"
        try:
            with self._log_lock:
                store.ensure_dir(p.parent)
                if p.exists() and p.stat().st_size > LOG_MAX:
                    p.replace(p.with_name(p.name + ".1"))
                with open(p, "a", encoding="utf-8") as f:
                    f.write(line)
        except OSError:
            pass

    def handle_error(self, request, client_address):   # 기본은 원격 주소와 스택을 찍는다
        pass


def make_server(cfg: Config) -> OpsServer:
    return OpsServer(cfg)
