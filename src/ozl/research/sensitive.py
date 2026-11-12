#!/usr/bin/env python3
"""민감 소재 1차 표시 — 갈래별 기준(2026-11-13 확정: private/plan/민감기준_확정안_초안_20261110_215144.md 의 제안과 사용자 결정)을
낱말 규칙으로 옮긴 것.

후보 묶음에 RED/YELLOW/GREEN 을 붙여 주는 **사전 표시기**다. 최종 판정은 카드를 쓰는 쪽이 한다.
- RED    = 다루지 않는다: 국내 정당·정치인 평가와 공방 / 국내 개인의 형사 사건과 피해자 / 사생활 / 고인·유족을 다루는 사건 보도 /
           비하 낱말 / 수사기관 개편 공방
- YELLOW = 통계·해외 비교·시장 메커니즘으로만: 국내 정책 찬반 / 정부·대통령실 발표의 정책 내용 / 국내 선거 제도·관리 /
           사건·사고 / 사법·범죄 통계와 제도 / 해외의 형사 사건 / 젠더 갈등·종교 단체(비하 낱말이 없을 때) / 자살
- 해외 정치·선거·지정학은 GREEN 이다.

낱말 규칙이라 놓치기도 하고 잘못 막기도 한다. 그래서 쓰는 쪽은 둘을 같이 한다(절차서 §1 2단계 문턱 3):
  GREEN·YELLOW 로 나온 묶음에도 기준을 직접 적용하고, RED 로 빠진 묶음 가운데 큰 것은 사유를 읽어 잘못 막힌 것이 없는지 본다.

해외로 '풀어 주는' 규칙은 풀 근거가 글 안에 분명할 때만 쓴다.
  정치 낱말: (1) 낱말 바로 앞(8자 안)에 해외 표지가 붙어 있다. 또는
             (2) 같은 글이나 같은 묶음(context) 어딘가에 해외 표지가 있고 국내 표지는 어디에도 없다.
             '민주당'은 나라 이름만으로는 풀지 않는다 — 바로 앞에 '미국·美·미'가 붙었거나 미국 정치임을 가리키는 표지(_US_POLITICS)가 있어야 한다
             ('민주당, 미국 관세 협상 두고 정부 비판'은 국내다).
  형사 사건·사망 보도: 같은 글 안에서 해외 표지가 그 낱말보다 **앞에** 있고 국내 표지·국내 지명이 없을 때만 해외 사건으로 본다.
             묶음의 다른 제목에 있는 해외 낱말로는 풀지 않는다('…1심 선고…미국 언론 주목'은 국내 사건이다).
  '여당·국회·원내대표'처럼 해외에도 있는 말은 바로 앞에 해외 표지가 붙으면 국내 표지로 치지 않는다('프랑스 집권 여당').

알려진 한계(규칙을 더 넓히지 않고 쓰는 쪽의 판정에 맡긴다): 나라 이름이 없는 해외 기업·인물 기사 속의 '지지율·청문회',
  호칭 없이 이름만 나오는 인물의 형사 사건, 영문 기사의 한국 선거 관리 소식(RED 로 남는다), '유족'만 있는 기사(YELLOW),
  제목은 심급 낱말뿐이고 민사 소송임은 요약에만 적힌 기사(RED 로 남는다), 나라 이름 없이 도시 이름만 나오는 해외 사건(RED 로 남는다).
  2026-11-13 에 다른 에이전트와 Codex 가 두 차례 반박 검토했고, 그때의 반례는 tests/test_scout.py 의 REVIEW 목록이다.
"""
from __future__ import annotations

import re

NEAR = 8   # 정치 낱말 앞 몇 글자 안에 해외·국내 표지가 있어야 '붙어 있다'고 보는가
_B = r"(?<![가-힣])"   # 앞이 한글이면(사람 이름·다른 낱말의 일부) 그 낱말로 보지 않는다

