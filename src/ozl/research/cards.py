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
RELATIONS = ("배경", "후속", "전제 변화", "반대 증거", "같은 주제")  # ⑥ 이 채널이 전에 다룬 영상과 오늘 소재의 관계
RELATION_MAX = 8      # 관계를 붙인 영상은 카드당 이만큼까지
COV_GIST_MAX = 60     # ⑥ 영상 요지 한 줄의 글자 수 상한
YT_ID = re.compile(r"[A-Za-z0-9_-]{11}")   # relation 을 붙인 영상의 video_id 모양
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
            if "verification" not in c:
                e.append(f"{cid}: verified 인데 human_verified 가 아님 — 사람 육안 대조 전에는 pending")
            else:
                e += [f"{cid}: {x}" for x in machine_struct_errors(c)]
        if tier not in ("T1", "T2") and not (tier == "T3" and ind):
            e.append(f"{cid}: verified 는 T1/T2 원문이거나, 원출처가 다른 교차 출처가 있는 T3 여야 한다")
        if ch.get("unit_ok") is not True and not (hv is not True and _is_na(ch.get("unit_ok")) and not observed_has_quantity(c)):
            e.append(f"{cid}: verified 인데 checks.unit_ok 가 true 가 아님"
                     + (" — n/a 는 observed 에 수량이 하나도 없는 기계 대조 기록(수치 없는 인용)에서만 받는다" if _is_na(ch.get("unit_ok")) else ""))
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


# ── 기계 대조(사람 대조 대신 저장한 원문 사본으로) ──────────────────────
# 설계 정본: ~/.claude/plans/ozl_redesign_plan_20261113_014132.md 3-2절. `verification` 칸은 새로 쓰는 기록에만 생긴다
# (칸이 없는 옛 기록은 종전과 똑같이 판정된다 · 이미 발행한 기록에 칸을 더하면 내용 지문이 바뀌어 승인이 풀린다).
#
#   verification:
#     method: machine
#     capture: {url, final_url, fetched_at, status, content_type, charset, bytes, sha256, path, kind, text_path}   # capture 명령이 채운다
#     match: {found, count, offsets, context}            # 프로그램이 채운다(machine_verify 가 다시 계산해 덮어쓴다)
#     image: {path, reason}                               # 그림을 못 만들면 path 가 비고 reason 에 사유
#     author: {by, located}                               # 쓴 쪽. located 는 observed 가 사본에 여러 번 나올 때 어느 자리인지 가리키는 대목
#     recheck: {by, located, checks: {unit, as_of, status, population, speaker}, at}   # 쓴 쪽과 다른 에이전트가 채운다
#     verified_at: …                                      # machine_verify 가 채운다
GRADE_HUMAN = "확인"
GRADE_MACHINE = "원문 일치"
RECHECK_STATUS = ("확정", "잠정", "전망", "주장")
_REVISION_TO_STATUS = {"final": "확정", "preliminary": "잠정"}   # 그 밖의 값(n/a 등)은 견주지 않고 채워졌는가만 본다


def _same_agent(a, b) -> bool:
    return str(a or "").strip().casefold() == str(b or "").strip().casefold()


