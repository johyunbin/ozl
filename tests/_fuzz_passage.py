"""통째 대목(규칙 1 · capture.passage_bounds_error)과 차트 점 값 낱말 일치(규칙 2 · capture.find_value) 무작위 시험의 생성기.
만든 방법이 곧 정답이다 — capture.py·numbers.py 에 기대지 않는다. 예시 낱말과 수치는 전부 지어낸 것이다.

규칙 1 (passage_doc): 문단(문장들 · 문장 안의 '부드러운' 줄바꿈 · 수량 한가운데의 '단단한' 줄바꿈) · html 표의 줄(칸 사이 탭) ·
PDF 표의 줄(칸 사이 여러 칸 공백) · 마침표 없는 제목 줄을 줄바꿈·쪽 구분으로 이어 붙인다. 만들면서 원문 자리에 표시해 둔다:
  시작 가능 = 글의 처음 · 탭 뒤 · 블록 사이 줄바꿈 뒤 · 부드러운 줄바꿈 뒤 · 문장 끝(닫는 따옴표 포함) 뒤 공백 뒤
  끝 가능   = 글의 끝 · 탭 앞 · 블록 사이 줄바꿈 앞 · 부드러운 줄바꿈 앞 · 문장 끝 글자 바로 뒤(뒤가 공백)
  단단한 줄바꿈(3\\n억원 · −\\n$3 million · 3%~\\n5% · 3%\\n~5% · 1억\\n2천만원 · $3\\nmillion · 4,513\\n억원)은 어느 쪽도 아니다.
  기대값: 시작·끝이 둘 다 가능한 자리이고 사이에 탭이 없으면 통과, 그 밖은 거부.
  부드러운 줄바꿈은 앞이 수 없는 낱말일 때만 넣는다(앞 줄이 수량으로 끝나는 줄바꿈은 수량이 이어지는지 본래 가를 수 없다).
  부호로 '–'·'—' 를 쓰지 않는다(줄 머리의 '–' 는 범위 이음과 가를 수 없다).

규칙 2 (value_doc): 낱말 목록을 알고 글을 만든다. 홀로 선 값(표의 칸) · 부호가 붙은 값(-v · △v · (v)) · 범위(v~w) · 조사가 붙은 값(v명이다.) ·
띄어 쓴 부호(− v) · 띄어 쓴 범위(v ~ w) · 낱말. 항목 사이는 탭(표의 다른 칸)일 수 있고, 탭 너머의 '-' 는 이웃으로 보지 않는다. 기대값: 낱말 하나로 넣은 항목의 그 낱말과 글자 그대로 같으면 찾는다(부호 뗀 값·범위의 한쪽·
조사 뗀 값·조각은 못 찾는다). 다만 홀로 선 값 바로 뒤에
띄어 쓴 '-' 부호가 오면(v - w) 범위의 앞쪽과 가를 수 없어 거부로 본다."""
from __future__ import annotations

import random
import unicodedata

WORDS = ["가상의", "섬의", "감자", "당근", "수확량은", "출하는", "전년", "대비", "최대", "늘었다", "줄었다", "기록했다", "the", "index",
         "rose", "growth", "통계청은", "올해", "지난해"]
SIGNS = ["", "", "", "-", "−", "+", "△", "▲", "▼"]
TAILS = ["", "", "%", "%p", "만", "억", "조"]
MEASURES = ["", "", "원", "명", "톤", "달러"]


def _num(r: random.Random) -> str:
    n = r.choice([r.randint(1, 9), r.randint(10, 999), r.randint(1000, 9_999_999)])
    s = f"{n:,}" if n >= 1000 and r.random() < 0.6 else str(n)
    if r.random() < 0.35:
        s += "." + str(r.randint(1, 99))
    return s