_KR_PARTY_NAME = r"더불어민주당|국민의힘|국힘|조국혁신당|개혁신당|진보당|정의당|기본소득당|與|野"
_AMBIGUOUS_PARTY = r"민주당"
# 선거 이름. '최대선사'·사람 이름 속의 글자는 잡지 않는다
_ELECTION_EVENT = r"(?:(?<![가-힣])|(?<=미)|(?<=차기)|(?<=조기))대선|(?:(?<![가-힣])|(?<=조기)|(?<=차기))총선|지방선거|보궐선거|재보선"
# 사람 이름의 일부일 수 있는 '경선'은 앞이 한글이 아닐 때와 정해 둔 앞말일 때만 잡는다(전경선 시의원 ≠ 경선).
# '여야 합의'는 입법 절차라 공방으로 치지 않는다(_LEGISLATION 에서 YELLOW).
_POLITICS = (_ELECTION_EVENT + r"|여당|야당|여야(?!\s?(?:잠정\s?)?합의)|여·야|당대표|원내대표|최고위원|비대위|"
             r"(?:(?<![가-힣])|(?<=예비)|(?<=당내)|(?<=대선)|(?<=총선))경선|공천|지지율|여론조사|출마|후보 단일화|"
             r"탄핵|특검|국정조사|국정감사|청문회|계엄|내란|체포동의안|필리버스터")
_LEGISLATION = r"여야\s?(?:잠정\s?)?합의|본회의 통과|본회의 의결"
_REFORM_FIGHT = r"검찰개혁"
_REFORM_AGENCY = r"중수청|중대범죄수사청"   # 기관 이름만 나오면 YELLOW, 개편을 둘러싼 다툼 낱말과 함께면 RED
_FIGHT_WORD = r"공방|반발|논란|갈등|불만|폐지"

# 해외 표지. 두 글자 나라 이름은 앞이 한글이면 잡지 않는다(김영국 씨, 원칙이란). '하원'은 의회 용례일 때만(어린이집 하원 ≠ 의회)
_CONGRESS = (r"(?:미국|美|연방|" + _B + r"미)\s?(?:상원|하원)|" + _B + r"(?:상원|하원)\s?(?:의원|의장|선거|표결|통과|다수당|원내대표|장악|청문회|의석|개표|판세)|"
             r"상·하원")   # 앞이 한글이면 사람 이름이다(김상원 의원)
_FOREIGN = (_B + r"(?:미국|일본|중국|영국|독일|대만|호주|북한|태국|칠레|페루|홍콩|몽골|이란|인도(?!적|네|주의|양|받|되|하|해))|"
            + _B + r"미(?:\s(?=[가-힣])|(?=대선))|美|英|獨|佛|(?<![\d가-힣])日(?!報)|" + _B + r"中(?!企)|"
            r"트럼프|백악관|공화당|중간선거|주지사|텍사스|캘리포니아|자민당|시진핑|러시아|푸틴|우크라이나|유럽|(?<![A-Za-z])EU(?![A-Za-z])|"
            r"프랑스|이탈리아|스페인|폴란드|헝가리|이스라엘|대이란|브라질|아르헨|멕시코|캐나다|튀르키예|사우디|베네수엘라|파라과이|"
            r"싱가포르|인도네시아|베트남|필리핀|말레이시아|파키스탄|남아공|케냐|나이지리아|이집트|이라크|시리아|레바논|카타르|"
            r"네덜란드|벨기에|스웨덴|노르웨이|핀란드|덴마크|오스트리아|스위스|그리스|포르투갈|체코|루마니아|콜롬비아|뉴질랜드|" + _CONGRESS)
_US_POLITICS = _CONGRESS + r"|중간선거|공화당|주지사|백악관|블루웨이브|블루쓰나미|美 의회|미 의회|연방의회|美민주|미 민주|美 민주"
_US_ATTACHED = r"(?:미국|美|" + _B + r"미)\s?$"   # '민주당' 바로 앞에 붙은 나라 표지

_DOMESTIC = r"국내|한국|우리나라|정부·여당|당정"   # 정치 낱말 바로 앞에 붙으면 국내
_KR_FIGURE = r"윤석열|이재명|김건희|김혜경|문재인|박근혜|이명박"
_KR_OFFICE = (r"(?:서울|부산|인천|대구|광주|대전|울산|세종)\s?시장|(?:경기|강원|충북|충남|전북|전남|경북|경남|제주)\s?(?:도)?지사|"
              r"구청장|시의원|도의원|구의원|교육감")
# 글·묶음 어디에 있든 국내임을 가리키는 표지
_DOMESTIC_FIXED = (_KR_PARTY_NAME + r"|" + _KR_FIGURE + r"|" + _KR_OFFICE + r"|李|靑|尹|청와대|대통령실|당정|민주당\s?대표|"
                   r"국내 정치|한국 정치|국내 정당|국내 선관위|중앙선관위|중앙선거관리위원회")
