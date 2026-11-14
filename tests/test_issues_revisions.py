"""판 고정 사본, 발행 목록, 승인(멱등), 검토 조건, 시험·실제 규칙 시험(설계 9절, 6-12, 6-21, 6-22).
자료는 지어낸 예시 두 건(가상의 한빛시, 가상의 회사 누리전자)뿐이다. 네트워크를 쓰지 않는다."""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import digest, export, model, paths, revisions  # noqa: E402
from test_issues_check import I1, I2, desk, load  # noqa: E402,F401

NOW = "2099-01-02T12:00:00+09:00"
EDITOR = "편집자"


# ── 도우미(다른 B 시험 파일도 가져다 쓴다) ────────────────────────────
def add_review(iid, kind, by_model, family, result, **kw):
    """검토 원문 파일(지어낸 한 줄)을 reviews 폴더에 두고 검토 줄을 더한다."""
    d = revisions.notes_dir(iid)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"note_{len(list(d.iterdir())) + 1}.md"
    f.write_text(f"{kind} {by_model} {result} — 시험용으로 지어낸 검토 원문\n", encoding="utf-8")
    return revisions.add_review(iid, kind, by_model, family, result, notes_path=str(f), **kw)


@pytest.fixture
def real(desk, monkeypatch):
    """시험 폴더를 실제 자료 루트로 흉내 낸다(실제 private/desk 는 건드리지 않는다)."""
    monkeypatch.setattr(paths, "real_root", lambda: desk)
    assert paths.is_real_root()
    return desk


def ready(iid, reviewer="Claude Sonnet") -> str:
    """게시 대기로 두고 검토 두 줄(다른 모델의 문장 대조, 다른 계열의 해석 점검)을 더한다. 지금 내용 해시를 돌려준다."""
    issue = model.load_issue(iid)
    issue["work_state"] = "게시 대기"
    model.save_issue(issue)
    add_review(iid, "문장 대조", reviewer, "anthropic", "통과", now=NOW)
    add_review(iid, "해석 점검", "가상 모델 G", "openai", "통과", now=NOW)
    return digest.content_hash(*load(iid))


def approve(iid, by=None, now=NOW):
    by = by or (EDITOR if paths.is_real_root() else revisions.TEST_BY)
    issue, evs = load(iid)
    return revisions.approve(iid, issue["revision"], digest.content_hash(issue, evs), by, now=now)


def edit(iid, fn):
    issue = model.load_issue(iid)
    fn(issue)
    model.save_issue(issue)


def claim(issue, cid):
    return next(c for c in issue["claims"] if c["id"] == cid)


