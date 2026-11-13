"""운영 자료 파일 — 폴더, 잠금, JSON 원자적 쓰기, jsonl 덧붙이기, 요청 번호 색인(설계 2절).

자료 루트는 부를 때마다 `paths.desk_root()` 로 읽는다. 모듈 수준 상수로 박지 않는다(시험이 실제 private/desk 에 쓰지 않게).
잠금 순서는 늘 "운영 잠금 → 이슈 잠금"이다.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import threading
from datetime import datetime, timedelta, timezone

from ozl.issues import paths

KST = timezone(timedelta(hours=9))


def ops_dir() -> pathlib.Path:
    return paths.desk_root() / "ops"


ALIAS_MSG = ("자료 루트가 실제 자료 루트(private/desk)와 같은 폴더를 다른 철자나 링크로 가리킨다. "
             "실제 자료 루트는 OZL_DESK_ROOT 없이, 시험은 다른 폴더로 준다.")


def root_alias() -> bool:
    """시험 루트로 보이는데 실제 자료 루트와 같은 폴더인가(대소문자만 다른 경로, 심볼릭 링크).

    `paths.is_real_root()` 는 resolve() 한 문자열을 비교한다. APFS 는 대소문자를 가리지 않고 resolve() 는 대소문자를
    바로잡지 않으므로 `private/DESK` 가 시험 루트로 판정된다. 여기서는 파일 시스템의 같은 파일인지(samefile)로 본다.
    """
    if paths.is_real_root():
        return False
    real = paths.real_root()
    for a, b in ((paths.desk_root(), real), (paths.issues_dir(), real / "issues"), (ops_dir(), real / "ops")):
        try:
            if os.path.samefile(a, b):
                return True
        except OSError:
            continue
    return False


def require_safe_root() -> None:
    """자료 루트가 실제 자료 루트의 별칭이면 RuntimeError. 쓰기 전과 서버 시작 때 부른다."""
    if root_alias():
        raise RuntimeError(ALIAS_MSG)


def ensure_dir(p: pathlib.Path) -> pathlib.Path:
    p.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(p, 0o700)
    return p


def ops_file(name: str) -> pathlib.Path:
    return ops_dir() / name


_THREAD_LOCK = threading.RLock()


@contextlib.contextmanager
def ops_lock():
    """운영 JSON 을 고치는 동안 거는 잠금. 프로세스 사이는 fcntl, 같은 프로세스의 스레드 사이는 RLock.

    자료 루트가 실제 자료 루트의 별칭이면 폴더를 만들기 전에 멈춘다(`require_safe_root`).
    """
    require_safe_root()
    d = ensure_dir(ops_dir())
    with _THREAD_LOCK:
        with open(d / ".lock", "a+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def read_json(p: pathlib.Path, default: dict) -> dict:
    if not p.exists():
        return json.loads(json.dumps(default))
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(p: pathlib.Path, obj: dict) -> None:
    ensure_dir(p.parent)
    paths.write_atomic(p, json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
    with contextlib.suppress(OSError):
        os.chmod(p, 0o600)


def append_jsonl(p: pathlib.Path, obj: dict) -> None:
    """한 줄 덧붙이기. 고치거나 지우지 않는다."""
    ensure_dir(p.parent)
    line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_jsonl(p: pathlib.Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            with contextlib.suppress(ValueError):
                out.append(json.loads(line))
    return out


def now_kst(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(KST)


def iso(now: datetime | None = None) -> str:
    return now_kst(now).isoformat(timespec="seconds")


def fingerprint(fields: dict) -> str:
    """요청 지문 = 요청 번호를 뺀 동작 칸들의 sha256."""
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class RequestIndex:
    """{request_id: (지문, 답할 알림 번호)}. 운영 잠금 안에서만 읽고 고친다.

    자료 루트마다 따로 든다(시험 서버마다 루트가 다르다). 처음 쓸 때 actions.jsonl·approvals.jsonl 에서 채운다.
    """

    FILES = ("actions.jsonl", "approvals.jsonl")

    def __init__(self) -> None:
        self._by_root: dict[str, dict[str, tuple[str, int]]] = {}

    def _table(self) -> dict[str, tuple[str, int]]:
        key = str(ops_dir().resolve())
        t = self._by_root.get(key)
        if t is None:
            t = {}
            for name in self.FILES:
                for r in read_jsonl(ops_file(name)):
                    rid, fp = r.get("request_id"), r.get("fp")
                    if rid and fp and rid not in t:
                        t[rid] = (fp, int(r.get("m") or 0))
            self._by_root[key] = t
        return t

    def lookup(self, request_id: str) -> tuple[str, int] | None:
        return self._table().get(request_id)

    def remember(self, request_id: str, fp: str, m: int) -> None:
        self._table().setdefault(request_id, (fp, m))
