"""분야(§6-3). [d−2, d] 대표 기사마다 (피드 섹션 분야 +1) + (제목에 낱말이 있는 분야마다 +2, 분야당 한 번).
정치 낱말은 나라 이름(한국 제외)이 있고 국내 표지가 없으면 국제로 센다. 같으면 정치 → 사회 → 경제 → 국제 → 과학기술 → 연예 → 스포츠.
합이 2점 미만이면 기타."""
from __future__ import annotations

import functools
import re
from collections import Counter

import yaml

from ozl.signals import config

OTHER = "기타"
DOMESTIC = ("국내", "한국", "우리나라")       # sensitive._DOMESTIC 의 나라 표지와 같은 낱말


@functools.lru_cache(maxsize=1)
def table() -> dict:
    doc = yaml.safe_load((config.DATA / "categories.yaml").read_text(encoding="utf-8")) or {}
    from ozl.research import videos
    from ozl.signals import text
    secs = text._keyword_sections()
    reps = {c for s, cs in secs.items() if s.startswith("나라") for c in cs} - {"한국"}
    amap = videos.load_keywords()
    names = set(reps)
    for k, v in amap.items():
        if v in reps and len(k) >= 2 and re.fullmatch(r"[가-힣]+", k):
            names.add(k)
    names = sorted({n for n in names if len(n) >= 2}, key=len, reverse=True)
    words = {c: [str(w) for w in ws] for c, ws in (doc.get("words") or {}).items()}
    words.setdefault("국제", [])
    words["국제"] = words["국제"] + names
    return {"words": words, "sections": {str(k): str(v) for k, v in (doc.get("sections") or {}).items()},
            "tie": [str(x) for x in doc.get("tie_order") or []], "countries": names}


def _has(t: str, w: str) -> bool:
    if re.fullmatch(r"[A-Za-z]+", w):
        return re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", t) is not None
    return w in t


def article_points(title: str, section: str) -> Counter:
    T = table()
    pts: Counter = Counter()
    sec = T["sections"].get(section or "")
    if sec:
        pts[sec] += 1
    foreign = any(n in title for n in T["countries"]) and not any(m in title for m in DOMESTIC)
    hit = {("국제" if cat == "정치" and foreign else cat) for cat, ws in T["words"].items() if any(_has(title, w) for w in ws)}
    for cat in hit:
        pts[cat] += 2
    return pts


def category_of(arts: list[dict]) -> tuple[str, dict]:
    """arts: [{'title', 'section'}] → (분야, 분야별 점수)."""
    T = table()
    tot: Counter = Counter()
    for a in arts:
        tot.update(article_points(a.get("title") or "", a.get("section") or ""))
    if not tot or max(tot.values()) < 2:
        return OTHER, dict(tot)
    best = max(tot.values())
    tie = [c for c in T["tie"] if tot.get(c) == best] or sorted(c for c, v in tot.items() if v == best)
    return tie[0], dict(tot)