# 해외에도 있는 말 — 바로 앞에 해외 표지가 붙으면 국내 표지로 치지 않는다
_DOMESTIC_ROLE = r"여야|여·야|여당|야당|국회|원내대표|당대표|최고위|국정"
# 형사 사건·사망 보도가 국내 일임을 가리키는 지명
_KR_PLACE = r"서울|부산(?!물)|인천|대구|광주|(?<!세계)대전(?!환)|울산|세종|경기도|강원|충북|충남|전북|전남|경북|경남|제주|강남|한국인|국내|한국(?=\s?(?:경찰|검찰|법원|정부|국회))"

_GOV_KR = r"李대통령|李 대통령|(?<![가-힣])이 대통령|이재명 대통령|청와대|靑|대통령실|김혜경 여사|(?<![가-힣])김 여사"
_GOV_AMBIG = r"대통령 \"|대통령 “|여사|국회의원|전 의장"   # 해외 인물일 수도 있는 꼴 — 해외 맥락이면 표시하지 않는다
_ELECTION_ADMIN = r"선관위|선거관리위원회|사전투표|투표율|투표용지|개표"
_ELECTION_RESULT = r"당선|낙선|접전|압승|참패|득표|박빙|출구조사|후보"   # 이 낱말이 있으면 선거 관리 기사로 낮추지 않는다

# 형사 절차임이 분명한 낱말 / 민사에도 쓰는 심급 낱말
_KR_CRIMINAL = (r"구속영장|구속기소|구속 기소|불구속 기소|구속 송치|불구속 송치|검찰 송치|송치|법정구속|징역|집행유예|실형|압수수색|"
                r"혐의|유죄|무죄|입건|체포(?!동의안)|출소|가석방|특별사면|수감|(?<!불)기소|형사\s?재판|형사소송|횡령|배임|뇌물")
_KR_INSTANCE = r"(?<!\d)[12]심|항소심|상고심|선고 공판"
_CIVIL = r"손해배상|특허|승소|패소|민사|행정소송|상표권|저작권|가처분"
_SURNAME = "김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진지엄채원천방공현함변염여추도소석선설마길위표명기반왕금옥육인맹제탁국어은편용"
_PERSON = (r"[가-힣]{2,4}\s?(?:씨|의원|대표|회장|부회장|사장|장관|지사|총장|위원장|이사장|교수|대통령)"
           r"|(?:전|前)\s?(?:의원|대표|회장|장관|시장|지사|총장|위원장|대통령)"
           r"|(?:서울|부산|인천|대구|광주|대전|울산|세종)\s?시장"
           r"|(?:배우|가수|아이돌|개그맨|방송인|유튜버|아나운서)\s[가-힣]{2,4}"
           rf"|(?<![가-힣])[{_SURNAME}]모?\s?씨(?![가-힣])|[A-Z]\s?씨|\(\d{{2}}\)|\d{{2}}대\s?(?:남성|여성|남|여)(?![가-힣])|피고인|피의자|용의자")
_VIOLENT = (r"살인(?!물가|적|\s?더위|\s?일정)|살해|성폭행|성폭력|성범죄|성추행|불법촬영|아동학대|스토킹|학교폭력|가정폭력|데이트\s?폭력|"
            r"숨진 채|폭행|흉기|절도|난동|방화(?!벽|문|셔터|복|구획)|성관계 강요|성매매 강요|감금|납치|유괴|묻지마")
_STATS = r"통계|발생률|건수|추이|실태조사"   # 특정인이 없고 집계만 다루면 범죄 통계로 본다
_VICTIM_WORD = r"피해자"                      # 단독으로는 표시하지 않는다(보이스피싱 피해자 지원 등)
_BEREAVED = r"유족(?!\s?연금|\s?급여|\s?보상(?:금|\s?제도|\s?기준|\s?확대))|유가족|희생자|추모식|추모제|분향소"
_PRIVATE = (r"불륜|열애|파경|혼외자|혼외 관계|내연녀|내연남|내연 관계|결별설|결별 인정|이혼 소송(?!\s?(?:통계|건수))|이혼설|합의 이혼|이혼 조정|"
            r"이혼\s?재산분할|섹스\s?스캔들|(?<![가-힣])성\s?스캔들|사생활(?=\s?(?:논란|의혹|폭로|루머|유출))")
