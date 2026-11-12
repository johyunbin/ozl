"""find_phrase 무작위 시험의 생성기 — 만든 방법이 곧 정답이다(find_phrase·numbers.py 에 기대지 않는다).

수량 = [부호][정수(쉼표 유무)][.소수][크기 단위·%·%p] 가 핵심(core), 그 뒤에 측정 단위 낱말(원·명·톤·달러)이 붙을 수 있다.
측정 단위 낱말은 수량에 넣지 않는다(numbers.py 와 같은 정의) — 그래서 core 만 쓴 문구도 '온전한 수량'이다.
복합 수량(1억2만원 · 1억 2천만원)과 범위(3~5 · 3%~5% · 3억~5억원)는 전체(와 측정 단위를 뗀 전체)만 온전하다.
기대값: 온전한 표기(위)가 글에 그 표기로 있으면 찾는다. 그 밖에 숫자를 담은 진부분 문자열·범위의 한쪽·복합의 일부·
탭·줄바꿈을 건너 두 수량을 이은 문구는 찾지 않는다.
모호한 꼴은 만들지 않는다(ambiguous_space): 같은 줄에서 공백 한 칸으로 이은 '숫자 공백 숫자'·'크기 단위 공백 숫자'·'공백 -수'."""
from __future__ import annotations

import random

SIGNS = ["", "", "", "-", "−", "△", "▲", "▼", "+"]
TAILS = ["", "", "%", "%p", "만", "억", "조"]
MEASURES = ["", "", "원", "명", "톤", "달러"]
SEPS = [" ", ", ", " 그리고 ", "\t", "\n", "는 ", "이고 "]


def _int(r: random.Random) -> str:
    n = r.choice([r.randint(1, 9), r.randint(10, 999), r.randint(1000, 9_999_999)])
    s = str(n)
    if n >= 1000 and r.random() < 0.6:
        s = f"{n:,}"
    return s


def _num(r: random.Random) -> str:
    s = _int(r)
    if r.random() < 0.35:
        s += "." + str(r.randint(1, 99))
    return s


def quantity(r: random.Random) -> dict:
    """{text, whole: [온전한 표기들], kind}."""
    k = r.random()
    if k < 0.55:
        sign, num, tail = r.choice(SIGNS), _num(r), r.choice(TAILS)
        meas = r.choice(MEASURES) if tail not in ("%", "%p") else ""
        core = sign + num + tail
        if not sign and not tail and not meas and r.random() < 0.15:
            core = f"({num})"
        t = core + meas
        return {"text": t, "whole": {t, core}, "kind": "single"}
    if k < 0.75:
        a, b = r.randint(1, 9), r.randint(1, 9999)
        form = r.choice(["{a}억{b}만원", "{a}억 {b}천만원", "{a}억{b}만"])
        if "천만" in form:
            b = r.randint(1, 9)
        t = form.format(a=a, b=b)
        whole = {t, t[:-1] if t.endswith("원") else t}
        return {"text": t, "whole": whole, "kind": "compound"}
    a, b = sorted(r.sample(range(1, 999), 2))
    form = r.choice(["{a}~{b}", "{a}%~{b}%", "{a}억~{b}억원", "{a}~{b}%"])
    t = form.format(a=a, b=b)
    whole = {t, t[:-1] if t.endswith("원") else t}
    return {"text": t, "whole": whole, "kind": "range"}


MAGS = "십백천만억조경"


def ambiguous_space(prev: str, nxt: str) -> bool:
    """같은 줄에서 공백 한 칸으로 이은 두 수량 가운데 판정이 원래 모호한 꼴 — 만들지 않는다.
    '숫자 공백 숫자'(자릿수를 공백으로 나눈 표기) · '크기 단위 공백 숫자'(1억 2,345 같은 복합 수량) · '공백 -수'(12% -3% 는 범위로도 읽힌다)."""
    return ((prev[-1].isdigit() or prev[-1] == ")" or prev[-1] in MAGS) and nxt[0].isdigit()) or nxt[0] in "-–"


def document(r: random.Random, n: int = 6) -> tuple[str, list[dict]]:
    parts, items = [], []
    for x in range(n):
        q = quantity(r)
        if parts:
            sep = r.choice(SEPS)
            prev = parts[-1]
            if sep == " " and ambiguous_space(prev, q["text"]):
                sep = " 및 "
            parts.append(sep)
            q["sep_before"] = sep
        parts.append(q["text"])
        items.append(q)
    return "가상 표: " + "".join(parts) + " 끝.", items


def queries(r: random.Random, items: list[dict], k: int = 12) -> list[tuple[str, str]]:
    """(문구, 만든 까닭) — 'whole'(온전한 표기) · 'piece'(숫자를 담은 진부분 문자열) · 'cross'(탭·줄바꿈을 건너 둘을 이음)."""
    out = []
    for _ in range(k):
        q = r.choice(items)
        roll = r.random()
        if roll < 0.35:
            out.append((r.choice(sorted(q["whole"])), "whole"))
            continue
        if roll < 0.45:
            i = items.index(q)
            if i + 1 < len(items) and items[i + 1].get("sep_before") in ("\t", "\n"):
                out.append((q["text"] + " " + items[i + 1]["text"], "cross"))
                continue
        t = q["text"]
        for _ in range(20):
            a = r.randrange(len(t))
            b = r.randrange(a + 1, len(t) + 1)
            sub = t[a:b].strip()
            if sub and sub != t and any(c.isdigit() for c in sub) and sub not in q["whole"]:
                out.append((sub, "piece"))
                break
    return out


def expected(text: str, items: list[dict], query: str, why: str) -> bool:
    """온전한 표기 가운데 query 와 같은 것이 글에 있으면 찾는다. 그 밖은 찾지 않는다."""
    if why == "cross":
        return False
    return any(query in it["whole"] for it in items)
