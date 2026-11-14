"""완성 절차 진행 기록 — 통과한 카드 한 장을 완성본까지 만드는 동안의 상태를 한 파일에 남긴다.

    python -m ozl.render progress <card_id>                                   # 상태 보기
    python -m ozl.render progress <card_id> --start [--by 이름] [--force]    # 시작
    python -m ozl.render progress <card_id> --resume [--by 이름] [--force]   # 끊긴 진행을 이어 받기
    python -m ozl.render progress <card_id> --mark <단계> [--by 이름] [--note 글] [--spec 사양.yaml]
    python -m ozl.render progress <card_id> --done --final <완성본 폴더> [--by 이름] [--note 글] [--force]
    python -m ozl.render progress <card_id> --abandon [--by 이름] [--note 사유] [--force]

자리 = private/desk/builds/<card_id>/state.yaml(비공개 백업 대상). 단계마다 카드·기록 지문(cards.content_digest)과,
사양을 주면 그 sha256 을 남긴다 — 이어 할 때 마지막 단계 뒤에 카드나 기록이 바뀌었으면 알린다.

- 같은 카드를 두 번 만들지 않는다: 진행 중(만료 전)이면 --start 를 거부하고 --resume 을 안내한다. 완성본이 이미 있으면
  --start 를 거부한다(--force 로만 다시 시작).
- '진행 중'은 세션이 죽으면 남는다 → 마지막 기록 뒤 LEASE_HOURS 가 지나면 만료로 보고 --start 를 받는다.
- 임대가 살아 있는 동안 다른 이름(--by)으로는 이어 받기·단계 표시·완성을 받지 않는다(--force 로만). 만료된 기록에
  단계를 적으려면 먼저 --resume 한다 — 죽은 줄 알았던 세션과 새 세션이 같은 카드를 함께 고치지 않게(2026-11-13 점검).
- --done 은 산출 앞의 단계(명제 … 재확인)를 이번 회차에 모두 지났을 때만 받는다(--force 로만 예외).
- 덱 빌드(`python -m ozl.render build`)는 한 편에 여러 번 부르므로 막지 않는다 — 진행 기록은 절차 단위의 상태다.
- 판 상한(설계 5-7절): 검토는 3판(MAX_ROUNDS)까지다. '검토' 단계 기록에 큰 오류(major — 숫자 검사 실패, 근거 없는 사실 문장으로 기록된
  지적, 넘침이나 빈칸)를 남긴다. `--mark 검토 --spec 사양.yaml` 이면 그 사양을 엄격 모드로 검사한 실패를 큰 오류로 함께 적고(spec_major),
  문장 대조가 찾은 근거 없는 사실 문장은 `--major "글"`(여러 번)로 적는다. 판 = 이번 회차 '검토' 기록의 서로 다른 사양 sha256 수.
  3판째 검토 뒤에도 큰 오류가 남으면 상태가 '미완성'이 된다(임대를 풀고 '미완성' 단계를 남긴다). 큰 오류가 남은 동안 --done 은 거부한다.
  미완성에서 다시 하려면 --start --force. 옛 기록(major 칸 없음)은 큰 오류 없음으로 읽는다.
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
INCOMPLETE = "미완성"
MAX_ROUNDS = 3                 # 검토 판 상한
ROUND_STEP = "검토"            # 판을 세는 단계
MAJOR_STEPS = ("검토", "게이트")  # 큰 오류(major)를 남기는 단계


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
def _locked(card_id: str, create: bool = False):
    """카드별 잠금 — 읽기 → 판정 → 저장을 한 덩어리로(두 세션이 같은 카드를 동시에 시작하거나 단계를 적어도 덮어쓰지 않게).
    create=False(시작 말고 모든 호출)이면 진행 기록 폴더가 없을 때 잠금 파일과 폴더를 만들지 않고 거부한다
    (2026-11-14: 거부로 끝나는 --resume 이 빈 builds/<card_id>/state.lock 을 남겼다)."""
    lock = state_path(card_id).with_name("state.lock")
    if not create and not lock.parent.is_dir():
        raise ValueError(f"{card_id} 는 진행 중이 아니다(상태: 기록 없음) — --start")
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
    with _locked(card_id, create=True):
        st = load(card_id)
        if lease_alive(st, at):
            raise ValueError(f"{card_id} 는 진행 중이다({st.get('by', '')} · {st['lease_until']} 까지) — 이어 받으려면 --resume")
        if st.get("status") == DONE and not force:
            raise ValueError(f"{card_id} 는 이미 완성본이 있다({st.get('final', '')}) — 다시 만들려면 --force")
        if st.get("status") == INCOMPLETE and not force:
            raise ValueError(f"{card_id} 는 {MAX_ROUNDS}판 검토 뒤에도 큰 오류가 남아 미완성이다 — 다시 하려면 --force")
        prev = st.get("status", "")
        st = {"card_id": card_id, "status": IN_PROGRESS, "by": by, "started_at": _iso(at), "steps": list(st.get("steps") or []),
              "final": st.get("final", "") if prev == DONE else ""}
        if prev:
            st["steps"].append({"step": "다시 시작", "at": _iso(at), "note": f"이전 상태: {prev}", "digest": digest(card_id)})
        _renew(st, at)
        save(card_id, st)
        return st


def _holder_error(st: dict, by: str, at: datetime) -> str:
    """임대가 살아 있고 주인 이름이 있는데, 호출이 이름을 밝히지 않았거나 다른 이름이면 그 까닭(2026-11-13 Codex 지적:
    이름을 빼면 남의 임대를 고칠 수 있었다). 주인 이름이 없는 기록(이름 없이 시작한 것)은 막지 않는다."""
    if not (lease_alive(st, at) and st.get("by")):
        return ""
    if not by:
        return f"{st['by']} 가 진행 중이다({st['lease_until']} 까지) — 이름(--by)을 밝혀야 한다"
    if by != st["by"]:
        return f"{st['by']} 가 진행 중이다({st['lease_until']} 까지) — 다른 이름({by})으로는 받지 않는다(--force 로만)"
    return ""


def resume(card_id: str, by: str = "", at: datetime | None = None, force: bool = False) -> tuple[dict, str]:
    """진행 중 기록을 이어 받는다(만료돼도 받는다 · 살아 있는 남의 임대는 거부). 돌려주는 글 = 마지막 단계와, 그 뒤에 카드·기록이 바뀌었는지."""
    at = at or now()
    with _locked(card_id):
        st = load(card_id)
        if st.get("status") != IN_PROGRESS:
            raise ValueError(f"{card_id} 는 진행 중이 아니다(상태: {st.get('status') or '기록 없음'}) — --start")
        why = _holder_error(st, by, at)
        if why and not force:
            raise ValueError(f"{card_id}: {why}")
        st["by"] = by or st.get("by", "")
        _renew(st, at)
        save(card_id, st)
    return st, summary(st, card_id)


def rounds(st: dict) -> int:
    """이번 회차의 검토 판 수 — '검토' 기록의 서로 다른 사양 sha256 수(사양 없이 적은 검토는 한 판씩)."""
    shas, bare = set(), 0
    for s in run_steps(st):
        if s.get("step") == ROUND_STEP:
            if s.get("spec_sha256"):
                shas.add(s["spec_sha256"])
            else:
                bare += 1
    return len(shas) + bare


def major_left(st: dict) -> list[str]:
    """지금 남은 큰 오류 — 이번 회차에서 major 칸을 남긴 마지막 단계의 것. 옛 기록(칸 없음)은 빈 목록."""
    for s in reversed(run_steps(st)):
        if "major" in s:
            return [str(x) for x in s.get("major") or []]
    return []


def spec_major(spec_path: str) -> list[str]:
    """사양을 엄격 모드로 검사한 실패(숫자 검사 실패 · 넘침 · 빈칸 등) — 큰 오류로 적는다. 검사를 돌리지 못하면 그 사유 한 줄."""
    try:
        from ozl.render import build as B
        from ozl.render import pictures as PIC
        from ozl.render import spec as S
        sp, _ = PIC.drop_memes(S.load_spec(pathlib.Path(spec_path)))
        cid = str(sp.get("card_id") or "")
        card = C.load_card(cid) if C.CARD_ID.match(cid) and C.card_path(cid).exists() else None
        claims, staged = S.load_claims(S.cited_ids(sp))
        rep = S.check(sp, claims, S.load_template(), card, B.layout_problems, staged=staged, appendix_fn=B.appendix_problems)
        return [f"검사: {e}" for e in rep.errors]
    except Exception as e:  # noqa: BLE001 — 검사를 못 돌린 것도 큰 오류로 남긴다(통과로 치지 않는다)
        return [f"검사를 돌리지 못했다({type(e).__name__}): {e}"]


def _mark_unlocked(card_id: str, step: str, note: str, spec: str | None, at: datetime, by: str = "", force: bool = False,
                   major: list[str] | None = None) -> dict:
    if step not in STEPS:
        raise ValueError(f"단계 이름은 {', '.join(STEPS)} 가운데 하나다: {step!r}")
    st = load(card_id)
    if st.get("status") != IN_PROGRESS:
        raise ValueError(f"{card_id} 는 진행 중이 아니다 — --start 먼저")
    if not lease_alive(st, at):   # --force 로도 넘기지 않는다(만료된 기록은 이어 받기가 먼저)
        raise ValueError(f"{card_id} 의 임대가 만료됐다({st.get('lease_until', '')}) — --resume 으로 이어 받은 뒤 적는다")
    why = _holder_error(st, by, at)
    if why and not force:
        raise ValueError(f"{card_id}: {why}")
    rec = {"step": step, "at": _iso(at), "note": note, "digest": digest(card_id)}
    if spec:
        sp = pathlib.Path(spec)
        if not sp.is_file():
            raise ValueError(f"사양 파일이 없다: {spec}")
        rec["spec"] = sp.name
        rec["spec_sha256"] = hashlib.sha256(sp.read_bytes()).hexdigest()
    if step in MAJOR_STEPS and (spec or major is not None):
        rec["major"] = (spec_major(spec) if spec else []) + [str(x) for x in major or []]
    st.setdefault("steps", []).append(rec)
    _renew(st, at)
    n = rounds(st)
    left = major_left(st)
    if step == ROUND_STEP and n >= MAX_ROUNDS and left:
        st["steps"].append({"step": INCOMPLETE, "at": _iso(at), "note": f"{n}판 검토 뒤에도 큰 오류 {len(left)}건이 남았다(상한 {MAX_ROUNDS}판)",
                            "digest": rec["digest"]})
        st.update({"status": INCOMPLETE, "lease_until": "", "updated_at": _iso(at)})
    return st


def mark(card_id: str, step: str, note: str = "", spec: str | None = None, at: datetime | None = None, by: str = "",
         force: bool = False, major: list[str] | None = None) -> dict:
    """major = 이 단계가 찾은 큰 오류(검토 · 게이트). spec 을 주면 그 사양의 엄격 검사 실패를 더해 적는다."""
    with _locked(card_id):
        st = _mark_unlocked(card_id, step, note, spec, at or now(), by, force, major)
        save(card_id, st)
        return st


def done(card_id: str, final: str, note: str = "", at: datetime | None = None, by: str = "", force: bool = False) -> dict:
    if not pathlib.Path(final).is_dir():
        raise ValueError(f"완성본 폴더가 없다: {final}")
    with _locked(card_id):   # 단계 기록과 상태 바꿈을 한 번에 저장한다
        if not force:
            cur = load(card_id)
            passed = {s["step"] for s in run_steps(cur)}
            missing = [s for s in STEPS[:-1] if s not in passed]
            if missing:
                raise ValueError(f"{card_id}: 아직 지나지 않은 단계가 있다({' → '.join(missing)}) — 완성으로 적지 않는다(--force 로만)")
            left = major_left(cur)
            if left:
                raise ValueError(f"{card_id}: 큰 오류 {len(left)}건이 남았다(첫째: {left[0]}) — 완성으로 적지 않는다(--force 로만)")
        st = _mark_unlocked(card_id, "산출", note or "완성본", None, at or now(), by, force)
        st.update({"status": DONE, "final": str(final), "lease_until": ""})
        save(card_id, st)
        return st


def abandon(card_id: str, note: str = "", at: datetime | None = None, by: str = "", force: bool = False) -> dict:
    at = at or now()
    with _locked(card_id):
        st = load(card_id)
        if not st:
            raise ValueError(f"{card_id} 의 진행 기록이 없다")
        why = _holder_error(st, by, at)   # 살아 있는 남의 임대를 이름 없이·다른 이름으로 접지 못한다
        if why and not force:
            raise ValueError(f"{card_id}: {why}")
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
    n = rounds(st)
    left = major_left(st)
    if n or left:
        lines.append(f"검토 {n}판/{MAX_ROUNDS}판 · 남은 큰 오류 {len(left)}건" + (f" — {left[0]}" if left else ""))
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
    ap.add_argument("--major", action="append", default=None, help="검토·게이트가 찾은 큰 오류(여러 번). --spec 을 주면 그 사양의 엄격 검사 실패도 더해 적는다")
    a = ap.parse_args(argv)
    try:
        if a.start:
            st = start(a.card_id, a.by, a.force)
        elif a.resume:
            st, text = resume(a.card_id, a.by, force=a.force)
            print(text)
            return 0
        elif a.mark:
            st = mark(a.card_id, a.mark, a.note, a.spec, by=a.by, force=a.force, major=a.major)
        elif a.done:
            if not a.final:
                raise ValueError("--done 에는 --final <완성본 폴더> 가 있어야 한다")
            st = done(a.card_id, a.final, a.note, by=a.by, force=a.force)
        elif a.abandon:
            st = abandon(a.card_id, a.note, by=a.by, force=a.force)
        else:
            st = load(a.card_id)
    except ValueError as e:
        print(f"[progress] {e}", file=sys.stderr)
        return 1
    print(summary(st, a.card_id))
    return 0
