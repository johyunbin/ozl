#!/usr/bin/env python3
"""덱 사양(YAML) 읽기와 검사 — 슬라이드 초안의 결정적 앞단.

사양은 사람이(또는 대화 세션의 모델이) 카드와 클레임을 읽고 직접 쓴다. 이 모듈은 문장을 짓지 않고 검사만 한다.

검사 항목
  ① 숫자 규칙: 슬라이드에 보이는 숫자는 그 슬라이드가 인용한 클레임(사람 대조 `human_verified: true` 또는 기계 대조 「원문 일치」)의 `observed`·`text` 에 같은 표기로 있어야 한다.
     - 숫자가 있는데 `claim_ids` 가 없으면 실패
     - 인용한 클레임이 없거나, 사람 대조 전이면서 「원문 일치」도 아니면 실패
     - 표기가 원문에 없으면 실패. 단위를 바꿔 적었으면 `conversions`(보이는 표기 · 원문 표기 · 클레임 · 환산 근거)를 적어야 통과
     - 숫자 판독(토큰 종류·부호·범위·면제·못 잡는 것)은 numbers.py 머리말이 정본이다. 달력·식별자는 대조하지 않고, 수량·기간·수량 낱말은 대조한다
     - 환산 원문(source)은 기록 안의 완전한 숫자 토큰이어야 한다(복합 수량의 조각·숫자 없는 말은 안 된다)
  ② 단계 순서: 구성 템플릿(tracks/syuka/style/composition_template_v0.json)의 단계 위치 중앙값 순서를 거꾸로 가면 실패.
     전개·반전·여담은 한 편에 여러 번 나오는 단계라 중간 어디에나 둘 수 있다. 첫 단계는 여는 장(또는 우회 도입), 마지막은 닫는 장이나 시사점.
  ③ 글 배치: 어절 단위로 줄을 나눈 결과가 글상자 줄 수를 넘거나, 제목이 한 줄을 넘으면 실패.
  ④ 그림(chart · capture): 그림 자리가 있는 종류(VISUAL_KINDS)에서 image·chart·capture 가운데 하나만 쓴다.
     - chart: charts.validate_chart 오류 · chart.claims 는 그 쪽 claim_ids 안 · 그림에 찍히는 수량(chart_quantities)은 ①과 같은 규칙
       · 그려지는 모든 점의 값(꼬리표가 없는 점 포함)은 chart.claims 가운데 한 기록의 원문 사본 글에 그 표기로 있어야 한다
         (capture.find_phrase — 공백만 정리, 더 긴 수의 조각은 찾은 것으로 치지 않는다). 사본이 없는 기록(사람이 대조한 옛 기록)은 observed·text 에서 찾는다.
       · 못 하는 것: 값이 사본에 있는지만 프로그램이 봤다. 칸(어느 달·어느 항목)과 값의 짝은 문장 대조에서 본다.
         세로축 눈금 숫자는 대조하지 않는다(자료가 아니라 축척이다). y_from_zero: false 는 러닝시트에 적힌다.
     - capture: <claim_id> — 그 기록의 원문 캡처. 빌드 때 해시가 확인된 사본에서 대조한 자리(match.target)의 그림을 새로 그린다
       (verification.image 는 미리 보기일 뿐 쓰지 않는다). claim_ids 안이어야 하고, 엄격 모드는 받는 기록(acceptance_error 빈 문자열)이며
       사본이 그림을 그릴 수 있고(copy_source 통과) 대조한 자리가 하나로 정해져야 한다. 초안 모드는 기록이 아직 받아들여지지 않으면
       그 쪽을 '그림 대기'로 표시한다(pending 에 '그림:<claim_id>').
     - 엄격 모드에서 image_text 쪽에 그림이 하나도 없으면 경고(글만 있는 장이 의도일 수 있어 실패는 아니다).

    python -m ozl.render check <사양.yaml>
"""
from __future__ import annotations

import json
import math
import pathlib
import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from ozl.research import cards as C

ROOT = pathlib.Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "tracks" / "syuka" / "style" / "composition_template_v0.json"
SPECS = ROOT / "private" / "decks" / "specs"

KINDS = ("title_hook", "image_text", "quote_translation", "number", "compare_table", "quote_line", "closing")

# 카드 어휘(cards.STAGES) → 구성 템플릿 JSON 의 단계 키
STAGE_KEY = {
    "여는 장": "hook", "우회 도입": "lead_in", "배경": "background", "근거 수치": "data", "전개": "development",
    "반전": "turn", "비교": "comparison", "시사점": "implication", "해법": "solution", "여담": "digression", "닫는 장": "closing",
}
REPEATABLE = {"development", "turn", "digression"}  # 템플릿 v0: 전개 편당 3.4번 · 반전 지점 편당 5곳 · 여담은 끼어드는 단계
OPENERS, ENDERS = {"hook", "lead_in"}, {"closing", "implication"}


