"""승인 지문(내용 해시), 근거 해시, 본문 해시 — 설계 8절.

정규화는 _canon 한 곳만 쓴다: 모든 문자열(사전 키 포함)을 NFC 로 바꾸고 양끝 공백을 뗀 뒤
json.dumps(sort_keys, ensure_ascii=False, 구분자 최소) → sha256 16진수 앞 32자. 'sha256:' 을 붙이지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata

from . import model

# 이슈의 최상위 칸은 지문 안(DIGEST_FIELDS) 또는 밖(DIGEST_SKIP) 정확히 한 곳에 있다(시험이 고정한다).
DIGEST_FIELDS = ("issue_id", "slug", "aliases", "revision", "split_from", "merged_into", "category", "keywords", "example",
                 "reason", "publish", "sensitive", "election", "syuka_deck", "event_check", "titles", "rev_line", "what_new",
                 "why_matters", "so_far", "so_far_refs", "numbers", "facts", "claims", "flow", "stances", "open_questions",
                 "spillover", "figures", "corrections", "production")
DIGEST_SKIP = ("topic_state", "trend", "work_state", "history", "reviews")
BODY_SKIP = ("header", "footer", "trend", "trend_now", "internal")


def _norm(v):
    if isinstance(v, str):
        return unicodedata.normalize("NFC", v).strip()
    if isinstance(v, dict):
        return {_norm(str(k)): _norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    return v


def _canon(obj) -> str:
    raw = json.dumps(_norm(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(unicodedata.normalize("NFC", raw).encode("utf-8")).hexdigest()[:32]


def _pick(d, *keys):
    d = d if isinstance(d, dict) else {}
    return {k: d.get(k) for k in keys}


def evidence_view(ev: dict) -> dict:
    """근거 기록 가운데 지문에 드는 칸만(사본 경로, 받기 세부값, 다시 계산되는 대조 결과, 고친 횟수는 뺀다)."""
    v = ev.get("verification") if isinstance(ev.get("verification"), dict) else {}
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else None
    return {
        "evidence_id": ev.get("evidence_id"), "kind": ev.get("kind"),
        "source": _pick(ev.get("source"), "url", "publisher", "title", "accessed"),
        "observed": ev.get("observed"), "checks": ev.get("checks"), "doc": ev.get("doc"), "report": ev.get("report"),
        "raw": {k: x for k, x in raw.items() if k not in ("path", "text_path")} if raw is not None else None,
        "verification": {"capture": _pick(v.get("capture"), "sha256", "url"),
                         "author": _pick(v.get("author"), "located"),
                         "recheck": _pick(v.get("recheck"), "located", "checks")} if v else None,
    }


def issue_view(issue: dict) -> dict:
    return {k: issue.get(k) for k in DIGEST_FIELDS}


def cited(issue: dict, evidences: dict) -> list[str]:
    return sorted(set(model.cited_evidence_ids(issue)))


def content_hash(issue: dict, evidences: dict) -> str:
    """승인 지문. 인용한 근거가 근거 기록에 없으면 '없음' 표시로 넣는다(근거를 지운 것도 내용 변화다)."""
    evs = [evidence_view(evidences[e]) if e in evidences else {"evidence_id": e, "missing": True} for e in cited(issue, evidences)]
    return _canon([issue_view(issue), evs])


def evidence_hash(issue: dict, evidences: dict) -> str:
    rows = []
    for e in cited(issue, evidences):
        ev = evidences.get(e) or {}
        v = ev.get("verification") if isinstance(ev.get("verification"), dict) else {}
        sha = ((v.get("capture") or {}).get("sha256") if isinstance(v.get("capture"), dict) else None) \
            or ((ev.get("raw") or {}).get("sha256") if isinstance(ev.get("raw"), dict) else None) or ""
        rows.append([e, sha, ((ev.get("source") or {}) if isinstance(ev.get("source"), dict) else {}).get("url", "")])
    return _canon(rows)


def body_hash(body: dict) -> str:
    """본문 해시 — 머리, 바닥, 추이, 미리보기 덧붙임을 뺀 본문(가림과 내림을 적용하기 전)."""
    return _canon({k: v for k, v in body.items() if k not in BODY_SKIP})


def snapshot_view(issue: dict, evidences: dict) -> dict:
    """검토 이어받기 비교에 쓰는 사본 — 지문에 드는 칸 그대로."""
    return {"issue": issue_view(issue), "evidence": {e: evidence_view(evidences[e]) for e in cited(issue, evidences) if e in evidences}}


def changed_paths(before: dict, after: dict) -> list[str]:
    """두 snapshot_view 사이에 바뀐 칸 경로. 항목 목록은 '<목록>.<id>.<칸>', 근거는 'evidence.<번호>' 까지 내려간다."""
    out: list[str] = []
    bi, ai = before.get("issue") or {}, after.get("issue") or {}
    for k in DIGEST_FIELDS:
        if _canon(bi.get(k)) == _canon(ai.get(k)):
            continue
        if k in model.ITEM_LISTS:
            bm = {it.get("id"): it for it in bi.get(k) or [] if isinstance(it, dict)}
            am = {it.get("id"): it for it in ai.get(k) or [] if isinstance(it, dict)}
            for iid in sorted(set(bm) | set(am), key=str):
                b, a = bm.get(iid), am.get(iid)
                if b is None or a is None:
                    out.append(f"{k}.{iid}")
                    continue
                for f in sorted(set(b) | set(a)):
                    if _canon(b.get(f)) != _canon(a.get(f)):
                        out.append(f"{k}.{iid}.{f}")
        else:
            out.append(k)
    be, ae = before.get("evidence") or {}, after.get("evidence") or {}
    for e in sorted(set(be) | set(ae)):
        if _canon(be.get(e)) != _canon(ae.get(e)):
            out.append(f"evidence.{e}")
    return out


def changed_fields(before_issue: dict | None, after_issue: dict) -> list[str]:
    """앞 판과 견준 최상위 칸 목록(승인 기록의 changed_fields). 앞 판이 없으면 ['새 이슈']."""
    if before_issue is None:
        return ["새 이슈"]
    return [k for k in DIGEST_FIELDS if k != "revision" and _canon(before_issue.get(k)) != _canon(after_issue.get(k))]
