"""발행 목록(<자료 루트>/issues/manifest.json) 읽고 쓰기, 승인한 쪽 이름 규칙, 판 공개 판정의 공통 층, 멱등·요청 번호 규칙,
다른 이슈와 겹치는 주소 이름 — 이슈의 판(revisions)과 화제 목록·복원판(units)이 같이 쓴다. revisions 가 이 이름들을 다시 내보낸다."""
from __future__ import annotations

import json
import pathlib

from ozl.research import cards

from . import model, paths

TEST_BY = "시험"
EMPTY = {"schema": 1, "entries": [], "withdrawn": []}
MSG_TEST_IN_REAL = "시험 승인은 실제 발행 목록에 넣지 않는다"
MSG_REAL_IN_TEST = "시험 폴더에서는 승인한 쪽을 '시험'으로만 적는다"
MSG_TEST_NOT_PUBLIC = "시험 승인은 공개용 출력에 싣지 않는다"
MSG_ROOT_ALIAS = "자료 루트(OZL_DESK_ROOT)가 실제 자료 루트의 다른 이름이다(대소문자, 링크) — 승인하지 않는다"
MSG_SLUG_TAKEN = "주소 이름과 별칭은 다른 이슈와 겹치지 않는다"
MSG_WITHDRAWN = "내린 판은 다시 승인하지 않는다 — 판 번호를 올려 새 판으로 승인받는다"
MSG_REQUEST_ID = "같은 요청 번호(request_id)로 다른 대상·판·내용을 이미 승인했다"


# ── 발행 목록 ─────────────────────────────────────────────────────────
def load_manifest() -> dict:
    p = paths.manifest_file()
    if not p.exists():
        return json.loads(json.dumps(EMPTY))
    d = json.loads(p.read_text(encoding="utf-8"))
    if not (isinstance(d, dict) and d.get("schema") == 1 and isinstance(d.get("entries"), list) and isinstance(d.get("withdrawn"), list)):
        raise ValueError(f"발행 목록의 모양이 틀렸다: {p}")
    return d


def save_manifest(d: dict) -> None:
    paths.write_atomic(paths.manifest_file(), json.dumps(d, ensure_ascii=False, indent=1) + "\n")


def entries(man: dict, unit: str, uid: str) -> list[dict]:
    return sorted([e for e in man["entries"] if e.get("unit") == unit and e.get("id") == uid], key=lambda e: int(e.get("rev") or 0))


def entry(man: dict, unit: str, uid: str, rev: int) -> dict | None:
    return next((e for e in entries(man, unit, uid) if e.get("rev") == rev), None)


def is_withdrawn(man: dict, unit: str, uid: str, rev: int | None) -> bool:
    """판을 지정한 내림은 그 판에, 판 없는 내림(rev: null)은 내릴 때 승인돼 있던 판(upto_rev 이하)에 적용한다 — 그 뒤 판을 올려
    다시 승인하면 되살아난다(설계 9-2). upto_rev 가 없는 옛 줄은 모든 판에 적용한다. rev=None 으로 물으면 가장 큰 판을 본다."""
    if rev is None:
        ents = entries(man, unit, uid)
        rev = int(ents[-1]["rev"]) if ents else None
    for w in man["withdrawn"]:
        if w.get("unit") != unit or w.get("id") != uid:
            continue
        if w.get("rev") is not None and w.get("rev") == rev:
            return True
        if w.get("rev") is None and (rev is None or not isinstance(w.get("upto_rev"), int) or rev <= w["upto_rev"]):
            return True
    return False


def approver_error(by: str) -> tuple[int, str]:
    """(종료 코드, 문구) — 승인한 쪽 이름의 시험·실제 규칙(6-12)."""
    if cards._blank(by):
        return 2, "승인한 쪽(--by)을 적는다"
    if paths.is_alias_of_real_root():
        return 2, MSG_ROOT_ALIAS
    if paths.is_real_root() and by.strip() == TEST_BY:
        return 2, MSG_TEST_IN_REAL
    if not paths.is_real_root() and by.strip() != TEST_BY:
        return 2, MSG_REAL_IN_TEST
    return 0, ""


