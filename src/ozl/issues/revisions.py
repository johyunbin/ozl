"""판 고정 사본, 발행 목록, 승인(멱등), 내림, 판 공개 판정, 검토 조건 — 설계 9절.

발행 목록(<자료 루트>/issues/manifest.json)이 게시와 내림을 정한다. 승인은 판 번호와 내용 해시를 함께 받고 지금 작업본과 다르면 거부한다.
같은 승인 요청이 두 번 와도 발행 목록에는 한 줄만 생긴다. 시험 폴더에서는 승인한 쪽을 '시험'으로만, 실제 폴더에서는 '시험'을 받지 않는다.
승인한 쪽이 '시험'인 판은 어느 폴더에서도 공개 판정이 거짓이다(공개용 내보내기에 나가지 않는다).
check 에 발행 목록이 있어야 하는 검사(승인 뒤 판 번호, 게시한 주소 이름, 게시 대기의 검토 조건)를 더하는 감싼 함수도 여기 둔다.
"""
from __future__ import annotations

import json
import pathlib
import shutil

from ozl.research import capture as K
from ozl.research import cards

from . import body as B
from . import check, digest, model, paths, rules
from . import evidence as EV

TEST_BY = "시험"
EMPTY = {"schema": 1, "entries": [], "withdrawn": []}
REASON_BODY = "다시 만든 본문이 승인 때와 다르다"
MSG_TEST_IN_REAL = "시험 승인은 실제 발행 목록에 넣지 않는다"
MSG_REAL_IN_TEST = "시험 폴더에서는 승인한 쪽을 '시험'으로만 적는다"
MSG_SAME_REV = "승인된 판과 내용이 다른데 판 번호가 같다 — 판 번호를 올린다"
MSG_TEST_NOT_PUBLIC = "시험 승인은 공개용 출력에 싣지 않는다"
MSG_SLUG = "게시한 주소 이름은 바꾸지 않는다(옛 이름은 aliases 로)"
MSG_REVIEW = "게시 대기인데 검토 조건(다른 모델의 문장 대조, 다른 계열의 해석 점검)을 채우지 못했다"


# ── 발행 목록 ─────────────────────────────────────────────────────────
def load_manifest() -> dict:
    p = paths.manifest_file()
    if not p.exists():
        return json.loads(json.dumps(EMPTY))
    d = json.loads(p.read_text(encoding="utf-8"))
    if not (isinstance(d, dict) and d.get("schema") == 1 and isinstance(d.get("entries"), list) and isinstance(d.get("withdrawn"), list)):
        raise ValueError(f"발행 목록의 모양이 틀렸다: {p}")
    return d


def save_manifest(d: dict) -> None:
    paths.write_atomic(paths.manifest_file(), json.dumps(d, ensure_ascii=False, indent=1) + "\n")


def entries(man: dict, unit: str, uid: str) -> list[dict]:
    return sorted([e for e in man["entries"] if e.get("unit") == unit and e.get("id") == uid], key=lambda e: int(e.get("rev") or 0))


def entry(man: dict, unit: str, uid: str, rev: int) -> dict | None:
    return next((e for e in entries(man, unit, uid) if e.get("rev") == rev), None)


def is_withdrawn(man: dict, unit: str, uid: str, rev: int | None) -> bool:
    """판을 지정한 내림은 그 판에, 판 없는 내림(rev: null)은 내릴 때 승인돼 있던 판(upto_rev 이하)에 적용한다 — 그 뒤 판을 올려
    다시 승인하면 되살아난다(설계 9-2). upto_rev 가 없는 옛 줄은 모든 판에 적용한다. rev=None 으로 물으면 가장 큰 판을 본다."""
    if rev is None:
        ents = entries(man, unit, uid)
        rev = int(ents[-1]["rev"]) if ents else None
    for w in man["withdrawn"]:
        if w.get("unit") != unit or w.get("id") != uid:
            continue
        if w.get("rev") is not None and w.get("rev") == rev:
            return True
        if w.get("rev") is None and (rev is None or not isinstance(w.get("upto_rev"), int) or rev <= w["upto_rev"]):
            return True
    return False


