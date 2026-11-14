"""3판 자료의 DB 표(`private/syuka/syuka.db` 안, 기존 videos·records·merged 표는 그대로 둔다).

표: v3_videos(영상) · v3_segments(토막) · v3_claims · v3_stages · v3_names(인물, 기관, 나라 — 맞춘 표기와 원래 표기)
· v3_keywords · v3_followups. 원본 JSON 은 v3_videos.json 에 그대로 둔다.
한 영상을 다시 넣으면 그 영상의 행을 모두 지우고 새로 넣는다(같은 파일을 몇 번 넣어도 행 수가 같다).
"""
from __future__ import annotations

import json
import sqlite3

from . import names
from .db import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS v3_videos(
  video_id TEXT PRIMARY KEY, model TEXT NOT NULL, n_segments INTEGER NOT NULL, summary TEXT NOT NULL,
  ad_disclosure TEXT NOT NULL, seconds REAL NOT NULL, read_to_end INTEGER NOT NULL, transcript_chars INTEGER,
  notes TEXT, json TEXT NOT NULL, loaded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v3_segments(
  video_id TEXT NOT NULL, seg INTEGER NOT NULL,
  start_char INTEGER, end_char INTEGER, start_sec REAL, end_sec REAL,
  topic_line TEXT NOT NULL, question TEXT NOT NULL, field TEXT NOT NULL, field2 TEXT, intro_style TEXT NOT NULL,
  main_person TEXT, main_person_key TEXT, main_org TEXT, main_org_key TEXT,
  korea_level TEXT, korea_line TEXT, core_start TEXT, core_end TEXT, background_years TEXT,
  story_devices TEXT, source_types TEXT, sensitive TEXT, sponsored_level TEXT, sponsored_line TEXT,
  evergreen TEXT, notes TEXT,
  PRIMARY KEY(video_id, seg));
CREATE TABLE IF NOT EXISTS v3_claims(
  video_id TEXT NOT NULL, seg INTEGER NOT NULL, i INTEGER NOT NULL,
  point TEXT NOT NULL, value TEXT, unit TEXT, as_of TEXT, PRIMARY KEY(video_id, seg, i));
CREATE TABLE IF NOT EXISTS v3_stages(
  video_id TEXT NOT NULL, seg INTEGER NOT NULL, i INTEGER NOT NULL,
  role TEXT NOT NULL, line TEXT NOT NULL, PRIMARY KEY(video_id, seg, i));
CREATE TABLE IF NOT EXISTS v3_names(
  video_id TEXT NOT NULL, seg INTEGER NOT NULL, kind TEXT NOT NULL, i INTEGER NOT NULL,
  raw TEXT NOT NULL, name_key TEXT NOT NULL, display TEXT NOT NULL, is_main INTEGER NOT NULL,
  PRIMARY KEY(video_id, seg, kind, i));
CREATE TABLE IF NOT EXISTS v3_keywords(
  video_id TEXT NOT NULL, seg INTEGER NOT NULL, i INTEGER NOT NULL, keyword TEXT NOT NULL,
  PRIMARY KEY(video_id, seg, i));
CREATE TABLE IF NOT EXISTS v3_followups(
  video_id TEXT NOT NULL, seg INTEGER NOT NULL, i INTEGER NOT NULL,
  metric TEXT NOT NULL, value_then TEXT, date_then TEXT, why TEXT, PRIMARY KEY(video_id, seg, i));
CREATE INDEX IF NOT EXISTS v3_names_key ON v3_names(name_key);
CREATE INDEX IF NOT EXISTS v3_segments_field ON v3_segments(field);
"""

CHILD_TABLES = ("v3_segments", "v3_claims", "v3_stages", "v3_names", "v3_keywords", "v3_followups")
NAME_KINDS = (("people", "person", "main_person"), ("orgs", "org", "main_org"), ("countries", "country", None))


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def put(con: sqlite3.Connection, doc: dict) -> None:
    """검사를 통과한 3판 파일 한 편을 넣는다(그 영상의 이전 행은 지운다). 한 거래로 묶는다."""
    ensure(con)
    vid = doc["video_id"]
    with con:
        for t in ("v3_videos",) + CHILD_TABLES:
            con.execute(f"DELETE FROM {t} WHERE video_id=?", (vid,))
        con.execute("INSERT INTO v3_videos VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (vid, doc["model"], doc["n_segments"], doc["summary"], doc["ad_disclosure"], doc["seconds"],
                     int(doc["read_to_end"]), doc["transcript_chars"], doc["notes"],
                     json.dumps(doc, ensure_ascii=False, sort_keys=True), now()))
        for s in doc["segments"]:
            n, sp, per = s["seg"], s["span"], s["period"]
            mp = names.person(s["main_person"])[0] if s["main_person"] else None
            mo = names.org(s["main_org"])[0] if s["main_org"] else None
            con.execute(
                "INSERT INTO v3_segments VALUES(" + ",".join("?" * 27) + ")",
                (vid, n, sp.get("start_char"), sp.get("end_char"), sp.get("start_sec"), sp.get("end_sec"),
                 s["topic_line"], s["question"], s["field"], s["field2"], s["intro_style"],
                 s["main_person"], mp, s["main_org"], mo,
                 s["korea_link"]["level"], s["korea_link"]["line"], per["core_start"], per["core_end"],
                 _j(per["background_years"]), _j(s["story_devices"]), _j(s["source_types"]), _j(s["sensitive"]),
                 s["sponsored"]["level"], s["sponsored"]["line"], s["evergreen"], s["notes"]))
            con.executemany("INSERT INTO v3_claims VALUES(?,?,?,?,?,?,?)",
                            [(vid, n, i, c["point"], c["value"], c["unit"], c["as_of"]) for i, c in enumerate(s["claims"])])
            con.executemany("INSERT INTO v3_stages VALUES(?,?,?,?,?)",
                            [(vid, n, i, x["role"], x["line"]) for i, x in enumerate(s["stages"])])
            con.executemany("INSERT INTO v3_keywords VALUES(?,?,?,?)",
                            [(vid, n, i, k) for i, k in enumerate(s["keywords"])])
            con.executemany("INSERT INTO v3_followups VALUES(?,?,?,?,?,?,?)",
                            [(vid, n, i, f["metric"], f["value_then"], f["date_then"], f["why"])
                             for i, f in enumerate(s["followups"])])
            rows = []
            for field, kind, main in NAME_KINDS:
                for i, raw in enumerate(s[field]):
                    k, disp = names.canon(kind, raw)
                    rows.append((vid, n, kind, i, raw, k, disp, int(main is not None and raw == s[main])))
            con.executemany("INSERT INTO v3_names VALUES(?,?,?,?,?,?,?,?)", rows)


def counts(con: sqlite3.Connection) -> dict[str, int]:
    ensure(con)
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("v3_videos",) + CHILD_TABLES}


def find(con: sqlite3.Connection, word: str) -> list[dict]:
    """토막의 주제, 질문, 키워드, 인물, 기관, 나라에서 낱말을 찾는다. 올린 날 순. 이름은 맞춘 표기로도 찾는다."""
    ensure(con)
    w = word.strip()
    if not w:
        return []
    like = f"%{w}%"
    keys = {names.key(w), names.person(w)[0], names.org(w)[0]} - {""}
    kq = ",".join("?" * len(keys)) or "''"
    hits: dict[tuple[str, int], set[str]] = {}

    def add(rows, where):
        for vid, seg in rows:
            hits.setdefault((vid, seg), set()).add(where)

    add(con.execute("SELECT video_id, seg FROM v3_segments WHERE topic_line LIKE ? OR question LIKE ?", (like, like)), "주제")
    add(con.execute("SELECT video_id, seg FROM v3_keywords WHERE keyword LIKE ?", (like,)), "키워드")
    for kind, label in (("person", "인물"), ("org", "기관"), ("country", "나라")):
        add(con.execute(f"SELECT video_id, seg FROM v3_names WHERE kind=? AND (raw LIKE ? OR display LIKE ? "
                        f"OR name_key IN ({kq}))", (kind, like, like, *keys)), label)
    if not hits:
        return []
    out = []
    for (vid, seg), where in hits.items():
        r = con.execute(
            "SELECT s.*, v.title, v.upload_at, v.kind FROM v3_segments s LEFT JOIN videos v USING(video_id) "
            "WHERE s.video_id=? AND s.seg=?", (vid, seg)).fetchone()
        d = dict(r) | {"matched": sorted(where)}
        out.append(d)
    return sorted(out, key=lambda d: (d.get("upload_at") or "", d["video_id"], d["seg"]))