def machine_struct_errors(c: dict) -> list[str]:
    """기계 대조로 verified 가 된 기록의 구조 검사(파일 재해시·문구 재대조는 machine_verify 가 한다). 빈 목록이면 구조는 맞다."""
    e: list[str] = []
    v = c.get("verification")
    if not isinstance(v, dict) or v.get("method") != "machine":
        return ["verified 인데 human_verified 도 아니고 verification.method 가 machine 도 아님"]
    src = c.get("source") or {}
    if src.get("tier") not in ("T1", "T2"):
        e.append(f"기계 대조는 T1/T2 출처만(지금 {src.get('tier')})")
    cap = v.get("capture") or {}
    for k in ("url", "fetched_at", "sha256", "path", "kind"):
        if _blank(cap.get(k)):
            e.append(f"verification.capture.{k} 없음")
    if cap.get("url") and cap.get("url") != src.get("url"):
        e.append("verification.capture.url 이 source.url 과 다름")
    if (v.get("match") or {}).get("found") is not True:
        e.append("verification.match.found 가 true 가 아님")
    au, rc = v.get("author") or {}, v.get("recheck") or {}
    if _blank(au.get("by")):
        e.append("verification.author.by 없음")
    if _blank(rc.get("by")):
        e.append("verification.recheck.by 없음")
    elif _same_agent(au.get("by"), rc.get("by")):
        e.append("쓴 쪽과 재대조한 쪽의 식별자가 같다")
    if _blank(rc.get("located")):
        e.append("verification.recheck.located 없음")
    rch = rc.get("checks") or {}
    for k in ("unit", "as_of", "status"):
        if _blank(rch.get(k)):
            e.append(f"verification.recheck.checks.{k} 비어 있음")
    if not _blank(rch.get("status")) and rch.get("status") not in RECHECK_STATUS:
        e.append(f"verification.recheck.checks.status 는 {'|'.join(RECHECK_STATUS)}")
    if _blank(v.get("verified_at")):
        e.append("verification.verified_at 없음")
    return e


def grade_label(c: dict) -> str:
    """기록 한 건의 표시 문구. 사람이 대조한 verified 만 '확인', 기계 대조로 올라간 verified 는 「원문 일치」."""
    st = c.get("status")
    if st == "verified":
        if c.get("human_verified") is True:
            return GRADE_HUMAN
        return GRADE_MACHINE if "verification" in c and not machine_struct_errors(c) else "검증 오류"
    return BADGE_KO.get(st, "?")


_PERIOD_FORMS = [
    ("date", re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})|(\d{4})년 ?(\d{1,2})월 ?(\d{1,2})일")),
    ("month", re.compile(r"(\d{4})-(\d{1,2})|(\d{4})년 ?(\d{1,2})월")),
    ("quarter", re.compile(r"(\d{4})-[Qq]([1-4])|(\d{4})년 ?([1-4])분기")),
    ("year", re.compile(r"(\d{4})년?")),
]


def _period_one(s: str):
    for kind, rx in _PERIOD_FORMS:
        m = rx.fullmatch(s)
        if m:
            return (kind,) + tuple(int(x) for x in m.groups() if x is not None)
    return None


def _period_key(s) -> tuple:
    """기준 시점의 종류를 보존한 키 — 연 · 분기 · 월 · 날짜 · 범위(A~B, 양끝을 각각 판독). 종류가 다르면 다른 시점이다
    ('2026년 1월' ≠ '2026년 1분기'). 판독하지 못하는 표기는 공백만 정리한 문자열로 견준다."""
    t = re.sub(r"\s+", " ", str(s)).strip()
    one = _period_one(t)
    if one:
        return one
    if t.count("~") == 1:
        a, b = (_period_one(x.strip()) for x in t.split("~"))
        if a and b:
            return ("range", a, b)
    return ("s", t.casefold())


def _is_na(v) -> bool:
    return isinstance(v, str) and v.strip().casefold() == "n/a"


def observed_has_quantity(c: dict) -> bool:
    """observed 에 대조가 필요한 수량(수량·기간·수량 낱말 — numbers.claim_tokens, 덱 숫자 검사의 needs_claim 과 같은 기준)이 있는가.
    달력(2026년 3월)·식별자는 수량으로 치지 않는다."""
    from ozl.render import numbers as N
    return bool(N.claim_tokens(str(c.get("observed") or "")))


