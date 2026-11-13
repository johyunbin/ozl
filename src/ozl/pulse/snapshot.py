"""매시 실행 한 번 — 피드 수집 → 저장 → 최근 6시간 묶음 → 주제 추적 → 신호·점수 → now.json.

    python -m ozl.pulse run            # 수집하고 private/pulse/out/now.json 을 새로 쓴다
    python -m ozl.pulse run --no-fetch # 수집 없이 저장된 항목으로만 다시 계산(점검용)
    python -m ozl.pulse run --community # 회차(하루 2회) — 피드에 더해 국내 커뮤니티 인기글·실시간 검색어(community.py)도 받는다

피드가 전부 실패하면 now.json 을 덮지 않고 실패한 실행만 기록한다(이전 화면이 남는다).
산출은 비공개다 — 검증 전 신호이고, 공개 문서에 옮기지 않는다.
"""
from __future__ import annotations

import concurrent.futures as cf
import fcntl
import json
import os
import pathlib
import re
from datetime import datetime, timedelta, timezone

from ..research import collect, coverage, sensitive
from . import community as community_mod
from . import rank, signals, store

WINDOW_H = 6.0
TOP = 30
OUT = store.PULSE / "out"


def fetch_all(now: datetime) -> tuple[list[dict], list[dict]]:
    cfg = collect.load_config()
    feeds = [f for f in cfg["feeds"] if f.get("enabled", True)]
    items, statuses = [], []
    with cf.ThreadPoolExecutor(8) as ex:
        for got, st in ex.map(lambda f: collect.fetch_feed(f, now), feeds):
            items += got
            statuses.append(st)
    return items, statuses


def link_overlap(c: dict, seed: set[str]) -> int:
    """묶음의 기사 하나하나를 주제 seed 와 견주어 조건을 넘는 가장 큰 겹침(없으면 0).
    묶음 낱말 합집합과 견주면 기사가 많은 묶음이 낱말 몇 개 걸쳐서 남의 주제를 가져간다.
    조건: 겹침 ≥ need(짧은 쪽 길이, 최소 2 · 최대 3) 이고 짧은 쪽의 절반 이상."""
    best = 0
    for it in c["items"]:
        t = it.get("_tok") or set()
        if t and t == seed:   # 낱말이 하나·둘뿐인 같은 제목("SQLite")은 겹침 기준과 무관하게 같은 주제
            best = max(best, len(t))
            continue
        ov = len(t & seed)
        short = min(len(t), len(seed))
        if ov >= max(2, min(3, short)) and ov >= 0.5 * short:
            best = max(best, ov)
    return best


def match_topics(clusters: list[dict], topics: list[dict]) -> list[int | None]:
    """묶음마다 이어 붙일 기존 주제(없으면 None). 가능한 (묶음, 주제) 쌍 전부를 겹침 큰 순으로 짝짓는다 —
    한 주제는 한 묶음에만, 한 묶음은 한 주제에만."""
    pairs = []
    for i, c in enumerate(clusters):
        for t in topics:
            if t["lang"] != c["lang"]:
                continue
            ov = link_overlap(c, t["seed_tok"])
            if ov:
                pairs.append((ov, -len(c["items"]), i, t["topic_id"]))
    out: list[int | None] = [None] * len(clusters)
    taken: set[int] = set()
    for ov, _, i, tid in sorted(pairs, reverse=True):
        if out[i] is None and tid not in taken:
            out[i] = tid
            taken.add(tid)
    return out


def worth_tracking(c: dict, sig: dict[str, float]) -> bool:
    """한 매체 기사 하나짜리 묶음은 주제로 등록하지 않는다(다음 시각에 커지면 그때 등록). 보도 말고 다른 신호가 켜졌으면 등록."""
    outlets = {i["outlet"] for i in c["items"] if i["kind"] in signals.NEWS_KINDS}
    return len(outlets) >= 2 or any(v >= rank.ON for k, v in sig.items() if k != "volume")


def lead_item(c: dict) -> dict:
    """대표 기사 — 묶음의 첫 항목(collect.cluster 가 티어·최신순으로 seed 를 고른다)."""
    return c["items"][0]


NOISE = re.compile(r"^\s*\[(부고|인사|부음|포토|사진|오늘의 운세|게시판|알림)\]|이 시각 헤드라인|\(YC [A-Z]\d+\) is hiring|^\s*\[?(속보|단독)\]?\s*$")


