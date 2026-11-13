"""검토 — 검토 줄 더하기(잠금 안에서), 검토 원문 확인, 검토 조건(설계 9-4)과 이어받기(수정 확인). revisions 가 이 이름들을 다시 내보낸다."""
from __future__ import annotations

import pathlib

from ozl.research import capture as K
from ozl.research import cards

from . import digest, model, paths


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


def _objections(reviews: list, h: str) -> list[dict]:
    """그 내용(해시)을 본 검토 가운데 남은 지적·반려인 줄. 지적은 같은 내용을 본 같은 종류의 뒤 검토가 '통과'로 그 지적을
    가리키면(addresses) 풀린다 — 내용을 고치지 않고 지적을 해소했다는 기록. 반려는 내용을 고쳐야(해시가 바뀌어야) 풀린다."""
    out = []
    for i, r in enumerate(reviews):
        if r.get("result") not in ("지적", "반려") or (r.get("after_hash") or r.get("content_hash")) != h:
            continue
        if r.get("result") == "지적" and any(
                x.get("result") == "통과" and x.get("kind") == r.get("kind") and x.get("content_hash") == h
                and r.get("id") in (x.get("addresses") or []) for x in reviews[i + 1:]):
            continue
        out.append(r)
    return out


def review_state(issue: dict, evidences: dict) -> str:
    """'검토 완료' | '검토 대기' — 설계 9-4. 이어받기(수정 확인)는 바뀐 칸이 모두 지적한 칸 안일 때만 받는다."""
    reviews = [r for r in issue.get("reviews") or [] if isinstance(r, dict) and _notes_ok(issue.get("issue_id"), r)]
    drafted = (issue.get("production") or {}).get("drafted_by") if isinstance(issue.get("production"), dict) else None
    h = digest.content_hash(issue, evidences)
    if _objections(reviews, h):                     # 이 내용에 남은 지적·반려가 있으면 앞선 통과로 넘기지 않는다
        return "검토 대기"
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
        if not isinstance(hb, str) or not _full(reviews, hb, drafted) or not snap.is_file() \
                or any(x.get("result") == "반려" for x in _objections(reviews, hb)):   # 반려된 내용은 이어받지 않는다
            continue
        try:
            before = model.load_yaml(snap)
        except (OSError, ValueError):
            continue
        if digest.snapshot_hash(before) != hb:          # 사본을 바꿔치기했으면 이어받지 않는다
            continue
        # 지적은 같은 이전 내용(before_hash)을 본 검토의 것만, 그리고 더할 때 적은 지문과 맞는 것만 믿는다
        fields = {str(f.get("field")) for a in r.get("addresses") or [] for f in _findings(by_id.get(a), hb)
                  if isinstance(f, dict) and f.get("field")}
        changed = digest.changed_paths(before, digest.snapshot_view(issue, evidences))
        if changed and all(any(p == f or p.startswith(f + ".") for f in fields) for p in changed):
            return "검토 완료"
    return "검토 대기"


def _findings(r, hb: str) -> list:
    """이어받기가 믿는 지적 — 그 검토가 이전 내용(hb)을 보았고, 지적 목록이 더할 때 적은 지문(findings_hash)과 같을 때만."""
    if not isinstance(r, dict) or r.get("content_hash") != hb:
        return []
    f = r.get("findings")
    if not isinstance(f, list) or not f or r.get("findings_hash") != digest.findings_hash(f):
        return []
    return f


def add_review(issue_id: str, kind: str, by_model: str, family: str, result: str, findings=None, before_hash=None,
               addresses=None, notes_path="", now=None) -> dict:
    """검토 한 줄을 더하고 그 내용의 사본(snapshots/<내용 해시>.yaml)을 남긴다. 검토 번호 r 는 여기서 센다."""
    if kind not in model.REVIEW_KINDS or family not in model.REVIEW_FAMILIES or result not in model.REVIEW_RESULTS:
        raise ValueError("검토의 kind·family·result 가 허용 값이 아니다")
    if cards._blank(by_model):
        raise ValueError("검토한 모델(by_model)을 적는다")
    findings = list(findings or [])
    if any(not isinstance(x, dict) or cards._blank(x.get("field")) for x in findings):
        raise ValueError("지적은 [{field, note}] 목록이다(field 를 적는다)")
    d = notes_dir(issue_id).resolve()
    f = pathlib.Path(notes_path).resolve() if not cards._blank(notes_path) else None
    if f is None or d not in f.parents or not f.is_file() or f.stat().st_size == 0:
        raise ValueError(f"검토 원문(--notes-path)은 {d} 안의 비어 있지 않은 파일이다 — 검토한 쪽의 원문을 먼저 저장한다")
    notes_rel, notes_sha = str(f.relative_to(paths.issue_dir(issue_id).resolve())), K.sha256_file(f)
    # 읽기부터 번호 세기·사본·저장까지 승인·내림과 같은 잠금 안에서 — 동시에 더한 검토가 서로를 지우지 않게
    with paths.lock():
        issue, evs = model.load_issue(issue_id), model.load_evidences(issue_id)
        h = digest.content_hash(issue, evs)
        nums = [int(str(r.get("id"))[1:]) for r in issue.get("reviews") or [] if isinstance(r, dict)
                and str(r.get("id", "")).startswith("r") and str(r.get("id"))[1:].isdigit()]
        row = {"id": f"r{max(nums, default=0) + 1}", "kind": kind, "by_model": by_model, "family": family, "at": now or cards.now_kst(),
               "content_hash": h, "result": result, "findings": findings, "findings_hash": digest.findings_hash(findings),
               "notes_path": notes_rel, "notes_sha256": notes_sha}
        if before_hash:
            row["before_hash"] = before_hash
        if addresses:
            row["addresses"] = list(addresses)
        snap = snapshot_file(issue_id, h)
        if not snap.exists() or digest.snapshot_hash(_load_or_none(snap)) != h:
            model.save_yaml(snap, digest.snapshot_view(issue, evs))
        issue.setdefault("reviews", []).append(row)
        model.save_issue(issue)
    return row


def _load_or_none(p):
    try:
        return model.load_yaml(p)
    except (OSError, ValueError):
        return None