# ── 숫자 ────────────────────────────────────────────────────────────────
# 판독은 numbers.py 한 곳에서 한다(토큰 종류를 먼저 가르고 직접 대조와 환산 경계 검사가 같은 결과를 쓴다).
from ozl.render import numbers as N  # noqa: E402

SEP = "\n¶\n"  # 칸과 칸 사이 — 한 칸 끝의 수량이 다음 칸 첫 숫자와 이어 읽히지 않게


def numeric_tokens(text, exempt: bool = True, identifiers=()) -> list[str]:
    """대조할 숫자 표기의 정규형 목록. exempt=False 면 달력·식별자까지 숫자가 든 토큰을 모두 낸다."""
    toks = N.scan(text, identifiers)
    if exempt:
        return [t.canon for t in toks if t.needs_claim]
    return [t.canon for t in toks if any(c.isdigit() for c in t.canon)]


def basis_texts(claim: dict) -> list[str]:
    """숫자 근거가 되는 글. 사람이 대조한 기록과 옛 기록은 observed·text 둘 다(사람이 문장까지 보았다).
    기계 대조 기록(`verification` 묶음이 있고 사람 대조는 아닌 것)은 사본과 대조한 observed 만 —
    text 는 쓴 쪽의 문장이고 프로그램이 원문과 견준 적이 없다."""
    if claim.get("human_verified") is not True and isinstance(claim.get("verification"), dict):
        return [_s(claim.get("observed"))]
    return [_s(claim.get("observed")), _s(claim.get("text"))]


def source_tokens(claim: dict) -> set[str]:
    return N.pool(*basis_texts(claim))


def _s(v) -> str:
    return "" if v is None else str(v)  # 0 · False 도 글자로 남긴다


def visible_text(sl: dict) -> list[str]:
    """슬라이드(와 그 그림 자리·시각물 부록)에 실제로 찍히는 글. 발표자 노트(notes)는 뺀다."""
    out = [_s(sl.get("title"))]
    out += [_s(x.get("text") if isinstance(x, dict) else x) for x in sl.get("body") or []]
    for k in ("en", "ko", "sub"):
        out.append(_s(sl.get(k)))
    num = sl.get("number")
    if isinstance(num, dict):
        out += [_s(num.get("value")), _s(num.get("label"))]
    tbl = sl.get("table")
    if isinstance(tbl, dict):
        out += [_s(x) for x in tbl.get("header") or []]
        for row in tbl.get("rows") or []:
            out += [_s(x) for x in (row if isinstance(row, list) else [row])]
    q = sl.get("quote")
    if isinstance(q, dict):
        out += [_s(q.get("text")), _s(q.get("by"))]
    img = sl.get("image")
    if isinstance(img, dict):
        out += [_s(img.get("caption")), _s(img.get("what")), _s(img.get("source"))]
    return [t for t in out if t != ""]


def spoken_text(sl: dict) -> list[str]:
    """방송에서 소리 내어 말할 글 — 화면 글과 같은 숫자 규칙을 받는다."""
    return [_s(sl.get(k)) for k in ("spoken", "transition") if _s(sl.get(k))]


def acceptance_error(c: dict) -> str:
    """엄격 모드가 이 기록을 받지 않는 까닭. 빈 문자열이면 받는다.
    받는 기록 = 사람이 대조했거나(종전 그대로 human_verified 가 참), 기계 대조로 「원문 일치」가 됐고 **지금 다시 검사해도** 증거가 맞는 것.
    기록 파일에 verified 라고 적혀 있다는 것만으로는 받지 않는다 — 사본 해시, 문구, 재대조 대목을 쓸 때마다 다시 본다."""
    if c.get("human_verified") is True:
        return ""
    if C.grade_label(c) != C.GRADE_MACHINE:
        return f"사람 대조 전이다(human_verified 아님 · 「{C.GRADE_MACHINE}」도 아님)"
    errs = C.machine_check(c, fresh=False)[0] or C.validate_claim(c, deep=True)   # 등급을 올릴 때 본 것을 쓸 때도 전부 다시 본다
    return f"「{C.GRADE_MACHINE}」 기록인데 지금 다시 검사하니 증거가 맞지 않는다 — {errs[0]}" if errs else ""


def accepted(c: dict) -> bool:
    return not acceptance_error(c)


