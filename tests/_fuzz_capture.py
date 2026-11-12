"""find_phrase 무작위 시험의 생성기 — 만든 방법이 곧 정답이다(find_phrase·numbers.py 에 기대지 않는다).

수량 = [부호][정수(쉼표 유무)][.소수][크기 단위·%·%p] 가 핵심(core), 그 뒤에 측정 단위 낱말(원·명·톤·달러)이 붙을 수 있다.
측정 단위 낱말은 수량에 넣지 않는다(numbers.py 와 같은 정의) — 그래서 core 만 쓴 문구도 '온전한 수량'이다.
복합 수량(1억2만원 · 1억 2천만원)과 범위(3~5 · 3%~5% · 3억~5억원)는 전체(와 측정 단위를 뗀 전체)만 온전하다.
기대값: 온전한 표기(위)가 글에 그 표기로 있으면 찾는다. 그 밖에 숫자를 담은 진부분 문자열·범위의 한쪽·복합의 일부·
탭·줄바꿈을 건너 두 수량을 이은 문구는 찾지 않는다(줄바꿈 너머가 여는 괄호로 시작하는 줄만 예외 — 괄호 설명과 가를 수 없다).
모호한 꼴은 만들지 않는다(ambiguous_space): 같은 줄에서 공백 한 칸으로 이은 '숫자 공백 숫자'·'크기 단위 공백 숫자'·'공백 -수'.
줄바꿈은 이어 읽는다(탭만 칸을 끊는다). 그래서 같은 꼴을 줄바꿈으로 이은 자리는 만들되, 그 양옆 수량의 기대값은 '거부'다(expected)."""
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


def ambiguous_newline(prev: str, nxt: str) -> bool:
    """줄바꿈으로 이은 두 수량 가운데 이어 읽으면 한 수량과 가를 수 없는 꼴 — '크기 단위\n숫자'(1억\n2,345 = 복합 수량)와
    '수량(단위 낱말 없이)\n-수'(12%\n-3% = 범위). 측정 단위 낱말 뒤의 '-' 는 다음 수의 부호이고, '숫자\n숫자' 는 두 수로 읽는다."""
    last = prev[-1]
    return (last in MAGS and nxt[0].isdigit()) or (nxt[0] in "-–" and (last.isdigit() or last in MAGS or last == "%" or prev.endswith("%p")))


def document(r: random.Random, n: int = 6) -> tuple[str, list[dict]]:
    parts, items = [], []
    for x in range(n):
        q = quantity(r)
        if parts:
            sep = r.choice(SEPS)
            prev = parts[-1]
            if sep == " " and ambiguous_space(prev, q["text"]):
                sep = " 및 "
            if sep == "\n" and ambiguous_newline(prev, q["text"]):
                items[-1]["ambig"] = q["ambig"] = True   # 줄바꿈은 이어 읽으므로(PDF 줄바꿈이 수량 한가운데일 수 있다) 같은 꼴이 모호하다 → 둘 다 거부
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
    """온전한 표기 가운데 query 와 같은 것이 글에 있으면 찾는다. 그 밖은 찾지 않는다.
    모호한 줄바꿈(ambiguous_space 꼴을 줄바꿈으로 이은 자리) 양옆의 수량은 온전한 표기라도 찾지 않는다 — 줄바꿈을 공백으로 이어 읽으면
    '3억\n3,000' 은 복합 수량 '3억 3,000' 과, '12%\n-3%' 는 범위와 가를 수 없다."""
    if why == "cross":
        # 줄바꿈 너머가 여는 괄호로 시작하는 줄('3억톤\n(7.5)')은 문장이 괄호 설명으로 이어지는 꼴과 가를 수 없어 거부하지 않는다
        # (find_phrase 의 줄바꿈 거부는 숫자·부호·범위 이음으로 시작하는 줄만 — 주 방어선은 통째 대목 규칙이다). 탭을 건넌 것은 거부.
        return any(it.get("sep_before") == "\n" and it["text"].startswith("(") and query.endswith(" " + it["text"]) and
                   items[i - 1]["text"] + " " + it["text"] == query for i, it in enumerate(items) if i)
    return any(query in it["whole"] and not it.get("ambig") for it in items)