def quantity(r: random.Random) -> tuple[str, list[int]]:
    """(수량 표기, 단단한 줄바꿈을 넣을 수 있는 자리 — 표기 안의 위치(그 앞에서 줄을 바꾼다))."""
    k = r.random()
    if k < 0.45:
        sign, num, tail = r.choice(SIGNS), _num(r), r.choice(TAILS)
        meas = r.choice(MEASURES) if tail not in ("%", "%p") else ""
        t = sign + num + tail + meas
        cuts = []
        if sign:
            cuts.append(len(sign))                                   # −\n3%
        if tail in ("만", "억", "조"):
            cuts.append(len(sign + num))                             # 3\n억원
        if tail == "%":
            cuts.append(len(sign + num))                             # 3\n%
        return t, cuts
    if k < 0.60:
        a, b = r.randint(1, 9), r.randint(1, 9)
        t = f"{a}억 {b}천만원"
        return t, [t.index(" ")]                                      # 1억\n2천만원 (공백 자리를 줄바꿈으로)
    if k < 0.75:
        a, b = sorted(r.sample(range(1, 999), 2))
        t = r.choice(["{a}%~{b}%", "{a}~{b}", "{a}억~{b}억원"]).format(a=a, b=b)
        i = t.index("~")
        return t, [i, i + 1]                                          # 3%\n~5% · 3%~\n5%
    if k < 0.88:
        sign = r.choice(["", "−", "-"])
        t = f"{sign}${r.randint(1, 99)} million"
        cuts = [t.index(" ")]                                         # $3\nmillion
        if sign:
            cuts.append(1)                                            # −\n$3 million
        return t, cuts
    a = f"{r.randint(1, 9)},{r.randint(100, 999)}"
    return a + "억원", [len(a)]                                        # 4,513\n억원


class _Doc:
    def __init__(self):
        self.parts: list[str] = []
        self.n = 0
        self.vs: set[int] = set()       # 원문 자리: 대목이 시작해도 되는 첫 글자
        self.ve: set[int] = set()       # 원문 자리: 대목이 끝나도 되는 자리(마지막 글자 다음)
        self.hard: list[int] = []       # 단단한 줄바꿈의 원문 자리

    def add(self, s: str, start_ok: bool = False):
        if start_ok:
            self.vs.add(self.n)
        self.parts.append(s)
        self.n += len(s)

    def end_ok(self):
        self.ve.add(self.n)

    @property
    def text(self) -> str:
        return "".join(self.parts)


def _sentence(r: random.Random, d: _Doc, first: bool):
    """한 문장. first 면 문장 첫 글자를 시작 가능 자리로(앞이 블록 경계거나 문장 끝 + 공백)."""
    quoted = r.random() < 0.12
    toks = []
    for x in range(r.randint(2, 7)):   # 첫 토큰은 낱말 — 앞 블록이 수량으로 끝난 줄이면 '수량\n수량' 이 되어 본래 가를 수 없다
        toks.append(("q", *quantity(r)) if x and r.random() < 0.4 else ("w", r.choice(WORDS), []))
    toks.append(("w", r.choice(["늘었다", "줄었다", "기록했다"]), []))
    if quoted:
        d.add('"', start_ok=first)
        first = False
    for x, (kind, t, cuts) in enumerate(toks):
        if x:
            prev_kind = toks[x - 1][0]
            if prev_kind == "w" and r.random() < 0.15:   # 부드러운 줄바꿈 — 앞이 수 없는 낱말
                d.end_ok()
                d.add("\n")
                d.vs.add(d.n)
            else:
                d.add(" ")
        start = first and x == 0
        if kind == "q" and cuts and r.random() < 0.3:
            c = r.choice(cuts)
            head, tail = t[:c], t[c:]
            tail = tail[1:] if tail.startswith(" ") else tail   # 공백 자리는 그 공백을 줄바꿈으로 바꾼다
            d.add(head, start_ok=start)
            d.hard.append(d.n)
            d.add("\n")
            d.add(tail)
        else:
            d.add(t, start_ok=start)
    d.add("." + ('"' if quoted else ""))
    d.end_ok()


