"""이슈 기록 읽고 쓰기, 빈 뼈대, 모듈 크기 시험."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import check, ids, model, paths  # noqa: E402
from ozl.research import cards  # noqa: E402
from test_issues_check import I1, I2, desk, load  # noqa: E402,F401


def test_roundtrip_and_skeleton(desk):
    for iid in (I1, I2):
        issue, evs = load(iid)
        model.save_issue(issue)
        for ev in evs.values():
            model.save_evidence(ev)
        assert load(iid) == (issue, evs)
    iid = ids.next_issue_ids("2099-03-01")[0]
    sk = model.skeleton(iid, "sample-issue", example=True, now="2099-03-01 09:00")
    model.save_issue(sk)
    assert model.load_issue(iid) == sk and iid in model.all_issue_ids()
    r = check.check_issue(sk, {}, public=False)
    assert r["errors"] == [], r
    assert check.check_issue(sk, {}, public=True)["errors"]            # 게시 필수 칸은 비어 있다
    assert set(model.ISSUE_FIELDS) >= set(sk) and model.CATEGORIES == tuple(cards.CATEGORIES)


def test_desk_root_is_read_per_call(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV, raising=False)
    assert paths.is_real_root()
    monkeypatch.setenv(paths.ENV, str(tmp_path))
    assert paths.desk_root() == tmp_path and not paths.is_real_root() and paths.ledger_file().parent == tmp_path / "issues"


def test_issues_module_size():
    for p in sorted((ROOT / "src" / "ozl" / "issues").glob("*.py")):
        n = len(p.read_text(encoding="utf-8").splitlines())
        assert n <= 400, f"{p.name} 가 {n}줄이다 — 400줄 이하로 나눈다"
