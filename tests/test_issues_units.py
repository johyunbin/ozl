"""그날의 화제 목록과 복원판 시험(설계 10절). 지어낸 키워드와 가상의 문서 이름만 쓴다."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import export, gate, model, revisions, units  # noqa: E402
from test_issues_check import I1, I2, desk, load  # noqa: E402,F401
from test_issues_revisions import approve, ready, real  # noqa: E402,F401

DATE = "2099-01-03"


def day(**kw):
    d = {"date": DATE, "revision": 1, "made_at": f"{DATE} 07:00",
         "line": {"updated_at": f"{DATE} 07:00", "source_kinds_ok": ["공식 발표"], "source_kinds_failed": []},
         "new": [{"issue_id": I1, "status_line": "시가 인상안을 발표했다."}, {"issue_id": I2, "status_line": "회수 명령이 나왔다."}],
         "ongoing": [], "upcoming": [{"date": "2099-01-20", "what": "가상 시의회 본회의", "url": "https://council.example/plan"}],
         "pre": [{"keyword": "가상 축제 일정", "desc": "올해 일정이 바뀌었다는 말이 돈다.", "links": [], "flags": []},
                 {"keyword": "가상 인물 소문", "desc": "", "links": [], "flags": ["개인"]}],
         "empty_note": {"new": "", "ongoing": "오늘 이어지는 기록은 없다."}}
    d.update(kw)
    return d


def restored(**kw):
    d = {"date": DATE, "revision": 1, "made_at": f"{DATE} 07:00", "label": units.RESTORED_LABEL,
         "source_url": "https://wiki.example/pageviews", "items": [{"rank": 1, "article": "가상 도시", "views": 1200}]}
    d.update(kw)
    return d


def put(unit, d):
    model.save_yaml(units.unit_file(unit, d["date"]), d)
    return units.unit_hash(unit, d)


def test_day_list_and_restored(real, tmp_path, monkeypatch):
    item = {"keyword": "가상 소재", "state": "정리 전"}
    assert units.check_unit("day", day(new=[item] * 5))["errors"]                       # 새로 뜬 것 4개 상한
    assert units.check_unit("day", day(ongoing=[item] * 7))["errors"]                   # 이어지는 것 6개 상한
    assert not units.check_unit("day", day(new=[item] * 4, ongoing=[item] * 6))["errors"]
    w = units.check_unit("day", day(pre=[{"keyword": "가상 인물 소문", "desc": "누가 무엇을 했다는 말", "flags": ["개인"]}]))
    assert w["warnings"] and not w["errors"]
    assert units.check_unit("restored", restored(items=[{"rank": 1, "article": "가상 도시", "views": 3, "verdict": "확인"}]))["errors"]
    assert units.check_unit("restored", restored(score=3))["errors"]
    assert not units.check_unit("restored", restored())["errors"]
    # 점수·갱신 시각만 바뀌면 지문이 같다
    h = units.unit_hash("day", day())
    assert units.unit_hash("day", day(line={"updated_at": "다른 시각", "source_kinds_ok": ["공식 발표"], "source_kinds_failed": []})) == h
    # 각각 따로 승인(멱등, 판·해시 대조)
    hd, hr = put("day", day()), put("restored", restored())
    assert units.approve_unit("day", DATE, 1, "0" * 32, "편집자")["code"] == 3
    assert units.approve_unit("day", DATE, 1, hd, "편집자")["code"] == 0
    assert units.approve_unit("day", DATE, 1, hd, "편집자")["code"] == 0
    assert gate.is_public("day", DATE) and not gate.is_public("restored", DATE)
    assert units.approve_unit("restored", DATE, 1, hr, "편집자")["code"] == 0
    assert gate.is_public("restored", DATE)
    assert len(revisions.load_manifest()["entries"]) == 2
    # 공개용: 제외 표시 항목은 빠지고, 공개 판이 없는 이슈 항목은 '정리 전'으로 바뀐다
    ready(I1)
    assert approve(I1)["code"] == 0
    monkeypatch.setenv(export.CONTACT_ENV, "report@example.invalid")
    out = tmp_path / "pub"
    assert export.export("public", out)["code"] == 0
    d = json.loads((out / "days" / f"{DATE}.json").read_text(encoding="utf-8"))
    assert [p["keyword"] for p in d["topics"]["pre"]] == ["가상 축제 일정"]
    assert d["topics"]["new"][0]["issue_id"] == I1 and "verdict_summary" in d["topics"]["new"][0]
    assert d["topics"]["new"][1] == {"keyword": "", "state": "정리 전"}
    assert d["restored"]["items"][0]["article"] == "가상 도시" and "verdict" not in json.dumps(d["restored"])
    assert "가상 인물 소문" not in (out / "days" / f"{DATE}.json").read_text(encoding="utf-8")
    # 작업본을 고치면 승인한 판은 그대로 남고, 판을 올리지 않은 새 내용은 공개되지 않는다
    put("day", day(new=[]))
    assert units.unit_publishable("day", DATE)[0]


def test_unit_test_root_rules(desk):
    h = put("day", day())
    assert units.approve_unit("day", DATE, 1, h, "편집자")["code"] == 2
    assert units.approve_unit("day", DATE, 1, h, revisions.TEST_BY)["code"] == 0
    assert not units.unit_publishable("day", DATE)[0]                                    # 시험 승인은 공개되지 않는다


@pytest.mark.parametrize("bad", [{"date": "2099-13-01"}, {"revision": 0}])
def test_day_shape(bad):
    assert units.check_unit("day", day(**bad), DATE)["errors"]