def passage_doc(r: random.Random) -> _Doc:
    d = _Doc()
    for b in range(r.randint(2, 6)):
        if b:
            d.add(r.choice(["\n", "\n\n", "\f", "\n\f"]))
        kind = r.random()
        if kind < 0.5:                                      # 문단
            for s in range(r.randint(1, 4)):
                if s:
                    d.add(" ")
                _sentence(r, d, first=True)
        elif kind < 0.7:                                    # html 표의 줄(칸 사이 탭)
            d.add(r.choice(WORDS), start_ok=True)
            for _ in range(r.randint(1, 4)):
                d.end_ok()
                d.add("\t")
                d.add(quantity(r)[0], start_ok=True)
            d.end_ok()
        elif kind < 0.85:                                   # PDF 표의 줄(칸 사이 여러 칸 공백) — 줄 전체만 통째 대목
            d.add(r.choice(WORDS), start_ok=True)
            for _ in range(r.randint(1, 4)):
                d.add(" " * r.randint(2, 6))
                d.add(quantity(r)[0])
            d.end_ok()
        else:                                               # 마침표 없는 제목 줄
            d.add(" ".join(r.choice(WORDS) for _ in range(r.randint(1, 3))) + f" {r.randint(1000, 2999)}", start_ok=True)
            d.end_ok()
    return d


def spans(r: random.Random, d: _Doc, norm_len: int, pos: list[int], k: int = 40) -> list[tuple[int, int, bool]]:
    """(정리한 글의 시작, 끝, 기대 통과 여부). 가능한 자리끼리 · 무작위 · 단단한 줄바꿈 바로 앞뒤를 섞는다."""
    text = d.text
    vs = [i for i in range(norm_len) if pos[i] in d.vs]
    ve = [j for j in range(1, norm_len + 1) if pos[j - 1] + 1 in d.ve]
    near_hard = []
    for h in d.hard:
        for i in range(norm_len):
            if pos[i] > h:
                near_hard.append(i)            # 단단한 줄바꿈 바로 뒤에서 시작
                break
    hard_end = []
    for h in d.hard:
        j = max((j for j in range(1, norm_len + 1) if pos[j - 1] < h), default=None)
        if j:
            hard_end.append(j)                 # 단단한 줄바꿈 바로 앞에서 끝
    svs, sve = set(vs), set(ve)
    out = []
    for _ in range(k):
        roll = r.random()
        a = r.choice(vs) if roll < 0.55 or not near_hard else r.choice(near_hard) if roll < 0.7 else r.randrange(norm_len)
        cand_b = [j for j in ve if j > a]
        hb = [j for j in hard_end if j > a]
        roll = r.random()
        if roll < 0.55 and cand_b:
            b = r.choice(cand_b[:8])
        elif roll < 0.7 and hb:
            b = r.choice(hb)
        else:
            b = r.randrange(a + 1, norm_len + 1)
        if r.random() < 0.15:                  # 가능한 자리에서 한 글자 어긋나게
            b = min(norm_len, max(a + 1, b + r.choice([-1, 1])))
        raw = text[pos[a]:pos[b - 1] + 1]
        out.append((a, b, a in svs and b in sve and "\t" not in raw))
    return out


# ── 규칙 2 ─────────────────────────────────────────────────────────────
VALUES_INT = ["66", "1,234", "11,234", "4", "850,364", "2026", "123"]


def _value(r: random.Random) -> str:
    v = r.choice([r.choice(VALUES_INT), f"{r.randint(0, 99)}.{r.randint(0, 99):02d}", f".{r.randint(1, 9)}"])
    return v + r.choice(["", "", "%", "%p"]) if not v.endswith("%") else v


