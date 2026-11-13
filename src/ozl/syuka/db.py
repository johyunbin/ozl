"""영상 자료 DB `private/syuka/syuka.db` (수집 DB `private/pulse/pulse.db` 와 다른 파일).

표: videos(영상 목록) · records(모델별 추출 자료) · merged(두 모델을 합친 최종 자료). 통계 칸은 없다.
같은 입력을 두 번 넣어도 행이 늘지 않는다(기본 키로 덮어쓴다).
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

from .catalog import ROOT

DB_PATH = ROOT / "private" / "syuka" / "syuka.db"
KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos(
  video_id TEXT PRIMARY KEY, title TEXT, upload_at TEXT, duration_sec INTEGER, kind TEXT,
  has_transcript INTEGER, transcript_source TEXT, transcript_path TEXT, chars INTEGER,
  in_uploads INTEGER, in_transcripts INTEGER);
CREATE TABLE IF NOT EXISTS records(
  video_id TEXT NOT NULL, model TEXT NOT NULL, schema_version INTEGER NOT NULL,
  json TEXT NOT NULL, extracted_at TEXT NOT NULL, seconds REAL,
  PRIMARY KEY(video_id, model, schema_version));
CREATE TABLE IF NOT EXISTS merged(
  video_id TEXT NOT NULL, schema_version INTEGER NOT NULL, json TEXT NOT NULL, merged_at TEXT NOT NULL,
  PRIMARY KEY(video_id, schema_version));
CREATE INDEX IF NOT EXISTS videos_kind ON videos(kind, upload_at);
CREATE INDEX IF NOT EXISTS records_model ON records(model, schema_version);
"""

VIDEO_COLS = ("video_id", "title", "upload_at", "duration_sec", "kind", "has_transcript",
              "transcript_source", "transcript_path", "chars", "in_uploads", "in_transcripts")


def now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def connect(path: pathlib.Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def put_videos(con: sqlite3.Connection, rows: list[dict]) -> None:
    sets = ", ".join(f"{c}=excluded.{c}" for c in VIDEO_COLS[1:])
    con.executemany(
        f"INSERT INTO videos({', '.join(VIDEO_COLS)}) VALUES({', '.join('?' * len(VIDEO_COLS))}) "
        f"ON CONFLICT(video_id) DO UPDATE SET {sets}",
        [tuple(r[c] for c in VIDEO_COLS) for r in rows])
    con.commit()


def put_record(con: sqlite3.Connection, video_id: str, model: str, schema_version: int, record: dict,
               seconds: float | None, extracted_at: str | None = None) -> None:
    con.execute(
        "INSERT INTO records VALUES(?,?,?,?,?,?) ON CONFLICT(video_id, model, schema_version) "
        "DO UPDATE SET json=excluded.json, extracted_at=excluded.extracted_at, seconds=excluded.seconds",
        (video_id, model, schema_version, json.dumps(record, ensure_ascii=False, sort_keys=True),
         extracted_at or now(), seconds))
    con.commit()


def put_merged(con: sqlite3.Connection, video_id: str, schema_version: int, record: dict) -> None:
    con.execute(
        "INSERT INTO merged VALUES(?,?,?,?) ON CONFLICT(video_id, schema_version) "
        "DO UPDATE SET json=excluded.json, merged_at=excluded.merged_at",
        (video_id, schema_version, json.dumps(record, ensure_ascii=False, sort_keys=True), now()))
    con.commit()


def video(con: sqlite3.Connection, video_id: str) -> dict | None:
    r = con.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
    return dict(r) if r else None


def records(con: sqlite3.Connection, schema_version: int | None = None) -> list[dict]:
    q, a = "SELECT * FROM records", ()
    if schema_version is not None:
        q, a = q + " WHERE schema_version=?", (schema_version,)
    return [dict(r) | {"record": json.loads(r["json"])} for r in con.execute(q + " ORDER BY video_id, model", a)]
