#!/usr/bin/env python3
"""민감 소재 1차 표시 — docs/methodology.md §6 의 임시 기준을 낱말 규칙으로 옮긴 것.

후보 묶음에 RED/YELLOW/GREEN 을 붙여 주는 **사전 표시기**다. 최종 신호등은 카드를 쓰는 사람이 정하고,
이 규칙은 "놓치지 않게 먼저 들이미는" 용도라 과하게 잡는 쪽으로 기운다.
- RED   = 다루지 않는다(국내 정당·선거·정치인 평가 / 진행 중 형사 사건 피해자 / 젠더·종교·지역 비하)
- YELLOW = 통계·해외 비교·시장 메커니즘으로만 다룬다(국내 정책 찬반 / 사건·사고)
- 해외 정치·지정학은 허용이다. 정치 낱말 **바로 앞**(8자 안)에 해외 표지가 붙어 있을 때만 해외 정치로 본다 —
  문장 어딘가에 '미국'이 있다는 이유만으로 국내 정치를 풀어 주지 않는다.
"""
from __future__ import annotations

import re

# 국내 정당 실명 — 앞에 해외 표지가 붙어도(예: '미국 민주당') 동명 정당일 수 있는 것은 _AMBIGUOUS 로 따로 둔다
_KR_PARTY_NAME = r"더불어민주당|국민의힘|조국혁신당|개혁신당|진보당|정의당|기본소득당"
_AMBIGUOUS_PARTY = r"민주당"
_POLITICS = (r"여당|야당|여야|당대표|원내대표|최고위원|비대위|대선|총선|지방선거|보궐선거|재보선|경선|공천|지지율|여론조사|출마|후보 단일화|"
             r"대통령실|용산|탄핵|특검|국정조사|국정감사|청문회|계엄|내란|체포동의안|필리버스터")
_KR_JUSTICE = r"구속영장|구속기소|불구속 기소|1심|2심|항소심|선고 공판|징역|집행유예|검찰 송치|압수수색"
_FOREIGN = (r"미국|美|미 |트럼프|백악관|공화당|일본|日|자민당|중국|中|시진핑|대만|러시아|푸틴|우크라이나|유럽|EU|독일|프랑스|영국|이탈리아|폴란드|"
            r"헝가리|이스라엘|이란|인도|브라질|아르헨티나|멕시코|캐나다|호주|튀르키예|사우디|베네수엘라|북한")
_DOMESTIC = r"국내|한국|우리나라|정부·여당|당정"
_VICTIM = r"피해자|유족|유가족|살인|살해|성폭행|성폭력|성범죄|성추행|불법촬영|아동학대|스토킹|학교폭력|극단적 선택|숨진 채"
_HATE = r"여혐|남혐|페미|젠더 갈등|이대남|이대녀|한남|김치녀|맘충|틀딱|급식충|전라디언|개독|이슬람 혐오|난민 혐오|일베|메갈|워마드"
_RELIGION = r"신천지|통일교|사이비|이단|종교 편향"
_KR_POLICY = (r"노란봉투법|중대재해처벌법|상법 개정|세법 개정|법인세|종부세|금투세|상속세|부동산 대책|공시가격|전세 대책|최저임금|"
              r"연금개혁|국민연금 개혁|의대 증원|의정 갈등|주 4일제|주4일제|정년 연장|노동시간|추경|예산안|기본소득|민생회복")
_ACCIDENT = r"참사|사망|숨져|추락|붕괴|화재|폭발|침몰|추돌|산사태|실종"
_EN_KOREA = r"\b(south korea|south korean|seoul)\b"
_EN_POLITICS = r"\b(election|impeach\w*|ruling party|opposition party|prosecut\w*|indict\w*|lawmakers?)\b"
_EN_VICTIM = r"\b(rape|sexual assault|child abuse|murder victims?|stabbing victims?)\b"
NEAR = 8   # 정치 낱말 앞 몇 글자 안에 해외·국내 표지가 있어야 '붙어 있다'고 보는가
_ORDER = {"GREEN": 0, "YELLOW": 1, "RED": 2}


def _has(pat: str, text: str, flags: int = 0) -> list[str]:
    return sorted(set(m.group(0) for m in re.finditer(pat, text, flags)))


def _domestic_politics(t: str) -> list[str]:
    """국내 정치로 읽히는 낱말들. 바로 앞에 해외 표지가 붙은 것은 뺀다(국내 표지가 붙어 있으면 빼지 않는다)."""
    hits = [m.group(0) for m in re.finditer(_KR_PARTY_NAME, t)]
    for m in re.finditer(f"{_AMBIGUOUS_PARTY}|{_POLITICS}", t):
        if m.group(0) == "민주당" and t[max(0, m.start() - 3):m.start()] == "더불어":
            continue   # 위에서 이미 셌다
        before = t[max(0, m.start() - NEAR):m.start()]
        if re.search(_DOMESTIC, before) or not re.search(_FOREIGN, before):
            hits.append(m.group(0))
    return sorted(set(hits))


def classify(text: str) -> dict:
    """문자열 하나(제목+요약)를 받아 {"level", "reasons"} 를 돌려준다."""
    t = text or ""
    reasons: list[tuple[str, str]] = []
    pol = _domestic_politics(t)
    if pol:
        reasons.append(("RED", f"국내 정당·선거·정치 공방({', '.join(pol[:3])})"))
    elif _has(f"{_AMBIGUOUS_PARTY}|{_POLITICS}", t):
        reasons.append(("GREEN", "해외 정치 맥락"))
    just = _has(_KR_JUSTICE, t)
    if just and not re.search(_FOREIGN, t):
        reasons.append(("RED", f"진행 중 사법 절차({', '.join(just[:3])})"))
    vic = _has(_VICTIM, t)
    if vic:
        reasons.append(("RED", f"형사 사건·피해자({', '.join(vic[:3])})"))
    hate = _has(_HATE, t) + _has(_RELIGION, t)
    if hate:
        reasons.append(("RED", f"젠더·종교·지역 갈등 낱말({', '.join(hate[:3])})"))
    policy = _has(_KR_POLICY, t)
    if policy:
        reasons.append(("YELLOW", f"국내 정책 찬반 — 통계·해외 비교로만({', '.join(policy[:3])})"))
    acc = _has(_ACCIDENT, t)
    if acc and not vic:
        reasons.append(("YELLOW", f"사건·사고 — 피해자 소재 주의({', '.join(acc[:3])})"))
    if re.search(_EN_KOREA, t, re.I) and re.search(_EN_POLITICS, t, re.I):   # 어순과 무관하게 둘 다 있으면
        reasons.append(("RED", "국내 정치(영문 기사)"))
    if re.search(_EN_VICTIM, t, re.I):
        reasons.append(("RED", "형사 사건·피해자(영문 기사)"))
    level = max((lv for lv, _ in reasons), key=_ORDER.get, default="GREEN")
    return {"level": level, "reasons": [r for lv, r in reasons if lv == level]}


def worst(results: list[dict]) -> dict:
    """여러 항목의 판정 가운데 가장 높은 것 — 묶음에 속한 기사 하나라도 RED 면 묶음이 RED 다."""
    if not results:
        return {"level": "GREEN", "reasons": []}
    level = max((r["level"] for r in results), key=_ORDER.get)
    seen, reasons = set(), []
    for r in results:
        if r["level"] == level:
            for x in r["reasons"]:
                if x not in seen:
                    seen.add(x)
                    reasons.append(x)
    return {"level": level, "reasons": reasons}
