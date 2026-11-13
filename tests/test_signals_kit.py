"""화제 엔진 시험의 공용 도구(시험 함수 없음). 임시 수집 DB 를 pulse.store.SCHEMA 로 만들고 지어낸 기사를 넣는다."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from datetime import datetime, timedelta

import yaml

from ozl.pulse import store as pulse_store
from ozl.signals import config

FIX = pathlib.Path(__file__).parent / "fixtures" / "signals"
FEED = {"연합뉴스": "yna_economy", "한국경제": "hk_economy", "매일경제": "mk_economy", "서울경제": "sedaily_economy",
        "머니투데이": "mt_all", "조선일보": "chosun_economy", "동아일보": "donga_economy", "경향신문": "khan_economy",
        "SBS": "sbs_economy"}


def kst(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return (d if d.tzinfo else d.replace(tzinfo=config.KST)).astimezone(config.UTC)


def art(title: str, outlet: str, published: str, summary: str = "", delay_min: int = 10, url: str | None = None,
        kind: str = "news", feed: str | None = None, extra: dict | None = None, lang: str = "ko",
        first_seen: str | None = None) -> dict:
    pub = kst(published)
    seen = kst(first_seen) if first_seen else pub + timedelta(minutes=delay_min)
    return {"title": title, "outlet": outlet, "feed": feed or FEED.get(outlet, "yna_economy"), "kind": kind, "tier": "T3",
            "lang": lang, "published": pub.isoformat(), "undated": 0, "first_seen": seen.isoformat(),
            "summary": summary, "url": url if url is not None else "https://news.example.test/" + hashlib.sha1((outlet + title).encode()).hexdigest()[:12],
            "extra": extra or {}}


def make_pulse(path: pathlib.Path, items: list[dict], runs: list[datetime]) -> pathlib.Path:
    con = sqlite3.connect(path)
    con.executescript(pulse_store.SCHEMA)
    for it in items:
        con.execute("INSERT OR IGNORE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pulse_store.item_key(it), it["title"], it["url"], it["outlet"], it["feed"], it["kind"], it["tier"],
                     it["lang"], it["published"], it["undated"], it["first_seen"], it["summary"],
                     json.dumps(it["extra"], ensure_ascii=False)))
    for r in runs:
        con.execute("INSERT INTO runs (at, n_fetched, n_new, feeds_failed, error) VALUES (?,?,?,?,?)",
                    (r.astimezone(config.UTC).isoformat(), 0, 0, "[]", None))
    con.commit()
    con.close()
    return path


def key_of(it: dict) -> str:
    return pulse_store.item_key(it)


def hourly(start: str, end: str, every_h: int = 1, minute: int = 5) -> list[datetime]:
    t = kst(start).astimezone(config.KST).replace(minute=minute, second=0, microsecond=0)
    out = []
    while t <= kst(end):
        out.append(t.astimezone(config.UTC))
        t += timedelta(hours=every_h)
    return out


def load_gold() -> list[dict]:
    return yaml.safe_load((FIX / "pairs_gold.yaml").read_text(encoding="utf-8"))


def gold_items() -> tuple[list[dict], dict]:
    """정답 60쌍의 기사와 지지 기사 → (수집 항목 목록, 메타: 쌍별 키·라벨)."""
    items, meta = [], {"pairs": [], "labels": {}, "copy_pairs": []}
    for p in load_gold():
        ka = kb = None
        for side in ("a", "b"):
            x = p[side]
            it = art(x["title"], x["outlet"], x["published"], x.get("summary", ""))
            items.append(it)
            k = key_of(it)
            meta["labels"][k] = p["event_" + side]
            if side == "a":
                ka = k
            else:
                kb = k
        for s in p.get("support") or []:
            it = art(s["title"], s["outlet"], s["published"], s.get("summary", ""))
            items.append(it)
            meta["labels"][key_of(it)] = p["event_" + s["for"]]
        meta["pairs"].append({"id": p["id"], "kind": p["kind"], "a_key": ka, "b_key": kb, "same_issue": p["same_issue"]})
        if p.get("same_copy_group"):
            meta["copy_pairs"].append({"id": p["id"], "a_key": ka, "b_key": kb, "b_outlet": p["b"]["outlet"]})
    return items, meta


def unit(title: str, outlet: str, published: str, kind: str = "news", lang: str = "ko", summary: str = "") -> dict:
    """분석까지 마친 단위(엔진 안쪽 자료 꼴). 수집 DB 없이 묶기·잇기를 시험할 때 쓴다."""
    from ozl.signals import text
    pub = kst(published)
    a = {"key": f"{outlet}|{title}", "title": title, "url": "", "canon": None, "outlet": outlet, "family": outlet,
         "feed": "x", "section": "", "kind": kind, "lang": lang, "summary": summary, "extra": {}, "event_at": pub,
         "received_at": pub + timedelta(minutes=5), "undated": 0, "day": config.kst_day(pub)}
    a.update(text.analyze(title, lang))
    return a


def groups(units: list[dict], day: str) -> list[dict]:
    from ozl.signals import cluster
    return cluster.group_day(units, day)