def claim_state_errors(ids: list[str], claims: dict[str, dict], draft: bool = False, staged: set[str] | None = None) -> tuple[list[str], list[str]]:
    """(실패, 검증 대기 claim_id). 엄격 모드: 없거나 사람 대조 전(「원문 일치」도 아님)이거나 대기 폴더(--claims-dir) 기록이면 실패.
    초안 모드: 기록이 있기만 하면 되고, 사람 대조 전·대기 폴더 기록은 '검증 대기'로 돌려준다."""
    errs, pending = [], []
    staged = staged or set()
    for cid in ids:
        c = claims.get(cid)
        if c is None:
            errs.append(f"클레임 {cid} 를 찾지 못했다")
            continue
        why = acceptance_error(c)
        unverified = bool(why)
        if not draft:
            if cid in staged:
                errs.append(f"클레임 {cid} 는 대기 폴더(--claims-dir)의 기록이다 — 초안 모드(--draft)에서만 쓸 수 있다")
            elif unverified:
                errs.append(f"클레임 {cid} 는 {why}")
        elif unverified or cid in staged:
            pending.append(cid)
    return errs, pending


def number_errors(sl: dict, claims: dict[str, dict], draft: bool = False, staged: set[str] | None = None, extra_screen: list[str] | None = None,
                  identifiers=()) -> list[str]:
    """숫자 규칙 세 가지 + 인용 클레임 상태. 화면 글(각주에 찍히는 source_labels·refs 포함)과 말로 할 문장(spoken·transition)을 같은 규칙으로 본다."""
    ids = [str(x) for x in sl.get("claim_ids") or []]
    errs, _ = claim_state_errors(ids, claims, draft, staged)
    screen = SEP.join(visible_text(sl) + list(extra_screen or []))
    said = SEP.join(spoken_text(sl))
    both = screen + SEP + said
    covered: set[str] = set()
    for i, cv in enumerate(sl.get("conversions") or []):
        shown, src, cid, basis = (_s(cv.get(k)).strip() for k in ("shown", "source", "claim_id", "basis"))
        where = f"conversions[{i}]"
        if not (shown and src and cid and basis):
            errs.append(f"{where}: shown·source·claim_id·basis 넷 다 있어야 한다")
            continue
        own = N.complete_in(shown, both, need_digits=False, identifiers=identifiers)
        if own is None:
            errs.append(f"{where}: 보이는 표기 '{shown}' 가 슬라이드 글·말에 완전한 수량으로 없다")
            continue
        if cid not in ids:
            errs.append(f"{where}: {cid} 가 이 슬라이드의 claim_ids 에 없다")
            continue
        c = claims.get(cid) or {}
        if all(N.complete_in(src, b, True) is None for b in basis_texts(c)):
            errs.append(f"{where}: 원문 표기 '{src}' 가 {cid} 의 observed·text 에 완전한 수량 토큰으로 없다(숫자가 든 토큰 전체여야 한다)")
            continue
        covered |= {t.canon for t in own if t.needs_claim}
    pl: set[str] = set()
    for cid in ids:
        if cid in claims:
            pl |= source_tokens(claims[cid])
    for label, text in (("화면", screen), ("말로 할 문장(spoken·transition)", said)):
        toks = list(dict.fromkeys(t.canon for t in N.claim_tokens(text, identifiers)))
        if not toks:
            continue
        frag = [t[1:] for t in toks if t.startswith("?")]
        if frag:  # 판독부가 통째로 읽지 못한 표기 — 근거가 있어도 맞춰 볼 수 없다
            errs.append(f"{label}의 숫자 표기 {frag} 를 온전한 수량으로 읽지 못했다 — 앞뒤에 숫자 이음이 남았다. 표기를 한 덩어리로 고쳐 쓰거나 나눠 쓴다")
        toks = [t for t in toks if not t.startswith("?")]
        if not toks:
            continue
        if not ids:
            errs.append(f"{label}에 숫자·수량({', '.join(toks)})이 있는데 claim_ids 가 없다")
            continue
        missing = [t for t in toks if t not in pl and t not in covered]
        if missing:
            errs.append(f"{label}의 숫자·수량 {missing} 가 인용한 클레임({', '.join(ids)})의 observed·text 에 없다 — 같은 표기로 쓰거나 conversions 에 환산 근거를 적는다")
    return errs


# ── 그림(차트 · 원문 캡처) ───────────────────────────────────────────────
VISUAL_KINDS = ("image_text", "number")  # build.plan_slide 가 왼쪽 그림 자리(deck.IMG_W × IMG_H)를 두는 종류
VISUAL_KEYS = ("image", "chart", "capture")
WAIT_IMAGE = "그림:"  # 초안 모드 pending 항목 머리 — '그림:<claim_id>' = 원문 화면 그림 대기


def visual_of(sl: dict) -> str:
    """이 쪽 그림 자리에 들어갈 것: 'chart' · 'capture' · 'image'(종전 회색 자리) · ''(없음). 둘 이상이면 앞의 것(검사가 실패시킨다)."""
    for k in ("chart", "capture", "image"):
        if sl.get(k) not in (None, "", {}, []):
            return k
    return ""


