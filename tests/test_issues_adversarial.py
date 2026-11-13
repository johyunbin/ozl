"""적대 검토(2026-11-14, 다른 모델 계열 셋) 지적 반영 시험 — 지적마다 그 구멍만 어긋난 최소 자료로 거부까지 본다.
고치기 전 코드에서는 실패한다. 자료는 전부 지어낸 것이다(가상의 한빛시, 가상의 회사 누리전자, 가상의 갑 후보). 네트워크를 쓰지 않는다."""
from __future__ import annotations

import copy
import json
import pathlib
import shutil
import sys
import threading
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import body as B  # noqa: E402
from ozl.issues import digest, export, mask, model, numbers, paths, revisions, rules, units  # noqa: E402
from ozl.issues.__main__ import main  # noqa: E402
from test_issues_check import (I1, I2, add_official, claim, desk, doc_of, errors, has, link, load,  # noqa: E402,F401
                               new_claim)
from test_issues_hardening import _approved, _day, _elect, _resync  # noqa: E402
from test_issues_revisions import add_review, approve, edit, ready, real  # noqa: E402,F401

E1, E2, E3 = I1 + "-e1", I1 + "-e2", I1 + "-e3"
F1, F2, F3, F4 = I2 + "-e1", I2 + "-e2", I2 + "-e3", I2 + "-e4"
SLUG1 = "hanbit-bus-fare-400"
IN_WINDOW = "2099-04-05T10:00:00+09:00"


@pytest.fixture
def contact(monkeypatch):
    monkeypatch.setenv(export.CONTACT_ENV, "report@example.invalid")


