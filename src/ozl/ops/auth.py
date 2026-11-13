"""쓰기 요청 검사 — 토큰 파일, 로그인, 세션 쿠키, 요청 토큰, Host·Origin, 본문 크기·종류(설계 3절).

모든 POST 는 `check_write` 한 함수를 거친다(처리기마다 따로 검사하지 않는다). 검사 순서와 답은 설계 3절 표 그대로:
Host 403 → Origin·Sec-Fetch-Site 403 → 길이 411/413 → 종류 415 → 쿠키 401 → 요청 토큰 403 → 칸 모양 400.
비교는 전부 `hmac.compare_digest`. 토큰·쿠키·요청 토큰·본문은 어디에도 찍지 않는다.
"""
from __future__ import annotations

import collections
import hashlib
import hmac
import os
import pathlib
import re
import secrets
import stat
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie

SESSION_COOKIE = "ozl_ops"
PRE_COOKIE = "ozl_pre"
SESSION_AGE = 12 * 3600       # 반나절. 서버가 아는 세션 목록(SessionTable)에도 있어야 받는다
MAX_SESSIONS = 8
PRE_AGE = 600
MAX_BODY = 8 * 1024
MAX_FIELDS = 20
FORBIDDEN_QUERY = {"token", "t", "key", "csrf"}
LOGIN_NEXT = ("/pick", "/approve", "/ops")
FAIL_LIMIT = 5
FAIL_WINDOW = 600
HOST_RE = re.compile(r"(\[[0-9A-Fa-f:]+\]|[A-Za-z0-9.-]+)(:[0-9]{1,5})?")
REQUEST_ID = re.compile(r"[0-9a-f]{32}")


class Reject(Exception):
    """검사에 걸림. code 는 HTTP 상태, msg 는 사람이 읽는 한 문장(받은 값을 되비추지 않는다)."""

    def __init__(self, code: int, msg: str) -> None:
        super().__init__(code)
        self.code, self.msg = code, msg


# ---------- 토큰 파일 ----------

def token_ok_mode(p: pathlib.Path) -> bool:
    st = p.stat()
    return stat.S_IMODE(st.st_mode) == 0o600


def read_token(p: pathlib.Path) -> str:
    """권한이 600 이 아니거나 비었으면 거부한다."""
    if not p.exists():
        raise RuntimeError("토큰 파일이 없다 — python -m ozl.ops token 으로 만든다")
    if not token_ok_mode(p):
        raise RuntimeError("토큰 파일 권한이 600 이 아니다")
    tok = p.read_text(encoding="utf-8").strip()
    if len(tok) < 32:
        raise RuntimeError("토큰 파일이 비었거나 짧다")
    return tok