def copy_text(c: dict) -> tuple[bool, str | None, str]:
    """기록의 원문 사본 글. (사본 묶음이 있는가, 글 | None, 못 읽은 사유). cards.copy_text 그대로 —
    machine_check 와 같은 한 길(경로 규칙 · 재해시 · 종류 재판별 · 추출 캐시)로 읽는다."""
    return C.copy_text(c)


def point_notation(pt) -> str:
    """대조할 점 값의 표기: 표시 문자열(셋째 칸)이 있으면 그것, 없으면 입력 값의 표기(문자열은 그대로, 수는 str)."""
    if len(pt) >= 3 and isinstance(pt[2], str) and pt[2].strip():
        return pt[2].strip()
    v = pt[1]
    return v.strip() if isinstance(v, str) else str(v)


def chart_screen_text(sl: dict) -> list[str]:
    """차트 그림에 글자로 찍히는 수량(charts.chart_quantities) — number_errors 의 화면 글에 더한다. 사양 오류면 빈 목록(오류는 chart_errors 가 낸다)."""
    from ozl.render import charts as G
    ch = sl.get("chart")
    if not isinstance(ch, dict) or G.validate_chart(ch):
        return []
    return list(G.chart_quantities(ch))


def chart_errors(sl: dict, claims: dict[str, dict]) -> list[str]:
    from ozl.research import capture as K
    from ozl.render import charts as G
    ch = sl.get("chart")
    errs = [f"chart: {e}" for e in G.validate_chart(ch)]
    if errs:
        return errs
    ids = [str(x) for x in sl.get("claim_ids") or []]
    used = [str(x) for x in ch["claims"]]
    out_ids = [c for c in used if c not in ids]
    if out_ids:
        errs.append(f"chart.claims {out_ids} 가 이 쪽의 claim_ids 에 없다 — 차트가 쓴 기록은 그 쪽이 인용한 기록이어야 한다")
    texts: list[tuple[str, str]] = []   # (claim_id, 대조할 글) — 사본이 있으면 사본 글, 없으면 observed·text
    for cid in used:
        c = claims.get(cid)
        if c is None:
            if cid in ids:
                continue  # claim_state_errors 가 '찾지 못했다'를 낸다
            errs.append(f"chart.claims {cid} 를 찾지 못했다")
            continue
        has, text, why = copy_text(c)
        if has:
            if text is None:
                errs.append(f"chart.claims {cid} 의 원문 사본 글을 읽지 못했다 — {why}")
            else:
                texts.append((cid, text))
        else:
            texts += [(cid, _s(c.get("observed"))), (cid, _s(c.get("text")))]
    if not texts:
        return errs
    where = "원문 사본 글(사본이 없는 기록은 observed·text)"
    for s in ch["series"]:
        for pt in s["points"]:
            nota = point_notation(pt)
            hits = [K.find_phrase(t, nota) for _, t in texts]
            if any(h["found"] for h in hits):
                continue
            cut = sum(h["cut"] for h in hits)
            errs.append(f"chart 계열 '{s['name']}' 점 {pt[0]}: 값 '{nota}' 이 chart.claims({', '.join(used)})의 {where}에 그 표기로 없다"
                        + (f"(더 긴 수의 조각인 자리 {cut}곳은 찾은 것으로 치지 않았다)" if cut else ""))
    return errs


def capture_errors(sl: dict, claims: dict[str, dict], draft: bool) -> tuple[list[str], str | None]:
    """(실패, 그림 대기 claim_id | None). 원문 캡처 그림은 빌드 때 해시가 확인된 사본에서 새로 그린다(기록의 verification.image 는 쓰지 않는다).
    그래서 여기서는 그림 파일이 아니라 '기록이 받아들여지는가(acceptance_error 빈 문자열)'와 '사본에서 그림을 그릴 수 있는가'를 본다.
    초안 모드의 그림 대기 = 기록이 아직 받아들여지지 않을 때."""
    cid = _s(sl.get("capture")).strip()
    ids = [str(x) for x in sl.get("claim_ids") or []]
    if not C.CLAIM_ID.match(cid):
        return [f"capture '{cid}' 는 claim_id 하나여야 한다"], None
    if cid not in ids:
        return [f"capture {cid} 가 이 쪽의 claim_ids 에 없다 — 원문 캡처는 그 쪽이 인용한 기록의 것이어야 한다"], None
    c = claims.get(cid)
    if c is None:
        return [], None  # claim_state_errors 가 '찾지 못했다'를 낸다
    why = acceptance_error(c)
    if why:
        return ([], cid) if draft else ([f"capture {cid} 는 {why}"], None)
    src = C.copy_source(c)
    if not src["ok"]:
        return [f"capture {cid} 의 원문 사본으로 그림을 그릴 수 없다 — {src['reason']}"], None
    if not capture_target(c):
        return [f"capture {cid} 의 대조한 자리를 정하지 못했다 — observed 가 사본에 한 번만 나오거나 재대조 기록이 자리를 정해야 한다"], None
    return [], None