def approver_error(by: str) -> tuple[int, str]:
    """(종료 코드, 문구) — 승인한 쪽 이름의 시험·실제 규칙(6-12)."""
    if cards._blank(by):
        return 2, "승인한 쪽(--by)을 적는다"
    if paths.is_real_root() and by.strip() == TEST_BY:
        return 2, MSG_TEST_IN_REAL
    if not paths.is_real_root() and by.strip() != TEST_BY:
        return 2, MSG_REAL_IN_TEST
    return 0, ""


def rev_dir(issue_id: str, rev: int) -> pathlib.Path:
    return paths.issue_dir(issue_id) / "revisions" / f"r{rev}"


def snapshot_file(issue_id: str, h: str) -> pathlib.Path:
    return paths.issue_dir(issue_id) / "snapshots" / f"{h}.yaml"


# ── 검토 ──────────────────────────────────────────────────────────────
def _same(a, b) -> bool:
    return " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold()


def notes_dir(issue_id: str) -> pathlib.Path:
    return paths.issue_dir(issue_id) / "reviews"


def _notes_ok(issue_id, r: dict) -> bool:
    """검토 줄의 검토 원문(notes_path)이 이 이슈의 reviews 폴더에 그대로 있는가(적힌 해시와 같은가)."""
    if not isinstance(issue_id, str) or cards._blank(r.get("notes_path")) or cards._blank(r.get("notes_sha256")):
        return False
    d = notes_dir(issue_id).resolve()
    f = (paths.issue_dir(issue_id) / str(r["notes_path"])).resolve()
    return d in f.parents and f.is_file() and f.stat().st_size > 0 and K.sha256_file(f) == r["notes_sha256"]


def _full(reviews: list, h: str, drafted_by) -> bool:
    cmp = any(r.get("kind") == "문장 대조" and r.get("family") == "anthropic" and not _same(r.get("by_model"), drafted_by)
              and r.get("result") == "통과" and r.get("content_hash") == h for r in reviews)
    itp = any(r.get("kind") == "해석 점검" and r.get("family") not in (None, "anthropic") and r.get("result") == "통과"
              and r.get("content_hash") == h for r in reviews)
    return cmp and itp


def review_state(issue: dict, evidences: dict) -> str:
    """'검토 완료' | '검토 대기' — 설계 9-4. 이어받기(수정 확인)는 바뀐 칸이 모두 지적한 칸 안일 때만 받는다."""
    reviews = [r for r in issue.get("reviews") or [] if isinstance(r, dict) and _notes_ok(issue.get("issue_id"), r)]
    drafted = (issue.get("production") or {}).get("drafted_by") if isinstance(issue.get("production"), dict) else None
    h = digest.content_hash(issue, evidences)
    if _full(reviews, h, drafted):
        return "검토 완료"
    by_id = {r.get("id"): r for r in reviews}
    for r in reviews:
        after = r.get("after_hash") or r.get("content_hash")
        if not (r.get("kind") == "수정 확인" and r.get("family") == "anthropic" and not _same(r.get("by_model"), drafted)
                and r.get("result") == "통과" and after == h and r.get("before_hash")):
            continue
        hb = r["before_hash"]
        snap = snapshot_file(issue.get("issue_id"), hb)
        if not _full(reviews, hb, drafted) or not snap.is_file():
            continue
        fields = {str(f.get("field")) for a in r.get("addresses") or [] for f in (by_id.get(a) or {}).get("findings") or []
                  if isinstance(f, dict) and f.get("field")}
        changed = digest.changed_paths(model.load_yaml(snap), digest.snapshot_view(issue, evidences))
        if all(any(p == f or p.startswith(f + ".") for f in fields) for p in changed):
            return "검토 완료"
    return "검토 대기"


