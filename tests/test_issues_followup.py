"""실제 이슈를 만들며 찾은 검사기의 빈틈과 오탐(private/plan/issues_followup_20261114_0545.md 1~9절) 회귀 시험.
자료는 전부 지어낸 것이다(가상의 한빛시, 가상의 누리전자). 네트워크를 쓰지 않는다."""
from __future__ import annotations

import os
import pathlib
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import body as B  # noqa: E402
from ozl.issues import check, digest, export, fields, mask, model, numbers, paths, revisions  # noqa: E402
from ozl.issues import reviews as RV  # noqa: E402
from ozl.issues.__main__ import main  # noqa: E402
from test_issues_check import I1, I2, desk, errors, has, load  # noqa: E402,F401
from test_issues_hardening import _elect  # noqa: E402
from test_issues_revisions import add_review, approve, ready  # noqa: E402

E1, E2, E3 = I1 + "-e1", I1 + "-e2", I1 + "-e3"


def warns(issue, evs):
    return check.check_issue(issue, evs, public=True)["warnings"]


def has_w(ws, path, msg) -> bool:
    return any(f" {path}: " in w and msg in w for w in ws)


# ── 1. 이름 속 숫자(identifiers) ──────────────────────────────────────
NAME_TEXT = "제2형 차량과 KTX-1 노선 이용자에게도 요금이 바뀐다."


def test_name_digits_are_quantities_without_identifiers(desk):
    issue, evs = load(I1)
    issue["why_matters"] = NAME_TEXT
    errs = errors(issue, evs)
    assert has(errs, "why_matters", "숫자 '2'의 종류") and has(errs, "why_matters", "숫자 '-1'의 종류"), errs


def test_identifiers_exempt_name_digits_and_notice(desk, capsys):
    issue, evs = load(I1)
    issue["why_matters"] = NAME_TEXT
    issue["identifiers"] = ["KTX-1", "제2형"]
    assert not [e for e in errors(issue, evs) if "why_matters" in e], errors(issue, evs)
    assert numbers.exempt_note(issue) == "수량으로 보지 않은 표기: KTX-1(1곳), 제2형(1곳)"
    model.save_issue(issue)
    main(["check", I1])
    out = capsys.readouterr().out
    assert "알림 i20990101-01: 수량으로 보지 않은 표기: KTX-1(1곳), 제2형(1곳)" in out
    assert out.strip().endswith("오류 0건, 경고 0건")       # 알림은 오류·경고 건수에 넣지 않는다
    main(["status", I1])
    assert "수량으로 보지 않은 표기: KTX-1(1곳)" in capsys.readouterr().out


def test_identifier_does_not_exempt_other_quantity(desk):
    issue, evs = load(I1)
    issue["why_matters"] = "KTX-1 노선 차량 12개가 대상이다."
    issue["identifiers"] = ["KTX-1"]
    assert has(errors(issue, evs), "why_matters", "숫자 '12'의 종류")


@pytest.mark.parametrize("bad", ["12개", "3개월", "49", "6병", "30만 원대", "30만", "요금 400원", "", 7])
def test_identifier_rejects_quantity_forms(desk, bad):
    issue, evs = load(I1)
    issue["identifiers"] = [bad]
    assert has(errors(issue, evs), "identifiers.0", ""), errors(issue, evs)


@pytest.mark.parametrize("good", ["KTX-1", "제2형", "COVID-19", "B-52", "G7"])
def test_identifier_accepts_names(desk, good):
    issue, evs = load(I1)
    issue["identifiers"] = [good]
    assert not [e for e in errors(issue, evs) if "identifiers" in e]


@pytest.mark.parametrize("text", ["시가 요금 인상에 조건을 붙였다.", "시장은 경건한 태도로 설명했다.", "공원에 꽃이 만개했다.",
                                  "시는 요금 원칙을 천명한 바 있다.", "시장이 입장을 천명했다."])
def test_korean_magnitude_words_not_quantity(desk, text):
    issue, evs = load(I1)
    issue["why_matters"] = text
    assert not [e for e in errors(issue, evs) if "why_matters" in e], errors(issue, evs)


@pytest.mark.parametrize("text,shown", [("이용료는 만 원이다.", "만 원"), ("이용자는 천 명이다.", "천 명"), ("신고는 백 건이다.", "백 건")])
def test_korean_quantities_still_caught(text, shown):
    assert numbers.korean_qty(text) == [shown]


