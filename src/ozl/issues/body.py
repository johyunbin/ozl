"""판 하나의 본문 JSON(공개 모양) — 게시 가능 항목만 싣는다. 승인 지문(digest)과 내보내기(export)가 같이 쓴다.

본문의 모양이 승인을 묶는다(본문 해시). 모양을 바꾸면 EXPORT_VERSION 을 올린다 — 이미 승인한 판은 공개용에서 빠지고 다시 승인받는다.
가림(선거)과 내림은 여기서 적용하지 않는다(mask, export 가 출력 때 적용한다).
"""
from __future__ import annotations

from ozl.research import cards

from . import evidence as EV
from . import manifest, model, rules

EXPORT_VERSION = 3   # 2: 주장·작은 주장에 scope(확인한 범위)와 basis(판정을 받치는 사실 문장)를 더함, 당사자 입장 없음 문구
#                      3: 주장에 press_label(보도 요약)을 따로 두고 evidence_label 에서 보도를 뺌, 판정 변경 기록은 게시한 판 뒤의 것만
VERDICT_ORDER = ("확인", "일부 맞음", "사실과 다름", "확인 못 함")
VERDICT_NOTE = {"확인 못 함": "거짓이라는 뜻이 아니다"}
# AI 고지(독자 화면의 글). 승인된 판(rev_at 이 있는 판)은 "게시 승인은 사람이 했다",
# 승인 전 판(작업본 미리보기 · export --preview)은 아직 승인하지 않았다는 사실대로 적는다.
AI_NOTICE_TAIL = "AI를 썼다는 고지가 내용의 정확성을 보증하지는 않는다."
AI_NOTICE_PERSON = "조사, 판정, 초안은 AI 도구가 했고, 고르기와 게시 승인은 사람이 했다. " + AI_NOTICE_TAIL
AI_NOTICE_MODEL = "조사, 판정, 초안, 고르기는 AI 도구가 했고, 게시 승인은 사람이 했다. " + AI_NOTICE_TAIL
AI_NOTICE_PERSON_PENDING = ("조사, 판정, 초안은 AI 도구가 했고, 고르기는 사람이 했다. "
                            "게시 승인은 사람이 한다. 이 판은 아직 승인 전이다. " + AI_NOTICE_TAIL)
AI_NOTICE_MODEL_PENDING = ("조사, 판정, 초안, 고르기는 AI 도구가 했다. "
                           "게시 승인은 사람이 한다. 이 판은 아직 승인 전이다. " + AI_NOTICE_TAIL)
NO_POSITION = "당사자의 직접 발표를 찾지 못함({} 확인)"
# 출력 검사(6-11)가 숨긴 항목의 문장을 찾을 때 보는 칸
HIDDEN_TEXT_FIELDS = ("text", "gist", "what", "summary", "caption", "alt", "would_decide")
TOP_TEXT_PREFIX = ("titles.", "so_far.", "what_new", "why_matters", "rev_line", "reason", "spillover.")


def _source(ev: dict | None, eid: str) -> dict:
    if not isinstance(ev, dict):
        return {"id": eid, "kind": "", "by": "", "title": "", "url": "", "checked_at": ""}
    src = ev.get("source") if isinstance(ev.get("source"), dict) else {}
    kind = ev.get("kind")
    if kind == "보도":
        r = ev.get("report") if isinstance(ev.get("report"), dict) else {}
        return {"id": eid, "kind": kind, "by": r.get("outlet") or src.get("publisher") or "", "title": r.get("title") or "",
                "url": src.get("url") or "", "checked_at": str(r.get("read_at") or "")}
    v = ev.get("verification") if isinstance(ev.get("verification"), dict) else {}
    at = v.get("verified_at") or ((ev.get("raw") or {}).get("fetched_at") if isinstance(ev.get("raw"), dict) else "") or src.get("accessed")
    return {"id": eid, "kind": kind or "", "by": src.get("publisher") or "", "title": src.get("title") or "",
            "url": src.get("url") or "", "checked_at": str(at or "")}


