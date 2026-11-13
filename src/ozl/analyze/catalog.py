#!/usr/bin/env python3
"""메타 JSONL → (비공개) 전체 카탈로그 CSV · (공개) 집계 개요 · 대표 30편 · 라이브↔클립 매핑 (OZL Phase 1A).

    python -m ozl.analyze.catalog all            # 세 채널 카탈로그 + 공개 집계
    python -m ozl.analyze.catalog sample30       # 슈카월드 대표 30편(최신/중간/고조회 10편씩)
    python -m ozl.analyze.catalog livemap        # 슈카월드 라이브 풀버전 ↔ 주중 클립 매핑

공개 산출(`tracks/syuka/analysis/`)은 집계만. 개별 영상 행(제목·조회수 등)은 `private/meta/` 에만 둔다(YouTube API 정책: 30일 갱신).
"""
from __future__ import annotations

import csv
import json
import pathlib
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
META = ROOT / "private" / "meta"
EXPORT_IDX = ROOT / "private" / "transcripts" / "trading_export" / "index.csv"
PUB = ROOT / "tracks" / "syuka" / "analysis"
HANDLES = {"syukaworld": "슈카월드", "moneymoneycomics": "머니코믹스", "rsangmoo": "알상무"}
KST = timezone(timedelta(hours=9))


def load(handle: str) -> list[dict]:
    p = META / f"{handle}_videos.jsonl"
    rows = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    tr = {}
    if EXPORT_IDX.exists():
        for r in csv.DictReader(EXPORT_IDX.open(encoding="utf-8")):
            tr[r["video_id"]] = r
    for r in rows:
        t = tr.get(r["video_id"])
        r["has_transcript"] = int(bool(t and t.get("has_transcript") == "1"))
        r["transcript_source"] = (t or {}).get("transcript_source", "")
        r["published_kst"] = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    rows.sort(key=lambda r: r["published_at"], reverse=True)
    return rows


def write_catalog(handle: str, rows: list[dict]) -> pathlib.Path:
    out = META / f"catalog_{handle}.csv"
    cols = ["video_id", "title", "published_kst", "duration_sec", "kind", "view_count", "like_count", "comment_count",
            "category_id", "topics", "tags", "has_transcript", "transcript_source", "caption", "fetched_at"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get("video_id"), r.get("title"), r.get("published_kst"), r.get("duration_sec"), r.get("kind"),
                        r.get("view_count"), r.get("like_count"), r.get("comment_count"), r.get("category_id"),
                        "|".join(r.get("topics") or []), "|".join(r.get("tags") or []), r.get("has_transcript"),
                        r.get("transcript_source"), r.get("caption"), r.get("fetched_at")])
    return out


def bucket(sec: int) -> str:
    m = sec / 60
    return "<5분" if m < 5 else "5~15" if m < 15 else "15~30" if m < 30 else "30~60" if m < 60 else "60~120" if m < 120 else "120+"