def test_hash_unchanged_by_empty_new_fields(desk):
    issue, evs = load(I1)
    issue.pop("identifiers", None)
    for c in issue["claims"]:
        c.pop("basis_facts", None)
        for p in c.get("parts") or []:
            p.pop("basis_facts", None)
    h = digest.content_hash(issue, evs)
    issue["identifiers"] = []
    issue["claims"][2]["basis_facts"] = []
    issue["claims"][4]["parts"][0]["basis_facts"] = []
    assert digest.content_hash(issue, evs) == h                         # 비어 있으면 지문에서 빠진다
    issue["identifiers"] = ["KTX-1"]
    assert digest.content_hash(issue, evs) != h                         # 적으면 지문에 든다
    issue["identifiers"] = []
    issue["claims"][2]["basis_facts"] = ["f1"]
    assert digest.content_hash(issue, evs) != h


# ── 9. 키워드의 이름 속 숫자 ──────────────────────────────────────────
def test_keyword_identifier_accepted_quantity_still_refused(desk):
    issue, evs = load(I1)
    issue["keywords"].append("주 4.5일제")
    assert has(errors(issue, evs), "keywords.3", check.MSG_KW_QTY)
    issue["identifiers"] = ["주 4.5일제"]
    assert not has(errors(issue, evs), "keywords.3", check.MSG_KW_QTY)
    issue["keywords"][3] = "버스 요금 400원"
    issue["identifiers"] = ["버스 요금 400원"]
    errs = errors(issue, evs)
    assert has(errs, "keywords.3", check.MSG_KW_QTY) and has(errs, "identifiers.0", "수 + 단위")


# ── 8. 달력 'M.D.(요일)' 과 시각 'H시 M분' ─────────────────────────────
def test_dot_date_and_clock_not_quantities(desk):
    issue, evs = load(I1)
    issue["why_matters"] = "시는 1.2.(토) 04시 15분에 새 요금을 알렸다."
    assert not [e for e in errors(issue, evs) if "why_matters" in e and "숫자" in e], errors(issue, evs)


def test_hours_duration_still_quantity(desk):
    issue, evs = load(I1)
    issue["why_matters"] = "시는 4시간 15분 동안 새 요금을 알렸다."
    assert has(errors(issue, evs), "why_matters", "숫자")


@pytest.mark.parametrize("text", ["시는 1월 2일부터 5일까지 접수한다.", "시는 11월 8일부터 12일까지 접수한다.",
                                  "시는 11월 8일~12일 신청을 받는다."])
def test_same_month_date_range_not_quantities(desk, text):
    issue, evs = load(I1)
    issue["why_matters"] = text
    assert not [e for e in errors(issue, evs) if "why_matters" in e and "숫자" in e], errors(issue, evs)


@pytest.mark.parametrize("text", ["시는 11월 8일부터 12일까지 3일간 접수한다.",     # 범위 뒤의 기간은 그대로 수량이다
                                  "시는 11월 12일부터 8일까지 접수한다.",          # 뒤 날짜가 앞보다 작으면 범위가 아니다
                                  "시는 11월 8일~12일간 신청을 받는다.",           # '~D일간' 은 기간이다
                                  "시는 11월 8일부터 12일 동안 신청을 받는다."])   # '까지' 가 없으면 범위로 보지 않는다
def test_date_range_mask_stays_narrow(desk, text):
    issue, evs = load(I1)
    issue["why_matters"] = text
    assert has(errors(issue, evs), "why_matters", "숫자"), errors(issue, evs)


# ── 2. 정해지지 않은 칸 ───────────────────────────────────────────────
@pytest.mark.parametrize("where", ["fact", "claim", "link", "part", "party", "flow", "stance", "question", "title", "spread_link",
                                   "publish", "production"])
