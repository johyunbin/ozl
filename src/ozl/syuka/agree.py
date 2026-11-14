"""두 모델 추출 자료의 칸별 일치율(계획 7-4절 기준). '정확도'가 아니라 두 모델이 같은 답을 낸 비율이다.

- field·intro_style: 같은 값 · sensitive: 같은 집합(둘 다 빈 목록도 일치)
- people·orgs: 같은 대상끼리 짝지은 뒤 자카드(짝 수 ÷ (a 수 + b 수 − 짝 수)) ≥ 0.6(둘 다 비면 일치)
- event_period: 시작·끝의 연-월이 같음(둘 다 '특정 시기 없음'도 일치)

계산 이력(기준 85%·0.6·연과 월은 그대로다):
- 1판 계산: 이름을 직함만 떼고 정규화한 집합의 자카드.
- 2판 계산(2026-11-14): 같은 대상의 다른 표기를 같게 본다 — (1) 외래어 표기 차이 목록 `PERSON_TOKEN_ALIAS`·`ORG_ALIAS`
  (1차 자료에서 두 모델이 같은 대상을 달리 적은 것만), (2) 영문 가운데 글자(F.) 떼기, (3) 한쪽이 성만 적고 다른 쪽이
  전체 이름을 적으면 성이 같을 때 같은 사람, (4) 기관 앞의 나라 이름("미국 재무부"·"미 재무부"·"재무부"),
  (5) 괄호 속 다른 이름("인도공과대학(IIT)"), 기관 이름 속 '대한민국'과 '한국', (6) 1판 값을 2판 값으로 옮김(`schema.V1_TO_V2` — 분야 두 값 합침, 도입 방식 이름).
  같은 1판 자료에 2판 계산만 적용한 값은 `agree --schema-version 1` 로 따로 낸다.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import schema

JACCARD_MIN = 0.6
PASS_RATE = 0.85
FIELDS = ("field", "sensitive", "intro_style", "people", "orgs", "event_period")

# 직함, 표기 사전, 나라 앞말은 names.py 에 있다(2판 사전 그대로 — 3판 사전은 여기서 쓰지 않는다).
from .names import _ORG_MARK, _TITLE_TAIL, COUNTRY_PREFIX, ORG_ALIAS, PERSON_TOKEN_ALIAS, TITLES  # noqa: E402,F401


def norm_person(name: str) -> str:
    """직함을 떼고, 영문 가운데 글자를 떼고, 외래어 표기 차이를 맞춘 이름(공백 없음)."""
    return "".join(_person_tokens(name))


def _person_tokens(name: str) -> list[str]:
    toks = [t for t in re.split(r"\s+", name.lower().strip()) if t and t not in TITLES]
    toks = [re.sub(r"[·.\-]", "", t) for t in toks]
    toks = [t for t in toks if t and not re.fullmatch(r"[a-z]", t)]  # 영문 가운데 글자(F.)
    toks = [PERSON_TOKEN_ALIAS.get(t, t) for t in toks]
    if toks:
        toks[-1] = _TITLE_TAIL.sub("", toks[-1]) or toks[-1]
    return toks


def norm_org(name: str) -> str:
    """앞의 나라를 '미국' 꼴로 맞추고 공백·문장부호를 뗀 기관 이름(나라는 남긴다)."""
    country, rest = _org_split(name)
    return _org_core(rest, country)


def _org_core(s: str, country: str = "") -> str:
    """나라를 뗀 이름에 별칭을 적용한 뒤 나라를 앞에 붙인다("독일 사민당" → "독일사회민주당")."""
    s = re.sub(r"[\s·.,\-]", "", _ORG_MARK.sub("", s.lower().strip())).replace("대한민국", "한국")
    return country + ORG_ALIAS.get(s, s)


def _org_split(name: str) -> tuple[str, str]:
    """('미국', '재무부') — 띄어 쓴 나라 이름이 앞에 있을 때만. 없으면 ('', 이름)."""
    head, _, rest = name.strip().partition(" ")
    if rest and head in COUNTRY_PREFIX:
        return ("미국" if head == "미" else head), rest
    return "", name


def _person_keys(name: str) -> tuple[set[str], str | None]:
    """(바로 맞추는 열쇠들, 성만 적은 이름과 맞출 성). 낱말이 하나면 그 이름 자체가 성 자리에 온다."""
    toks = _person_tokens(name)
    full = "".join(toks)
    return {full}, (toks[-1] if len(toks) > 1 else None)


def _org_keys(name: str) -> tuple[set[str], str | None]:
    """(바로 맞추는 열쇠들, 나라를 뗀 이름). 괄호 속 다른 이름도 열쇠다."""
    country, rest = _org_split(name)
    keys = {_org_core(rest, country)}
    m = re.match(r"^(.*?)\((.+)\)\s*(.*)$", rest)
    if m:
        keys |= {_org_core(m.group(1) + m.group(3), country), _org_core(m.group(2))}
    return keys, (_org_core(rest) if country else None)


def match_count(a: list[str], b: list[str], kind: str) -> tuple[int, int, int]:
    """(a 의 서로 다른 대상 수, b 의 수, 짝 수). 1단계: 열쇠가 겹치는 것끼리. 2단계: 남은 것 가운데
    한쪽의 짧은 이름(성만, 나라 없는 기관)이 다른 쪽의 긴 이름의 성·나라 뗀 이름과 같으면 짝."""
    keyf = _person_keys if kind == "people" else _org_keys
    A = _dedupe([keyf(n) for n in a])
    B = _dedupe([keyf(n) for n in b])
    used_b, pairs = set(), 0
    left_a = []
    for i, (ka, sa) in enumerate(A):
        j = next((j for j, (kb, _) in enumerate(B) if j not in used_b and ka & kb), None)
        if j is None:
            left_a.append(i)
        else:
            used_b.add(j)
            pairs += 1
    for i in left_a:
        ka, sa = A[i]
        for j, (kb, sb) in enumerate(B):
            if j in used_b:
                continue
            # a 가 긴 이름(sa = 성·나라 뗀 이름)이고 b 가 짧은 이름이거나, 그 반대
            if (sa and sb is None and sa in kb) or (sb and sa is None and sb in ka):
                used_b.add(j)
                pairs += 1
                break
    return len(A), len(B), pairs


def _dedupe(items: list[tuple[set[str], str | None]]) -> list[tuple[set[str], str | None]]:
    out = []
    for k, s in items:
        if not any(k & k2 for k2, _ in out):
            out.append((k, s))
    return out


def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def list_jaccard(a: list[str], b: list[str], kind: str) -> float:
    na, nb, p = match_count(a or [], b or [], kind)
    return 1.0 if na == nb == 0 else p / (na + nb - p)


def canon(field: str, value):
    """1판 값을 2판 값으로(합친 값·바꾼 이름). 2판 값은 그대로."""
    m = schema.V1_TO_V2.get(field)
    return m.get(value, value) if m and isinstance(value, str) else value


def same(field: str, a: dict, b: dict) -> bool:
    x, y = canon(field, a.get(field)), canon(field, b.get(field))
    if field == "sensitive":
        return set(x or []) == set(y or [])
    if field in ("people", "orgs"):
        return list_jaccard(x, y, field) >= JACCARD_MIN
    if field == "event_period" and isinstance(x, dict) and isinstance(y, dict):
        return (x.get("start"), x.get("end")) == (y.get("start"), y.get("end"))
    return x == y


def compare(records: list[dict], model_a: str, model_b: str) -> dict:
    """records: db.records() 의 행들(한 판). 두 모델이 다 있는 영상만 견준다."""
    by = defaultdict(dict)
    for r in records:
        by[r["video_id"]][r["model"]] = r
    pairs = {v: m for v, m in by.items() if model_a in m and model_b in m}
    rates, diffs = {}, []
    for f in FIELDS:
        ok = 0
        for vid, m in sorted(pairs.items()):
            a, b = m[model_a]["record"], m[model_b]["record"]
            if same(f, a, b):
                ok += 1
            else:
                diffs.append({"video_id": vid, "field": f, model_a: a.get(f), model_b: b.get(f)})
        rates[f] = {"agree": ok, "n": len(pairs), "rate": round(ok / len(pairs), 4) if pairs else None,
                    "pass": bool(pairs) and ok / len(pairs) >= PASS_RATE}
    secs = {m: [r["seconds"] for v in pairs for r in [by[v][m]] if r["seconds"]] for m in (model_a, model_b)}
    versions = sorted({r.get("schema_version") for v in pairs for r in by[v].values() if r.get("schema_version")})
    return {
        "models": [model_a, model_b], "n_videos": len(pairs),
        "schema_versions": versions, "calc_version": schema.SCHEMA_VERSION,
        "only_one_model": sorted(v for v, m in by.items() if (model_a in m) != (model_b in m)),
        "fields": rates,
        "all_pass": bool(pairs) and all(r["pass"] for r in rates.values()),
        "seconds_median": {m: _median(s) for m, s in secs.items()},
        "disagreements": diffs,
        "note": "두 모델이 같은 답을 낸 비율(일치율)이다. 정확도가 아니다.",
    }


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = len(s) // 2
    return s[k] if len(s) % 2 else (s[k - 1] + s[k]) / 2