def write_overview(handle: str, rows: list[dict]) -> pathlib.Path:
    name = HANDLES.get(handle, handle)
    kinds = Counter(r["kind"] for r in rows)
    years = defaultdict(lambda: {"n": 0, "h": 0.0, "live": 0, "tr": 0})
    for r in rows:
        y = r["published_kst"][:4]
        years[y]["n"] += 1
        years[y]["h"] += r["duration_sec"] / 3600
        years[y]["live"] += r["kind"] == "live"
        years[y]["tr"] += r["has_transcript"]
    durb = Counter(bucket(r["duration_sec"]) for r in rows if r["kind"] != "short")
    tags = Counter(t for r in rows for t in (r.get("tags") or []))
    topics = Counter(t for r in rows for t in (r.get("topics") or []))
    wd = Counter(datetime.strptime(r["published_kst"], "%Y-%m-%d %H:%M").strftime("%a") for r in rows if r["kind"] == "video")
    hours = Counter(r["published_kst"][11:13] + "시" for r in rows if r["kind"] == "video")
    recent = [r for r in rows if r["kind"] == "video" and r["published_kst"] >= (datetime.now(KST) - timedelta(days=365)).strftime("%Y-%m-%d")]
    # 조회수 집계는 내지 않는다(2026-11-14). 유튜브 API 개발자 정책이 API 통계로 집계와 새 지표를 만드는 것을 막는다.
    total_h = sum(r["duration_sec"] for r in rows) / 3600
    lines = [f"# {name} 채널 개요 (집계)", "",
             f"- 기준: YouTube Data API v3 · 수집 {rows[0]['fetched_at'][:10] if rows else ''} · 개별 영상 데이터는 비공개(집계만 공개)",
             f"- 총 {len(rows):,}편 · {total_h:,.0f}시간 · 종류: " + ", ".join(f"{k} {v:,}" for k, v in kinds.most_common()),
             f"- 전사 보유(내부 코퍼스): {sum(r['has_transcript'] for r in rows):,}편 / 쇼츠 제외 {sum(1 for r in rows if r['kind'] != 'short'):,}편",
             "", "## 연도별", "", "| 연도 | 편수 | 시간 | 라이브 | 전사 보유 |", "|---|---|---|---|---|"]
    for y in sorted(years):
        v = years[y]
        lines.append(f"| {y} | {v['n']:,} | {v['h']:,.0f} | {v['live']} | {v['tr']:,} |")
    lines += ["", "## 길이 분포(쇼츠 제외)", "", "| 구간(분) | 편수 |", "|---|---|"]
    for k in ["<5분", "5~15", "15~30", "30~60", "60~120", "120+"]:
        lines.append(f"| {k} | {durb.get(k, 0):,} |")
    lines += ["", f"## 최근 12개월 일반 영상 {len(recent):,}편", "",
              f"- 평균 길이 {statistics.mean([r['duration_sec'] for r in recent])/60:.1f}분" if recent else "",
              "", "## 업로드 요일(일반 영상)", "", "| 요일 | 편수 |", "|---|---|"]
    for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        lines.append(f"| {d} | {wd.get(d, 0):,} |")
    lines += ["", "## 업로드 시각(KST, 일반 영상 상위 6)", "", "| 시각 | 편수 |", "|---|---|"]
    for h, n in hours.most_common(6):
        lines.append(f"| {h} | {n:,} |")
    lines += ["", "## YouTube 주제 카테고리(topicDetails) 상위", "", "| 주제 | 편수 |", "|---|---|"]
    for t, n in topics.most_common(12):
        lines.append(f"| {t} | {n:,} |")
    lines += ["", "## 태그 상위 30(채널이 붙인 태그 집계)", "", "| 태그 | 편수 |", "|---|---|"]
    for t, n in tags.most_common(30):
        lines.append(f"| {t} | {n:,} |")
    PUB.mkdir(parents=True, exist_ok=True)
    out = PUB / f"overview_{handle}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


TOPIC_RULES = [
    ("국제·지정학", ["미국", "중국", "일본", "유럽", "러시아", "트럼프", "전쟁", "인도", "브라질", "프랑스", "독일", "영국", "대만", "북한", "이스라엘", "중동", "폴란드", "선거"]),
    ("금융·증시", ["주가", "코스피", "나스닥", "증시", "주식", "시가총액", "투자", "금리", "환율", "채권", "ETF", "개미", "반도체", "삼성전자", "애플", "테슬라", "엔비디아"]),
    ("국내 경제·정책", ["부동산", "집값", "연금", "복지", "세금", "물가", "고용", "취업", "정부", "한국", "국내", "저출산", "인구"]),
    ("사회·문화", ["교육", "대학", "청년", "결혼", "범죄", "사건", "논란", "유행", "문화", "농사", "농민", "의료", "병원"]),
    ("역사·과학·기술", ["역사", "제국", "왕", "전쟁사", "우주", "AI", "인공지능", "로봇", "과학", "기술", "소나무", "기후", "에너지", "원전", "철도", "열차"]),
]


def topic_of(r: dict) -> str:
    # 태그는 채널 공통("경제·주식·투자")이라 변별력이 없다 → 제목만 사용
    text = r.get("title") or ""
    scores = {name: sum(text.count(k) for k in kws) for name, kws in TOPIC_RULES}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "기타"


