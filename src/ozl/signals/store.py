"""engine.db(엔진이 쓰는 유일한 저장소)의 구조와 읽기·쓰기(§8-2). 수집 DB 와 따로 둔다."""
from __future__ import annotations

import json
import pathlib
import sqlite3

from ozl.signals.link import Issue

SCHEMA_VER = "1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS calc_runs (
  calc_id INTEGER PRIMARY KEY AUTOINCREMENT, asof TEXT NOT NULL, decided_at TEXT NOT NULL, mode TEXT NOT NULL,
  rules_ver TEXT, formula_ver TEXT, dict_ver TEXT, ledger_hash TEXT, feeds_hash TEXT, overrides_hash TEXT,
  source_status TEXT, excluded TEXT, late_items INTEGER DEFAULT 0, n_items INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS articles (
  item_key TEXT PRIMARY KEY, dict_ver TEXT, canon_url TEXT, same_url_of TEXT, lang TEXT, kind TEXT, feed TEXT,
  outlet TEXT, family TEXT, section TEXT, event_at TEXT, received_at TEXT, day TEXT, title TEXT, norm_title TEXT,
  norm_summary TEXT, entities TEXT, terms TEXT, person INTEGER, indirect INTEGER, sensitivity TEXT);
CREATE TABLE IF NOT EXISTS copies (item_key TEXT PRIMARY KEY, rep_key TEXT NOT NULL, rule TEXT, dice REAL);
CREATE TABLE IF NOT EXISTS groups (
  group_id TEXT NOT NULL, day TEXT NOT NULL, calc_id INTEGER NOT NULL, final INTEGER NOT NULL DEFAULT 0, lang TEXT,
  seed_key TEXT, members TEXT, copies TEXT, families TEXT, sources TEXT, has_official INTEGER, ent_fam TEXT,
  term_fam TEXT, title TEXT, first_at TEXT, issue_id TEXT, link TEXT, PRIMARY KEY (group_id, calc_id));
CREATE INDEX IF NOT EXISTS groups_day ON groups(day, final);
CREATE INDEX IF NOT EXISTS groups_calc ON groups(calc_id);
CREATE TABLE IF NOT EXISTS final_days (day TEXT PRIMARY KEY, calc_id INTEGER, finalized_at TEXT);
CREATE TABLE IF NOT EXISTS issues (
  issue_id TEXT PRIMARY KEY, lang TEXT, first_day TEXT, minted_at TEXT, minted_calc INTEGER, seed_key TEXT, title TEXT,
  state_override TEXT, status TEXT DEFAULT 'active', split_of TEXT, override_sig TEXT);