def test_unknown_keys_rejected(desk, where):
    issue, evs = load(I1)
    c = issue["claims"][0]
    target, path = {
        "fact": (issue["facts"][0], "facts.f1"), "claim": (c, "claims.c1"), "link": (c["evidence"][0], f"claims.c1.evidence.{E2}"),
        "part": (issue["claims"][4]["parts"][0], "claims.c5.parts.p1"), "party": (c["party_position"], "claims.c1.party_position"),
        "flow": (issue["flow"][0], "flow.w1"), "stance": (issue["stances"][0], "stances.s1"),
        "question": (issue["open_questions"][0], "open_questions.q1"), "title": (issue["titles"]["candidates"][0], "titles.candidates.0"),
        "spread_link": (None, "claims.c1.spread.links.0"), "publish": (issue["publish"], "publish"),
        "production": (issue["production"], "production"),
    }[where]
    if where == "spread_link":
        c["spread"]["links"] = [{"outlet": "가상일보", "url": "https://news.example/a", "시의회가 받았다.": None}]
    else:
        target["시의회가 받았다."] = None
    assert has(errors(issue, evs), path, "정해지지 않은 칸 '시의회가 받았다.'"), errors(issue, evs)


def test_inline_dict_split_at_comma_is_caught(desk):
    issue, evs = load(I1)
    w = yaml.safe_load("{id: w1, event_date: '2099-01-02', what: 시가 인상안을 내놓았고, 시의회가 받았다., kind: 계기}")
    issue["flow"][0].update(w)
    errs = errors(issue, evs)
    assert has(errs, "flow.w1", "정해지지 않은 칸 '시의회가 받았다.'")
    assert has(errs, "flow.w1.what", fields.MSG_SENTENCE)


@pytest.mark.parametrize("path", ["source", "doc", "checks", "verification.recheck"])
def test_unknown_evidence_keys_rejected(desk, path):
    issue, evs = load(I1)
    d = evs[E1]
    for k in path.split("."):
        d = d[k]
    d["낯선 칸"] = None
    assert has(errors(issue, evs), f"evidence.{E1}.{path}", "정해지지 않은 칸 '낯선 칸'"), errors(issue, evs)


@pytest.mark.parametrize("path,setter", [
    ("what_new", lambda i: i.update(what_new="시가 1월 2일 요금 400원 인상안을 발표했고")),
    ("so_far.0", lambda i: i["so_far"].__setitem__(0, "시는 인상 근거로 운송 적자와 연료비를 들었고")),
    ("facts.f1.text", lambda i: i["facts"][0].update(text="한빛시는 1월 2일 시내버스 요금을 400원 올리는 안을 발표했고")),
    ("stances.s1.summary", lambda i: i["stances"][0].update(summary="운송 적자와 연료비를 인상 근거로 들었고")),
])
def test_sentence_fields_must_end(desk, path, setter):
    issue, evs = load(I1)
    setter(issue)
    assert has(errors(issue, evs), path, fields.MSG_SENTENCE), errors(issue, evs)


def test_gist_title_question_not_sentence_checked(desk):
    issue, evs = load(I1)
    issue["claims"][0]["gist"] = "한빛시 버스 운송 적자가 한 해 200억 원"
    assert not [e for e in errors(issue, evs) if fields.MSG_SENTENCE in e]   # 남은 질문, 제목은 원래 마침표가 없다


# ── 3. 글 속의 날짜 ───────────────────────────────────────────────────
def test_item_date_must_be_supported(desk):
    issue, evs = load(I1)
    assert not [e for e in errors(issue, evs) if "날짜" in e]
    issue["facts"][0]["text"] = "한빛시는 1월 3일 시내버스 요금을 400원 올리는 안을 발표했다."
    assert has(errors(issue, evs), "facts.f1.text", "날짜 '1월 3일'")


def test_top_date_must_be_supported(desk):
    issue, evs = load(I1)
    issue["what_new"] = "시가 1월 5일 요금 400원 인상안을 발표했다."
    assert has(errors(issue, evs), "what_new", "날짜 '1월 5일'이 흐름, 주장의 기간, 근거 대목 어디에도 없다")
    issue["flow"][0]["report_date"] = "2099-01-05"
    assert not has(errors(issue, evs), "what_new", "날짜")


def test_english_passage_date_supports(desk):
    issue, evs = load(I1)
    issue["facts"][0]["text"] = "한빛시는 1월 3일 시내버스 요금을 400원 올리는 안을 발표했다."
    evs[E1]["observed"] += " Effective January 3, 2099."
    assert not has(errors(issue, evs), "facts.f1.text", "날짜")


def test_flow_date_supports_flow_text(desk):
    issue, evs = load(I1)
    issue["flow"][0]["what"] = "시가 2099년 1월 2일 인상안을 발표했다."
    assert not has(errors(issue, evs), "flow.w1.what", "날짜")
    issue["flow"][0]["what"] = "시가 1월 4일 인상안을 발표했다."
    assert has(errors(issue, evs), "flow.w1.what", "날짜 '1월 4일'")


