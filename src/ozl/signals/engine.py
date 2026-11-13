"""계산 단계 한 번(§7): 묶기(pipeline.step) → 출처 상태 → 날짜별 값(days.DayCalc) → 저장 → board.json.

- 단계(mode='step')는 수집 DB 실행 기록의 각 시각이다. 번호 발급과 날짜별 값 저장은 단계에서만 한다.
- 실행 시각이 아닌 asof 는 보기 전용(mode='view'): 임시 번호로 board 만 만들고 아무것도 저장하지 않는다.
- 날짜 d 는 d 다음날 12:00 KST 뒤 첫 단계에서 확정되고(받은 시각 ≤ 그 시각인 자료만), 확정 행은 다시 쓰지 않는다.
  확정 안 된 날(보통 어제와 오늘)은 단계마다 처음부터 다시 내고 계산 번호를 붙여 쌓는다.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta

from ozl.signals import board, config, days, health, pipeline, score, source, store, trends, wiki

FINAL_KEY = "score_final_through"


def _compute_days(con, res: dict, asof: datetime) -> tuple[list[str], set[str]]:
    base = config.kst_day(asof)
    through = store.meta_get(con, FINAL_KEY)
    if through:
        start = config.day_add(through, 1)
    else:
        gds = [g["day"] for g in [*res["frozen"], *res["groups"]]]
        start = min(gds + [base])
    out, d = [], start
    while d <= base:
        out.append(d)
        d = config.day_add(d, 1)
    return out, {d for d in out if config.t_final(d) <= asof}


def _meta(res, asof, mode, decided_at, st_base, runs, tg, unmatched) -> dict:
    base = config.kst_day(asof)
    failed_both = all(st_base[k]["status"] == health.FAILED for k in (score.NEWS, score.SEARCH))
    return {"asof": asof.astimezone(config.KST).isoformat(), "base_day": base,
            "partial": asof < health.day_end(base, asof + timedelta(days=2)),
            "decided_at": decided_at.astimezone(config.KST).isoformat(), "calc_id": res["calc_id"], "mode": mode,
            "versions": res["versions"], "basis": health.basis(st_base),
            "sources": health.sources_block(runs, tg, st_base, wiki.off_reason()),
            "missing": health.missing_labels(st_base), "unmatched": unmatched, "merge_hints": res["merge_hints"],
            "failed_both": failed_both,
            "status": {k: v["status"] for k, v in st_base.items()}}


def step(con: sqlite3.Connection, pulse_db, asof: datetime, mode: str = "step", overrides_path=None,
         decided_at: datetime | None = None, board_out=None) -> dict:
    asof = asof.astimezone(config.UTC)
    if mode == "view":
        last = store.last_step_asof(con)
        if last and config.parse_ts(last) > asof:
            # 확정 행·확정 그룹은 asof 로 자를 수 없다(그 뒤에 확정된 날의 값이 섞인다). 지난 시각은 rebuild_board 로 본다.
            raise ValueError(f"보기 전용 계산의 기준 시각({config.iso_utc(asof)})이 마지막 단계({last})보다 이르다 "
                             "— 지난 판은 rebuild_board 로 본다")
    decided_at = decided_at or datetime.now(config.UTC)
    res = pipeline.step(con, pulse_db, asof, mode, overrides_path, decided_at=decided_at, trend_rule=trends.group_hit)
    tg = health.targets()
    runs = health.parse_runs(source.runs_until(pulse_db, asof))
    dlist, final_now = _compute_days(con, res, asof)
    statuses = {d: health.day_status(runs, tg, d, asof) for d in dlist}
    since = config.day_add(dlist[0], -(config.DORMANT_KEEP_DAYS + 30))
    memo: dict = {}

    def status_of(d):           # 계산 목록 밖의 날(줄을 쓰지 않고 건너뛴 날)의 수집 상태
        if d not in memo:
            memo[d] = health.day_status(runs, tg, d, asof)
        return memo[d]
    calc = days.DayCalc(res, store.final_day_rows(con, since), statuses, asof, dlist, final_now, status_of)
    calc.run()
    base = config.kst_day(asof)
    meta = _meta(res, asof, mode, decided_at, statuses[base], runs, tg, calc.unmatched.get(base, []))
    cid = res["calc_id"]
    keep = [r for r in calc.out_rows if r["final"] or r["_active"] or r["day"] == base]
    for r in calc.out_rows:
        r["calc_id"] = cid
    if mode == "step":
        store.save_days(con, keep)
        store.save_trends(con, cid, calc.trend_rows)
        store.save_followups(con, calc.fu_rows)
        store.save_entities(con, calc.ent_rows)
        store.add_history(con, calc.hist)
        for d in sorted(final_now):
            store.meta_set(con, FINAL_KEY, d)
        store.drop_old_provisional(con, config.day_add(base, -config.PROVISIONAL_KEEP_DAYS))
        store.set_board_meta(con, cid, {**meta, "status_by_day": {d: {k: v["status"] for k, v in s.items()}
                                                                  for d, s in statuses.items()}})
        con.commit()
    al = store.aliases_upto(con, config.iso_utc(asof))
    b = board.build(meta, [r for r in calc.out_rows if r["day"] == base], al)
    if board_out:
        board.write(b, board_out)
    return {"res": res, "rows": calc.out_rows, "board": b, "meta": meta, "calc": calc}


def rebuild_board(con, asof: datetime | None = None) -> dict | None:
    """이미 계산된 단계로 board 만 다시 만든다(계산하지 않는다)."""
    cid = store.last_calc_upto(con, config.iso_utc(asof) if asof else None)
    if cid is None:
        return None
    meta = store.calc_row(con, cid)
    m = json.loads(meta["source_status"])
    rows = [r for r in store.calc_day_rows(con, cid) if r["day"] == m["base_day"]]
    return board.build(m, rows, store.aliases_upto(con, meta["asof"]))


def catch_up(con, pulse_db, asof: datetime | None = None, overrides_path=None, board_out=None, log=None) -> dict | None:
    """마지막 단계 뒤의 실행 시각을 차례로 계산하고, asof 가 실행 시각이 아니면 보기 전용 계산을 한 번 더 한다."""
    now = (asof or datetime.now(config.UTC)).astimezone(config.UTC)
    last = store.last_step_asof(con)
    last_dt = config.parse_ts(last) if last else None
    if asof is not None and last_dt is not None and now < last_dt:
        # 지난 시각: 다시 계산하지 않고 그 시각 이전 마지막 단계의 판을 돌려준다. 라이브 board.json 은 덮어쓰지 않는다.
        if log:
            log("기준 시각이 마지막 단계보다 이르다 — 그 앞 단계의 판을 보여 주고 board.json 은 쓰지 않는다")
        b = rebuild_board(con, now)
        return {"board": b, "past": True} if b else None
    todo = [t for t in pipeline.run_times(pulse_db, until=now) if last_dt is None or t > last_dt]
    out = None
    for i, t in enumerate(todo):
        out = step(con, pulse_db, t, "step", overrides_path, board_out=board_out if i == len(todo) - 1 else None)
        if log:
            log(f"단계 {t.astimezone(config.KST):%m-%d %H:%M} 계산")
    is_run = any(abs((t - now).total_seconds()) < 1e-3 for t in pipeline.run_times(pulse_db, until=now)[-1:])
    if asof is not None and not is_run:
        out = step(con, pulse_db, now, "view", overrides_path, board_out=board_out)
    elif out is None:
        b = rebuild_board(con, now)
        if b and board_out:
            board.write(b, board_out)
        out = {"board": b} if b else None
    return out


def replay(pulse_db, db_path, frm: str, to: str, step_kind: str = "runs", overrides_path=None, board_out=None,
           log=None) -> dict:
    """가진 기간을 날짜순으로 처음부터 다시 계산한다(빈 engine.db 에)."""
    t0 = time.monotonic()
    con = store.connect(db_path)
    if step_kind == "daily":
        steps, d = [], frm
        while d <= to:
            steps.append(datetime.fromisoformat(d + "T23:59:59").replace(tzinfo=config.KST).astimezone(config.UTC))
            d = config.day_add(d, 1)
    else:
        steps = pipeline.run_times(pulse_db, frm, to, until=datetime.now(config.UTC) + timedelta(days=3650))
    out = None
    for i, t in enumerate(steps):
        out = step(con, pulse_db, t, "step", overrides_path, board_out=board_out if i == len(steps) - 1 else None)
        if log and (i % 10 == 0 or i == len(steps) - 1):
            log(f"{i + 1}/{len(steps)} 단계 {t.astimezone(config.KST):%m-%d %H:%M}")
    by_day = Counter()
    for (d,) in con.execute("SELECT day FROM issue_days d WHERE final=1 OR calc_id=(SELECT MAX(calc_id) FROM calc_runs) "
                            "GROUP BY issue_id, day"):
        by_day[d] += 1
    summary = {"steps": len(steps), "issues_by_day": dict(sorted(by_day.items())),
               "final_days": sorted(r[0] for r in con.execute("SELECT DISTINCT day FROM issue_days WHERE final=1")),
               "issues": con.execute("SELECT COUNT(*) FROM issues").fetchone()[0],
               "seconds": round(time.monotonic() - t0, 1), "board": out["board"] if out else None}
    con.close()
    return summary


def compare(a, b) -> list[str]:
    """두 계산 파일의 issues·issue_aliases·issue_days 가 같은가. 다른 표 이름 목록."""
    qs = {"issues": "SELECT issue_id, lang, first_day, minted_at, seed_key, title, status, split_of FROM issues ORDER BY 1",
          "issue_aliases": "SELECT * FROM issue_aliases ORDER BY 1, 2",
          "issue_days": "SELECT * FROM issue_days ORDER BY issue_id, day, calc_id"}
    ca, cb = store.connect(a), store.connect(b)
    try:
        return [k for k, q in qs.items() if [tuple(r) for r in ca.execute(q)] != [tuple(r) for r in cb.execute(q)]]
    finally:
        ca.close()
        cb.close()
