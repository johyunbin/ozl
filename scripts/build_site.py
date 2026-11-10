#!/usr/bin/env python3
"""daily/ 의 발행본을 docs/daily/ 로 옮기고 「기록」 쪽(docs/daily/index.md)을 만든다 — MkDocs 빌드 직전에 부른다.

CI 에는 ozl 패키지도 private/ 도 없으므로 표준 라이브러리만 쓴다. 발행 카드 표는 daily/index.json 에서만 만든다
(그 파일은 `python -m ozl.research render` 가 publishable() 을 통과한 카드만 골라 쓴다).
- 발행본은 daily/**/*.md 를 docs/daily/ 에 평평하게 복사한다(이름이 겹치면 종료 코드 1)
- index.json 이 없으면 보고서 목록만 만들고 경고를 낸다
- index.json 이 있는데 모양이 틀리거나(schema·배열·필수 키·날짜/회차/card_id 형식), 색인의 보고서 파일이 없거나,
  카드의 자리표(<a id="am-01"></a>)가 없거나, 건수가 모순되거나 중복이 있으면 종료 코드 1. 파일은 있는데 색인에 없는 보고서는 목록에 넣고 경고만 낸다
불러오기만으로는 아무것도 하지 않는다.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys

REPORT_FILE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(am|pm|wk)\.md$")
SLOT_KO = {"am": "아침", "pm": "저녁", "wk": "주간"}
SLOT_ORDER = {"am": 0, "pm": 1, "wk": 2}


def _month(date: str) -> str:
    return f"{date[:4]}년 {int(date[5:7])}월"


def _cell(s: str) -> str:
    """표 칸에 넣을 글자 — 역슬래시를 먼저 막고, 링크 글자를 닫거나 칸을 나누는 [ ] | 를 이스케이프한다."""
    s = str(s).replace("\\", "\\\\")
    for ch in "[]|":
        s = s.replace(ch, "\\" + ch)
    return s.replace("\r", " ").replace("\n", " ")


DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SLOT = re.compile(r"am|pm|wk")
REPORT_KEYS = {"date": str, "slot": str, "file": str, "cards": int, "published": int}
CARD_KEYS = {"card_id": str, "date": str, "slot": str, "title": str, "category": str, "badge": str, "url": str}


def load_index(path: pathlib.Path) -> dict | None:
    """없으면 None. 있는데 JSON 이 아니면 ValueError — 없는 것과 깨진 것을 구분한다."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _entry_errors(kind: str, i: int, x, keys: dict) -> list[str]:
    if not isinstance(x, dict):
        return [f"{kind}[{i}] 가 객체가 아니다"]
    errs = [f"{kind}[{i}].{k} 가 없거나 형식이 다르다" for k, t in keys.items()
            if not isinstance(x.get(k), t) or isinstance(x.get(k), bool)]
    if errs:
        return errs
    date, slot = x["date"], x["slot"]
    if not DATE.fullmatch(date):
        errs.append(f"{kind}[{i}].date 형식 오류: {date!r}")
    if not SLOT.fullmatch(slot):
        errs.append(f"{kind}[{i}].slot 형식 오류: {slot!r}")
    if kind == "cards" and not re.fullmatch(rf"{re.escape(date)}-{re.escape(slot)}-\d{{2}}", x["card_id"]):
        errs.append(f"{kind}[{i}].card_id 가 <날짜>-<회차>-NN 이 아니다: {x['card_id']!r}")
    if kind == "reports" and not (x["file"].startswith("daily/") and x["file"].endswith(f"/{date}_{slot}.md") and ".." not in x["file"].split("/")):
        errs.append(f"{kind}[{i}].file 이 daily/…/{date}_{slot}.md 가 아니다: {x['file']!r}")
    return errs


