"""Notion 에 올릴 행 — 지어낸 예시 이슈로 시험한다. 본문이 새지 않는지 본다."""
import importlib.util
import json
import pathlib
import shutil

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "issues"


@pytest.fixture()
def NR(tmp_path, monkeypatch):
    desk = tmp_path / "desk"
    shutil.copytree(FIX, desk / "issues")
    monkeypatch.setenv("OZL_DESK_ROOT", str(desk))
    spec = importlib.util.spec_from_file_location("notion_rows", ROOT / "scripts" / "notion_rows.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_rows_have_summary_only(NR, tmp_path):
    out = NR.build(cards_root=tmp_path / "cards")
    ids = [r["이슈 번호"] for r in out["issues"]]
    assert ids == sorted(ids) and "i20990101-01" in ids
    row = next(r for r in out["issues"] if r["이슈 번호"] == "i20990101-01")
    assert row["날짜"] == "2099-01-01" and row["제목"] and isinstance(row["민감 표시"], list)
    assert set(row) == {"이슈 번호", "제목", "날짜", "분야", "상태", "게시 가부", "민감 표시", "슈카 덱", "판 번호", "판정 집계", "검토", "사이트 주소"}
    # 본문이 새지 않는다: 주장의 요지와 확인된 사실의 문장이 어느 칸에도 없다
    issue = NR.model.load_issue("i20990101-01")
    body = [c.get("gist") for c in issue.get("claims") or []] + [f.get("text") for f in issue.get("facts") or []]
    blob = json.dumps(out, ensure_ascii=False)
    assert all(s not in blob for s in body if s and s != row["제목"])


def test_twice_gives_same_rows_and_product_keys_are_unique(NR, tmp_path):
    a, b = NR.build(cards_root=tmp_path / "cards"), NR.build(cards_root=tmp_path / "cards")
    assert a == b
    keys = [p["제작물 번호"] for p in a["products"]]
    assert len(keys) == len(set(keys)) and all(k.endswith(":web") for k in keys)


def test_excluded_issue_hides_title(NR, tmp_path, monkeypatch):
    issue = NR.model.load_issue("i20990101-02")
    issue["publish"] = {"state": "공개 제외", "why": "지어낸 까닭"}
    NR.model.save_issue(issue)
    row = next(r for r in NR.build(cards_root=tmp_path / "cards")["issues"] if r["이슈 번호"] == "i20990101-02")
    assert row["제목"] == NR.HIDDEN_TITLE and row["판정 집계"] == ""


def test_card_images_add_a_product_row(NR, tmp_path):
    issue = NR.model.load_issue("i20990101-01")
    d = tmp_path / "cards" / issue["slug"] / f"r{issue['revision']}"
    d.mkdir(parents=True)
    (d / "01.png").write_bytes(b"x")
    prods = NR.build(["i20990101-01"], cards_root=tmp_path / "cards")["products"]
    assert [p["형식"] for p in prods] == ["웹 이슈 화면", "카드 그림"]