def recheck_check_errors(c: dict) -> list[str]:
    """재대조한 쪽의 맥락 칸을 쓴 쪽의 checks 와 견준다. 견줄 수 없는 칸은 채워졌는가만 본다."""
    e: list[str] = []
    ch = c.get("checks") or {}
    rch = ((c.get("verification") or {}).get("recheck") or {}).get("checks") or {}
    for k in ("unit", "as_of", "status"):
        if _blank(rch.get(k)):
            e.append(f"재대조 맥락 칸 {k} 비어 있음")
    if e:
        return e
    has_q = observed_has_quantity(c)
    if not has_q and _is_na(ch.get("unit_ok")):   # 수치 없는 인용: 쓴 쪽 n/a 면 재대조 단위도 n/a 여야 한다
        if not _is_na(rch["unit"]):
            e.append(f"쓴 쪽 checks.unit_ok 는 n/a(수치 없는 인용)인데 재대조는 단위 {rch['unit']!r} 를 적었다 — 단위 판단이 어긋난다")
    elif ch.get("unit_ok") is not True:
        e.append("쓴 쪽 checks.unit_ok 가 true 가 아닌데 재대조는 단위를 적었다 — 단위 판단이 어긋난다")
    if has_q and _is_na(rch["unit"]):
        e.append("observed 에 수량이 있는데 재대조 단위가 n/a 다 — 단위를 적는다")
    bp = ch.get("base_period")
    if not _blank(bp) and str(bp).strip().casefold() != "n/a" and _period_key(bp) != _period_key(rch["as_of"]):
        e.append(f"기준 시점 불일치: 쓴 쪽 base_period {bp!r} · 재대조 as_of {rch['as_of']!r}")
    if rch["status"] not in RECHECK_STATUS:
        e.append(f"재대조 status 값 오류({rch['status']}) — {'|'.join(RECHECK_STATUS)}")
    want = _REVISION_TO_STATUS.get(str(ch.get("revision_status") or "").strip())
    if want and rch["status"] != want:
        e.append(f"확정·잠정 불일치: 쓴 쪽 revision_status {ch.get('revision_status')!r} → {want} · 재대조 {rch['status']}")
    return e


def _resolve(p) -> pathlib.Path:
    q = pathlib.Path(str(p))
    return q if q.is_absolute() else ROOT / q


def _inside_captures(p) -> bool:
    """사본 경로로 받는 것: '..' 조각이 없고, 풀어 쓴 경로의 조상 폴더 가운데 이름이 captures 인 것이 있다.
    기록에 해시만 맞게 적으면 아무 로컬 파일이나 사본으로 인정되는 길을 막는다."""
    raw = pathlib.Path(str(p))
    if ".." in raw.parts:
        return False
    return any(a.name == "captures" for a in _resolve(raw).resolve().parents)


def _unique_span(norm_find: dict, what: str, errs: list[str]):
    if not norm_find["found"]:
        errs.append(f"{what} 가 사본 글에 없다")
        return None
    if norm_find["count"] > 1:
        errs.append(f"{what} 가 사본 글에 {norm_find['count']}번 나와 자리를 하나로 정할 수 없다 — 더 긴 대목을 적는다")
        return None
    m = norm_find["matches"][0]
    return (m["offset"], m["end"])


_TEXT_CACHE: dict[tuple[str, str, str, str], dict] = {}   # (사본 경로, sha256, 종류, charset) → 뽑은 글. 덱 검사가 같은 사본을 장마다 다시 읽지 않게


_STRONG_KINDS = {"html", "pdf", "xlsx", "hwpx"}   # 바이트만으로 가를 수 있는 종류