def score_clusters(window: list[dict], trends: list[dict], youtube: list[dict], events: list[dict], now: datetime) -> list[dict]:
    """창 안 항목 → 점수 매긴 묶음(추적할 것만). DB 와 무관한 순수 계산이라 테스트가 직접 부른다.
    부고·인사·사진·헤드라인 모음 같은 정례 기사는 묶기 전에 뺀다."""
    scored = []
    body = [i for i in window if i["kind"] != "trend" and not NOISE.search(i["title"])]
    for c in collect.cluster(body):
        tok, lang = c["tok"], c["lang"]
        s_v, r_v, vol = signals.volume_signal(c["items"], now)
        s_s, r_s, hits = signals.search_signal(tok, lang, trends)
        s_c, r_c = signals.community_signal(c["items"], tok, lang, youtube)
        s_o, r_o = signals.official_signal(c["items"], tok, lang, events, now)
        sig = {"search": s_s, "volume": s_v, "community": s_c, "official": s_o}
        if not worth_tracking(c, sig):
            continue
        score, on = rank.combine(sig)
        reasons = r_s + r_v + r_o + r_c
        if vol["n_outlets"] < 2 and score > rank.SINGLE_CAP:   # 기사 한 곳짜리는 검색·커뮤니티가 세도 여러 매체가 다룬 주제 위로 못 오게
            score = rank.SINGLE_CAP
            reasons.append(f"매체 1곳 — 점수 상한 {rank.SINGLE_CAP}")
        scored.append({"c": c, "signals": sig, "on": on, "score": score, "volume": vol,
                       "reasons": reasons, "trend_hits": [t["title"] for t in hits]})
    return scored


def official_new(window: list[dict], now: datetime, hours: float = 3) -> list[dict]:
    """최근 몇 시간 안에 나온 기관 원문(보도가 붙었든 아니든) — 순위와 따로 보여 주는 "기관 발표" 목록."""
    since = (now - timedelta(hours=hours)).isoformat()
    rows = [i for i in window if i["kind"] == "official" and i["ts"] >= since]
    return [{"title": i["title"], "url": i["url"], "outlet": i["outlet"], "tier": i["tier"], "ts": i["ts"]}
            for i in sorted(rows, key=lambda i: i["ts"], reverse=True)]