RANGE_WORDS = ["-", "–", "—", "~", "∼", "〜", "～"]
SIGN_WORDS = ["−", "-", "+", "△", "▲", "▽", "▼", "~", "("]
SPACES = [" ", " ", "  ", "\t", "\n", "\f", "　", "\xa0", "\r\n"]


def value_doc(r: random.Random) -> tuple[str, list[dict]]:
    """(글, 항목들). 항목 = {words, standalone(홀로 선 값의 낱말 | None), inner(그 항목에 든 값들)}."""
    items = []
    for _ in range(r.randint(4, 12)):
        k = r.random()
        v, w = _value(r), _value(r)
        if k < 0.30:
            items.append({"words": [v], "standalone": v, "inner": [v]})
        elif k < 0.42:                       # 낱말 하나인 항목은 그 낱말 통째가 홀로 선 낱말이다('-0.8%' 를 그대로 찾으면 찾는다)
            s = r.choice(["-", "−", "△", "▲", "+"])
            items.append({"words": [s + v], "standalone": s + v, "inner": [v]})
        elif k < 0.50:
            items.append({"words": [f"({v})"], "standalone": f"({v})", "inner": [v]})
        elif k < 0.60:
            items.append({"words": [f"{v}~{w}"], "standalone": f"{v}~{w}", "inner": [v, w]})
        elif k < 0.68:
            items.append({"words": [f"{v}명이다."], "standalone": f"{v}명이다.", "inner": [v, v + "명"]})
        elif k < 0.78:
            items.append({"words": [r.choice(SIGN_WORDS), v], "standalone": None, "inner": [v]})
        elif k < 0.88:
            items.append({"words": [v, r.choice(RANGE_WORDS), w], "standalone": None, "inner": [v, w]})
        else:
            items.append({"words": [r.choice(WORDS)], "standalone": None, "inner": []})
    # 항목 사이는 아무 공백류(탭 = 표의 다른 칸 포함), 한 항목 안의 낱말 사이는 탭이 아닌 공백류(띄어 쓴 부호·범위는 한 칸 안이다)
    gaps = [r.choice(SPACES) for _ in items[1:]]
    for x in range(len(items) - 1):          # 홀로 선 값 바로 뒤가 같은 칸의 범위 이음 낱말이면(v - w) 범위의 앞쪽과 가를 수 없다 → 거부
        if items[x]["standalone"] and items[x + 1]["words"][0] in RANGE_WORDS and "\t" not in gaps[x]:
            items[x]["ambig"] = True
    inner = [s for s in SPACES if "\t" not in s]
    parts = []
    for x, it in enumerate(items):
        if x:
            parts.append(gaps[x - 1])
        parts.append(it["words"][0] + "".join(r.choice(inner) + w for w in it["words"][1:]))
    return "".join(parts), items


def value_queries(r: random.Random, items: list[dict], k: int = 10) -> list[str]:
    """차트 점 값처럼 숫자가 든 문구만 — 값 · 값의 조각 · 부호 뗀 값 · 범위의 한쪽 · 조사 뗀 값 · 낱말 통째."""
    out = []
    while len(out) < k:
        it = r.choice(items)
        roll = r.random()
        if it["inner"] and roll < 0.5:
            out.append(r.choice(it["inner"]))
        elif roll < 0.8:
            w = r.choice(it["words"])
            if any(c.isdigit() for c in w) and len(w) > 1:
                a = r.randrange(len(w))
                b = r.randrange(a + 1, len(w) + 1)
                out.append(w[a:b])
            else:
                out.append(w)
        else:
            out.append(r.choice(it["words"]))
        if not any(c.isdigit() for c in out[-1]):
            out.pop()
    return out


def value_expected(items: list[dict], q: str) -> bool:
    q = q.strip()
    if not q or any(ch.isspace() or unicodedata.category(ch) == "Cf" for ch in q):
        return False
    return any(it["standalone"] == q and not it.get("ambig") for it in items)
