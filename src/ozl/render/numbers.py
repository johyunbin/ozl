#!/usr/bin/env python3
"""덱 사양의 숫자 판독부 — 원칙 하나: **확신이 없으면 수량으로 보고 근거를 요구한다.**

판독 앞에 입력을 정규화한다(모든 공백 문자 — 탭·개행·연속 공백·줄바꿈 없는 공백 — 을 공백 한 칸으로. 숫자와 한글 크기 단위 사이의
공백은, 크기 단위 글자들이 따로 선 낱말이거나 '분의' 가 붙었을 때 붙인다: '70 만 배럴' · '3 백만 달러' · '1 만분의 1'. 다른 한글이 바로
붙은 꼴('3 만원' · '표 3 조명 산업')은 크기 단위인지 낱말인지 가를 수 없어 붙이지 않고, 경계 그물이 앞의 숫자를 조각으로 둔다).
그다음 왼쪽부터 한 번 훑어 토큰 종류를 가르고, 직접 대조와 환산 경계 검사가 같은 결과를 쓴다.

토큰 종류
  qty   수량(가장 길게 하나로): 부호 · 숫자(쉼표·소수) · 분수(1/2 · 1/2.5 · 1/2,000 · 2분의 1) · 한글 크기 단위의 연속과 마지막 자리
        (70만 1천 5백 · 3천 3백만 · 2천3백4십5 · 1억 2,345) · 영문 크기 단위(million·billion… — 뒤에 한글이 붙어도) · %·%p.
        대조는 공백·쉼표를 지운 정규형으로 한다(3천 3백만 = 3천3백만 · 1억 2,345 = 1억2345). 판독하지 못한 숫자 이음(1.2.3 · 1/2/3)은
        조각 내지 않고 뒤의 크기 단위·% 까지 통째로 하나의 토큰(raw:…)으로 두어 기록에 같은 표기가 있어야 통과한다.
        복합 분모(1만분의 1 → 1/[1만] — 분자 뒤 크기 단위 '2분의 1만' 과 다른 정규형) · 영문 percent·percentage points(→ %·%p) 도 읽는다.
        범위의 앞 수가 단위 없이 적혀 있으면 뒤 수의 단위를 같이 쓴다(3~5% 의 3 은 3% · 70~80만 의 70 은 70만 · $3–4 billion 의 3 은 3 billion
        · 3~5년 의 3 은 3년). 범위로 보는 이음은 붙여 쓴 '-'·'–'·'~' 와 공백을 둔 '–'·'~' 다. 공백으로 둘러싼 '-' 는 줄표이고, 통화 기호가 붙은
        금액 뒤의 비율('$100 – 20% 할인')은 범위가 아니다. 뒤 수가 단순한 '수+단위' 꼴이 아니면(70~80만5천 · $3–5B) 앞 수는 조각으로 둔다.
        어떤 꼴로 시작했든(부호·통화 기호·소수점) 본문을 읽은 뒤의 처리(_finish_qty)는 한 곳이다.
        숫자 뒤의 측정 단위 낱말(배럴·달러·명)은 토큰에 넣지 않는다. 숫자 앞에 영문자가 붙어 있어도 수량이다(USD100 million · GDP3%).
        숫자 뒤에 영문자가 바로 붙은 표기(52C · 3.5B · 701k · 5kg)는 글자까지 통째로 한 토큰(raw:52C)이다 — 숫자만 떼면 다른 것이 된다.
  dur   기간: N년간 · N년 만 · N년 동안 · N개월 · N일 · N주 · N시간(소수 포함 — 1.5년), 그리고 달력 꼴이 닫힌 조건을 못 갖춘 'YYYY년'(2000년 6개월 동안).
  word  숫자 없는 수량 낱말(작은 목록: 반년 · 절반 · 갑절 · 두 배 · 세 번 · 열 달 …). 조사가 붙어도 잡는다.
  cal   달력 — 아래 꼴 전체가 맞고, 뒤가 닫힌 조건일 때만:
        꼴: YYYY-MM-DD · YYYY.MM.DD · YYYY-MM · YYYY년 · M월 D일 · M월 · YYYY~YYYY년 · M~M월 · N분기 · June 26, 2007 · June 2007
            · 3/4분기
            (YYYY 는 1000~2999 네 자리. 연도 범위는 '년' 이 붙어야 달력이다 — '2004~2025' 만으로는 수량 범위와 가를 수 없어 수량으로 본다)
        뒤: 문장 끝 · 문장부호 · 정해 둔 조사(_PARTICLES)·꼬리말(판·호·말·초·중·께·쯤)·꼬리말+조사(3월말까지) · 공백 뒤 일반 낱말
            · 공백 뒤 수량이나 다음 달력 꼴.
            공백을 건너 수량·기간·측정 단위 낱말(_BLOCK_WORDS · _BLOCK_ASCII: million · kg · 배럴 · 동안 · 만 · 년 …)이 오거나,
            공백 뒤 기간(6개월)이 오거나, 붙어서 목록 밖 한글·영문자·숫자·%·소수점+숫자가 오면 달력이 아니다.
  ident 식별자 — 자동으로 추측하지 않는다. 사건 번호 꼴(ARB/07/27)과, 사양 맨 위 `identifiers` 목록에 작성자가 적은 표기만.
        숫자만으로 된 표기('49')는 목록에 적어도 식별자로 받지 않는다(면제하면 '49억'·'49개월' 이 같이 빠진다).
        둘 다 일치한 구간 바로 뒤에 소수점·쉼표+숫자 · % · 퍼센트 · 영문 크기 단위 · 한글 크기 단위(뒤가 숫자·측정 단위·문장부호·글 끝일 때)가
        오면 면제하지 않는다(USD100.5 million · USD100,500 million · ARB/07/27%). '49B만으로'·'49B만 남았다'·'49B 조사' 의 '만'·'조' 는
        조사·낱말이라 식별자로 둔다.
수치 주장으로 대조하는 것은 qty · dur · word 다. cal · ident 는 대조하지 않는다(check 가 면제한 식별자를 출력한다).

경계 그물(_mark_fragments) — 판독 규칙이 놓친 것을 받는 마지막 단계
  훑은 뒤에 수량·기간 토큰의 앞뒤를 다시 본다. 앞뒤에 같은 수의 나머지로 보이는 글자(숫자 · [.,/]+숫자 · 토큰에 안 든 %·크기 단위 ·
  크기 단위 뒤 공백+숫자)가 남아 있으면 판독부가 그 표기를 통째로 읽지 못한 것이다. 서로 이어진 토큰은 하나로 묶어 raw 토큰(공백만 지운
  원래 표기)으로 만들어 기록에 같은 표기가 통째로 있어야 맞게 하고, 묶을 짝이 없으면 조각(fragment)으로 표시한다.
  조각은 기록 쪽에서는 근거 목록(pool)에 들지 않고, 화면 쪽에서는 "온전한 수량으로 읽지 못했다"는 오류가 된다.
  그래서 긴 표기의 일부만 떼어 쓴 화면 글이 통과하려면 판독 규칙과 이 그물이 둘 다 놓쳐야 한다.

부호와 범위
  '-'·'–'·'~' 는 앞 수량에 이어져 있으면 범위 연결이다: 바로 뒤(3-5) · 공백 한 칸 뒤($70 –$80 · 12% -3%) · 목록에 있는 측정 단위
  (_UNITS · _UNIT_ASCII)에 붙어서($70/bbl–$80 · $70 per barrel–$80 · 70만 배럴-80만 배럴). 그 밖의 '-'·'–'·'+' 는 부호다 — 설명하는 말 뒤
  (전년비-3% · GDP-3% · 수익률-3%), 단위와 띄어 쓴 뒤(100억원 -3%). 낱말에 붙은 이음표 뒤에 통화 기호가 오면(bbl–$80) 부호가 아니다.
  U+2212(−)는 언제나 부호다(12% −3% 의 −3%). 공백 한 칸이나 통화 기호를 건너도 부호다(− 3% · -$3.5 billion · −$3).
  공백으로 둘러싼 '-' 는 줄표로 본다('지표 - 3% 상승' 의 3% 는 양수).

못 잡는 것(느슨하게 통과시키지 않고 여기에 적는다)
  - 측정 단위 낱말은 비교하지 않는다: '1,234톤' 과 원문 '1,234 t', '70만 배럴' 과 원문 '70만 달러' 를 같은 숫자로 본다.
  - 숫자 없이 수량을 말하는 낱말은 목록에 있는 것만 잡는다('몇 배'·'수년'·'대부분' 같은 막연한 말은 못 잡는다).
    목록 낱말이 서수로 쓰여도('세 번째') 수량으로 잡는다(근거를 요구하는 쪽으로 틀린다).
  - 기록(observed·text)에 같은 표기가 있으면 통과한다. 기록 안의 숫자가 다른 것을 가리켜도(허가 52호의 52 · 표 3 의 3) 같은 숫자로 본다.
    영문자가 붙은 표기(52C)만 글자까지 본다.
  - 공백을 둔 슬래시('736,192 / 1,029,398')는 두 수의 구분으로 본다. 그렇게 적힌 분수('1 / 2')의 분자나 분모만 떼어 써도 통과한다.
  - 괄호로 적은 음수('(3.5)')의 부호는 읽지 못한다.
  - 공백으로 자릿수를 끊은 표기('1 234')는 두 수로 읽는다. 한글로 쓴 수('삼천억')는 읽지 못한다.
  - 숫자 뒤에 띄어 쓴 '크기 단위 글자 + 한글'('3 만원' · '표 3 조명 산업' · 'SGLT2 억제제')은 조각으로 둔다. 맞는 표기도 막는 쪽이다 —
    크기 단위면 붙여 쓰고, 낱말이면 문장부호를 넣거나(표 3: 조명 산업) 식별자로 적는다(SGLT2).
  - 범위 연결로 보는 측정 단위는 목록에 있는 것뿐이다. 목록 밖 단위에 붙은 '-'('70만 가마-80만 가마')는 뒤 수의 부호로 읽는다.
  - 공백을 둔 줄표(–) 앞이 단위 없는 수이고 뒤가 % 이면 범위로 읽어 앞 수에도 % 를 붙인다('100 – 20%' — 통화 기호가 없을 때).
  - 세 자리 이하 연도('918년')는 달력으로 보지 않는다(수량으로 보고 근거를 요구한다).
  - 달력 뒤 '공백 + 일반 낱말' 은 달력으로 둔다. 달력 꼴로 읽힌 표기가 실은 수량이고 뒤의 단위 낱말이 차단 목록
    (_BLOCK_WORDS·_BLOCK_ASCII) 밖이면('2004-11 그램' — 연-월 꼴) 달력으로 면제된다. 붙여 쓴 목록 밖 한글은 수량으로 본다(근거를 요구하는 쪽).
  - 부록 출처 표의 문서 위치 칸(primary_doc_locator — 쪽·조·문단·표 번호)의 숫자는 검사하지 않는다(구조 칸 · build.APPX_STRUCTURAL).
    기관 이름과 교차 출처 기관 이름은 대조한다(build.APPX_CHECKED).
  - 정해 둔 조사 목록 밖의 어미가 달력에 붙으면('3월 18일이니') 수량으로 보고 근거를 요구한다(오실패 쪽으로 틀린다).

열 번의 코드 검토에서 나온 재현 입력은 tests/test_deck_spec.py 에 들어 있고, 조각 무작위 시험이 같이 돈다. 그래도 이 검사만으로 덱의 숫자를 믿지 않는다 —
사양을 쓴 쪽과 다른 눈의 문장 대조, 사람의 원문 대조가 따로 있다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CLAIM_KINDS = ("qty", "dur", "word")


@dataclass(frozen=True)
class Token:
    kind: str
    canon: str
    start: int
    end: int
    fragment: bool = False   # 앞뒤에 숫자 이음이 남은 토큰 — 온전한 수량으로 읽지 못했다는 뜻. 근거가 되지도, 근거를 얻지도 못한다

    @property
    def needs_claim(self) -> bool:
        return self.kind in CLAIM_KINDS


_MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_Y = r"[12]\d{3}"
_M = r"(?:1[0-2]|0?[1-9])"
_D = r"(?:3[01]|[12]\d|0?[1-9])"
_MAGC = "십백천만억조경"
_SCALE = r"(?:thousand|million|billion|trillion|bn|mn)(?![A-Za-z])"
_PCT = r"(?:%p|%포인트|퍼센트포인트|percentage points?(?![A-Za-z])|%|퍼센트|percent(?![A-Za-z])|per cent(?![A-Za-z]))"
_CUR = "$€£¥₩"
_NUM = r"(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)"

_CAL = [
    re.compile(_MONTHS + r" \d{1,2}, ?" + _Y),
    re.compile(_MONTHS + r" " + _Y),
    re.compile(_Y + r"([-.])" + _M + r"\1" + _D),          # YYYY-MM-DD · YYYY.MM.DD
    re.compile(_Y + r"-" + _M + r"(?![\d.])"),               # YYYY-MM
    re.compile(_Y + r" ?[-–~] ?" + _Y + r"년"),              # YYYY~YYYY년 — '년' 없는 범위는 수량 범위와 가를 수 없어 수량으로 본다
    re.compile(_Y + r"년"),
    re.compile(_M + r"월 ?" + _D + r"일"),
    re.compile(_M + r" ?[~–-] ?" + _M + r"월"),
    re.compile(_M + r"월"),
    re.compile(r"[1-4]/4 ?분기"),                             # 3/4분기
    re.compile(r"[1-4] ?분기"),
]
# 달력 꼴 뒤에 붙어도 되는 것(닫힌 목록): 조사 · 판·호 같은 꼬리말
_PARTICLES = ("에서는", "에서도", "에서", "에는", "에도", "부터는", "부터", "까지는", "까지", "보다", "으로는", "으로", "로는",
              "입니다", "이었다", "이라는", "이라", "이며", "이고", "이다", "였다", "인",
              "에", "은", "는", "이", "가", "을", "를", "의", "와", "과", "로", "엔", "도")
_TAILS = ("판", "호", "말", "초", "중", "께", "쯤")
_AFTER_OK = tuple(sorted(_PARTICLES + _TAILS, key=len, reverse=True))
# 달력 꼴 뒤에 공백을 두고 이 낱말이 오면 달력이 아니다(기간 표지 · 측정 단위 · 크기 단위)
_BLOCK_WORDS = {"동안", "간", "만", "만에", "만의", "사이", "이상", "이내", "가량", "넘게", "여", "째", "새", "전", "후",
                "년", "개월", "달", "일", "주", "시간", "배럴", "달러", "원", "톤", "명", "개", "건", "대", "척", "가구", "곳",
                "위", "배", "퍼센트", "포인트"} | set(_MAGC)
_BLOCK_ASCII = ("thousand", "million", "billion", "trillion", "bn", "mn", "kg", "km", "t", "mt", "bbl", "bpd", "b/d",
                "barrel", "barrels", "usd", "dollar", "dollars", "%", "percent", "percentage")
_PUNCT_STOP = r"\s.,;:!?()\[\]「」『』\"'“”‘’·/~→—–−-"
_CASE_NO = re.compile(r"[A-Z]{2,}/\d+(?:/\d+)+")
_DUR = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?|\.\d+) ?(개월|년|일|주|시간)")
_MAGSEG = r"(?:[" + _MAGC + r"]\d*(?:,\d{3})*)+"           # 천3백4십5 — 마지막 일의 자리까지
_QTY = re.compile(
    r"(?P<num>" + _NUM + r")"
    r"(?:(?P<frac>/\d+(?:,\d{3})*(?:\.\d+)?)|(?P<kden>[" + _MAGC + r"]+)? ?분의 ?(?P<kofrac>\d+(?:,\d{3})*(?:\.\d+)?))?"
    r"(?P<mag>" + _MAGSEG + r"(?: \d+(?:,\d{3})*" + _MAGSEG + r")*)?"
    r"(?P<scale> ?" + _SCALE + r")?"
    r"(?P<pct> ?" + _PCT + r")?", re.IGNORECASE)
_RAW_TAIL = re.compile(r"[./]\d")                            # 판독하지 못한 숫자 이음(1.2.3 · 1/2/3) — 조각 내지 않고 통째로
# 식별자 뒤에 이것이 오면 식별자가 아니라 수량의 일부다. 크기 단위 글자(만·조…)는 뒤가 숫자·측정 단위·문장부호·글 끝일 때만 크기 단위로 본다
# ('49B만 남았다' · '49B만으로' · '49B 조사' 의 '만'·'조' 는 조사·낱말).
_UNITS = ("배럴|달러|파운드|유로|위안|루블|리터|가구|세대|마리|원|불|엔|명|개|톤|건|대|척|곳|배|평|주|표|석|권|편|장|호"
          "|kg|km|MW|GW|TEU")
_UNIT_END = "(?:가량|였다|이었다|이다|입니다|이며|이고|이라|쯤|씩|어치|짜리|으로|에서|까지|부터|보다|이나|[은는이가을를의로에와과도만])?(?![가-힣A-Za-z])"
_UNITW = r"(?:" + _UNITS + r")" + _UNIT_END   # 측정 단위 낱말 하나(뒤에 조사·어미가 붙을 수 있고, 다른 낱말로 이어지지 않는다)
_QTY_TAIL = re.compile(r"[.,]\d| ?" + _PCT + r"| ?" + _SCALE + r"| ?[" + _MAGC + r"]+(?:$|(?= ?\d)|(?= ?" + _UNITW + r")|(?=[^ 가-힣])|(?= [A-Za-z]))",
                       re.IGNORECASE)
_LASTGRP = re.compile(r" (\d+(?:,\d{3})*)(?!\d|[.,/]\d)")   # 복합 수량의 마지막 자리: '1억 2,345' 의 ' 2,345'
_TAIL_UNIT = re.compile(r"(?P<scale> ?" + _SCALE + r")?(?P<pct> ?" + _PCT + r")?", re.IGNORECASE)
_RAW_SUFFIX = re.compile(r"(?:[" + _MAGC + r"])*(?: ?" + _SCALE + r")?(?: ?" + _PCT + r")?", re.IGNORECASE)
_WORDS = ["반 토막", "반토막", "반년", "반세기", "절반", "반값", "갑절", "두 배", "세 배", "네 배", "다섯 배", "열 배",
          "두 번", "세 번", "네 번", "다섯 번", "두 달", "석 달", "열 달"]
_WORD = re.compile("|".join(re.escape(w) for w in sorted(_WORDS, key=len, reverse=True)))
_RANGE = "-–~"        # 수량·기간 바로 뒤(또는 숫자에 붙어)이면 범위 연결
_SIGN = "-–−+"        # 그 밖에는 부호. U+2212(−)는 언제나 부호다
_UNIT_NORM = {"%포인트": "%p", "퍼센트포인트": "%p", "퍼센트": "%", "bn": "billion", "mn": "million"}


# 숫자 뒤에 공백을 두고 온 한글 크기 단위: 크기 단위 글자들이 따로 선 낱말이거나(뒤가 공백·숫자·문장부호·글 끝) '분의' 가 붙었을 때만
# 크기 단위로 본다. 다른 한글이 바로 붙은 꼴('3 만원' · '3 만평' · '표 3 조명 산업' · '표 3 만주 지역')은 크기 단위인지 낱말인지 가를 수 없어
# 붙이지 않고, 경계 그물이 앞의 숫자를 조각으로 둔다(근거가 되지도, 근거를 얻지도 못한다).
_MAG_WORD = r"[" + _MAGC + r"]+(?:$|[^가-힣A-Za-z]|분의)"
_SQUEEZE = re.compile(r"(?<=\d) (?=" + _MAG_WORD + r")")


def _squeeze(s: str) -> str:
    """'70 만 배럴'·'3 백만 달러'·'1 만분의 1' 처럼 숫자와 따로 선 한글 크기 단위 사이의 공백을 붙여서 읽는다(_MAG_WORD 조건)."""
    return _SQUEEZE.sub("", s)


def normalize(text) -> str:
    """판독 앞의 입력 정규화: 모든 공백 문자(탭·개행·연속 공백·줄바꿈 없는 공백)를 공백 한 칸으로 접는다."""
    return re.sub(r"\s+", " ", "" if text is None else str(text))


def _dur_canon(d: re.Match) -> str:
    num = d.group(1).replace(",", "")
    return ("0" + num if num.startswith(".") else num) + d.group(2)


def _pct_norm(p) -> str:
    p = re.sub(r"\s+", " ", (p or "").strip().lower())
    if not p:
        return ""
    return "%p" if p in ("%p", "%포인트", "퍼센트포인트") or p.startswith("percentage point") else "%"


def _qty_canon(sign: str, m: re.Match) -> str:
    num = m.group("num").replace(",", "")
    if num.startswith("."):
        num = "0" + num
    if m.group("kofrac"):
        den = num + (m.group("kden") or "")
        body = f"{m.group('kofrac').replace(',', '')}/" + (f"[{den}]" if m.group("kden") else den)  # 2분의 1 → 1/2 · 1만분의 1 → 1/[1만]
    else:
        body = num + (m.group("frac") or "").replace(",", "")
    mag = re.sub(r"[\s,]", "", m.group("mag") or "")
    scale = (m.group("scale") or "").strip().lower()
    pct = _pct_norm(m.group("pct"))
    return ("-" if sign and sign in "-−–" else sign) + body + mag + _UNIT_NORM.get(scale, scale) + pct


def _is_hangul(c: str) -> bool:
    return bool(c) and "가" <= c <= "힣"


def _starts_cal(s: str, i: int) -> bool:
    for rx in _CAL:
        m = rx.match(s, i)
        if m and _cal_ok(s, m.end()):
            return True
    return False


def _cal_ok(s: str, e: int) -> bool:
    """달력 꼴 뒤가 닫힌 조건일 때만 달력이다: 문장 끝 · 문장부호 · 정해 둔 조사·꼬리말 · 공백 뒤 일반 낱말 또는 다음 달력 꼴.
    공백을 건너 수량·기간 낱말(million · kg · 배럴 · 동안 · 만)이 오거나 숫자가 오면(달력 꼴이 아닌) 달력이 아니다."""
    rest = s[e:]
    if not rest:
        return True
    c = rest[0]
    if c.isdigit() or c == "%" or (c.isascii() and c.isalpha()):
        return False
    if c in ".," :
        return not rest[1:2].isdigit()
    if c in "~-–−" and rest[1:2].isdigit():
        return False
    if _is_hangul(c):
        for p in _AFTER_OK:
            if rest.startswith(p) and not _is_hangul(rest[len(p):len(p) + 1]):
                return _cal_ok(s, e + len(p)) if rest[len(p):len(p) + 1] == " " else True
        for t in _TAILS:  # 꼬리말 뒤에 조사가 이어진 꼴(3월말까지 · 2026년판은)
            if rest.startswith(t):
                for p in sorted(_PARTICLES, key=len, reverse=True):
                    k = len(t) + len(p)
                    if rest[len(t):].startswith(p) and not _is_hangul(rest[k:k + 1]):
                        return _cal_ok(s, e + k) if rest[k:k + 1] == " " else True
        return False
    if c == " ":
        m = re.match(r" ([^" + _PUNCT_STOP + r"]+)", rest)
        if not m:
            return True
        word = m.group(1)
        if word[0].isdigit():
            # 다음이 기간이면 복합 기간(2000년 6개월 동안)이라 달력이 아니다. 다음이 수량·달력이면 달력(2001년 147만 배럴 · 2026년 1분기)
            return not (_DUR.match(s, e + 1) and not _starts_cal(s, e + 1))
        head = re.match(r"[A-Za-z%/]+", word)  # 영문 단위에 한글 조사가 붙어도 본다(kg으로 · million달러)
        if head:
            lw = head.group(0).lower()
            if any(lw == x or lw.startswith(x) and not lw[len(x):len(x) + 1].isalpha() for x in _BLOCK_ASCII):
                return False
            if word.isascii():
                return True
        base = word
        for p in sorted(_PARTICLES, key=len, reverse=True):  # 조사만 떼고 본다(꼬리말 '판'을 떼면 '원판'이 '원'이 된다)
            if base.endswith(p) and len(base) > len(p):
                base = base[:-len(p)]
                break
        return word not in _BLOCK_WORDS and base not in _BLOCK_WORDS
    return True


def _qty_tail(s: str, b: int) -> bool:
    """식별자 꼴 바로 뒤가 수량의 이음인가. 크기 단위 글자 뒤 '공백+숫자' 가 달력·기간이면 그 글자는 보조사다(49B만 3월까지 유효)."""
    m = _QTY_TAIL.match(s, b)
    if not m:
        return False
    e = m.end()
    if s[e - 1:e] in tuple(_MAGC) and s[e:e + 1] == " " and s[e + 1:e + 2].isdigit() and (_starts_cal(s, e + 1) or _DUR.match(s, e + 1)):
        return False
    return True


def _ident_spans(s: str, identifiers) -> list[tuple[int, int, str]]:
    spans = []
    for ident in sorted({normalize(x).strip() for x in identifiers or () if str(x).strip()}, key=len, reverse=True):
        if not re.search(r"[^\d\s.,]", ident):
            continue  # 숫자만으로 된 표기는 식별자로 받지 않는다 — 수량과 가를 수 없다('49' 를 면제하면 '49억'·'49개월' 이 같이 빠진다)
        for m in re.finditer(re.escape(ident), s):
            a, b = m.span()
            before = s[a - 1] if a else ""
            after = s[b] if b < len(s) else ""
            if (before.isascii() and before.isalnum()) or (after.isascii() and after.isalnum()):
                continue  # 다른 낱말의 일부
            if any(not (b <= x or a >= y) for x, y, _ in spans):
                continue
            if _qty_tail(s, b):
                continue  # 뒤에 소수점+숫자·%·크기 단위가 이어지면 식별자가 아니라 수량의 일부다(USD100.5 million · USD100 million)
            spans.append((a, b, ident))
    return sorted(spans)


def scan(text, identifiers=()) -> list[Token]:
    """정규화한 글을 왼쪽부터 한 번 훑어 토큰 목록을 만든다. 우선순위: 식별자(목록·사건 번호) → 달력(닫힌 조건) → 기간 → 수량 → 수량 낱말.
    토큰의 위치(start·end)는 정규화한 글 기준이다."""
    s = _squeeze(normalize(text))
    out: list[Token] = []
    idents = {a: (b, name) for a, b, name in _ident_spans(s, identifiers)}
    i, n = 0, len(s)
    while i < n:
        if i in idents:
            b, name = idents[i]
            out.append(Token("ident", name, i, b))
            i = b
            continue
        ch = s[i]
        prev = s[i - 1] if i else ""
        if ch.isascii() and ch.isupper() and not (prev.isascii() and prev.isalnum()):
            m = _CASE_NO.match(s, i)
            if m and not _qty_tail(s, m.end()):
                out.append(Token("ident", m.group(0), i, m.end()))
                i = m.end()
                continue
        num_start = ch.isdigit() and not prev.isdigit() and not (prev and prev in ".,")
        if num_start or (ch.isascii() and ch.isupper() and not (prev.isascii() and prev.isalpha())):
            hit = None
            for rx in _CAL:
                m = rx.match(s, i)
                if m and _cal_ok(s, m.end()):
                    hit = m
                    break
            if hit:
                out.append(Token("cal", hit.group(0).replace(" ", ""), i, hit.end()))
                i = hit.end()
                continue
        if num_start or (ch == "." and s[i + 1:i + 2].isdigit() and not prev.isdigit()):
            d = _DUR.match(s, i)
            if d:
                out.append(Token("dur", _dur_canon(d), i, d.end()))
                i = d.end()
                continue
        # 수량 — 부호·범위 판정 → 본문 → 뒤처리. 어떤 꼴로 시작했든 같은 뒤처리(_finish_qty)를 받는다
        sign, j = "", i
        if ch in _SIGN + "~":
            k = i + 1                                   # 부호 뒤의 숫자 자리: 공백(U+2212 뒤)·통화 기호·그 뒤 공백을 건넌다
            if ch == "−" and s[k:k + 1] == " ":
                k += 1
            if s[k:k + 1] and s[k] in _CUR:
                k += 1
                if s[k:k + 1] == " ":
                    k += 1
            if s[k:k + 1].isdigit() or (s[k:k + 1] == "." and s[k + 1:k + 2].isdigit()):
                # 앞 수량 바로 뒤(사이에 단위 글자 몇 개와 공백 한 칸까지: '$70/bbl–$80' · '12% -3%')이면 범위 연결이다
                # 앞 수량에 이어진 '-'·'–' 는 범위 연결이다: 바로 뒤('3-5') · 공백 한 칸 뒤('$70 –$80' · '12% -3%') · 목록에 있는 측정 단위에
                # 붙어서('$70/bbl–$80' · '70만 배럴-80만 배럴'). 그 밖에는 부호다('전년비-3%' · '100억원 -3%'). U+2212 는 언제나 부호다.
                gap = s[out[-1].end:i] if out and out[-1].kind in ("qty", "dur") else None
                after_tok = gap is not None and (gap in ("", " ") or (prev != " " and _UNIT_GAP.fullmatch(gap) is not None))
                if k > i + 1 and not after_tok and prev not in ("", " ", "(", "[", ":", "=", ",", "·") and ch != "−":
                    i += 1                              # 낱말에 붙은 이음표 뒤의 통화 기호(bbl–$80) — 부호가 아니다
                    continue
                if ch == "~" or (ch in _RANGE and (after_tok or prev.isdigit())):
                    i += 1                              # 범위·이음 — 뒤의 수는 양수로 따로 읽는다
                    continue
                sign, j = ch, k
                d = _DUR.match(s, j)                    # 부호 붙은 기간(−1.5년)
                if d:
                    out.append(Token("dur", "-" + _dur_canon(d) if ch in "-−–" else ch + _dur_canon(d), i, d.end()))
                    i = d.end()
                    continue
        if (s[j:j + 1].isdigit() or (s[j:j + 1] == "." and s[j + 1:j + 2].isdigit())) and not (j == i and prev.isdigit()):
            m = _QTY.match(s, j)
            if m:
                canon, e = _finish_qty(s, j, m, sign)
                out.append(Token("qty", canon, i, e))
                i = e
                continue
        w = _WORD.match(s, i)
        if w and not _is_hangul(prev):
            out.append(Token("word", w.group(0).replace(" ", ""), i, w.end()))
            i = w.end()
            continue
        i += 1
    return _mark_fragments(s, _share_range_unit(s, out))


# 앞 수량과 이음표 사이에 올 수 있는 측정 단위(목록에 있는 것만). 설명하는 말('전년비-3%' · 'YoY-3%')은 단위가 아니라서 그 뒤의 '-' 는 부호다
_UNIT_ASCII = r"(?:/[A-Za-z]+|per barrel|barrels?|bbl|b/d|bpd|tonnes?|tons?|kg|km|dollars?|usd)"
_UNIT_GAP = re.compile(r" ?(?:(?:" + _UNITS + r")|" + _UNIT_ASCII + r")", re.IGNORECASE)
_PLAIN_NUM = re.compile(r"[+-]?\d+(?:\.\d+)?")
_NUM_UNIT = re.compile(r"[+-]?\d+(?:\.\d+)?(?P<unit>(?:[" + _MAGC + r"]+|thousand|million|billion|trillion)?(?:%p|%)?)")
_DUR_UNIT = re.compile(r"\d+(?:\.\d+)?(?P<unit>개월|년|일|주|시간)")
# 범위 연결: 붙여 쓴 '-'·'–'·'~' 와 공백을 둔 '–'·'~'. 공백으로 둘러싼 '-' 는 줄표라 범위로 보지 않는다
_RANGE_GAP = re.compile(r"(?:[-–~]| ?[–~] ?)(?:[" + re.escape(_CUR) + r"] ?)?")


def _share_range_unit(s: str, toks: list[Token]) -> list[Token]:
    """범위의 앞 수가 단위 없이 적혀 있으면 뒤 수의 단위를 같이 쓴다: '3~5%' 의 3 은 3% · '70~80만' 의 70 은 70만 · '$3–4 billion' 의 3 은
    3 billion · '3~5년' 의 3 은 3년. 이렇게 하지 않으면 앞 수가 단위 없는 숫자로 남아, 단위를 뗀 화면 글('3 배럴')의 근거가 된다.
    뒤 수가 단순한 '수+단위' 꼴이 아니어서 단위를 나눠 줄 수 없으면(70~80만5천) 앞 수는 조각으로 둔다."""
    out = list(toks)
    for n in range(len(out) - 1):
        a, b = out[n], out[n + 1]
        if a.kind != "qty" or not _PLAIN_NUM.fullmatch(a.canon) or not _RANGE_GAP.fullmatch(s[a.end:b.start]):
            continue
        if b.kind == "dur":
            m = _DUR_UNIT.fullmatch(b.canon)
            if m:
                out[n] = Token("dur", a.canon + m.group("unit"), a.start, a.end)
            continue
        if b.kind != "qty" or _PLAIN_NUM.fullmatch(b.canon):
            continue                                    # 둘 다 단위 없는 수(1~3) · 뒤가 달력·식별자 — 그대로 둔다
        m = _NUM_UNIT.fullmatch(b.canon)
        gap = s[a.end:b.start]
        if m and m.group("unit") in ("%", "%p") and re.search(r"[" + re.escape(_CUR) + r"] ?$", s[max(0, a.start - 2):a.start]) \
                and not any(c in gap for c in _CUR):
            continue                                    # '$100 – 20% 할인' — 금액과 비율은 범위가 아니다. 앞 수는 그대로 둔다
        if m and m.group("unit"):
            out[n] = Token("qty", a.canon + m.group("unit"), a.start, a.end)
        else:
            out[n] = Token("qty", "?" + s[a.start:a.end], a.start, a.end, True)
    return out


def _finish_qty(s: str, j: int, m: re.Match, sign: str) -> tuple[str, int]:
    """_QTY 가 읽은 본문의 뒤처리(한 곳). 돌려주는 것: (정규형, 끝 위치).
      · 숫자로 끝났는데 [./]+숫자가 이어지면 판독하지 못한 이음 — 통째로 raw(뒤의 크기 단위·% 포함)
      · 크기 단위로 끝났고 공백 뒤에 크기 단위 없는 마지막 자리가 오면 한 수량(1억 2,345 · 뒤가 달력·기간이면 다른 말)
      · 숫자·크기 단위 바로 뒤에 영문자가 붙으면 글자까지 한 토큰(52C · 3.5B · 701k · 1.2.3B). %·영문 크기 단위로 닫힌 뒤의 영문자는 다른 낱말(3%YoY)"""
    sg = "-" if sign and sign in "-−–" else sign
    e = m.end()
    if s[e - 1].isdigit() and _RAW_TAIL.match(s, e):
        r = re.match(r"[\d.,/]+", s[j:])
        e = j + len(r.group(0).rstrip(".,/"))                # 문장 끝의 마침표·쉼표는 표기가 아니다
        body = s[j:e]
        suf = _RAW_SUFFIX.match(s, e)                          # 뒤의 크기 단위·% 는 같은 표기의 일부다(1/2/3% ≠ 1/2/3)
        tail = re.sub(r"\s", "", suf.group(0)).lower()
        e = suf.end()
        if (not tail or tail[-1] in _MAGC) and s[e:e + 1].isascii() and s[e:e + 1].isalpha():
            w = re.match(r"[A-Za-z]+", s[e:])
            tail, e = tail + w.group(0), e + w.end()
            tail, e = _exponent(s, tail, e)
        return "raw:" + sg + body + tail, e
    canon = _qty_canon(sign, m)
    if s[e - 1] in _MAGC:
        g = _LASTGRP.match(s, e)
        if g and not _starts_cal(s, e + 1) and not _DUR.match(s, e + 1):
            canon, e = canon + g.group(1).replace(",", ""), g.end()
            suf = _TAIL_UNIT.match(s, e)                       # 마지막 자리 뒤의 영문 크기 단위·% 도 같은 수량이다
            sc = (suf.group("scale") or "").strip().lower()
            canon, e = canon + _UNIT_NORM.get(sc, sc) + _pct_norm(suf.group("pct")), suf.end()
    if (s[e - 1].isdigit() or s[e - 1] in _MAGC) and s[e:e + 1].isascii() and s[e:e + 1].isalpha():
        w = re.match(r"[A-Za-z]+", s[e:])
        e += w.end()
        tail, e = _exponent(s, w.group(0), e)
        canon = "raw:" + sg + re.sub(r"[\s,]", "", s[j:e])
    return canon, e


def _exponent(s: str, tail: str, e: int) -> tuple[str, int]:
    """지수 표기(1.2e-3%)는 지수와 뒤의 크기 단위·% 까지 한 표기다 — 'e' 뒤의 '-3%' 가 따로 음수로 읽히지 않게."""
    if tail[-1:] in ("e", "E"):
        x = re.match(r"[+\-−]?\d+", s[e:])
        if x:
            e += x.end()
            suf = _RAW_SUFFIX.match(s, e)
            return tail + x.group(0).replace("−", "-") + re.sub(r"\s", "", suf.group(0)).lower(), suf.end()
    return tail, e


def _mark_fragments(s: str, toks: list[Token]) -> list[Token]:
    """수량·기간 토큰의 앞뒤에 같은 수의 나머지로 보이는 글자가 남아 있으면, 판독부가 그 표기를 통째로 읽지 못한 것이다.
    그런 토큰이 근거로 쓰이거나(기록 쪽) 근거를 얻는(화면 쪽) 일이 없게 하는 마지막 그물이다.
      앞: 숫자 · 숫자 뒤의 [.,/] · '분의' · 바로 앞 수량 토큰이 크기 단위로 끝남(공백 한 칸 포함)
      뒤: 숫자 · [.,/]+숫자 · '분의' · 토큰에 안 든 %·영문 크기 단위 · 크기 단위로 끝났는데 공백 뒤에 숫자(달력·기간이 아닌)
      %·영문 크기 단위·기간 단위로 닫힌 토큰 뒤의 구분자와 숫자는 다음 수량의 시작으로 본다(10%,20% · 3일/4일 · 6년9개월).
    서로 이어진 토큰들은 하나로 묶어 raw 토큰(공백만 지운 원래 표기)으로 만든다 — 기록에 같은 표기가 통째로 있어야 맞는다.
    묶을 짝이 없거나 묶음 바깥에도 이음이 남으면 조각(fragment)이다. 조각은 어느 쪽에서도 맞는 것으로 치지 않는다."""
    def ch(k: int) -> str:
        return s[k] if 0 <= k < len(s) else ""

    def before_bad(t: Token) -> bool:
        if ch(t.start - 1).isdigit() or (ch(t.start - 1) in (".", ",", "/") and ch(t.start - 2).isdigit()):
            return True
        if re.search(r"분의 ?$", s[max(0, t.start - 4):t.start]):             # 읽지 못한 '…분의 N' 의 N
            return True
        # 읽지 못한 부호: U+2212 가 공백·통화 기호 몇 글자 건너 앞에 남아 있는데 토큰이 음수가 아니다
        return t.kind == "qty" and not t.canon.lstrip("raw:").startswith("-") \
            and bool(re.search(r"−[ " + re.escape(_CUR) + r"]{0,3}$", s[max(0, t.start - 4):t.start]))

    def closed(t: Token) -> bool:  # %·영문 크기 단위·기간 단위로 끝난 토큰 — 뒤의 구분자·숫자는 다음 수량의 시작이다(10%,20% · 3일/4일 · 6년9개월)
        return t.kind == "dur" or t.canon.endswith(("%", "%p")) or bool(re.search(_SCALE + r"$", t.canon, re.IGNORECASE))

    def after_bad(t: Token) -> bool:
        b = t.end
        rest = s[b:]
        if re.match(r" ?분의", rest):                                           # 읽지 못한 'N…분의'
            return True
        if closed(t):
            return False
        if ch(b - 1).isdigit() and re.match(r" [" + _MAGC + r"]+[가-힣]| ?" + _MAG_WORD, rest):
            return True     # 읽지 못한 한글 크기 단위, 또는 크기 단위인지 낱말인지 가를 수 없는 꼴('3 만원' · '3 조명') — 추측하지 않는다
        if ch(b).isdigit():
            return True                                                         # 바로 붙은 숫자는 언제나 같은 수의 나머지다
        if ch(b - 1) in _MAGC:
            return False                                                        # 크기 단위 뒤의 [.,/]+숫자는 다음 수량이다(70만,80만)
        if ch(b) in (".", ",", "/") and ch(b + 1).isdigit():
            return True
        if t.kind != "qty":
            return False
        if re.match(r" ?" + _PCT, rest, re.IGNORECASE):
            return True
        return bool(re.match(r" ?" + _SCALE, rest, re.IGNORECASE))

    def joins_next(t: Token) -> bool:  # '1억' + ' 2,345.5' — 크기 단위로 끝났는데 공백 뒤에 달력·기간이 아닌 숫자
        b = t.end
        return t.kind == "qty" and ch(b - 1) in _MAGC and ch(b) == " " and ch(b + 1).isdigit() \
            and not _starts_cal(s, b + 1) and not _DUR.match(s, b + 1)

    num = [t.kind in ("qty", "dur") for t in toks]
    out: list[Token] = []
    n = 0
    while n < len(toks):
        t = toks[n]
        if not num[n] or t.fragment:
            out.append(t)
            n += 1
            continue
        m = n  # 이어진 토큰을 끝까지 묶는다(사이가 없거나 공백·[.,/] 한 글자이고, 한쪽이라도 이음을 보일 때)
        while m + 1 < len(toks) and num[m + 1]:
            gap = s[toks[m].end:toks[m + 1].start]
            if (gap in ("", " ", ".", ",", "/") or re.fullmatch(r" ?분의 ?", gap)) \
                    and (after_bad(toks[m]) or joins_next(toks[m]) or before_bad(toks[m + 1])):
                m += 1
            else:
                break
        first, last = toks[n], toks[m]
        outer = before_bad(first) or after_bad(last) or joins_next(last)
        if m == n:
            out.append(Token(t.kind, "?" + s[t.start:t.end], t.start, t.end, True) if outer else t)
        else:
            surface = re.sub(r"\s", "", s[first.start:last.end])
            out.append(Token("qty", ("?" if outer else "raw:") + surface, first.start, last.end, outer))
        n = m + 1
    return out


def claim_tokens(text, identifiers=()) -> list[Token]:
    return [t for t in scan(text, identifiers) if t.needs_claim]


def pool(*texts) -> set[str]:
    """원문(observed·text)에서 대조에 쓸 수 있는 정규형 — 수량·기간·수량 낱말."""
    out: set[str] = set()
    for t in texts:
        out |= {x.canon for x in claim_tokens(t) if not x.fragment}
    return out


def _seq(tokens) -> list[Token]:
    return [t for t in tokens if t.kind in ("qty", "dur", "word", "cal")]


def _same(a: Token, b: Token) -> bool:
    if a.fragment or b.fragment:
        return False  # 조각은 어느 쪽에서도 맞는 것으로 치지 않는다
    if a.canon == b.canon and a.kind == b.kind:
        return True
    # '2007'(수량) ← 원문 '2007년'(달력): 꾸밈 없는 숫자가 연도의 숫자와 같으면 같은 토큰으로 본다
    return a.kind == "qty" and a.canon.isdigit() and b.kind == "cal" and re.match(r"\d+", b.canon) is not None \
        and re.match(r"\d+", b.canon).group(0) == a.canon and len(b.canon) - len(a.canon) <= 1


def complete_in(sub: str, hay: str, need_digits: bool, identifiers=()) -> list[Token] | None:
    """sub 를 훑은 토큰열이 hay 를 훑은 토큰열 안에 그대로(완전한 토큰 단위로) 있으면 sub 의 토큰을, 아니면 None.
    토큰 단위로 비교하므로 복합 수량의 조각('5백' ← '70만 1천 5백'), 부호를 뗀 값, 단위를 자른 값은 맞지 않는다.
    need_digits: 숫자가 든 토큰(수량·기간·달력)이 하나 이상 있어야 한다(환산 원문 — 숫자 없는 말로 임의 수치를 승인하지 않는다)."""
    own = _seq(scan(sub, identifiers))
    if not own:
        return None
    if need_digits and not any(t.kind in ("qty", "dur", "cal") for t in own):
        return None
    if not need_digits and not any(t.needs_claim for t in own):
        return None
    hs = _seq(scan(hay, identifiers))
    k = len(own)
    for i in range(len(hs) - k + 1):
        if all(_same(own[x], hs[i + x]) for x in range(k)):
            return own
    return None


def exempt_identifiers(text, identifiers=()) -> list[str]:
    return [t.canon for t in scan(text, identifiers) if t.kind == "ident"]
