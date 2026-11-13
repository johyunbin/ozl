"""이슈 번호·근거 번호·항목 번호 발급 시험 — 시험 루트(tmp)에서만 쓴다."""
from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import check, ids, model, paths  # noqa: E402
from test_issues_check import I1, desk, load  # noqa: E402,F401


@pytest.fixture
def empty_root(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV, str(tmp_path / "desk"))
    return tmp_path / "desk"


def test_issue_ids_never_reused(empty_root):
    a = ids.next_issue_ids("2099-02-01", 2)
    assert a == ["i20990201-01", "i20990201-02"]
    for iid in a:
        model.save_issue(model.skeleton(iid, "sample-issue"))
    shutil.rmtree(paths.issue_dir(a[1]))                      # 지운 번호도 다시 주지 않는다
    assert ids.next_issue_ids("2099-02-01") == ["i20990201-03"]
    (paths.issues_dir() / "i20990201-07").mkdir()              # 대장 밖에 생긴 폴더도 본다
    assert ids.next_issue_ids("2099-02-01") == ["i20990201-08"]
    e = ids.next_evidence_ids(a[0], 2)
    assert e == [f"{a[0]}-e1", f"{a[0]}-e2"]
    assert ids.next_evidence_ids(a[0]) == [f"{a[0]}-e3"]
    assert ids.next_item_ids(a[0], "c", 2) == ["c1", "c2"]
    assert ids.next_item_ids(a[0], "c") == ["c3"]
    with pytest.raises(ValueError):
        ids.next_evidence_ids("i20990201-55")                    # 대장에 없는 이슈
    with pytest.raises(ValueError):
        ids.next_item_ids(a[0], "p")                              # 작은 주장은 대장이 세지 않는다
    with pytest.raises(ValueError):
        ids.next_issue_ids("2099-02-02", 100)                      # 99 초과
    ids.next_issue_ids("2099-02-03", 99)
    with pytest.raises(ValueError):
        ids.next_issue_ids("2099-02-03")
    paths.ledger_file().write_text("{깨진", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        ids.next_issue_ids("2099-02-04")
    paths.ledger_file().write_text('{"schema": 1, "issues": {}}', encoding="utf-8")
    with pytest.raises(ValueError):
        ids.next_issue_ids("2099-02-04")
    assert not (paths.issues_dir() / "i20990204-01").exists()


def test_item_beyond_ledger_is_rejected(desk):
    issue, evs = load(I1)
    issue["open_questions"].append({"id": "q9", "text": "다음 판에서 볼 것", "target_kind": "기관과 정책", "publish": "게시 가능"})
    errs = check.check_issue(issue, evs, public=True)["errors"]
    assert any(" open_questions.q9: 대장에 없는 번호다" in e for e in errs)


@pytest.mark.parametrize("slug,ok", [("hanbit-bus-fare-400", True), ("abc", True), ("ab", False), ("Hanbit-bus", False),
                                      ("hanbit_bus", False), ("hanbit--bus", False), ("-hanbit", False), ("한빛-버스", False),
                                      ("a-b-c-d-e-f-g-h", True), ("a-b-c-d-e-f-g-h-i", False), ("a" * 61, False)])
def test_slug_rules(slug, ok):
    assert (ids.slug_error(slug) == "") is ok


def test_id_shapes():
    assert ids.issue_id_ok("i20261114-01") and not ids.issue_id_ok("i20261131-01") and not ids.issue_id_ok("i20261114-00")
    assert ids.evidence_id_ok("i20261114-01-e3", "i20261114-01") and not ids.evidence_id_ok("i20261114-01-e3", "i20261114-02")
    assert not ids.evidence_id_ok("i20261114-01-e0")
    assert ids.item_id_ok("c12", "c") and not ids.item_id_ok("c0") and not ids.item_id_ok("x1")