def capture_target(c: dict) -> dict | None:
    """원문 캡처를 그릴 자리 — machine_check 가 정한 유일한 자리(match.target). 사람이 대조한 기록은 observed 가 사본에 한 번만 나올 때 그 자리."""
    from ozl.research import capture as K
    _, match = C.machine_check(c, fresh=False)
    if match.get("target"):
        return match["target"]
    if c.get("human_verified") is True:
        src = C.copy_source(c)
        if src["ok"]:
            f = K.find_phrase(src["text"], _s(c.get("observed")))
            if f["count"] == 1:
                m = f["matches"][0]
                return {"offset": m["offset"], "end": m["end"], "page": m["page"]}
    return None


def visual_errors(sl: dict, claims: dict[str, dict], draft: bool) -> tuple[list[str], str | None]:
    """그림 칸 검사 (실패, 그림 대기 claim_id | None)."""
    have = [k for k in VISUAL_KEYS if sl.get(k) not in (None, "", {}, [])]
    errs: list[str] = []
    if len(have) > 1:
        errs.append(f"그림 자리는 하나다 — {' · '.join(have)} 가운데 하나만 쓴다")
    kind = sl.get("kind")
    for k in ("chart", "capture"):
        if k in have and kind not in VISUAL_KINDS:
            errs.append(f"'{k}' 는 그림 자리가 있는 종류({', '.join(VISUAL_KINDS)})에서만 쓴다(지금 {kind})")
    if errs:
        return errs, None
    if "chart" in have:
        return chart_errors(sl, claims), None
    if "capture" in have:
        return capture_errors(sl, claims, draft)
    return [], None


# ── 각주(화면에 찍히는 글 — 생성과 검사가 같은 함수를 쓴다) ─────────────────
def base_period_text(base) -> str:
    """기록의 base_period 를 화면 표기로: 2023 → 2023년 · 2026-07 → 2026년 7월 · 2026-Q3 → 2026년 3분기 · 날짜는 그대로."""
    b = _s(base).strip()
    if not b or b == "n/a":
        return ""
    if re.fullmatch(r"\d{4}", b):
        return f"{b}년"
    m = re.fullmatch(r"(\d{4})-(\d{2})", b)
    if m:
        return f"{m.group(1)}년 {int(m.group(2))}월"
    m = re.fullmatch(r"(\d{4})-Q([1-4])", b)
    if m:
        return f"{m.group(1)}년 {m.group(2)}분기"
    return b


def short_source(cid: str, claim: dict, card: dict | None, labels: dict | None = None) -> str:
    if labels and labels.get(cid):
        return str(labels[cid])
    for d in (card or {}).get("data") or []:
        if d.get("claim_id") == cid and d.get("source_name"):
            return str(d["source_name"])
    return str((claim.get("source") or {}).get("publisher") or "")


def footnote_text(sl: dict, claims: dict, card: dict | None, labels: dict | None = None) -> str:
    parts: list[str] = []
    for cid in sl.get("claim_ids") or []:
        c = claims.get(str(cid)) or {}
        base = base_period_text((c.get("checks") or {}).get("base_period"))
        label = short_source(str(cid), c, card, labels) + (f" · 기준 {base}" if base else "")
        if label not in parts:
            parts.append(label)
    refs = [str(x) for x in sl.get("refs") or []]
    out = ("출처: " + " / ".join(parts)) if parts else ""
    if refs:
        out += ("  ·  " if out else "") + "보도: " + " / ".join(refs)
    return out


