#!/usr/bin/env python3
"""OZL 이슈 브리핑 명령줄.

    python -m ozl.briefs candidates --slot pm [--hours 14] [--top 30]   # 이슈 후보 → private/briefs/<날짜>/<회차>/candidates.md
    python -m ozl.briefs ids --slot pm -n 3                              # 새 덱 번호
    python -m ozl.briefs check <덱.yaml>… | --date <날짜>                  # 덱 검사
    python -m ozl.briefs list [--date <날짜>]                             # 덱 목록(JSON)
날짜를 생략하면 오늘(KST).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime

from ..research import collect
from . import candidates, deck


def today() -> str:
    return datetime.now(collect.KST).strftime("%Y-%m-%d")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ozl.briefs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates")
    c.add_argument("--slot", choices=["am", "pm"], required=True)
    c.add_argument("--date")
    c.add_argument("--hours", type=float, default=24.0)
    c.add_argument("--top", type=int, default=30)
    i = sub.add_parser("ids")
    i.add_argument("--slot", choices=["am", "pm"], required=True)
    i.add_argument("--date")
    i.add_argument("-n", type=int, default=1)
    k = sub.add_parser("check")
    k.add_argument("paths", nargs="*")
    k.add_argument("--date")
    lst = sub.add_parser("list")
    lst.add_argument("--date")
    a = ap.parse_args(argv)

    if a.cmd == "candidates":
        print(candidates.run(a.slot, a.date, a.hours, a.top))
        return 0
    if a.cmd == "ids":
        print("\n".join(deck.issue(a.slot, a.date or today(), a.n)))
        return 0
    if a.cmd == "check":
        paths = [pathlib.Path(p) for p in a.paths] or deck.decks(a.date or today())
        if not paths:
            print("검사할 덱이 없다", file=sys.stderr)
            return 1
        bad = 0
        for p in paths:
            d = deck.load(p)
            err, warn = (["YAML 을 읽지 못했다(문법 오류)"], []) if d is None else deck.check(d, p.stem)
            print(f"{'오류' if err else '통과'} {p.name} — 오류 {len(err)} · 경고 {len(warn)}")
            for e in err:
                print(f"  ✗ {e}")
            for w in warn:
                print(f"  △ {w}")
            bad += bool(err)
        return 1 if bad else 0
    if a.cmd == "list":
        print(json.dumps(deck.listing(a.date), ensure_ascii=False, indent=1))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