def _sources(item, evidences) -> list[dict]:
    return [_source(evidences.get(e), e) for e in model.item_evidence_ids(item)]


ITEM_NUMBER_KEYS = ("value", "kind", "unit", "formula", "inputs", "rounding", "refutes")


def _nums(item, keys=ITEM_NUMBER_KEYS) -> list[dict]:
    out = []
    for n in (item.get("numbers") if isinstance(item, dict) else None) or []:
        if isinstance(n, dict):
            d = {k: n[k] for k in keys if k in n}
            if isinstance(d.get("inputs"), dict):   # 계산 입력도 정해진 칸만 싣는다
                d["inputs"] = {k: ({x: v[x] for x in model.INPUT_KEYS if x in v} if isinstance(v, dict) else v)
                               for k, v in d["inputs"].items()}
            out.append(d)
    return out


def _party(pp) -> str:
    if not isinstance(pp, dict):
        return ""
    if pp.get("none") is True:
        return NO_POSITION.format(pp.get("checked_at") or "")
    return str(pp.get("text") or "")


def basis_texts(issue: dict, fact_ids) -> list[str]:
    """판정을 받치는 사실 문장 — basis_facts 가 가리킨 확인된 사실 가운데 게시되는 것의 문장(적은 차례대로)."""
    facts = {f.get("id"): f for f in _public(issue, "facts")}
    return [str(facts[x].get("text") or "") for x in dict.fromkeys(fact_ids if isinstance(fact_ids, list) else [])
            if isinstance(x, str) and x in facts and facts[x].get("text")]


def _part(issue: dict, p: dict, evidences: dict) -> dict:
    return {"id": p.get("id"), "gist": p.get("gist") or "", "core": bool(p.get("core")), "verdict": p.get("verdict"),
            "reasons": list(p.get("unverified_reasons") or []), "would_decide": p.get("would_decide") or "",
            "scope": p.get("scope") or "", "basis": basis_texts(issue, p.get("basis_facts")),
            "sources": _sources(p, evidences)}


def first_published(man: dict | None, issue_id) -> int | None:
    """그 이슈가 발행 목록에 처음 오른 판(내린 판도 센다). 없으면 None."""
    ents = manifest.entries(man, "issue", issue_id) if isinstance(man, dict) else []
    return int(ents[0]["rev"]) if ents else None


def public_history(issue: dict, c: dict, first_rev: int | None) -> list[dict]:
    """독자에게 보이는 판정 변경 기록 — 게시한 판에 실렸던 판정에서 바뀐 것만.
    게시한 판이 없으면 빈 목록이고, 있으면 처음 게시한 판보다 뒤이면서 이 판 이하인 판(rev)의 기록만 싣는다.
    rev 가 없는 옛 기록은 싣지 않는다. 판 번호로만 가르므로 승인 때 만든 본문과 고정 사본에서 다시 만든 본문이 같다."""
    if first_rev is None:
        return []
    top = issue.get("revision")
    out = []
    for h in c.get("verdict_history") or []:
        r = h.get("rev") if isinstance(h, dict) else None
        if isinstance(r, int) and not isinstance(r, bool) and r > first_rev and (not isinstance(top, int) or r <= top):
            out.append(h)
    return out


def _claim(issue: dict, c: dict, evidences: dict, copy_errs: dict, first_rev: int | None = None) -> dict:
    return {"id": c.get("id"), "gist": c.get("gist") or "", "kind": c.get("kind"), "verdict": c.get("verdict"),
            "scope": c.get("scope") or "", "basis": basis_texts(issue, c.get("basis_facts")),
            "evidence_label": rules.evidence_label(c, evidences, copy_errs),
            "press_label": rules.press_label(c, evidences, copy_errs),
            "searched": c.get("searched") or "", "not_found": c.get("not_found") or "",
            "reasons": list(c.get("unverified_reasons") or []), "would_decide": c.get("would_decide") or "",
            "party_position": _party(c.get("party_position")),
            "parts": [_part(issue, p, evidences) for p in c.get("parts") or [] if isinstance(p, dict)],
            "sources": _sources(c, evidences), "history": public_history(issue, c, first_rev),
            "numbers": _nums(c), "election_mask": bool(c.get("election_mask", False))}