# ── 단계 순서 ────────────────────────────────────────────────────────────
def load_template(path: pathlib.Path = TEMPLATE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _runs(stages: list[str]) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for i, s in enumerate(stages):
        if out and out[-1][0] == s:
            out[-1] = (s, out[-1][1], i)
        else:
            out.append((s, i, i))
    return out


def stage_errors(stages: list[str], template: dict) -> tuple[list[str], list[str]]:
    """(실패, 경고). 실패 = 순서가 템플릿을 거스름. 경고 = 템플릿 규칙(적중률 기반)에서 벗어남."""
    errs, warns = [], []
    pos = {s["stage"]: s["position_median"] for s in template.get("stages", [])}
    keys = []
    for i, s in enumerate(stages, 1):
        k = STAGE_KEY.get(s)
        if k is None or s not in C.STAGES:
            errs.append(f"{i}쪽: 단계 '{s}' 는 구성 템플릿 어휘가 아니다({' · '.join(C.STAGES)})")
        elif k not in pos:
            errs.append(f"{i}쪽: 단계 '{s}'({k}) 가 구성 템플릿 JSON 에 없다")
        keys.append(k)
    if errs or not keys:
        return errs or ["슬라이드가 없다"], warns
    runs = _runs(keys)
    if runs[0][0] not in OPENERS:
        errs.append(f"첫 단계는 여는 장 또는 우회 도입이어야 한다(지금 '{stages[0]}')")
    if runs[-1][0] not in ENDERS:
        errs.append(f"마지막 단계는 닫는 장 또는 시사점이어야 한다(지금 '{stages[-1]}')")
    for k, a, b in runs[1:]:
        if k == "hook":
            errs.append(f"{a + 1}쪽: 여는 장은 맨 앞에만 둔다")
    for k, a, b in runs[:-1]:
        if k == "closing":
            errs.append(f"{a + 1}쪽: 닫는 장은 맨 끝에만 둔다")
    last_k, last_p = None, -1.0
    for k, a, b in runs:
        if k in REPEATABLE:
            continue
        if pos[k] < last_p:
            ko = {v: kk for kk, v in STAGE_KEY.items()}
            errs.append(f"{a + 1}쪽: '{ko[k]}' 가 '{ko[last_k]}' 뒤에 왔다 — 템플릿 순서(위치 중앙값 {pos[k]:.2f} < {last_p:.2f})를 거스른다")
        else:
            last_k, last_p = k, pos[k]
    n = len(keys)
    turns = [r for r in runs if r[0] == "turn"]
    if not turns:
        warns.append("반전 단계가 없다(템플릿: 편당 반전 지점 3~6곳)")
    else:
        if turns[0][1] / n > 0.35:
            warns.append(f"첫 반전이 {turns[0][1] + 1}쪽({turns[0][1] / n:.0%} 지점) — 템플릿 규칙은 앞 35% 안")
        if not 3 <= len(turns) <= 6:
            warns.append(f"반전 묶음 {len(turns)}곳 — 템플릿 규칙은 3~6곳")
    if (runs[0][2] + 1) / n > 0.15:
        warns.append(f"여는 단계가 {runs[0][2] + 1}장 — 템플릿 규칙은 전체의 15% 이하")
    if sum(1 for r in runs if r[0] == "development") < 2:
        warns.append("전개가 2번 미만(템플릿: 21/25편에서 2번 이상)")
    return errs, warns


# ── 글 배치(어절 줄바꿈) ─────────────────────────────────────────────────
_FONT_DIRS = [pathlib.Path("/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts"),
              pathlib.Path.home() / "Library/Fonts", pathlib.Path("/Library/Fonts")]


@lru_cache(maxsize=None)
def _font(bold: bool):
    try:
        from PIL import ImageFont
    except ImportError:  # pragma: no cover
        return None
    name = "malgunbd.ttf" if bold else "malgun.ttf"
    for d in _FONT_DIRS:
        p = d / name
        if p.exists():
            return ImageFont.truetype(str(p), 100)
    return None


def measure(text: str, size: float, bold: bool = False) -> float:
    """맑은 고딕으로 잰 글 폭(pt). 폰트 파일이 없으면 어림(한글 1em · 그 밖 0.55em)."""
    f = _font(bold)
    if f is not None:
        return f.getlength(text) * size / 100.0
    return sum(size if ord(ch) > 0x2E80 else size * 0.55 for ch in text) * (1.04 if bold else 1.0)


def wrap(text: str, width_pt: float, size: float, bold_mask: list[bool] | None = None, measure_fn=measure) -> list[tuple[int, int]]:
    """어절(공백으로 나뉜 덩어리) 단위로 줄을 나눈다. 반환 = 각 줄의 [시작, 끝) 글자 위치(줄 끝 공백 제외).
    한 어절이 줄 폭보다 길어도 자르지 않고 그 줄에 홀로 둔다(검사에서 넘침으로 잡는다)."""
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    if not words:
        return []
    mask = bold_mask or [False] * len(text)

    def w(a: int, b: int) -> float:
        tot, i = 0.0, a
        while i < b:
            j = i
            while j < b and mask[j] == mask[i]:
                j += 1
            tot += measure_fn(text[i:j], size, mask[i])
            i = j
        return tot

    lines: list[tuple[int, int]] = []
    a, b = words[0]
    for s, e in words[1:]:
        if w(a, e) <= width_pt:
            b = e
        else:
            lines.append((a, b))
            a, b = s, e
    lines.append((a, b))
    return lines


def emphasis_mask(text: str, phrases: list[str]) -> list[bool]:
    m = [False] * len(text)
    for ph in phrases or []:
        if not ph:
            continue
        for x in re.finditer(re.escape(ph), text):
            for i in range(x.start(), x.end()):
                m[i] = True
    return m


# ── 사양 ────────────────────────────────────────────────────────────────
@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pending: dict[int, list[str]] = field(default_factory=dict)  # 초안 모드: 쪽 번호 → 검증 대기 claim_id
    exempt_idents: list[str] = field(default_factory=list)  # 대조에서 면제한 식별자(검토자가 볼 수 있게 출력한다)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_spec(path: pathlib.Path) -> dict:
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}