def add_review(issue_id: str, kind: str, by_model: str, family: str, result: str, findings=None, before_hash=None,
               addresses=None, notes_path="", now=None) -> dict:
    """검토 한 줄을 더하고 그 내용의 사본(snapshots/<내용 해시>.yaml)을 남긴다. 검토 번호 r 는 여기서 센다."""
    issue, evs = model.load_issue(issue_id), model.load_evidences(issue_id)
    if kind not in model.REVIEW_KINDS or family not in model.REVIEW_FAMILIES or result not in model.REVIEW_RESULTS:
        raise ValueError("검토의 kind·family·result 가 허용 값이 아니다")
    if cards._blank(by_model):
        raise ValueError("검토한 모델(by_model)을 적는다")
    d = notes_dir(issue_id).resolve()
    f = pathlib.Path(notes_path).resolve() if not cards._blank(notes_path) else None
    if f is None or d not in f.parents or not f.is_file() or f.stat().st_size == 0:
        raise ValueError(f"검토 원문(--notes-path)은 {d} 안의 비어 있지 않은 파일이다 — 검토한 쪽의 원문을 먼저 저장한다")
    notes_rel, notes_sha = str(f.relative_to(paths.issue_dir(issue_id).resolve())), K.sha256_file(f)
    h = digest.content_hash(issue, evs)
    nums = [int(str(r.get("id"))[1:]) for r in issue.get("reviews") or [] if isinstance(r, dict) and str(r.get("id", "")).startswith("r")
            and str(r.get("id"))[1:].isdigit()]
    row = {"id": f"r{max(nums, default=0) + 1}", "kind": kind, "by_model": by_model, "family": family, "at": now or cards.now_kst(),
           "content_hash": h, "result": result, "findings": list(findings or []), "notes_path": notes_rel, "notes_sha256": notes_sha}
    if before_hash:
        row["before_hash"] = before_hash
    if addresses:
        row["addresses"] = list(addresses)
    snap = snapshot_file(issue_id, h)
    if not snap.exists():
        model.save_yaml(snap, digest.snapshot_view(issue, evs))
    issue.setdefault("reviews", []).append(row)
    model.save_issue(issue)
    return row


# ── check 감싼 함수 ───────────────────────────────────────────────────
def manifest_errors(issue: dict, evidences: dict, man: dict) -> list[str]:
    iid = issue.get("issue_id")
    out = []
    ents = entries(man, "issue", iid)
    e = entry(man, "issue", iid, issue.get("revision"))
    if e and e.get("content_hash") != digest.content_hash(issue, evidences):
        out.append(f"{iid} revision: {MSG_SAME_REV}")
    if ents and ents[0].get("slug") != issue.get("slug"):
        out.append(f"{iid} slug: {MSG_SLUG}")
    if issue.get("work_state") == "게시 대기" and review_state(issue, evidences) == "검토 대기":
        out.append(f"{iid} reviews: {MSG_REVIEW}")
    return out


def check_with_manifest(issue: dict, evidences: dict, public: bool = False, articles=(), man: dict | None = None) -> dict:
    r = check.check_issue(issue, evidences, public=public, articles=articles)
    try:
        man = load_manifest() if man is None else man
    except (ValueError, OSError, json.JSONDecodeError) as e:
        r["errors"].append(f"{issue.get('issue_id')} manifest: 발행 목록을 읽지 못했다 — {e}")
        return r
    r["errors"] += manifest_errors(issue, evidences, man)
    return r