# ── 4. 흐름의 '시행' ──────────────────────────────────────────────────
def test_flow_kind_enforced_and_past_plan_warned(desk):
    issue, evs = load(I1)
    issue["flow"][0]["kind"] = "시행"
    assert not has(errors(issue, evs), "flow.w1.kind", "")
    issue["flow"][0].update(kind="예정", event_date="2098-12-31")
    assert has_w(warns(issue, evs), "flow.w1.kind", "'예정'인데")
    issue["flow"][0]["event_date"] = "2099-01-05"
    assert not has_w(warns(issue, evs), "flow.w1.kind", "'예정'")


# ── 5. 검토 기록 ──────────────────────────────────────────────────────
def test_same_model_other_version_is_not_a_review(desk):
    issue = model.load_issue(I1)
    issue["production"]["drafted_by"] = "Claude Opus"
    model.save_issue(issue)
    ready(I1, reviewer="Claude Opus 5.5")                               # 판 번호만 다른 같은 모델의 문장 대조
    assert revisions.review_state(*load(I1)) == "검토 대기"
    assert RV.missing_reviews(*load(I1)) == [RV.NEED_CMP]
    add_review(I1, "문장 대조", "Claude Sonnet 5.5", "anthropic", "통과")
    assert revisions.review_state(*load(I1)) == "검토 완료" and RV.missing_reviews(*load(I1)) == []


def test_objection_not_passed_by_other_model(desk):
    ready(I1)
    add_review(I1, "해석 점검", "가상 모델 G", "openai", "지적", findings=[{"field": "claims.c1", "note": "표현 확인"}])
    add_review(I1, "해석 점검", "가상 모델 H", "google", "통과")              # 다른 모델의 통과로 넘어가지 않는다
    assert revisions.review_state(*load(I1)) == "검토 대기"
    assert RV.missing_reviews(*load(I1)) == [RV.NEED_OBJ]


def test_review_add_with_content_hash_needs_snapshot(desk, capsys):
    h0 = digest.content_hash(*load(I1))
    d = revisions.notes_dir(I1)
    d.mkdir(parents=True, exist_ok=True)
    note = d / "late.md"
    note.write_text("해석 점검 — 시험용으로 지어낸 검토 원문\n", encoding="utf-8")
    args = ["review", "add", I1, "--kind", "해석 점검", "--by-model", "가상 모델 G", "--family", "openai", "--result", "통과",
            "--notes-path", str(note), "--content-hash", h0]
    assert main(args) == 1 and RV.MSG_SNAP_MISSING in capsys.readouterr().err   # 사본 없이 준 해시는 받지 않는다
    assert main(["snapshot", I1]) == 0 and h0 in capsys.readouterr().out
    issue = model.load_issue(I1)                                        # 답을 기다리는 동안 기록이 고쳐졌다
    issue["why_matters"] = "하루 버스 이용자 모두의 요금이 바뀐다."
    model.save_issue(issue)
    assert digest.content_hash(*load(I1)) != h0
    assert main(args) == 0
    row = model.load_issue(I1)["reviews"][-1]
    assert row["content_hash"] == h0                                    # 검토가 본 내용에 묶였다
    assert main(args[:-2] + ["--content-hash", "0" * 32]) == 1           # 사본이 없는 해시
    (RV.snapshot_file(I1, h0)).write_text("issue: {}\nevidence: {}\n", encoding="utf-8")
    assert main(args) == 1                                              # 바꿔치기한 사본은 받지 않는다


def test_missing_reviews_matches_ops(desk):
    from ozl.ops import approvals
    issue, evs = load(I1)
    assert approvals.missing_reviews(issue, evs) == RV.missing_reviews(issue, evs) == [RV.NEED_CMP, RV.NEED_ITP]
    assert approvals.NEED_CMP == RV.NEED_CMP and approvals.NEED_ITP == RV.NEED_ITP


def test_recheck_by_links_to_sentence_reviewer(desk):
    issue, evs = load(I1)
    add_review(I1, "문장 대조", "Claude Sonnet", "anthropic", "통과")
    issue, evs = load(I1)
    for ev in evs.values():
        if (ev.get("verification") or {}).get("recheck"):
            ev["verification"]["recheck"]["by"] = "reviewer-claude-sonnet-5.5-r2"
    assert not [w for w in warns(issue, evs) if "recheck.by" in w]
    evs[E1]["verification"]["recheck"]["by"] = "writer-claude-opus-r2"
    assert has_w(warns(issue, evs), f"evidence.{E1}.verification.recheck.by", "이어지지 않는다")