def load_claims(ids, claims_dirs=()) -> tuple[dict[str, dict], set[str]]:
    """사양이 인용한 클레임을 읽는다(읽기만). 정본(private/desk/claims)에 없으면 claims_dirs(대기 폴더)에서 `<claim_id>.yaml` 을 찾는다.
    반환 = (클레임, 대기 폴더에서 온 claim_id). 대기 폴더 기록은 초안 모드에서만 쓸 수 있다(check 가 가른다)."""
    out: dict[str, dict] = {}
    staged: set[str] = set()
    dirs = [pathlib.Path(d) for d in claims_dirs or ()]
    for cid in ids:
        if not C.CLAIM_ID.match(cid):
            continue
        p = C.claim_path(cid)
        if p.exists() or p.is_symlink():
            real = p.resolve()
            canon = C.CLAIMS.resolve()
            out[cid] = C.load_yaml(real) if real.exists() else {}
            if p.is_symlink() or canon not in real.parents:
                staged.add(cid)  # 정본 자리에 놓인 링크 — 실제로 읽은 파일이 정본 폴더 밖이면 대기 기록과 같게 다룬다(엄격 모드 실패)
            if not out[cid]:
                del out[cid]
            continue
        for d in dirs:
            hits = sorted(d.rglob(f"{cid}.yaml")) if d.is_dir() else []
            if hits:
                c = C.load_yaml(hits[0])
                if c.get("claim_id") == cid:
                    out[cid] = c
                    staged.add(cid)
                break
    return out, staged


def cited_ids(spec: dict) -> list[str]:
    seen: dict[str, None] = {}
    for sl in spec.get("slides") or []:
        for cid in sl.get("claim_ids") or []:
            seen[str(cid)] = None
        for cv in sl.get("conversions") or []:
            if cv.get("claim_id"):
                seen[str(cv["claim_id"])] = None
    return list(seen)


_REQUIRED = {
    "title_hook": ("title",),
    "image_text": ("title", "body"),
    "quote_translation": ("title", "en", "ko"),
    "number": ("title", "number"),
    "compare_table": ("title", "table"),
    "quote_line": ("title", "quote"),
    "closing": ("title", "body"),
}
_NESTED = {"number": ("value",), "quote": ("text",), "table": ("header", "rows"), "image": ("what", "source")}


def _present(v) -> bool:
    return v is not None and (not isinstance(v, (str, list, dict)) or len(v) > 0) and _s(v).strip() != ""


