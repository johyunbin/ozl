#!/usr/bin/env python3
"""OZL Pulse 명령줄.

    python -m ozl.pulse run [--no-fetch]   # 수집 → 점수 → private/pulse/out/now.json
    python -m ozl.pulse show [-n 15]       # now.json 상위 주제를 표로
    python -m ozl.pulse prune [--days 90]  # 오래된 항목·실행 기록 정리
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import snapshot, store


def show(n: int) -> int:
    p = snapshot.OUT / "now.json"
    if not p.exists():
        print("now.json 없음 — 먼저 run", file=sys.stderr)
        return 1
    d = json.loads(p.read_text(encoding="utf-8"))
    print(f"{d['generated_at']} · 주제 {d['n_topics']} · 수집 {d['n_fetched']}(새 {d['n_new']}) · 실패 피드 {len(d['feeds_failed'])} · 유튜브 {d['signal_status']['youtube']}")
    for t in d["topics"][:n]:
        sens = "" if t["sensitivity"]["level"] == "GREEN" else f" [{t['sensitivity']['level']}]"
        print(f"{t['rank']:>2} {t['move']:>4} {t['score']:>5.2f} {'/'.join(t['on']) or '-':<14} {t['title'][:60]}{sens}")
        print(f"          {' · '.join(t['reasons'])}")
    if d["searches"]:
        print("급상승어:", ", ".join(f"{s['title']}({s['traffic']})" + ("*" if s["topic_id"] else "") for s in d["searches"][:20]), "(* = 주제와 연결)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ozl.pulse")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--no-fetch", action="store_true")
    s = sub.add_parser("show")
    s.add_argument("-n", type=int, default=15)
    p = sub.add_parser("prune")
    p.add_argument("--days", type=int, default=90)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        res = snapshot.run(fetch=not a.no_fetch)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res["ok"] else 2
    if a.cmd == "show":
        return show(a.n)
    if a.cmd == "prune":
        print(json.dumps(store.prune(store.connect(), datetime.now(timezone.utc), a.days), ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
