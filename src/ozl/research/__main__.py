#!/usr/bin/env python3
"""OZL 이슈 데스크 명령줄 — `/ozl` 스킬이 부르는 결정적 단계들.

    python -m ozl.research collect --slot am                  # 후보 수집 → private/desk/<날짜>_am/candidates.md
    python -m ozl.research coverage 낱말 [낱말…] [--fulltext]   # 슈카월드 기존 커버리지 대조
    python -m ozl.research ids --slot am -n 6                 # 새 카드 ID 발급(발급 대장에 적힌다 — 부를 때마다 번호가 소비된다)
    python -m ozl.research validate --slot am                 # 카드·클레임 스키마 검사
    python -m ozl.research render --slot am                   # 전체본·검증 시트(비공개) + 발행본(공개) 쓰기
    python -m ozl.research notion --slot am                   # Notion upsert 용 속성 JSON
    python -m ozl.research status                             # 채택 대기·검증 대기 목록
    python -m ozl.research ledger                             # 카드 원장 private/desk/ledger.csv 쓰기(전체 카드 한 줄씩)
    python -m ozl.research pick <card_id>                     # 채택(상태만 바꾼다)
    python -m ozl.research human-verify <claim_id>… --by 이름  # 사람이 원문을 대조했다고 말한 클레임만
    python -m ozl.research publish <card_id>… --by 이름        # 공개 발행 승인(배지 조건 통과 시)
    python -m ozl.research withdraw <card_id> --by 이름 --reason 사유   # 발행 철회(공개 클레임 사본 제거 · 발행본에 철회 줄)
    python -m ozl.research capture <claim_id…> [--claims-dir 폴더] [--captures-dir 폴더] [--author 쓴쪽]   # 원문 확보·문구 대조·그림 → verification 묶음
    python -m ozl.research capture --refetch-check <claim_id…> | --claims-dir 폴더   # 내기 직전: 원문을 새로 받아 다시 대조(파일은 고치지 않는다)
    python -m ozl.research machine-verify <claim_id…> [--claims-dir 폴더]   # 사본 재해시·재대조·재대조 기록 검사 → 「원문 일치」(verified·human_verified false)
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
            except (ValueError, FileNotFoundError, RuntimeError) as e:
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
            pub = C.publish_status(c, C.claims_for(c["card_id"]))
            print(f"- {c['card_id']} [{c['state']}] {C.badge_ko(c)} · 사람 확인 {sum(bool(h) for h in hv)}/{len(hv)} · {pub} · {c['titles'][0]}")
        return 0
    if cmd == "ledger":
        a = ap.parse_args(rest)
        from . import archive
        p, n = archive.write_ledger()
        print(f"{p} · {n}행")
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
    if cmd in ("capture", "machine-verify"):
        return _machine(cmd, ap, rest)
    print(f"모르는 명령: {cmd}\n{__doc__}")
    return 2


def _claim_files(ids: list[str], claims_dir: str | None) -> list[tuple[str, "pathlib.Path"]]:
    import pathlib
    if claims_dir:
        d = pathlib.Path(claims_dir)
        if not ids:
            ids = sorted((p.stem for p in d.glob("*-c*.yaml") if C.CLAIM_ID.match(p.stem)), key=lambda x: int(C.CLAIM_ID.match(x).group(2)))
        return [(cid, d / f"{cid}.yaml") for cid in ids]
    return [(cid, C.claim_path(cid) if C.CLAIM_ID.fullmatch(cid) else pathlib.Path("/nonexistent") / "bad-id") for cid in ids]


def _machine(cmd: str, ap: argparse.ArgumentParser, rest: list[str]) -> int:
    """capture: 새 기록(pending · 사람 대조 전 · 발행 승인된 카드의 정본 기록이 아닌 것)에만 verification 묶음을 쓴다.
    machine-verify: cards.machine_verify 로 검사하고 통과한 것만 올린다. 둘 다 human_verify·publish 를 부르지 않는다."""
    import pathlib
    import time
    from . import capture as K
    ap.add_argument("claim_ids", nargs="*")
    ap.add_argument("--claims-dir", help="정본 대신 이 폴더의 기록(시험 사본·대기 기록 사본)을 읽고 쓴다")
    if cmd == "capture":
        ap.add_argument("--captures-dir", help="원문 사본·그림을 둘 곳(기본 private/desk/captures)")
        ap.add_argument("--author", default="", help="기록을 쓴 쪽 식별자(verification.author.by)")
        ap.add_argument("--no-image", action="store_true")
        ap.add_argument("--delay", type=float, default=4.0, help="서로 다른 주소를 받을 때 사이 간격(초)")
        ap.add_argument("--refetch-check", action="store_true", help="원문을 새로 받아 observed 를 다시 찾는다(기록·사본을 고치지 않는다)")
    a = ap.parse_args(rest)
    if not a.claim_ids and not a.claims_dir:
        print("claim_id 나 --claims-dir 가 필요하다")
        return 2
    items = _claim_files(a.claim_ids, a.claims_dir)
    rc = 0
    if cmd == "machine-verify":
        for cid, p in items:
            r = C.machine_verify(cid, path=p if a.claims_dir else None)
            if r["ok"]:
                print(f"{cid} → verified (「{C.GRADE_MACHINE}」 · human_verified false)")
            else:
                rc = 1
                print(f"{cid} 올리지 않음:")
                for x in r["reasons"]:
                    print(f"  - {x}")
        return rc
    croot = pathlib.Path(a.captures_dir) if a.captures_dir else C.DESK / "captures"
    cache: dict = {}
    last_net = 0.0
    for cid, p in items:
        if not C.CLAIM_ID.fullmatch(cid or ""):
            print(f"{cid}: 건너뜀 — claim_id 형식 오류")
            rc = 1
            continue
        if not p.is_file():
            print(f"{cid}: 기록 파일 없음({p})")
            rc = 1
            continue
        c = C.load_yaml(p)
        if c.get("claim_id") != cid or p.stem != cid:
            print(f"{cid}: 건너뜀 — 파일 이름과 기록의 claim_id 가 다르다({c.get('claim_id')!r})")
            rc = 1
            continue
        url = (c.get("source") or {}).get("url", "")
        if a.refetch_check:
            fresh = url not in cache
            if fresh and last_net:
                wait = a.delay - (time.monotonic() - last_net)
                if wait > 0:
                    time.sleep(wait)
            r = K.refetch_check(c, cache=cache)
            if fresh:
                last_net = time.monotonic()
            grade = C.grade_label(c)
            bad = grade == C.GRADE_MACHINE and not r["found"]
            rc = 1 if bad else rc
            print(f"{cid}: [{grade}] 받음 {'예' if r['ok'] else '아니오'} · 찾음 {'예' if r['found'] else '아니오'}({r['count']}곳) · "
                  f"사본과 같은 해시 {'예' if r['same_sha'] else '아니오'}" + (f" · {r['reason']}" if r["reason"] else "") + (" · ✗ 「원문 일치」 기록인데 못 찾음" if bad else ""))
            continue
        if c.get("status") != "pending" or c.get("human_verified") is True:
            print(f"{cid}: 건너뜀 — pending 이고 사람 대조 전인 새 기록에만 verification 을 쓴다")
            continue
        if ((C.load_card(c["card_id"]) if C.card_path(c["card_id"]).is_file() else {}).get("publish") or {}).get("approved") is True:
            print(f"{cid}: 건너뜀 — 발행 승인된 카드의 기록이다(정본 카드가 승인돼 있으면 --claims-dir 사본이어도 쓰지 않는다)")
            continue
        fresh = url not in cache
        if fresh and last_net:
            wait = a.delay - (time.monotonic() - last_net)
            if wait > 0:
                time.sleep(wait)
        v = c.get("verification") if isinstance(c.get("verification"), dict) else {}
        try:
            got = K.capture_claim(c, croot, C.ROOT, cache=cache, shot=not a.no_image)
        except ValueError as e:
            print(f"{cid}: 건너뜀 — {e}")
            rc = 1
            continue
        if fresh:
            last_net = time.monotonic()
        c["verification"] = {"method": "machine", **got,
                             "author": {"by": a.author or (v.get("author") or {}).get("by", ""), "located": (v.get("author") or {}).get("located", "")},
                             "recheck": v.get("recheck") or {"by": "", "located": "", "checks": {"unit": "", "as_of": "", "status": "", "population": "", "speaker": ""}, "at": ""},
                             "verified_at": ""}
        C.save_yaml(p, c)
        cap, m = got["capture"], got["match"]
        state = "찾음" if m["found"] else ("열지 못함" if not cap["ok"] else ("대조 불가" if m.get("reason", "").startswith("프로그램 대조 불가") else "못 찾음"))
        print(f"{cid}: {state} · {cap.get('kind') or '-'} {cap.get('bytes') or 0}B · 그림 {'있음' if got['image']['path'] else '없음(' + got['image']['reason'] + ')'}"
              + (f" · {cap['reason'] or m.get('reason', '')}" if state != "찾음" else ""))
    return rc


if __name__ == "__main__":
    sys.exit(main())