_DECEASED = r"시신(?!경)|빈소|故\s?(?=[가-힣])|고\(故\)|영결식"
_SLUR = (r"여혐|남혐|한남(?!동|\d|더힐|대교|뉴타운|오거리|역|대|초|IC|[가-힣]?구역)|김치녀|맘충|틀딱|급식충|전라디언|개독|"
         r"이슬람 혐오|난민 혐오|일베|메갈|워마드")
_GENDER = r"젠더 갈등|이대남|이대녀|페미"
_RELIGION = r"신천지|통일교|사이비|이단|종교 편향"
_KR_POLICY = (r"노란봉투법|중대재해처벌법|상법 개정|세법 개정|법인세|종부세|금투세|상속세|부동산 대책|공시가격|전세 대책|최저임금|"
              r"연금개혁|국민연금 개혁|의대 증원|의정 갈등|주 4일제|주4일제|정년 연장|노동시간|추경|예산안|기본소득|민생회복")
_ACCIDENT = r"참사|사망|숨져|추락|붕괴|화재|(?<!수요\s)(?<!주문\s)(?<!인기\s)폭발(?!적|력|성)|침몰|추돌|산사태|실종"
_SUICIDE = r"자살|극단적 선택"

_EN_KOREA = r"\b(?:south korea(?:n|'s)?|seoul|yoon suk[- ]yeol|lee jae[- ]myung)\b|(?<!north )\bkorea(?:n|'s)?\b"
# 다른 나라의 선거는 한국 정치 낱말로 세지 않는다(대소문자를 가린다: 'US' ≠ 'us')
_EN_FOREIGN_ELECTION = (r"\b(?:US|U\.S\.|American|Japanese|Chinese|Taiwan(?:ese)?|German|French|UK|British|European)\s+"
                        r"(?:presidential\s+|general\s+|midterm\s+)?elections?\b")
_EN_POLITICS = (r"\b(?:elections?|by-?elections?|impeach\w*|ruling party|opposition party|prosecut\w*|indict\w*|lawmakers?|sentenc\w*|"
                r"martial law|arrest\w*)\b")
_EN_JUSTICE = r"\b(?:indict\w*|convicted|sentenced|charged with|pleads? guilty|found guilty|guilty of|arrested|on trial)\b"
_EN_VICTIM = r"\b(?:rape|sexual assault|child abuse|murder victims?|stabbing victims?|bereaved famil\w+)\b"
_EN_PRIVATE = (r"\b(?:extramarital|mistress|sex scandal|an affair|affair with|(?:alleged|love|secret|second|his|her)\s+(?:\w+\s+)?affair|"
               r"confirms? divorce|files? for divorce|divorce settlement)\b")
_ORDER = {"GREEN": 0, "YELLOW": 1, "RED": 2}


def _has(pat: str, text: str, flags: int = 0) -> list[str]:
    return sorted(set(m.group(0) for m in re.finditer(pat, text, flags)))


def _is_domestic(text: str) -> bool:
    """글에 국내임을 가리키는 표지가 있는가. 해외에도 있는 말(여당·국회 등)은 바로 앞에 해외 표지가 붙지 않았을 때만 센다."""
    if re.search(_DOMESTIC_FIXED, text):
        return True
    for m in re.finditer(_DOMESTIC_ROLE, text):
        if not re.search(_FOREIGN, text[max(0, m.start() - NEAR):m.start()]):
            return True
    return False


def _foreign_event(t: str, pos: int) -> bool:
    """t[pos] 에서 시작하는 낱말이 해외 사건으로 읽히는가 — 같은 글에서 해외 표지가 그보다 앞에 있고 국내 표지·국내 지명이 없을 때만."""
    return bool(re.search(_FOREIGN, t[:pos])) and not _is_domestic(t) and not re.search(_KR_PLACE, t)