# ── 6. 화면 문구 ──────────────────────────────────────────────────────
def test_no_position_wording(desk):
    b = B.issue_body(*load(I1))
    c2 = next(c for g in b["verdicts"]["groups"] for c in g["claims"] if c["id"] == "c2")
    assert c2["party_position"] == "당사자의 직접 발표를 찾지 못함(2099-01-02 11:00 확인)"
    assert "공개된 입장 없음" not in str(b)


# ── 7. 판정을 받치는 사실(basis_facts → basis) ─────────────────────────
def _claim(b, cid):
    return next(c for g in b["verdicts"]["groups"] for c in g["claims"] if c["id"] == cid)


def test_basis_exported(desk):
    b = B.issue_body(*load(I1))
    assert _claim(b, "c1")["basis"] == ["2098년 한빛시 시내버스 운송 적자는 118억 원으로 확정됐다."]
    p2 = next(p for p in _claim(b, "c5")["parts"] if p["id"] == "p2")
    assert p2["basis"] == ["2098년 한빛시 경유 평균 가격은 전년보다 12% 올랐다."]
    assert _claim(b, "c3")["basis"] == []


@pytest.mark.parametrize("change,msg", [
    (lambda i: i["claims"][0].update(basis_facts=["f9"]), "없는 사실을 가리킨다: f9"),
    (lambda i: i["claims"][0].update(basis_facts="f3"), "basis_facts 는 확인된 사실 번호 목록이다"),
    (lambda i: i["claims"][0].update(basis_facts=["f4"]), "근거가 이 주장의 근거 연결이나 당사자 입장의 근거에 없다"),
    (lambda i: i["facts"][2].update(publish="보류"), "판정을 받치는 사실(f3)이 게시 가능이 아니다"),
])
def test_basis_facts_rejected(desk, change, msg):
    issue, evs = load(I1)
    change(issue)
    assert has(errors(issue, evs), "claims.c1.basis_facts", msg), errors(issue, evs)


def test_basis_party_position_evidence_ok_and_missing_warned(desk):
    issue, evs = load(I1)
    issue["claims"][0]["basis_facts"] = ["f1"]                          # c1 의 당사자 입장 근거(e1)
    assert not has(errors(issue, evs), "claims.c1.basis_facts", "")
    del issue["claims"][0]["basis_facts"]
    assert has_w(warns(issue, evs), "claims.c1.basis_facts", "basis_facts")
    issue["claims"][4]["parts"][1].pop("basis_facts")
    assert has_w(warns(issue, evs), "claims.c5.parts.p2.basis_facts", "basis_facts")


def test_basis_missing_not_warned_for_hidden_claim(desk):
    """보류나 공개 제외로 숨긴 주장은 화면에 나가지 않는다. 판정을 받치는 사실이 비어도 알리지 않는다."""
    issue, evs = load(I1)
    del issue["claims"][0]["basis_facts"]
    issue["claims"][0]["publish"] = "보류"
    assert not has_w(warns(issue, evs), "claims.c1.basis_facts", "basis_facts")


def test_basis_masked_with_fact(desk):
    issue, evs = load(I1)
    _elect(issue, ("f3",))
    out = mask.apply(B.issue_body(issue, evs), "2099-04-05T10:00:00+09:00")
    assert _claim(out, "c1")["basis"] == []
    assert "118억" not in str(out)


# ── 9. 확인한 범위(scope) ─────────────────────────────────────────────
def test_scope_exported_and_warned(desk):
    issue, evs = load(I1)
    b = B.issue_body(issue, evs)
    assert _claim(b, "c4")["scope"] == "시내버스 기본요금"
    p1 = next(p for p in _claim(b, "c5")["parts"] if p["id"] == "p1")
    assert p1["scope"] == "시 보도자료"
    issue["claims"][3]["scope"] = "해당 없음"
    assert has_w(warns(issue, evs), "claims.c4.scope", "확인한 범위")


def test_scope_text_is_reader_text(desk):
    issue, evs = load(I1)
    issue["claims"][3]["scope"] = "시내버스 기본요금, 노선 12개"
    assert has(errors(issue, evs), "claims.c4.scope", "숫자 '12'의 종류")