def entry_error(man: dict, unit: str, uid: str, rev) -> str:
    """판 공개 판정의 공통 층 — 판 번호 꼴, 같은 판 중복, 승인한 쪽과 시각, 시험 승인. 문제가 없으면 빈 글."""
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        return "판 번호가 1 이상 정수가 아니다"
    same = [e for e in man.get("entries") or [] if e.get("unit") == unit and e.get("id") == uid and e.get("rev") == rev
            and isinstance(e.get("rev"), int) and not isinstance(e.get("rev"), bool)]
    if len(same) > 1:
        return "발행 목록에 같은 판이 두 줄 있다"
    e = same[0] if same else None
    if e is None:
        return "발행 목록에 없다"
    if is_withdrawn(man, unit, uid, rev):
        return "내렸다"
    by = e.get("approved_by")
    if isinstance(by, str) and by.strip() == TEST_BY:
        return MSG_TEST_NOT_PUBLIC   # 시험 폴더에서도 시험 승인은 공개용에 나가지 않는다
    if not paths.is_real_root():
        # 시험 폴더의 승인은 모두 시험 승인이다(approver_error) — 이름 칸만 바꿔 공개 승인으로 만들지 못하게 폴더로 막는다
        return MSG_TEST_NOT_PUBLIC
    if cards._blank(by) or not isinstance(by, str) or cards._blank(e.get("approved_at")):
        return "승인한 쪽이나 승인 시각이 비어 있다"
    return ""


def prior_approval(man: dict, unit: str, uid: str, rev: int, h: str, request_id, approval_path: pathlib.Path) -> dict | None:
    """멱등 분기와 요청 번호 충돌 — 승인을 계속하면 None, 아니면 돌려줄 {code, msg, entry}."""
    if not cards._blank(request_id):
        for e in man.get("entries") or []:
            if e.get("request_id") == request_id and (e.get("unit"), e.get("id"), e.get("rev"), e.get("content_hash")) != (unit, uid, rev, h):
                return {"code": 3, "msg": f"{MSG_REQUEST_ID}({e.get('unit')}:{e.get('id')} {e.get('rev')}판)", "entry": None}
    old = entry(man, unit, uid, rev)
    if not old:
        return None
    label = uid if unit == "issue" else f"{unit}:{uid}"
    if old.get("content_hash") != h:
        return {"code": 3, "msg": f"{label} {rev}판: 같은 판이 다른 내용으로 이미 승인됐다 — 판 번호를 올린다", "entry": None}
    if is_withdrawn(man, unit, uid, rev):
        return {"code": 3, "msg": f"{label} {rev}판: {MSG_WITHDRAWN}", "entry": None}
    if not approval_path.is_file():
        return {"code": 3, "msg": f"{label} {rev}판: 발행 목록에는 있는데 고정 사본이 없다 — 판 번호를 올린다", "entry": None}
    return {"code": 0, "msg": f"{label} {rev}판: 이미 승인됨", "entry": old}


def _names_of(issue: dict) -> set[str]:
    al = issue.get("aliases") if isinstance(issue.get("aliases"), list) else []
    return {str(x) for x in [issue.get("slug"), *al] if isinstance(x, str) and x}


def slug_conflicts(issue: dict, man: dict) -> list[tuple[str, str]]:
    """다른 이슈(작업본, 발행 목록)와 겹치는 주소 이름·별칭 [(칸, 문구)]. 합친 이슈의 옛 주소가 합친 쪽 별칭인 것은 겹침이 아니다."""
    iid = issue.get("issue_id")
    others: dict[str, dict] = {}
    for o in model.all_issue_ids():
        if o == iid:
            continue
        try:
            others[o] = model.load_issue(o)
        except (OSError, ValueError):
            continue
    used: dict[str, set[str]] = {}
    for o, oi in others.items():
        if oi.get("merged_into") == iid or issue.get("merged_into") == o:
            continue
        for n in _names_of(oi):
            used.setdefault(n, set()).add(o)
    for e in man.get("entries") or []:
        if e.get("unit") == "issue" and e.get("id") != iid and isinstance(e.get("slug"), str):
            o = e["id"]
            if (others.get(o) or {}).get("merged_into") == iid or issue.get("merged_into") == o:
                continue
            used.setdefault(e["slug"], set()).add(o)
    out = []
    al = issue.get("aliases") if isinstance(issue.get("aliases"), list) else []
    for k, names in (("slug", [issue.get("slug")]), ("aliases", al)):
        for n in names:
            if isinstance(n, str) and n in used:
                out.append((k, f"{MSG_SLUG_TAKEN} — '{n}'을 다른 이슈({', '.join(sorted(used[n]))})가 쓴다"))
    return out
