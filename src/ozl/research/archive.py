#!/usr/bin/env python3
"""카드 원장(비공개)과 발행 카드 색인(공개).

- 원장   private/desk/ledger.csv  모든 카드 한 줄씩 — 상태·배지·발행 여부·채택/발행 시각·클레임 수. 엑셀에서 열리게 utf-8-sig 로 쓴다
- 색인   daily/index.json          발행본 목록과 `publishable()` 을 통과한 카드만 — 사이트 「기록」 쪽이 이 파일 하나로 만들어진다
색인에는 생성 시각처럼 돌릴 때마다 바뀌는 값을 넣지 않는다(같은 카드면 같은 파일이 나와야 차이가 내용 변화만 보인다).
경로는 부를 때 계산한다 — 테스트가 cards·report 의 경로를 바꿔 끼운다.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import sys

from . import cards as C
from . import report as R

LEDGER_COLUMNS = ["card_id", "date", "slot", "rank", "title", "category", "topic", "state", "badge", "publish",
                  "picked_at", "published_at", "republished_at", "withdrawn_at", "revision", "claims", "human_verified", "videos"]
REPORT_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(am|pm|wk)\.md$")
SLOT_ORDER = {"am": 0, "pm": 1, "wk": 2}


def ledger_path() -> pathlib.Path:
    return C.DESK / "ledger.csv"


def index_path() -> pathlib.Path:
    return R.ROOT / "daily" / "index.json"


def _replace(path: pathlib.Path, write) -> None:
    """임시 파일에 다 쓴 뒤 바꿔 끼운다 — 중간에 멈춰도 반쯤 쓴 파일이 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    write(tmp)
    os.replace(tmp, path)


def ledger_rows() -> list[dict]:
    rows = []
    for c in C.all_cards():
        claims = C.claims_for(c["card_id"])
        ev = C.event_times(c)
        rows.append({"card_id": c["card_id"], "date": c.get("date", ""), "slot": c.get("slot", ""), "rank": c.get("rank", ""),
                     "title": (c.get("titles") or [""])[0], "category": c.get("category", ""), "topic": c.get("topic", ""),
                     "state": c.get("state", ""), "badge": C.BADGE_KO.get(c.get("badge"), c.get("badge") or ""),
                     "publish": C.publish_status(c, claims), **ev, "revision": c.get("revision", ""), "claims": len(claims),
                     "human_verified": sum(x.get("human_verified") is True for x in claims),
                     "videos": len((c.get("coverage") or {}).get("videos") or [])})
    return rows


