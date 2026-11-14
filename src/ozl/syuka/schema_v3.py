"""3판 추출 양식(영상 → 토막)과 검사기. 지침: `private/syuka/extract_guide_v3.md`.

파일: `private/syuka/extract_v3/<video_id>.json` 한 편에 하나.

    {"video_id", "schema_version": 3, "model", "seconds", "read_to_end": true, "transcript_chars",
     "summary", "ad_disclosure", "n_segments", "notes", "segments": [토막, ...]}

2판에서 바뀐 것(까닭은 `private/out/슈카_표본_20261114.md` 6절):
- 생방송에서 주제 하나를 고르지 않고 주제마다 토막으로 나눈다(주제 고르기가 갈렸다).
- 인물과 기관은 중심 하나(`main_person`, `main_org`)를 따로 적고 목록은 8개까지(목록 통째 일치가 빡빡했다).
- 다룬 시기는 중심 사건의 시작과 끝(`core_start`, `core_end`)과 배경 연도(`background_years`)로 나눈다
  (시작을 배경으로 볼지 중심 사건으로 볼지 갈렸다).
- 이름 표기는 추출자가 맞추지 않고 `names.py` 가 넣을 때 맞춘다.
분야, 도입 방식, 민감 표시의 값과 정의는 2판 그대로다(`schema.py`).
"""
from __future__ import annotations

import re

from . import schema

SCHEMA_VERSION = 3
EXTRACT_DIR = "extract_v3"  # private/syuka/ 아래

FIELDS = tuple(schema.FIELDS)
INTRO_STYLES = schema.INTRO_STYLES
SENSITIVE = schema.SENSITIVE
KOREA_LINK = schema.KOREA_LINK

ROLES = ("hook", "context", "explainer", "case", "data", "turn", "comparison", "implication", "solution", "summary")
STORY_DEVICES = ("비유", "역사 사례", "해외 사례 비교", "개인 경험", "시청자 반응 인용", "유머와 밈",
                 "가정과 사고 실험", "숫자로 충격 주기", "반전")
SOURCE_TYPES = ("외신", "국내 언론", "공식 통계", "연구 보고서", "기업 공시와 실적", "정부 발표", "SNS와 커뮤니티",
                "책", "알 수 없음")
UNKNOWN_SOURCE = "알 수 없음"
SPONSORED = ("예", "아니오", "불분명")
AD_DISCLOSURE = ("예", "아니오", "불분명")
EVERGREEN = ("시사", "상시", "중간")

MAX_PEOPLE = MAX_ORGS = 8
MAX_KEYWORDS = 6
MAX_FOLLOWUPS = 3
MAX_SEGMENTS = 40

PERIOD_RE = schema.PERIOD_RE                      # YYYY 또는 YYYY-MM(기원전은 음수)
DATE_RE = re.compile(r"^-?\d{1,4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")  # + YYYY-MM-DD

FILE_KEYS = ("video_id", "schema_version", "model", "seconds", "read_to_end", "transcript_chars", "summary",
             "ad_disclosure", "n_segments", "notes", "segments")
SEG_KEYS = ("seg", "span", "topic_line", "question", "field", "field2", "intro_style", "main_person", "main_org",
            "people", "orgs", "countries", "korea_link", "period", "claims", "stages", "story_devices",
            "source_types", "sensitive", "sponsored", "evergreen", "followups", "keywords", "notes")
MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _text(errs, d, key, maxlen, p, allow_empty=False, nullable=False):
    v = d.get(key)
    if v is None and nullable:
        return
    if not isinstance(v, str) or (not allow_empty and not v.strip()):
        errs.append(f"{p}{key}: 글이어야 한다" + ("" if allow_empty else "(빈 글 안 됨)") + (" 또는 null" if nullable else ""))
    elif len(v) > maxlen:
        errs.append(f"{p}{key}: {maxlen}자 초과({len(v)}자)")
    elif "\n" in v:
        errs.append(f"{p}{key}: 한 줄이어야 한다(줄바꿈 있음)")


