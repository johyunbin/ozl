#!/usr/bin/env python3
"""OZL 이슈 데스크 명령줄 — `/ozl` 스킬이 부르는 결정적 단계들.

    python -m ozl.research collect --slot am                  # 후보 수집 → private/desk/<날짜>_am/candidates.md
    python -m ozl.research coverage 낱말 [낱말…] [--fulltext]   # 슈카월드 기존 커버리지 대조
    python -m ozl.research ids --slot am -n 6                 # 새 카드 ID 발급(발급 대장에 적힌다 — 부를 때마다 번호가 소비된다)
    python -m ozl.research validate --slot am                 # 카드·클레임 스키마 검사
    python -m ozl.research render --slot am                   # 전체본·검증 시트(비공개) + 발행본(공개) 쓰기
    python -m ozl.research notion --slot am                   # Notion upsert 용 속성 JSON
    python -m ozl.research status                             # 채택 대기·검증 대기 목록
    python -m ozl.research pick <card_id>                     # 채택(상태만 바꾼다)
    python -m ozl.research human-verify <claim_id>… --by 이름  # 사람이 원문을 대조했다고 말한 클레임만
    python -m ozl.research publish <card_id>… --by 이름        # 공개 발행 승인(배지 조건 통과 시)
    python -m ozl.research withdraw <card_id> --by 이름 --reason 사유   # 발행 철회(공개 클레임 사본 제거 · 발행본에 철회 줄)
날짜를 생략하면 오늘(KST).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from . import cards as C


def today() -> str:
    return datetime.now(C.KST).strftime("%Y-%m-%d")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "collect":
        from . import collect
        return collect.main(rest)
    if cmd == "coverage":
        from . import coverage
        return coverage.main(rest)

    ap = argparse.ArgumentParser(prog=f"ozl.research {cmd}")
    if cmd in ("ids", "validate", "render", "notion"):
        ap.add_argument("--slot", required=True, choices=["am", "pm", "wk"])
        ap.add_argument("--date", default=today())
        if cmd == "ids":
            ap.add_argument("-n", type=int, default=6)
        a = ap.parse_args(rest)
        if cmd == "ids":
            print("\n".join(C.next_ids(a.date, a.slot, a.n)))
            return 0
        from . import report
        if cmd == "validate":
            cards = C.cards_for(a.date, a.slot)
            errs = [e for c in cards for e in C.validate_card(c, C.claims_for(c["card_id"]))]
            print(f"{a.date} {a.slot}: 카드 {len(cards)}장 · 클레임 {sum(len(C.claims_for(c['card_id'])) for c in cards)}건 · 오류 {len(errs)}건")
            for e in errs:
                print(f"  - {e}")
            return 1 if (errs or not cards) else 0
        if cmd == "render":
            try:
                r = report.render_all(a.date, a.slot)
            except (ValueError, FileNotFoundError) as e:
                print(e)
                return 1
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return 0
        print(json.dumps(report.notion_rows(a.date, a.slot), ensure_ascii=False, indent=1))
        return 0
    if cmd == "status":
        ap.add_argument("--date")
        a = ap.parse_args(rest)
        files = sorted(C.CARDS.glob(f"{a.date or ''}*.yaml"))
        rows = [C.load_yaml(p) for p in files]
        wait = [c for c in rows if c.get("state") == "제안"]
        picked = [c for c in rows if c.get("state") == "채택"]
        print(f"카드 {len(rows)}장 · 채택 대기 {len(wait)} · 채택 {len(picked)}")
        for c in rows[-30:]:
            hv = [x.get("human_verified") for x in C.claims_for(c["card_id"])]
            pub = "발행" if C.publishable(c, C.claims_for(c["card_id"])) else "철회" if (c.get("publish") or {}).get("withdrawn_at") else "미발행"
            print(f"- {c['card_id']} [{c['state']}] {C.BADGE_KO[c['badge']]} · 사람 확인 {sum(bool(h) for h in hv)}/{len(hv)} · {pub} · {c['titles'][0]}")
        return 0
    if cmd == "pick":
        ap.add_argument("card_id")
        a = ap.parse_args(rest)
        c = C.set_state(a.card_id, "채택")
        print(f"{a.card_id} → 채택 (r{c['revision']}). 다음: 클레임 전수 검증 → private/decks/drafts/ 초안")
        return 0
    if cmd == "human-verify":
        ap.add_argument("claim_ids", nargs="+")
        ap.add_argument("--by", required=True)
        a = ap.parse_args(rest)
        try:
            out = C.human_verify(a.claim_ids, a.by)
        except (ValueError, FileNotFoundError) as e:
            print(f"거부: {e}")
            return 1
        for c in out:
            print(f"{c['claim_id']} → human_verified · status {c['status']}")
        return 0
    if cmd == "publish":
        ap.add_argument("card_ids", nargs="+")
        ap.add_argument("--by", required=True)
        a = ap.parse_args(rest)
        from . import report
        rc = 0
        for cid in a.card_ids:
            try:
                C.approve_publish(cid, a.by)
                print(f"{cid} → 공개 발행 승인")
            except (PermissionError, ValueError) as e:
                print(f"거부: {e}")
                rc = 1
        for date, slot in sorted({(cid[:10], cid[11:13]) for cid in a.card_ids}):
            print(json.dumps(report.render_all(date, slot), ensure_ascii=False))
        return rc
    if cmd == "withdraw":
        ap.add_argument("card_id")
        ap.add_argument("--by", required=True)
        ap.add_argument("--reason", required=True)
        a = ap.parse_args(rest)
        from . import report
        C.withdraw(a.card_id, a.by, a.reason)
        print(f"{a.card_id} → 발행 철회. docs/corrections.md 에 정정·철회 기록을 적을 것")
        print(json.dumps(report.render_all(a.card_id[:10], a.card_id[11:13]), ensure_ascii=False))
        return 0
    print(f"모르는 명령: {cmd}\n{__doc__}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
