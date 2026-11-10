#!/usr/bin/env python3
"""소재 카드·클레임 레코드 — 저장 위치·스키마 검증·배지 계산·상태 전이.

정본(비공개): private/desk/cards/<card_id>.yaml · private/desk/claims/<날짜>/<card_id>-cN.yaml
공개(발행 승인된 카드만): daily/YYYY/MM/<날짜>_<회차>.md · claims/<날짜>/<card_id>-cN.yaml
규칙의 정본은 docs/methodology.md §2~§4·§7·§8 이고, 여기는 그것을 기계가 검사하게 옮긴 것이다.

공개 여부를 묻는 곳은 전부 `publishable()` 하나만 쓴다 — 승인이 참(bool)이고, 지금 클레임으로 다시 계산한 배지가
확인·추정이며, 승인 때의 내용 지문과 지금 내용이 같을 때만 참이다(승인 뒤에 고친 카드는 다시 승인받아야 한다).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
from datetime import datetime, timedelta, timezone

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
DESK = ROOT / "private" / "desk"
CARDS = DESK / "cards"
CLAIMS = DESK / "claims"
PUB_CLAIMS = ROOT / "claims"
KST = timezone(timedelta(hours=9))

CARD_ID = re.compile(r"^(\d{4}-\d{2}-\d{2})-(am|pm|wk)-(\d{2})$")
CLAIM_ID = re.compile(r"^(\d{4}-\d{2}-\d{2}-(?:am|pm|wk)-\d{2})-c(\d+)$")
STATES = ["제안", "보류", "채택", "PPT 초안", "PPT 완료", "반려"]
STATUSES = ["verified", "credible_estimate", "single_source", "unverified_rumor", "pending"]
BADGE_KO = {"verified": "확인", "credible_estimate": "추정", "single_source": "단독", "unverified_rumor": "루머", "pending": "pending"}
BADGE_LABEL = {"verified": "[공식 확인]", "credible_estimate": "[보도 종합·추정]", "single_source": "[단독·반론 대기]",
               "unverified_rumor": "[주의: 확인 안 된 루머]", "pending": "[검증 대기]"}
PUBLISHABLE = {"verified", "credible_estimate"}
TIERS = ["T1", "T2", "T3", "T4", "T5"]
STAGES = ["여는 장", "우회 도입", "배경", "전개", "반전", "근거 수치", "비교", "해법", "여담", "시사점", "닫는 장"]  # 구성 템플릿 v0 의 단계 어휘
CATEGORIES = ["국제·지정학", "금융·증시", "국내 경제·정책", "사회·문화", "역사·과학·기술", "기타"]  # Notion DB 「주제」 선택지와 같아야 한다
TRIGGERS = ["공식 발표", "예정 일정", "보도", "시장 움직임", "기념일·주기", "트렌드"]
CHECK_KEYS = ["unit_ok", "base_period", "real_vs_nominal", "seasonally_adjusted", "methodology_match", "revision_status",
              "primary_doc_locator", "recalculated", "translation_checked"]
COUNTER_KEYS = ["core_claim", "strongest_counter", "denominator_check", "residual_uncertainty"]
# 승인 지문에서 빼는 칸 — 내용이 아니라 진행 상태이거나 다른 칸에서 계산되는 것
_DIGEST_SKIP_CARD = {"publish", "history", "revision", "state", "rank", "badge", "badge_note", "discovery"}
_DIGEST_SKIP_CLAIM = {"revision"}


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _real_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def card_path(card_id: str) -> pathlib.Path:
    return CARDS / f"{card_id}.yaml"


def claim_path(claim_id: str, public: bool = False) -> pathlib.Path:
    m = CLAIM_ID.match(claim_id)
    if not m:
        raise ValueError(f"클레임 ID 형식 오류: {claim_id}")
    return (PUB_CLAIMS if public else CLAIMS) / m.group(1)[:10] / f"{claim_id}.yaml"


def load_yaml(p: pathlib.Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def save_yaml(p: pathlib.Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")


def load_card(card_id: str) -> dict:
    return load_yaml(card_path(card_id))


def cards_for(date: str, slot: str) -> list[dict]:
    out = [load_yaml(p) for p in sorted(CARDS.glob(f"{date}-{slot}-*.yaml"))]
    return sorted(out, key=lambda c: (c.get("rank") or 99, c.get("card_id", "")))


def claims_for(card_id: str) -> list[dict]:
    d = CLAIMS / card_id[:10]
    out = [load_yaml(p) for p in sorted(d.glob(f"{card_id}-c*.yaml"))] if d.exists() else []
    return sorted(out, key=lambda c: int(CLAIM_ID.match(c["claim_id"]).group(2)))


def _ledger() -> pathlib.Path:
    return CARDS.parent / "issued_ids.json"


def next_ids(date: str, slot: str, n: int) -> list[str]:
    """새 카드 ID n개를 발급하고 대장에 적는다. 한번 내준 번호는 파일을 지워도, 저장 전에 다시 불러도 재사용하지 않는다."""
    if not _real_date(date) or slot not in ("am", "pm", "wk") or n < 1:
        raise ValueError(f"날짜·회차·개수 오류: {date} {slot} {n}")
    led = _ledger()
    issued: list[str] = json.loads(led.read_text(encoding="utf-8")) if led.exists() else []   # 읽지 못하면 예외 — 빈 대장으로 넘기지 않는다
    prefix = f"{date}-{slot}-"
    used = {int(i[len(prefix):]) for i in issued if i.startswith(prefix)}
    used |= {int(CARD_ID.match(p.stem).group(3)) for p in CARDS.glob(f"{prefix}*.yaml") if CARD_ID.match(p.stem)}
    start = max(used, default=0) + 1
    if start + n - 1 > 99:
        raise ValueError(f"{prefix}NN 번호가 99 를 넘는다 — 한 회차에 카드를 그만큼 만들지 않는다")
    ids = [f"{prefix}{i:02d}" for i in range(start, start + n)]
    led.parent.mkdir(parents=True, exist_ok=True)
    tmp = led.with_suffix(".tmp")
    tmp.write_text(json.dumps(issued + ids, ensure_ascii=False, indent=0), encoding="utf-8")
    os.replace(tmp, led)
    return ids


# ── 검증 ─────────────────────────────────────────────────────────────

def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


def _good_cross(x) -> bool:
    return (isinstance(x, dict) and str(x.get("url", "")).startswith("http") and x.get("tier") in TIERS
            and not _blank(x.get("publisher")) and isinstance(x.get("same_origin_as_source"), bool))


def _independent_cross(c: dict) -> list[dict]:
    """원출처가 다르고 T1~T3 인 교차 출처만 센다."""
    return [x for x in (c.get("cross_check") or []) if _good_cross(x) and x["same_origin_as_source"] is False and x["tier"] in ("T1", "T2", "T3")]


def validate_claim(c: dict, deep: bool = True) -> list[str]:
    """클레임 한 건. deep=True(상위 카드)는 checks·counter 까지 본다."""
    e: list[str] = []
    cid = c.get("claim_id", "")
    m = CLAIM_ID.match(cid) if isinstance(cid, str) else None
    if not m or not _real_date(m.group(1)[:10]):
        return [f"{cid or '(ID 없음)'}: claim_id 형식 오류"]
    if c.get("card_id") != m.group(1):
        e.append(f"{cid}: card_id 가 claim_id 와 다름")
    if _blank(c.get("text")):
        e.append(f"{cid}: text 없음")
    if _blank(c.get("observed")):
        e.append(f"{cid}: observed(원문에 적힌 값 그대로) 없음")
    src = c.get("source") or {}
    tier = src.get("tier")
    if not str(src.get("url", "")).startswith("http"):
        e.append(f"{cid}: source.url 없음")
    if tier not in TIERS:
        e.append(f"{cid}: source.tier 오류({tier})")
    for k in ("publisher", "accessed"):
        if _blank(src.get(k)):
            e.append(f"{cid}: source.{k} 없음")
    for i, x in enumerate(c.get("cross_check") or [], 1):
        if not _good_cross(x):
            e.append(f"{cid}: cross_check {i} 의 url·tier·publisher·same_origin_as_source 누락")
    st = c.get("status")
    if st not in STATUSES:
        e.append(f"{cid}: status 오류({st})")
    hv = c.get("human_verified")
    if not isinstance(hv, bool):
        e.append(f"{cid}: human_verified 는 true/false")
    if hv is True and (_blank(c.get("human_verified_at")) or _blank(c.get("human_verified_by"))):
        e.append(f"{cid}: human_verified_at·human_verified_by 없음")
    if not isinstance(c.get("revision"), int):
        e.append(f"{cid}: revision 없음")
    ch = c.get("checks") or {}
    ind = _independent_cross(c)
    if tier == "T5" and st not in ("pending", "unverified_rumor"):
        e.append(f"{cid}: T5 출처는 인용할 수 없다 — pending·unverified_rumor 만")
    if st == "verified":
        if hv is not True:
            e.append(f"{cid}: verified 인데 human_verified 가 아님 — 사람 육안 대조 전에는 pending")
        if tier not in ("T1", "T2") and not (tier == "T3" and ind):
            e.append(f"{cid}: verified 는 T1/T2 원문이거나, 원출처가 다른 교차 출처가 있는 T3 여야 한다")
        if ch.get("unit_ok") is not True:
            e.append(f"{cid}: verified 인데 checks.unit_ok 가 true 가 아님")
        if ch.get("methodology_match") is False or ch.get("translation_checked") is False:
            e.append(f"{cid}: verified 인데 methodology_match·translation_checked 가 false")
        if ch.get("recalculated") not in (True, "n/a"):
            e.append(f"{cid}: verified 인데 checks.recalculated 가 true 도 n/a(재계산할 것이 없는 직접 인용)도 아님")
        for k in ("base_period", "revision_status", "primary_doc_locator"):
            if _blank(ch.get(k)):
                e.append(f"{cid}: verified 인데 checks.{k} 비어 있음")
    if st == "credible_estimate":
        if tier not in ("T2", "T3", "T4"):
            e.append(f"{cid}: credible_estimate 는 T2~T4 출처에 쓴다(T1 원문이면 verified 대상)")
        if tier in ("T3", "T4") and not ind:
            e.append(f"{cid}: credible_estimate(T3·T4)는 원출처가 다른 교차 출처 1건 이상")
    if deep:
        for k in CHECK_KEYS:
            if k not in ch:
                e.append(f"{cid}: checks.{k} 없음")
        if _blank(ch.get("primary_doc_locator")):
            e.append(f"{cid}: checks.primary_doc_locator(원문 위치) 비어 있음")
        ct = c.get("counter") or {}
        for k in COUNTER_KEYS:
            if _blank(ct.get(k)):
                e.append(f"{cid}: counter.{k} 비어 있음")
    return e


def badge_of(claims: list[dict]) -> str:
    """카드 배지 = 클레임 상태 중 가장 약한 것. 클레임이 없거나 모르는 상태가 섞이면 pending."""
    st = [c.get("status") for c in claims]
    if not st or any(s not in STATUSES or s == "pending" for s in st):
        return "pending"
    for weak in ("unverified_rumor", "single_source", "credible_estimate"):
        if weak in st:
            return weak
    return "verified"


def content_digest(card: dict, claims: list[dict]) -> str:
    """승인 대상 내용의 지문 — 카드 본문과 그 클레임 전부. 진행 상태 칸은 뺀다."""
    core = {k: v for k, v in card.items() if k not in _DIGEST_SKIP_CARD}
    cl = [{k: v for k, v in c.items() if k not in _DIGEST_SKIP_CLAIM} for c in sorted(claims, key=lambda c: str(c.get("claim_id")))]
    raw = json.dumps([core, cl], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=16).hexdigest()


def publishable(card: dict, claims: list[dict]) -> bool:
    """공개해도 되는가 — 보고서·Notion·승인 경로가 모두 이 함수만 쓴다."""
    pub = card.get("publish") or {}
    if pub.get("approved") is not True:
        return False
    badge = badge_of(claims)
    if badge not in PUBLISHABLE or card.get("badge") != badge:
        return False
    ids = {c.get("claim_id") for c in claims}
    if not card.get("data") or any(d.get("claim_id") not in ids for d in card["data"]):
        return False   # 공개되는 수치는 전부 클레임 레코드가 있어야 한다
    if any(validate_claim(c, deep=(card.get("depth") == "full")) for c in claims):
        return False
    return pub.get("digest") == content_digest(card, claims)


def validate_card(card: dict, claims: list[dict]) -> list[str]:
    e: list[str] = []
    cid = card.get("card_id", "")
    m = CARD_ID.match(cid) if isinstance(cid, str) else None
    if not m or not _real_date(m.group(1)):
        return [f"{cid or '(ID 없음)'}: card_id 형식 오류"]
    if card.get("date") != m.group(1) or card.get("slot") != m.group(2):
        e.append(f"{cid}: date·slot 이 card_id 와 다름")
    if card.get("state") not in STATES:
        e.append(f"{cid}: state 오류({card.get('state')})")
    if not isinstance(card.get("revision"), int):
        e.append(f"{cid}: revision 없음")
    if card.get("category") not in CATEGORIES:
        e.append(f"{cid}: category 는 {'|'.join(CATEGORIES)} 중 하나({card.get('category')})")
    depth = card.get("depth")
    if depth not in ("full", "light"):
        e.append(f"{cid}: depth 는 full|light")
    titles = card.get("titles") or []
    if len(titles) < 2 or any(_blank(t) or not isinstance(t, str) for t in titles):
        e.append(f"{cid}: ① 제목 후보 2개 이상")
    if _blank(card.get("hook")):
        e.append(f"{cid}: ② 한 줄 훅 없음")
    wt = card.get("why_today") or {}
    if _blank(wt.get("text")) or not _real_date(wt.get("trigger_date")):
        e.append(f"{cid}: ③ 왜 오늘인가(text·trigger_date) 없음")
    if wt.get("trigger_type") not in TRIGGERS:
        e.append(f"{cid}: ③ trigger_type 오류({wt.get('trigger_type')})")
    data = card.get("data") or []
    by_id = {c.get("claim_id"): c for c in claims}
    if depth == "full" and len(data) < 3:
        e.append(f"{cid}: ④ 핵심 데이터 3개 이상(상위 카드)")
    for i, d in enumerate(data, 1):
        if _blank(d.get("text")) or not str(d.get("url", "")).startswith("http") or _blank(d.get("source_name")) or d.get("tier") not in TIERS:
            e.append(f"{cid}: ④ 데이터 {i} 의 text·source_name·url·tier 누락")
        if depth == "full" and d.get("tier") not in ("T1", "T2"):
            e.append(f"{cid}: ④ 데이터 {i} 의 출처 등급이 T1/T2 가 아님({d.get('tier')})")
        link = d.get("claim_id")
        if depth == "full" and not link:
            e.append(f"{cid}: ④ 데이터 {i} 의 클레임 레코드 없음(claim_id 비어 있음)")
        if link:
            cl = by_id.get(link)
            if cl is None:
                e.append(f"{cid}: ④ 데이터 {i} 의 클레임 레코드 없음({link})")
            else:
                src = cl.get("source") or {}
                if d.get("url") != src.get("url") or d.get("tier") != src.get("tier"):
                    e.append(f"{cid}: ④ 데이터 {i} 의 url·tier 가 연결된 클레임({link})과 다름")
    if depth == "light" and not (card.get("sources") or data):
        e.append(f"{cid}: 1차 출처 링크 1개 이상")
    for s in card.get("sources") or []:
        if not str(s.get("url", "")).startswith("http") or s.get("tier") not in TIERS or _blank(s.get("name")):
            e.append(f"{cid}: sources 항목의 name·url·tier 오류")
    badge = card.get("badge")
    if badge not in STATUSES:
        e.append(f"{cid}: ⑤ 배지 오류({badge})")
    elif badge != badge_of(claims):
        e.append(f"{cid}: ⑤ 배지({badge})가 클레임 상태({badge_of(claims)})와 다름")
    cov = card.get("coverage") or {}
    if _blank(cov.get("summary")):
        e.append(f"{cid}: ⑥ 기존 커버리지 요약 없음")
    if _blank(cov.get("searched")):
        e.append(f"{cid}: ⑥ 대조에 쓴 낱말(searched) 없음 — 찾아보지 않은 것과 없는 것을 구분한다")
    for v in cov.get("videos") or []:
        if _blank(v.get("video_id")) or _blank(v.get("title")) or not _real_date(v.get("date")):
            e.append(f"{cid}: ⑥ videos 항목의 video_id·title·date 오류")
    sens = card.get("sensitivity") or {}
    if sens.get("level") not in ("GREEN", "YELLOW"):
        e.append(f"{cid}: ⑦ 민감도는 GREEN|YELLOW (RED 는 카드로 올리지 않는다)")
    if sens.get("level") == "YELLOW" and _blank(sens.get("reason")):
        e.append(f"{cid}: ⑦ YELLOW 사유 없음")
    outline = card.get("outline") or []
    if len(outline) < 5:
        e.append(f"{cid}: ⑧ 예상 구성 5단계 이상")
    for o in outline:
        if o.get("stage") not in STAGES or _blank(o.get("note")):
            e.append(f"{cid}: ⑧ 단계 이름·내용 오류({o.get('stage')})")
    if outline and not any(o.get("stage") == "반전" for o in outline):
        e.append(f"{cid}: ⑧ 반전 단계 없음")
    ang = card.get("angles") or {}
    for k in ("twist", "bridge"):
        if _blank(ang.get(k)):
            e.append(f"{cid}: ⑨ {k} 없음")
    if _blank(ang.get("parallel")) and _blank(ang.get("analogy")):
        e.append(f"{cid}: ⑨ 평행 사례나 비유 중 하나")
    risks = card.get("risks") or []
    if not risks or any(_blank(r) for r in risks):
        e.append(f"{cid}: ⑩ 리스크 없음")
    pub = card.get("publish") or {}
    if "approved" in pub and not isinstance(pub["approved"], bool):
        e.append(f"{cid}: publish.approved 는 true/false (문자열 불가)")
    elif pub.get("approved") is True and not publishable(card, claims):
        e.append(f"{cid}: 발행 승인 뒤 내용이 바뀌었거나 배지가 {badge_of(claims)} 로 내려갔다 — 다시 승인받거나 `withdraw` 로 철회한다")
    for c in claims:
        e += validate_claim(c, deep=(depth == "full"))
    return e


# ── 상태 전이(사용자 지시가 있을 때만 부른다) ─────────────────────────

def _touch(card: dict, event: str) -> None:
    card["revision"] = int(card.get("revision", 1)) + 1
    card.setdefault("history", []).append({"at": now_kst(), "event": event})


def set_state(card_id: str, state: str) -> dict:
    if state not in STATES:
        raise ValueError(f"상태 오류: {state}")
    card = load_card(card_id)
    card["state"] = state
    _touch(card, f"state → {state}")
    save_yaml(card_path(card_id), card)
    return card


def human_verify(claim_ids: list[str], by: str) -> list[dict]:
    """사람이 원문과 눈으로 대조했다고 말한 클레임만 올린다. 모델·루틴은 이 함수를 스스로 부르지 않는다.
    올린 뒤의 레코드가 검증을 통과하지 못하면(단위 확인 실패·T5 출처 등) 아무것도 저장하지 않고 멈춘다."""
    if _blank(by):
        raise ValueError("대조한 사람(by)이 필요하다")
    staged = []
    for cid in claim_ids:
        c = load_yaml(claim_path(cid))
        if not c:
            raise FileNotFoundError(f"클레임 없음: {cid}")
        tier = (c.get("source") or {}).get("tier")
        if tier == "T5":
            raise ValueError(f"{cid}: T5 출처는 사람 대조로도 올릴 수 없다 — T1~T3 로 역추적한 출처로 바꿔야 한다")
        c["human_verified"], c["human_verified_at"], c["human_verified_by"] = True, now_kst(), by
        if c.get("status") == "pending":
            ind = _independent_cross(c)
            c["status"] = "verified" if (tier in ("T1", "T2") or (tier == "T3" and ind)) else "credible_estimate" if (tier == "T4" and ind) else "single_source"
        c["revision"] = int(c.get("revision", 1)) + 1
        errs = validate_claim(c, deep=True)
        if errs:
            raise ValueError(f"{cid}: 올릴 수 없다 — " + "; ".join(errs[:4]))
        staged.append(c)
    for c in staged:
        save_yaml(claim_path(c["claim_id"]), c)
    for card_id in sorted({c["card_id"] for c in staged}):
        card = load_card(card_id)
        card["badge"] = badge_of(claims_for(card_id))
        _touch(card, f"사람 대조 {sum(c['card_id'] == card_id for c in staged)}건 → 배지 {card['badge']}")
        save_yaml(card_path(card_id), card)
    return staged


def approve_publish(card_id: str, by: str) -> dict:
    """공개 발행 승인 — 배지가 확인·추정이 아니거나 검증 오류가 있으면 거부한다. 승인 때의 내용 지문을 함께 적는다."""
    if _blank(by):
        raise ValueError("승인한 사람(by)이 필요하다")
    card = load_card(card_id)
    claims = claims_for(card_id)
    badge = badge_of(claims)
    if badge not in PUBLISHABLE:
        raise PermissionError(f"{card_id}: 배지가 {badge} — 공개 발행은 verified·credible_estimate 만 (docs/methodology.md §8)")
    draft = {**card, "badge": badge, "publish": {"approved": False}}
    errs = validate_card(draft, claims)
    ids = {c["claim_id"] for c in claims}
    if any(d.get("claim_id") not in ids for d in card.get("data") or []) or not card.get("data"):
        errs.append(f"{card_id}: 공개되는 수치는 전부 클레임 레코드가 있어야 한다")
    if errs:
        raise ValueError(f"{card_id}: 검증 오류 {len(errs)}건 — " + "; ".join(errs[:3]))
    card["badge"] = badge
    _touch(card, "공개 발행 승인")
    card["publish"] = {"approved": True, "approved_at": now_kst(), "by": by, "digest": content_digest(card, claims)}
    save_yaml(card_path(card_id), card)
    for c in claims:
        dst = claim_path(c["claim_id"], public=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(claim_path(c["claim_id"]), dst)
    return card


def withdraw(card_id: str, by: str, reason: str) -> dict:
    """발행 철회 — 승인을 내리고 공개 폴더의 클레임 사본을 치운다. 발행본에는 '철회' 줄로 남는다(정정 기록은 docs/corrections.md 에 사람이 적는다)."""
    if _blank(by) or _blank(reason):
        raise ValueError("철회한 사람(by)과 사유(reason)가 필요하다")
    card = load_card(card_id)
    card["publish"] = {"approved": False, "withdrawn_at": now_kst(), "by": by, "reason": reason}
    _touch(card, f"발행 철회 — {reason}")
    save_yaml(card_path(card_id), card)
    d = PUB_CLAIMS / card_id[:10]
    if d.exists():
        for p in d.glob(f"{card_id}-c*.yaml"):
            p.unlink()
    return card