def copy_source(c: dict) -> dict:
    """기록의 원문 사본을 읽는 단 하나의 길 — machine_check 와 덱 검사(spec.copy_text)·빌드가 모두 이것만 쓴다.
    {has(사본 묶음이 있는가), ok, text, reason, path, kind, cap}. 경로 규칙(captures 안 · '..' 없음) → 파일 있음 → 재해시 →
    종류 재판별(바이트가 html·pdf·zip 이면 기록의 kind 와 같아야 한다 — kind 만 바꿔 숨긴 글을 꺼내는 길을 막는다) → 추출(캐시)."""
    from . import capture as K
    v = c.get("verification")
    cap = v.get("capture") if isinstance(v, dict) else None
    out = {"has": False, "ok": False, "text": None, "reason": "", "path": None, "kind": "", "cap": cap if isinstance(cap, dict) else {}}
    if not isinstance(cap, dict) or _blank(cap.get("path")):
        out["reason"] = f"사본 파일이 없다({(cap or {}).get('path') if isinstance(cap, dict) else None})"
        return out
    out["has"] = True
    kind = cap.get("kind")
    if kind not in K.KINDS:
        out["reason"] = f"사본 종류 오류({kind})"
        return out
    for k in ("path", "text_path"):
        if not _blank(cap.get(k)) and not _inside_captures(cap.get(k)):
            out["reason"] = f"사본 경로가 사본 폴더(captures) 밖이다(capture.{k}: {cap.get(k)})"
            return out
    path = _resolve(cap["path"])
    if not path.is_file():
        out["reason"] = f"사본 파일이 없다({cap.get('path')})"
        return out
    if K.sha256_file(path) != cap.get("sha256"):
        out["reason"] = "사본 파일의 sha256 이 기록과 다르다(받은 뒤에 바뀌었다)"
        return out
    with open(path, "rb") as f:
        head = f.read(8192)
    bk = K.byte_kind(head)
    if (bk in _STRONG_KINDS and bk != kind) or (kind in ("pdf", "xlsx", "hwpx") and bk != kind):
        out["reason"] = f"사본 바이트는 {bk or '판별 불가'} 인데 기록의 kind 는 {kind} 다 — 종류를 바꿔 읽지 않는다"
        return out
    key = (str(path), str(cap.get("sha256")), str(kind), str(cap.get("charset") or ""))
    if key not in _TEXT_CACHE:
        _TEXT_CACHE[key] = K.extract_text(path, kind, cap.get("charset") or "")
    ex = _TEXT_CACHE[key]
    out.update(path=path, kind=kind)
    if not ex["ok"]:
        out["reason"] = ex["reason"]
        return out
    out.update(ok=True, text=ex["text"])
    return out


def copy_text(c: dict) -> tuple[bool, str | None, str]:
    """(사본 묶음이 있는가, 사본 글 | None, 못 읽은 사유). copy_source 의 짧은 꼴."""
    r = copy_source(c)
    return r["has"], r["text"], r["reason"]