def tree_hash(d: pathlib.Path) -> str:
    if not d.exists():
        return "없음"
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        h.update(str(p.relative_to(d)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


# ── 시험 ──────────────────────────────────────────────────────────────
def test_approve_idempotent(real):
    ready(I1)
    r1, r2 = approve(I1), approve(I1)
    assert r1["code"] == 0 and r2["code"] == 0 and "이미 승인됨" in r2["msg"]
    man = revisions.load_manifest()
    assert len(revisions.entries(man, "issue", I1)) == 1
    revs = [p.name for p in (paths.issue_dir(I1) / "revisions").iterdir()]
    assert revs == ["r1"]
    ok, why = revisions.revision_publishable(I1, 1)
    assert ok, why
    appr = revisions.load_fixed(I1, 1)[2]
    assert appr["changed_fields"] == ["새 이슈"] and appr["approved_by"] == EDITOR


def test_approve_hash_mismatch(real):
    h = ready(I1)
    assert revisions.approve(I1, 2, h, EDITOR)["code"] == 3
    r = revisions.approve(I1, 1, "0" * 32, EDITOR)
    assert r["code"] == 3 and "내용 해시" in r["msg"]
    assert not paths.manifest_file().exists() and not (paths.issue_dir(I1) / "revisions").exists()


def test_approve_requires_reviews(real):
    edit(I1, lambda i: i.update(work_state="게시 대기"))
    r = approve(I1)
    assert r["code"] == 1 and "검토" in r["msg"]
    # 같은 모델이 쓴 초안을 같은 모델이 대조하면 검토가 아니다
    add_review(I1, "문장 대조", "Claude Opus", "anthropic", "통과")
    add_review(I1, "해석 점검", "가상 모델 G", "google", "통과")
    assert revisions.review_state(*load(I1)) == "검토 대기"
    ready(I1)
    assert approve(I1)["code"] == 0
    # 이어받기: 지적한 칸만 고친 수정은 수정 확인 한 줄로 넘어간다. 지적은 검토를 더할 때 적는다(나중에 고친 지적은 믿지 않는다).
    h0 = ready(I2)
    add_review(I2, "문장 대조", "Claude Sonnet", "anthropic", "지적",
               findings=[{"field": "claims.c3.would_decide", "note": "범위를 좁힌다"}])                 # r3
    add_review(I2, "해석 점검", "가상 모델 G", "openai", "지적", findings=[{"field": "claims.c1", "note": "요지를 고친다"}])   # r4
    edit(I2, lambda i: claim(i, "c3").update(would_decide="대법원의 확정 판결"))
    assert revisions.review_state(*load(I2)) == "검토 대기"
    add_review(I2, "수정 확인", "Claude Sonnet", "anthropic", "통과", before_hash=h0, addresses=["r3"])
    assert revisions.review_state(*load(I2)) == "검토 완료"
    assert approve(I2)["code"] == 0
    # 지적과 무관한 칸(다른 주장의 요지)까지 바뀌면 같은 이어받기로는 다시 검토 대기
    edit(I2, lambda i: claim(i, "c1").update(gist="회수 대상은 1만 2천 개이고, 모두 국내용이다."))
    add_review(I2, "수정 확인", "Claude Sonnet", "anthropic", "통과", before_hash=h0, addresses=["r3"])
    assert revisions.review_state(*load(I2)) == "검토 대기"
    add_review(I2, "수정 확인", "Claude Sonnet", "anthropic", "통과", before_hash=h0, addresses=["r3", "r4"])
    assert revisions.review_state(*load(I2)) == "검토 완료"


def test_test_approval_rules(desk, monkeypatch, tmp_path):
    ready(I1)
    r = approve(I1, by=EDITOR)
    assert r["code"] == 2 and r["msg"] == revisions.MSG_REAL_IN_TEST
    assert approve(I1, by=revisions.TEST_BY)["code"] == 0
    assert not revisions.revision_publishable(I1, 1)[0]            # 시험 승인은 시험 폴더에서도 공개되지 않는다
    monkeypatch.setenv(export.CONTACT_ENV, "report@example.invalid")
    res = export.export("public", tmp_path / "out_t")
    assert res["code"] == 0 and res["counts"]["issues"] == 0
    monkeypatch.setattr(paths, "real_root", lambda: desk)        # 실제 루트 흉내: 시험 승인이 섞인 발행 목록
    ready(I2)
    r = approve(I2, by=revisions.TEST_BY)
    assert r["code"] == 2 and r["msg"] == revisions.MSG_TEST_IN_REAL
    res = export.export("public", tmp_path / "out_r")
    assert res["code"] == 1 and export.MSG_TEST_MIX in res["msgs"] and not (tmp_path / "out_r").exists()


def test_test_desk_leaves_real_untouched(desk, monkeypatch, tmp_path):
    real_issues = paths.ROOT / "private" / "desk" / "issues"
    before = tree_hash(real_issues)
    assert not paths.is_real_root()
    ready(I1)
    assert approve(I1)["code"] == 0
    assert revisions.withdraw(I1, None, revisions.TEST_BY, "시험 내림")["code"] == 0
    monkeypatch.setenv(export.CONTACT_ENV, "report@example.invalid")
    assert export.export("preview", desk / "out_p")["code"] == 0
    assert export.export("public", desk / "out_q")["code"] == 0
    assert tree_hash(real_issues) == before


def test_edit_after_approval_needs_new_rev(real):
    ready(I1)
    assert approve(I1)["code"] == 0
    edit(I1, lambda i: claim(i, "c1").update(searched="시 결산서 2098년, 시 보도자료"))
    errs = revisions.check_ids([I1])[I1]["errors"]
    assert any(revisions.MSG_SAME_REV in e for e in errs)
    edit(I1, lambda i: i.update(revision=2, rev_line="찾아본 범위를 고쳐 적었다.", slug="hanbit-bus-fare"))
    errs = revisions.check_ids([I1])[I1]["errors"]
    assert not any(revisions.MSG_SAME_REV in e for e in errs)
    assert any(revisions.MSG_SLUG in e for e in errs)


def test_withdraw_needs_manifest_entry(desk):
    assert revisions.withdraw(I1, None, revisions.TEST_BY, "까닭")["code"] == 2
    assert revisions.withdraw(I1, None, "", "까닭")["code"] == 2


# ── 게시 대기로 올린 뒤 내용이 바뀌면 검토가 풀린다: status 는 '검토 대기'로 보이고 경고하며, check 는 오류로 막는다 ──
def test_stale_ready_shown_as_review_wait(desk, capsys):
    ready(I1)
    row = revisions.status_rows([I1])[0]
    assert row["work_state"] == "게시 대기" and row["shown_state"] == "게시 대기" and not row["stale_ready"]
    edit(I1, lambda i: i.__setitem__("what_new", i["what_new"].rstrip(".") + " 시험으로 고친 문장이다."))
    row = revisions.status_rows([I1])[0]
    assert row["work_state"] == "게시 대기"                    # 파일은 그대로 두고
    assert row["review"] == "검토 대기" and row["stale_ready"] and row["shown_state"] == "검토 대기"
    issue, evs = load(I1)
    assert any(revisions.MSG_REVIEW in e for e in revisions.check_with_manifest(issue, evs)["errors"])
    from ozl.issues.__main__ import main
    assert main(["status", I1]) == 0
    out = capsys.readouterr().out
    assert revisions.STALE_READY in out and "경고:" in out