def write_ledger(path: pathlib.Path | None = None) -> tuple[pathlib.Path, int]:
    path = pathlib.Path(path) if path else ledger_path()
    rows = ledger_rows()

    def w(tmp: pathlib.Path) -> None:
        with tmp.open("w", encoding="utf-8-sig", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
            wr.writeheader()
            wr.writerows(rows)
    _replace(path, w)
    return path, len(rows)


def _report_files() -> list[tuple[str, str, pathlib.Path]]:
    """공개 발행본 파일 — daily/**/<날짜>_<회차>.md 만(검증 시트 같은 다른 이름은 세지 않는다)."""
    daily = R.ROOT / "daily"
    out = []
    for p in daily.rglob("*.md") if daily.exists() else []:
        m = REPORT_FILE.match(p.name)
        if m:
            out.append((m.group(1), m.group(2), p))
    return sorted(out, key=lambda t: (t[0], SLOT_ORDER[t[1]], str(t[2])))


REPORT_KEYS = {"date": str, "slot": str, "file": str, "cards": int, "published": int}
CARD_KEYS = {"card_id": str, "date": str, "slot": str, "title": str, "category": str, "badge": str, "url": str}
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def index_errors(idx) -> list[str]:
    """색인 검사 — 모양(schema·배열·필수 키·형식)과 정합성(건수·유일성). scripts/build_site.py 의 검사와 같은 규칙이다
    (그쪽은 표준 라이브러리만 써야 해서 따로 옮겨 적었다 — 한쪽을 고치면 다른 쪽도 고친다)."""
    if not isinstance(idx, dict):
        return [f"최상위가 객체가 아니다({type(idx).__name__})"]
    errs = [] if idx.get("schema") == 1 and not isinstance(idx.get("schema"), bool) else [f"schema 가 1 이 아니다({idx.get('schema')!r})"]
    for kind, keys in (("reports", REPORT_KEYS), ("cards", CARD_KEYS)):
        if not isinstance(idx.get(kind), list):
            errs.append(f"{kind} 가 배열이 아니다")
            continue
        for i, x in enumerate(idx[kind]):
            if not isinstance(x, dict):
                errs.append(f"{kind}[{i}] 가 객체가 아니다")
                continue
            bad = [k for k, t in keys.items() if not isinstance(x.get(k), t) or isinstance(x.get(k), bool)]
            if bad:
                errs += [f"{kind}[{i}].{k} 가 없거나 형식이 다르다" for k in bad]
                continue
            d, sl = x["date"], x["slot"]
            if not DATE.fullmatch(d) or sl not in SLOT_ORDER:
                errs.append(f"{kind}[{i}] 날짜·회차 형식 오류: {d!r} {sl!r}")
            elif kind == "cards" and not re.fullmatch(rf"{re.escape(d)}-{sl}-\d{{2}}", x["card_id"]):
                errs.append(f"cards[{i}].card_id({x['card_id']!r})가 그 회차 {d}-{sl}-NN 과 맞지 않다")
            elif kind == "reports" and not (x["file"].startswith("daily/") and x["file"].endswith(f"/{d}_{sl}.md") and ".." not in x["file"].split("/")):
                errs.append(f"reports[{i}].file 이 daily/…/{d}_{sl}.md 가 아니다: {x['file']!r}")
            elif kind == "reports" and not 0 <= x["published"] <= x["cards"]:
                errs.append(f"reports[{i}] 건수 모순: 발행 {x['published']} · 카드 {x['cards']}")
    if errs:
        return errs
    seen_r, seen_c, per = set(), set(), {}
    for r in idx["reports"]:
        key = (r["date"], r["slot"])
        if key in seen_r:
            errs.append(f"보고서 {key[0]} {key[1]} 가 둘 이상이다")
        seen_r.add(key)
    for c in idx["cards"]:
        if c["card_id"] in seen_c:
            errs.append(f"카드 {c['card_id']} 가 둘 이상이다")
        seen_c.add(c["card_id"])
        per[(c["date"], c["slot"])] = per.get((c["date"], c["slot"]), 0) + 1
    for r in idx["reports"]:
        n = per.get((r["date"], r["slot"]), 0)
        if n != r["published"]:
            errs.append(f"보고서 {r['date']} {r['slot']} 의 발행 {r['published']}장과 색인 카드 {n}장이 다르다")
    for key in sorted(set(per) - seen_r):
        errs.append(f"카드가 있는 회차 {key[0]} {key[1]} 의 보고서가 색인에 없다")
    return errs


def _load_prior(path: pathlib.Path) -> dict:
    """기존 색인 — 카드가 없는 회차의 항목을 넘겨 쓰는 데만 쓴다. 넘겨 쓰기 전에 index_errors() 로 검사하고,
    어긋난 항목이 하나라도 있으면 예외를 낸다(검사하지 않은 옛 항목이 현재 판정을 우회하지 못하게)."""
    if not path.exists():
        return {"reports": [], "cards": []}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"기존 색인 {path} 를 읽지 못해 넘겨 쓸 수 없다 — {e}") from e
    errs = index_errors(d)
    if errs:
        raise ValueError(f"기존 색인 {path} 가 검사를 통과하지 못해 넘겨 쓰지 않는다 — " + "; ".join(errs[:4]))
    return d