CREATE TABLE IF NOT EXISTS issue_aliases (old_id TEXT, new_id TEXT, at TEXT, reason TEXT, PRIMARY KEY (old_id, new_id));
CREATE TABLE IF NOT EXISTS issue_history (issue_id TEXT, at TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS issue_trends (
  issue_id TEXT, day TEXT, calc_id INTEGER, trend_key TEXT, keyword TEXT, traffic_raw TEXT, grade REAL, matched_article TEXT);
CREATE TABLE IF NOT EXISTS issue_followups (issue_id TEXT, day TEXT, unit_id TEXT, seed_key TEXT, families TEXT, new_terms TEXT);
CREATE TABLE IF NOT EXISTS issue_entities (issue_id TEXT, entity TEXT, first_day TEXT, families TEXT, PRIMARY KEY (issue_id, entity));
CREATE TABLE IF NOT EXISTS issue_days (
  issue_id TEXT, day TEXT, calc_id INTEGER, final INTEGER DEFAULT 0, A INTEGER, g REAL, w REAL, v REAL, H REAL, B REAL,
  P REAL, D REAL, f_new INTEGER, e_new INTEGER, score_raw REAL, score INTEGER, state TEXT, kinds_present TEXT,
  kinds_ok TEXT, missing TEXT, category TEXT, sensitivity TEXT, person INTEGER, indirect_n INTEGER, articles_n INTEGER,
  copies_n INTEGER, detail TEXT, PRIMARY KEY (issue_id, day, calc_id));
CREATE INDEX IF NOT EXISTS issue_days_final ON issue_days(final, day);
CREATE INDEX IF NOT EXISTS issue_days_calc ON issue_days(calc_id);
"""


def connect(path: pathlib.Path | str) -> sqlite3.Connection:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    cols = {r[1] for r in con.execute("PRAGMA table_info(issue_days)")}
    if cols and "detail" not in cols:          # A 덩어리 때 만든 파일
        con.execute("ALTER TABLE issue_days ADD COLUMN detail TEXT")
    con.executescript(SCHEMA)
    con.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (SCHEMA_VER,))
    con.commit()
    return con


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


# ── 계산 기록
def new_calc(con, asof: str, decided_at: str, mode: str, versions: dict) -> int:
    cur = con.execute(
        "INSERT INTO calc_runs (asof, decided_at, mode, rules_ver, formula_ver, dict_ver, ledger_hash, feeds_hash,"
        " overrides_hash) VALUES (?,?,?,?,?,?,?,?,?)",
        (asof, decided_at, mode, versions.get("rules"), versions.get("formula"), versions.get("dict"),
         versions.get("ledger"), versions.get("feeds"), versions.get("overrides")))
    return int(cur.lastrowid)


def finish_calc(con, calc_id: int, excluded: dict, late: int, n_items: int, source_status=None) -> None:
    con.execute("UPDATE calc_runs SET excluded=?, late_items=?, n_items=?, source_status=? WHERE calc_id=?",
                (_j(excluded), late, n_items, _j(source_status or {}), calc_id))


def last_step_calc(con) -> int | None:
    r = con.execute("SELECT MAX(calc_id) FROM calc_runs WHERE mode IN ('step','replay')").fetchone()
    return r[0]


def last_step_asof(con) -> str | None:
    r = con.execute("SELECT asof FROM calc_runs WHERE mode IN ('step','replay') ORDER BY calc_id DESC LIMIT 1").fetchone()
    return r[0] if r else None


# ── 낱말 분석 저장소
def get_analysis(con, keys: list[str], dict_ver: str) -> dict[str, dict]:
    out = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in con.execute(f"SELECT item_key, title, entities, terms, person, indirect FROM articles"
                             f" WHERE dict_ver=? AND item_key IN ({q})", [dict_ver, *chunk]):
            out[r["item_key"]] = {"title": r["title"], "entities": json.loads(r["entities"]),
                                  "terms": json.loads(r["terms"]), "person": bool(r["person"]),
                                  "indirect": bool(r["indirect"])}
    return out


def put_articles(con, arts: list[dict], dict_ver: str) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO articles (item_key, dict_ver, canon_url, same_url_of, lang, kind, feed, outlet, family,"
        " section, event_at, received_at, day, title, norm_title, norm_summary, entities, terms, person, indirect,"
        " sensitivity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(a["key"], dict_ver, a.get("canon"), a.get("same_url_of"), a["lang"], a["kind"], a["feed"], a["outlet"],
          a["family"], a.get("section", ""), a["event_at"].isoformat(), a["received_at"].isoformat(), a["day"],
          a["title"], a.get("norm_title", ""), a.get("norm_summary", ""), _j(a.get("entities") or []),
          _j(a.get("terms") or []), int(bool(a.get("person"))), int(bool(a.get("indirect"))),
          _j(a.get("sensitivity")) if a.get("sensitivity") else None) for a in arts])


# ── 번호 대장
_STATUS_KIND = {"흡수": "absorbed", "사라짐(잠정)": "vanished"}


def load_registry(con, asof: str | None = None) -> dict[str, Issue]:
    """번호 대장. asof 를 주면 minted_at ≤ asof 인 번호만, 상태도 그 시각까지의 이력으로 정한다."""
    rows = con.execute("SELECT * FROM issues ORDER BY issue_id").fetchall()
    st: dict[str, str] = {}
    if asof:
        for iid, kind in con.execute("SELECT issue_id, kind FROM issue_history WHERE at<=? AND kind IN ('흡수','사라짐(잠정)')"
                                     " ORDER BY at", (asof,)):
            st[iid] = _STATUS_KIND[kind]
    out = {}
    for r in rows:
        if asof and r["minted_at"] and r["minted_at"] > asof:
            continue
        status = st.get(r["issue_id"], "active") if asof else (r["status"] or "active")
        out[r["issue_id"]] = Issue(r["issue_id"], r["lang"], r["first_day"], r["minted_at"], r["minted_calc"],
                                   r["seed_key"], r["title"], status, r["split_of"], r["override_sig"])
    return out


def save_registry(con, reg: dict[str, Issue]) -> None:
    con.executemany(
        "INSERT INTO issues (issue_id, lang, first_day, minted_at, minted_calc, seed_key, title, status, split_of,"
        " override_sig) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(issue_id) DO UPDATE SET status=excluded.status",
        [(i.issue_id, i.lang, i.first_day, i.minted_at, i.minted_calc, i.seed_key, i.title, i.status, i.split_of,
          i.override_sig) for i in reg.values()])


def add_history(con, rows: list[dict]) -> None:
    con.executemany("INSERT INTO issue_history VALUES (?,?,?,?)",
                    [(h["issue_id"], h["at"], h["kind"], _j(h.get("detail") or {})) for h in rows])


def add_aliases(con, rows: list[dict]) -> None:
    con.executemany("INSERT OR IGNORE INTO issue_aliases VALUES (?,?,?,?)",
                    [(a["old_id"], a["new_id"], a["at"], a["reason"]) for a in rows])


def aliases(con) -> dict[str, str]:
    return {r[0]: r[1] for r in con.execute("SELECT old_id, new_id FROM issue_aliases ORDER BY at")}


# ── 그룹
def save_groups(con, calc_id: int, groups: list[dict], final: bool) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO groups VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(g["group_id"], g["day"], calc_id, int(final), g["lang"], g["seed"], _j(g["units"]), _j(g.get("copies") or []),
          _j(g["families"]), _j(g["sources"]), int(g["has_official"]), _j(g["ent_fam"]), _j(g["term_fam"]),
          g["title"], g["first_at"], g.get("issue_id"), _j(g.get("link"))) for g in groups])


def _row_group(r) -> dict:
    return {"group_id": r["group_id"], "day": r["day"], "calc_id": r["calc_id"], "final": bool(r["final"]),
            "lang": r["lang"], "seed": r["seed_key"], "units": json.loads(r["members"]),
            "copies": json.loads(r["copies"]), "families": json.loads(r["families"]), "sources": json.loads(r["sources"]),
            "has_official": bool(r["has_official"]), "ent_fam": json.loads(r["ent_fam"]),
            "term_fam": json.loads(r["term_fam"]), "title": r["title"], "first_at": r["first_at"],
            "issue_id": r["issue_id"], "link": json.loads(r["link"]) if r["link"] else None}


def final_groups(con, since_day: str | None = None) -> list[dict]:
    q = "SELECT * FROM groups WHERE final=1" + (" AND day>=?" if since_day else "") + " ORDER BY day, first_at, seed_key"
    return [_row_group(r) for r in con.execute(q, (since_day,) if since_day else ())]


def calc_groups(con, calc_id: int) -> list[dict]:
    return [_row_group(r) for r in con.execute(
        "SELECT * FROM groups WHERE calc_id=? AND final=0 ORDER BY day, first_at, seed_key", (calc_id,))]


def final_days(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT day FROM final_days")}


def mark_final(con, day: str, calc_id: int, at: str) -> None:
    con.execute("INSERT OR IGNORE INTO final_days VALUES (?,?,?)", (day, calc_id, at))


def save_copies(con, copies: dict[str, dict]) -> None:
    con.executemany("INSERT OR REPLACE INTO copies VALUES (?,?,?,?)",
                    [(k, v["rep"], v["rule"], v["dice"]) for k, v in sorted(copies.items())])


# ── 점수(B 덩어리)
DAY_COLS = ("issue_id", "day", "calc_id", "final", "A", "g", "w", "v", "H", "B", "P", "D", "f_new", "e_new", "score_raw",
            "score", "state", "kinds_present", "kinds_ok", "missing", "category", "sensitivity", "person", "indirect_n",
            "articles_n", "copies_n", "detail")
_JSON_COLS = ("kinds_present", "kinds_ok", "missing", "sensitivity", "detail")


def meta_get(con, key: str) -> str | None:
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def meta_set(con, key: str, value: str) -> None:
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))


def _r6(x):
    return None if x is None else round(float(x), 6)


def save_days(con, rows: list[dict]) -> None:
    out = []
    for r in rows:
        t = []
        for c in DAY_COLS:
            v = r.get(c)
            if c in _JSON_COLS:
                v = _j(v)
            elif c in ("g", "w", "v", "H", "B", "P", "D", "score_raw"):
                v = _r6(v)
            elif c in ("final", "person"):
                v = int(bool(v))
            t.append(v)
        out.append(tuple(t))
    q = ",".join("?" * len(DAY_COLS))
    con.executemany(f"INSERT OR REPLACE INTO issue_days ({','.join(DAY_COLS)}) VALUES ({q})", out)


def _row_day(r) -> dict:
    d = {c: r[c] for c in DAY_COLS}
    for c in _JSON_COLS:
        d[c] = json.loads(d[c]) if d[c] else ([] if c != "detail" and c != "sensitivity" else {})
    d["final"] = bool(d["final"])
    d["person"] = bool(d["person"])
    return d


def final_day_rows(con, since_day: str) -> list[dict]:
    return [_row_day(r) for r in con.execute(
        "SELECT * FROM issue_days WHERE final=1 AND day>=? ORDER BY issue_id, day", (since_day,))]


def calc_day_rows(con, calc_id: int) -> list[dict]:
    return [_row_day(r) for r in con.execute("SELECT * FROM issue_days WHERE calc_id=? ORDER BY issue_id, day", (calc_id,))]


def issue_day_rows(con, issue_id: str, asof: str | None = None) -> list[dict]:
    """한 이슈의 날짜별 값: 확정 행 + (asof 까지의 마지막 단계 계산의) 잠정 행.
    정리(prune)로 그 계산의 잠정 행이 지워진 날(지금은 확정된 날)은 그 앞 계산 가운데 마지막 것의 잠정 행을 쓴다."""
    cid = last_calc_upto(con, asof)
    q = ("SELECT d.* FROM issue_days d JOIN calc_runs c USING(calc_id) WHERE d.issue_id=? AND c.asof<=? AND "
         "(d.final=1 OR d.calc_id=?) ORDER BY d.day")
    out = {r["day"]: _row_day(r) for r in con.execute(q, (issue_id, asof or "9999", cid))}
    if cid is not None and meta_get(con, "pruned_through"):
        later = {r[0] for r in con.execute("SELECT day FROM final_days WHERE calc_id>?", (cid,))}
        older = {}
        for r in con.execute("SELECT * FROM issue_days WHERE issue_id=? AND final=0 AND calc_id<? ORDER BY calc_id",
                             (issue_id, cid)):
            if r["day"] in later and r["day"] not in out:
                older[r["day"]] = r                      # 계산 번호 순이라 마지막 것이 남는다
        out.update({d: _row_day(r) for d, r in older.items()})
    return [out[d] for d in sorted(out)]


def last_calc_upto(con, asof: str | None = None) -> int | None:
    r = con.execute("SELECT calc_id FROM calc_runs WHERE mode IN ('step','replay') AND asof<=? AND source_status IS NOT NULL"
                    " AND source_status!='{}' ORDER BY asof DESC, calc_id DESC LIMIT 1", (asof or "9999",)).fetchone()
    return r[0] if r else None


def calc_row(con, calc_id: int) -> dict | None:
    r = con.execute("SELECT * FROM calc_runs WHERE calc_id=?", (calc_id,)).fetchone()
    return dict(r) if r else None


def set_board_meta(con, calc_id: int, payload: dict) -> None:
    con.execute("UPDATE calc_runs SET source_status=? WHERE calc_id=?", (_j(payload), calc_id))


def drop_old_provisional(con, before_day: str) -> None:
    con.execute("DELETE FROM issue_days WHERE final=0 AND day<?", (before_day,))
    con.execute("DELETE FROM issue_trends WHERE day<? AND calc_id NOT IN (SELECT calc_id FROM issue_days WHERE final=1)",
                (before_day,))


def save_trends(con, calc_id: int, rows: list[dict]) -> None:
    con.executemany("INSERT INTO issue_trends VALUES (?,?,?,?,?,?,?,?)",
                    [(r["issue_id"], r["day"], calc_id, r["trend_key"], r["keyword"], r["traffic_raw"], r["grade"],
                      r.get("matched_article")) for r in rows])


def save_followups(con, rows: list[dict]) -> None:
    con.executemany("INSERT INTO issue_followups VALUES (?,?,?,?,?,?)",
                    [(r["issue_id"], r["day"], r["unit_id"], r["seed"], _j(r["families"]), _j(r["new_terms"]))
                     for r in rows])


def save_entities(con, rows: list[dict]) -> None:
    con.executemany("INSERT OR IGNORE INTO issue_entities VALUES (?,?,?,?)",
                    [(r["issue_id"], r["entity"], r["day"], _j(r["families"])) for r in rows])


def aliases_upto(con, asof: str) -> dict[str, list[str]]:
    """새 번호 → 그 번호로 들어간 옛 번호들(at ≤ asof)."""
    out: dict[str, list[str]] = {}
    for old, new in con.execute("SELECT old_id, new_id FROM issue_aliases WHERE at<=? ORDER BY old_id", (asof,)):
        out.setdefault(new, []).append(old)
    return out


def history(con, issue_id: str, asof: str | None = None) -> list[dict]:
    return [{"at": r[0], "kind": r[1], "detail": json.loads(r[2] or "{}")} for r in con.execute(
        "SELECT at, kind, detail FROM issue_history WHERE issue_id=? AND at<=? ORDER BY at, kind", (issue_id, asof or "9999"))]


# ── 정리(prune)
def prune(con) -> dict:
    """확정된 날의 확정 전 행 가운데 다시 쓰이지 않는 것을 지운다. 지운 뒤에도 지난 시각의 board(rebuild_board), 다음 단계의
    계산, replay 의 결과는 같다(시험이 지킨다). 남기는 것:
    - 확정 행 전부, 마지막 단계 계산의 행 전부(다음 단계의 재식별이 읽는다).
    - issue_days: 각 계산의 기준일 줄(그 시각의 board 를 다시 만드는 데 쓴다), 그 날의 마지막 계산분.
    - groups·issue_trends: 그 날의 마지막 계산분.
    지난 시각의 explain 은 그 계산의 어제 줄이 지워졌으면 그 앞 계산의 줄로 보인다(issue_day_rows)."""
    from ozl.signals import config
    last = last_step_calc(con)
    base = {cid: config.kst_day(config.parse_ts(a)) for cid, a in con.execute("SELECT calc_id, asof FROM calc_runs")}
    fin = [r[0] for r in con.execute("SELECT day FROM final_days ORDER BY day")]
    n = {"groups": 0, "issue_days": 0, "issue_trends": 0}
    for d in fin:
        for tbl, extra in (("groups", False), ("issue_days", True), ("issue_trends", False)):
            fcol = "final=0 AND " if tbl != "issue_trends" else ""
            cids = sorted({r[0] for r in con.execute(f"SELECT DISTINCT calc_id FROM {tbl} WHERE {fcol}day=?", (d,))})
            if tbl == "issue_trends":
                fc = con.execute("SELECT calc_id FROM final_days WHERE day=?", (d,)).fetchone()[0]
                cids = [c for c in cids if c != fc]
            if not cids:
                continue
            keep = {max(cids), last}
            if extra:
                keep |= {c for c in cids if base.get(c) == d}
            drop = [c for c in cids if c not in keep]
            for i in range(0, len(drop), 500):
                chunk = drop[i:i + 500]
                q = ",".join("?" * len(chunk))
                cur = con.execute(f"DELETE FROM {tbl} WHERE {fcol}day=? AND calc_id IN ({q})", [d, *chunk])
                n[tbl] += cur.rowcount
    if fin:
        meta_set(con, "pruned_through", fin[-1])
    con.commit()
    return n