def _str_list(errs, d, key, lo, hi, maxlen, p):
    v = d.get(key)
    if not isinstance(v, list) or not all(isinstance(s, str) and s.strip() for s in v):
        errs.append(f"{p}{key}: 빈 칸 없는 글 목록이어야 한다")
        return []
    if not lo <= len(v) <= hi:
        errs.append(f"{p}{key}: {lo}~{hi}개여야 한다(지금 {len(v)}개)")
    for i, s in enumerate(v):
        if len(s) > maxlen:
            errs.append(f"{p}{key}[{i}]: {maxlen}자 초과({len(s)}자)")
    if len({s.strip() for s in v}) != len(v):
        errs.append(f"{p}{key}: 같은 값이 두 번 있다")
    return v


def _closed_list(errs, d, key, allowed, p, lo=0):
    v = d.get(key)
    if not isinstance(v, list) or any(x not in allowed for x in v) or len(set(v)) != len(v) or len(v) < lo:
        errs.append(f"{p}{key}: {list(allowed)} 에서 {lo}개 이상, 겹침 없이")
        return []
    return v


def period_key(v: str) -> tuple[int, int]:
    neg = v.startswith("-")
    parts = v.lstrip("-").split("-")
    y = int(parts[0])
    return (-y if neg else y, int(parts[1]) if len(parts) > 1 else 0)


def _check_period(errs, seg, p, upload_at):
    per = seg.get("period")
    if not isinstance(per, dict) or set(per) != {"core_start", "core_end", "background_years"}:
        errs.append(f"{p}period: 칸은 core_start·core_end·background_years")
        return
    cs, ce, bg = per["core_start"], per["core_end"], per["background_years"]
    if (cs is None) != (ce is None):
        errs.append(f"{p}period: core_start 와 core_end 는 둘 다 적거나 둘 다 null(특정 시기 없음)")
    elif cs is not None:
        if not all(isinstance(v, str) and PERIOD_RE.match(v) for v in (cs, ce)):
            errs.append(f"{p}period: core_start·core_end 는 'YYYY' 또는 'YYYY-MM'")
        elif period_key(cs) > period_key(ce):
            errs.append(f"{p}period: core_start 가 core_end 보다 늦다")
        elif upload_at:
            uy, um = int(upload_at[:4]), int(upload_at[5:7])
            for k, v in (("core_start", cs), ("core_end", ce)):
                y, m = period_key(v)
                if y < uy - 1 and m:
                    errs.append(f"{p}period.{k}: {uy - 1}년보다 이른 시점은 연만 적는다('{y}')")
                if (y, m) > (uy, um):
                    errs.append(f"{p}period.{k}: 올린 달({uy}-{um:02d})보다 늦다 — 예정과 전망은 넣지 않는다")
    if not isinstance(bg, list) or not all(_is_int(y) for y in bg) or len(set(bg)) != len(bg) or len(bg) > 10:
        errs.append(f"{p}period.background_years: 정수 연도 목록(겹침 없이, 10개까지)")
    else:
        if bg != sorted(bg):
            errs.append(f"{p}period.background_years: 오래된 해부터 적는다")
        if cs is not None and isinstance(cs, str) and PERIOD_RE.match(cs) and any(y >= period_key(cs)[0] for y in bg):
            errs.append(f"{p}period.background_years: core_start 의 해보다 이른 해만 적는다(중심 사건 안의 해는 넣지 않는다)")
        if upload_at and any(y > int(upload_at[:4]) for y in bg):
            errs.append(f"{p}period.background_years: 올린 해보다 늦은 해가 있다")


def _check_span(errs, seg, p, n_chars):
    sp = seg.get("span")
    keys = {"start_char", "end_char", "start_sec", "end_sec"}
    if not isinstance(sp, dict) or not set(sp) <= keys or not sp:
        errs.append(f"{p}span: 칸은 start_char·end_char 또는 start_sec·end_sec(둘 다도 된다)")
        return None
    ok = False
    for a, b in (("start_char", "end_char"), ("start_sec", "end_sec")):
        if (a in sp) != (b in sp):
            errs.append(f"{p}span: {a} 와 {b} 는 함께 적는다")
            continue
        if a not in sp:
            continue
        x, y = sp[a], sp[b]
        isok = _is_int if a == "start_char" else _is_num
        if not (isok(x) and isok(y) and 0 <= x < y):
            errs.append(f"{p}span: 0 ≤ {a} < {b} 인 수여야 한다")
            continue
        if a == "start_char" and n_chars is not None and y > n_chars:
            errs.append(f"{p}span.end_char: 전사 길이({n_chars}자)보다 크다")
            continue
        ok = True
    return sp if ok else None