def check(spec: dict, claims: dict[str, dict], template: dict, card: dict | None = None, layout_fn=None,
          draft: bool = False, staged: set[str] | None = None, appendix_fn=None) -> Report:
    """사양 전체 검사. layout_fn(slide) → 넘침 메시지 목록 (build.layout_problems — 글상자 크기를 아는 쪽이 준다).
    draft=True: 사람 대조 전·대기 폴더 기록을 인용해도 실패하지 않고 r.pending 에 쪽별로 모은다(기록은 실제로 있어야 하고 숫자 대조는 그대로)."""
    r = Report()
    slides = spec.get("slides") or []
    cid = spec.get("card_id")
    if not cid:
        r.errors.append("card_id 가 없다")
    elif not C.CARD_ID.match(str(cid)):
        r.errors.append(f"card_id '{cid}' 가 카드 ID 형식(YYYY-MM-DD-am|pm|wk-NN)이 아니다")
    idents = spec.get("identifiers") or []
    if not isinstance(idents, list) or not all(isinstance(x, str) and x.strip() for x in idents):
        r.errors.append("identifiers 는 식별자 표기(문자열)의 목록이어야 한다")
        idents = []
    for k, v in (spec.get("source_labels") or {}).items():
        if not C.CLAIM_ID.match(str(k)) or not _present(v):
            r.errors.append(f"source_labels: '{k}' 는 claim_id 와 짧은 출처 이름의 짝이어야 한다")
    if not slides:
        r.errors.append("slides 가 비었다")
        return r
    card_sources = {s.get("name") for s in (card or {}).get("sources") or []}
    # 사양에 직접 적은 보도 출처(카드 sources 에 아직 반영되지 않은 것) — 초안 모드에서만 refs 로 쓸 수 있다
    press = {}
    for k, ps in enumerate(spec.get("press_sources") or []):
        if not isinstance(ps, dict) or not all(_present(ps.get(x)) for x in ("name", "tier", "url")):
            r.errors.append(f"press_sources[{k}]: name·tier·url 셋 다 있어야 한다")
            continue
        if str(ps["tier"]) not in C.TIERS:
            r.errors.append(f"press_sources[{k}]: tier '{ps['tier']}' 는 {C.TIERS} 가 아니다")
        if not str(ps["url"]).startswith(("https://", "http://")):
            r.errors.append(f"press_sources[{k}]: url 이 주소가 아니다")
        press[str(ps["name"])] = ps
    bare: list[int] = []  # 엄격 모드: 그림이 하나도 없는 image_text 쪽(경고 한 줄로 모은다)
    for i, sl in enumerate(slides, 1):
        tag = f"{i}쪽"
        if not isinstance(sl, dict):
            r.errors.append(f"{tag}: 슬라이드가 사전(mapping)이 아니다")
            continue
        kind = sl.get("kind")
        if kind not in KINDS:
            r.errors.append(f"{tag}: 슬라이드 종류 '{kind}' 를 모른다({', '.join(KINDS)})")
            continue
        for k in _REQUIRED[kind]:
            if not _present(sl.get(k)):
                r.errors.append(f"{tag}: {kind} 에는 '{k}' 가 있어야 한다")
        for k, subs in _NESTED.items():
            v = sl.get(k)
            if v is None:
                continue
            if not isinstance(v, dict):
                r.errors.append(f"{tag}: '{k}' 는 사전(mapping)이어야 한다")
                continue
            for sub in subs:
                if not _present(v.get(sub)):
                    r.errors.append(f"{tag}: '{k}.{sub}' 가 있어야 한다")
        tbl = sl.get("table") if isinstance(sl.get("table"), dict) else {}
        for j, row in enumerate(tbl.get("rows") or []):
            if not isinstance(row, list) or len(row) != len(tbl.get("header") or []):
                n = len(row) if isinstance(row, list) else 1
                r.errors.append(f"{tag}: 표 {j + 1}행의 칸 수 {n} ≠ 머리글 {len(tbl.get('header') or [])}칸(YAML 쉼표에 칸이 쪼개졌는지 본다)")
        if tbl.get("widths") is not None:
            ws = tbl["widths"]
            if not isinstance(ws, list) or len(ws) != len(tbl.get("header") or []):
                r.errors.append(f"{tag}: 표 widths 칸 수가 머리글과 다르다")
            elif not all(isinstance(w, (int, float)) and not isinstance(w, bool) and math.isfinite(w) and w > 0 for w in ws):
                r.errors.append(f"{tag}: 표 widths 는 양의 유한수여야 한다({ws})")
        foot = footnote_text(sl, claims, card, spec.get("source_labels") or {})
        for t in visible_text(sl) + spoken_text(sl) + [foot]:
            for x in N.exempt_identifiers(t, idents):
                if x not in r.exempt_idents:
                    r.exempt_idents.append(x)
        for e in number_errors(sl, claims, draft, staged, [foot] + chart_screen_text(sl), idents):
            r.errors.append(f"{tag}: {e}")
        if draft:
            _, pend = claim_state_errors([str(x) for x in sl.get("claim_ids") or []], claims, True, staged)
            if pend:
                r.pending[i] = pend
        for c_id in sl.get("claim_ids") or []:
            c = claims.get(str(c_id)) or {}
            if card and c.get("card_id") and c.get("card_id") != spec.get("card_id"):
                r.warnings.append(f"{tag}: {c_id} 는 다른 카드의 클레임이다")
        for ref in sl.get("refs") or []:
            if card is not None and ref in card_sources:
                continue
            if ref in press:
                if draft:
                    r.pending.setdefault(i, []).append(f"보도:{ref}")
                else:
                    r.errors.append(f"{tag}: refs '{ref}' 는 사양 press_sources 에만 있다 — 카드 sources 에 반영되기 전에는 초안 모드(--draft)에서만 쓸 수 있다")
            elif card is not None or press:
                r.errors.append(f"{tag}: refs '{ref}' 가 카드 sources 와 사양 press_sources 의 name 에 없다")
        verrs, wait = visual_errors(sl, claims, draft)
        r.errors += [f"{tag}: {e}" for e in verrs]
        if wait:
            r.pending.setdefault(i, []).append(WAIT_IMAGE + wait)
        if not draft and kind == "image_text" and not visual_of(sl):
            bare.append(i)
        if sl.get("seconds") is None:
            r.warnings.append(f"{tag}: 예상 발화 시간(seconds)이 없다")
        if layout_fn is not None:
            for e in layout_fn(sl):
                r.errors.append(f"{tag}: {e}")
    if bare:
        r.warnings.append(f"그림 자리가 비었다(image_text 인데 chart·capture·image 가 없다): {', '.join(map(str, bare))}쪽 — 글만 있는 장이 의도면 그대로 둔다")
    errs, warns = stage_errors([str(sl.get("stage")) if isinstance(sl, dict) else "" for sl in slides], template)
    r.errors += errs
    r.warnings += warns
    if appendix_fn is not None and not r.errors:
        r.errors += list(appendix_fn(spec, claims, card, r.pending))
    return r
