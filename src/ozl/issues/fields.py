"""정해 둔 칸만 받는다 — 이슈 기록과 근거 기록의 모든 항목 사전에서 낯선 키를 오류로 낸다. 문장으로 끝나야 하는 칸의 끝맺음도 본다.

한 줄 사전 표기({a: b, c})가 쉼표에서 잘리면 뒷부분이 값이 null 인 낯선 키가 되고 화면에는 잘린 문장이 나간다(2026-11-14 실제 이슈).
허용 목록은 설계 3절과 지금 예시·실제 이슈가 쓰는 칸이다. 칸을 더하면 여기와 model.ISSUE_FIELDS 를 함께 고친다.
최상위 칸(model.ISSUE_FIELDS), 숫자 항목(model.NUMBER_KEYS), 정정·판정 변경 이력·비슷한 사례·추이는 check 가 이미 모양을 본다.
근거 기록의 verification.capture·match 는 프로그램(capture, machine-verify)이 쓰는 칸이라 보지 않는다.
"""
from __future__ import annotations

import re

from ozl.research import cards

MSG = "정해지지 않은 칸 '{}'"

ITEM_COMMON = ("id", "target_kind", "publish", "election_mask")
LINK = ("id", "stance", "basis", "subject", "period", "scope", "unit", "passage_role", "refers_to_original", "addresses_cause")
CLAIM = ITEM_COMMON + ("gist", "kind", "attributed_to", "subject", "period", "scope", "unit", "spread", "verdict", "unverified_reasons",
                       "would_decide", "searched", "not_found", "counter_searched", "basis_label", "evidence", "parts", "party_position",
                       "about_procedure", "premise_event", "allegation", "numbers", "verdict_history", "refutes", "basis_facts")
PART = ("id", "gist", "core", "verdict", "evidence", "unverified_reasons", "would_decide", "kind", "subject", "period", "scope", "unit",
        "basis_facts")
ITEMS = {
    "facts": ITEM_COMMON + ("text", "type", "kind", "evidence", "numbers", "refutes"),
    "claims": CLAIM,
    "flow": ITEM_COMMON + ("event_date", "report_date", "what", "kind", "evidence", "numbers", "refutes"),
    "stances": ITEM_COMMON + ("who", "kind", "summary", "evidence", "at", "numbers", "refutes"),
    "open_questions": ITEM_COMMON + ("text",),
    "figures": ITEM_COMMON + ("kind", "caption", "alt", "evidence", "register_id"),
}
TOP_DICTS = {
    "publish": ("state", "why"),
    "election": ("kind", "date", "poll_close", "restrict_from", "schedule_url"),
    "event_check": ("confirmed", "evidence", "at"),
    "titles": ("candidates", "chosen", "target_kind", "basis_claims"),
    "production": ("researched_by", "drafted_by", "chosen_by"),
    "spillover": ("issues", "similar_cases"),
}
REVIEW = ("id", "kind", "by_model", "family", "at", "content_hash", "result", "findings", "findings_hash", "notes_path", "notes_sha256",
          "before_hash", "after_hash", "addresses")

# 근거 기록 안의 사전
EV_DICTS = {
    "source": ("url", "publisher", "title", "tier", "accessed"),
    "doc": ("speaker", "speaker_role", "doc_kind", "doc_stage", "court", "admission", "authority", "transcribed", "denies_own_document"),
    "doc.court": ("level", "final"),
    "doc.admission": ("kind", "scope", "against_interest"),
    "checks": tuple(cards.CHECK_KEYS),
    "raw": ("url", "fetched_at", "sha256", "located", "author_by", "recheck_by", "path", "text_path"),
    "verification": ("method", "capture", "match", "image", "author", "recheck", "verified_at"),
    "verification.author": ("by", "located"),
    "verification.recheck": ("by", "located", "checks", "at"),
    "verification.recheck.checks": ("unit", "as_of", "status", "population", "speaker"),
}

# 문장으로 끝나야 하는 칸 — 마침표, 물음표, 느낌표, 닫는 괄호나 따옴표로 끝난다(주장의 요지, 제목, 남은 질문은 보지 않는다)
SENTENCE_END = re.compile(r"[.?!。)）\]」』\"'’”]\s*$")
MSG_SENTENCE = "문장으로 끝맺지 않았다(마침표, 물음표, 닫는 괄호나 따옴표) — 잘린 문장인지 본다"