def check_structure(idx) -> list[str]:
    """색인 모양 검사 — null·{}·잘못된 구조는 '없는 색인'으로 넘기지 않고 실패시킨다."""
    if not isinstance(idx, dict):
        return [f"최상위가 객체가 아니다({type(idx).__name__})"]
    errs = [] if idx.get("schema") == 1 and not isinstance(idx.get("schema"), bool) else [f"schema 가 1 이 아니다({idx.get('schema')!r})"]
    for kind, keys in (("reports", REPORT_KEYS), ("cards", CARD_KEYS)):
        if not isinstance(idx.get(kind), list):
            errs.append(f"{kind} 가 배열이 아니다")
            continue
        for i, x in enumerate(idx[kind]):
            errs += _entry_errors(kind, i, x, keys)
    return errs or check_counts(idx)


def check_counts(idx: dict) -> list[str]:
    """건수 모순과 중복 — 0 <= 발행 <= 카드, 회차별 색인 카드 수 = 그 회차 발행 수, card_id·(날짜, 회차) 보고서 유일.
    src/ozl/research/archive.py 의 index_errors() 와 같은 규칙이다(이 파일은 표준 라이브러리만 써서 따로 적었다)."""
    errs, seen_r, seen_c, per = [], set(), set(), {}
    for r in idx["reports"]:
        key = (r["date"], r["slot"])
        if not 0 <= r["published"] <= r["cards"]:
            errs.append(f"보고서 {key[0]} {key[1]} 건수 모순: 발행 {r['published']} · 카드 {r['cards']}")
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


def _inside(dst: pathlib.Path, name: str) -> pathlib.Path | None:
    p = (dst / name).resolve()
    return p if p.parent == dst.resolve() else None


def check_files(idx: dict, dst: pathlib.Path, reports: list[tuple[str, str, str]], root: pathlib.Path) -> tuple[list[str], list[str]]:
    """(오류, 경고). 색인의 보고서마다 file 경로 그대로 저장소의 daily/ 안에 있는지, 카드마다 docs/daily 의 보고서와
    자리표가 있는지 대조한다. 형식 검사를 통과한 색인만 넘긴다."""
    errs, warns, cache = [], [], {}
    daily = (root / "daily").resolve()
    for r in idx["reports"]:
        real = (root / r["file"]).resolve()
        if daily not in real.parents or not real.is_file():
            errs.append(f"reports: 색인의 file {r['file']} 가 저장소에 없다")

    def text_of(name: str):
        if name not in cache:
            p = _inside(dst, name)
            cache[name] = p.read_text(encoding="utf-8") if p and p.is_file() else None
        return cache[name]

    listed = set()
    for r in idx["reports"]:
        name = f"{r['date']}_{r['slot']}.md"
        listed.add(name)
        if _inside(dst, name) is None:
            errs.append(f"reports: {name} 가 docs/daily 밖을 가리킨다")
        elif text_of(name) is None:
            errs.append(f"reports: 색인에 있는 보고서 {r['file']} 가 없다")
    for _, _, name in reports:
        if name not in listed:
            warns.append(f"보고서 {name} 가 색인에 없다 — 목록에는 넣고 카드 수는 비운다")
    for c in idx["cards"]:
        cid, name = c["card_id"], f"{c['date']}_{c['slot']}.md"
        if _inside(dst, name) is None:
            errs.append(f"{cid}: {name} 가 docs/daily 밖을 가리킨다")
        elif text_of(name) is None:
            errs.append(f"{cid}: 보고서 {name} 가 없다")
        elif f'<a id="{cid[11:]}"></a>' not in text_of(name):
            errs.append(f"{cid}: {name} 에 자리표 <a id=\"{cid[11:]}\"></a> 가 없다")
    return errs, warns


