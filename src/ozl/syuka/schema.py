"""영상 한 건의 추출 자료 양식(JSON)과 검사기.

파일 모양(판마다 폴더가 다르다 — `EXTRACT_DIRS`):
    {"video_id": "...", "schema_version": 2, "seconds": 412, "record": {...아래 칸...}}

검사기가 잡는 것: 칸 누락·남는 칸, 형식, 목록 밖의 값, 길이·개수 초과, 전사 문장 옮김(정규화 후 연속 16자 이상 같음),
다룬 시기의 정밀도(올린 해의 앞 해보다 이른 시점은 연만)와 올린 달 뒤의 시점.

판 이력:
- 1판(2026-11-14 표본 1차): `private/syuka/extract/`.
- 2판(2026-11-14 표본 2차): 분야 `증시·투자`와 `기업·산업`을 `기업·증시` 하나로 합침(1차에서 서로 바뀐 쌍이 가장 많았다).
  도입 방식 `개인 경험이나 잡담으로 출발`을 `개인 경험으로 출발`로 바꿈(잡담은 건너뛰는 대목이라 값 이름과 지침이 부딪쳤다).
  인물·기관은 각 6개까지. 다룬 시기의 정밀도 규칙. 1판 값 → 2판 값 대응은 `V1_TO_V2`.
"""
from __future__ import annotations

import re

SCHEMA_VERSION = 2

# 판 → 추출 파일 폴더(`private/syuka/` 아래). 1판 자료는 지우거나 덮어쓰지 않는다.
EXTRACT_DIRS = {1: "extract", 2: "extract_20261114_0610"}

# 분야 — 공개 주제 분포(tracks/syuka/analysis/topics_syukaworld.md)의 6분류를 잘게 나눈 것. 값 → 6분류
# 순서가 곧 우선순위다: 한 영상이 두 분야에 걸치면 앞에 있는 값을 고른다(지침 3절).
FIELDS = {
    "전쟁·안보": "국제·지정학",
    "국제 정치·외교": "국제·지정학",
    "부동산": "국내 경제·정책",
    "금리·통화·환율": "금융·증시",
    "에너지·원자재": "국제·지정학",
    "기업·증시": "금융·증시",
    "국내 경제·정책": "국내 경제·정책",
    "해외 경제": "국제·지정학",
    "과학·기술": "역사·과학·기술",
    "사회·인구·노동": "사회·문화",
    "문화·생활": "사회·문화",
    "역사": "역사·과학·기술",
    "그 밖": "기타",
}

# 도입 방식 — 공개 분석 bridge_patterns_public.md §c(세그먼트 시작 훅 58건)의 유형을 묶은 것
INTRO_STYLES = (
    "최근 뉴스에서 출발",          # 날짜가 붙은 뉴스 사건 22%
    "질문으로 출발",              # 질문형 제목 29%
    "숫자나 통계로 출발",          # 의외의 숫자 12%
    "별명·밈·말장난으로 출발",      # 밈·별칭 16%
    "인용으로 출발",              # 발언·보도·논문 인용
    "역사나 옛 사례로 출발",
    "개인 경험으로 출발",          # 본 주제와 이어지는 진행자의 경험(주제와 무관한 잡담은 건너뛴다)
    "그 밖",
)

# 1판 값 → 2판 값(합치거나 이름만 바꾼 것). 일치율을 판끼리 견줄 때 1판 자료에 적용한다.
V1_TO_V2 = {
    "field": {"증시·투자": "기업·증시", "기업·산업": "기업·증시"},
    "intro_style": {"개인 경험이나 잡담으로 출발": "개인 경험으로 출발"},
}
MAX_PEOPLE = MAX_ORGS = 6

SENSITIVE = ("국내 정치와 선거", "젠더", "종교", "지역", "범죄 피해자", "그 밖")  # 빈 목록 = 없음
KOREA_LINK = ("직접", "간접", "없음")
NO_PERIOD = "특정 시기 없음"
PERIOD_RE = re.compile(r"^-?\d{1,4}(-(0[1-9]|1[0-2]))?$")  # 연-월, 월을 모르면 연만(기원전은 음수)