def machine_check(c: dict, fresh: bool = True) -> tuple[list[str], dict]:
    """기록을 저장한 사본으로 다시 검사한다. (사유 목록, 다시 계산한 match). 기록에 적힌 found·offsets 는 믿지 않는다.
    fresh=True 는 등급을 올리기 전의 검사(pending 이고 사람 대조 전이어야 한다). fresh=False 는 이미 「원문 일치」인 기록을
    쓸 때마다 다시 확인하는 검사다 — 기록 파일에 verified 라고 적혀 있다는 것만으로는 받지 않는다(덱 엄격 모드가 부른다)."""
    from . import capture as K
    errs: list[str] = []
    cid = c.get("claim_id", "?")
    src = c.get("source") or {}
    if src.get("tier") not in ("T1", "T2"):
        errs.append(f"출처 등급이 {src.get('tier')} — 기계 대조는 T1/T2 원문만")
    if fresh:
        if c.get("human_verified") is True:
            errs.append("이미 사람이 대조한 기록이다")
        if c.get("status") != "pending":
            errs.append(f"status 가 pending 이 아니다({c.get('status')})")
    v = c.get("verification")
    if not isinstance(v, dict) or v.get("method") != "machine":
        return errs + ["verification(method: machine) 묶음이 없다 — capture 명령을 먼저 돌린다"], {}
    cap = v.get("capture") or {}
    if cap.get("url") != src.get("url"):
        errs.append("사본을 받은 주소가 source.url 과 다르다")
    src_copy = copy_source(c)
    if not src_copy["ok"]:
        return [f"{cid}: {x}" for x in errs + [src_copy["reason"]]], {}
    text = src_copy["text"]
    obs = K.find_phrase(text, c.get("observed") or "")
    match = {"found": obs["found"], "count": obs["count"], "offsets": [m["offset"] for m in obs["matches"]],
             "context": K.context_of(obs["matches"][0], c["observed"]) if obs["found"] else ""}
    if not obs["found"]:
        errs.append("observed 가 사본 글에 없다(공백만 정리해 비교)")
    au, rc = v.get("author") or {}, v.get("recheck") or {}
    if _blank(au.get("by")):
        errs.append("쓴 쪽 식별자(author.by)가 없다")
    if _blank(rc.get("by")):
        errs.append("재대조한 쪽 식별자(recheck.by)가 없다")
    elif _same_agent(au.get("by"), rc.get("by")):
        errs.append("쓴 쪽과 재대조한 쪽의 식별자가 같다")
    # 쓴 쪽이 가리키는 자리(target)는 observed 가 나온 자리 정확히 하나: observed 가 한 번만 나오거나, author.located 안에 정확히 한 번
    target: tuple[int, int] | None = None
    occ = [(m["offset"], m["end"]) for m in obs["matches"]] if obs["found"] else []
    if occ:
        if _blank(au.get("located")):
            if len(occ) == 1:
                target = occ[0]
            else:
                errs.append(f"observed 가 사본에 {len(occ)}번 나온다 — 쓴 쪽이 author.located 로 어느 자리인지 가리켜야 한다"
                            "(표의 칸이면 그 칸이 든 표의 행 전체(줄의 처음부터 끝까지)를 author.located 에 적는다)")
        else:
            span = _unique_span(K.find_phrase(text, au["located"], cross_tabs=True), "쓴 쪽 대목(author.located)", errs)
            if span:
                inside = [o for o in occ if span[0] <= o[0] and o[1] <= span[1]]
                if len(inside) == 1:
                    target = inside[0]
                elif not inside:
                    errs.append("쓴 쪽 대목(author.located) 안에 observed 가 없다")
                else:
                    errs.append(f"쓴 쪽 대목(author.located) 안에 observed 가 {len(inside)}번 나와 어느 자리인지 정해지지 않는다")
    if _blank(rc.get("located")):
        errs.append("재대조한 쪽 대목(recheck.located)이 없다")
    else:
        span = _unique_span(K.find_phrase(text, rc["located"], cross_tabs=True), "재대조한 쪽 대목(recheck.located)", errs)
        if span and target:
            n_in = sum(1 for o in occ if span[0] <= o[0] and o[1] <= span[1])
            if not (span[0] <= target[0] and target[1] <= span[1]):
                errs.append("재대조한 쪽 대목이 쓴 쪽의 자리(observed 가 나온 자리)를 통째로 담지 않는다")
            elif n_in != 1:
                errs.append(f"재대조한 쪽 대목 안에 observed 가 {n_in}번 나와 같은 자리라고 할 수 없다")
    # 규칙 1: observed 의 대조한 자리와 두 located 는 통째 대목(문장 · 줄 · 표의 칸)이어야 한다 — 발췌가 수량을 자르는 일을 구조로 막는다
    spans = [("observed 의 대조한 자리", target)]
    for what, who in (("쓴 쪽 대목(author.located)", au), ("재대조한 쪽 대목(recheck.located)", rc)):
        if not _blank(who.get("located")):
            f = K.find_phrase(text, who["located"], cross_tabs=True)
            if f["count"] == 1:
                spans.append((what, (f["matches"][0]["offset"], f["matches"][0]["end"])))
    for x, (what, span) in enumerate(spans):
        if span:
            why = K.passage_bounds_error(text, span[0], span[1], allow_row=x > 0)   # located 만 표의 행 전체를 받는다
            if why:
                errs.append(f"{what} 가 통째 대목이 아니다 — 문장(마침표까지)·줄·칸을 통째로 따와야 한다. {why}")
    errs += recheck_check_errors(c)
    if target:   # 대조한 자리 하나 — 문맥·그림은 이 자리의 것이다(첫째 자리가 아니라)
        m = next(x for x in obs["matches"] if (x["offset"], x["end"]) == target)
        match["target"] = {"offset": m["offset"], "end": m["end"], "raw_offset": m["raw_offset"], "page": m["page"],
                           "nth": obs["matches"].index(m)}
        match["context"] = K.context_of(m, c["observed"])
    return [f"{cid}: {x}" for x in errs], match


