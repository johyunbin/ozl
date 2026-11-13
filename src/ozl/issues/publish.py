"""조합표 3단계 — 게시 가부(설계 5-4). rules 가 다시 내보내므로 다른 모듈은 rules.item_public 처럼 부른다."""
from __future__ import annotations

from ozl.research import cards

from . import model
from .rules import DISCLOSURE_LABEL, MSG_PRIVATE, MSG_REASON, MSG_REF_HIDDEN, MSG_SO_FAR, OFFICIAL, TARGET_MUST_EXCLUDE  # noqa: F401


def item_public(issue: dict, item: dict) -> bool:
    """이슈가 게시 가능이고 항목도 게시 가능일 때만 참(대상이 일반인·공인의 사생활이면 늘 거짓)."""
    pub = issue.get("publish") if isinstance(issue.get("publish"), dict) else {}
    return (pub.get("state") == "게시 가능" and isinstance(item, dict) and item.get("publish") == "게시 가능"
            and item.get("target_kind") not in TARGET_MUST_EXCLUDE)


def hidden_claims(issue: dict) -> int:
    return sum(1 for c in issue.get("claims") or [] if not item_public(issue, c))


def publish_errors(issue: dict, evidences: dict | None = None) -> list[tuple[str, str]]:
    """게시 가부 오류 [(칸 경로, 문구)] — 설계 5-4."""
    errs: list[tuple[str, str]] = []
    state = (issue.get("publish") or {}).get("state") if isinstance(issue.get("publish"), dict) else None
    if state == "게시 가능" and cards._blank(issue.get("reason")):
        errs.append(("reason", MSG_REASON))
    if state == "게시 가능" and not cards._blank(issue.get("merged_into")):
        errs.append(("merged_into", "합쳐진 이슈는 게시하지 않는다(주소는 합친 쪽의 별칭으로 둔다)"))
    for lst in ("facts", "claims", "flow", "stances", "open_questions", "figures"):
        for it in issue.get(lst) or []:
            if not isinstance(it, dict):
                continue
            if it.get("target_kind") in TARGET_MUST_EXCLUDE and it.get("publish") == "게시 가능":
                errs.append((f"{lst}.{it.get('id')}.publish", MSG_PRIVATE))
    t = issue.get("titles") if isinstance(issue.get("titles"), dict) else {}
    if t.get("target_kind") in TARGET_MUST_EXCLUDE:
        errs.append(("titles.target_kind", MSG_PRIVATE + " — 제목은 공개 제외가 없으므로 그런 대상을 제목으로 삼지 않는다"))
    for g in issue.get("figures") or []:
        if not isinstance(g, dict):
            continue
        where = f"figures.{g.get('id')}"
        if g.get("kind") not in model.FIGURE_KINDS:
            errs.append((f"{where}.kind", f"그림 종류 '{g.get('kind')}'은 허용 값({', '.join(model.FIGURE_KINDS)})이 아니다"))
        elif g.get("kind") == "공식 문서 캡처" and ((evidences or {}).get(g.get("evidence")) or {}).get("kind") not in OFFICIAL:
            errs.append((f"{where}.evidence", "공식 문서 캡처는 공식 원문이나 기관 자료 근거에서만 만든다"))
        elif g.get("kind") == "검수 대장 그림" and cards._blank(g.get("register_id")):
            errs.append((f"{where}.register_id", "검수 대장 그림은 대장 번호(register_id)를 적는다"))
    refs = issue.get("so_far_refs") or []
    basis = (t.get("basis_claims") or []) if isinstance(t.get("basis_claims"), list) else []
    byid = {c.get("id"): c for c in issue.get("claims") or [] if isinstance(c, dict)}
    for k, lst in (("so_far_refs", refs if isinstance(refs, list) else []), ("titles.basis_claims", basis)):
        for r in lst:
            if r in byid and not item_public(issue, byid[r]) and state == "게시 가능":
                errs.append((k, MSG_REF_HIDDEN.format(r)))
    for c in issue.get("claims") or []:
        if isinstance(c, dict) and c.get("verdict") == "사실과 다름" and item_public(issue, c) and c.get("id") not in refs:
            errs.append(("so_far_refs", MSG_SO_FAR.format(c.get("id"))))
    return errs