def build_index(include: list[tuple[str, str]] | tuple = (), path: pathlib.Path | None = None) -> dict:
    """색인 내용을 만든다(쓰지는 않는다). include = 아직 파일로 쓰기 전인 회차 — render_all 이 보고서를 쓰기 전에 넘긴다.
    카드가 있는 회차는 언제나 지금 카드로 새로 계산한다. 카드가 0장인 회차는 기존 색인에 있던 그 회차 항목을 그대로 넘겨 쓰고
    경고를 낸다. 기존 색인에도 없으면 예외 — 카드가 없는 기기에서 돌려 발행 카드가 조용히 빠지는 일을 막는다.
    비공개 카드가 실제로 있는 card_id 는 넘겨 쓰지 않는다. 결과가 index_errors() 를 통과하지 못하면 예외."""
    path = pathlib.Path(path) if path else index_path()
    slots = {(d, s): p for d, s, p in _report_files()}
    for d, s in include:
        slots.setdefault((d, s), R.paths(d, s)["public"])
    everything = C.all_cards()
    private_ids = {c.get("card_id") for c in everything}
    prior = None
    reports, cards = [], []
    for (date, slot) in sorted(slots, key=lambda t: (t[0], SLOT_ORDER[t[1]])):
        rel = slots[(date, slot)].relative_to(R.ROOT).as_posix()
        here = C.cards_for(date, slot)
        if not here:
            prior = prior if prior is not None else _load_prior(path)
            old = [r for r in prior["reports"] if r["date"] == date and r["slot"] == slot]
            if not old:
                raise FileNotFoundError(f"{rel} 는 있는데 {date} {slot} 비공개 카드가 0장이고 기존 색인에도 그 회차가 없다 — "
                                        "private/desk/cards/ 가 있는 기기에서 다시 돌린다(보고서·색인 모두 쓰지 않았다)")
            print(f"경고: {date} {slot} 비공개 카드가 0장이다 — 기존 색인의 그 회차 항목을 그대로 넘겨 쓴다", file=sys.stderr)
            reports.append(old[0])
            cards += [c for c in prior["cards"] if c["date"] == date and c["slot"] == slot and c["card_id"] not in private_ids]
            continue
        reports.append({"date": date, "slot": slot, "file": rel, "cards": len(here),
                        "published": sum(C.publishable(c, C.claims_for(c["card_id"])) for c in here)})
    for c in everything:
        if not C.publishable(c, C.claims_for(c["card_id"])):
            continue   # 상태(반려 등)와 무관하게 발행 판정 하나로만 고른다
        cards.append({"card_id": c["card_id"], "date": c["date"], "slot": c["slot"], "title": c["titles"][0],
                      "category": c.get("category", ""), "badge": C.BADGE_KO[c["badge"]], "url": R.page_url(c["card_id"])})
    cards.sort(key=lambda c: str(c.get("card_id", "")))
    idx = {"schema": 1, "reports": reports, "cards": cards}
    errs = index_errors(idx)
    if errs:
        raise ValueError("만든 색인이 검사를 통과하지 못해 쓰지 않는다 — " + "; ".join(errs[:4]))
    return idx


def save_index(idx: dict, path: pathlib.Path | None = None) -> tuple[pathlib.Path, int]:
    errs = index_errors(idx)
    if errs:   # 스스로 만든 색인도 검사를 통과해야 저장한다
        raise ValueError("색인이 검사를 통과하지 못해 쓰지 않는다 — " + "; ".join(errs[:4]))
    path = pathlib.Path(path) if path else index_path()
    text = json.dumps(idx, ensure_ascii=False, indent=1) + "\n"   # 이스케이프하면 공개본 검사가 한글을 읽지 못한다
    _replace(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))
    return path, len(idx["cards"])


def write_index(path: pathlib.Path | None = None) -> tuple[pathlib.Path, int]:
    return save_index(build_index(path=path), path)
