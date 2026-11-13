"""게시 단위 셋 가운데 그날의 화제 목록과 복원판 — 형식 검사, 지문, 승인, 공개 판정(설계 10절). 이슈의 판은 revisions 가 맡는다.

화제 목록 = <자료 루트>/daily_lists/<날짜>.yaml, 복원판 = <자료 루트>/restored/<날짜>.yaml.
고정 사본은 각 폴더의 revisions/<날짜>/r<판>.yaml 과 r<판>.approval.json. 승인 규칙(판·해시 대조, 멱등, 시험·실제)은 이슈와 같다.
"""
from __future__ import annotations

import copy
import json
import pathlib
import re

from ozl.research import cards

from . import digest, model, paths, revisions, style
from .evidence import MSG_COMMUNITY, community_url

UNITS = {"day": "daily_lists", "restored": "restored"}
NEW_MAX, ONGOING_MAX = 4, 6
EXCLUDE_FLAGS = {"개인", "사생활", "범죄 의혹", "선거 판세"}
RESTORED_LABEL = "위키백과 조회로 본 그날의 관심 문서"
RESTORED_BANNED = re.compile(r"verdict|score|issue_id|trend|판정|점수")
HASH_SKIP = {"score", "trend", "bars7", "verdict_summary", "hidden_claims"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def unit_file(unit: str, date: str) -> pathlib.Path:
    return paths.desk_root() / UNITS[unit] / f"{date}.yaml"


def rev_file(unit: str, date: str, rev: int) -> pathlib.Path:
    return paths.desk_root() / UNITS[unit] / "revisions" / date / f"r{rev}.yaml"


def all_dates(unit: str) -> list[str]:
    d = paths.desk_root() / UNITS[unit]
    return sorted(p.stem for p in d.glob("*.yaml") if DATE.match(p.stem)) if d.is_dir() else []


def _strip(v, skip):
    if isinstance(v, dict):
        return {k: _strip(x, skip) for k, x in v.items() if k not in skip}
    if isinstance(v, list):
        return [_strip(x, skip) for x in v]
    return v


def unit_hash(unit: str, d: dict) -> str:
    """화제 목록은 line.updated_at 과 점수·계산 칸을 뺀다(본문에서 계산하는 판정 요약도 승인 대상이 아니다). 복원판은 전체."""
    if unit == "restored":
        return digest._canon(d)
    x = _strip(copy.deepcopy(d), HASH_SKIP)
    if isinstance(x.get("line"), dict):
        x["line"].pop("updated_at", None)
    return digest._canon(x)


# ── 검사 ──────────────────────────────────────────────────────────────
def _text_errors(where: str, text: str) -> list[str]:
    """화제 목록의 글 한 칸 — 문체, 범죄·비위 낱말, 판세 낱말, 수량(종류 검사를 받을 수 없으니 쓰지 않는다)."""
    from ozl.render import numbers as N

    from .numbers import korean_qty
    e = [f"{where}: {m}" for m in style.text_errors("status_line", text)]
    if style.crime_words(text):
        e.append(f"{where}: {style.MSG_CRIME}")
    if style.poll_words(text):
        e.append(f"{where}: 화제 목록에는 판세를 쓰지 않는다(가림 표시가 없다)")
    if korean_qty(text) or any(t.kind != "cal" for t in N.claim_tokens(text)):
        e.append(f"{where}: 화제 목록 줄에는 수량을 쓰지 않는다 — 수치는 기록 본문에서 종류와 함께 적는다")
    return e


def _item_errors(where: str, it) -> list[str]:
    if not isinstance(it, dict):
        return [f"{where}: 항목은 사전이다"]
    e = []
    if "issue_id" in it:
        if not re.match(r"^i\d{8}-\d{2}$", str(it.get("issue_id"))):
            e.append(f"{where}.issue_id: 이슈 번호 꼴이 아니다")
        e += _text_errors(f"{where}.status_line", str(it.get("status_line") or ""))
    elif cards._blank(it.get("keyword")) or it.get("state") != "정리 전":
        e.append(f"{where}: 항목은 {{issue_id, status_line}} 또는 {{keyword, state: 정리 전}} 이다")
    else:
        e += _text_errors(f"{where}.keyword", str(it.get("keyword")))
    return e


def check_unit(unit: str, d: dict, date: str | None = None) -> dict:
    """{errors, warnings}."""
    e, w = [], []
    if not isinstance(d, dict):
        return {"errors": ["맨 위가 사전이 아니다"], "warnings": []}
    if date and d.get("date") != date:
        e.append(f"date: 파일 이름의 날짜({date})와 다르다")
    if not cards._real_date(str(d.get("date"))):
        e.append("date: YYYY-MM-DD 가 아니다")
    rev = d.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        e.append("revision: 판 번호는 1 이상 정수다")
    if unit == "restored":
        if d.get("label") != RESTORED_LABEL:
            e.append(f"label: 복원판의 표시는 '{RESTORED_LABEL}' 로 고정이다")
        bad = [k for k in json.dumps(d, ensure_ascii=False, default=str).split('"') if RESTORED_BANNED.fullmatch(k)]
        if bad:
            e.append(f"복원판에는 판정, 점수, 이슈 번호 칸을 두지 않는다({', '.join(sorted(set(bad)))})")
        for i, it in enumerate(d.get("items") or []):
            if not (isinstance(it, dict) and isinstance(it.get("rank"), int) and not cards._blank(it.get("article"))
                    and isinstance(it.get("views"), int)):
                e.append(f"items.{i}: 항목은 {{rank, article, views}} 이다")
        return {"errors": e, "warnings": w}
    for k, mx in (("new", NEW_MAX), ("ongoing", ONGOING_MAX)):
        lst = d.get(k) or []
        if not isinstance(lst, list) or len(lst) > mx:
            e.append(f"{k}: {mx}개 이하다")
        for i, it in enumerate(lst if isinstance(lst, list) else []):
            e += _item_errors(f"{k}.{i}", it)
    line = d.get("line") if isinstance(d.get("line"), dict) else {}
    for k, v in line.items():
        for j, x in enumerate(v if isinstance(v, list) else [v]):
            if isinstance(x, str) and k != "updated_at":
                e += _text_errors(f"line.{k}.{j}", x)
    for i, u in enumerate(d.get("upcoming") or []):
        if not isinstance(u, dict) or set(u) - {"date", "what", "url"} or cards._blank(u.get("what")):
            e.append(f"upcoming.{i}: 항목은 {{date, what, url}} 이다")
            continue
        e += _text_errors(f"upcoming.{i}.what", str(u.get("what")))
        if community_url(u.get("url")):
            e.append(f"upcoming.{i}.url: {MSG_COMMUNITY}")
    for i, p in enumerate(d.get("pre") or []):
        if not isinstance(p, dict) or cards._blank(p.get("keyword")):
            e.append(f"pre.{i}: 항목은 {{keyword, desc, links, flags}} 이다")
            continue
        if not set(p.get("flags") or []) & EXCLUDE_FLAGS:          # 공개용에서 빠지는 항목은 글을 내보내지 않는다
            for k in ("keyword", "desc"):
                e += _text_errors(f"pre.{i}.{k}", str(p.get(k) or ""))
        else:
            e += [f"pre.{i}.desc: {m}" for m in style.text_errors("desc", str(p.get("desc") or ""))]
        for j, ln in enumerate(p.get("links") or []):
            if community_url((ln or {}).get("url") if isinstance(ln, dict) else ln):
                e.append(f"pre.{i}.links.{j}: {MSG_COMMUNITY}")
        if set(p.get("flags") or []) & EXCLUDE_FLAGS and not cards._blank(p.get("desc")):
            w.append(f"경고 pre.{i}.desc: 공개용에서 빠지는 항목({', '.join(sorted(set(p['flags']) & EXCLUDE_FLAGS))})인데 설명이 있다")
    return {"errors": e, "warnings": w}


# ── 승인과 공개 판정 ──────────────────────────────────────────────────
def load_unit(unit: str, date: str) -> dict:
    return model.load_yaml(unit_file(unit, date))


def approve_unit(unit: str, date: str, rev: int, h: str, by: str, request_id=None, now=None) -> dict:
    """{code, msg, entry} — 이슈 승인과 같은 규칙."""
    with paths.lock():
        if unit not in UNITS or not unit_file(unit, date).is_file():
            return {"code": 2, "msg": f"{unit}:{date} 작업본이 없다", "entry": None}
        d = load_unit(unit, date)
        if rev != d.get("revision"):
            return {"code": 3, "msg": f"요청한 판({rev})과 작업본의 판({d.get('revision')})이 다르다", "entry": None}
        cur = unit_hash(unit, d)
        if h != cur:
            return {"code": 3, "msg": "요청한 내용 해시가 지금 내용과 다르다 — 다시 보고 승인한다", "entry": None}
        man = revisions.load_manifest()
        old = revisions.entry(man, unit, date, rev)
        if old:
            if old.get("content_hash") == cur:
                return {"code": 0, "msg": f"{unit}:{date} {rev}판: 이미 승인됨", "entry": old}
            return {"code": 3, "msg": f"{unit}:{date} {rev}판: 같은 판이 다른 내용으로 이미 승인됐다", "entry": None}
        code, msg = revisions.approver_error(by)
        if code:
            return {"code": code, "msg": msg, "entry": None}
        errs = check_unit(unit, d, date)["errors"]
        if errs:
            return {"code": 1, "msg": "\n".join(errs), "entry": None}
        f = rev_file(unit, date, rev)
        if f.exists():
            return {"code": 3, "msg": f"고정 사본이 이미 있다: {f}", "entry": None}
        ent = {"unit": unit, "id": date, "rev": rev, "content_hash": cur, "approved_at": now or cards.now_kst(),
               "approved_by": by.strip(), "request_id": request_id}
        model.save_yaml(f, d)
        paths.write_atomic(f.with_suffix(".approval.json"), json.dumps(ent, ensure_ascii=False, indent=1) + "\n")
        man["entries"].append(ent)
        revisions.save_manifest(man)
        return {"code": 0, "msg": f"{unit}:{date} {rev}판 승인", "entry": ent}


def unit_publishable(unit: str, date: str, man: dict | None = None) -> tuple[bool, str, int | None]:
    """(참거짓, 사유, 판) — 내리지 않은 가장 큰 승인 판이 고정 사본·승인 기록·검사와 맞을 때만 참."""
    man = revisions.load_manifest() if man is None else man
    for e in reversed(revisions.entries(man, unit, date)):
        rev = e["rev"]
        if revisions.is_withdrawn(man, unit, date, rev):
            continue
        if e.get("approved_by") == revisions.TEST_BY:
            continue
        f = rev_file(unit, date, rev)
        try:
            d = model.load_yaml(f)
            appr = json.loads(f.with_suffix(".approval.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if unit_hash(unit, d) != e.get("content_hash") or appr != e or check_unit(unit, d, date)["errors"]:
            continue
        return True, "", rev
    return False, "공개할 수 있는 판이 없다", None


def load_fixed_unit(unit: str, date: str, rev: int) -> dict:
    return model.load_yaml(rev_file(unit, date, rev))


def public_day(d: dict, is_public_issue) -> dict:
    """공개용 화제 목록: 제외 표시가 붙은 미리 알림은 빼고, 공개 판이 없는 이슈 항목은 '정리 전'으로 바꾼다."""
    out = copy.deepcopy(d)
    out["pre"] = [p for p in out.get("pre") or [] if isinstance(p, dict) and not set(p.get("flags") or []) & EXCLUDE_FLAGS]
    for k in ("new", "ongoing"):
        lst = []
        for it in out.get(k) or []:
            if isinstance(it, dict) and "issue_id" in it and not is_public_issue(it["issue_id"]):
                lst.append({"keyword": it.get("keyword") or "", "state": "정리 전"})
            else:
                lst.append(it)
        out[k] = lst
    return out