def check_ids(issue_ids: list[str], public: bool = False, articles=()) -> dict[str, dict]:
    out = check.check_ids(issue_ids, public=public, articles=articles)
    try:
        man = load_manifest()
    except (ValueError, OSError, json.JSONDecodeError) as e:
        for r in out.values():
            r["errors"].append(f"발행 목록을 읽지 못했다 — {e}")
        return out
    for iid, r in out.items():
        try:
            issue = model.load_issue(iid)
        except (OSError, ValueError):
            continue   # 읽지 못한 것은 check 가 이미 오류로 냈다
        if issue.get("issue_id") == iid:
            r["errors"] += manifest_errors(issue, model.load_evidences(iid), man)
    return out


# ── 승인 ──────────────────────────────────────────────────────────────
def _fixed_copy(issue_id: str, rev: int, issue: dict, evs: dict, cited: list[str], tmp: pathlib.Path) -> None:
    final_caps = rev_dir(issue_id, rev) / "captures"
    model.save_yaml(tmp / "issue.yaml", issue)
    for eid in cited:
        ev = evs[eid]
        cap = ((ev.get("verification") or {}).get("capture")) if isinstance(ev.get("verification"), dict) else None
        if isinstance(cap, dict) and not cards._blank(cap.get("path")):
            src_dir = cards._resolve(cap["path"]).parent
            dst = tmp / "captures" / eid
            shutil.copytree(src_dir, dst)
            if K.sha256_file(dst / cards._resolve(cap["path"]).name) != cap.get("sha256"):
                raise ValueError(f"{eid}: 고정 사본으로 옮긴 원문 사본의 해시가 기록과 다르다")
        model.save_yaml(tmp / "evidence" / f"{eid}.yaml", EV.with_capture_dir(ev, final_caps))


def load_fixed(issue_id: str, rev: int) -> tuple[dict, dict, dict]:
    d = rev_dir(issue_id, rev)
    return (model.load_yaml(d / "issue.yaml"), model.load_evidences(issue_id, d / "evidence"),
            json.loads((d / "approval.json").read_text(encoding="utf-8")))


