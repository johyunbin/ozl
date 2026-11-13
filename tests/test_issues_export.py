"""미리보기용·공개용 내보내기 시험(설계 11절, 6-11, 6-13, 6-14, 6-20). 지어낸 예시만 쓴다. 공개용 내용 시험은 시험 폴더를
실제 루트로 흉내 내고(시험 승인은 공개용에 나가지 않으므로) '편집자' 이름으로 승인한다."""
from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import body as B  # noqa: E402
from ozl.issues import export, mask, model, paths, revisions, style, units  # noqa: E402
from test_issues_check import I1, I2, desk, load  # noqa: E402,F401
from test_issues_revisions import approve, claim, edit, ready, real  # noqa: E402,F401

SLUG1, SLUG2 = "hanbit-bus-fare-400", "nuri-battery-recall"


@pytest.fixture
def contact(monkeypatch):
    monkeypatch.setenv(export.CONTACT_ENV, "report@example.invalid")


def run(out, mode="public", now=None):
    return export.export(mode, out, now=now)


def all_text(out: pathlib.Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(out.rglob("*.json")))


def jload(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def file_bytes(*ps):
    return [p.read_bytes() if p.exists() else None for p in ps]


def test_preview_marks_states(real, tmp_path):
    ready(I1)
    assert approve(I1)["code"] == 0
    edit(I2, lambda i: i.update(work_state="게시 대기"))
    man, appr = paths.manifest_file(), revisions.rev_dir(I1, 1) / "approval.json"
    before = file_bytes(man, appr)
    r = run(tmp_path / "pv", mode="preview")
    assert r["code"] == 0
    rows = {x["id"]: x for x in jload(tmp_path / "pv" / "index.json")["issues"]}
    assert rows[I1]["publish_state"] == "게시" and rows[I2]["publish_state"] == "검토 대기"
    b2 = jload(tmp_path / "pv" / "issues" / f"{SLUG2}.json")
    assert set(b2["internal"]["hidden"]) == {"claims.c5", "claims.c6"} and b2["internal"]["publish_state"] == "검토 대기"
    assert file_bytes(man, appr) == before
    assert jload(tmp_path / "pv" / "meta.json")["report_contact"] == ""


def test_public_only_manifest(real, contact, tmp_path):
    ready(I1)
    assert approve(I1)["code"] == 0
    ready(I2)                                                        # 게시 대기지만 승인하지 않았다
    r = run(tmp_path / "pub")
    assert r["code"] == 0, r
    txt = all_text(tmp_path / "pub")
    issue2 = model.load_issue(I2)
    for word in [SLUG2, I2, "누리전자", issue2["titles"]["chosen"]] + issue2["keywords"]:
        assert word not in txt
    assert SLUG1 in txt and jload(tmp_path / "pub" / "meta.json")["test"] is False


def test_excluded_content_not_in_public(real, contact, tmp_path, monkeypatch):
    ready(I2)
    assert approve(I2)["code"] == 0
    out = tmp_path / "pub"
    assert run(out)["code"] == 0
    txt = style.norm(all_text(out))
    issue = model.load_issue(I2)
    for cid in ("c5", "c6"):
        assert style.norm(claim(issue, cid)["gist"]) not in txt
    row = jload(out / "index.json")["issues"][0]
    assert row["hidden_claims"] == 2 and sum(row["verdict_summary"].values()) == 4
    # 출력 검사가 실제로 발화하는가 — 색인 줄에 숨긴 주장을 끼워 넣으면 실패하고 출력 폴더는 그대로다
    leak = claim(issue, "c5")["gist"]
    orig = export._index_row
    monkeypatch.setattr(export, "_index_row", lambda b, i, extra=None: dict(orig(b, i, extra), note=leak))
    before = all_text(out)
    r = run(out)
    assert r["code"] == 1 and any("공개 제외 항목(claims.c5)" in m for m in r["msgs"])
    assert all_text(out) == before and not list(tmp_path.glob("pub.tmp-*"))


def test_rerendered_body_mismatch_skipped(real, contact, tmp_path, monkeypatch):
    for iid in (I1, I2):
        ready(iid)
        assert approve(iid)["code"] == 0
    monkeypatch.setattr(B, "EXPORT_VERSION", B.EXPORT_VERSION + 1)
    r = run(tmp_path / "a")
    assert r["code"] == 4 and r["counts"]["issues"] == 0
    assert any("1판: 다시 만든 본문이 승인 때와 다르다" in m for m in r["msgs"])
    monkeypatch.setattr(B, "EXPORT_VERSION", B.EXPORT_VERSION - 1)
    orig = B.issue_body
    monkeypatch.setattr(B, "issue_body", lambda i, e, rev_at="", copy_errs=None, **kw: dict(orig(i, e, rev_at, copy_errs, **kw), extra="모양 바뀜"))
    assert run(tmp_path / "b")["code"] == 4


def test_public_requires_contact(real, tmp_path, monkeypatch):
    ready(I1)
    assert approve(I1)["code"] == 0
    for v in ("", "   "):
        monkeypatch.setenv(export.CONTACT_ENV, v)
        r = run(tmp_path / "pub")
        assert r["code"] == 2 and r["msgs"] == [export.MSG_CONTACT] and not (tmp_path / "pub").exists()
    monkeypatch.delenv(export.CONTACT_ENV)
    assert run(tmp_path / "pv", mode="preview")["code"] == 0             # 미리보기용은 실패하지 않는다
    monkeypatch.setenv(export.CONTACT_ENV, "report@example.invalid")
    assert run(tmp_path / "pub")["code"] == 0
    assert jload(tmp_path / "pub" / "meta.json")["report_contact"] == "report@example.invalid"


def _day(date, iid):
    d = {"date": date, "revision": 1, "made_at": f"{date} 07:00",
         "line": {"updated_at": f"{date} 07:00", "source_kinds_ok": ["공식 발표"], "source_kinds_failed": []},
         "new": [{"issue_id": iid, "status_line": "시가 인상안을 발표했다."}], "ongoing": [], "upcoming": [], "pre": [],
         "empty_note": {"new": "", "ongoing": "오늘 이어지는 기록은 없다."}}
    model.save_yaml(units.unit_file("day", date), d)
    return units.approve_unit("day", date, 1, units.unit_hash("day", d), "편집자")


def test_withdraw_removes_everywhere(real, contact, tmp_path):
    ready(I1)
    assert approve(I1, now="2099-01-02T12:00:00+09:00")["code"] == 0
    edit(I1, lambda i: i.update(revision=2, rev_line="찾아본 범위를 더 적었다."))
    edit(I1, lambda i: claim(i, "c3").update(searched="시 교통 통계, 시의회 회의록, 시 보도자료"))
    ready(I1)
    assert approve(I1, now="2099-01-03T12:00:00+09:00")["code"] == 0
    assert _day("2099-01-03", I1)["code"] == 0
    out = tmp_path / "pub"
    assert run(out)["code"] == 0
    assert jload(out / "issues" / f"{SLUG1}.json")["rev"] == 2
    assert jload(out / "days" / "2099-01-03.json")["records"][0]["slug"] == SLUG1
    assert revisions.withdraw(I1, 2, "편집자", "2판 문장 점검")["code"] == 0
    assert run(out)["code"] == 0
    assert jload(out / "issues" / f"{SLUG1}.json")["rev"] == 1 and not (out / "issues" / SLUG1 / "r" / "2.json").exists()
    assert revisions.withdraw(I1, None, "편집자", "사실 확인 다시")["code"] == 0
    assert run(out)["code"] == 0
    txt = all_text(out)
    title = model.load_issue(I1)["titles"]["chosen"]
    for name in ("index.json", "keywords.json", "search.json", "feed.json", "days/2099-01-03.json", "days/2099-01-02.json"):
        p = out / name
        if p.exists():
            assert SLUG1 not in p.read_text(encoding="utf-8") and title not in p.read_text(encoding="utf-8")
    assert SLUG1 not in txt and title not in txt and not (out / "issues" / SLUG1).exists()
    day = jload(out / "days" / "2099-01-03.json")
    assert day["records"] == [] and day["topics"]["new"] == [{"keyword": "", "state": "정리 전"}]
    td = jload(out / "takedowns.json")
    assert {(t["id"], t["rev"]) for t in td} == {(I1, 2), (I1, None)}
    assert any(c.get("kind") == "내림" and c.get("id") == I1 for c in jload(out / "corrections.json")["items"])
    assert (revisions.rev_dir(I1, 1) / "issue.yaml").is_file()          # 승인한 원본은 비공개 폴더에 그대로


def _electionize(issue):
    issue["sensitive"] = ["선거"]
    issue["election"] = {"kind": "가상 시장 선거", "date": "2099-04-10", "poll_close": "18:00", "restrict_from": "2099-04-04",
                         "schedule_url": "https://election.example/schedule"}
    for lst in model.ITEM_LISTS:
        for it in issue.get(lst) or []:
            it["election_mask"] = it.get("id") == "c3"


def test_election_mask_window(real, contact, tmp_path):
    edit(I1, _electionize)
    ready(I1)
    r = approve(I1)
    assert r["code"] == 0, r["msg"]
    gist = claim(model.load_issue(I1), "c3")["gist"]
    out_in, out_after = tmp_path / "in", tmp_path / "after"
    assert run(out_in, now="2099-04-05T10:00:00+09:00")["code"] == 0
    b = jload(out_in / "issues" / f"{SLUG1}.json")
    assert gist not in all_text(out_in) and mask.MASKED_TEXT in json.dumps(b, ensure_ascii=False)
    assert b["masked"]["rule_version"] == mask.RULE_VERSION and len(b["masked"]["original_body_hash"]) == 32
    assert run(out_after, now="2099-04-10T18:01:00+09:00")["code"] == 0
    b = jload(out_after / "issues" / f"{SLUG1}.json")
    assert "masked" not in b and gist in json.dumps(b, ensure_ascii=False)


def test_capture_outside_rejected_on_export(desk, contact, tmp_path):
    src = paths.captures_dir(I1) / f"{I1}-e1" / "source.html"
    shutil.copy(src, paths.issue_dir(I1) / "copy_of_source.html")
    for mode in ("preview", "public"):
        r = run(tmp_path / mode, mode=mode)
        assert r["code"] == 1 and "captures 폴더 밖" in r["msgs"][0] and not (tmp_path / mode).exists()
    sys.path.insert(0, str(ROOT / "scripts"))
    import private_bundle  # noqa: E402  백업 검사도 같은 파일을 거르는지(스크립트는 고치지 않는다)
    hashes = private_bundle.copy_hashes(private_bundle.build_manifest(desk))
    bad = private_bundle.check_paths(desk, [f"issues/{I1}/copy_of_source.html"], hashes)
    assert bad and "해시가 같은 파일" in bad[0]


def test_test_out_dir_guard(desk, tmp_path):
    out = ROOT / "private" / "test_desk_export_guard_out"
    r = run(out, mode="preview")
    assert r["code"] == 2 and r["msgs"] == [export.MSG_TEST_OUT] and not out.exists()
    assert run(desk / "out", mode="preview")["code"] == 0
    assert jload(desk / "out" / "meta.json")["test"] is True


def test_example_flag(real, contact, tmp_path):
    ready(I1)
    assert approve(I1)["code"] == 0
    assert run(tmp_path / "pub")["code"] == 0
    b = jload(tmp_path / "pub" / "issues" / f"{SLUG1}.json")
    assert b["example"] is True and not b["title"].startswith("[예시]")
    assert jload(tmp_path / "pub" / "index.json")["issues"][0]["example"] is True