def write_token(p: pathlib.Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    tok = secrets.token_urlsafe(32)
    tmp = p.with_name(f".{p.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (tok + "\n").encode("ascii"))
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def session_key(token: str) -> bytes:
    return hashlib.sha256(("ozl-ops-session|" + token).encode("utf-8")).digest()


def token_matches(token: str, given: str) -> bool:
    """길이가 드러나지 않게 양쪽 sha256 다이제스트를 비교한다."""
    a = hashlib.sha256(token.encode("utf-8")).digest()
    b = hashlib.sha256((given or "").encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


# ---------- 세션 쿠키와 요청 토큰 ----------

def _sig(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session(key: bytes, now: float | None = None) -> str:
    ts = str(int(now if now is not None else time.time()))
    rnd = secrets.token_hex(16)
    return f"{ts}.{rnd}.{_sig(key, 's|' + ts + '|' + rnd)}"


def check_session(key: bytes, value: str | None, now: float | None = None) -> str | None:
    """맞으면 무작위 부분, 틀리거나 14일 지났으면 None."""
    if not value:
        return None
    parts = value.split(".")
    if len(parts) != 3 or not re.fullmatch(r"[0-9]{1,12}", parts[0]) or not re.fullmatch(r"[0-9a-f]{32}", parts[1]):
        return None
    ts, rnd, sig = parts
    if not hmac.compare_digest(_sig(key, "s|" + ts + "|" + rnd).encode("ascii"), sig.encode("ascii", "replace")):
        return None
    age = (now if now is not None else time.time()) - int(ts)
    if age < -300 or age > SESSION_AGE:
        return None
    return rnd


def csrf_for(key: bytes, rnd: str) -> str:
    return _sig(key, "c|" + rnd)


def read_cookie(header: str | None, name: str) -> str | None:
    if not header:
        return None
    c = SimpleCookie()
    try:
        c.load(header)
    except CookieError:
        return None
    m = c.get(name)
    return m.value if m else None


def session_cookie_header(value: str) -> str:
    return f"{SESSION_COOKIE}={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_AGE}"


def clear_session_header() -> str:
    return f"{SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"


def pre_cookie_header(value: str) -> str:
    return f"{PRE_COOKIE}={value}; HttpOnly; SameSite=Strict; Path=/login; Max-Age={PRE_AGE}"


# ---------- Host 와 Origin ----------

def host_shape_ok(host: str | None) -> bool:
    return bool(host) and HOST_RE.fullmatch(host) is not None


def allowed_hosts(port: int, extra=()) -> set[str]:
    base = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    for h in extra:
        h = h.strip().lower().rstrip(".")
        if h:
            base.add(f"{h}:{port}")
    return base


def host_exact(host: str | None, allow: set[str]) -> bool:
    return bool(host) and host.lower() in allow


def query_forbidden(query: str) -> bool:
    """질의 문자열에 토큰처럼 보이는 이름이 있는가(값은 보지 않는다)."""
    if not query:
        return False
    for part in re.split(r"[&;]", query):
        name = urllib.parse.unquote_plus(part.split("=", 1)[0]).strip().lower()
        if name in FORBIDDEN_QUERY:
            return True
    return False


# ---------- 로그인 실패 횟수 ----------

class FailLimiter:
    """10분에 5번까지 틀리면 잠긴다. 메모리에만 둔다.

    서버는 127.0.0.1 에만 묶이고 tailnet 요청도 같은 기기의 프록시를 거쳐 오므로 원격 주소로 나눌 수 없다.
    그래서 잠긴 동안에도 맞는 토큰은 받는다(느리게 — LOCKED_DELAY 초). 틀린 토큰만 429 로 막는다.
    누구든 틀린 토큰을 다섯 번 보내 주인을 막는 길을 없애고, 막힌 동안의 추측은 느리게 한다(토큰은 256비트 무작위).
    """

    def __init__(self, limit: int = FAIL_LIMIT, window: float = FAIL_WINDOW) -> None:
        self.limit, self.window = limit, window
        self._t: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    def _trim(self, now: float) -> None:
        while self._t and self._t[0] <= now - self.window:
            self._t.popleft()

    def blocked(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            self._trim(now)
            return len(self._t) >= self.limit

    def fail(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._trim(now)
            self._t.append(now)
            while len(self._t) > self.limit * 4:      # 메모리가 끝없이 늘지 않게
                self._t.popleft()


LOCKED_DELAY = 2.0


# ---------- 서버가 아는 세션 ----------

class SessionTable:
    """서버가 발급한 세션의 무작위 부분. 로그아웃하면 지우고, 서버를 다시 띄우면 비어 모든 세션이 끝난다.

    쿠키는 포트로 격리되지 않아 같은 호스트의 다른 포트 서비스가 받아 갈 수 있다. 서명만 보면 수명 내내 재사용되므로
    서버 쪽 목록에 있어야만 받는다. 가장 오래된 것부터 MAX_SESSIONS 개를 넘으면 버린다.
    """

    def __init__(self, cap: int = MAX_SESSIONS) -> None:
        self.cap = cap
        self._live: collections.OrderedDict[str, None] = collections.OrderedDict()
        self._lock = threading.Lock()

    def add(self, rnd: str) -> None:
        with self._lock:
            self._live[rnd] = None
            while len(self._live) > self.cap:
                self._live.popitem(last=False)

    def drop(self, rnd: str | None) -> None:
        with self._lock:
            if rnd:
                self._live.pop(rnd, None)

    def has(self, rnd: str | None) -> bool:
        with self._lock:
            return bool(rnd) and rnd in self._live


# ---------- 한 곳에서 하는 쓰기 검사 ----------

@dataclass
class WriteOK:
    form: dict[str, str]
    key: bytes
    rnd: str | None = None             # 세션 무작위 부분(로그인 요청은 None)
    extra: dict = field(default_factory=dict)


def _parse_body(raw: bytes) -> tuple[dict[str, str], bool]:
    """(한 번만 나온 칸들, 모양이 맞는가). 겹친 칸이 있으면 모양이 틀리지만 요청 토큰은 그대로 찾을 수 있다."""
    try:
        text = raw.decode("utf-8")
        q = urllib.parse.parse_qs(text, keep_blank_values=True, strict_parsing=bool(text), max_num_fields=MAX_FIELDS)
    except (UnicodeDecodeError, ValueError):
        return {}, False
    single = {k: v[0] for k, v in q.items() if len(v) == 1}
    return single, len(single) == len(q)


def check_write(headers, rfile, *, token_path: pathlib.Path, allow: set[str], login: bool = False,
                live: SessionTable | None = None) -> WriteOK:
    """POST 한 건의 검사. 통과하면 읽은 폼과 세션 정보를, 아니면 Reject 를 던진다.

    login=True 는 POST /login: 세션 쿠키 대신 `pre` 칸이 `ozl_pre` 쿠키와 같은지 본다(토큰 비교는 부르는 쪽).
    """
    if not host_exact(headers.get("Host"), allow):
        raise Reject(403, "허용하지 않은 주소로 들어온 요청이다")
    origin = headers.get("Origin")
    if not origin or not origin.lower().startswith("http://") or origin[len("http://"):].lower() not in allow:
        raise Reject(403, "다른 출처에서 온 요청은 받지 않는다")
    sfs = headers.get("Sec-Fetch-Site")
    if sfs is not None and sfs.strip().lower() != "same-origin":
        raise Reject(403, "다른 출처에서 온 요청은 받지 않는다")
    if headers.get("Transfer-Encoding"):
        raise Reject(411, "본문 길이가 없다")
    cl = headers.get("Content-Length")
    if cl is None or not re.fullmatch(r"[0-9]{1,6}", cl.strip()):   # isdigit() 는 '²' 같은 유니코드 숫자도 참
        raise Reject(411, "본문 길이가 없다")
    n = int(cl.strip())
    if n > MAX_BODY:
        raise Reject(413, "본문이 너무 크다")
    ctype = (headers.get("Content-Type") or "").split(";")
    if ctype[0].strip().lower() != "application/x-www-form-urlencoded" or any(
            p.strip().lower() not in ("charset=utf-8", "") for p in ctype[1:]):
        raise Reject(415, "폼으로 보낸 요청만 받는다")
    raw = rfile.read(n) if n else b""
    form, shape_ok = _parse_body(raw)
    try:
        key = session_key(read_token(token_path))
    except (OSError, RuntimeError) as e:
        raise Reject(503, "서버 설정이 끝나지 않았다") from e
    cookie_header = headers.get("Cookie")
    if login:
        pre_c = read_cookie(cookie_header, PRE_COOKIE)
        pre_f = form.get("pre", "")
        if not pre_c or not hmac.compare_digest(pre_c.encode("utf-8", "replace"), pre_f.encode("utf-8", "replace")):
            raise Reject(403, "로그인 화면을 다시 열어 주세요")
        if not shape_ok:
            raise Reject(400, "요청 모양이 맞지 않는다")
        return WriteOK(form=form, key=key)
    rnd = check_session(key, read_cookie(cookie_header, SESSION_COOKIE))
    if rnd is None or (live is not None and not live.has(rnd)):
        raise Reject(401, "로그인이 필요하다")
    given = form.get("csrf") or headers.get("X-OZL-CSRF") or ""
    if not hmac.compare_digest(csrf_for(key, rnd).encode("ascii"), given.encode("utf-8", "replace")):
        raise Reject(403, "화면을 새로 열고 다시 눌러 주세요")
    if not shape_ok:
        raise Reject(400, "요청 모양이 맞지 않는다")
    return WriteOK(form=form, key=key, rnd=rnd)


def session_of(headers, token_path: pathlib.Path, live: SessionTable | None = None) -> tuple[bytes, str] | None:
    """GET 화면용: 로그인했으면 (세션 키, 무작위 부분). 폼에 요청 토큰을 심을 때 쓴다."""
    try:
        key = session_key(read_token(token_path))
    except (OSError, RuntimeError):
        return None
    rnd = check_session(key, read_cookie(headers.get("Cookie"), SESSION_COOKIE))
    if live is not None and not live.has(rnd):
        return None
    return (key, rnd) if rnd else None


def safe_next(v: str | None) -> str:
    return v if v in LOGIN_NEXT else "/ops"


def request_id_ok(v: str | None) -> bool:
    return bool(v) and REQUEST_ID.fullmatch(v) is not None