def approve(issue_id: str, rev: int, content_hash: str, by: str, request_id=None, now=None) -> dict:
    """{code, msg, entry}. 0 승인(또는 이미 승인), 1 검사·검토 미충족, 2 사용 오류·시험/실제 규칙, 3 판·해시 충돌."""
    with paths.lock():
        if not paths.issue_file(issue_id).is_file():
            return {"code": 2, "msg": f"{issue_id}: 작업본이 없다", "entry": None}
        issue, evs = model.load_issue(issue_id), model.load_evidences(issue_id)
        if rev != issue.get("revision"):
            return {"code": 3, "msg": f"요청한 판({rev})과 작업본의 판({issue.get('revision')})이 다르다", "entry": None}
        h = digest.content_hash(issue, evs)
        if content_hash != h:
            return {"code": 3, "msg": "요청한 내용 해시가 지금 내용과 다르다 — 다시 보고 승인한다", "entry": None}
        man = load_manifest()
        old = entry(man, "issue", issue_id, rev)
        if old:
            if old.get("content_hash") == h:
                return {"code": 0, "msg": f"{issue_id} {rev}판: 이미 승인됨", "entry": old}
            return {"code": 3, "msg": f"{issue_id} {rev}판: 같은 판이 다른 내용으로 이미 승인됐다 — 판 번호를 올린다", "entry": None}
        code, msg = approver_error(by)
        if code:
            return {"code": code, "msg": msg, "entry": None}
        why = check_with_manifest(issue, evs, public=True, man=man)["errors"]
        if issue.get("work_state") != "게시 대기":
            why.append(f"{issue_id} work_state: 작업 상태가 '게시 대기'가 아니다({issue.get('work_state')})")
        if review_state(issue, evs) != "검토 완료":
            why.append(f"{issue_id} reviews: 검토 조건을 채우지 못했다(검토 대기)")
        if (issue.get("publish") or {}).get("state") != "게시 가능":
            why.append(f"{issue_id} publish.state: 게시 가부가 '게시 가능'이 아니다")
        if why:
            return {"code": 1, "msg": "\n".join(dict.fromkeys(why)), "entry": None}
        at = now or cards.now_kst()
        body = B.issue_body(issue, evs, rev_at=at)
        cited = [e for e in digest.cited(issue, evs) if e in evs]
        final = rev_dir(issue_id, rev)
        if final.exists():
            return {"code": 3, "msg": f"{issue_id} {rev}판: 고정 사본 폴더가 이미 있다({final})", "entry": None}
        tmp = final.parent / f".r{rev}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        tr = issue.get("trend") if isinstance(issue.get("trend"), dict) else {}
        score = {k: tr.get(k) for k in ("score", "bars7", "asof", "formula_version")}
        prev = [e for e in entries(man, "issue", issue_id) if int(e["rev"]) < rev]
        prev_issue = model.load_yaml(rev_dir(issue_id, prev[-1]["rev"]) / "issue.yaml") if prev else None
        ent = {"unit": "issue", "id": issue_id, "slug": issue.get("slug"), "rev": rev, "content_hash": h,
               "evidence_hash": digest.evidence_hash(issue, evs), "body_hash": digest.body_hash(body),
               "score_asof": score.get("asof"), "formula_version": score.get("formula_version"), "export_version": B.EXPORT_VERSION,
               "approved_at": at, "approved_by": by.strip(), "request_id": request_id}
        approval = dict(ent, changed_fields=digest.changed_fields(prev_issue, issue))
        approval.pop("unit")
        approval["issue_id"] = approval.pop("id")
        try:
            _fixed_copy(issue_id, rev, issue, evs, cited, tmp)
            paths.write_atomic(tmp / "score.json", json.dumps(score, ensure_ascii=False, indent=1) + "\n")
            paths.write_atomic(tmp / "approval.json", json.dumps(approval, ensure_ascii=False, indent=1) + "\n")
            tmp.replace(final)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        fi, fe, _ = load_fixed(issue_id, rev)
        if digest.body_hash(B.issue_body(fi, fe, rev_at=at)) != ent["body_hash"]:
            shutil.rmtree(final, ignore_errors=True)
            return {"code": 1, "msg": f"{issue_id} {rev}판: 고정 사본으로 다시 만든 본문이 작업본과 다르다 — 승인하지 않았다", "entry": None}
        man["entries"].append(ent)
        save_manifest(man)
        issue.setdefault("history", []).append({"at": at, "event": f"{rev}판 승인({by.strip()})"})
        model.save_issue(issue)
        return {"code": 0, "msg": f"{issue_id} {rev}판 승인", "entry": ent}


# ── 판 공개 판정 ──────────────────────────────────────────────────────
def revision_publishable(issue_id: str, rev: int, man: dict | None = None) -> tuple[bool, str]:
    man = load_manifest() if man is None else man
    e = entry(man, "issue", issue_id, rev)
    if not e:
        return False, "발행 목록에 없다"
    if is_withdrawn(man, "issue", issue_id, rev):
        return False, "내렸다"
    if e.get("approved_by") == TEST_BY:
        return False, MSG_TEST_NOT_PUBLIC   # 시험 폴더에서도 시험 승인은 공개용에 나가지 않는다
    if not (rev_dir(issue_id, rev) / "approval.json").is_file():
        return False, "고정 사본이 없다"
    try:
        fi, fe, appr = load_fixed(issue_id, rev)
    except (OSError, ValueError, json.JSONDecodeError) as x:
        return False, f"고정 사본을 읽지 못했다 — {x}"
    if digest.content_hash(fi, fe) != e.get("content_hash"):
        return False, "고정 사본의 내용 해시가 발행 목록과 다르다"
    if digest.evidence_hash(fi, fe) != e.get("evidence_hash"):
        return False, "고정 사본의 근거 해시가 발행 목록과 다르다"
    for eid, ev in fe.items():
        if ev.get("kind") in EV.OFFICIAL:
            cs = cards.copy_source(EV.as_claim_view(ev))
            if not cs["ok"]:
                return False, f"근거 사본이 바뀌면 무효 — {eid}: {cs['reason']}"
    errs = check.check_issue(fi, fe, public=True)["errors"]
    if errs:
        return False, f"고정 사본이 검사를 통과하지 못한다 — {errs[0]}"
    if e.get("export_version") != B.EXPORT_VERSION or digest.body_hash(B.issue_body(fi, fe, rev_at=appr.get("approved_at", ""))) != e.get("body_hash"):
        return False, REASON_BODY
    keys = ("slug", "rev", "content_hash", "evidence_hash", "body_hash", "export_version", "approved_at", "approved_by", "request_id")
    if any(appr.get(k) != e.get(k) for k in keys) or appr.get("issue_id") != issue_id:
        return False, "승인 기록(approval.json)이 발행 목록과 다르다"
    return True, ""