def _public(issue, lst):
    return [it for it in issue.get(lst) or [] if isinstance(it, dict) and rules.item_public(issue, it)]


def _top_numbers(issue: dict) -> dict:
    """최상위 numbers 지도 가운데 이슈 칸(제목, 첫 화면 줄)과 게시되는 항목의 칸만."""
    top = issue.get("numbers") if isinstance(issue.get("numbers"), dict) else {}
    shown = {f"{lst}.{it.get('id')}." for lst in model.ITEM_LISTS for it in _public(issue, lst)}
    shown |= {f"corrections.{i}." for i in range(len(issue.get("corrections") or []))}
    ok_paths = model.top_number_paths(issue)        # 검사기가 보는 글 칸 경로만 — 그 밖의 키는 검사받지 않으므로 싣지 않는다
    out = {}
    for k, v in sorted(top.items(), key=lambda x: str(x[0])):
        if k in ok_paths and (k.startswith(TOP_TEXT_PREFIX) or any(k.startswith(s) for s in shown)):
            out[k] = _nums({"numbers": v if isinstance(v, list) else []}, model.NUMBER_KEYS)
    return out


def ai_notice(issue: dict, approved: bool = True) -> str:
    """approved 가 거짓이면(승인 전 판) 게시 승인을 아직 하지 않았다고 적는다."""
    prod = issue.get("production") if isinstance(issue.get("production"), dict) else {}
    person = prod.get("chosen_by") == "사람"
    if approved:
        return AI_NOTICE_PERSON if person else AI_NOTICE_MODEL
    return AI_NOTICE_PERSON_PENDING if person else AI_NOTICE_MODEL_PENDING


def copy_errs_of(evidences: dict) -> dict:
    return {eid: EV.copy_errors(ev) for eid, ev in evidences.items()}


