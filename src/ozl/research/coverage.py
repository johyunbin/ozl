#!/usr/bin/env python3
"""슈카월드 기존 커버리지 대조 — "이미 다룬 소재인가"를 제목·전사에서 찾는다.

    python -m ozl.research coverage 엔비디아 "젠슨 황"            # 제목에 낱말이 든 영상(최근 24개월)
    python -m ozl.research coverage 관세 --fulltext --months 12   # 전사 본문에 나온 횟수까지
    python -m ozl.research coverage 코스피 --fulltext --asof 2026-11-10T07:30   # 그 시각에 있던 영상만(지난 회차 다시 보기)

--fulltext 는 기준 시각에서 14일 안에 올라온 영상 가운데 전사가 없는 것도 따로 찍는다 — 그런 영상과 닿는 소재는
"겹침 없음"이 아니라 "판정 못 함"이다(절차서 §1 3단계). 최신 업로드 목록은 짧은 영상을 가르는 칸이 없어 섞여 나온다.

읽는 것(전부 비공개): private/meta/catalog_syukaworld.csv · private/desk/latest_uploads.json(수집기가 받은 최신 업로드) ·
private/transcripts/trading_export/**.json. 전사 문장은 돌려주지 않는다 — 영상 식별자·제목·날짜·횟수만.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
CATALOG = ROOT / "private" / "meta" / "catalog_syukaworld.csv"
LATEST = ROOT / "private" / "desk" / "latest_uploads.json"
EXPORT = ROOT / "private" / "transcripts" / "trading_export"
INDEX = EXPORT / "index.csv"                       # 전사 반출 색인 — 일요 생방송 전체본도 여기에만 있다
TRADING = pathlib.Path.home() / "Trading"          # 전사가 생긴 시각을 볼 때만 읽는다(쓰지 않는다)
SHORT_SEC = 180                                    # 이 길이 이하는 짧은 영상(대개 발췌)
KST = timezone(timedelta(hours=9))

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


def _now() -> datetime:
    """지금(KST · naive) — 실행 환경의 시간대와 무관하게 견주려고(2026-11-13 Codex 지적)."""
    return datetime.now(KST).replace(tzinfo=None)


def _space_free(s: str) -> str:
    """띄어쓰기를 무시하고 찾으려고 — '데이터 센터'와 '데이터센터'를 같은 낱말로 센다."""
    return re.sub(r"\s+", "", (s or "").lower())


def load_catalog() -> list[dict]:
    """영상 목록 CSV + 전사 반출 색인(syuka 채널) + 최신 업로드를 합쳐 최신순으로. 읽지 못하면 예외를 그대로 올린다.
    - CSV 가 정본이다(제목·시각·길이). 짧은 영상(kind=short)은 뺀다.
    - 전사 반출 색인은 CSV 에 없는 영상(일요 생방송 전체본 · CSV 갱신 뒤 올라온 영상)을 채우고, 생방송 여부(live)를 붙인다.
      제목은 CSV 에 없을 때만 쓴다(색인의 제목은 나중에 바뀐 것일 수 있다).
    - 최신 업로드 목록은 날짜만 있고 짧은 영상인지 알 수 없다(kind_unknown).
    short = 길이를 아는 영상 가운데 SHORT_SEC 이하(대개 본편·생방송의 발췌)."""
    rows: dict[str, dict] = {}
    excluded: set[str] = set()   # CSV 가 짧은 영상(short)으로 뺀 것 — 색인·최신 목록이 되살리지 못하게
    with CATALOG.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("kind") == "short":
                excluded.add(r["video_id"])
                continue
            rows[r["video_id"]] = {"video_id": r["video_id"], "title": r["title"], "date": r["published_kst"][:10],
                                   "published": r["published_kst"][:16], "duration_sec": int(r.get("duration_sec") or 0), "live": False}
    if INDEX.exists():
        with INDEX.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("channel") != "syuka" or not r.get("upload_at") or r["video_id"] in excluded:
                    continue
                live = r.get("is_live_full") == "1"
                if r["video_id"] in rows:
                    rows[r["video_id"]]["live"] = rows[r["video_id"]]["live"] or live
                    continue
                rows[r["video_id"]] = {"video_id": r["video_id"], "title": r["title"], "date": r["upload_at"][:10],
                                       "published": r["upload_at"][:16], "duration_sec": int(r.get("duration_sec") or 0), "live": live}
    if LATEST.exists():
        for r in json.loads(LATEST.read_text(encoding="utf-8")).get("videos", []):
            if r["video_id"] in excluded:
                continue
            rows.setdefault(r["video_id"], {"video_id": r["video_id"], "title": r["title"], "date": r["date"],
                                            "published": r["date"], "duration_sec": 0, "live": False, "kind_unknown": True})
    for r in rows.values():
        r["short"] = 0 < r["duration_sec"] <= SHORT_SEC
    return sorted(rows.values(), key=lambda r: str(r.get("published") or r["date"]), reverse=True)


def _born_ts(p: pathlib.Path) -> float:
    """파일이 생긴 시각(epoch 초) — macOS 는 st_birthtime, 없으면 st_mtime."""
    st = p.stat()
    return getattr(st, "st_birthtime", None) or st.st_mtime


def transcript_ready_at(j: dict) -> datetime | None:
    """전사가 생긴 시각(KST 기준 naive) — Trading 쪽 전사 파일이 생긴 시각(st_birthtime). 그 파일이 없으면 OZL 로 반출한 시각.
    실측(11-13 · 9월 15일 뒤 59편): 업로드에서 전사까지 중앙 0.3시간 · 최대 10.8시간 — 그래서 지난 회차를 다시 볼 때는
    '영상이 있었다'와 '전사가 있었다'를 따로 본다."""
    p = TRADING / str(j.get("trading_md_path") or "")
    if j.get("trading_md_path") and p.exists():
        return datetime.fromtimestamp(_born_ts(p), KST).replace(tzinfo=None)   # 실행 환경의 시간대와 무관하게 KST
    ex = j.get("exported_at")
    if ex:
        try:
            return datetime.fromisoformat(str(ex)).astimezone(KST).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _ready_by(j: dict, asof: str | None) -> bool:
    """기준 시각에 그 전사가 있었는가. 생성 시각을 알 수 없으면 '있었다'고 하지 않는다(그때의 대조에서 빼고 전사 없음으로 친다)."""
    if not asof:
        return True
    t = transcript_ready_at(j)
    return t is not None and t <= datetime.strptime(_asof_key(asof), "%Y-%m-%d %H:%M")


def _load_transcript(f: pathlib.Path) -> dict | None:
    """전사 JSON 을 읽는다. 못 읽거나 text 가 글이 아니면 None — search 와 untranscribed 가 같은 기준을 쓴다."""
    try:
        j = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return j if isinstance(j, dict) and isinstance(j.get("text"), str) else None


def _asof_key(asof: str) -> str:
    """'2026-11-10T07:30' · '2026-11-10 07:30' · '2026-11-10' → 'YYYY-MM-DD HH:MM'(날짜만이면 그날 00:00)."""
    s = asof.strip().replace("T", " ")
    try:
        dt = datetime.strptime(s[:16], "%Y-%m-%d %H:%M") if len(s) > 10 else datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"기준 시각 형식 오류: {asof!r} — 2026-11-10T07:30 꼴") from e
    return dt.strftime("%Y-%m-%d %H:%M")


def existed_at(r: dict, asof: str | None) -> bool:
    """그 시각에 이미 올라와 있던 영상인가. 시각을 모르는 영상(최신 업로드 목록은 날짜만)은 그날 것을 빼고 전날까지만 넣는다 —
    지난 회차를 다시 볼 때 나중에 올라온 영상이 섞이지 않게(그날 이른 시각 영상을 놓치는 쪽을 택한다)."""
    if not asof:
        return True
    key = _asof_key(asof)
    pub = str(r.get("published") or r["date"])
    if len(pub) > 10:
        return pub[:16].replace("T", " ") <= key
    return pub[:10] < key[:10]


def search(keywords: list[str], months: int = 24, fulltext: bool = False, today: str | None = None, catalog: list[dict] | None = None,
           stats: dict | None = None, asof: str | None = None) -> list[dict]:
    """낱말 중 하나라도 제목에 든 영상. fulltext 면 전사 본문 등장 횟수(body_hits)도 센다 — 1회 이상이면 결과에 넣는다.
    낱말과 제목·본문은 띄어쓰기를 무시하고 견준다. 생방송 전체본도 훑는다(live).
    stats 를 넘기면 읽지 못한 전사 수(unreadable)·훑은 편수(scanned)·그때 아직 없던 전사(not_ready)를 채워 준다.
    asof('2026-11-10T07:30')를 주면 그 시각 뒤에 올라온 영상과 그 시각에 아직 없던 전사는 빼고, 기간도 그날을 끝으로 센다."""
    kws = [_space_free(k) for k in keywords if k.strip()]
    if not kws:
        return []
    cat = load_catalog() if catalog is None else catalog
    if asof:
        today = _asof_key(asof)[:10]
    base = datetime.strptime(today, "%Y-%m-%d") if today else _now()
    since, until = (base - timedelta(days=30.5 * months)).strftime("%Y-%m-%d"), base.strftime("%Y-%m-%d")
    hits: dict[str, dict] = {}
    scanned = unreadable = not_ready = 0
    seen: set[str] = set()
    for r in cat:
        if not since <= r["date"] <= until or not existed_at(r, asof):
            continue
        t = _space_free(r["title"])
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
            if not r or not since <= r["date"] <= until or not existed_at(r, asof):
                continue
            j = _load_transcript(f)
            if j is None:   # 깨진 전사 한 편 때문에 전체 대조를 멈추지는 않되, 못 읽은 수는 센다
                scanned += 1
                unreadable += 1
                continue
            body = _space_free(j["text"])
            if not _ready_by(j, asof):
                not_ready += 1   # 영상은 있었지만 전사는 아직 없었다 — 그때의 대조에서는 '전사 없음'
                continue
            scanned += 1
            seen.add(vid)
            n = sum(body.count(k) for k in kws)
            if n >= 1 or vid in hits:
                hits.setdefault(vid, {**r, "title_hits": [], "body_hits": 0})["body_hits"] = n
        for r in hits.values():   # 제목만 걸리고 (그때) 전사가 없던 영상 — '본문 0회'(안 나옴)와 '전사 없음'(못 봄)을 가른다
            r["no_transcript"] = r["video_id"] not in seen
    if stats is not None:
        stats.update(scanned=scanned, unreadable=unreadable, not_ready=not_ready)
    if fulltext and scanned and unreadable == scanned:
        raise OSError(f"전사 {scanned}편을 하나도 읽지 못했다 — 본문 대조 결과를 '없음'으로 쓰지 않는다")
    return sorted(hits.values(), key=lambda r: (bool(r["title_hits"]), r["body_hits"] if not r["title_hits"] else 0, r["date"]), reverse=True)


def untranscribed(catalog: list[dict] | None = None, asof: str | None = None, days: int = 14,
                  keywords: list[str] | None = None) -> list[dict]:
    """기준 시각에서 days 일 안에 올라온 영상 가운데 (그때) 전사가 없던 것(최신순). keywords 를 주면 제목에 든 낱말을 title_hits 로.
    이런 영상과 제목이 닿는 후보는 겹침을 판정할 수 없다 — 절차서는 최근 2주 안의 본편이면 후보에서 빼고, 짧은 영상(short)은 적기만 한다."""
    cat = load_catalog() if catalog is None else catalog
    end = datetime.strptime(_asof_key(asof), "%Y-%m-%d %H:%M") if asof else _now()
    start = end - timedelta(days=days)
    kws = [_space_free(k) for k in (keywords or []) if k.strip()]
    src = EXPORT / "syuka"
    out = []
    for r in cat:
        pub = str(r.get("published") or r["date"])
        if len(pub) > 10:   # 시각을 아는 영상은 시각까지 견준다
            t = datetime.strptime(pub[:16].replace("T", " "), "%Y-%m-%d %H:%M")
            if not start <= t <= end:
                continue
        elif not start.strftime("%Y-%m-%d") <= pub[:10] <= end.strftime("%Y-%m-%d"):
            continue
        if not existed_at(r, asof):
            continue
        f = src / f"{r['video_id']}.json"
        if f.exists():
            j = _load_transcript(f)   # 못 읽는 전사는 없는 것과 같게 친다(search 와 같은 기준)
            if j is not None and _ready_by(j, asof):
                continue
        out.append({**r, "title_hits": [k for k in kws if k in _space_free(r["title"])]})
    return sorted(out, key=lambda r: str(r.get("published") or r["date"]), reverse=True)


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
    ap.add_argument("--asof", help="이 시각에 있던 영상만(예: 2026-11-10T07:30) — 지난 회차를 다시 볼 때")
    a = ap.parse_args(argv)
    st: dict = {}
    try:
        rows = search(a.keywords, a.months, a.fulltext, stats=st, asof=a.asof)
    except ValueError as e:
        print(f"[coverage] {e}", file=sys.stderr)
        return 1
    print(f"낱말 {a.keywords} · 최근 {a.months}개월" + (f" · 기준 {_asof_key(a.asof)}" if a.asof else "") + f" · {len(rows)}편"
          + (f" · 전사 {st['scanned']}편 훑음(생방송 전체본 포함)" if a.fulltext else "")
          + (f" · 그때 아직 없던 전사 {st['not_ready']}편" if st.get("not_ready") else ""))
    if st.get("unreadable"):
        print(f"⚠️ 읽지 못한 전사 {st['unreadable']}편 — 본문 대조가 불완전하다")

    def tag(r: dict) -> str:
        return ("[생방송] " if r.get("live") else "") + ("[짧은 영상] " if r.get("short") else "")
    for r in rows:   # 잘라 내지 않는다 — 1~2회만 나온 영상이 같은 질문을 다룬 경우가 있다(11-13 시험)
        body = (" · 전사 없음(본문 대조 못 함)" if r.get("no_transcript") else f" · 본문 {r['body_hits']}회") if a.fulltext else ""
        print(f"- {r.get('published') or r['date']} {r['video_id']} {tag(r)}{r['title']}{body}")
    if a.fulltext:
        miss = untranscribed(asof=a.asof, keywords=a.keywords)
        if miss:
            near = [r for r in miss if r["title_hits"]]
            print(f"전사 없는 최근 영상(기준에서 14일 안) {len(miss)}편 — 제목에 낱말이 든 것 {len(near)}편 · 이 영상들과는 겹침을 판정하지 못한다"
                  f"(본편이면 후보에서 빼고, 짧은 영상은 적기만 한다 — 절차서 §1 3단계)")
            for r in miss:
                mark = " ← 제목에 낱말" if r["title_hits"] else ""
                kind = " (짧은 영상인지 알 수 없음)" if r.get("kind_unknown") else ""
                print(f"  · {r.get('published') or r['date']} {r['video_id']} {tag(r)}{r['title']}{kind}{mark}")
    return 0