def test_export_version_bumped():
    assert B.EXPORT_VERSION == 3


# ── 9. 실제 자료 루트의 다른 이름, 실행기가 띄운 자식 ─────────────────────
def test_symlinked_issues_dir_is_alias(tmp_path, monkeypatch):
    real = tmp_path / "real"
    (real / "issues").mkdir(parents=True)
    monkeypatch.setattr(paths, "real_root", lambda: real)
    other = tmp_path / "other"
    other.mkdir()
    (other / "issues").symlink_to(real / "issues")
    monkeypatch.setenv(paths.ENV, str(other))
    assert not paths.is_real_root() and paths.is_alias_of_real_root()
    (real / "issues" / "manifest.json").write_text('{"schema": 1, "entries": [{"unit": "issue", "id": "i20990101-01", "rev": 1}], '
                                                   '"withdrawn": []}\n', encoding="utf-8")
    r = revisions.withdraw("i20990101-01", None, revisions.TEST_BY, "시험")
    assert r["code"] == 2 and "다른 이름" in r["msg"]
    assert "withdrawn\": []" in (real / "issues" / "manifest.json").read_text(encoding="utf-8")
    monkeypatch.setenv(export.CONTACT_ENV, "report@example.test")
    assert export.export("public", tmp_path / "out")["code"] == 2


def test_runner_child_refused(desk, monkeypatch, tmp_path):
    h = ready(I1)
    monkeypatch.setenv(paths.RUNNER_ENV, "1")
    r = revisions.approve(I1, 1, h, revisions.TEST_BY)
    assert r["code"] == 2 and r["msg"] == paths.MSG_RUNNER and not revisions.load_manifest()["entries"]
    assert main(["approve", I1, "--rev", "1", "--hash", h, "--by", revisions.TEST_BY]) == 2
    assert revisions.withdraw(I1, None, revisions.TEST_BY, "시험")["code"] == 2
    monkeypatch.setenv(export.CONTACT_ENV, "report@example.test")
    r = export.export("public", desk / "out")
    assert r["code"] == 2 and r["msgs"] == [paths.MSG_RUNNER]
    assert export.export("preview", desk / "prev")["code"] == 0          # 미리보기는 그대로
    monkeypatch.delenv(paths.RUNNER_ENV)
    assert approve(I1)["code"] == 0


def test_runner_env_zero_is_not_runner(monkeypatch):
    monkeypatch.setenv(paths.RUNNER_ENV, "0")
    assert not paths.in_runner()
    monkeypatch.delenv(paths.RUNNER_ENV)
    assert not paths.in_runner() and os.environ.get(paths.RUNNER_ENV) is None


# ── 범위 칸에 낱말 하나만(대상 이름) 있는 경우와, 일어난 날을 모르는 흐름 ─────────────────────
def test_scope_one_word_is_refused_for_public_claims(desk):
    issue, evs = load(I1)
    issue["claims"][3]["scope"] = "시내버스"
    assert has(errors(issue, evs), "claims.c4.scope", "낱말 하나만")
    issue["claims"][3]["publish"] = "보류"          # 숨긴 주장의 범위는 화면에 나가지 않는다
    assert not has(errors(issue, evs), "claims.c4.scope", "낱말 하나만")


def test_scope_short_phrase_is_kept(desk):
    issue, evs = load(I1)
    assert not has(errors(issue, evs), "claims.c4.scope", "낱말 하나만")      # '시내버스 기본요금'


def test_flow_event_date_may_be_blank_when_report_date_known(desk):
    issue, evs = load(I1)
    w = issue["flow"][0]
    w["report_date"] = w.get("report_date") or str(w["event_date"])
    w["event_date"] = None
    assert not has(errors(issue, evs), f"flow.{w['id']}.event_date", "event_date")
    assert B.issue_body(issue, evs)["flow"][0]["event_date"] == ""
    w["report_date"] = None
    assert has(errors(issue, evs), f"flow.{w['id']}.event_date", "보도된 날")


def test_flow_event_date_wrong_shape_is_still_refused(desk):
    issue, evs = load(I1)
    issue["flow"][0]["event_date"] = "2099년 1월"
    assert has(errors(issue, evs), f"flow.{issue['flow'][0]['id']}.event_date", "YYYY-MM-DD")