def jload(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def all_text(out: pathlib.Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(out.rglob("*.json")))


# ── astra-1: 해시 밖 칸(trend, topic_state, score.json)은 모양을 검사하고 검사한 값만 싣는다 ──
def test_trend_shape_checked(desk):
    issue, evs = load(I1)
    issue["trend"] = dict(issue["trend"], internal="비공개 상담 기록")
    assert has(errors(issue, evs), "trend", "trend 는")
    issue, evs = load(I1)
    issue["trend"]["asof"] = "갑 후보 지지율이 앞선다"
    assert has(errors(issue, evs), "trend", "trend 는")
    issue, evs = load(I1)
    issue["trend"]["bars7"] = ["비공개", 0, 0, 0, 0, 0, 0]
    assert has(errors(issue, evs), "trend", "trend 는")
    assert model.clean_trend({"score": 41, "bars7": [0] * 7, "asof": "2099-01-02 07:40", "formula_version": 1}) is not None


def test_export_trend_and_topic_state_sanitized(real, contact, tmp_path):
    ready(I1)
    assert approve(I1)["code"] == 0
    sp = revisions.rev_dir(I1, 1) / "score.json"
    s = jload(sp)
    s.update(internal="비공개 상담 기록 하나", asof="갑 후보 지지율이 앞선다")
    sp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    edit(I1, lambda i: i.update(trend=dict(i["trend"], internal="비공개 상담 기록 둘"), topic_state="비공개 상담 기록 셋"))
    out = tmp_path / "pub"
    assert export.export("public", out)["code"] == 0
    txt = all_text(out)
    assert "비공개 상담 기록" not in txt and "지지율" not in txt
    b = jload(out / "issues" / f"{SLUG1}.json")
    assert b["trend"] is None and b["trend_now"] is None
    assert jload(out / "index.json")["issues"][0]["topic_state"] is None
    # 모양이 맞는 추이는 그대로 실린다
    edit(I1, lambda i: i.update(trend={"score": 50, "bars7": [0, 0, 0, 0, 0, 0.5, 1], "asof": "2099-01-03 07:40", "formula_version": 1},
                                topic_state="커지는 중"))
    assert export.export("public", out)["code"] == 0
    b = jload(out / "issues" / f"{SLUG1}.json")
    assert b["trend_now"]["score"] == 50 and jload(out / "index.json")["issues"][0]["topic_state"] == "커지는 중"


# ── astra-2: 화제 목록 지문에서 빼는 칸은 정해진 자리만, 모르는 칸은 거부 ──
def test_day_hash_skip_only_known_paths():
    d = _day()
    h = units.unit_hash("day", d)
    d2 = copy.deepcopy(d)
    d2["new"][0]["score"] = "일반인 비공개 기록"
    assert units.unit_hash("day", d2) != h
    assert units.check_unit("day", d2)["errors"]
    d3 = copy.deepcopy(d)
    d3["new"][0].update(verdict_summary={"확인": 1}, hidden_claims=0)         # 본문에서 계산하는 칸은 지문 밖
    assert units.unit_hash("day", d3) == h and not units.check_unit("day", d3)["errors"]
    d4 = copy.deepcopy(d)
    d4["upcoming"][0]["trend"] = "일반인 비공개 기록"
    assert units.unit_hash("day", d4) != h and units.check_unit("day", d4)["errors"]
    d5 = copy.deepcopy(d)
    d5["memo"] = "일반인 비공개 기록"
    assert units.check_unit("day", d5)["errors"]
    out = units.public_day(d2, lambda i: True)
    assert "일반인 비공개 기록" not in json.dumps(out, ensure_ascii=False)


# ── astra-3 · agy-13: 최상위 numbers 지도는 실제 글 칸 경로만, 숫자 항목은 정해진 칸만 ──
@pytest.mark.parametrize("key", ["what_new.private_notes", "titles.bogus", "claims.c1.gist", "facts.f1.text"])
def test_top_numbers_paths_checked(desk, key):
    issue, evs = load(I1)
    issue["numbers"][key] = [{"value": "900억 원", "kind": "공식", "evidence": "none", "internal": "일반인 비공개 기록"}]
    assert has(errors(issue, evs), f"numbers.{key}", "글 칸"), errors(issue, evs)
    b = B.issue_body(issue, evs)
    assert key not in b["numbers"] and "일반인 비공개 기록" not in json.dumps(b, ensure_ascii=False)


def test_number_entry_keys_checked(desk):
    issue, evs = load(I1)
    issue["numbers"]["what_new"][0]["internal"] = "일반인 비공개 기록"
    assert has(errors(issue, evs), "what_new", "숫자 항목에 둘 수 없는 칸")
    issue, evs = load(I1)
    issue["facts"][0]["numbers"][0]["internal"] = "일반인 비공개 기록"
    assert has(errors(issue, evs), "facts.f1.text", "숫자 항목에 둘 수 없는 칸")
    issue, evs = load(I1)
    issue["numbers"]["so_far.1"][0]["inputs"]["결산연도"]["memo"] = "일반인 비공개 기록"
    assert has(errors(issue, evs), "so_far.1", "계산 입력")


def test_figure_evidence_list_and_missing(desk):
    issue, evs = load(I2)
    issue["figures"].append({"id": "g1", "kind": "공식 문서 캡처", "caption": "회수 공고", "alt": "회수 공고를 옮긴 그림",
                             "evidence": [F1], "target_kind": "기관과 정책", "publish": "게시 가능"})
    led = json.loads(paths.ledger_file().read_text(encoding="utf-8"))
    led["items"][I2]["g"] = 1
    paths.write_atomic(paths.ledger_file(), json.dumps(led, ensure_ascii=False))
    assert has(errors(issue, evs), "figures.g1.evidence", "근거 번호")
    issue["figures"][0]["evidence"] = I2 + "-e9"
    assert has(errors(issue, evs), "figures.g1.evidence", "근거 기록이 없다")
    issue["figures"][0]["evidence"] = F1
    assert not has(errors(issue, evs), "figures.g1.evidence", "")


# ── astra-4: 작은 주장은 '일부 맞음'에만 ──
def test_parts_only_for_partly_true(desk):
    issue, evs = load(I1)
    claim(issue, "c3")["parts"] = [{"id": "p1", "gist": "요금 인상이 승객 감소의 원인이다.", "core": True, "verdict": "확인", "evidence": []}]
    assert has(errors(issue, evs), "claims.c3.parts", "일부 맞음")


# ── astra-5: 당사자 인정의 범위는 근거 조건 글자와 무관하게 ──
def test_admission_scope_any_basis(desk):
    issue, evs = load(I2)
    c = claim(issue, "c2")
    c["scope"] = "회수 대상 제품의 교환 비용 전체"
    c["evidence"][0].update(scope=c["scope"], basis="다", refers_to_original=True)
    errs = errors(issue, evs)
    assert has(errs, f"claims.c2.evidence.{F2}", "인정한 범위"), errs


# ── astra-6 · agy-1: '사실과 다름'도 충돌 근거를 보고, 의혹 검사는 판정 쪽 근거만 ──
def test_false_with_conflicting_support(desk):
    issue, evs = load(I1)
    c = claim(issue, "c1")
    c["evidence"].append(dict(c["evidence"][0], stance="지지"))                # 같은 근거를 양쪽에
    assert has(errors(issue, evs), "claims.c1.verdict", "근거끼리 어긋나면")


def test_allegation_needs_ga_on_verdict_side(desk):
    issue, evs = load(I1)
    c = claim(issue, "c1")
    c["allegation"] = True
    c["evidence"] = [dict(c["evidence"][0], stance="지지"),
                     link(E1, "반대", "다", c, passage_role="사실 기재", refers_to_original=True)]
    assert has(errors(issue, evs), "claims.c1.verdict", rules.MSG_ALLEGATION)


# ── agy-6: '발표 여부' 예외도 문서 쪽 방어를 받는다 ──
@pytest.mark.parametrize("bad", [{"doc_stage": "조사 중"}, {"transcribed": True}, {"doc_stage": "한쪽 주장을 옮긴 것"}, "passage"])
def test_announce_exception_doc_stage(desk, bad):
    issue, _ = load(I1)
    eid = add_official(I1, "한빛통계원은 요금 인상을 권고하는 자료를 낸 적이 없다.",
                       doc_of("한빛통계원", role="당사자", kind="보도자료", stage="작성자 자신의 발표", authority=False, denies_own_document=True),
                       kind="공식 원문", base="n/a", as_of="n/a", revision="n/a")
    evs = model.load_evidences(I1)
    c = new_claim(I1, issue, kind="발표 여부", attributed_to="한빛통계원", gist="한빛통계원이 요금 인상을 권고하는 자료를 냈다.",
                  subject="한빛통계원의 요금 인상 권고 자료", period="해당 없음", scope="한빛통계원 발표", verdict="사실과 다름")
    c["evidence"] = [link(eid, "반대", "없음", c, passage_role="사실 기재")]
    issue["so_far_refs"].append(c["id"])
    assert errors(issue, evs) == []
    if bad == "passage":
        c["evidence"][0]["passage_role"] = "당사자 주장을 옮긴 것"
    else:
        evs[eid]["doc"].update(bad)
    assert has(errors(issue, evs), f"claims.{c['id']}.verdict", "")


# ── agy-5: 빈 제목 후보, 빈 작은 주장 요지, 정정의 칸 ──
def test_blank_titles_parts_corrections(desk):
    issue, evs = load(I1)
    issue["titles"]["candidates"] = [{"text": "", "angle": a} for a in ("판정", "규모", "절차")]
    issue["titles"]["chosen"] = ""
    issue["titles"]["basis_claims"] = []
    issue["numbers"] = {k: v for k, v in issue["numbers"].items() if not k.startswith("titles.")}
    errs = errors(issue, evs)
    assert has(errs, "titles.candidates.0.text", "없다") and has(errs, "titles.chosen", "없다")
    issue, evs = load(I1)
    claim(issue, "c5")["parts"][0]["gist"] = ""
    assert has(errors(issue, evs), "claims.c5.parts.p1.gist", "없다")
    issue, evs = load(I1)
    issue["corrections"] = [{"kind": "정정"}]
    errs = errors(issue, evs)
    assert has(errs, "corrections.0", "rev")
    issue["corrections"] = [{"rev": 1, "at": "2099-01-03", "kind": "정정", "before": "적자 수치의 기준 연도", "after": "적자는 결산 기준",
                             "why": "표기를 고쳤다", "memo": "일반인 비공개 기록"}]
    assert has(errors(issue, evs), "corrections.0", "rev")
    issue["corrections"][0].pop("memo")
    assert not has(errors(issue, evs), "corrections.0", "")


# ── agy-7: 키워드의 판세 낱말과 수량 ──
@pytest.mark.parametrize("kw,election", [("지지율", True), ("이백억 원", False), ("200억 원", False)])
def test_keywords_poll_and_numbers(desk, kw, election):
    issue, evs = load(I1)
    if election:
        _elect(issue)
    issue["keywords"].append(kw)
    assert has(errors(issue, evs), "keywords.3", "키워드"), errors(issue, evs)


# ── astra-9: 출처 제목과 키워드의 판세 낱말은 가림 기간에 가린다 ──
def test_mask_source_titles_and_keywords(desk):
    issue, evs = load(I1)
    _elect(issue)
    evs[E1]["source"]["title"] = "갑 후보 지지율이 앞선다"
    issue["keywords"].append("판세 비교")
    body = B.issue_body(issue, evs)
    assert "지지율" in json.dumps(body, ensure_ascii=False)
    out = mask.apply(body, IN_WINDOW)
    flat = json.dumps(out, ensure_ascii=False)
    assert "지지율" not in flat and "판세 비교" not in flat
    assert "지지율" in json.dumps(mask.apply(body, "2099-04-10T18:01:00+09:00"), ensure_ascii=False)


# ── astra-7 · agy-2: 계산식은 모든 입력을 써야 하고 상수로 값을 만들지 않는다 ──
@pytest.mark.parametrize("value,formula", [("700원", "700"), ("700원", "a*0+700"), ("400원", "a*1"), ("400원", "(a)"),
                                           ("1000원", "a-a+1000"), ("400원", "a+b-b"), ("500원", "a + 100"), ("401원", "a + 1 + 0"),
                                           ("400원", "a*10/10")])
def test_formula_must_use_inputs(desk, value, formula):
    issue, evs = load(I1)
    f = issue["facts"][0]
    f["text"] = f"한빛시 요금 값은 {value}이다."
    f["numbers"] = [{"value": value, "kind": "계산", "unit": "원", "rounding": "그대로", "formula": formula,
                     "inputs": {"a": {"value": "400원", "kind": "공식", "evidence": E1},
                                "b": {"value": "400원", "kind": "공식", "evidence": E1}} if "b" in formula
                     else {"a": {"value": "400원", "kind": "공식", "evidence": E1}}}]
    assert has(errors(issue, evs), "facts.f1.text", "계산 값"), errors(issue, evs)


def test_formula_ok_with_scale(desk):
    issue, evs = load(I1)
    f = issue["facts"][0]
    f["text"] = "한빛시 요금 값은 4원이다."
    f["numbers"] = [{"value": "4원", "kind": "계산", "unit": "원", "rounding": "그대로", "formula": "a / 100",
                     "inputs": {"a": {"value": "400원", "kind": "공식", "evidence": E1}}}]
    assert not has(errors(issue, evs), "facts.f1.text", "")


# ── astra-8 · agy-2: 음수와 0 ──
@pytest.mark.parametrize("text,want", [("-2억 원", -2e8), ("0억 원", 0.0), ("0천 명", 0.0), ("1만 2천 개", 12000.0),
                                       ("-3", -3.0), ("3천3백만 원", 33000000.0), ("-1억 5천만 원", -1.5e8)])
def test_to_number_sign_and_zero(text, want):
    assert numbers.to_number(text) == want


# ── agy-3 · astra-11 · astra-12: 판 공개 판정은 고정 사본의 상태와 번호까지 본다 ──
@pytest.mark.parametrize("fn", [
    lambda i: i.update(publish={"state": "공개 제외", "why": "검토 중"}),
    lambda i: i.update(work_state="작성 중"),
    lambda i: i.update(reviews=[]),
    lambda i: i.update(slug="hanbit-bus-fare-other"),
])
def test_publishable_checks_fixed_state(real, fn):
    d = _approved()

    def change(d):
        i = model.load_yaml(d / "issue.yaml")
        fn(i)
        model.save_yaml(d / "issue.yaml", i)
    _resync(d, change)
    assert not revisions.revision_publishable(I1, 1)[0]


@pytest.mark.parametrize("field", ["approved_by", "approved_at"])
def test_publishable_needs_approver(real, field):
    d = _approved()
    man = revisions.load_manifest()
    revisions.entry(man, "issue", I1, 1)[field] = ""
    revisions.save_manifest(man)
    appr = jload(d / "approval.json")
    appr[field] = ""
    (d / "approval.json").write_text(json.dumps(appr, ensure_ascii=False), encoding="utf-8")
    assert not revisions.revision_publishable(I1, 1)[0]


def test_publishable_duplicate_entry_and_rev_type(real):
    _approved()
    man = revisions.load_manifest()
    man["entries"].append(dict(revisions.entry(man, "issue", I1, 1)))
    revisions.save_manifest(man)
    assert not revisions.revision_publishable(I1, 1)[0]
    assert not revisions.revision_publishable(I1, True)[0]


def test_publishable_fixed_revision_matches(real):
    """정상 r1 을 r2 자리로 복사하고 발행 목록·승인 기록의 판만 2로 맞추면 공개되지 않는다."""
    d = _approved()
    d2 = revisions.rev_dir(I1, 2)
    shutil.copytree(d, d2)
    man = revisions.load_manifest()
    man["entries"].append(dict(revisions.entry(man, "issue", I1, 1), rev=2))
    revisions.save_manifest(man)
    appr = jload(d2 / "approval.json")
    appr["rev"] = 2
    (d2 / "approval.json").write_text(json.dumps(appr, ensure_ascii=False), encoding="utf-8")
    assert not revisions.revision_publishable(I1, 2)[0]
    assert revisions.latest_public(I1) == 1


def test_test_approval_cannot_be_renamed(desk):
    """시험 폴더의 시험 승인은 발행 목록과 승인 기록의 이름을 둘 다 바꿔도 공개되지 않는다."""
    ready(I1)
    assert approve(I1)["code"] == 0
    man = revisions.load_manifest()
    revisions.entry(man, "issue", I1, 1)["approved_by"] = "편집자"
    revisions.save_manifest(man)
    p = revisions.rev_dir(I1, 1) / "approval.json"
    p.write_text(json.dumps(dict(jload(p), approved_by="편집자"), ensure_ascii=False), encoding="utf-8")
    assert not revisions.revision_publishable(I1, 1)[0]
    h = units.unit_hash("day", _day())
    model.save_yaml(units.unit_file("day", "2099-01-03"), _day())
    assert units.approve_unit("day", "2099-01-03", 1, h, revisions.TEST_BY)["code"] == 0
    man = revisions.load_manifest()
    revisions.entry(man, "day", "2099-01-03", 1)["approved_by"] = "편집자"
    revisions.save_manifest(man)
    f = units.rev_file("day", "2099-01-03", 1).with_suffix(".approval.json")
    f.write_text(json.dumps(dict(jload(f), approved_by="편집자"), ensure_ascii=False), encoding="utf-8")
    assert not units.unit_publishable("day", "2099-01-03")[0]


def _approve_day(date="2099-01-03"):
    d = _day(date=date)
    model.save_yaml(units.unit_file("day", date), d)
    assert units.approve_unit("day", date, 1, units.unit_hash("day", d), "편집자")["code"] == 0
    return date


def test_unit_publishable_rev_and_approver(real):
    date = _approve_day()
    f1 = units.rev_file("day", date, 1)
    f2 = units.rev_file("day", date, 2)
    shutil.copy(f1, f2)
    a = jload(f1.with_suffix(".approval.json"))
    a["rev"] = 2
    f2.with_suffix(".approval.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    man = revisions.load_manifest()
    man["entries"].append(a)
    revisions.save_manifest(man)
    assert units.unit_publishable("day", date)[2] == 1                       # 고정 사본의 판이 1 이면 2판으로 세지 않는다
    man["entries"].pop()
    e = revisions.entry(man, "day", date, 1)
    e["approved_by"] = ""
    revisions.save_manifest(man)
    f1.with_suffix(".approval.json").write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    assert not units.unit_publishable("day", date)[0]
    man["entries"] = [dict(e, approved_by="편집자"), dict(e, approved_by="편집자")]
    revisions.save_manifest(man)
    f1.with_suffix(".approval.json").write_text(json.dumps(man["entries"][0], ensure_ascii=False), encoding="utf-8")
    assert not units.unit_publishable("day", date)[0]                        # 같은 판이 두 줄


# ── agy-11: 승인 순서(이름 규칙이 먼저), 내린 판의 재승인, 요청 번호 충돌 ──
def test_approve_ordering_and_request_id(real):
    ready(I1)
    assert approve(I1)["code"] == 0
    r = approve(I1, by=revisions.TEST_BY)
    assert r["code"] == 2 and r["msg"] == revisions.MSG_TEST_IN_REAL
    assert revisions.withdraw(I1, 1, "편집자", "다시 확인")["code"] == 0
    r = approve(I1)
    assert r["code"] == 3 and "내린" in r["msg"]
    h2 = ready(I2)
    assert revisions.approve(I2, 1, h2, "편집자", request_id="req-1", now="2099-01-02T12:00:00+09:00")["code"] == 0
    assert revisions.approve(I2, 1, h2, "편집자", request_id="req-1")["code"] == 0      # 같은 요청은 멱등
    date = _approve_day()
    d = units.load_unit("day", date)
    assert units.approve_unit("day", date, 1, units.unit_hash("day", d), revisions.TEST_BY)["code"] == 2
    model.save_yaml(units.unit_file("day", date), dict(d, revision=2))
    r = units.approve_unit("day", date, 2, units.unit_hash("day", dict(d, revision=2)), "편집자", request_id="req-1")
    assert r["code"] == 3 and "request_id" in r["msg"]


# ── agy-4 · astra-13: 검토 추가는 잠금 안에서 ──
def test_add_review_concurrent(desk, monkeypatch):
    d = revisions.notes_dir(I1)
    d.mkdir(parents=True, exist_ok=True)
    notes = []
    for k in (1, 2):
        f = d / f"conc_{k}.md"
        f.write_text(f"동시 검토 {k} — 시험용으로 지어낸 원문\n", encoding="utf-8")
        notes.append(f)
    orig = model.load_issue

    def slow(iid):
        x = orig(iid)
        time.sleep(0.4)
        return x
    monkeypatch.setattr(model, "load_issue", slow)
    ts = [threading.Thread(target=revisions.add_review, args=(I1, "문장 대조", f"모델 {k}", "anthropic", "통과"),
                           kwargs={"notes_path": str(notes[k])}) for k in (0, 1)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    monkeypatch.setattr(model, "load_issue", orig)
    rows = model.load_issue(I1)["reviews"]
    assert sorted(r["id"] for r in rows) == ["r1", "r2"]


# ── agy-10 · astra-10: 이어받기는 사본의 해시, 같은 해시의 검토, 묶인 지적만 믿는다 ──
def _finding(iid, field, **kw):
    return add_review(iid, "문장 대조", "Claude Sonnet", "anthropic", "지적", findings=[{"field": field, "note": "고친다"}], **kw)


def test_followup_snapshot_must_match_hash(desk):
    h0 = ready(I2)
    _finding(I2, "claims.c3.would_decide")                                  # r3
    edit(I2, lambda i: claim(i, "c3").update(would_decide="대법원의 확정 판결"))
    edit(I2, lambda i: claim(i, "c1").update(gist="회수 대상은 1만 2천 개이고, 모두 국내용이다."))     # 지적 밖의 변경
    model.save_yaml(revisions.snapshot_file(I2, h0), digest.snapshot_view(*load(I2)))               # 이전 사본을 지금 내용으로 바꿔치기
    add_review(I2, "수정 확인", "Claude Sonnet", "anthropic", "통과", before_hash=h0, addresses=["r3"])
    assert revisions.review_state(*load(I2)) == "검토 대기"


def test_followup_addresses_same_hash(desk):
    ready(I2)
    _finding(I2, "claims")                                                  # r3 — 옛 내용의 넓은 지적
    edit(I2, lambda i: claim(i, "c3").update(would_decide="대법원의 확정 판결"))
    h1 = ready(I2)                                                          # r4, r5 — 새 내용의 검토 완료
    edit(I2, lambda i: claim(i, "c1").update(gist="회수 대상은 1만 2천 개이고, 모두 국내용이다."))
    add_review(I2, "수정 확인", "Claude Sonnet", "anthropic", "통과", before_hash=h1, addresses=["r3"])
    assert revisions.review_state(*load(I2)) == "검토 대기"


def test_followup_findings_tamper(desk):
    h0 = ready(I2)
    _finding(I2, "claims.c3.would_decide")                                  # r3
    edit(I2, lambda i: claim(i, "c3").update(would_decide="대법원의 확정 판결"))
    add_review(I2, "수정 확인", "Claude Sonnet", "anthropic", "통과", before_hash=h0, addresses=["r3"])
    assert revisions.review_state(*load(I2)) == "검토 완료"
    edit(I2, lambda i: claim(i, "c1").update(gist="회수 대상은 1만 2천 개이고, 모두 국내용이다."))
    edit(I2, lambda i: i["reviews"][2]["findings"].append({"field": "claims.c1", "note": "나중에 더함"}))
    add_review(I2, "수정 확인", "Claude Sonnet", "anthropic", "통과", before_hash=h0, addresses=["r3"])
    assert revisions.review_state(*load(I2)) == "검토 대기"


# ── agy-9: 출력 자리는 자료실 하위 폴더를 거부하고, 바꾸다 실패하면 기존 출력을 되살린다 ──
def test_out_rejects_desk_subfolders(desk):
    for out in (paths.issues_dir() / "pub", desk / "daily_lists" / "pub", desk / "restored" / "pub"):
        r = export.export("preview", out)
        assert r["code"] == 2 and not out.exists(), (out, r)


def test_out_rejects_real_root_subfolder(real):
    r = export.export("preview", real / "pub")
    assert r["code"] == 2 and not (real / "pub").exists()


def test_export_swap_restores_on_failure(desk, monkeypatch):
    out = desk / "pv"
    assert export.export("preview", out)["code"] == 0
    before = all_text(out)
    orig = pathlib.Path.rename

    def bad(self, target):
        if ".tmp-" in self.name:
            raise OSError("가짜 실패")
        return orig(self, target)
    monkeypatch.setattr(pathlib.Path, "rename", bad)
    with pytest.raises(OSError):
        export.export("preview", out)
    monkeypatch.setattr(pathlib.Path, "rename", orig)
    assert out.is_dir() and all_text(out) == before
    assert not list(desk.glob("pv.old-*")) and not list(desk.glob("pv.tmp-*"))


# ── agy-8: 주소 이름과 별칭은 다른 이슈와 겹치지 않는다 ──
def test_slug_conflict(desk):
    edit(I2, lambda i: i.update(slug=SLUG1))
    errs = revisions.check_ids([I2])[I2]["errors"]
    assert any("주소 이름" in e and I1 in e for e in errs), errs
    edit(I2, lambda i: i.update(slug="nuri-battery-recall", aliases=[SLUG1]))
    errs = revisions.check_ids([I2])[I2]["errors"]
    assert any("주소 이름" in e and I1 in e for e in errs), errs
    edit(I2, lambda i: i.update(aliases=["nuri-battery-recall"]))
    assert any("aliases" in e for e in revisions.check_ids([I2])[I2]["errors"])


def test_export_skips_duplicate_slug(desk):
    edit(I2, lambda i: i.update(slug=SLUG1))
    out = desk / "pv"
    r = export.export("preview", out)
    assert r["code"] == 4 and any("주소 이름" in m for m in r["msgs"]), r
    assert jload(out / "issues" / f"{SLUG1}.json")["id"] == I1


def test_new_slug_taken(desk):
    assert main(["new", "--date", "2099-01-05", "--slug", SLUG1]) == 2
    assert main(["new", "--date", "2099-01-05", "--slug", "fresh-topic"]) == 0
    assert main(["new", "--date", "2099-01-05", "--slug", "fresh-topic"]) == 2


# ── agy-12: 복원판·화제 목록 항목은 허용한 칸만 ──
@pytest.mark.parametrize("bad", [
    lambda r: r["items"][0].update(verdict_summary={"확인": 1}),
    lambda r: r.update(scores=[1]),
    lambda r: r["items"][0].update(issue_ids=[I1]),
])
def test_restored_allowed_keys(bad):
    r = {"date": "2099-01-03", "revision": 1, "made_at": "2099-01-03 07:00", "label": units.RESTORED_LABEL,
         "source_url": "https://wiki.example/pageviews", "items": [{"rank": 1, "article": "가상 도시", "views": 1200}]}
    assert not units.check_unit("restored", r)["errors"]
    bad(r)
    assert units.check_unit("restored", r)["errors"]


def test_day_issue_item_keyword_checked():
    d = _day(new=[{"issue_id": I1, "status_line": "시가 인상안을 발표했다.", "keyword": "지지율 1위"}])
    assert any(e.startswith("new.0.keyword") for e in units.check_unit("day", d)["errors"])
    d = _day(new=[{"issue_id": I1, "status_line": "시가 인상안을 발표했다.", "keyword": "가상 버스 요금"}])
    assert not units.check_unit("day", d)["errors"]
    out = units.public_day(d, lambda i: False)
    assert out["new"] == [{"keyword": "가상 버스 요금", "state": "정리 전"}]


# ── sol: 세 번째 검토(sol)에만 있던 지적 ──────────────────────────────
def test_out_existing_with_other_files_rejected(desk):
    """sol-1: 이전 내보내기 폴더라도 내보내기가 쓰지 않는 파일(정본 yaml 등)이 섞여 있으면 폴더째 바꾸지 않는다."""
    out = desk / "pv"
    assert export.export("preview", out)["code"] == 0
    (out / "2099-01-03.yaml").write_text("date: '2099-01-03'\n", encoding="utf-8")
    r = export.export("preview", out)
    assert r["code"] == 2 and (out / "2099-01-03.yaml").is_file()


def test_computed_negative_sign(desk):
    """sol-6: 부호가 반대인 계산 값은 다시 계산한 값과 다르다."""
    issue, evs = load(I1)
    f = issue["facts"][0]
    f["text"] = "한빛시 요금 차이는 -4억 원이다."
    f["numbers"] = [{"value": "-4억 원", "kind": "계산", "unit": "원", "rounding": "그대로", "formula": "a * 1000000",
                     "inputs": {"a": {"value": "400원", "kind": "공식", "evidence": E1}}}]
    assert has(errors(issue, evs), "facts.f1.text", "다시 계산한 값")
    f["numbers"][0]["formula"] = "a * 100000000"          # 셈 입력에 10^8 을 곱해 '2억 건'을 만드는 길은 상수 검사가 막는다
    f["numbers"][0]["inputs"] = {"a": {"kind": "셈", "of": ["운송 적자", "연료비 상승"], "evidence": E1}}
    assert has(errors(issue, evs), "facts.f1.text", "셈 입력에 곱하거나 나눈 수")


def test_allegation_needs_court_or_disposition(desk):
    """sol-7: 의혹은 (가)여도 공식 통계·일반 보고서로는 판정하지 않는다(확정 판결·처분만)."""
    issue, _ = load(I1)
    eid = add_official(I1, "한빛통계원은 시 회계 담당자의 공금 사용이 규정을 넘었다고 집계했다.",
                       doc_of("한빛통계원", kind="공식 통계"))
    evs = model.load_evidences(I1)
    c = new_claim(I1, issue, gist="시 회계 담당자가 공금을 규정 밖으로 썼다.", subject="한빛시 회계 담당자의 공금 사용",
                  scope="한빛시 회계", allegation=True, target_kind="공인의 공적 활동")
    c["evidence"] = [link(eid, "지지", "가", c)]
    assert has(errors(issue, evs), f"claims.{c['id']}.verdict", rules.MSG_ALLEGATION)
    evs[eid]["doc"]["doc_kind"] = "처분"
    assert not has(errors(issue, evs), f"claims.{c['id']}.verdict", rules.MSG_ALLEGATION)


def test_later_objection_same_hash_blocks(desk):
    """sol-9: 같은 내용에 뒤늦은 반려·지적이 있으면 앞선 통과 두 줄로 검토 완료가 되지 않는다."""
    ready(I1)
    assert revisions.review_state(*load(I1)) == "검토 완료"
    add_review(I1, "해석 점검", "가상 모델 G", "openai", "반려", findings=[{"field": "claims.c1", "note": "핵심 오류"}])
    assert revisions.review_state(*load(I1)) == "검토 대기"


def test_capture_rejects_path_ids(desk):
    """sol-13: 이슈·근거 번호 자리에 경로를 주면 자료 루트 밖을 읽고 쓰지 않는다."""
    other = desk.parent / "other_desk" / "issues" / I1
    shutil.copytree(paths.issue_dir(I1), other)
    for args in ([str(other), E1], [I1, str(other / "evidence" / E1)], ["../" + I1, E1]):
        assert main(["capture", *args]) == 2
        assert main(["machine-verify", *args]) == 1


def test_export_rebuilds_when_manifest_moves(real, contact, tmp_path, monkeypatch):
    """sol-15: 만드는 동안 내림이 끝나면 그 내림을 반영해 다시 만든다(내린 판이 실린 묵은 출력을 올리지 않는다)."""
    ready(I1)
    assert approve(I1)["code"] == 0
    orig = export._build
    calls = []

    def build(*a, **kw):
        r = orig(*a, **kw)
        if not calls:
            assert revisions.withdraw(I1, None, "편집자", "다시 확인")["code"] == 0
        calls.append(1)
        return r
    monkeypatch.setattr(export, "_build", build)
    out = tmp_path / "pub"
    r = export.export("public", out)
    assert r["code"] == 0 and len(calls) == 2 and r["counts"]["issues"] == 0
    assert SLUG1 not in all_text(out)


# ── agy-15: 출력 자리 보호 층마다 그 층만 남긴 시험 ──────────────────
def test_out_equal_to_desk_root_rejected(tmp_path, monkeypatch):
    """자료 루트 자체는 이전 내보내기처럼 보여도(meta.json, json 만) 출력 자리로 받지 않는다 — 바꾸면 루트가 통째로 지워진다."""
    root = tmp_path / "desk_only_json"
    root.mkdir()
    (root / "meta.json").write_text(json.dumps({"schema": 1, "mode": "preview"}), encoding="utf-8")
    monkeypatch.setenv(paths.ENV, str(root))
    r = export.export("preview", root)
    assert r["code"] == 2 and (root / "meta.json").is_file()


def test_out_existing_without_meta_rejected(desk):
    """이전 내보내기 표시(meta.json)가 없는 폴더는 json 파일만 있어도 바꾸지 않는다."""
    other = desk / "json_only"
    other.mkdir()
    (other / "keep.json").write_text("{}", encoding="utf-8")
    assert export.export("preview", other)["code"] == 2 and (other / "keep.json").is_file()
