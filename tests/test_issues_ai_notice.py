"""AI 고지 문구 — 승인된 판은 "게시 승인은 사람이 했다", 승인 전 판(작업본 미리보기)은 아직 승인 전이라고 적는다.

지어낸 예시 이슈(tests/fixtures/issues)만 쓴다.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import body as B  # noqa: E402
from ozl.issues import export, revisions  # noqa: E402
from test_issues_check import I1, I2, desk, load  # noqa: E402,F401
from test_issues_revisions import approve, ready, real  # noqa: E402,F401

APPROVED = "게시 승인은 사람이 했다."
PENDING = "게시 승인은 사람이 한다. 이 판은 아직 승인 전이다."


def test_notice_wording():
    person = {"production": {"chosen_by": "사람"}}
    model = {"production": {"chosen_by": "모델"}}
    assert B.ai_notice(person) == B.AI_NOTICE_PERSON and B.ai_notice(model) == B.AI_NOTICE_MODEL
    for n in (B.AI_NOTICE_PERSON, B.AI_NOTICE_MODEL):
        assert APPROVED in n and PENDING not in n
    for n in (B.ai_notice(person, approved=False), B.ai_notice(model, approved=False)):
        assert PENDING in n and "사람이 했다." not in n.replace("고르기는 사람이 했다.", "")
    assert "고르기는 사람이 했다." in B.ai_notice(person, approved=False)
    assert "고르기는 AI 도구가 했다." in B.ai_notice(model, approved=False)
    for n in (B.AI_NOTICE_PERSON, B.AI_NOTICE_MODEL, B.AI_NOTICE_PERSON_PENDING, B.AI_NOTICE_MODEL_PENDING):
        assert "AI를 썼다는" in n and "AI 를" not in n


def test_body_notice_follows_rev_at(desk):
    issue, evs = load(I1)
    assert PENDING in B.issue_body(issue, evs)["ai_notice"]
    assert APPROVED in B.issue_body(issue, evs, rev_at="2099-01-01T12:00:00+09:00")["ai_notice"]
    assert APPROVED in B.issue_body(issue, evs, approved=True)["ai_notice"]


def test_preview_export_says_not_yet_approved(desk, tmp_path):
    out = tmp_path / "pv"
    assert export.export("preview", out)["code"] == 0
    for p in (out / "issues").glob("*.json"):
        b = json.loads(p.read_text(encoding="utf-8"))
        assert PENDING in b["ai_notice"] and APPROVED not in b["ai_notice"], p.name


def test_approved_revision_keeps_approved_notice(real):
    ready(I1)
    assert approve(I1)["code"] == 0
    fi, fe, appr = revisions.load_fixed(I1, 1)
    b = B.issue_body(fi, fe, rev_at=appr.get("approved_at", ""))
    assert APPROVED in b["ai_notice"] and PENDING not in b["ai_notice"]