def render_index(reports: list[tuple[str, str, str]], idx: dict | None) -> str:
    """reports = [(날짜, 회차, 파일 이름)] · idx = daily/index.json 내용(없으면 None)."""
    L = ["# 기록", ""]
    if not reports:
        return "\n".join(L + ["아직 발행된 보고서가 없습니다.", ""])
    counts = {(r.get("date"), r.get("slot")): r for r in (idx or {}).get("reports") or []}
    L += ["회차별 보고서와 공개를 승인한 카드를 달마다 모아 둡니다. 최근 것이 위에 옵니다.", ""]
    rs = sorted(reports, key=lambda t: (t[0], SLOT_ORDER[t[1]]), reverse=True)
    month = None
    for date, slot, name in rs:
        if _month(date) != month:
            if month is not None:
                L += [""]
            month = _month(date)
            L += [f"## {month}", ""]
        r = counts.get((date, slot))
        tail = f" · 카드 {r['cards']}장, 발행 {r['published']}장" if r else ""
        L += [f"- [{date} {SLOT_KO[slot]}]({name}){tail}"]
    L += [""]
    if idx is None:
        return "\n".join(L)
    # 회차는 최근 것부터, 한 회차 안에서는 카드 번호 순(정렬이 안정적이라 두 번 나눠 정렬한다)
    cards = sorted(idx.get("cards") or [], key=lambda c: c["card_id"])
    cards.sort(key=lambda c: (c["date"], SLOT_ORDER.get(c["slot"], 9)), reverse=True)
    if not cards:
        return "\n".join(L + ["아직 공개를 승인한 카드가 없습니다.", ""])
    month = None
    for c in cards:
        if _month(c["date"]) != month:
            if month is not None:
                L += [""]
            month = _month(c["date"])
            L += [f"## {month} 발행 카드", "", "| 날짜 | 제목 | 분야 | 배지 |", "|---|---|---|---|"]
        link = f"{c['date']}_{c['slot']}.md#{c['card_id'][11:]}"
        L += [f"| {c['date']} {SLOT_KO.get(c['slot'], c['slot'])} | [{_cell(c['title'])}]({link}) | {_cell(c.get('category', ''))} | {_cell(c.get('badge', ''))} |"]
    return "\n".join(L + [""])


def main(root: pathlib.Path | str | None = None) -> int:
    root = pathlib.Path(root) if root else pathlib.Path(__file__).resolve().parent.parent
    src, dst = root / "daily", root / "docs" / "daily"
    files = sorted(src.rglob("*.md")) if src.exists() else []
    names: dict[str, list[str]] = {}
    for f in files:
        names.setdefault(f.name, []).append(f.relative_to(root).as_posix())
    dup = {n: ps for n, ps in names.items() if len(ps) > 1 or n == "index.md"}
    if dup:   # 평평하게 복사하면 하나가 다른 하나를 덮어쓴다 — 쓰기 전에 멈춘다
        for n, ps in sorted(dup.items()):
            print(f"오류: docs/daily/{n} 로 겹치는 파일 — {', '.join(ps)}", file=sys.stderr)
        return 1
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    reports = []
    for f in files:
        shutil.copy2(f, dst / f.name)
        m = REPORT_FILE.match(f.name)
        if m:
            reports.append((f"{m.group(1)}-{m.group(2)}-{m.group(3)}", m.group(4), f.name))
    ipath = src / "index.json"
    try:
        idx = load_index(ipath)
    except (OSError, ValueError) as e:
        print(f"오류: daily/index.json 을 읽지 못했다 — {e}", file=sys.stderr)
        return 1
    if not ipath.exists():   # 내용이 null 인 색인과 파일이 없는 경우를 가른다 — null 은 아래 모양 검사에서 실패한다
        print("경고: daily/index.json 이 없다 — 보고서 목록만 만들고 발행 카드 표는 뺀다", file=sys.stderr)
    else:
        errs = check_structure(idx)
        warns: list[str] = []
        if not errs:
            errs, warns = check_files(idx, dst, reports, root)
        if errs:
            for e in errs:
                print(f"오류: daily/index.json — {e}", file=sys.stderr)
            return 1
        for w in warns:
            print(f"경고: {w}", file=sys.stderr)
    (dst / "index.md").write_text(render_index(reports, idx), encoding="utf-8")
    print(f"synced {len(files)} files · 보고서 {len(reports)}건 · 발행 카드 {len((idx or {}).get('cards') or [])}장")
    return 0


if __name__ == "__main__":
    sys.exit(main())