def _domestic_politics(t: str, context: str = "") -> list[str]:
    """국내 정치로 읽히는 낱말들. 모듈 머리말의 조건으로 해외임이 드러난 것은 뺀다."""
    whole = f"{t} {context}"
    domestic_anywhere = _is_domestic(whole)
    foreign_anywhere = bool(re.search(_FOREIGN, whole))
    us_politics_anywhere = bool(re.search(_US_POLITICS, whole))
    hits = [m.group(0) for m in re.finditer(_KR_PARTY_NAME, t)]
    for m in re.finditer(f"{_AMBIGUOUS_PARTY}|{_POLITICS}", t):
        w = m.group(0)
        if w == "민주당" and t[max(0, m.start() - 3):m.start()] == "더불어":
            continue   # 위에서 이미 셌다
        before = t[max(0, m.start() - NEAR):m.start()]
        if w == "민주당":
            if re.search(_DOMESTIC, before):
                hits.append(w)
                continue
            if re.search(_US_ATTACHED, before) or re.search(_US_POLITICS, before):
                continue   # '미국 민주당', '공화당·민주당'
            if us_politics_anywhere and not domestic_anywhere:
                continue
            hits.append(w)
            continue
        if re.search(_DOMESTIC, before):
            hits.append(w)
            continue
        if re.search(_FOREIGN, before):
            continue   # (1) 바로 앞에 해외 표지
        if foreign_anywhere and not domestic_anywhere:
            continue   # (2) 글·묶음 어딘가에 해외 표지가 있고 국내 표지는 없다
        hits.append(w)
    return sorted(set(hits))


def _spots(pat: str, t: str) -> list[tuple[str, int]]:
    return [(m.group(0), m.start()) for m in re.finditer(pat, t)]


