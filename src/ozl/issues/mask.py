"""출력할 때 적용하는 선거 가림 — 본문 해시를 만든 뒤(승인한 본문은 그대로 두고) 공개용 출력에만 적용한다.

법정 기간 = election.restrict_from 00:00 부터 election.date 의 poll_close 까지(KST). 정적 출력은 내보낸 뒤에도 그대로 남으므로
투표 마감 전에 내보내는 출력은 기간 시작 전이라도 가린다. election_mask 가 참인 항목과 판세 낱말이 든 항목·정정·비슷한 사례를
"선거법상 가린 내용" 으로 바꾸고, 가린 항목의 판정·근거·숫자(최상위 numbers 지도의 그 항목 칸 포함)를 지운다. 마감 뒤에는 그대로 돌려준다.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from . import digest, model, style

RULE_VERSION = 1
MASKED_TEXT = "선거법상 가린 내용"
KST = timezone(timedelta(hours=9))
TEXT_KEYS = ("text", "gist", "what", "summary", "caption", "alt", "searched", "not_found", "would_decide", "party_position",
             "evidence_label")
ITEM_LISTS = ("facts", "flow", "stances", "open_questions", "figures")
SOURCE_TEXT_KEYS = ("title", "by", "url")


def _parse(s) -> datetime | None:
    if not s:
        return None
    s = str(s).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s.replace("+09:00", "+0900"), fmt)
            return d if d.tzinfo else d.replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def window(election) -> tuple[datetime, datetime] | None:
    if not isinstance(election, dict):
        return None
    start = _parse(election.get("restrict_from"))
    end = _parse(f"{election.get('date')} {election.get('poll_close')}")
    return (start, end) if start and end else None


def active(election, now) -> bool:
    """가림을 적용하는가. 기간이 끝나기(투표 마감) 전이면 참이다 — 기간 시작 전에 내보낸 정적 출력이 기간 안에도 그대로 남지
    않게 기간 시작 전부터 가린다. 선거일·기간을 읽지 못하면 가린다(열린 쪽으로 새지 않는다). now 를 읽지 못하면 ValueError."""
    t = _parse(now)
    if t is None:
        raise ValueError(f"시각을 읽지 못했다: {now}")
    w = window(election)
    return w is None or t <= w[1]


def _texts(item: dict) -> list[str]:
    out = [str(item.get(k) or "") for k in TEXT_KEYS]
    for p in item.get("parts") or []:
        if isinstance(p, dict):
            out += [str(p.get(k) or "") for k in ("gist", "would_decide")]
    for h in item.get("history") or []:
        if isinstance(h, dict):
            out += [str(v) for v in h.values() if isinstance(v, str)]
    return out


def _hit(item: dict) -> bool:
    return bool(item.get("election_mask")) or any(style.poll_words(t) for t in _texts(item))


def _masked(item: dict) -> dict:
    """가린 항목 — 번호와 가림 표시, 글 칸 자리의 가린 문구만 남긴다(판정, 판정 이력, 근거, 숫자, 작은 주장은 지운다)."""
    out = {"id": item.get("id"), "masked": True, "election_mask": True}
    out.update({k: MASKED_TEXT for k in TEXT_KEYS if isinstance(item.get(k), str)})
    return out


def _src_ids(items) -> set:
    out = set()
    for it in items:
        out |= {s.get("id") for s in it.get("sources") or [] if isinstance(s, dict)}
        for p in it.get("parts") or []:
            if isinstance(p, dict):
                out |= {s.get("id") for s in p.get("sources") or [] if isinstance(s, dict)}
    return out


def _all_sources(out: dict) -> list[dict]:
    """본문 안의 출처 사전 전부(최상위 sources, 항목의 sources, 판정 묶음 안 주장과 작은 주장의 sources)."""
    found: list[dict] = []
    for s in out.get("sources") or []:
        if isinstance(s, dict):
            found.append(s)
    items = [it for lst in ITEM_LISTS for it in out.get(lst) or [] if isinstance(it, dict)]
    items += [c for g in (out.get("verdicts") or {}).get("groups") or [] for c in g.get("claims") or [] if isinstance(c, dict)]
    for it in items:
        found += [s for s in it.get("sources") or [] if isinstance(s, dict)]
        for p in it.get("parts") or []:
            if isinstance(p, dict):
                found += [s for s in p.get("sources") or [] if isinstance(s, dict)]
    return found


def apply(body: dict, now) -> dict:
    """선거 가림을 적용한 사본. 선거 이슈가 아니거나 기간이 끝났으면 그대로의 사본."""
    out = copy.deepcopy(body)
    if "선거" not in (out.get("sensitive") or []) or not active(out.get("election"), now):
        return out
    hits, gone, kept_items, prefixes = 0, set(), [], []
    for lst in ITEM_LISTS:
        new = []
        for it in out.get(lst) or []:
            if isinstance(it, dict) and _hit(it):
                hits += 1
                gone |= _src_ids([it])
                prefixes.append(f"{lst}.{it.get('id')}.")
                new.append(_masked(it))
            else:
                new.append(it)
                kept_items.append(it)
        out[lst] = new
    vd = out.get("verdicts") or {}
    groups, n_masked = [], 0
    for g in vd.get("groups") or []:
        keep = []
        for c in g.get("claims") or []:
            if _hit(c):
                hits += 1
                n_masked += 1
                gone |= _src_ids([c])
                prefixes.append(f"claims.{c.get('id')}.")
            else:
                keep.append(c)
                kept_items.append(c)
        if keep:
            groups.append(dict(g, claims=keep))
    if n_masked:
        vd["groups"] = groups
        vd["masked_claims"] = n_masked
        vd["masked_claim_text"] = MASKED_TEXT
        vd["summary"] = {v: sum(len(g["claims"]) for g in groups if g.get("verdict") == v) for v in (vd.get("summary") or {})}
    nums = out.get("numbers") if isinstance(out.get("numbers"), dict) else {}
    out["numbers"] = {k: v for k, v in nums.items() if not any(k.startswith(p) for p in prefixes)}
    for key in ("corrections", "corrections_top"):
        for c in out.get(key) or []:
            if isinstance(c, dict) and any(style.poll_words(str(c.get(k) or "")) for k in ("before", "after", "why")):
                hits += 1
                c.update({k: MASKED_TEXT for k in ("before", "after", "why")}, masked=True)
    for c in (out.get("spillover") or {}).get("similar_cases") or []:
        if isinstance(c, dict) and style.poll_words(str(c.get("text") or "")):
            hits += 1
            c.update(text=MASKED_TEXT, masked=True)
    # 출처의 글(제목, 발행처, 주소)과 키워드는 가림 표시가 없으니 판세 낱말이 있으면 가린다 — 셋 가운데 하나에만 있어도 셋 다
    for src in _all_sources(out):
        if any(style.poll_words(str(src.get(k) or "")) for k in SOURCE_TEXT_KEYS):
            hits += 1
            src.update({k: MASKED_TEXT for k in ("title", "by") if k in src}, masked=True)
            if "url" in src:
                src["url"] = ""
    kws = out.get("keywords")
    if isinstance(kws, list) and any(style.poll_words(str(k)) for k in kws):
        hits += 1
        out["keywords"] = [k for k in kws if not style.poll_words(str(k))]
    if hits:
        keep = _src_ids(kept_items) | {e for v in out["numbers"].values() for e in model.number_evidence_ids(v)}
        out["sources"] = [s for s in out.get("sources") or [] if s.get("id") in keep or s.get("id") not in gone]
        out["masked"] = {"rule_version": RULE_VERSION, "at": str(now), "original_body_hash": digest.body_hash(body),
                         "reason": "선거일 엿새 전부터 투표 마감까지 판세를 말하는 내용을 가린다(기간 전에 내보낸 출력도 가린다)"}
    return out
