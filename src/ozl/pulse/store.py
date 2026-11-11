"""Pulse 저장소 — SQLite 한 파일(private/pulse/pulse.db). 제목·링크·매체·시각만 둔다(본문·전사 없음).

시각은 전부 UTC ISO 문자열. 항목 키는 (매체, 정규화한 제목) — 같은 매체가 같은 제목을 다시 내면 한 건.
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[3]
PULSE = ROOT / "private" / "pulse"
DB = PULSE / "pulse.db"
# items.extra 에 두는 칸 — 급상승어의 검색량·딸린 기사 제목, 커뮤니티 목록의 소스·순위·추천/조회/댓글 수·정치 게시판 표시
EXTRA = ("traffic", "trend_news", "source", "rank", "votes", "views", "comments", "politics")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, n_fetched INTEGER, n_new INTEGER,
  feeds_failed TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS items (
  key TEXT PRIMARY KEY, title TEXT, url TEXT, outlet TEXT, feed TEXT, kind TEXT, tier TEXT, lang TEXT,
  published TEXT, undated INTEGER, first_seen TEXT, summary TEXT, extra TEXT);
CREATE INDEX IF NOT EXISTS items_seen ON items(first_seen);
CREATE TABLE IF NOT EXISTS topics (
  topic_id INTEGER PRIMARY KEY AUTOINCREMENT, lang TEXT, seed_tok TEXT, title TEXT, first_seen TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS topic_hours (
  topic_id INTEGER, run_id INTEGER, rank INTEGER, score REAL, n_items INTEGER, n_outlets INTEGER,
  recent_1h INTEGER, signals TEXT, PRIMARY KEY (topic_id, run_id));
"""


def connect(path: pathlib.Path | None = None) -> sqlite3.Connection:
    path = path or DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")   # 웹 서버의 읽기 전용 연결이 쓰기 도중·중단 뒤에도 읽을 수 있게
    con.executescript(SCHEMA)
    return con


def item_key(it: dict) -> str:
    return it["outlet"] + "|" + re.sub(r"\W+", "", it["title"].lower())


def add_items(con: sqlite3.Connection, items: list[dict], now: datetime) -> int:
    """새 항목만 넣고 넣은 수를 돌려준다. 이미 있던 항목의 first_seen 은 바꾸지 않는다."""
    n = 0
    for it in items:
        cur = con.execute(
            "INSERT OR IGNORE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_key(it), it["title"], it.get("url", ""), it["outlet"], it["feed"], it["kind"], it["tier"], it["lang"],
             it["published"], int(bool(it.get("undated"))), now.isoformat(), it.get("summary", ""),
             json.dumps({k: it[k] for k in EXTRA if k in it}, ensure_ascii=False)))
        n += cur.rowcount
    return n


def window_items(con: sqlite3.Connection, now: datetime, hours: float) -> list[dict]:
    """최근 hours 시간 항목. 발행 시각이 없는 피드는 처음 본 시각으로 잰다."""
    since = (now - timedelta(hours=hours)).isoformat()
    rows = con.execute("SELECT * FROM items WHERE (undated=0 AND published>=?) OR (undated=1 AND first_seen>=?)",
                       (since, since)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["undated"] = bool(d["undated"])
        d.update(json.loads(d.pop("extra") or "{}"))   # EXTRA 칸
        d["ts"] = d["first_seen"] if d["undated"] else d["published"]
        out.append(d)
    return out


def active_topics(con: sqlite3.Connection, now: datetime, hours: float = 24) -> list[dict]:
    since = (now - timedelta(hours=hours)).isoformat()
    return [{**dict(r), "seed_tok": set(json.loads(r["seed_tok"]))}
            for r in con.execute("SELECT * FROM topics WHERE last_seen>=?", (since,)).fetchall()]


def new_topic(con: sqlite3.Connection, lang: str, seed: set[str], title: str, now: datetime) -> int:
    cur = con.execute("INSERT INTO topics (lang, seed_tok, title, first_seen, last_seen) VALUES (?,?,?,?,?)",
                      (lang, json.dumps(sorted(seed), ensure_ascii=False), title, now.isoformat(), now.isoformat()))
    return cur.lastrowid


def touch_topic(con: sqlite3.Connection, topic_id: int, title: str, now: datetime) -> None:
    con.execute("UPDATE topics SET title=?, last_seen=? WHERE topic_id=?", (title, now.isoformat(), topic_id))


def prev_ranks(con: sqlite3.Connection, run_id: int) -> dict[int, int]:
    """직전 실행(run_id 바로 앞)의 주제별 순위."""
    r = con.execute("SELECT MAX(run_id) FROM runs WHERE run_id<? AND error IS NULL", (run_id,)).fetchone()[0]
    if r is None:
        return {}
    return {row["topic_id"]: row["rank"] for row in con.execute("SELECT topic_id, rank FROM topic_hours WHERE run_id=?", (r,))}


def history(con: sqlite3.Connection, topic_id: int, now: datetime, hours: float = 24) -> list[dict]:
    since = (now - timedelta(hours=hours)).isoformat()
    rows = con.execute("SELECT r.at, h.rank, h.score, h.n_items, h.n_outlets, h.recent_1h FROM topic_hours h "
                       "JOIN runs r USING(run_id) WHERE h.topic_id=? AND r.at>=? ORDER BY r.at", (topic_id, since)).fetchall()
    return [dict(r) for r in rows]


def prune(con: sqlite3.Connection, now: datetime, days: int = 90) -> dict:
    since = (now - timedelta(days=days)).isoformat()
    n_items = con.execute("DELETE FROM items WHERE first_seen<?", (since,)).rowcount
    old_runs = [r[0] for r in con.execute("SELECT run_id FROM runs WHERE at<?", (since,))]
    con.executemany("DELETE FROM topic_hours WHERE run_id=?", [(r,) for r in old_runs])
    con.execute("DELETE FROM runs WHERE at<?", (since,))
    n_topics = con.execute("DELETE FROM topics WHERE last_seen<?", (since,)).rowcount
    con.commit()
    return {"items": n_items, "runs": len(old_runs), "topics": n_topics}
