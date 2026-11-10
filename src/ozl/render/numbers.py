#!/usr/bin/env python3
"""덱 사양의 숫자 판독부 — 원칙 하나: **확신이 없으면 수량으로 보고 근거를 요구한다.**

판독 앞에 입력을 정규화한다(모든 공백 문자 — 탭·개행·연속 공백·줄바꿈 없는 공백 — 을 공백 한 칸으로).
그다음 왼쪽부터 한 번 훑어 토큰 종류를 가르고, 직접 대조와 환산 경계 검사가 같은 결과를 쓴다.

토큰 종류
  qty   수량(가장 길게 하나로): 부호 · 숫자(쉼표·소수) · 분수(1/2 · 1/2.5 · 2분의 1) · 한글 크기 단위의 연속과 마지막 일의 자리
        (70만 1천 5백 · 3천 3백만 · 2천3백4십5) · 영문 크기 단위(million·billion… — 뒤에 한글이 붙어도) · %·%p.
        대조는 공백·쉼표를 지운 정규형으로 한다(3천 3백만 = 3천3백만). 판독하지 못한 숫자 이음(1.2.3 · 1/2/3)은 조각 내지 않고
        통째로 하나의 토큰(raw:…)으로 두어 기록에 같은 표기가 있어야 통과한다.
        숫자 뒤의 측정 단위 낱말(배럴·달러·kg·명)은 토큰에 넣지 않는다. 숫자 앞에 영문자가 붙어 있어도 수량이다(USD100 million · GDP3%).
  dur   기간: N년간 · N년 만 · N년 동안 · N개월 · N일 · N주 · N시간, 그리고 달력 꼴이 닫힌 조건을 못 갖춘 'YYYY년'(2000년 6개월 동안).
  word  숫자 없는 수량 낱말(작은 목록: 반년 · 절반 · 갑절 · 두 배 · 세 번 · 열 달 …). 조사가 붙어도 잡는다.
  cal   달력 — 아래 꼴 전체가 맞고, 뒤가 닫힌 조건일 때만:
        꼴: YYYY-MM-DD · YYYY.MM.DD · YYYY-MM · YYYY년 · M월 D일 · M월 · YYYY~YYYY(년) · M~M월 · N분기 · June 26, 2007 · June 2007
            (YYYY 는 1000~2999 네 자리)
        뒤: 문장 끝 · 문장부호 · 정해 둔 조사(_PARTICLES)·꼬리말(판·호·말·초·중·께·쯤) · 공백 뒤 일반 낱말 · 공백 뒤 수량이나 다음 달력 꼴.
            공백을 건너 수량·기간·측정 단위 낱말(_BLOCK_WORDS · _BLOCK_ASCII: million · kg · 배럴 · 동안 · 만 · 년 …)이 오거나,
            공백 뒤 기간(6개월)이 오거나, 붙어서 목록 밖 한글·영문자·숫자·%·소수점+숫자가 오면 달력이 아니다.
  ident 식별자 — 자동으로 추측하지 않는다. 사건 번호 꼴(ARB/07/27)과, 사양 맨 위 `identifiers` 목록에 작성자가 적은 표기만.
        둘 다 일치한 구간 바로 뒤에 소수점+숫자 · % · 퍼센트 · 영문 크기 단위 · 한글 크기 단위(뒤에 한글이 없거나 원·달러 같은 단위가 붙을 때)가
        오면 면제하지 않는다(USD100.5 million · ARB/07/27%). '49B만으로'·'49B 조사' 의 '만'·'조' 는 조사·낱말이라 식별자로 둔다.
수치 주장으로 대조하는 것은 qty · dur · word 다. cal · ident 는 대조하지 않는다(check 가 면제한 식별자를 출력한다).

부호와 범위
  '-'·'–'·'~' 는 수량·기간 토큰 바로 뒤(공백 한 칸까지)이거나 숫자에 바로 붙어 있으면 범위 연결이다. 그 밖의 '-'·'–'·'+' 는 부호다.
  U+2212(−)는 언제나 부호다(12% −3% 의 −3%).

못 잡는 것(느슨하게 통과시키지 않고 여기에 적는다)
  - 측정 단위 낱말은 비교하지 않는다: '1,234톤' 과 원문 '1,234 t', '70만 배럴' 과 원문 '70만 달러' 를 같은 숫자로 본다.
  - 숫자 없이 수량을 말하는 낱말은 목록에 있는 것만 잡는다('몇 배'·'수년'·'대부분' 같은 막연한 말은 못 잡는다).
    목록 낱말이 서수로 쓰여도('세 번째') 수량으로 잡는다(근거를 요구하는 쪽으로 틀린다).
  - 기록(observed·text)에 같은 표기가 있으면 통과한다. 기록 안의 숫자가 식별자(허가 번호 52C 의 52)여도 같은 숫자로 본다.
  - 세 자리 이하 연도('918년')는 달력으로 보지 않는다(수량으로 보고 근거를 요구한다).
  - 달력 뒤 '공백 + 일반 낱말' 은 달력으로 둔다. 차단 낱말 목록(_BLOCK_WORDS·_BLOCK_ASCII) 밖의 단위 낱말이 공백 뒤에 오면
    ('2025 그램'처럼 목록에 없는 단위) 달력으로 면제된다. 붙여 쓴 목록 밖 한글은 수량으로 본다(근거를 요구하는 쪽).
  - 부록 출처 표의 문서 위치 칸(primary_doc_locator — 쪽·조·문단·표 번호)의 숫자는 검사하지 않는다(구조 칸 · build.APPX_STRUCTURAL).
    기관 이름과 교차 출처 기관 이름은 대조한다(build.APPX_CHECKED).
  - 정해 둔 조사 목록 밖의 어미가 달력에 붙으면('3월 18일이니') 수량으로 보고 근거를 요구한다(오실패 쪽으로 틀린다).

알려진 결함(2026-11-10 여섯 번째 검토에서 재현했고 아직 고치지 않았다. 이 검사만으로 덱의 숫자를 믿지 않는다 —
사양을 쓴 쪽과 다른 눈의 문장 대조, 사람의 원문 대조가 따로 있다)
  근거 없이 통과하는 것
  - 연도 범위 꼴 뒤에 '영문 단위 + 한글 조사'가 오면 달력으로 면제한다('2004~2025 kg으로').
  - 기록의 복합 수량에서 공백 뒤 마지막 숫자에 크기 단위가 없으면 둘로 나뉘어, 앞부분만 쓴 화면 글이 통과한다
    (기록 '1억 2,345원', 화면 '1억').
  - 분모에 쉼표가 있으면 잘린다(기록 '1/2,000', 화면 '1/2').
  - 선언한 식별자 뒤에 쉼표로 이어진 숫자가 오면 뒷부분만 수량으로 읽는다('USD100,500 million').
  - raw 토큰은 뒤의 %·크기 단위를 버린다('1/2/3' 과 '1/2/3%' 를 같게 본다). 위의 "통째로" 는 숫자 이음까지만 맞다.
  맞는 표기를 막는 것
  - 같은 수량을 한쪽은 붙여 쓰고 한쪽은 띄어 쓰면 어긋난다(기록 '1억2345원', 화면 '1억 2,345원').
  - 달력 꼬리말 뒤에 조사가 이어지면 수량으로 본다('3월말까지' · '2026년판은').
  - 선언한 식별자 뒤의 보조사 '만' 다음에 낱말이 이어지면 크기 단위로 읽는다('49B만 남았다').
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

    @property
    def needs_claim(self) -> bool:
        return self.kind in CLAIM_KINDS


_MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_Y = r"[12]\d{3}"
_M = r"(?:1[0-2]|0?[1-9])"
_D = r"(?:3[01]|[12]\d|0?[1-9])"
_MAGC = "십백천만억조경"
_SCALE = r"(?:thousand|million|billion|trillion|bn|mn)(?![A-Za-z])"
_PCT = r"(?:%p|%포인트|퍼센트포인트|%|퍼센트)"
_NUM = r"(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)"

_CAL = [
    re.compile(_MONTHS + r" \d{1,2}, ?" + _Y),
    re.compile(_MONTHS + r" " + _Y),
    re.compile(_Y + r"([-.])" + _M + r"\1" + _D),          # YYYY-MM-DD · YYYY.MM.DD
    re.compile(_Y + r"-" + _M + r"(?![\d.])"),               # YYYY-MM
    re.compile(_Y + r" ?[-–~] ?" + _Y + r"(?:년)?"),         # YYYY~YYYY(년)
    re.compile(_Y + r"년"),
    re.compile(_M + r"월 ?" + _D + r"일"),
    re.compile(_M + r" ?[~–-] ?" + _M + r"월"),
    re.compile(_M + r"월"),
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
                "barrel", "barrels", "usd", "dollar", "dollars", "%")
_PUNCT_STOP = r"\s.,;:!?()\[\]「」『』\"'“”‘’·/~→—–−-"
_CASE_NO = re.compile(r"[A-Z]{2,}/\d+(?:/\d+)+")
_DUR = re.compile(r"(\d+(?:,\d{3})*) ?(개월|년|일|주|시간)")
_MAGSEG = r"(?:[" + _MAGC + r"]\d*(?:,\d{3})*)+"           # 천3백4십5 — 마지막 일의 자리까지
_QTY = re.compile(
    r"(?P<num>" + _NUM + r")"
    r"(?:(?P<frac>/\d+(?:\.\d+)?)| ?분의 ?(?P<kofrac>\d+(?:\.\d+)?))?"
    r"(?P<mag>" + _MAGSEG + r"(?: \d+(?:,\d{3})*" + _MAGSEG + r")*)?"
    r"(?P<scale> ?" + _SCALE + r")?"
    r"(?P<pct> ?" + _PCT + r")?", re.IGNORECASE)
_RAW_TAIL = re.compile(r"[./]\d")                            # 판독하지 못한 숫자 이음(1.2.3 · 1/2/3) — 조각 내지 않고 통째로
_QTY_TAIL = re.compile(r"\.\d| ?%| ?퍼센트| ?" + _SCALE + r"| ?[" + _MAGC + r"](?:(?![가-힣])|(?=원|달러|배럴|명|개|톤|건|대))", re.IGNORECASE)
_WORDS = ["반 토막", "반토막", "반년", "반세기", "절반", "반값", "갑절", "두 배", "세 배", "네 배", "다섯 배", "열 배",
          "두 번", "세 번", "네 번", "다섯 번", "두 달", "석 달", "열 달"]
_WORD = re.compile("|".join(re.escape(w) for w in sorted(_WORDS, key=len, reverse=True)))
_RANGE = "-–~"        # 수량·기간 바로 뒤(또는 숫자에 붙어)이면 범위 연결
_SIGN = "-–−+"        # 그 밖에는 부호. U+2212(−)는 언제나 부호다
_UNIT_NORM = {"%포인트": "%p", "퍼센트포인트": "%p", "퍼센트": "%", "bn": "billion", "mn": "million"}


def normalize(text) -> str:
    """판독 앞의 입력 정규화: 모든 공백 문자(탭·개행·연속 공백·줄바꿈 없는 공백)를 공백 한 칸으로 접는다."""
    return re.sub(r"\s+", " ", "" if text is None else str(text))


def _qty_canon(sign: str, m: re.Match) -> str:
    num = m.group("num").replace(",", "")
    if num.startswith("."):
        num = "0" + num
    if m.group("kofrac"):
        body = f"{m.group('kofrac')}/{num}"  # 2분의 1 → 1/2
    else:
        body = num + (m.group("frac") or "")
    mag = re.sub(r"[\s,]", "", m.group("mag") or "")
    scale = (m.group("scale") or "").strip().lower()
    pct = (m.group("pct") or "").strip()
    pct = _UNIT_NORM.get(pct, pct)
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
        return False
    if c == " ":
        m = re.match(r" ([^" + _PUNCT_STOP + r"]+)", rest)
        if not m:
            return True
        word = m.group(1)
        if word[0].isdigit():
            # 다음이 기간이면 복합 기간(2000년 6개월 동안)이라 달력이 아니다. 다음이 수량·달력이면 달력(2001년 147만 배럴 · 2026년 1분기)
            return not (_DUR.match(s, e + 1) and not _starts_cal(s, e + 1))
        lw = word.lower()
        if word.isascii():
            return not any(lw == x or lw.startswith(x) and not lw[len(x):len(x) + 1].isalpha() for x in _BLOCK_ASCII)
        base = word
        for p in sorted(_PARTICLES, key=len, reverse=True):  # 조사만 떼고 본다(꼬리말 '판'을 떼면 '원판'이 '원'이 된다)
            if base.endswith(p) and len(base) > len(p):
                base = base[:-len(p)]
                break
        return word not in _BLOCK_WORDS and base not in _BLOCK_WORDS
    return True


def _ident_spans(s: str, identifiers) -> list[tuple[int, int, str]]:
    spans = []
    for ident in sorted({normalize(x).strip() for x in identifiers or () if str(x).strip()}, key=len, reverse=True):
        for m in re.finditer(re.escape(ident), s):
            a, b = m.span()
            before = s[a - 1] if a else ""
            after = s[b] if b < len(s) else ""
            if (before.isascii() and before.isalnum()) or (after.isascii() and after.isalnum()):
                continue  # 다른 낱말의 일부
            if any(not (b <= x or a >= y) for x, y, _ in spans):
                continue
            if _QTY_TAIL.match(s, b):
                continue  # 뒤에 소수점+숫자·%·크기 단위가 이어지면 식별자가 아니라 수량의 일부다(USD100.5 million · USD100 million)
            spans.append((a, b, ident))
    return sorted(spans)


def scan(text, identifiers=()) -> list[Token]:
    """정규화한 글을 왼쪽부터 한 번 훑어 토큰 목록을 만든다. 우선순위: 식별자(목록·사건 번호) → 달력(닫힌 조건) → 기간 → 수량 → 수량 낱말.
    토큰의 위치(start·end)는 정규화한 글 기준이다."""
    s = normalize(text)
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
            if m and not _QTY_TAIL.match(s, m.end()):
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
        if num_start:
            d = _DUR.match(s, i)
            if d:
                out.append(Token("dur", d.group(1).replace(",", "") + d.group(2), i, d.end()))
                i = d.end()
                continue
        # 수량(부호·범위 판정)
        sign, j = "", i
        if ch in _SIGN + "~" and i + 1 < n and (s[i + 1].isdigit() or (s[i + 1] == "." and s[i + 2:i + 3].isdigit())):
            k = i - 1 if prev != " " else i - 2
            after_tok = bool(out) and out[-1].kind in ("qty", "dur") and out[-1].end == k + 1
            if ch in _RANGE and (after_tok or prev.isdigit()):
                i += 1  # 범위 연결
                continue
            if ch == "~":
                i += 1
                continue
            sign, j = ch, i + 1
        if (s[j:j + 1].isdigit() or (s[j:j + 1] == "." and s[j + 1:j + 2].isdigit())) and not (j == i and prev.isdigit()):
            m = _QTY.match(s, j)
            if m:
                e = m.end()
                if _RAW_TAIL.match(s, e):  # 판독하지 못한 이음 — 통째로 하나의 토큰(기록에 같은 표기가 있어야 통과)
                    r = re.match(r"[\d.,/]+", s[j:])
                    e = j + r.end()
                    out.append(Token("qty", "raw:" + sign + s[j:e], i, e))
                else:
                    out.append(Token("qty", _qty_canon(sign, m), i, e))
                i = e
                continue
        w = _WORD.match(s, i)
        if w and not _is_hangul(prev):
            out.append(Token("word", w.group(0).replace(" ", ""), i, w.end()))
            i = w.end()
            continue
        i += 1
    return out


def claim_tokens(text, identifiers=()) -> list[Token]:
    return [t for t in scan(text, identifiers) if t.needs_claim]


def pool(*texts) -> set[str]:
    """원문(observed·text)에서 대조에 쓸 수 있는 정규형 — 수량·기간·수량 낱말."""
    out: set[str] = set()
    for t in texts:
        out |= {x.canon for x in claim_tokens(t)}
    return out


def _seq(tokens) -> list[Token]:
    return [t for t in tokens if t.kind in ("qty", "dur", "word", "cal")]


def _same(a: Token, b: Token) -> bool:
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