def latest_public(issue_id: str, man: dict | None = None) -> int | None:
    man = load_manifest() if man is None else man
    for e in reversed(entries(man, "issue", issue_id)):
        if revision_publishable(issue_id, e["rev"], man)[0]:
            return e["rev"]
    return None


# ── 내림 ──────────────────────────────────────────────────────────────
def withdraw(target: str, rev: int | None, by: str, reason: str, now=None) -> dict:
    """{code, msg}. target = 이슈 번호 | day:<날짜> | restored:<날짜>. 지우지 않고 withdrawn 에 더한다."""
    if cards._blank(by) or cards._blank(reason):
        return {"code": 2, "msg": "내린 쪽(--by)과 까닭(--reason)을 적는다"}
    unit, uid = ("issue", target) if ":" not in target else tuple(target.split(":", 1))
    if unit not in ("issue", "day", "restored"):
        return {"code": 2, "msg": f"대상 꼴이 틀렸다: {target}"}
    at = now or cards.now_kst()
    with paths.lock():
        man = load_manifest()
        if not entries(man, unit, uid):
            return {"code": 2, "msg": f"발행 목록에 없는 대상이다: {target}"}
        if rev is not None and not entry(man, unit, uid, rev):
            return {"code": 2, "msg": f"발행 목록에 없는 판이다: {target} {rev}판"}
        row = {"unit": unit, "id": uid, "rev": rev, "at": at, "by": by.strip(), "reason": reason}
        if rev is None:
            row["upto_rev"] = max(int(e["rev"]) for e in entries(man, unit, uid))
        man["withdrawn"].append(row)
        save_manifest(man)
        if unit == "issue" and paths.issue_file(uid).is_file():
            issue = model.load_issue(uid)
            issue.setdefault("history", []).append({"at": at, "event": f"내림({'전체' if rev is None else f'{rev}판'}, {by.strip()})"})
            model.save_issue(issue)
    return {"code": 0, "msg": f"{target} {'모든 판' if rev is None else f'{rev}판'}을 내렸다"}


def status_rows(issue_ids=None) -> list[dict]:
    man = load_manifest()
    rows = []
    for iid in issue_ids or model.all_issue_ids():
        issue, evs = model.load_issue(iid), model.load_evidences(iid)
        h = digest.content_hash(issue, evs)
        ents = entries(man, "issue", iid)
        latest = latest_public(iid, man)
        if ents and is_withdrawn(man, "issue", iid, None):
            appr = "내림"
        elif any(e.get("content_hash") == h for e in ents):
            appr = "승인됨"
        elif ents:
            appr = "승인 뒤 고침"
        else:
            appr = "미승인"
        rows.append({"id": iid, "rev": issue.get("revision"), "work_state": issue.get("work_state"), "content_hash": h,
                     "approval": appr, "latest_public": latest, "review": review_state(issue, evs),
                     "hidden_claims": rules.hidden_claims(issue)})
    return rows