KEYS = ("topic_line", "question", "field", "intro_style", "stages", "claims", "people", "orgs", "countries",
        "korea_link", "event_period", "sensitive", "notes")
COPY_RUN = 15  # 이 글자 수를 넘게(16자 이상) 이어서 같으면 옮김


def norm(s: str) -> str:
    """scripts/publish_gate.py 의 norm 과 같은 정규화 — 공백·문장부호 제거, 소문자."""
    return re.sub(r"[^\w가-힣]+", "", s or "").lower()


def _strs(x, path: str = ""):
    """자료 안의 모든 글(경로, 값)."""
    if isinstance(x, str):
        yield path, x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _strs(v, f"{path}.{k}" if path else k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _strs(v, f"{path}[{i}]")


def copied(text: str, transcript_norm: str, run: int = COPY_RUN) -> str:
    """text 가 전사와 연속 run+1 자 이상 같으면 그 조각(정규화된 글), 아니면 빈 문자열."""
    t = norm(text)
    n = run + 1
    for i in range(len(t) - n + 1):
        if t[i:i + n] in transcript_norm:
            return t[i:i + n]
    return ""


def _str_list(errs, rec, key, lo, hi, maxlen):
    v = rec.get(key)
    if not isinstance(v, list) or not all(isinstance(s, str) and s.strip() for s in v):
        errs.append(f"{key}: 빈 칸 없는 글 목록이어야 한다")
        return
    if not lo <= len(v) <= hi:
        errs.append(f"{key}: {lo}~{hi}개여야 한다(지금 {len(v)}개)")
    for i, s in enumerate(v):
        if len(s) > maxlen:
            errs.append(f"{key}[{i}]: {maxlen}자 초과({len(s)}자)")
    if len({s.strip() for s in v}) != len(v):
        errs.append(f"{key}: 같은 값이 두 번 있다")


def _text(errs, rec, key, maxlen, allow_empty=False):
    v = rec.get(key)
    if not isinstance(v, str) or (not allow_empty and not v.strip()):
        errs.append(f"{key}: 글이어야 한다" + ("" if allow_empty else "(빈 글 안 됨)"))
    elif len(v) > maxlen:
        errs.append(f"{key}: {maxlen}자 초과({len(v)}자)")


def validate(rec: dict, transcript: str | None = None, upload_at: str | None = None) -> list[str]:
    """오류 목록(빈 목록이면 통과). transcript 를 주면 옮김도, upload_at('YYYY-MM-DD …')을 주면 시기 정밀도도 검사한다."""
    if not isinstance(rec, dict):
        return ["record: 객체여야 한다"]
    errs = [f"{k}: 칸 없음" for k in KEYS if k not in rec]
    errs += [f"{k}: 양식에 없는 칸" for k in rec if k not in KEYS]
    _text(errs, rec, "topic_line", 60)
    _text(errs, rec, "question", 100)
    _text(errs, rec, "notes", 300, allow_empty=True)
    if rec.get("field") not in FIELDS:
        errs.append(f"field: 목록 밖의 값 {rec.get('field')!r}")
    if rec.get("intro_style") not in INTRO_STYLES:
        errs.append(f"intro_style: 목록 밖의 값 {rec.get('intro_style')!r}")
    _str_list(errs, rec, "stages", 3, 7, 80)
    _str_list(errs, rec, "people", 0, MAX_PEOPLE, 40)
    _str_list(errs, rec, "orgs", 0, MAX_ORGS, 60)
    _str_list(errs, rec, "countries", 0, 40, 30)

    s = rec.get("sensitive")
    if not isinstance(s, list) or any(x not in SENSITIVE for x in s) or len(set(s)) != len(s):
        errs.append(f"sensitive: {list(SENSITIVE)} 에서 0개 이상, 겹침 없이")

    c = rec.get("claims")
    if not isinstance(c, list) or not 3 <= len(c) <= 8:
        errs.append("claims: 3~8개 목록이어야 한다")
    else:
        for i, x in enumerate(c):
            if not isinstance(x, dict) or set(x) != {"point", "value", "unit"}:
                errs.append(f"claims[{i}]: 칸은 point·value·unit")
                continue
            if not isinstance(x["point"], str) or not x["point"].strip() or len(x["point"]) > 80:
                errs.append(f"claims[{i}].point: 1~80자 글")
            for k in ("value", "unit"):
                if x[k] is not None and (not isinstance(x[k], str) or len(x[k]) > 30):
                    errs.append(f"claims[{i}].{k}: 30자 이내 글 또는 null")
            if x["value"] is None and x["unit"] is not None:
                errs.append(f"claims[{i}]: 수치 없이 단위만 있다")

    k = rec.get("korea_link")
    if not isinstance(k, dict) or set(k) != {"level", "line"}:
        errs.append("korea_link: 칸은 level·line")
    else:
        if k["level"] not in KOREA_LINK:
            errs.append(f"korea_link.level: 목록 밖의 값 {k['level']!r}")
        if not isinstance(k["line"], str) or len(k["line"]) > 80 or (k["level"] != "없음" and not k["line"].strip()):
            errs.append("korea_link.line: 80자 이내 글(직접·간접이면 빈 글 안 됨)")

    p = rec.get("event_period")
    if p != NO_PERIOD:
        if not isinstance(p, dict) or set(p) != {"start", "end"}:
            errs.append(f"event_period: {{start, end}} 또는 {NO_PERIOD!r}")
        elif not all(isinstance(v, str) and PERIOD_RE.match(v) for v in p.values()):
            errs.append("event_period: start·end 는 'YYYY-MM' 또는 'YYYY'")
        elif _period_key(p["start"]) > _period_key(p["end"]):
            errs.append("event_period: start 가 end 보다 늦다")
        elif upload_at:
            errs += _period_vs_upload(p, upload_at)

    if transcript:
        tn = norm(transcript)
        for path, text in _strs({k: v for k, v in rec.items() if k in KEYS}):
            if copied(text, tn):  # 겹친 조각은 출력하지 않는다(전사 비공개)
                errs.append(f"{path}: 전사와 연속 {COPY_RUN}자 넘게 같다(옮김) — 요약해 다시 쓴다")
    return errs


def _period_vs_upload(p: dict, upload_at: str) -> list[str]:
    """올린 해의 앞 해보다 이른 시점은 연만(월을 적지 않는다). 올린 달보다 늦은 시점은 적지 않는다(예정·전망은 기간 밖)."""
    out = []
    uy, um = int(upload_at[:4]), int(upload_at[5:7])
    for k in ("start", "end"):
        y, m = _period_key(p[k])
        if y < uy - 1 and m:
            out.append(f"event_period.{k}: {uy - 1}년보다 이른 시점은 연만 적는다('{y}')")
        if (y, m) > (uy, um):
            out.append(f"event_period.{k}: 올린 달({uy}-{um:02d})보다 늦다 — 예정·전망은 기간에 넣지 않는다")
    return out


def _period_key(v: str) -> tuple[int, int]:
    neg = v.startswith("-")
    y, _, m = v.lstrip("-").partition("-")
    return (-int(y) if neg else int(y), int(m or 0))


def check_file(doc: dict, transcript: str | None = None, upload_at: str | None = None) -> list[str]:
    """파일 전체(겉 칸 + record) 검사."""
    if not isinstance(doc, dict):
        return ["파일: 객체여야 한다"]
    errs = [f"{k}: 칸 없음" for k in ("video_id", "schema_version", "seconds", "record") if k not in doc]
    if doc.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version: {SCHEMA_VERSION} 이어야 한다")
    sec = doc.get("seconds")
    if not isinstance(sec, (int, float)) or isinstance(sec, bool) or sec <= 0:
        errs.append("seconds: 양수(끝 시각 − 시작 시각, date +%s)")
    return errs + validate(doc.get("record"), transcript, upload_at)
