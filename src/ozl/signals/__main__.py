"""명령줄(§1-2).

python -m ozl.signals run [--asof 시각]                 — 아직 계산하지 않은 매시 수집 시각을 따라잡고 board.json 을 쓴다
python -m ozl.signals replay --from 날 --to 날 [--db 경로] [--step runs|daily] [--reset] [--check-against 다른 db]
python -m ozl.signals board [--asof 시각] [--out 경로]  — 계산된 것으로 board.json 만 다시 쓴다
python -m ozl.signals explain <이슈 번호> [--asof 시각] [--json]   — 점수 내역, 날짜별 그룹과 기사(매체·제목·주소), 잇기 근거
python -m ozl.signals prune [--db 경로] [--no-vacuum]   — 확정된 날의 확정 전 행 가운데 다시 쓰이지 않는 것을 지운다

경로: 인자 > 환경 변수(OZL_PULSE_DB, OZL_ENGINE_DB, OZL_BOARD_OUT, OZL_ENGINE_OVERRIDES) > 기본값(private/pulse/…).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import pathlib
import shutil
import sys
from datetime import datetime

from ozl.signals import config, engine, explain, store


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return (d if d.tzinfo else d.replace(tzinfo=config.KST)).astimezone(config.UTC)


def _stamp() -> str:
    return datetime.now(config.KST).strftime("%Y%m%d_%H%M%S")


def _say(msg: str) -> None:
    print(msg, file=sys.stderr)


def _summary_line(b: dict) -> str:
    z = b["zones"]
    return (f"{b['asof'][:16]} · {b['mode']} · 후보 {len(b['candidates'])} · 새로 뜬 것 {len(z['new']['rows'])}"
            f" · 이어지는 것 {len(z['ongoing']['rows'])} · {b['basis']}" + (f" · 누락 {', '.join(b['missing'])}" if b["missing"] else ""))


def cmd_run(a, P) -> int:
    P["lock"].parent.mkdir(parents=True, exist_ok=True)
    with open(P["lock"], "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _say("다른 엔진 계산이 돌고 있다 — 이번에는 건너뛴다")
            return 3
        con = store.connect(P["engine_db"])
        try:
            out = engine.catch_up(con, P["pulse_db"], _ts(a.asof), P["overrides"], P["board"], log=_say)
        finally:
            con.close()
    if not out or not out.get("board"):
        _say("계산할 실행 기록이 없다")
        return 1
    print(_summary_line(out["board"]))
    return 0


def cmd_replay(a, P) -> int:
    db = pathlib.Path(a.db) if a.db else P["pulse_db"].parent / f"engine_replay_{_stamp()}.db"
    live = db.resolve() == P["engine_db"].resolve()
    if db.exists() and db.stat().st_size > 0:
        if live and not a.reset:
            _say(f"{db} 는 라이브 engine.db 다. 바꾸려면 --reset 을 함께 준다(먼저 사본을 남긴다)")
            return 2
        if not a.reset:
            _say(f"{db} 가 이미 있다. 새 경로를 주거나 --reset 을 준다")
            return 2
        bak = db.with_name(db.name + f".bak_{_stamp()}")
        shutil.copy2(db, bak)
        for ext in ("", "-wal", "-shm"):
            q = pathlib.Path(str(db) + ext)
            if q.exists():
                q.unlink()
        _say(f"사본을 남겼다: {bak}")
    s = engine.replay(P["pulse_db"], db, a.frm, a.to, a.step, P["overrides"], P["board"], log=_say)
    if a.step == "daily":
        _say("주의: --step daily 는 날마다 23:59:59 한 번만 계산한다. 번호가 매시 단계 계산과 다를 수 있다")
    print(json.dumps({k: v for k, v in s.items() if k != "board"} | {"db": str(db)}, ensure_ascii=False))
    if s["board"]:
        print(_summary_line(s["board"]))
    if a.check_against:
        diff = engine.compare(db, a.check_against)
        if diff:
            print("다른 표: " + ", ".join(diff))
            return 1
        print("같다: issues, issue_aliases, issue_days")
    return 0


def cmd_board(a, P) -> int:
    con = store.connect(P["engine_db"])
    try:
        b = engine.rebuild_board(con, _ts(a.asof))
    finally:
        con.close()
    if not b:
        _say("계산된 단계가 없다 — 먼저 run")
        return 1
    from ozl.signals import board
    board.write(b, P["board"])
    print(_summary_line(b))
    return 0


def cmd_prune(a, P) -> int:
    """확정된 날의 확정 전 행 가운데 다시 쓰이지 않는 것을 지우고 파일을 줄인다(store.prune). 엔진 잠금을 잡고 한다."""
    P["lock"].parent.mkdir(parents=True, exist_ok=True)
    with open(P["lock"], "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _say("다른 엔진 계산이 돌고 있다 — 이번에는 건너뛴다")
            return 3
        db = P["engine_db"]
        before = db.stat().st_size if db.exists() else 0
        con = store.connect(db)
        try:
            n = store.prune(con)
            if not a.no_vacuum:
                con.execute("VACUUM")
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            con.close()
    after = db.stat().st_size
    print(json.dumps({"deleted": n, "bytes_before": before, "bytes_after": after, "db": str(db)}, ensure_ascii=False))
    return 0


def cmd_explain(a, P) -> int:
    con = store.connect(P["engine_db"])
    try:
        x = explain.explain(con, a.issue, _ts(a.asof), P["pulse_db"])
    finally:
        con.close()
    print(json.dumps(x, ensure_ascii=False, indent=1) if a.json else explain.render(x))
    return 0 if x["found"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ozl.signals", description="화제 엔진(1판)")
    ap.add_argument("--pulse-db")
    ap.add_argument("--db", dest="engine_db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--asof")
    r.add_argument("--out")
    rp = sub.add_parser("replay")
    rp.add_argument("--from", dest="frm", required=True)
    rp.add_argument("--to", required=True)
    rp.add_argument("--db")
    rp.add_argument("--step", choices=("runs", "daily"), default="runs")
    rp.add_argument("--reset", action="store_true")
    rp.add_argument("--check-against")
    rp.add_argument("--out")
    b = sub.add_parser("board")
    b.add_argument("--asof")
    b.add_argument("--out")
    pr = sub.add_parser("prune")
    pr.add_argument("--no-vacuum", action="store_true")
    e = sub.add_parser("explain")
    e.add_argument("issue")
    e.add_argument("--asof")
    e.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    P = config.paths(a.pulse_db, a.engine_db, getattr(a, "out", None))
    return {"run": cmd_run, "replay": cmd_replay, "board": cmd_board, "explain": cmd_explain,
            "prune": cmd_prune}[a.cmd](a, P)


if __name__ == "__main__":
    sys.exit(main())
