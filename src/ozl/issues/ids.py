"""번호 규칙과 발급 대장.

이슈 `i20261114-01` · 근거 `i20261114-01-e3` · 항목 `c1`·`f1`·`w1`·`s1`·`g1`·`q1`(작은 주장 `p1`, 검토 `r1`).
대장 `<자료 루트>/issues/issued_ids.json` 은 옛 카드 대장(private/desk/issued_ids.json)과 다른 파일이다.
한번 준 번호는 파일을 지워도 다시 주지 않는다. 대장을 읽지 못하면 예외로 멈춘다(빈 대장으로 넘기지 않는다).
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from . import paths

ISSUE_ID = re.compile(r"^i(\d{4})(\d{2})(\d{2})-(\d{2})$")
EVIDENCE_ID = re.compile(r"^(i\d{8}-\d{2})-e([1-9]\d{0,3})$")
ITEM_ID = re.compile(r"^[cpfwsgqr][1-9]\d{0,2}$")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+){0,7}$")
SLUG_LEN = (3, 60)
MAX_PER_DAY = 99
EMPTY = {"schema": 1, "issues": [], "evidence": {}, "items": {}}


def issue_id_ok(s) -> bool:
    m = ISSUE_ID.match(s) if isinstance(s, str) else None
    if not m or m.group(4) == "00":
        return False
    try:
        datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return False
    return True


def evidence_id_ok(s, issue_id: str | None = None) -> bool:
    m = EVIDENCE_ID.match(s) if isinstance(s, str) else None
    return bool(m) and issue_id_ok(m.group(1)) and (issue_id is None or m.group(1) == issue_id)


def item_id_ok(s, kind: str | None = None) -> bool:
    return isinstance(s, str) and bool(ITEM_ID.match(s)) and (kind is None or s[0] == kind)


def slug_error(s) -> str:
    """주소 이름의 모양 오류(빈 글이면 맞다)."""
    if not isinstance(s, str) or not SLUG.match(s):
        return "주소 이름은 영문 소문자와 숫자를 하이픈으로 이은 꼴(낱말 8개까지)이다"
    if not SLUG_LEN[0] <= len(s) <= SLUG_LEN[1]:
        return f"주소 이름은 {SLUG_LEN[0]}~{SLUG_LEN[1]}자다(지금 {len(s)}자)"
    return ""


# ── 대장 ──────────────────────────────────────────────────────────────
def load_ledger() -> dict:
    """대장이 없으면 빈 대장. 있는데 읽지 못하거나 모양이 틀리면 예외."""
    p = paths.ledger_file()
    if not p.exists():
        return json.loads(json.dumps(EMPTY))
    d = json.loads(p.read_text(encoding="utf-8"))
    if not (isinstance(d, dict) and d.get("schema") == 1 and isinstance(d.get("issues"), list)
            and isinstance(d.get("evidence"), dict) and isinstance(d.get("items"), dict)):
        raise ValueError(f"발급 대장의 모양이 틀렸다: {p}")
    return d


def _save_ledger(d: dict) -> None:
    paths.write_atomic(paths.ledger_file(), json.dumps(d, ensure_ascii=False, indent=1) + "\n")


def next_issue_ids(date: str, n: int = 1) -> list[str]:
    """그날의 이슈 번호 n개. 대장과 실제 폴더 둘 다 보고 그 최댓값 + 1 부터 준다."""
    with paths.lock():
        return next_issue_ids_locked(date, n)


def next_issue_ids_locked(date: str, n: int = 1) -> list[str]:
    """next_issue_ids 의 본체 — 부르는 쪽이 이미 paths.lock() 을 잡고 있을 때 쓴다(잠금은 겹쳐 걸지 않는다)."""
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError(f"날짜 꼴이 틀렸다: {date}") from None
    if n < 1:
        raise ValueError("개수는 1 이상이다")
    prefix = "i" + d.strftime("%Y%m%d") + "-"
    led = load_ledger()
    used = {int(i[-2:]) for i in led["issues"] if isinstance(i, str) and i.startswith(prefix) and ISSUE_ID.match(i)}
    if paths.issues_dir().is_dir():
        used |= {int(p.name[-2:]) for p in paths.issues_dir().glob(prefix + "*") if ISSUE_ID.match(p.name)}
    start = max(used, default=0) + 1
    if start + n - 1 > MAX_PER_DAY:
        raise ValueError(f"{prefix}NN 번호가 {MAX_PER_DAY} 를 넘는다")
    out = [f"{prefix}{k:02d}" for k in range(start, start + n)]
    led["issues"] += out
    _save_ledger(led)
    return out


def next_evidence_ids(issue_id: str, n: int = 1) -> list[str]:
    if not issue_id_ok(issue_id) or n < 1:
        raise ValueError(f"이슈 번호나 개수가 틀렸다: {issue_id} {n}")
    with paths.lock():
        led = load_ledger()
        if issue_id not in led["issues"]:
            raise ValueError(f"대장에 없는 이슈 번호다: {issue_id}")
        top = int(led["evidence"].get(issue_id, 0))
        d = paths.evidence_dir(issue_id)
        if d.is_dir():
            for p in d.glob("*.yaml"):
                m = EVIDENCE_ID.match(p.stem)
                if m and m.group(1) == issue_id:
                    top = max(top, int(m.group(2)))
        out = [f"{issue_id}-e{k}" for k in range(top + 1, top + n + 1)]
        led["evidence"][issue_id] = top + n
        _save_ledger(led)
    return out


def _items_in_file(issue_id: str, kind: str) -> int:
    from .model import ITEM_LISTS, load_yaml
    p = paths.issue_file(issue_id)
    if not p.is_file():
        return 0
    issue = load_yaml(p)
    lst = next((k for k, v in ITEM_LISTS.items() if v == kind), None)
    nums = [int(it["id"][1:]) for it in issue.get(lst) or [] if isinstance(it, dict) and item_id_ok(it.get("id"), kind)] if lst else []
    return max(nums, default=0)


def next_item_ids(issue_id: str, kind: str, n: int = 1) -> list[str]:
    from .model import LEDGER_KINDS
    if kind not in LEDGER_KINDS or n < 1:
        raise ValueError(f"항목 종류는 {', '.join(LEDGER_KINDS)} 가운데 하나다: {kind}")
    with paths.lock():
        led = load_ledger()
        if issue_id not in led["issues"]:
            raise ValueError(f"대장에 없는 이슈 번호다: {issue_id}")
        items = led["items"].setdefault(issue_id, {})
        top = max(int(items.get(kind, 0)), _items_in_file(issue_id, kind))
        if top + n > 999:
            raise ValueError(f"항목 번호가 999 를 넘는다: {kind}")
        out = [f"{kind}{k}" for k in range(top + 1, top + n + 1)]
        items[kind] = top + n
        _save_ledger(led)
    return out


def ledger_errors(issue: dict, evidence_ids, led: dict | None = None) -> list[tuple[str, str]]:
    """issue.yaml 의 번호가 대장에 있는가(대장보다 큰 번호는 '대장에 없는 번호'). [(칸 경로, 문구)]."""
    from .model import ITEM_LISTS
    led = load_ledger() if led is None else led
    iid = issue.get("issue_id")
    errs: list[tuple[str, str]] = []
    if iid not in led["issues"]:
        return [("issue_id", "대장에 없는 번호다 — 번호는 ids 명령으로만 받는다")]
    top_ev = int(led["evidence"].get(iid, 0))
    for e in evidence_ids:
        m = EVIDENCE_ID.match(e or "")
        if m and int(m.group(2)) > top_ev:
            errs.append((f"evidence.{e}", "대장에 없는 번호다 — 번호는 ids 명령으로만 받는다"))
    items = led["items"].get(iid, {})
    for lst, kind in ITEM_LISTS.items():
        for it in issue.get(lst) or []:
            if isinstance(it, dict) and item_id_ok(it.get("id"), kind) and int(it["id"][1:]) > int(items.get(kind, 0)):
                errs.append((f"{lst}.{it['id']}", "대장에 없는 번호다 — 번호는 ids 명령으로만 받는다"))
    return errs