def classify(text: str, context: str = "") -> dict:
    """문자열 하나(제목+요약)를 받아 {"level", "reasons"} 를 돌려준다. context 는 같은 묶음의 다른 제목들(정치 낱말의 해외·국내를 가르는 데만 쓴다)."""
    t = text or ""
    whole = f"{t} {context or ''}"
    foreign = bool(re.search(_FOREIGN, whole))
    domestic = _is_domestic(whole)
    person = bool(re.search(_PERSON, t))
    reasons: list[tuple[str, str]] = []

    pol = _domestic_politics(t, context or "")
    admin = _has(_ELECTION_ADMIN, t)
    if pol:
        party = re.search(f"{_KR_PARTY_NAME}|{_AMBIGUOUS_PARTY}", t)
        only_event_names = all(re.fullmatch(_ELECTION_EVENT, w) for w in pol)   # 판세·후보 낱말이 없고 선거 이름뿐인가
        if admin and not party and only_event_names and not re.search(_ELECTION_RESULT, t):
            reasons.append(("YELLOW", f"국내 선거 제도·관리 — 제도와 통계로만({', '.join(admin[:3])})"))
        else:
            reasons.append(("RED", f"국내 정당·선거·정치 공방({', '.join(pol[:3])})"))
    elif _has(f"{_AMBIGUOUS_PARTY}|{_POLITICS}", t):
        reasons.append(("GREEN", "해외 정치 맥락"))
    if admin and not pol and (domestic or not foreign):
        reasons.append(("YELLOW", f"국내 선거 제도·관리 — 제도와 통계로만({', '.join(admin[:3])})"))
    law = _has(_LEGISLATION, t)
    if law:
        reasons.append(("YELLOW", f"국회 입법 — 법안 내용으로만({', '.join(law[:3])})"))
    fight = _has(_REFORM_FIGHT, t)
    agency = _has(_REFORM_AGENCY, t)
    if fight or (agency and re.search(_FIGHT_WORD, t)):
        reasons.append(("RED", f"수사기관 개편 공방({', '.join((fight + agency)[:3])})"))
    elif agency:
        reasons.append(("YELLOW", f"수사기관 — 제도와 절차로만({', '.join(agency[:3])})"))
    gov = _has(_GOV_KR, t)
    gov_ambig = _has(_GOV_AMBIG, t)
    if gov or (gov_ambig and (domestic or not foreign)):   # 해외 대통령의 발언('이란 대통령 "…"')은 여기 들지 않는다
        reasons.append(("YELLOW", f"정부·대통령실 발언 — 정책 내용만({', '.join((gov + gov_ambig)[:3])})"))

    crim = _spots(_KR_CRIMINAL, t)
    inst = _spots(_KR_INSTANCE, t)
    if crim or inst:
        words = sorted(set(w for w, _ in crim + inst))
        if all(_foreign_event(t, p) for _, p in crim + inst):
            reasons.append(("YELLOW", f"해외 사법 사건 — 경위와 영향으로만({', '.join(words[:3])})"))
        elif person and (crim or not re.search(_CIVIL, t)):
            reasons.append(("RED", f"진행 중 사법 절차({', '.join(words[:3])})"))
        else:
            reasons.append(("YELLOW", f"사법 통계·제도·민사({', '.join(words[:3])})"))
    violent = _spots(_VIOLENT, t)
    vwords = sorted(set(w for w, _ in violent))
    victim = _has(_VICTIM_WORD, t)
    if violent:
        if all(_foreign_event(t, p) for _, p in violent):
            reasons.append(("YELLOW", f"해외 사건 — 경위와 영향으로만({', '.join(vwords[:3])})"))
        elif re.search(_STATS, t) and not person:
            reasons.append(("YELLOW", f"범죄 통계 — 집계와 제도로만({', '.join(vwords[:3])})"))
        else:
            reasons.append(("RED", f"형사 사건·피해자({', '.join((vwords + victim)[:3])})"))
    acc = _spots(_ACCIDENT, t)
    awords = sorted(set(w for w, _ in acc))
    bereaved = _has(_BEREAVED, t)
    death = [(w, p) for w, p in acc if w in ("사망", "숨져")]
    if bereaved and (acc or violent):
        abroad = all(_foreign_event(t, p) for _, p in acc + violent)
        reasons.append(("YELLOW" if abroad else "RED", f"사망자·유족을 다루는 보도({', '.join(bereaved[:3])})"))
    elif death and person and not re.search(_STATS, t) and not all(_foreign_event(t, p) for _, p in death):
        reasons.append(("RED", f"특정인의 사망을 다루는 보도({', '.join(sorted(set(w for w, _ in death)))})"))
    elif bereaved:
        reasons.append(("YELLOW", f"유족·희생자 소재 — 주의({', '.join(bereaved[:3])})"))
    private = _has(_PRIVATE, t)
    if private:
        reasons.append(("RED", f"사생활({', '.join(private[:3])})"))
    dead = _spots(_DECEASED, t)
    if dead:
        abroad = all(_foreign_event(t, p) for _, p in dead)
        reasons.append(("YELLOW" if abroad else "RED", f"고인 소재({', '.join(sorted(set(w.strip() for w, _ in dead))[:3])})"))
    slur = _has(_SLUR, t)
    if slur:
        reasons.append(("RED", f"비하 낱말({', '.join(slur[:3])})"))
    soft = _has(_GENDER, t) + _has(_RELIGION, t)
    if soft and not slur:
        reasons.append(("YELLOW", f"젠더·종교 갈등 — 통계와 해외 비교로만({', '.join(soft[:3])})"))
    policy = _has(_KR_POLICY, t)
    if policy:
        reasons.append(("YELLOW", f"국내 정책 찬반 — 통계·해외 비교로만({', '.join(policy[:3])})"))
    if acc and not violent:
        reasons.append(("YELLOW", f"사건·사고 — 피해자 소재 주의({', '.join(awords[:3])})"))
    if _has(_SUICIDE, t):
        reasons.append(("YELLOW", "자살 — 통계와 예방 제도로만"))

    en = re.sub(_EN_FOREIGN_ELECTION, " ", t)
    if re.search(_EN_KOREA, en, re.I):
        if re.search(_EN_POLITICS, en, re.I) or re.search(_EN_JUSTICE, en, re.I):   # 어순과 무관하게 둘 다 있으면
            reasons.append(("RED", "국내 정치·사법(영문 기사)"))
    elif re.search(_EN_JUSTICE, en, re.I):
        reasons.append(("YELLOW", "해외 사법 사건(영문 기사) — 경위와 영향으로만"))
    if re.search(_EN_VICTIM, t, re.I):
        reasons.append(("RED", "형사 사건·피해자(영문 기사)"))
    if re.search(_EN_PRIVATE, t, re.I):
        reasons.append(("RED", "사생활(영문 기사)"))
    level = max((lv for lv, _ in reasons), key=_ORDER.get, default="GREEN")
    return {"level": level, "reasons": [r for lv, r in reasons if lv == level]}


def classify_item(title: str, summary: str = "", context: str = "") -> dict:
    """기사 하나(제목과 요약)의 판정. RED 는 제목에 근거가 있을 때만 준다.
    요약에만 민감 낱말이 있으면(다른 기사를 소개하는 문장이 요약에 섞이는 일이 흔하다) YELLOW 로 표시하고 사유에 그렇게 적는다."""
    by_title = classify(title, f"{summary or ''} {context or ''}")
    if by_title["level"] == "RED" or not (summary or "").strip():
        return by_title
    full = classify(f"{title} {summary}", context)
    if full["level"] == "RED":
        return {"level": "YELLOW", "reasons": [f"요약에만 있는 낱말 — 본문 확인: {r}" for r in full["reasons"]]}
    return full


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