def _check_claims(errs, seg, p):
    c = seg.get("claims")
    if not isinstance(c, list) or not 3 <= len(c) <= 8:
        errs.append(f"{p}claims: 3~8개 목록이어야 한다")
        return
    for i, x in enumerate(c):
        q = f"{p}claims[{i}]"
        if not isinstance(x, dict) or set(x) != {"point", "value", "unit", "as_of"}:
            errs.append(f"{q}: 칸은 point·value·unit·as_of")
            continue
        if not isinstance(x["point"], str) or not x["point"].strip() or len(x["point"]) > 80:
            errs.append(f"{q}.point: 1~80자 글")
        for k in ("value", "unit"):
            if x[k] is not None and (not isinstance(x[k], str) or not x[k].strip() or len(x[k]) > 30):
                errs.append(f"{q}.{k}: 30자 이내 글 또는 null")
        if x["value"] is None and (x["unit"] is not None or x["as_of"] is not None):
            errs.append(f"{q}: 수치 없이 단위나 기준 시점만 있다")
        if x["as_of"] is not None and not (isinstance(x["as_of"], str) and DATE_RE.match(x["as_of"])):
            errs.append(f"{q}.as_of: 'YYYY', 'YYYY-MM', 'YYYY-MM-DD' 또는 null")
        if isinstance(x["value"], str) and not re.search(r"\d|[십백천만억조]|절반|배", x["value"]):
            errs.append(f"{q}.value: 수치가 아니다(수치가 없으면 null)")


def _check_stages(errs, seg, p):
    st = seg.get("stages")
    if not isinstance(st, list) or not 3 <= len(st) <= 7:
        errs.append(f"{p}stages: 3~7개 목록이어야 한다")
        return
    for i, x in enumerate(st):
        q = f"{p}stages[{i}]"
        if not isinstance(x, dict) or set(x) != {"role", "line"}:
            errs.append(f"{q}: 칸은 role·line")
            continue
        if x["role"] not in ROLES:
            errs.append(f"{q}.role: 목록 밖의 값 {x['role']!r}")
        if not isinstance(x["line"], str) or not x["line"].strip() or len(x["line"]) > 80:
            errs.append(f"{q}.line: 1~80자 글")


def _check_followups(errs, seg, p, upload_at):
    f = seg.get("followups")
    if not isinstance(f, list) or len(f) > MAX_FOLLOWUPS:
        errs.append(f"{p}followups: 0~{MAX_FOLLOWUPS}개 목록")
        return
    for i, x in enumerate(f):
        q = f"{p}followups[{i}]"
        if not isinstance(x, dict) or set(x) != {"metric", "value_then", "date_then", "why"}:
            errs.append(f"{q}: 칸은 metric·value_then·date_then·why")
            continue
        if not isinstance(x["metric"], str) or not x["metric"].strip() or len(x["metric"]) > 40:
            errs.append(f"{q}.metric: 1~40자 글")
        if x["value_then"] is not None and (not isinstance(x["value_then"], str) or len(x["value_then"]) > 30):
            errs.append(f"{q}.value_then: 30자 이내 글 또는 null")
        d = x["date_then"]
        if d is not None and not (isinstance(d, str) and DATE_RE.match(d)):
            errs.append(f"{q}.date_then: 'YYYY', 'YYYY-MM', 'YYYY-MM-DD' 또는 null")
        elif d and upload_at and d[:7] > upload_at[:7] and not d.startswith("-"):
            errs.append(f"{q}.date_then: 올린 달보다 늦다(그때의 값과 시점을 적는다. 예정 일정은 why 에)")
        if not isinstance(x["why"], str) or not x["why"].strip() or len(x["why"]) > 80:
            errs.append(f"{q}.why: 1~80자 글")