def issue_body(issue: dict, evidences: dict, rev_at: str = "", copy_errs: dict | None = None,
               approved: bool | None = None, first_rev: int | None = None) -> dict:
    """본문 JSON. rev_at 은 그 판의 승인 시각(작업본 미리보기는 빈 값).
    approved 는 AI 고지의 승인 여부다. 주지 않으면 rev_at 이 있는 판만 승인된 판으로 본다.
    first_rev 는 그 이슈가 처음 게시된 판(first_published). 주지 않으면 게시한 판이 없는 것으로 보고 판정 변경 기록을 싣지 않는다."""
    ce = copy_errs_of(evidences) if copy_errs is None else copy_errs
    t = issue.get("titles") if isinstance(issue.get("titles"), dict) else {}
    shown = [_claim(issue, c, evidences, ce, first_rev) for c in _public(issue, "claims")]
    groups = []
    for v in VERDICT_ORDER:
        cl = [c for c in shown if c["verdict"] == v]
        if cl:
            groups.append({"verdict": v, "note": VERDICT_NOTE.get(v, ""), "claims": cl})
    cited: list[str] = []
    ec = issue.get("event_check") if isinstance(issue.get("event_check"), dict) else {}
    if isinstance(ec.get("evidence"), str):
        cited.append(ec["evidence"])
    for lst in ("facts", "claims", "flow", "stances", "figures"):
        for it in _public(issue, lst):
            cited += model.item_evidence_ids(it)
    for nums in _top_numbers(issue).values():
        cited += model.number_evidence_ids(nums)
    corrections = [{k: c.get(k) for k in ("rev", "at", "kind", "before", "after", "why")}
                   for c in issue.get("corrections") or [] if isinstance(c, dict)]
    sp = issue.get("spillover") if isinstance(issue.get("spillover"), dict) else {}
    return {
        "header": {"site": "OZL"}, "footer": {},
        "id": issue.get("issue_id"), "slug": issue.get("slug"), "rev": issue.get("revision"), "rev_at": rev_at or "",
        "example": bool(issue.get("example")), "title": t.get("chosen") or "", "rev_line": issue.get("rev_line") or "",
        "what_new": issue.get("what_new") or "", "why_matters": issue.get("why_matters") or "",
        "so_far": list(issue.get("so_far") or []), "reason": issue.get("reason") or "", "category": issue.get("category"),
        "keywords": list(issue.get("keywords") or []), "aliases": list(issue.get("aliases") or []),
        "sensitive": list(issue.get("sensitive") or []), "election": issue.get("election"),
        "numbers": _top_numbers(issue),
        "corrections_top": [c for c in corrections if c["kind"] == "정정"],
        "verdicts": {"groups": groups, "hidden_claims": rules.hidden_claims(issue),
                     "summary": {v: sum(1 for c in shown if c["verdict"] == v) for v in VERDICT_ORDER}},
        "facts": [{"id": f.get("id"), "text": f.get("text") or "", "type": f.get("type"), "kind": f.get("kind"),
                   "sources": _sources(f, evidences), "numbers": _nums(f), "election_mask": bool(f.get("election_mask", False))}
                  for f in _public(issue, "facts")],
        "flow": [{"id": w.get("id"), "event_date": str(w.get("event_date") or ""), "report_date": str(w.get("report_date") or ""),
                  "what": w.get("what") or "", "kind": w.get("kind"), "sources": _sources(w, evidences), "numbers": _nums(w),
                  "election_mask": bool(w.get("election_mask", False))} for w in _public(issue, "flow")],
        "stances": [{"id": s.get("id"), "who": s.get("who") or "", "kind": s.get("kind"), "summary": s.get("summary") or "",
                     "at": str(s.get("at") or ""), "sources": _sources(s, evidences), "numbers": _nums(s),
                     "election_mask": bool(s.get("election_mask", False))} for s in _public(issue, "stances")],
        "open_questions": [{"id": q.get("id"), "text": q.get("text") or "", "election_mask": bool(q.get("election_mask", False))}
                           for q in _public(issue, "open_questions")],
        "spillover": {"issues": list(sp.get("issues") or []),
                      "similar_cases": [{"text": c.get("text") or "", "url": c.get("url") or ""}
                                        for c in sp.get("similar_cases") or [] if isinstance(c, dict)]},
        "figures": [{"id": g.get("id"), "kind": g.get("kind"), "caption": g.get("caption") or "", "alt": g.get("alt") or "",
                     "sources": _sources(g, evidences), "register_id": g.get("register_id") or "",
                     "election_mask": bool(g.get("election_mask", False))} for g in _public(issue, "figures")],
        "sources": [_source(evidences.get(e), e) for e in dict.fromkeys(cited)],
        "corrections": corrections,
        "ai_notice": ai_notice(issue, approved=bool(rev_at) if approved is None else approved),
        "trend": None,
    }


def verdict_summary(body: dict) -> dict:
    return dict((body.get("verdicts") or {}).get("summary") or {})


def hidden_texts(issue: dict) -> list[tuple[str, str]]:
    """공개되지 않는 항목의 문장 [(항목 경로, 문장)] — 출력 검사(6-11)가 공개용 출력에서 찾는다.
    이슈 전체가 게시 가능이 아니면 모든 항목이 숨는다."""
    out = []
    for lst in model.ITEM_LISTS:
        for it in issue.get(lst) or []:
            if not isinstance(it, dict) or rules.item_public(issue, it):
                continue
            for k in HIDDEN_TEXT_FIELDS:
                if isinstance(it.get(k), str) and not cards._blank(it[k]):
                    out.append((f"{lst}.{it.get('id')}", it[k]))
            for p in it.get("parts") or []:
                if isinstance(p, dict) and isinstance(p.get("gist"), str):
                    out.append((f"{lst}.{it.get('id')}", p["gist"]))
    return out
