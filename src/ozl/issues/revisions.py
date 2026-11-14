"""판 고정 사본, 발행 목록, 승인(멱등), 내림, 판 공개 판정, 검토 조건 — 설계 9절.

발행 목록(<자료 루트>/issues/manifest.json)이 게시와 내림을 정한다. 승인은 판 번호와 내용 해시를 함께 받고 지금 작업본과 다르면 거부한다.
같은 승인 요청이 두 번 와도 발행 목록에는 한 줄만 생긴다. 시험 폴더에서는 승인한 쪽을 '시험'으로만, 실제 폴더에서는 '시험'을 받지 않는다.
승인한 쪽이 '시험'인 판은 어느 폴더에서도 공개 판정이 거짓이다(공개용 내보내기에 나가지 않는다).
check 에 발행 목록이 있어야 하는 검사(승인 뒤 판 번호, 게시한 주소 이름, 게시 대기의 검토 조건)를 더하는 감싼 함수도 여기 둔다.
발행 목록 읽고 쓰기와 공통 승인 규칙은 manifest, 검토는 reviews 에 있고 여기서 다시 내보낸다(revisions.add_review 처럼 부른다).
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
from .manifest import (EMPTY, MSG_REAL_IN_TEST, MSG_ROOT_ALIAS, MSG_REQUEST_ID, MSG_SLUG_TAKEN, MSG_TEST_IN_REAL, MSG_TEST_NOT_PUBLIC,  # noqa: F401
                       MSG_WITHDRAWN, TEST_BY, approver_error, entries, entry, entry_error, is_withdrawn, load_manifest,
                       prior_approval, save_manifest, slug_conflicts)
from .reviews import (_findings, _full, _notes_ok, _same, add_review, missing_reviews, notes_dir, review_state,  # noqa: F401
                      save_snapshot, snapshot_file)

REASON_BODY = "다시 만든 본문이 승인 때와 다르다"
MSG_SAME_REV = "승인된 판과 내용이 다른데 판 번호가 같다 — 판 번호를 올린다"
MSG_SLUG = "게시한 주소 이름은 바꾸지 않는다(옛 이름은 aliases 로)"
MSG_REVIEW = ("게시 대기인데 검토 조건(다른 모델의 문장 대조, 다른 계열의 해석 점검)을 지금 내용으로 채우지 못했다"
              "(검토 뒤에 내용이 바뀌었으면 검토가 풀린다). work_state 를 '검토 대기'로 내리고 검토를 다시 받는다")
STALE_READY = "게시 대기 → 검토 대기로 본다"


def shown_work_state(issue: dict, review: str) -> str:
    """화면과 status 에 보일 작업 상태. '게시 대기'인데 지금 내용 해시로 검토가 채워지지 않았으면 '검토 대기'로 보인다
    (검토 줄은 더한 때의 내용 해시에 묶이므로, 게시 대기로 올린 뒤 글이나 기록을 고치면 검토가 풀린다). 파일은 고치지 않는다."""
    ws = issue.get("work_state")
    if ws == "게시 대기" and review == "검토 대기":
        return "검토 대기"
    return ws or "작성 중"


def rev_dir(issue_id: str, rev: int) -> pathlib.Path:
    return paths.issue_dir(issue_id) / "revisions" / f"r{rev}"


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
    out += [f"{iid} {k}: {m}" for k, m in slug_conflicts(issue, man)]
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
        code, msg = approver_error(by)                  # 이름 규칙은 멱등 분기보다 먼저 — 이미 승인된 판이라도 틀린 이름은 거부
        if code:
            return {"code": code, "msg": msg, "entry": None}
        man = load_manifest()
        pre = prior_approval(man, "issue", issue_id, rev, h, request_id, rev_dir(issue_id, rev) / "approval.json")
        if pre is not None:
            return pre
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
        first = B.first_published(man, issue_id)       # 승인 전의 발행 목록 — 처음 게시하는 판이면 None
        body = B.issue_body(issue, evs, rev_at=at, first_rev=first)
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
        if digest.body_hash(B.issue_body(fi, fe, rev_at=at, first_rev=first)) != ent["body_hash"]:
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
    why = entry_error(man, "issue", issue_id, rev)
    if why:
        return False, why
    e = entry(man, "issue", issue_id, rev)
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
    # 고정 사본이 바로 그 이슈·판·주소인지, 승인할 수 있던 상태(게시 가능, 게시 대기, 검토 완료)인지 다시 본다
    if fi.get("issue_id") != issue_id or fi.get("revision") != rev or isinstance(fi.get("revision"), bool) \
            or fi.get("slug") != e.get("slug"):
        return False, "고정 사본의 이슈 번호·판 번호·주소 이름이 발행 목록과 다르다"
    if (fi.get("publish") or {}).get("state") != "게시 가능" if isinstance(fi.get("publish"), dict) else True:
        return False, "고정 사본의 게시 가부가 '게시 가능'이 아니다"
    if fi.get("work_state") != "게시 대기":
        return False, "고정 사본의 작업 상태가 '게시 대기'가 아니다"
    errs = check.check_issue(fi, fe, public=True)["errors"]
    if errs:
        return False, f"고정 사본이 검사를 통과하지 못한다 — {errs[0]}"
    if review_state(fi, fe) != "검토 완료":
        return False, "고정 사본의 검토 조건이 채워지지 않았다"
    if e.get("export_version") != B.EXPORT_VERSION or digest.body_hash(B.issue_body(fi, fe, rev_at=appr.get("approved_at", ""),
                                                                          first_rev=fixed_first_rev(man, issue_id, rev))) != e.get("body_hash"):
        return False, REASON_BODY
    keys = ("slug", "rev", "content_hash", "evidence_hash", "body_hash", "export_version", "approved_at", "approved_by", "request_id")
    if any(appr.get(k) != e.get(k) for k in keys) or appr.get("issue_id") != issue_id or appr.get("rev") != rev:
        return False, "승인 기록(approval.json)이 발행 목록과 다르다"
    return True, ""


def fixed_first_rev(man: dict, issue_id: str, rev: int) -> int | None:
    """고정 사본에서 본문을 다시 만들 때의 '처음 게시한 판' — 그 판을 승인할 때 발행 목록에 있던 판(그 판보다 앞의 판)만 본다.
    처음 게시한 판이면 None 이라 승인 때 만든 본문과 같다(그 판의 판정 변경 기록은 어차피 싣지 않는다)."""
    first = B.first_published(man, issue_id)
    return first if first is not None and first < rev else None


def latest_public(issue_id: str, man: dict | None = None) -> int | None:
    man = load_manifest() if man is None else man
    for e in reversed(entries(man, "issue", issue_id)):
        if revision_publishable(issue_id, e["rev"], man)[0]:
            return e["rev"]
    return None


# ── 내림 ──────────────────────────────────────────────────────────────
def withdraw(target: str, rev: int | None, by: str, reason: str, now=None) -> dict:
    """{code, msg}. target = 이슈 번호 | day:<날짜> | restored:<날짜>. 지우지 않고 withdrawn 에 더한다."""
    if paths.in_runner():
        return {"code": 2, "msg": paths.MSG_RUNNER}
    if paths.is_alias_of_real_root():               # 시험 루트로 보이는 실제 폴더의 다른 이름 — 실제 발행 목록에 내림이 적히지 않게
        return {"code": 2, "msg": MSG_ROOT_ALIAS}
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
        review = review_state(issue, evs)
        rows.append({"id": iid, "rev": issue.get("revision"), "work_state": issue.get("work_state"), "content_hash": h,
                     "shown_state": shown_work_state(issue, review),
                     "stale_ready": issue.get("work_state") == "게시 대기" and review == "검토 대기",
                     "approval": appr, "latest_public": latest, "review": review,
                     "hidden_claims": rules.hidden_claims(issue)})
    return rows