def validate_segment(seg: dict, upload_at: str | None = None, n_chars: int | None = None) -> list[str]:
    if not isinstance(seg, dict):
        return ["토막: 객체여야 한다"]
    p = f"segments[{seg.get('seg', '?')}]."
    errs = [f"{p}{k}: 칸 없음" for k in SEG_KEYS if k not in seg]
    errs += [f"{p}{k}: 양식에 없는 칸" for k in seg if k not in SEG_KEYS]
    _check_span(errs, seg, p, n_chars)
    _text(errs, seg, "topic_line", 40, p)
    _text(errs, seg, "question", 100, p)
    _text(errs, seg, "notes", 300, p, allow_empty=True)
    if seg.get("field") not in FIELDS:
        errs.append(f"{p}field: 목록 밖의 값 {seg.get('field')!r}")
    f2 = seg.get("field2")
    if f2 is not None and (f2 not in FIELDS or f2 == seg.get("field")):
        errs.append(f"{p}field2: null 이거나 field 와 다른 목록 값")
    if seg.get("intro_style") not in INTRO_STYLES:
        errs.append(f"{p}intro_style: 목록 밖의 값 {seg.get('intro_style')!r}")
    people = _str_list(errs, seg, "people", 0, MAX_PEOPLE, 40, p)
    orgs = _str_list(errs, seg, "orgs", 0, MAX_ORGS, 60, p)
    _str_list(errs, seg, "countries", 0, 40, 30, p)
    _str_list(errs, seg, "keywords", 1, MAX_KEYWORDS, 20, p)
    for k, lst in (("main_person", people), ("main_org", orgs)):
        v = seg.get(k)
        if v is None:
            continue
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{p}{k}: 이름 한 개(글) 또는 null")
        elif v not in lst:
            errs.append(f"{p}{k}: {'people' if k == 'main_person' else 'orgs'} 목록의 첫 자리에도 적는다")
        elif lst and lst[0] != v:
            errs.append(f"{p}{k}: {'people' if k == 'main_person' else 'orgs'} 목록의 첫 자리에 둔다")

    k = seg.get("korea_link")
    if not isinstance(k, dict) or set(k) != {"level", "line"}:
        errs.append(f"{p}korea_link: 칸은 level·line")
    else:
        if k["level"] not in KOREA_LINK:
            errs.append(f"{p}korea_link.level: 목록 밖의 값 {k['level']!r}")
        if not isinstance(k["line"], str) or len(k["line"]) > 80 or (k["level"] != "없음" and not k["line"].strip()):
            errs.append(f"{p}korea_link.line: 80자 이내 글(직접·간접이면 빈 글 안 됨)")

    _check_period(errs, seg, p, upload_at)
    _check_claims(errs, seg, p)
    _check_stages(errs, seg, p)
    dev = _closed_list(errs, seg, "story_devices", STORY_DEVICES, p)
    roles = [x.get("role") for x in seg.get("stages") or [] if isinstance(x, dict)]
    if "반전" in dev and "turn" not in roles:
        errs.append(f"{p}story_devices: '반전' 을 적었으면 stages 에 role 'turn' 단계가 있어야 한다")
    src = _closed_list(errs, seg, "source_types", SOURCE_TYPES, p, lo=1)
    if UNKNOWN_SOURCE in src and len(src) > 1:
        errs.append(f"{p}source_types: '{UNKNOWN_SOURCE}' 은 다른 값과 함께 적지 않는다")
    _closed_list(errs, seg, "sensitive", SENSITIVE, p)

    s = seg.get("sponsored")
    if not isinstance(s, dict) or set(s) != {"level", "line"}:
        errs.append(f"{p}sponsored: 칸은 level·line")
    else:
        if s["level"] not in SPONSORED:
            errs.append(f"{p}sponsored.level: 목록 밖의 값 {s['level']!r}")
        if not isinstance(s["line"], str) or len(s["line"]) > 80 or (s["level"] != "아니오" and not s["line"].strip()):
            errs.append(f"{p}sponsored.line: 80자 이내 글(예·불분명이면 근거를 적는다)")
    if seg.get("evergreen") not in EVERGREEN:
        errs.append(f"{p}evergreen: 목록 밖의 값 {seg.get('evergreen')!r}")
    _check_followups(errs, seg, p, upload_at)
    return errs


