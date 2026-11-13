"""내보내기의 독자 화면 표시 — 판정 변경 기록은 게시한 판 뒤의 것만, 보도 요약(press_label)은 근거 종류(evidence_label)와 따로,
미리보기에서 승인된 판은 승인된 판의 AI 고지. 지어낸 예시 이슈(tests/fixtures/issues)만 쓴다."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import body as B  # noqa: E402
from ozl.issues import export, revisions, rules  # noqa: E402
from test_issues_check import I1, I2, desk, load  # noqa: E402,F401
from test_issues_export import SLUG1, SLUG2, contact  # noqa: E402,F401
from test_issues_revisions import approve, claim, edit, ready, real  # noqa: E402,F401

APPROVED = "게시 승인은 사람이 했다."
PENDING = "이 판은 아직 승인 전이다."


def _claims(b: dict) -> dict:
    return {c["id"]: c for g in b["verdicts"]["groups"] for c in g["claims"]}


def _set_history(issue, rows):
    claim(issue, "c1")["verdict_history"] = [dict({"at": "2099-01-03", "from": "확인 못 함", "to": "일부 맞음",
                                                   "why": "시험용으로 지어낸 까닭"}, **r) for r in rows]


# ── 1. 판정 변경 기록 ─────────────────────────────────────────────────
def test_unpublished_issue_has_no_history(desk, tmp_path):
    edit(I1, lambda i: _set_history(i, [{"rev": 1}]))
    issue, evs = load(I1)
    assert _claims(B.issue_body(issue, evs))["c1"]["history"] == []
    assert export.export("preview", tmp_path / "pv")["code"] == 0
    b = json.loads((tmp_path / "pv" / "issues" / f"{SLUG1}.json").read_text(encoding="utf-8"))
    assert _claims(b)["c1"]["history"] == []


def test_history_after_first_published_rev(desk):
    edit(I1, lambda i: (i.update(revision=3), _set_history(i, [{"rev": 1}, {"rev": 2}, {"rev": 3}, {"rev": 4}])))
    issue, evs = load(I1)
    issue["claims"][0]["verdict_history"].append({"at": "2099-01-03", "from": "확인 못 함", "to": "일부 맞음", "why": "판 없음"})
    got = [h.get("rev") for h in _claims(B.issue_body(issue, evs, first_rev=1))["c1"]["history"]]
    assert got == [2, 3]                    # 처음 게시한 판(1)과 그 앞, 판 없는 옛 기록, 이 판보다 뒤(4)는 싣지 않는다
    assert _claims(B.issue_body(issue, evs, first_rev=3))["c1"]["history"] == []


def test_published_then_changed_in_preview_and_public(real, contact, tmp_path):
    ready(I1)
    assert approve(I1)["code"] == 0
    edit(I1, lambda i: (i.update(revision=2, rev_line="판정 변경 기록을 시험한다."), _set_history(i, [{"rev": 1}, {"rev": 2}])))
    assert export.export("preview", tmp_path / "pv")["code"] == 0
    b = json.loads((tmp_path / "pv" / "issues" / f"{SLUG1}.json").read_text(encoding="utf-8"))
    assert [h["rev"] for h in _claims(b)["c1"]["history"]] == [2]
    ready(I1)
    r = approve(I1, now="2099-01-03T12:00:00+09:00")
    assert r["code"] == 0, r["msg"]
    for rev in (1, 2):                      # 고정 사본에서 다시 만든 본문이 승인 때 본문과 같다
        assert revisions.revision_publishable(I1, rev) == (True, "")
    assert export.export("public", tmp_path / "pub")["code"] == 0
    r1 = json.loads((tmp_path / "pub" / "issues" / SLUG1 / "r" / "1.json").read_text(encoding="utf-8"))
    r2 = json.loads((tmp_path / "pub" / "issues" / SLUG1 / "r" / "2.json").read_text(encoding="utf-8"))
    assert _claims(r1)["c1"]["history"] == []
    assert [h["rev"] for h in _claims(r2)["c1"]["history"]] == [2]
    feed = json.loads((tmp_path / "pub" / "feed.json").read_text(encoding="utf-8"))
    assert {f["rev"]: f["kind"] for f in feed if f["slug"] == SLUG1} == {1: "새 판", 2: "판정 변경"}


# ── 2. 근거 종류와 보도 요약 ───────────────────────────────────────────
def test_press_label_separate_from_evidence_label(desk):
    issue, evs = load(I2)
    c4 = claim(issue, "c4")                 # 보도 한 곳만 받치는 주장
    assert rules.evidence_label(c4, evs) == ""
    assert rules.press_label(c4, evs) == "보도 1곳(맨 처음 가나일보. 기사가 든 근거: 익명 관계자)"
    for c in issue["claims"]:
        assert "보도" not in rules.evidence_label(c, evs)
    shown = _claims(B.issue_body(issue, evs))
    assert shown["c4"]["evidence_label"] == "" and shown["c4"]["press_label"].startswith("보도 1곳(")
    assert all("press_label" in c and "보도" not in c["evidence_label"] for c in shown.values())


def test_official_only_claim_has_no_press_label(desk):
    official = []
    for iid in (I1, I2):
        issue, evs = load(iid)
        official += [rules.press_label(c, evs) for c in issue["claims"] if rules.evidence_label(c, evs)
                     and "보도" not in {(evs.get(e.get("evidence_id")) or {}).get("kind") for e in c.get("evidence") or []}]
    assert official and all(x == "" for x in official)


# ── 3. 승인된 판의 미리보기 AI 고지 ───────────────────────────────────
def test_preview_of_approved_revision_says_approved(real, tmp_path):
    ready(I1)
    assert approve(I1)["code"] == 0
    assert export.export("preview", tmp_path / "pv")["code"] == 0
    b1 = json.loads((tmp_path / "pv" / "issues" / f"{SLUG1}.json").read_text(encoding="utf-8"))
    b2 = json.loads((tmp_path / "pv" / "issues" / f"{SLUG2}.json").read_text(encoding="utf-8"))
    assert APPROVED in b1["ai_notice"] and PENDING not in b1["ai_notice"]
    assert PENDING in b2["ai_notice"]
    edit(I1, lambda i: i.update(rev_line="승인 뒤에 고친 작업본이다."))      # 승인 뒤에 고치면 다시 승인 전이다
    assert export.export("preview", tmp_path / "pv")["code"] == 0
    b1 = json.loads((tmp_path / "pv" / "issues" / f"{SLUG1}.json").read_text(encoding="utf-8"))
    assert PENDING in b1["ai_notice"]
