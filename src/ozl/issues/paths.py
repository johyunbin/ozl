"""자료 루트와 경로, 파일 잠금, 원자적 쓰기.

자료 루트는 가져올 때 한 번 정하지 않고 부를 때마다 읽는다(`desk_root()`). 시험은 환경 변수 OZL_DESK_ROOT 로 바꾸고,
이 모듈을 쓰는 코드가 경로를 상수로 박으면 시험이 실제 private/desk 에 쓰게 된다.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
ENV = "OZL_DESK_ROOT"


def real_root() -> pathlib.Path:
    return ROOT / "private" / "desk"


def desk_root() -> pathlib.Path:
    v = os.environ.get(ENV, "").strip()
    return pathlib.Path(v) if v else real_root()


def is_real_root() -> bool:
    return desk_root().resolve() == real_root().resolve()


def issues_dir() -> pathlib.Path:
    return desk_root() / "issues"


def issue_dir(issue_id: str) -> pathlib.Path:
    return issues_dir() / issue_id


def issue_file(issue_id: str) -> pathlib.Path:
    return issue_dir(issue_id) / "issue.yaml"


def evidence_dir(issue_id: str) -> pathlib.Path:
    return issue_dir(issue_id) / "evidence"


def evidence_file(issue_id: str, evidence_id: str) -> pathlib.Path:
    return evidence_dir(issue_id) / f"{evidence_id}.yaml"


def captures_dir(issue_id: str) -> pathlib.Path:
    return issue_dir(issue_id) / "captures"


def ledger_file() -> pathlib.Path:
    return issues_dir() / "issued_ids.json"


def manifest_file() -> pathlib.Path:
    return issues_dir() / "manifest.json"


def lock_file() -> pathlib.Path:
    return issues_dir() / ".lock"


@contextlib.contextmanager
def lock():
    """대장과 발행 목록을 고치는 동안 거는 잠금(fcntl.flock). 같은 프로세스 안에서 겹쳐 부르지 않는다."""
    p = lock_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def write_atomic(path: pathlib.Path, text: str) -> None:
    """같은 폴더의 임시 파일에 다 쓴 뒤 os.replace 로 바꾼다. 쓰다 멈춰도 원래 파일은 그대로다."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def rel_or_abs(p) -> str:
    """기록에 적는 경로: 저장소 루트 아래면 상대 경로, 밖(시험의 임시 폴더)이면 절대 경로. cards._resolve 가 둘 다 푼다."""
    q = pathlib.Path(p).resolve()
    try:
        return str(q.relative_to(ROOT.resolve()))
    except ValueError:
        return str(q)
