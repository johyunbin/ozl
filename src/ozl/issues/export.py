"""미리보기용·공개용 내보내기 — 설계 11절. 웹을 만드는 쪽이 읽는 JSON 묶음을 한 폴더에 쓴다.

공개용은 발행 목록에 있고 판 공개 판정(revisions.revision_publishable)이 참인 판만 싣는다. 본문은 고정 사본으로 다시 만들고
본문 해시가 승인 때와 다르면 그 판을 싣지 않고 종료 코드 4 로 알린다. 신고 연락처(OZL_REPORT_CONTACT)가 비면 아무것도 쓰지 않는다.
쓰기는 <out>.tmp-<pid> 에 다 만든 뒤 출력 검사(공개 제외 문장, captures 밖 사본, 시험 표시)를 통과하면 <out> 와 바꾼다.
미리보기용은 작업본까지 싣고 승인 기록과 발행 목록을 바꾸지 않는다.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile

from ozl.research import capture as K
from ozl.research import cards

from . import body as B
from . import digest, mask, model, paths, revisions, rules, style, units

CONTACT_ENV = "OZL_REPORT_CONTACT"
MIN_HIDDEN = 12
FEED_MAX = 50
TAKEDOWN_WHY = "OZL 이 이 기록의 게시를 내렸다."
MSG_CONTACT = "신고 연락처(OZL_REPORT_CONTACT)가 비어 있어 공개용으로 내보내지 않는다"
MSG_TEST_OUT = "시험 자료는 시험 폴더에만 내보낸다"
MSG_TEST_MIX = "발행 목록에 시험 승인이 섞여 있다 — 내보내지 않는다"


def _under(p: pathlib.Path, root: pathlib.Path) -> bool:
    p, root = p.resolve(), root.resolve()
    return p == root or root in p.parents


def _out_error(out: pathlib.Path) -> str:
    """출력 자리 검사 — 자료 루트·저장소 루트와 같거나 그 위이면 거부하고, 이미 있는 폴더는 이전 내보내기(meta.json)일 때만 바꾼다."""
    o = out.resolve()
    for root in (paths.desk_root(), paths.ROOT, paths.real_root()):
        r = pathlib.Path(root).resolve()
        if o == r or o in r.parents:
            return f"출력 자리({out})가 자료 폴더나 저장소 자체이거나 그 위다 — 다른 폴더를 준다"
    if out.exists():
        try:
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = None
        if not (isinstance(meta, dict) and meta.get("schema") == 1 and meta.get("mode") in ("preview", "public")):
            return f"출력 자리({out})가 이전 내보내기 폴더가 아니다(meta.json 없음) — 빈 자리를 준다"
    return ""


def stray_captures() -> list[str]:
    """근거 기록에 적힌 사본 해시와 같은 파일이 captures 폴더 밖에 있으면 그 경로들(6-20)."""
    top = paths.issues_dir()
    if not top.is_dir():
        return []
    shas = set()
    for y in top.rglob("*.yaml"):
        if y.parent.name != "evidence":
            continue
        try:
            ev = model.load_yaml(y)
        except (OSError, ValueError):
            continue
        v = ev.get("verification") if isinstance(ev.get("verification"), dict) else {}
        for s in (((v.get("capture") or {}) if isinstance(v.get("capture"), dict) else {}).get("sha256"),
                  ((ev.get("raw") or {}) if isinstance(ev.get("raw"), dict) else {}).get("sha256")):
            if isinstance(s, str) and len(s) == 64:
                shas.add(s)
    out = []
    for f in sorted(top.rglob("*")):
        if f.is_file() and "captures" not in f.relative_to(top).parts and K.sha256_file(f) in shas:
            out.append(str(f))
    return out


def _dump(root: pathlib.Path, rel: str, obj) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


def _index_row(b: dict, issue: dict | None, extra: dict | None = None) -> dict:
    row = {"id": b["id"], "slug": b["slug"], "title": b["title"], "topic_state": (issue or {}).get("topic_state"),
           "rev": b["rev"], "rev_at": b["rev_at"], "rev_line": b["rev_line"], "verdict_summary": B.verdict_summary(b),
           "hidden_claims": b["verdicts"]["hidden_claims"], "sensitive": b["sensitive"], "example": b["example"],
           "category": b["category"], "keywords": b["keywords"]}
    row.update(extra or {})
    return row


def _feed_kind(issue: dict, rev) -> str:
    cs = [c for c in issue.get("corrections") or [] if isinstance(c, dict) and c.get("rev") == rev]
    if any(c.get("kind") == "정정" for c in cs):
        return "정정"
    vh = [h for c in issue.get("claims") or [] if isinstance(c, dict) for h in c.get("verdict_history") or []
          if isinstance(h, dict) and h.get("rev") == rev]
    return "판정 변경" if vh or any(c.get("kind") == "판정 변경" for c in cs) else "새 판"


def _keywords(latest: dict[str, dict], dates: dict[str, list]) -> dict:
    out: dict[str, dict] = {}
    for iid, b in sorted(latest.items()):
        for k in b["keywords"]:
            row = out.setdefault(k, {"issues": [], "dates": [], "first_seen": None, "related": []})
            row["issues"].append(b["slug"])
            row["dates"] = sorted(set(row["dates"]) | set(dates.get(iid, [])))
            row["related"] = sorted(set(row["related"]) | (set(b["keywords"]) - {k}))
    for row in out.values():
        row["first_seen"] = row["dates"][0] if row["dates"] else None
    return out


def _public_issues(man: dict, now, msgs: list[str]) -> tuple[dict, int]:
    """{이슈 번호: [(판, 본문(가림 적용), 고정 이슈, 승인 기록)]}, 종료 코드(0|4)."""
    code, out, n_test = 0, {}, 0
    for iid in sorted({e["id"] for e in man["entries"] if e.get("unit") == "issue"}):
        for e in revisions.entries(man, "issue", iid):
            ok, why = revisions.revision_publishable(iid, e["rev"], man)
            if not ok:
                if why == revisions.REASON_BODY:
                    code = 4
                    msgs.append(f"{iid} {e['rev']}판: {revisions.REASON_BODY} — 싣지 않았다. 다시 승인받는다")
                elif why == revisions.MSG_TEST_NOT_PUBLIC:
                    n_test += 1
                elif why != "내렸다":
                    msgs.append(f"{iid} {e['rev']}판: 싣지 않음({why})")
                continue
            fi, fe, appr = revisions.load_fixed(iid, e["rev"])
            b = mask.apply(B.issue_body(fi, fe, rev_at=appr.get("approved_at", "")), now)
            score_p = revisions.rev_dir(iid, e["rev"]) / "score.json"
            b["trend"] = json.loads(score_p.read_text(encoding="utf-8")) if score_p.is_file() else None
            out.setdefault(iid, []).append((e["rev"], b, fi, appr))
    if n_test:
        msgs.append(f"시험 승인 {n_test}개 판은 공개용에 싣지 않았다")
    return out, code


def _days(mode: str, man: dict, latest: dict[str, dict], approved_dates: dict[str, list]) -> dict[str, dict]:
    pub = mode == "public"
    dates = set(units.all_dates("day")) | set(units.all_dates("restored")) | {d for v in approved_dates.values() for d in v}
    out = {}
    for date in sorted(dates):
        topics, restored, mentioned = None, None, set()
        if pub:
            ok, _, rev = units.unit_publishable("day", date, man)
            d = units.load_fixed_unit("day", date, rev) if ok else None
        else:
            d = units.load_unit("day", date) if units.unit_file("day", date).is_file() else None
        if d:
            d = units.public_day(d, lambda i: i in latest) if pub else d
            for k in ("new", "ongoing"):
                for it in d.get(k) or []:
                    if isinstance(it, dict) and it.get("issue_id") in latest:
                        b = latest[it["issue_id"]]
                        it["verdict_summary"], it["hidden_claims"] = B.verdict_summary(b), b["verdicts"]["hidden_claims"]
                        mentioned.add(it["issue_id"])
            topics = {k: d.get(k) for k in ("line", "new", "ongoing", "upcoming", "pre")}
        if pub:
            ok, _, rev = units.unit_publishable("restored", date, man)
            r = units.load_fixed_unit("restored", date, rev) if ok else None
        else:
            r = units.load_unit("restored", date) if units.unit_file("restored", date).is_file() else None
        if r:
            restored = {"label": r.get("label"), "items": r.get("items") or []}
        ids = sorted(mentioned | {i for i, ds in approved_dates.items() if date in ds and i in latest})
        records = [{"id": latest[i]["id"], "slug": latest[i]["slug"], "title": latest[i]["title"], "rev": latest[i]["rev"],
                    "verdict_summary": B.verdict_summary(latest[i])} for i in ids]
        if topics or restored or records:
            out[date] = {"date": date, "topics": topics, "records": records, "restored": restored}
    return out


def _preview_state(issue: dict, evs: dict, man: dict) -> str:
    lp = revisions.latest_public(issue["issue_id"], man)
    if lp is not None and (revisions.entry(man, "issue", issue["issue_id"], lp) or {}).get("content_hash") == digest.content_hash(issue, evs):
        return "게시"
    ws = issue.get("work_state")
    if ws == "게시 대기" and revisions.review_state(issue, evs) == "검토 대기":
        return "검토 대기"
    return ws or "작성 중"


def _build(mode: str, tmp: pathlib.Path, man: dict, now, contact: str, msgs: list[str]) -> tuple[int, list[tuple[str, str]], dict]:
    pub = mode == "public"
    code, hidden = 0, []
    latest: dict[str, dict] = {}
    approved_dates: dict[str, list] = {}
    index, search, feed, corrections, n_revs = [], [], [], [], 0
    if pub:
        pubs, code = _public_issues(man, now, msgs)
        for iid, revs in pubs.items():
            work = model.load_issue(iid) if paths.issue_file(iid).is_file() else {}
            for rev, b, fi, appr in revs:
                _dump(tmp, f"issues/{b['slug']}/r/{rev}.json", b)
                hidden += B.hidden_texts(fi)
                feed.append({"slug": b["slug"], "rev": rev, "at": appr.get("approved_at"), "kind": _feed_kind(fi, rev),
                             "title": b["title"], "rev_line": b["rev_line"]})
                approved_dates.setdefault(iid, []).append(str(appr.get("approved_at", ""))[:10])
                n_revs += 1
            rev, b, fi, appr = revs[-1]
            lb = dict(b, trend_now=work.get("trend") if work else b.get("trend"))
            latest[iid] = lb
            _dump(tmp, f"issues/{b['slug']}.json", lb)
            index.append(_index_row(b, work or fi))
    else:
        for iid in model.all_issue_ids():
            issue, evs = model.load_issue(iid), model.load_evidences(iid)
            b = B.issue_body(issue, evs)
            r = revisions.check_with_manifest(issue, evs, public=False, man=man)
            state = _preview_state(issue, evs, man)
            b["internal"] = {"publish_state": state, "content_hash": digest.content_hash(issue, evs),
                             "hidden": [f"{lst}.{it.get('id')}" for lst in model.ITEM_LISTS for it in issue.get(lst) or []
                                        if isinstance(it, dict) and not rules.item_public(issue, it)],
                             "errors": r["errors"], "warnings": r["warnings"]}
            b["trend_now"] = issue.get("trend")
            latest[iid] = b
            _dump(tmp, f"issues/{b['slug']}.json", b)
            index.append(_index_row(b, issue, {"publish_state": state}))
    for b in latest.values():
        search.append({"slug": b["slug"], "rev": b["rev"], "title": b["title"], "keywords": b["keywords"], "aliases": b["aliases"],
                       "so_far": b["so_far"]})
        corrections += [dict(c, slug=b["slug"]) for c in b["corrections"]]
    takedowns = [{"id": w["id"], "rev": w.get("rev"), "at": w.get("at")} for w in man["withdrawn"]]
    corrections += [{"id": w["id"], "rev": w.get("rev"), "at": w.get("at"), "kind": "내림", "why": TAKEDOWN_WHY}
                    for w in man["withdrawn"] if w.get("unit") == "issue"]
    days = _days(mode, man, latest, approved_dates)
    for date, d in days.items():
        _dump(tmp, f"days/{date}.json", d)
    _dump(tmp, "index.json", {"issues": index})
    _dump(tmp, "keywords.json", _keywords(latest, approved_dates))
    _dump(tmp, "corrections.json", {"items": corrections})
    _dump(tmp, "search.json", search)
    _dump(tmp, "feed.json", sorted(feed, key=lambda x: str(x["at"]), reverse=True)[:FEED_MAX])
    _dump(tmp, "takedowns.json", takedowns)
    counts = {"issues": len(latest), "revisions": n_revs, "days": sum(1 for d in days.values() if d["topics"]),
              "restored": sum(1 for d in days.values() if d["restored"])}
    meta = {"schema": 1, "made_at": str(now), "export_version": B.EXPORT_VERSION, "mode": mode, "report_contact": contact,
            "test": not paths.is_real_root(), "mask_rule_version": mask.RULE_VERSION, "counts": counts}
    _dump(tmp, "meta.json", meta)
    return code, hidden, counts


def _hidden_hits(tmp: pathlib.Path, hidden: list[tuple[str, str]]) -> list[str]:
    files = {p: style.norm(p.read_text(encoding="utf-8")) for p in tmp.rglob("*.json")}
    out = []
    for where, text in hidden:
        n = style.norm(text)
        if len(n) < MIN_HIDDEN:
            continue
        for p, body in files.items():
            if n in body:
                out.append(f"공개 제외 항목({where})의 문장이 공개용 출력({p.relative_to(tmp)})에 들어 있다")
    return out


def export(mode: str, out, now=None) -> dict:
    """{code, msgs, counts}. 0 성공, 1 출력 검사 실패, 2 연락처 없음·출력 자리 거부, 4 일부 판을 싣지 못함."""
    if mode not in ("preview", "public"):
        return {"code": 2, "msgs": [f"모드가 틀렸다: {mode}"], "counts": {}}
    now = now or cards.now_kst()
    if mask._parse(now) is None:
        return {"code": 2, "msgs": [f"--now 시각을 읽지 못했다: {now} (예: 2099-04-05T10:00:00+09:00)"], "counts": {}}
    out = pathlib.Path(out)
    why = _out_error(out)
    if why:
        return {"code": 2, "msgs": [why], "counts": {}}
    if not paths.is_real_root() and not (_under(out, paths.desk_root()) or _under(out, pathlib.Path(tempfile.gettempdir()))):
        return {"code": 2, "msgs": [MSG_TEST_OUT], "counts": {}}
    contact = os.environ.get(CONTACT_ENV, "").strip()
    if mode == "public" and not contact:
        return {"code": 2, "msgs": [MSG_CONTACT], "counts": {}}
    man = revisions.load_manifest()
    if mode == "public" and paths.is_real_root() and any(e.get("approved_by") == revisions.TEST_BY for e in man["entries"]):
        return {"code": 1, "msgs": [MSG_TEST_MIX], "counts": {}}
    stray = stray_captures()
    if stray:
        return {"code": 1, "msgs": [f"원문 사본이 captures 폴더 밖에 있다: {s}" for s in stray], "counts": {}}
    tmp = out.parent / f"{out.name}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    msgs: list[str] = []
    try:
        code, hidden, counts = _build(mode, tmp, man, now, contact, msgs)
        bad = _hidden_hits(tmp, hidden) if mode == "public" else []
        if paths.is_real_root() and json.loads((tmp / "meta.json").read_text(encoding="utf-8"))["test"]:
            bad.append("실제 폴더의 출력에 시험 표시가 붙었다")
        if bad:
            shutil.rmtree(tmp, ignore_errors=True)
            return {"code": 1, "msgs": msgs + bad, "counts": counts}
        if out.exists():
            old = out.parent / f"{out.name}.old-{os.getpid()}"
            out.rename(old)
            tmp.rename(out)
            shutil.rmtree(old, ignore_errors=True)
        else:
            tmp.rename(out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {"code": code, "msgs": msgs, "counts": counts}