def run(fetch: bool = True, now: datetime | None = None, db: pathlib.Path | None = None,
        out_dir: pathlib.Path | None = None, youtube: list[dict] | None = None, community: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    out_dir = out_dir or OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    lock = open(out_dir / "run.lock", "w")
    try:   # 예약 실행과 수동 실행이 겹치면 나중 것은 그냥 멈춘다
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return {"ok": False, "error": "다른 실행이 진행 중"}
    try:
        return _run(fetch, now, db, out_dir, youtube, community)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def _run(fetch: bool, now: datetime, db, out_dir: pathlib.Path, youtube, community: bool = False) -> dict:
    con = store.connect(db)
    statuses, fetched, trends_now = [], [], []
    comm_st: list[dict] = []
    yt: list[dict] = youtube or []
    if fetch:
        fetched, statuses = fetch_all(now)
        if community:   # 회차 호출에서만 — 소스당 요청 1회
            got, comm_st = community_mod.fetch_all(now)
            fetched += got
            statuses += comm_st
        if youtube is None:
            yt, yt_st = signals.fetch_youtube(now)
            statuses.append(yt_st)
    failed = [s for s in statuses if s.get("error") and s.get("enabled", True)]
    if fetch and not any(i["kind"] in signals.NEWS_KINDS for i in fetched):   # 트렌드·커뮤니티만 살아 있으면 덮지 않는다
        con.execute("INSERT INTO runs (at, n_fetched, n_new, feeds_failed, error) VALUES (?,?,?,?,?)",
                    (now.isoformat(), 0, 0, json.dumps(failed, ensure_ascii=False), "뉴스·기관 항목 0개 — now.json 유지"))
        con.commit()
        return {"ok": False, "error": "뉴스·기관 항목 0개", "failed": failed, "community": comm_st}

    n_new = store.add_items(con, fetched, now)
    con.commit()   # 받은 기사는 먼저 남긴다. 아래 순위 계산·발행은 한 덩어리 — now.json 을 못 쓰면 실행 기록째 되돌린다
    cur = con.execute("INSERT INTO runs (at, n_fetched, n_new, feeds_failed, error) VALUES (?,?,?,?,NULL)",
                      (now.isoformat(), len(fetched), n_new, json.dumps(failed, ensure_ascii=False)))
    run_id = cur.lastrowid

    # 급상승어는 이번 수집분이 기준(지난 시각 급상승어는 지금 뜨는 것이 아니다). --no-fetch 면 최근 2시간 저장분.
    off = community_mod.off_feeds()   # 꺼 둔 소스에서 전에 받아 둔 항목은 점수와 화면에 쓰지 않는다
    trends_now = [i for i in fetched if i["kind"] == "trend"] if fetch else \
        [i for i in store.window_items(con, now, 2) if i["kind"] == "trend" and i.get("feed") not in off]
    window = [i for i in store.window_items(con, now, WINDOW_H) if i.get("feed") not in off]
    scored = score_clusters(window, trends_now, yt, signals.load_calendar(), now)

    topic_ids = match_topics([s["c"] for s in scored], store.active_topics(con, now))
    for s, tid in zip(scored, topic_ids):
        title = lead_item(s["c"])["title"]
        if tid is None:
            tid = store.new_topic(con, s["c"]["lang"], s["c"]["seed_tok"], title, now)
        else:
            store.touch_topic(con, tid, title, now)
        s["topic_id"] = tid

    scored.sort(key=lambda s: s["score"], reverse=True)
    prev = store.prev_ranks(con, run_id)
    for rnk, s in enumerate(scored, 1):
        s["rank"] = rnk
        con.execute("INSERT INTO topic_hours VALUES (?,?,?,?,?,?,?,?)",
                    (s["topic_id"], run_id, rnk, s["score"], len(s["c"]["items"]), s["volume"]["n_outlets"],
                     s["volume"]["recent_1h"], json.dumps(s["signals"])))

    try:
        catalog = coverage.load_catalog()
    except Exception:  # noqa: BLE001 — 커버리지는 표시용. 못 읽으면 None(겹침 없음과 구분)
        catalog = None
    date = now.astimezone(collect.KST).strftime("%Y-%m-%d")
    topics = []
    for s in scored[:TOP]:
        c = s["c"]
        row = con.execute("SELECT first_seen FROM topics WHERE topic_id=?", (s["topic_id"],)).fetchone()
        topics.append({
            "topic_id": s["topic_id"], "rank": s["rank"], "move": rank.movement(s["rank"], prev.get(s["topic_id"])),
            "title": lead_item(c)["title"], "lang": c["lang"], "score": s["score"], "signals": s["signals"],
            "on": [rank.LABELS[k] for k in s["on"]], "reasons": s["reasons"], "trend_hits": s["trend_hits"],
            "n_items": len(c["items"]), **s["volume"], "first_seen": row["first_seen"],
            "outlets": sorted({i["outlet"] for i in c["items"]}),
            "sensitivity": sensitive.worst([sensitive.classify(f"{i['title']} {i.get('summary', '')}") for i in c["items"]]),
            "coverage_recent": (coverage.recent_overlap(c["tok"], catalog, date) if c["lang"] == "ko" else []) if catalog is not None else None,
            "items": [{"title": i["title"], "url": i["url"], "outlet": i["outlet"], "kind": i["kind"], "tier": i["tier"], "ts": i["ts"],
                       **{k: i[k] for k in ("source", "votes", "views", "comments", "politics") if k in i}}
                      for i in sorted(c["items"], key=lambda i: i["ts"], reverse=True)[:10]],
        })
    matched = {t: s["topic_id"] for s in scored for t in s["trend_hits"]}
    data = {
        "generated_at": now.astimezone(collect.KST).isoformat(), "run_id": run_id, "window_hours": WINDOW_H,
        "n_fetched": len(fetched), "n_new": n_new, "n_window": len(window), "n_topics": len(scored),
        "feeds_failed": failed, "signal_status": {"youtube": "켜짐" if any(s["id"] == "youtube_popular_kr" and not s.get("error") for s in statuses) else "꺼짐"},
        "note": "검증 전 신호다. 점수는 순위용이고 사실 여부와 무관하다.",
        "topics": topics,
        "official_new": official_new(window, now),
        "searches": [{"title": t["title"], "lang": t["lang"], "traffic": t.get("traffic", ""), "news": t.get("trend_news", ""),
                      "topic_id": matched.get(t["title"]), "source": t.get("source", "google"), "rank": t.get("rank"),
                      "sensitivity": sensitive.classify(f"{t['title']} {t.get('trend_news', '')}")} for t in trends_now],
    }
    tmp = out_dir / f"now.json.{os.getpid()}.tmp"
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, out_dir / "now.json")   # 읽는 쪽(웹·앱)이 반쯤 쓴 파일을 보지 않게
    except Exception:
        con.rollback()   # 발행하지 못한 순위는 다음 실행의 등락 기준이 되지 않게
        tmp.unlink(missing_ok=True)
        raise
    con.commit()
    return {"ok": True, "run_id": run_id, "n_fetched": len(fetched), "n_new": n_new, "n_topics": len(scored),
            "failed": len(failed), "path": str(out_dir / "now.json"), "community": comm_st}