def sample30(rows: list[dict]) -> pathlib.Path:
    since = (datetime.now(KST) - timedelta(days=365)).strftime("%Y-%m-%d")
    pool = [r for r in rows if r["kind"] == "video" and r["published_kst"] >= since and 900 <= r["duration_sec"] <= 3600 and r["has_transcript"]]
    for r in pool:
        r["topic"] = topic_of(r)
    pool.sort(key=lambda r: r["published_kst"], reverse=True)
    latest = pool[:10]
    rest = [r for r in pool if r not in latest]
    rest_by_views = sorted(rest, key=lambda r: r["view_count"] or 0, reverse=True)
    top = rest_by_views[:10]
    middle_pool = [r for r in rest_by_views[10:]]
    mid_idx = len(middle_pool) // 2
    middle = middle_pool[max(0, mid_idx - 5): mid_idx + 5]
    picks = [("최신", r) for r in latest] + [("고조회", r) for r in top] + [("중간", r) for r in middle]
    out = META / "sample30_syukaworld.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stratum", "video_id", "published_kst", "duration_min", "view_count", "topic", "title"])
        for s, r in picks:
            w.writerow([s, r["video_id"], r["published_kst"], round(r["duration_sec"] / 60, 1), r["view_count"], r["topic"], r["title"]])
    print(f"[sample30] pool={len(pool)} picks={len(picks)} topics={Counter(r['topic'] for _, r in picks)}")
    for s, r in picks:
        print(f"  {s} {r['video_id']} {r['published_kst'][:10]} {r['duration_sec']//60}분 {r['view_count']:>9,} {r['topic']} | {r['title'][:48]}")
    return out


def livemap(rows: list[dict]) -> pathlib.Path:
    tr_rows = list(csv.DictReader(EXPORT_IDX.open(encoding="utf-8"))) if EXPORT_IDX.exists() else []
    api_ids = {r["video_id"] for r in rows}
    lives = [{"video_id": r["video_id"], "published_kst": r["published_kst"], "duration_sec": r["duration_sec"], "title": r["title"], "src": "api"}
             for r in rows if r["duration_sec"] >= 5400]
    for t in tr_rows:
        if t["channel"] == "syuka" and t["video_id"] not in api_ids and int(t["duration_sec"] or 0) >= 5400:
            lives.append({"video_id": t["video_id"], "published_kst": t["upload_at"], "duration_sec": int(t["duration_sec"]), "title": t["title"], "src": "trading_only"})
    lives.sort(key=lambda r: r["published_kst"])
    clips = sorted([r for r in rows if r["kind"] == "video" and 600 <= r["duration_sec"] <= 3600], key=lambda r: r["published_kst"])
    out = META / "live_clip_map_syukaworld.csv"
    n_map = 0
    per_live = Counter()
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["clip_id", "clip_published_kst", "clip_min", "clip_title", "live_id", "live_published_kst", "live_min", "days_after_live", "live_src"])
        for c in clips:
            cd = datetime.strptime(c["published_kst"], "%Y-%m-%d %H:%M")
            prev = [l for l in lives if datetime.strptime(l["published_kst"][:16], "%Y-%m-%d %H:%M") <= cd]
            if not prev:
                continue
            l = prev[-1]
            ld = datetime.strptime(l["published_kst"][:16], "%Y-%m-%d %H:%M")
            days = (cd - ld).days
            if days > 8:
                continue
            w.writerow([c["video_id"], c["published_kst"], round(c["duration_sec"] / 60, 1), c["title"], l["video_id"], l["published_kst"], l["duration_sec"] // 60, days, l["src"]])
            per_live[l["video_id"]] += 1
            n_map += 1
    recent = [l for l in lives if l["published_kst"] >= "2026-01"]
    print(f"[livemap] lives={len(lives)} (api {sum(1 for l in lives if l['src']=='api')}, trading_only {sum(1 for l in lives if l['src']=='trading_only')}) · 2026 lives={len(recent)} · mapped clips={n_map} · clips/live(2026)={statistics.mean([per_live[l['video_id']] for l in recent]) if recent else 0:.1f}")
    for l in recent[-6:]:
        print(f"  {l['video_id']} {l['published_kst'][:16]} {l['duration_sec']//60}분 clips={per_live[l['video_id']]} [{l['src']}] {l['title'][:50]}")
    return out


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "all"
    if cmd in ("all", "catalog"):
        for h in HANDLES:
            rows = load(h)
            c = write_catalog(h, rows)
            o = write_overview(h, rows)
            print(f"[{h}] {len(rows)} rows → {c.relative_to(ROOT)} · {o.relative_to(ROOT)}")
    if cmd in ("all", "sample30"):
        sample30(load("syukaworld"))
    if cmd in ("all", "livemap"):
        livemap(load("syukaworld"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