def _extra(d, allowed, path) -> list[tuple[str, str]]:
    if not isinstance(d, dict):
        return []
    return [(path, MSG.format(k)) for k in sorted(set(map(str, d)) - set(allowed))]


def issue_field_errors(issue: dict) -> list[tuple[str, str]]:
    """[(칸 경로, 문구)] — 이슈 기록의 항목 사전마다 정해지지 않은 칸."""
    e: list[tuple[str, str]] = []
    for k, allowed in TOP_DICTS.items():
        e += _extra(issue.get(k), allowed, k)
    t = issue.get("titles") if isinstance(issue.get("titles"), dict) else {}
    for i, c in enumerate(t.get("candidates") or []):
        e += _extra(c, ("text", "angle"), f"titles.candidates.{i}")
    for i, h in enumerate(issue.get("history") or []):
        e += _extra(h, ("at", "event"), f"history.{i}")
    for i, r in enumerate(issue.get("reviews") or []):
        e += _extra(r, REVIEW, f"reviews.{i}")
        for j, f in enumerate(r.get("findings") or [] if isinstance(r, dict) else []):
            e += _extra(f, ("field", "note"), f"reviews.{i}.findings.{j}")
    for lst, allowed in ITEMS.items():
        for i, it in enumerate(issue.get(lst) or []):
            if not isinstance(it, dict):
                continue
            p = f"{lst}.{it.get('id', i)}"
            e += _extra(it, allowed, p)
            if lst != "claims":
                continue
            for x in it.get("evidence") or []:
                e += _extra(x, LINK, f"{p}.evidence.{x.get('id') if isinstance(x, dict) else '?'}")
            for pt in it.get("parts") or []:
                if not isinstance(pt, dict):
                    continue
                pp = f"{p}.parts.{pt.get('id')}"
                e += _extra(pt, PART, pp)
                for x in pt.get("evidence") or []:
                    e += _extra(x, LINK, f"{pp}.evidence.{x.get('id') if isinstance(x, dict) else '?'}")
            e += _extra(it.get("party_position"), ("text", "evidence", "checked_at", "none"), f"{p}.party_position")
            sp = it.get("spread")
            e += _extra(sp, ("where", "first_seen", "links"), f"{p}.spread")
            for j, ln in enumerate((sp.get("links") or []) if isinstance(sp, dict) else []):
                e += _extra(ln, ("outlet", "url"), f"{p}.spread.links.{j}")
    return e


def evidence_field_errors(ev: dict) -> list[tuple[str, str]]:
    """[(근거 안의 칸 경로, 문구)] — 근거 기록 안 사전의 정해지지 않은 칸(맨 위 칸은 evidence.structure_errors 가 본다)."""
    e: list[tuple[str, str]] = []
    for path, allowed in EV_DICTS.items():
        d = ev
        for k in path.split("."):
            d = d.get(k) if isinstance(d, dict) else None
        e += _extra(d, allowed, path)
    return e


def sentence_paths(issue: dict) -> list[tuple[str, str]]:
    """문장으로 끝나야 하는 글 칸 [(칸 경로, 글)] — 확인된 사실, 흐름의 what, 입장의 summary, 무엇이 새로운가, 왜 중요한가,
    다루는 까닭, 지금까지 3줄. 빈 글은 빼다(빈 칸은 다른 검사가 본다)."""
    out = [(k, issue.get(k)) for k in ("what_new", "why_matters", "reason")]
    out += [(f"so_far.{i}", x) for i, x in enumerate(issue.get("so_far") or [])]
    for lst, k in (("facts", "text"), ("flow", "what"), ("stances", "summary")):
        out += [(f"{lst}.{it.get('id')}.{k}", it.get(k)) for it in issue.get(lst) or [] if isinstance(it, dict)]
    return [(p, t) for p, t in out if isinstance(t, str) and t.strip()]


def sentence_errors(issue: dict) -> list[tuple[str, str]]:
    return [(p, MSG_SENTENCE) for p, t in sentence_paths(issue) if not SENTENCE_END.search(t)]
