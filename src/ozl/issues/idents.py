"""이슈 쪽에서 글을 훑기 전에 수량에서 빼는 것 — 달력·시각 꼴('10.29.(목)', '04시 15분')과 작성자가 적은 식별자(identifiers).

render.numbers 는 고치지 않는다. numbers 가 이 이름들을 다시 내보낸다(numbers.identifiers 처럼 부른다).
"""
from __future__ import annotations

import re

from ozl.render import numbers as N

from . import model


def _unit(word: str) -> bool:
    from .numbers import _kw_unit               # 키워드의 세는 단위 목록을 같이 쓴다(가져오기 순환을 피해 부를 때 읽는다)
    return _kw_unit(word)


# ── 달력과 시각 — 이슈 쪽에서 글을 훑기 전에 수량에서 뺀다(render.numbers 는 고치지 않는다) ──
# 'M.D.(요일)' 꼴(10.29.(목))과 'H시 M분' 꼴(04시 15분 — '시' 뒤가 '간'이면 기간이라 뺀다).
DATE_DOT = re.compile(r"(?<![\d.])(1[0-2]|0?[1-9])\.\s?([12]\d|3[01]|0?[1-9])\.\s?\([월화수목금토일]\)")
CLOCK = re.compile(r"(?<![\d.])(?:[01]?\d|2[0-3])시(?!간)\s?[0-5]?\d분")
# 'M월 D일부터 D일까지'·'M월 D일~D일' 꼴(같은 달의 날짜 범위). 뒤 날짜가 앞 날짜보다 커야 하고, '~D일' 뒤가 '간'이면(기간) 빼지 않는다.
# render.numbers 는 'M월 D일부터 M월 D일까지' 는 달력으로 읽지만 달을 줄인 뒤쪽 날짜와 그 앞의 'M월 D일'은 수량으로 읽는다.
_DAY = r"([12]\d|3[01]|0?[1-9])"
DATE_RANGE = re.compile(r"(?<![\d.])(1[0-2]|0?[1-9])월\s?" + _DAY + r"일(?:부터\s?" + _DAY + r"일(?=까지)|\s?[~∼–-]\s?" + _DAY + r"일(?![간\d]))")


def mask_calendar(text: str) -> str:
    """달력·시각·같은 달 날짜 범위 꼴의 숫자를 '#' 로 바꾼 글(길이와 자리는 그대로) — 수량 토큰으로 읽히지 않게."""
    text = str(text or "")
    for rx in (DATE_DOT, CLOCK):
        text = rx.sub(lambda m: re.sub(r"\d", "#", m.group(0)), text)

    def _range(m):
        first, last = int(m.group(2)), int(m.group(3) or m.group(4))
        return re.sub(r"\d", "#", m.group(0)) if last > first else m.group(0)
    return DATE_RANGE.sub(_range, text)


# ── 식별자(identifiers) — 이름 속 숫자(KTX-1, 제2형, COVID-19, B-52, G7)를 수량으로 보지 않게 작성자가 적는 목록 ──
# 덱 사양의 identifiers 와 같은 뜻이다(render.numbers 머리말의 ident). 글자(영문자나 한글)가 하나 이상 있어야 하고,
# '수 + 단위' 꼴(12개, 3주, 4시간, 6대, 40만 원대, 49)은 받지 않는다 — 면제하면 수량이 검사 없이 실린다.
MSG_IDENT = "identifiers 는 이름 속 숫자 표기(KTX-1, 제2형, COVID-19)의 목록이다"


def identifier_error(s) -> str:
    """식별자 하나의 오류(빈 글이면 맞다)."""
    if not isinstance(s, str) or not s.strip():
        return f"{MSG_IDENT} — 빈 값이나 문자열이 아닌 값은 받지 않는다"
    if not re.search(r"[A-Za-z가-힣]", s):
        return f"'{s}'에는 글자(영문자나 한글)가 없다 — 숫자만으로 된 표기는 식별자가 아니다"
    if not re.search(r"\d", s):
        return f"'{s}'에는 숫자가 없다 — 면제할 것이 없다"
    for m in re.finditer(r"\d[\d.,]*", s):
        after = s[m.end():]
        run = re.match(r"[가-힣]+", after)
        word = run.group(0) if run else (re.match(r"\s+([가-힣A-Za-z%]+)", after) or [None, ""])[1]
        if after[:1] == "%" or re.match(r"[십백천만억조경]", word or "") or _unit(word or ""):
            return f"'{s}'은 '수 + 단위' 꼴이다 — 수량은 식별자로 면제하지 않는다"
    if re.fullmatch(r"\s*[\d.,]+\s*", s):
        return f"'{s}'은 숫자만이다"
    return ""


def identifiers(issue: dict) -> list[str]:
    """이슈의 identifiers 가운데 받을 수 있는 표기만(틀린 표기는 check 가 오류로 낸다)."""
    ids_ = issue.get("identifiers") if isinstance(issue, dict) else None
    return [x for x in ids_ if not identifier_error(x)] if isinstance(ids_, list) else []


def exempt_counts(issue: dict) -> dict[str, int]:
    """독자에게 보이는 글과 키워드에서 식별자로 면제한 표기와 그 수 {표기: 곳 수}(check·status 가 알림으로 찍는다)."""
    idents = identifiers(issue)
    out: dict[str, int] = {}
    if not idents:
        return out
    texts = [t for _p, t, _n, _i in model.reader_items(issue)] + [k for k in issue.get("keywords") or [] if isinstance(k, str)]
    for t in texts:
        for name in N.exempt_identifiers(mask_calendar(t), idents):
            out[name] = out.get(name, 0) + 1
    order = {N.normalize(x).strip(): i for i, x in enumerate(idents)}   # identifiers 에 적은 차례대로
    return dict(sorted(out.items(), key=lambda kv: order.get(kv[0], len(order))))


def exempt_note(issue: dict) -> str:
    c = exempt_counts(issue)
    return ("수량으로 보지 않은 표기: " + ", ".join(f"{k}({v}곳)" for k, v in c.items())) if c else ""


def identifier_list_errors(issue: dict) -> list[tuple[str, str]]:
    """identifiers 칸의 모양과 표기마다의 오류 [(칸 경로, 문구)]."""
    idl = issue.get("identifiers")
    if idl is None:
        return []
    if not isinstance(idl, list):
        return [("identifiers", MSG_IDENT + " — 목록으로 적는다")]
    return [(f"identifiers.{i}", identifier_error(x)) for i, x in enumerate(idl) if identifier_error(x)]