def machine_verify(claim_id: str, path: pathlib.Path | str | None = None, save: bool = True) -> dict:
    """저장한 원문 사본과 재대조 기록을 프로그램이 다시 검사해 통과하면 status 를 verified 로 올린다(human_verified 는 false 그대로).
    {ok, claim_id, reasons, claim}. 못 채우면 아무것도 저장하지 않는다. path 를 주면 그 파일(시험 사본 등)을 읽고 쓴다 —
    그때는 카드 파일을 건드리지 않는다. 정본 폴더의 기록이면 human_verify 와 같게 카드 배지를 다시 계산한다."""
    p = pathlib.Path(path) if path else claim_path(claim_id)
    if not p.is_file():
        return {"ok": False, "claim_id": claim_id, "reasons": [f"{claim_id}: 기록 파일 없음({p})"], "claim": None}
    c = load_yaml(p)
    if c.get("claim_id") != claim_id:
        return {"ok": False, "claim_id": claim_id, "reasons": [f"{claim_id}: 파일의 claim_id 가 다르다({c.get('claim_id')})"], "claim": None}
    reasons, match = machine_check(c)
    if not reasons:
        new = json.loads(json.dumps(c, ensure_ascii=False, default=str))
        new["verification"]["match"] = match
        new["verification"]["verified_at"] = now_kst()
        new["status"] = "verified"
        new["human_verified"] = False
        new["revision"] = int(c.get("revision", 1)) + 1
        reasons = validate_claim(new, deep=True)
        if not reasons:
            c = new
    if reasons:
        return {"ok": False, "claim_id": claim_id, "reasons": reasons, "claim": None}
    if save:
        save_yaml(p, c)
        if path is None and card_path(c["card_id"]).is_file():
            card = load_card(c["card_id"])
            card["badge"] = badge_of(claims_for(c["card_id"]))
            _touch(card, f"기계 대조 1건({claim_id}) → 배지 {card['badge']}")
            save_yaml(card_path(c["card_id"]), card)
    return {"ok": True, "claim_id": claim_id, "reasons": [], "claim": c}


def _verified_word(card: dict, claims: list[dict] | None) -> str | None:
    """카드 배지가 verified 일 때 넘겨받은 기록으로 다시 판정한다: 기록이 하나 이상이고 전부 verified 이면서 사람 대조 → 'human',
    전부 verified 인데 기계 대조가 섞임 → 'machine', 그 밖 → badge_of(claims) 의 상태(낡은 배지로 '확인'을 붙이지 않는다)."""
    cl = claims if claims is not None else claims_for(card["card_id"])
    if cl and all(c.get("status") == "verified" for c in cl):
        return "human" if all(c.get("human_verified") is True for c in cl) else "machine"
    return badge_of(cl)


def badge_ko(card: dict, claims: list[dict] | None = None) -> str:
    """카드 배지의 표시 낱말. verified 는 기록으로 다시 판정한다(사람 대조만 '확인', 기계 대조가 섞이면 「원문 일치」)."""
    b = card.get("badge")
    if b != "verified":
        return BADGE_KO.get(b, b or "")
    w = _verified_word(card, claims)
    return GRADE_HUMAN if w == "human" else GRADE_MACHINE if w == "machine" else BADGE_KO.get(w, w)


