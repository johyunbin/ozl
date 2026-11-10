#!/usr/bin/env python3
"""슈카월드 기존 커버리지 대조 — "이미 다룬 소재인가"를 제목·전사에서 찾는다.

    python -m ozl.research coverage 엔비디아 "젠슨 황"            # 제목에 낱말이 든 영상(최근 24개월)
    python -m ozl.research coverage 관세 --fulltext --months 12   # 전사 본문에 나온 횟수까지

읽는 것(전부 비공개): private/meta/catalog_syukaworld.csv · private/desk/latest_uploads.json(수집기가 받은 최신 업로드) ·
private/transcripts/trading_export/**.json. 전사 문장은 돌려주지 않는다 — 영상 식별자·제목·날짜·횟수만.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[3]
CATALOG = ROOT / "private" / "meta" / "catalog_syukaworld.csv"
LATEST = ROOT / "private" / "desk" / "latest_uploads.json"
EXPORT = ROOT / "private" / "transcripts" / "trading_export"

STOP = set("그리고 그러나 하지만 그런데 대한 위한 통해 관련 이번 올해 지난 오늘 내일 최근 현재 가운데 이후 이상 이하 대해 우리 한국 기자 종합 속보 단독 "
           "있다 없다 한다 했다 된다 됐다 것으로 밝혔다 전했다 따르면 예정 발표 전망 분석 가능성 the and for with from that this has have was were will after over into amid says said new".split())


def tokens(text: str) -> set[str]:
    """제목 대조용 낱말 집합 — 한글 2자 이상·영문 3자 이상·숫자 포함어. 조사 꼬리는 흔한 것만 뗀다."""
    out = set()
    for w in re.findall(r"[가-힣]+|[A-Za-z][A-Za-z0-9&.\-]+|\d+[가-힣%]+", text or ""):
        w = w.lower()
        if re.fullmatch(r"[가-힣]+", w):
            w = re.sub(r"(으로|에서|에게|까지|부터|이라는|라는|이라|에는|에도|으로는|은|는|이|가|을|를|의|에|도|와|과|로)$", "", w) if len(w) >= 3 else w
            if len(w) < 2:
                continue
        elif len(w) < 3:
            continue
        if w not in STOP:
            out.add(w)
    return out


def load_catalog() -> list[dict]:
    """카탈로그 + 최신 업로드를 합쳐 최신순으로. 읽지 못하면 예외를 그대로 올린다(조용히 '커버리지 없음'으로 보이지 않게)."""
    rows: dict[str, dict] = {}
    with CATALOG.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("kind") == "short":
                continue
            rows[r["video_id"]] = {"video_id": r["video_id"], "title": r["title"], "date": r["published_kst"][:10],
                                   "duration_sec": int(r.get("duration_sec") or 0)}
    if LATEST.exists():
        for r in json.loads(LATEST.read_text(encoding="utf-8")).get("videos", []):
            rows.setdefault(r["video_id"], {"video_id": r["video_id"], "title": r["title"], "date": r["date"], "duration_sec": 0})
    return sorted(rows.values(), key=lambda r: r["date"], reverse=True)


def search(keywords: list[str], months: int = 24, fulltext: bool = False, today: str | None = None, catalog: list[dict] | None = None,
           stats: dict | None = None) -> list[dict]:
    """낱말 중 하나라도 제목에 든 영상. fulltext 면 전사 본문 등장 횟수(body_hits)도 센다.
    stats 를 넘기면 읽지 못한 전사 수(unreadable)와 훑은 편수(scanned)를 채워 준다 — 0건이 '없음'인지 '못 읽음'인지 구분하려고."""
    kws = [k.strip().lower() for k in keywords if k.strip()]
    if not kws:
        return []
    cat = load_catalog() if catalog is None else catalog
    base = datetime.strptime(today, "%Y-%m-%d") if today else datetime.now()
    since, until = (base - timedelta(days=30.5 * months)).strftime("%Y-%m-%d"), base.strftime("%Y-%m-%d")
    hits: dict[str, dict] = {}
    scanned = unreadable = 0
    for r in cat:
        if not since <= r["date"] <= until:
            continue
        t = r["title"].lower()
        m = [k for k in kws if k in t]
        if m:
            hits[r["video_id"]] = {**r, "title_hits": m, "body_hits": 0}
    if fulltext:
        src = EXPORT / "syuka"
        if not src.exists():
            raise FileNotFoundError(f"전사 폴더 없음: {src} — 본문 대조를 건너뛴 채 '없음'으로 보고하지 않는다")
        by_id = {r["video_id"]: r for r in cat}
        for f in src.glob("*.json"):
            vid = f.stem
            r = by_id.get(vid)
            if not r or not since <= r["date"] <= until:
                continue
            scanned += 1
            try:
                body = json.loads(f.read_text(encoding="utf-8")).get("text", "").lower()
            except Exception:  # noqa: BLE001 — 깨진 전사 한 편 때문에 전체 대조를 멈추지는 않되, 못 읽은 수는 센다
                unreadable += 1
                continue
            n = sum(body.count(k) for k in kws)
            if n >= 3 or vid in hits:
                hits.setdefault(vid, {**r, "title_hits": [], "body_hits": 0})["body_hits"] = n
    if stats is not None:
        stats.update(scanned=scanned, unreadable=unreadable)
    if fulltext and scanned and unreadable == scanned:
        raise OSError(f"전사 {scanned}편을 하나도 읽지 못했다 — 본문 대조 결과를 '없음'으로 쓰지 않는다")
    return sorted(hits.values(), key=lambda r: (bool(r["title_hits"]), r["date"]), reverse=True)


def recent_overlap(title_tokens: set[str], catalog: list[dict], today: str, days: int = 180, need: int = 2) -> list[dict]:
    """후보 묶음의 낱말이 최근 영상 제목과 need 개 이상 겹치는 것 — 수집기의 자동 표시용(최대 3편)."""
    since = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    for r in sorted(catalog, key=lambda r: r["date"], reverse=True):
        if r["date"] > today:
            continue
        if r["date"] < since:
            break  # 최신순으로 훑으므로 여기서 끝낸다
        common = title_tokens & tokens(r["title"])
        if len(common) >= need:
            out.append({"video_id": r["video_id"], "title": r["title"], "date": r["date"], "common": sorted(common)})
    out.sort(key=lambda r: (len(r["common"]), r["date"]), reverse=True)
    return out[:3]


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="ozl.research coverage")
    ap.add_argument("keywords", nargs="+")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--fulltext", action="store_true")
    a = ap.parse_args(argv)
    st: dict = {}
    rows = search(a.keywords, a.months, a.fulltext, stats=st)
    print(f"낱말 {a.keywords} · 최근 {a.months}개월 · {len(rows)}편" + (f" · 전사 {st['scanned']}편 훑음" if a.fulltext else ""))
    if st.get("unreadable"):
        print(f"⚠️ 읽지 못한 전사 {st['unreadable']}편 — 본문 대조가 불완전하다")
    for r in rows[:30]:
        body = f" · 본문 {r['body_hits']}회" if a.fulltext else ""
        print(f"- {r['date']} {r['video_id']} {r['title']}{body}")
    return 0
