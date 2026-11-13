"""중복 제거(§2). 같은 주소는 한 기사, 통신사 전재는 대표 기사 하나로 묶는다."""
from __future__ import annotations

import re
from collections import defaultdict

from ozl.signals import config, text, urls
from ozl.signals.source import order_key


def merge_same_url(items: list[dict]) -> list[dict]:
    """news·official 가운데 정규화 주소가 같은 항목을 한 기사로. 대표 = 받은 시각이 가장 이른 것(같으면 키 순).
    다른 항목의 제목은 alt_titles, 키는 alt_keys 에 남긴다. 급상승(trend) 항목은 주소가 피드 주소라 넣지 않는다."""
    by: dict[str, list[dict]] = defaultdict(list)
    rest = []
    for it in items:
        if it["kind"] in ("news", "official") and urls.is_article_url(it.get("canon")):
            by[it["canon"]].append(it)
        else:
            rest.append(dict(it, alt_titles=[], alt_keys=[]))
    for _, grp in sorted(by.items()):
        grp = sorted(grp, key=lambda x: (x["received_at"], x["key"]))
        rep = dict(grp[0])
        rep["alt_titles"] = [g["title"] for g in grp[1:]]
        rep["alt_keys"] = [g["key"] for g in grp[1:]]
        rep["received_at"] = grp[0]["received_at"]
        rest.append(rep)
    rest.sort(key=order_key)
    return rest


_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_LATIN = re.compile(r"[A-Za-z]+")


def _prep(a: dict) -> None:
    """전재 비교에 쓰는 값. 표지는 '_sb'(요약 묶음)다. cluster.prep_unit 이 '_tb'만 붙인 기사가 와도 여기서 나머지를 만든다."""
    if "_sb" not in a:
        a["norm_title"] = a.get("norm_title") or text.norm_title(a["title"])
        a["norm_summary"] = a.get("norm_summary") if a.get("norm_summary") is not None else text.norm_summary(a.get("summary", ""))
        a["_tb"] = text.bigrams(a["norm_title"])
        a["_sb"] = text.bigrams(a["norm_summary"])
        t = text.strip_head(a["title"])
        a["_marks"] = (frozenset(_NUM.findall(t)), frozenset(w.lower() for w in _LATIN.findall(t)),
                       frozenset(a.get("entities") or ()))


def same_marks(a: dict, b: dict) -> bool:
    """두 제목의 숫자 토큰, 영문자 토큰, 고유명사 집합이 서로 다르지 않은가. 어느 한 집합이라도 양쪽에 상대에 없는 것이
    있으면(바꿔 끼운 표지) 제목 규칙으로는 전재로 보지 않는다('1공장 화재'와 '2공장 화재', 'A역'과 'B역'처럼 틀만 같은
    서로 다른 속보). 한쪽에만 표지가 더 있는 것('WSJ "…"', '이란 혁명수비대 …')은 전재로 둔다."""
    _prep(a)
    _prep(b)
    return not any((x - y) and (y - x) for x, y in zip(a["_marks"], b["_marks"]))


def copy_relation(a: dict, b: dict) -> tuple[str, float] | None:
    """(규칙, 제목 Dice) 또는 None. 규칙 '제목' = (가), '요약' = (나)."""
    if a["lang"] != b["lang"] or a["kind"] != "news" or b["kind"] != "news":
        return None
    _prep(a)
    _prep(b)
    hours = abs((a["event_at"] - b["event_at"]).total_seconds()) / 3600
    td = text.dice(a["_tb"], b["_tb"])
    if td >= config.COPY_TITLE_DICE and hours <= config.COPY_TITLE_HOURS and same_marks(a, b):
        return ("제목", td)
    if (len(a["norm_summary"]) >= config.COPY_SUMMARY_MINLEN and len(b["norm_summary"]) >= config.COPY_SUMMARY_MINLEN
            and td >= config.COPY_SUMMARY_TITLE_DICE and hours <= config.COPY_SUMMARY_HOURS
            and text.dice(a["_sb"], b["_sb"]) >= config.COPY_SUMMARY_DICE):
        return ("요약", td)
    return None


def copy_groups(articles: list[dict], prior_reps: list[dict] = ()) -> dict[str, dict]:
    """전재 사본 → {'rep': 대표 키, 'rule': '제목'|'요약', 'dice': 제목 Dice}.

    발행 시각순으로 보며, 이미 있는 묶음의 **대표**와 전재 관계면 그 묶음에(여럿이면 제목 Dice 가 큰 쪽, 같으면 대표가 이른 쪽),
    아니면 새 묶음의 대표가 된다(사슬 방지). prior_reps 는 확정된 날의 대표 기사(대표로만 쓰이고 바뀌지 않는다).
    """
    reps: list[dict] = []
    index: dict[str, list[int]] = defaultdict(list)   # 제목 글자 묶음 → 대표 번호
    floor = min(config.COPY_TITLE_DICE, config.COPY_SUMMARY_TITLE_DICE)
    window = max(config.COPY_TITLE_HOURS, config.COPY_SUMMARY_HOURS) * 3600

    def add_rep(a):
        _prep(a)
        reps.append(a)
        for g in a["_tb"]:
            index[g].append(len(reps) - 1)

    for p in sorted(prior_reps, key=order_key):
        add_rep(p)
    out: dict[str, dict] = {}
    for a in sorted(articles, key=order_key):
        if a["kind"] != "news":
            continue
        _prep(a)
        shared: dict[int, int] = defaultdict(int)
        for g in a["_tb"]:
            for i in index.get(g, ()):
                shared[i] += 1
        best = None
        for i in sorted(shared):
            r = reps[i]
            if r["key"] == a["key"] or 2 * shared[i] / (len(r["_tb"]) + len(a["_tb"])) < floor:
                continue
            if abs((r["event_at"] - a["event_at"]).total_seconds()) > window:
                continue
            rel = copy_relation(r, a)
            if rel is None:
                continue
            k = (rel[1], -i)
            if best is None or k > best[0]:
                best = (k, r, rel)
        if best is None:
            add_rep(a)
        else:
            _, r, rel = best
            out[a["key"]] = {"rep": r["key"], "rule": rel[0], "dice": round(rel[1], 6)}
    return out
