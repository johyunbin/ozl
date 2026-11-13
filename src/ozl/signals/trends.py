"""급상승 검색어를 이슈와 그룹에 잇기(§5-2). 검색어의 날짜는 오른 시각(published)의 KST 날짜이고, 같은 언어의 이슈에만 잇는다.

1. 검색어의 낱말(terms ∪ entities)이 비어 있지 않고 전부 이슈 쪽 낱말(d−1 ~ d 기사)에 들어 있다.
2. 딸린 기사(trend_news)가 있으면: 그 제목과 이슈 기사 제목 하나의 Dice ≥ 0.50, 또는 딸린 기사 낱말에서 검색어 낱말을 뺀 나머지가
   이슈 쪽과 2개 이상 겹친다.
3. 딸린 기사가 없으면 검색어 낱말이 둘 이상.
여럿이 맞으면 (Dice, 겹친 수)가 큰 이슈 하나, 같으면 번호가 이른 쪽. 딸린 기사는 기사로 세지 않는다(§2-3).
"""
from __future__ import annotations

import functools

from ozl.signals import config, score, text


@functools.lru_cache(maxsize=4096)
def _words(title: str, lang: str) -> frozenset:
    r = text.analyze(title, lang)
    return frozenset(r["terms"]) | frozenset(r["entities"])


def kw_words(t: dict) -> frozenset:
    return _words(t["title"], t["lang"])


def news_title(t: dict) -> str:
    return str((t.get("extra") or {}).get("trend_news") or "").strip()


def traffic(t: dict) -> str:
    return str((t.get("extra") or {}).get("traffic") or "")


def side_of(arts: list[dict]) -> tuple[frozenset, list]:
    """이슈(또는 그룹) 쪽: 기사들의 낱말 합과 제목 글자 묶음 목록."""
    words = set()
    tbs = []
    for a in arts:
        words |= set(a.get("terms") or ()) | set(a.get("entities") or ())
        tbs.append((a["key"], text.bigrams(text.norm_title(a["title"]))))
    return frozenset(words), tbs


def match(t: dict, side: tuple[frozenset, list]) -> tuple[bool, float, int, str | None]:
    """(맞는가, Dice, 겹친 수, 맞은 기사 키)."""
    words, tbs = side
    kw = kw_words(t)
    if not kw or not kw <= words:
        return False, 0.0, 0, None
    nt = news_title(t)
    if nt:
        ntb = text.bigrams(text.norm_title(nt))
        best, key = 0.0, None
        for k, tb in tbs:
            dv = text.dice(ntb, tb)
            if dv > best:
                best, key = dv, k
        over = len((_words(nt, t["lang"]) - kw) & words)
        ok = best >= config.TREND_NEWS_DICE or over >= config.TREND_NEWS_OVERLAP
        return ok, best, over, key if best >= config.TREND_NEWS_DICE else None
    return len(kw) >= config.TREND_MIN_WORDS, 0.0, 0, None


def assign(trends_d: list[dict], sides: dict[str, tuple[str, tuple]]) -> tuple[dict, list]:
    """trends_d: 그날 검색어. sides: 이슈 → (언어, 쪽). → ({검색어 키: 이은 결과}, 맞지 않은 검색어 목록)."""
    got, unmatched = {}, []
    for t in sorted(trends_d, key=lambda x: x["key"]):
        best = None
        for iid in sorted(sides):
            lang, side = sides[iid]
            if lang != t["lang"]:
                continue
            ok, dv, over, mk = match(t, side)
            if ok and (best is None or (dv, over) > best[0]):
                best = ((dv, over), iid, mk)
        if best is None:
            unmatched.append(t)
        else:
            got[t["key"]] = {"issue_id": best[1], "trend_key": t["key"], "keyword": t["title"], "traffic_raw": traffic(t),
                             "grade": score.grade(traffic(t)), "matched_article": best[2], "dice": round(best[0][0], 6),
                             "overlap": best[0][1]}
    return got, unmatched


def group_hit(group: dict, trends: list[dict], arts: dict) -> bool:
    """계열 1곳 그룹의 새 이슈 조건(§4-2): 같은 날·같은 언어 검색어 가운데 이 그룹에 맞는 것이 있나."""
    ts = [t for t in trends if t["day"] == group["day"] and t["lang"] == group["lang"]]
    if not ts:
        return False
    side = side_of([arts[k] for k in [*group["units"], *(group.get("copies") or [])] if k in arts])
    return any(match(t, side)[0] for t in ts)