def badge_label(card: dict, claims: list[dict] | None = None) -> str:
    b = card.get("badge")
    if b != "verified":
        return BADGE_LABEL[b]
    w = _verified_word(card, claims)
    return BADGE_LABEL["verified"] if w == "human" else f"[{GRADE_MACHINE}]" if w == "machine" else BADGE_LABEL[w]


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
    if pub.get("digest") != content_digest(card, claims):
        return False
    # 기계 대조 기록은 구조만 보지 않고 저장한 사본으로 증거를 다시 검사한다(사본 없는 위조 묶음을 막는다).
    # 사람 대조 기록과 verification 없는 옛 기록은 이 검사를 받지 않는다(종전 판정 그대로).
    return not any(machine_check(c, fresh=False)[0] for c in claims
                   if c.get("status") == "verified" and c.get("human_verified") is not True)


def publish_status(card: dict, claims: list[dict]) -> str:
    """발행 상태 한 낱말 — 발행·철회·미발행. 판정은 `publishable()` 에 맡기고, 철회는 승인이 내려간 뒤 남은 철회 시각으로 가른다."""
    if publishable(card, claims):
        return "발행"
    if (card.get("publish") or {}).get("withdrawn_at"):
        return "철회"
    return "미발행"


def event_times(card: dict) -> dict:
    """카드 history 에서 채택·첫 발행·마지막 재승인·철회 시각을 뽑는다. 없는 것은 빈 문자열이다.
    재승인 시각은 마지막 승인이 첫 승인과 다를 때만 적는다. 철회 시각은 history 의 마지막 철회 이벤트를 먼저 본다
    (철회 뒤 재승인하면 publish 칸이 통째로 바뀌어 publish.withdrawn_at 이 사라진다)."""
    picked, withdrawn, approvals = "", "", []
    for h in card.get("history") or []:
        ev, at = str(h.get("event", "")), str(h.get("at") or "")
        if ev == "state → 채택" or ev.startswith("state → 채택 "):
            picked = at
        elif ev == "공개 발행 승인":
            approvals.append(at)
        elif ev.startswith("발행 철회"):
            withdrawn = at
    first = approvals[0] if approvals else ""
    last = approvals[-1] if approvals else ""
    return {"picked_at": picked, "published_at": first, "republished_at": last if last != first else "",
            "withdrawn_at": withdrawn or str((card.get("publish") or {}).get("withdrawn_at") or "")}


def all_cards() -> list[dict]:
    """비공개 카드 전부를 card_id 순으로."""
    out = [load_yaml(p) for p in CARDS.glob("*.yaml")] if CARDS.exists() else []
    return sorted(out, key=lambda c: str(c.get("card_id", "")))


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
        # relation·gist 는 선택 칸이다. 없으면 검사하지 않고, 있으면 값의 모양만 본다.
        if "relation" in v:
            if v.get("relation") not in RELATIONS:
                e.append(f"{cid}: ⑥ videos 항목의 relation 오류({v.get('relation')}) — {' | '.join(RELATIONS)}")
            if not _real_date(v.get("date")):
                e.append(f"{cid}: ⑥ relation 을 붙인 영상({v.get('video_id')})의 date 가 YYYY-MM-DD 날짜가 아님")
            if not isinstance(v.get("video_id"), str) or not YT_ID.fullmatch(v["video_id"]):
                e.append(f"{cid}: ⑥ relation 을 붙인 영상의 video_id 가 유튜브 ID 11자가 아님({v.get('video_id')})")
        if "gist" in v:
            g = v.get("gist")
            if not isinstance(g, str) or "\n" in g or "\r" in g or len(g) > COV_GIST_MAX:
                e.append(f"{cid}: ⑥ videos 항목의 gist 는 줄바꿈 없는 {COV_GIST_MAX}자 이하 문자열({v.get('video_id')})")
    n_rel = sum(1 for v in cov.get("videos") or [] if "relation" in v)
    if n_rel > RELATION_MAX:
        e.append(f"{cid}: ⑥ relation 을 붙인 영상 {n_rel}편 — 카드당 {RELATION_MAX}편까지")
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
