"""완성 절차 진행 기록 — 통과한 카드 한 장을 완성본까지 만드는 동안의 상태를 한 파일에 남긴다.

    python -m ozl.render progress <card_id>                                   # 상태 보기
    python -m ozl.render progress <card_id> --start [--by 이름] [--force]    # 시작
    python -m ozl.render progress <card_id> --resume [--by 이름]             # 끊긴 진행을 이어 받기
    python -m ozl.render progress <card_id> --mark <단계> [--note 글] [--spec 사양.yaml]
    python -m ozl.render progress <card_id> --done --final <완성본 폴더> [--note 글]
    python -m ozl.render progress <card_id> --abandon [--note 사유]

자리 = private/desk/builds/<card_id>/state.yaml(비공개 백업 대상). 단계마다 카드·기록 지문(cards.content_digest)과,
사양을 주면 그 sha256 을 남긴다 — 이어 할 때 마지막 단계 뒤에 카드나 기록이 바뀌었으면 알린다.

- 같은 카드를 두 번 만들지 않는다: 진행 중(만료 전)이면 --start 를 거부하고 --resume 을 안내한다. 완성본이 이미 있으면
  --start 를 거부한다(--force 로만 다시 시작).
- '진행 중'은 세션이 죽으면 남는다 → 마지막 기록 뒤 LEASE_HOURS 가 지나면 만료로 보고 --start 를 받는다.
- 덱 빌드(`python -m ozl.render build`)는 한 편에 여러 번 부르므로 막지 않는다 — 진행 기록은 절차 단위의 상태다.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import yaml

from ozl.research import cards as C

KST = timezone(timedelta(hours=9))
LEASE_HOURS = 6
STEPS = ("명제", "원문", "기록", "재대조", "등급", "사양", "검토", "빌드", "게이트", "재확인", "산출")
IN_PROGRESS, DONE, ABANDONED = "진행 중", "완성", "접음"


def now() -> datetime:
    return datetime.now(KST)


def state_path(card_id: str) -> pathlib.Path:
    if not C.CARD_ID.match(str(card_id)):
        raise ValueError(f"카드 ID 형식 오류: {card_id!r}")
    return C.DESK / "builds" / str(card_id) / "state.yaml"


def load(card_id: str) -> dict:
    p = state_path(card_id)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def save(card_id: str, st: dict) -> pathlib.Path:
    """호출마다 고유한 임시 파일에 다 쓴 뒤 바꿔 끼운다 — 중간에 멈춰도 반쯤 쓴 기록이 남지 않고, 동시에 저장해도 임시 파일이 겹치지 않는다."""
    p = state_path(card_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml.safe_dump(st, allow_unicode=True, sort_keys=False, width=1000))
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    return p


@contextlib.contextmanager
def _locked(card_id: str):
    """카드별 잠금 — 읽기 → 판정 → 저장을 한 덩어리로(두 세션이 같은 카드를 동시에 시작하거나 단계를 적어도 덮어쓰지 않게)."""
    lock = state_path(card_id).with_name("state.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def run_steps(st: dict) -> list[dict]:
    """지금 작업 회차의 단계 — 마지막 '다시 시작' 뒤의 것만(이전 회차의 완료 단계를 새 작업의 완료로 세지 않는다)."""
    steps = list(st.get("steps") or [])
    cut = max((i for i, s in enumerate(steps) if s.get("step") == "다시 시작"), default=-1)
    return [s for s in steps[cut + 1:] if s.get("step") in STEPS]


def digest(card_id: str) -> str:
    """지금 카드·기록의 지문. 카드가 없으면 빈 문자열."""
    if not C.card_path(card_id).exists():
        return ""
    return C.content_digest(C.load_card(card_id), C.claims_for(card_id))


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def lease_alive(st: dict, at: datetime | None = None) -> bool:
    if st.get("status") != IN_PROGRESS or not st.get("lease_until"):
        return False
    try:
        return datetime.fromisoformat(str(st["lease_until"])) > (at or now())
    except ValueError:
        return False


def _renew(st: dict, at: datetime) -> None:
    st["updated_at"] = _iso(at)
    st["lease_until"] = _iso(at + timedelta(hours=LEASE_HOURS))


def start(card_id: str, by: str = "", force: bool = False, at: datetime | None = None) -> dict:
    at = at or now()
    if not C.card_path(card_id).exists():
        raise ValueError(f"카드 {card_id} 가 없다")
    with _locked(card_id):
        st = load(card_id)
        if lease_alive(st, at):
            raise ValueError(f"{card_id} 는 진행 중이다({st.get('by', '')} · {st['lease_until']} 까지) — 이어 받으려면 --resume")
        if st.get("status") == DONE and not force:
            raise ValueError(f"{card_id} 는 이미 완성본이 있다({st.get('final', '')}) — 다시 만들려면 --force")
        prev = st.get("status", "")
        st = {"card_id": card_id, "status": IN_PROGRESS, "by": by, "started_at": _iso(at), "steps": list(st.get("steps") or []),
              "final": st.get("final", "") if prev == DONE else ""}
        if prev:
            st["steps"].append({"step": "다시 시작", "at": _iso(at), "note": f"이전 상태: {prev}", "digest": digest(card_id)})
        _renew(st, at)
        save(card_id, st)
        return st


def resume(card_id: str, by: str = "", at: datetime | None = None) -> tuple[dict, str]:
    """진행 중 기록을 이어 받는다(만료돼도 받는다). 돌려주는 글 = 마지막 단계와, 그 뒤에 카드·기록이 바뀌었는지."""
    at = at or now()
    with _locked(card_id):
        st = load(card_id)
        if st.get("status") != IN_PROGRESS:
            raise ValueError(f"{card_id} 는 진행 중이 아니다(상태: {st.get('status') or '기록 없음'}) — --start")
        st["by"] = by or st.get("by", "")
        _renew(st, at)
        save(card_id, st)
    return st, summary(st, card_id)


def _mark_unlocked(card_id: str, step: str, note: str, spec: str | None, at: datetime) -> dict:
    if step not in STEPS:
        raise ValueError(f"단계 이름은 {', '.join(STEPS)} 가운데 하나다: {step!r}")
    st = load(card_id)
    if st.get("status") != IN_PROGRESS:
        raise ValueError(f"{card_id} 는 진행 중이 아니다 — --start 먼저")
    rec = {"step": step, "at": _iso(at), "note": note, "digest": digest(card_id)}
    if spec:
        sp = pathlib.Path(spec)
        if not sp.is_file():
            raise ValueError(f"사양 파일이 없다: {spec}")
        rec["spec"] = sp.name
        rec["spec_sha256"] = hashlib.sha256(sp.read_bytes()).hexdigest()
    st.setdefault("steps", []).append(rec)
    _renew(st, at)
    return st


def mark(card_id: str, step: str, note: str = "", spec: str | None = None, at: datetime | None = None) -> dict:
    with _locked(card_id):
        st = _mark_unlocked(card_id, step, note, spec, at or now())
        save(card_id, st)
        return st


def done(card_id: str, final: str, note: str = "", at: datetime | None = None) -> dict:
    if not pathlib.Path(final).is_dir():
        raise ValueError(f"완성본 폴더가 없다: {final}")
    with _locked(card_id):   # 단계 기록과 상태 바꿈을 한 번에 저장한다
        st = _mark_unlocked(card_id, "산출", note or "완성본", None, at or now())
        st.update({"status": DONE, "final": str(final), "lease_until": ""})
        save(card_id, st)
        return st


def abandon(card_id: str, note: str = "", at: datetime | None = None) -> dict:
    at = at or now()
    with _locked(card_id):
        st = load(card_id)
        if not st:
            raise ValueError(f"{card_id} 의 진행 기록이 없다")
        st.setdefault("steps", []).append({"step": "접음", "at": _iso(at), "note": note, "digest": digest(card_id)})
        st.update({"status": ABANDONED, "lease_until": "", "updated_at": _iso(at)})
        save(card_id, st)
        return st


def summary(st: dict, card_id: str) -> str:
    if not st:
        return f"{card_id}: 진행 기록 없음"
    steps = run_steps(st)
    last = steps[-1] if steps else None
    lines = [f"{card_id}: {st.get('status', '')}" + (f" · {st.get('by')}" if st.get("by") else "")
             + (f" · 만료 {st['lease_until']}" if st.get("lease_until") else "") + (f" · 완성본 {st['final']}" if st.get("final") else "")]
    if last:
        lines.append(f"마지막 단계: {last['step']} ({last['at']})" + (f" — {last['note']}" if last.get("note") else ""))
        now_d = digest(card_id)
        if last.get("digest") and now_d and last["digest"] != now_d:
            lines.append("주의: 마지막 단계 뒤에 카드나 기록이 바뀌었다 — 바뀐 기록이 걸린 단계부터 다시 한다")
    passed = [s["step"] for s in steps]
    rest = [s for s in STEPS if s not in passed]
    if st.get("status") == IN_PROGRESS and rest:
        lines.append("남은 단계: " + " → ".join(rest))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="ozl.render progress")
    ap.add_argument("card_id")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--start", action="store_true")
    g.add_argument("--resume", action="store_true")
    g.add_argument("--mark", choices=STEPS)
    g.add_argument("--done", action="store_true")
    g.add_argument("--abandon", action="store_true")
    ap.add_argument("--by", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--spec")
    ap.add_argument("--final")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.start:
            st = start(a.card_id, a.by, a.force)
        elif a.resume:
            st, text = resume(a.card_id, a.by)
            print(text)
            return 0
        elif a.mark:
            st = mark(a.card_id, a.mark, a.note, a.spec)
        elif a.done:
            if not a.final:
                raise ValueError("--done 에는 --final <완성본 폴더> 가 있어야 한다")
            st = done(a.card_id, a.final, a.note)
        elif a.abandon:
            st = abandon(a.card_id, a.note)
        else:
            st = load(a.card_id)
    except ValueError as e:
        print(f"[progress] {e}", file=sys.stderr)
        return 1
    print(summary(st, a.card_id))
    return 0
