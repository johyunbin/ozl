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
# 지문에서 빼는 칸은 정해진 자리만: line.updated_at 과 new·ongoing 항목의 계산 칸(본문에서 다시 계산해 싣는다).
ITEM_COMPUTED = ("verdict_summary", "hidden_claims")
DAY_KEYS = {"date", "revision", "made_at", "line", "new", "ongoing", "upcoming", "pre", "empty_note"}
LINE_KEYS = {"updated_at", "source_kinds_ok", "source_kinds_failed"}
ISSUE_ITEM_KEYS = {"issue_id", "status_line", "keyword", *ITEM_COMPUTED}
KEYWORD_ITEM_KEYS = {"keyword", "state"}
PRE_KEYS = {"keyword", "desc", "links", "flags"}
RESTORED_KEYS = {"date", "revision", "made_at", "label", "source_url", "items"}
RESTORED_ITEM_KEYS = {"rank", "article", "views"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def unit_file(unit: str, date: str) -> pathlib.Path:
    return paths.desk_root() / UNITS[unit] / f"{date}.yaml"


def rev_file(unit: str, date: str, rev: int) -> pathlib.Path:
    return paths.desk_root() / UNITS[unit] / "revisions" / date / f"r{rev}.yaml"


def all_dates(unit: str) -> list[str]:
    d = paths.desk_root() / UNITS[unit]
    return sorted(p.stem for p in d.glob("*.yaml") if DATE.match(p.stem)) if d.is_dir() else []


def unit_hash(unit: str, d: dict) -> str:
    """화제 목록은 line.updated_at 과 new·ongoing 항목의 계산 칸(판정 요약, 숨긴 주장 수)만 뺀다. 복원판은 전체.
    다른 깊이의 같은 이름 칸은 빼지 않는다 — 지문 밖 칸에 승인받지 않은 글을 실을 수 없게."""
    if unit == "restored" or not isinstance(d, dict):
        return digest._canon(d)
    x = copy.deepcopy(d)
    if isinstance(x.get("line"), dict):
        x["line"].pop("updated_at", None)
    for k in ("new", "ongoing"):
        for it in x.get(k) or [] if isinstance(x.get(k), list) else []:
            if isinstance(it, dict) and "issue_id" in it:
                for c in ITEM_COMPUTED:
                    it.pop(c, None)
    return digest._canon(x)


# ── 검사 ──────────────────────────────────────────────────────────────
def _text_errors(where: str, text: str, keyword: bool = False) -> list[str]:
    """화제 목록의 글 한 칸 — 문체, 범죄·비위 낱말, 판세 낱말, 수량(종류 검사를 받을 수 없으니 쓰지 않는다).
    키워드 칸(keyword=True)은 숫자가 이름의 일부인 표기(5G, 4대강)를 받는다 — numbers.keyword_qty."""
    from ozl.render import numbers as N

    from .numbers import keyword_qty, korean_qty
    e = [f"{where}: {m}" for m in style.text_errors("status_line", text)]
    if style.crime_words(text):
        e.append(f"{where}: {style.MSG_CRIME}")
    if style.poll_words(text):
        e.append(f"{where}: 화제 목록에는 판세를 쓰지 않는다(가림 표시가 없다)")
    if (keyword_qty(text) if keyword else (korean_qty(text) or any(t.kind != "cal" for t in N.claim_tokens(text)))):
        e.append(f"{where}: 화제 목록 줄에는 수량을 쓰지 않는다 — 수치는 기록 본문에서 종류와 함께 적는다")
    return e


def _item_errors(where: str, it) -> list[str]:
    if not isinstance(it, dict):
        return [f"{where}: 항목은 사전이다"]
    e = []
    if "issue_id" in it:
        if set(it) - ISSUE_ITEM_KEYS:
            e.append(f"{where}: 이슈 항목에 둘 수 없는 칸이 있다({', '.join(sorted(map(str, set(it) - ISSUE_ITEM_KEYS)))})")
        if not re.match(r"^i\d{8}-\d{2}$", str(it.get("issue_id"))):
            e.append(f"{where}.issue_id: 이슈 번호 꼴이 아니다")
        e += _text_errors(f"{where}.status_line", str(it.get("status_line") or ""))
        if "keyword" in it:                         # 공개 판이 없을 때 '정리 전' 항목으로 실린다
            e += _text_errors(f"{where}.keyword", str(it.get("keyword") or ""), keyword=True)
    elif set(it) - KEYWORD_ITEM_KEYS:
        e.append(f"{where}: 항목은 {{issue_id, status_line}} 또는 {{keyword, state: 정리 전}} 이다(둘 수 없는 칸이 있다)")
    elif cards._blank(it.get("keyword")) or it.get("state") != "정리 전":
        e.append(f"{where}: 항목은 {{issue_id, status_line}} 또는 {{keyword, state: 정리 전}} 이다")
    else:
        e += _text_errors(f"{where}.keyword", str(it.get("keyword")), keyword=True)
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
        if set(d) - RESTORED_KEYS:
            e.append(f"복원판에 둘 수 없는 칸이 있다({', '.join(sorted(map(str, set(d) - RESTORED_KEYS)))})")
        su = d.get("source_url")
        if su is not None and (not isinstance(su, str) or not re.match(r"^https?://[^/\s]+", su) or community_url(su)):
            e.append("source_url: http(s) 주소이고 커뮤니티 글이 아니다")
        items = d.get("items")
        if items is not None and not isinstance(items, list):
            e.append("items: 목록이다")
        for i, it in enumerate(items if isinstance(items, list) else []):
            if not (isinstance(it, dict) and not set(it) - RESTORED_ITEM_KEYS and isinstance(it.get("rank"), int)
                    and not isinstance(it.get("rank"), bool) and isinstance(it.get("article"), str) and not cards._blank(it.get("article"))
                    and isinstance(it.get("views"), int) and not isinstance(it.get("views"), bool)):
                e.append(f"items.{i}: 항목은 {{rank, article, views}} 이다(다른 칸을 두지 않는다)")
        return {"errors": e, "warnings": w}
    if set(d) - DAY_KEYS:
        e.append(f"화제 목록에 둘 수 없는 칸이 있다({', '.join(sorted(map(str, set(d) - DAY_KEYS)))})")
    if d.get("line") is not None and (not isinstance(d.get("line"), dict) or set(d["line"]) - LINE_KEYS):
        e.append("line: {updated_at, source_kinds_ok, source_kinds_failed} 이다")
    en = d.get("empty_note")
    if en is not None and (not isinstance(en, dict) or set(en) - {"new", "ongoing"}):
        e.append("empty_note: {new, ongoing} 이다")
    for k, v in (en.items() if isinstance(en, dict) else []):
        if isinstance(v, str) and v.strip():
            e += _text_errors(f"empty_note.{k}", v)
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
        if not isinstance(p, dict) or cards._blank(p.get("keyword")) or set(p) - PRE_KEYS:
            e.append(f"pre.{i}: 항목은 {{keyword, desc, links, flags}} 이다")
            continue
        if not set(p.get("flags") or []) & EXCLUDE_FLAGS:          # 공개용에서 빠지는 항목은 글을 내보내지 않는다
            for k in ("keyword", "desc"):
                e += _text_errors(f"pre.{i}.{k}", str(p.get(k) or ""), keyword=k == "keyword")
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
        code, msg = revisions.approver_error(by)       # 이름 규칙이 멱등 분기보다 먼저
        if code:
            return {"code": code, "msg": msg, "entry": None}
        man = revisions.load_manifest()
        pre = revisions.prior_approval(man, unit, date, rev, cur, request_id, rev_file(unit, date, rev).with_suffix(".approval.json"))
        if pre is not None:
            return pre
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
    if unit not in UNITS:
        return False, "공개할 수 있는 판이 없다", None
    for e in reversed(revisions.entries(man, unit, date)):
        rev = e.get("rev")
        if revisions.entry_error(man, unit, date, rev):   # 판 번호 꼴, 중복, 내림, 시험 승인, 빈 승인자·시각
            continue
        f = rev_file(unit, date, rev)
        try:
            d = model.load_yaml(f)
            appr = json.loads(f.with_suffix(".approval.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("revision") != rev or isinstance(d.get("revision"), bool) or d.get("date") != date:
            continue                                    # 고정 사본이 그 날짜·판이 아니다(다른 판을 옮겨 놓은 것)
        if unit_hash(unit, d) != e.get("content_hash") or appr != e or check_unit(unit, d, date)["errors"]:
            continue
        return True, "", rev
    return False, "공개할 수 있는 판이 없다", None


def load_fixed_unit(unit: str, date: str, rev: int) -> dict:
    return model.load_yaml(rev_file(unit, date, rev))


def public_day(d: dict, is_public_issue) -> dict:
    """공개용 화제 목록: 제외 표시가 붙은 미리 알림은 빼고, 공개 판이 없는 이슈 항목은 '정리 전'으로 바꾼다."""
    src = copy.deepcopy(d)
    out = {k: src[k] for k in DAY_KEYS if k in src}            # 정해진 칸만 — 모르는 칸은 싣지 않는다
    if isinstance(out.get("line"), dict):
        out["line"] = {k: v for k, v in out["line"].items() if k in LINE_KEYS}
    out["pre"] = [{k: p[k] for k in PRE_KEYS if k in p} for p in out.get("pre") or []
                  if isinstance(p, dict) and not set(p.get("flags") or []) & EXCLUDE_FLAGS]
    out["upcoming"] = [{k: u[k] for k in ("date", "what", "url") if k in u} for u in out.get("upcoming") or [] if isinstance(u, dict)]
    for k in ("new", "ongoing"):
        lst = []
        for it in out.get(k) or []:
            if not isinstance(it, dict):
                continue
            if "issue_id" in it and not is_public_issue(it["issue_id"]):
                lst.append({"keyword": it.get("keyword") or "", "state": "정리 전"})
            elif "issue_id" in it:
                lst.append({"issue_id": it["issue_id"], "status_line": it.get("status_line") or ""})
            else:
                lst.append({"keyword": it.get("keyword") or "", "state": it.get("state")})
        out[k] = lst
    return out
