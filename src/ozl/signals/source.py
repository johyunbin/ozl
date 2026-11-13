"""수집 DB 읽기(읽기 전용). 받은 시각 ≤ asof 인 항목만 읽고, 점수에 넣지 않는 항목을 사유별로 센다(§2-4).

수집 DB 는 file:…?mode=ro 로만 연다. pulse.store.connect() 는 쓰기 모드로 열고 스키마를 실행하므로 부르지 않는다.
"""
from __future__ import annotations

import functools
import json
import pathlib
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta

import yaml

from ozl.signals import config, urls

KINDS = ("news", "official", "trend")
NOISE_HEADS = ("부고", "부음", "인사", "포토", "사진", "게시판", "동정", "표", "오늘의 운세", "쇼츠")
_LEAD = re.compile(r"^\s*\[([^\]]{0,12})\]")


def connect_ro(path: pathlib.Path | str) -> sqlite3.Connection:
    p = pathlib.Path(path).resolve()
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


@functools.lru_cache(maxsize=1)
def feeds_meta() -> dict[str, dict]:
    """feeds.yaml 의 피드 id → {section, outlet, kind, enabled}."""
    from ozl.research import collect
    out = {}
    for f in collect.load_config().get("feeds") or []:
        out[f["id"]] = {"section": f.get("section", ""), "outlet": f.get("outlet", ""), "kind": f.get("kind", ""),
                        "enabled": f.get("enabled", True)}
    return out


@functools.lru_cache(maxsize=1)
def families() -> dict[str, str]:
    doc = yaml.safe_load((config.DATA / "outlet_family.yaml").read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in doc.items()}


def family_of(outlet: str) -> str:
    return families().get(outlet, outlet)


def is_noise(title: str) -> bool:
    t = title or ""
    if "이 시각 헤드라인" in t:
        return True
    m = _LEAD.match(t)
    return bool(m and m.group(1).strip() in NOISE_HEADS)


def _asof_str(asof: datetime) -> str:
    return config.iso_utc(asof)


def load_items(pulse_db: pathlib.Path | str, asof: datetime, scorable=None) -> tuple[list[dict], dict]:
    """받은 시각 ≤ asof 인 항목을 정리해 돌려준다. (항목 목록, 뺀 항목의 사유별 건수).

    항목: key, title, url, canon, outlet, family, feed, section, kind, lang, summary, extra(dict),
          event_at, received_at(datetime UTC), undated, day(KST 날짜 문자열).
    """
    if scorable is None:
        from ozl.research import ledger
        scorable = ledger.scorable()
    meta = feeds_meta()
    con = connect_ro(pulse_db)
    try:
        rows = con.execute("SELECT * FROM items ORDER BY key").fetchall()
    finally:
        con.close()
    cut = asof.astimezone(config.UTC)
    out, ex = [], Counter()
    for r in rows:
        rec = config.parse_ts(r["first_seen"])
        if rec is None or rec > cut:
            continue
        d = dict(r)
        if d["kind"] not in KINDS:
            ex["종류"] += 1
            continue
        if not scorable(d):
            ex["대장"] += 1
            continue
        if is_noise(d["title"]):
            ex["소음 제목"] += 1
            continue
        pub = config.parse_ts(d["published"])
        undated = bool(d["undated"]) or pub is None
        if not undated and pub < rec - timedelta(hours=config.OLD_ITEM_HOURS):
            ex["옛 항목"] += 1
            continue
        ev = rec if undated else pub
        try:
            extra = json.loads(d.get("extra") or "{}")
        except ValueError:
            extra = {}
        out.append({
            "key": d["key"], "title": d["title"] or "", "url": d["url"] or "", "canon": urls.canon_url(d["url"]),
            "outlet": d["outlet"] or "", "family": family_of(d["outlet"] or ""), "feed": d["feed"] or "",
            "section": meta.get(d["feed"], {}).get("section", ""), "kind": d["kind"], "lang": d["lang"] or "ko",
            "summary": d["summary"] or "", "extra": extra, "event_at": ev, "received_at": rec,
            "undated": int(undated), "day": config.kst_day(ev),
        })
    out.sort(key=order_key)
    return out, dict(ex)


def order_key(a: dict):
    """어디서나 같은 처리 순서: (사건 시각, 항목 키)."""
    return (a["event_at"], a["key"])


def runs_until(pulse_db: pathlib.Path | str, asof: datetime) -> list[dict]:
    """at ≤ asof 인 실행 기록, 시각순."""
    con = connect_ro(pulse_db)
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM runs ORDER BY at, run_id")]
    finally:
        con.close()
    cut = asof.astimezone(config.UTC)
    out = []
    for r in rows:
        at = config.parse_ts(r["at"])
        if at is not None and at <= cut:
            r["at_dt"] = at
            out.append(r)
    return out