def validate_file(doc: dict, transcript: str | None = None, upload_at: str | None = None) -> list[str]:
    """파일 전체 검사. transcript 를 주면 옮김(16자 이상 이어서 같음)과 글자 수를, upload_at 을 주면 시기를 본다."""
    if not isinstance(doc, dict):
        return ["파일: 객체여야 한다"]
    errs = [f"{k}: 칸 없음" for k in FILE_KEYS if k not in doc]
    errs += [f"{k}: 양식에 없는 칸" for k in doc if k not in FILE_KEYS]
    if not isinstance(doc.get("video_id"), str) or not VIDEO_ID_RE.match(doc.get("video_id") or ""):
        errs.append("video_id: 영상 id 글이어야 한다")
    if doc.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version: {SCHEMA_VERSION} 이어야 한다")
    if not isinstance(doc.get("model"), str) or not MODEL_RE.match(doc.get("model") or ""):
        errs.append("model: 소문자·숫자·._- (예: opus)")
    sec = doc.get("seconds")
    if not _is_num(sec) or sec <= 0:
        errs.append("seconds: 양수(끝 시각 − 전사를 열기 직전 시각)")
    if doc.get("read_to_end") is not True:
        errs.append("read_to_end: true 여야 한다(전사를 끝까지 읽지 않았으면 자료를 내지 않는다)")
    n_chars = len(transcript) if transcript is not None else None
    tc = doc.get("transcript_chars")
    if not _is_int(tc) or tc <= 0:
        errs.append("transcript_chars: 전사 글자 수(양의 정수)")
    elif n_chars is not None and tc != n_chars:
        errs.append(f"transcript_chars: 전사 글자 수와 다르다(적은 값 {tc}, 실제 {n_chars})")
    _text(errs, doc, "summary", 120, "")
    _text(errs, doc, "notes", 300, "", allow_empty=True)
    if doc.get("ad_disclosure") not in AD_DISCLOSURE:
        errs.append(f"ad_disclosure: 목록 밖의 값 {doc.get('ad_disclosure')!r}")

    segs = doc.get("segments")
    if not isinstance(segs, list) or not 1 <= len(segs) <= MAX_SEGMENTS:
        errs.append(f"segments: 1~{MAX_SEGMENTS}개 목록이어야 한다")
        segs = []
    if doc.get("n_segments") != len(segs):
        errs.append(f"n_segments: 토막 수({len(segs)})와 같아야 한다")
    nums = [s.get("seg") for s in segs if isinstance(s, dict)]
    if nums != list(range(1, len(segs) + 1)):
        errs.append("segments: seg 는 1부터 차례로(1, 2, 3 …)")
    for s in segs:
        errs += validate_segment(s, upload_at, n_chars)
    # 토막은 전사 순서대로, 서로 겹치지 않게(글자 위치를 적은 것끼리, 시각을 적은 것끼리)
    for a, b in (("start_char", "end_char"), ("start_sec", "end_sec")):
        spans = [(s["seg"], s["span"]) for s in segs
                 if isinstance(s, dict) and isinstance(s.get("span"), dict) and a in s["span"] and b in s["span"]
                 and _is_num(s["span"][a]) and _is_num(s["span"][b])]
        for (n1, s1), (n2, s2) in zip(spans, spans[1:]):
            if s2[a] < s1[b]:
                errs.append(f"segments[{n2}].span: 앞 토막({n1})과 겹치거나 순서가 바뀌었다({a})")
    if transcript:
        tn = schema.norm(transcript)
        body = {k: v for k, v in doc.items() if k in ("summary", "notes", "segments")}
        for path, text in schema._strs(body):
            if path.endswith((".field", ".field2", ".intro_style", ".role", ".level", ".evergreen")):
                continue
            if schema.copied(text, tn):  # 겹친 조각은 출력하지 않는다(전사 비공개)
                errs.append(f"{path}: 전사와 연속 {schema.COPY_RUN}자 넘게 같다(옮김) — 요약해 다시 쓴다")
    return errs
