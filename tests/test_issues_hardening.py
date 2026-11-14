"""검토 지적(2026-11-14) 반영 시험 — 지적마다 그 구멍만 어긋난 최소 자료로 거부 문구까지 본다. 고치기 전 코드에서는 실패한다.
자료는 전부 지어낸 것이다(가상의 한빛시, 가상의 회사 누리전자). 네트워크를 쓰지 않는다."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import body as B  # noqa: E402
from ozl.issues import check, digest, export, ids, mask, model, numbers, paths, revisions, rules, style, units  # noqa: E402
from test_issues_check import (I1, I2, add_official, claim, desk, doc_of, errors, has, link, load,  # noqa: E402,F401
                               new_claim)
from test_issues_revisions import add_review, approve, edit, ready, real  # noqa: E402,F401

E1, E2, E3 = I1 + "-e1", I1 + "-e2", I1 + "-e3"
F1, F2, F3 = I2 + "-e1", I2 + "-e2", I2 + "-e3"


def _c3_confirmed(issue, evs, final=True):
    c = claim(issue, "c3")
    c.update(verdict="확인", counter_searched=True)
    evs[F3]["doc"]["court"]["final"] = final
    return c


# ── 근거 조건 (다) 에도 문서 쪽 방어 ──────────────────────────────────
def test_da_denial_is_not_opposition(desk):
    issue, evs = load(I2)
    evs[F2]["doc"]["admission"] = {"kind": "부인", "scope": "회수 대상 제품의 교환 비용 추산", "against_interest": False}
    c = claim(issue, "c2")
    c.update(verdict="사실과 다름")
    c["evidence"][0].update(stance="반대", basis="다", refers_to_original=True)
    issue["so_far_refs"].append("c2")
    errs = errors(issue, evs)
    assert has(errs, "claims.c2.verdict", rules.MSG_DENIAL_ONLY), errs


def test_da_transcribed(desk):
    issue, evs = load(I2)
    c = _c3_confirmed(issue, evs)
    evs[F3]["doc"].update(transcribed=True, doc_stage="한쪽 주장을 옮긴 것")
    c["evidence"][0].update(basis="다", refers_to_original=True, passage_role="당사자 주장을 옮긴 것")
    assert has(errors(issue, evs), f"claims.c3.evidence.{F3}", rules.MSG_TRANSCRIBED)


def test_da_unfinal_ruling(desk):
    issue, evs = load(I2)
    c = _c3_confirmed(issue, evs, final=False)
    c["evidence"][0].update(basis="다", refers_to_original=True)
    errs = errors(issue, evs)
    assert has(errs, f"claims.c3.evidence.{F3}", rules.MSG_UNFINAL) and has(errs, "claims.c3.verdict", rules.MSG_NO_SUPPORT)


def test_da_investigation_procedure(desk):
    issue, _ = load(I1)
    eid = add_official(I1, "한빛시 경찰청은 시 회계 담당자를 상대로 수사를 시작했다.", doc_of("한빛시 경찰청", kind="수사 절차"),
                       base="n/a", as_of="n/a", revision="n/a")
    evs = model.load_evidences(I1)
    c = new_claim(I1, issue, gist="시 회계 담당자가 회계 규정을 어겼다.", subject="한빛시 회계 담당자", scope="한빛시 회계")
    c["evidence"] = [link(eid, "지지", "다", c, passage_role="사실 기재", refers_to_original=True)]
    assert has(errors(issue, evs), f"claims.{c['id']}.evidence.{eid}", rules.MSG_PROCEDURE)
    c["about_procedure"] = True
    assert not has(errors(issue, evs), f"claims.{c['id']}.evidence.{eid}", rules.MSG_PROCEDURE)


def test_cause_doc_must_be_third_party(desk):
    issue, evs = load(I2)
    c = _c3_confirmed(issue, evs)
    evs[F2]["doc"]["doc_kind"] = "원인 발표"                                  # 당사자 회사가 스스로 낸 원인 발표
    evs[F2]["doc"].pop("admission")                                         # 인정 범위 검사와 섞이지 않게(원인 문서 규칙만 본다)
    c["evidence"] = [link(F2, "지지", "다", c, passage_role="사실 기재", refers_to_original=True, addresses_cause=True)]
    assert has(errors(issue, evs), "claims.c3.verdict", rules.MSG_CAUSE)


def _raw_evidence(iid):
    eid = ids.next_evidence_ids(iid)[0]
    ev = {"evidence_id": eid, "issue_id": iid, "kind": "언론 공개 원자료",
          "source": {"url": "https://news.example/data.csv", "publisher": "가나일보", "title": "공개 자료", "tier": "T3",
                     "accessed": "2099-01-02 09:00"},
          "raw": {"url": "https://news.example/data.csv", "fetched_at": "2099-01-02 09:00", "sha256": "b" * 64,
                  "located": "기본요금 400원 인상", "author_by": "agent-a", "recheck_by": "agent-b"},
          "doc": doc_of("가나일보", role="보도 매체", kind="원자료", stage="작성자 자신의 발표", authority=False), "revision": 1}
    model.save_evidence(ev)
    return eid


def test_raw_material_not_counted(desk):
    issue, _ = load(I1)
    eid = _raw_evidence(I1)
    evs = model.load_evidences(I1)
    c = claim(issue, "c4")
    c["evidence"] = [link(eid, "지지", "다", c, passage_role="사실 기재", refers_to_original=True)]
    errs = errors(issue, evs)
    assert has(errs, f"claims.c4.evidence.{eid}", rules.MSG_RAW) and has(errs, "claims.c4.verdict", rules.MSG_NO_SUPPORT)
    issue, _ = load(I1)
    f = issue["facts"][0]
    f["evidence"].append(eid)
    f["numbers"] = [{"value": "400원", "kind": "공식", "evidence": eid}]
    assert has(errors(issue, evs), "facts.f1.text", "원문에 같은 표기로 없다")


# ── 작은 주장의 종류 ──────────────────────────────────────────────────
def _split_causal(issue):
    c = claim(issue, "c3")
    c.update(verdict="일부 맞음", counter_searched=True)
    p1 = {"id": "p1", "gist": "배터리 결함이 화재를 일으켰다.", "core": True, "verdict": "확인", "kind": "사실",
          "evidence": [link(F1, "지지", "가", c)]}
    p2 = {"id": "p2", "gist": "화재가 여러 번 났다.", "core": False, "verdict": "확인 못 함", "unverified_reasons": ["핵심 근거를 구하지 못함"],
          "would_decide": "제품안전원의 원인 조사 결과"}
    c["parts"] = [p1, p2]
    c["evidence"] = []
    return p1


def test_part_cannot_escape_causal_kind(desk):
    issue, evs = load(I2)
    _split_causal(issue)
    assert has(errors(issue, evs), "claims.c3.parts.p1.kind", rules.MSG_PART_KIND_LOCK)
    issue, evs = load(I2)
    _split_causal(issue)["kind"] = "기타"
    errs = errors(issue, evs)
    assert has(errs, "claims.c3.parts.p1.kind", rules.MSG_PART_KIND) and has(errs, "claims.c3.parts.p1.kind", "허용 값")
    issue, evs = load(I2)                                                    # 핵심 작은 주장은 인과가 아니어도 종류를 못 바꾼다
    p1 = claim(issue, "c1")["parts"][0]
    p1["kind"] = "사실"
    assert has(errors(issue, evs), "claims.c1.parts.p1.kind", rules.MSG_PART_KIND_LOCK)


# ── 숫자 ──────────────────────────────────────────────────────────────
def _fact_number(issue, text, n):
    f = issue["facts"][0]
    f["text"], f["numbers"] = text, [n]


@pytest.mark.parametrize("n,msg", [
    ({"value": "700원", "kind": "계산", "inputs": {"a": "700원"}, "formula": "a", "unit": "원", "rounding": "그대로"}, "출처를 밝힌다"),
    ({"value": "700원", "kind": "계산", "inputs": {"a": {"value": "700원", "kind": "공식", "evidence": E1}}, "formula": "a", "unit": "원",
      "rounding": "그대로"}, "원문에 같은 표기로 없다"),
    ({"value": "400원", "kind": "계산", "inputs": {"a": {"value": "400원", "kind": "공식", "evidence": E1}}, "formula": "a", "unit": "원",
      "rounding": "그대로"}, "그대로 옮긴 것"),
    ({"value": "2개", "kind": "계산", "inputs": {"a": {"kind": "셈", "of": ["운송 적자", "지하철 적자"], "evidence": E1}}, "formula": "a",
      "unit": "개", "rounding": "그대로"}, "원문에 없다"),
])
def test_computed_inputs_need_source(desk, n, msg):
    issue, evs = load(I1)
    v = n["value"]
    _fact_number(issue, f"한빛시는 1월 2일 시내버스 요금을 {v} 올리는 안을 발표했다.", n)
    assert has(errors(issue, evs), "facts.f1.text", msg)


def test_refutes_must_point_to_false_claim_with_value(desk):
    issue, evs = load(I1)
    issue["numbers"]["so_far.2"][0]["refutes"] = "c4"                       # '확인' 주장은 반박 대상이 아니다
    assert has(errors(issue, evs), "so_far.2", "주장 속 값 '200억 원'")
    issue, evs = load(I1)
    issue["so_far"][2] = "떠도는 '적자 300억 원'은 시 결산과 다르다."
    issue["numbers"]["so_far.2"] = [{"value": "300억 원", "kind": "주장", "refutes": "c1"}]    # c1 에 없는 값
    assert has(errors(issue, evs), "so_far.2", "주장 속 값 '300억 원'")
    issue, evs = load(I1)
    _fact_number(issue, "한빛시는 적자가 200억 원이라는 말을 부인했다.", {"value": "200억 원", "kind": "주장", "refutes": "c1"})
    assert has(errors(issue, evs), "facts.f1.text", "확인된 사실 칸에 쓰지 않는다")


@pytest.mark.parametrize("phrase", ["이백억 원", "삼십 퍼센트", "수천억 원", "백만 명", "열두 명"])
def test_korean_numerals_rejected(desk, phrase):
    issue, evs = load(I1)
    issue["why_matters"] = f"하루 버스 이용자 {phrase}에게 영향이 있다."
    assert has(errors(issue, evs), "why_matters", f"한글로 쓴 수량 '{phrase}'")


# ── 제목의 의혹 ───────────────────────────────────────────────────────
@pytest.mark.parametrize("title", ["누리전자가 결함을 알고도 한 달 넘게", "보조 배터리 결함 은폐", "누리전자 임원 부정행위",
                                   "회수 자료 조작", "누리전자 대표 음주운전", "누리전자 채용 시험 부정행위"])
def test_allegation_title(desk, title):
    issue, evs = load(I2)
    issue["titles"]["candidates"][0]["text"] = issue["titles"]["chosen"] = title
    assert has(errors(issue, evs), "titles.chosen", style.MSG_CRIME)


def test_allegation_basis_claim(desk):
    issue, evs = load(I2)
    issue["titles"]["basis_claims"] = ["c4"]
    assert has(errors(issue, evs), "titles.basis_claims", "의혹 주장(c4)에 제목을 기대지 않는다")


def test_title_refs_must_be_public(desk):
    issue, evs = load(I1)
    claim(issue, "c2")["publish"] = "보류"
    errs = errors(issue, evs)
    assert has(errs, "titles.basis_claims", rules.MSG_REF_HIDDEN.format("c2")) and has(errs, "so_far_refs", rules.MSG_REF_HIDDEN.format("c2"))


def test_numeric_claim_period_unit_na(desk):
    issue, evs = load(I1)
    c = claim(issue, "c4")
    for d in (c, c["evidence"][0]):
        d.update(period="해당 없음", unit="해당 없음")
    errs = errors(issue, evs)
    assert has(errs, "claims.c4.period", rules.MSG_NUM_NA.format("기간")) and has(errs, "claims.c4.unit", rules.MSG_NUM_NA.format("단위"))


# ── 본문에 실리는 칸은 모두 검사를 받는다 ─────────────────────────────
def _sc(issue, **kw):
    issue["spillover"]["similar_cases"] = [dict({"text": "이웃 도시도 요금을 올렸다.", "url": "https://city.example/a"}, **kw)]


def _vh(issue, **kw):
    claim(issue, "c1")["verdict_history"] = [dict({"rev": 1, "at": "2099-01-02", "from": "확인 못 함", "to": "사실과 다름",
                                                   "why": "결산서를 찾았다."}, **kw)]


@pytest.mark.parametrize("fn,path,msg", [
    (lambda i: _sc(i, text="이웃 도시도 요금을 올렸다 😀"), "spillover.similar_cases.0.text", "이모지"),
    (lambda i: _sc(i, text="이웃 도시는 300억 원 적자를 냈다."), "spillover.similar_cases.0.text", "종류(공식, 주장, 계산)를 적지 않았다"),
    (lambda i: _sc(i, note="덧붙인 말"), "spillover.similar_cases.0", "{text, url}"),
    (lambda i: i["stances"][0].update(who="한빛시 😀"), "stances.s1.who", "이모지"),
    (lambda i: _vh(i, why="결산서를 찾았다 😀"), "claims.c1.verdict_history.0.why", "이모지"),
    (lambda i: _vh(i, why="AI 분석 결과 500억 원 적자"), "claims.c1.verdict_history.0.why", "종류(공식, 주장, 계산)"),
    (lambda i: _vh(i, note="일반인 이름"), "claims.c1.verdict_history", "{rev, at, from, to, why}"),
    (lambda i: claim(i, "c1").update(basis_label="AI 분석"), "claims.c1.basis_label", "basis_label"),
    (lambda i: i["keywords"].append("횡령"), "keywords.3", style.MSG_CRIME),
])
def test_body_fields_are_checked(desk, fn, path, msg):
    issue, evs = load(I1)
    fn(issue)
    assert has(errors(issue, evs), path, msg)


def test_reader_items_cover_body_text(desk):
    """본문에 실리는 글 칸(입장 주체, 비슷한 사례, 판정 이력, 근거 표시 덧말)이 reader_items 에 다 있다."""
    issue, _ = load(I1)
    _sc(issue)
    _vh(issue)
    claim(issue, "c1")["basis_label"] = rules.DISCLOSURE_LABEL
    got = {p for p, *_ in model.reader_items(issue)}
    for p in ("spillover.similar_cases.0.text", "stances.s1.who", "claims.c1.verdict_history.0.why", "claims.c1.basis_label"):
        assert p in got


# ── 선거 가림 ─────────────────────────────────────────────────────────
def _elect(issue, masked=()):
    issue["sensitive"] = ["선거"]
    issue["election"] = {"kind": "가상 시장 선거", "date": "2099-04-10", "poll_close": "18:00", "restrict_from": "2099-04-04",
                         "schedule_url": "https://election.example/schedule"}
    for lst in model.ITEM_LISTS:
        for it in issue.get(lst) or []:
            it["election_mask"] = it.get("id") in masked


def test_poll_words_in_parts_and_corrections(desk):
    issue, evs = load(I1)
    _elect(issue)
    assert errors(issue, evs) == []
    claim(issue, "c5")["parts"][0]["gist"] = "후보 가 지지율이 앞서고 있다는 주장"
    assert has(errors(issue, evs), "claims.c5.election_mask", style.MSG_POLL)
    issue, evs = load(I1)
    _elect(issue)
    issue["corrections"] = [{"rev": 1, "at": "2099-01-03", "kind": "정정", "before": "여론조사에서 갑 후보가 앞선다고 적었다",
                             "after": "문장을 고쳤다", "why": "표기 오류"}]
    assert has(errors(issue, evs), "corrections.0.before", style.MSG_POLL)
    issue["corrections"] = []
    _sc(issue, text="이웃 도시 선거에서 지지율 격차가 컸다.")
    assert has(errors(issue, evs), "spillover.similar_cases.0.text", style.MSG_POLL)


def _elect_body(masked=("c1", "f1", "f3")):   # f3 = c1 을 받치는 사실(118억 원) — 함께 가린다
    issue, evs = load(I1)
    _elect(issue, masked)
    f1 = issue["facts"][0]
    issue["numbers"]["facts.f1.text"] = f1.pop("numbers")             # 항목에 numbers 칸이 없으면 최상위 지도를 쓴다
    issue["corrections"] = [{"rev": 1, "at": "2099-01-03", "kind": "정정", "before": "갑 후보 지지율 우세 문장", "after": "고쳤다", "why": "판세"}]
    issue["spillover"]["similar_cases"] = [{"text": "이웃 도시 선거 여론조사 격차", "url": "https://city.example/a"}]
    return B.issue_body(issue, evs)


def test_mask_strips_numbers_verdicts_sources(desk):
    body = _elect_body()
    assert body["numbers"]["facts.f1.text"] and any(s["id"] == E2 for s in body["sources"])
    out = mask.apply(body, "2099-04-05T10:00:00+09:00")
    assert "facts.f1.text" not in out["numbers"]
    f1 = next(f for f in out["facts"] if f["id"] == "f1")
    assert f1["text"] == mask.MASKED_TEXT and "sources" not in f1
    flat = json.dumps(out, ensure_ascii=False)
    assert "한빛시 버스 운송 적자가 한 해 200억 원" not in flat and "118억" not in flat     # c1 의 요지가 남지 않는다
    assert E2 in {x["id"] for x in out["sources"]}                         # 제목 숫자의 계산 입력이 기대는 근거는 남는다
    out3 = mask.apply(_elect_body(masked=("c5", "f4")), "2099-04-05T10:00:00+09:00")   # f4 = c5 의 작은 주장을 받치는 사실(e3)
    assert E3 in {x["id"] for x in _elect_body(masked=("c5", "f4"))["sources"]}
    assert E3 not in {x["id"] for x in out3["sources"]}                    # 가린 주장만 인용한 근거는 출처 목록에서 빠진다
    assert out["verdicts"]["masked_claims"] == 1 and out["verdicts"]["summary"]["사실과 다름"] == 1
    assert out["corrections"][0]["before"] == mask.MASKED_TEXT and out["corrections_top"][0]["after"] == mask.MASKED_TEXT
    assert out["spillover"]["similar_cases"][0]["text"] == mask.MASKED_TEXT


def test_mask_window_boundaries(desk):
    body = _elect_body()
    assert "masked" in mask.apply(body, "2099-03-01T10:00:00+09:00")       # 기간 전에 내보낸 정적 출력도 가린다
    assert "masked" in mask.apply(body, "2099-04-10T18:00:00+09:00")       # 마감 시각까지
    assert "masked" not in mask.apply(body, "2099-04-10T18:01:00+09:00")
    b2 = dict(body, election={"kind": "가상", "date": "날짜 모름"})
    assert "masked" in mask.apply(b2, "2099-05-01T10:00:00+09:00")          # 기간을 읽지 못하면 가린다
    with pytest.raises(ValueError):
        mask.apply(body, "2099/04/05 10:00")


@pytest.mark.parametrize("now", ["2099-04-05 10:00 KST", "2099/04/05 10:00", "어제"])
def test_export_bad_now(desk, tmp_path, now):
    r = export.export("preview", tmp_path / "pv", now=now)
    assert r["code"] == 2 and "--now" in r["msgs"][0] and not (tmp_path / "pv").exists()


def test_export_out_guard(desk, tmp_path):
    before = sorted(str(p) for p in desk.rglob("*"))
    r = export.export("preview", desk)
    assert r["code"] == 2 and sorted(str(p) for p in desk.rglob("*")) == before
    assert export.export("preview", desk.parent)["code"] == 2
    other = desk / "notes"
    other.mkdir()
    (other / "keep.txt").write_text("지우면 안 되는 파일", encoding="utf-8")
    assert export.export("preview", other)["code"] == 2 and (other / "keep.txt").is_file()
    assert export.export("preview", desk / "pv")["code"] == 0 and export.export("preview", desk / "pv")["code"] == 0


# ── 화제 목록 ─────────────────────────────────────────────────────────
def _day(**kw):
    d = {"date": "2099-01-03", "revision": 1, "made_at": "2099-01-03 07:00",
         "line": {"updated_at": "2099-01-03 07:00", "source_kinds_ok": ["공식 발표"], "source_kinds_failed": []},
         "new": [{"issue_id": I1, "status_line": "시가 인상안을 발표했다."}], "ongoing": [],
         "upcoming": [{"date": "2099-01-20", "what": "가상 시의회 본회의", "url": "https://council.example/plan"}],
         "pre": [{"keyword": "가상 축제 일정", "desc": "올해 일정이 바뀌었다는 말이 돈다.", "links": [], "flags": []}],
         "empty_note": {"new": "", "ongoing": ""}}
    d.update(kw)
    return d


@pytest.mark.parametrize("kw,where", [
    ({"new": [{"issue_id": I1, "status_line": "시 회계 횡령 소식"}]}, "new.0.status_line"),
    ({"new": [{"issue_id": I1, "status_line": "적자가 500억 원이다"}]}, "new.0.status_line"),
    ({"new": [{"issue_id": I1, "status_line": "여론조사 지지율 격차가 줄었다."}]}, "new.0.status_line"),
    ({"new": [{"keyword": "충격 소식 😀", "state": "정리 전"}]}, "new.0.keyword"),
    ({"upcoming": [{"date": "2099-01-20", "what": "구속 영장 심사 😀", "url": "https://court.example/a"}]}, "upcoming.0.what"),
    ({"pre": [{"keyword": "가상 소문", "desc": "이웃이 횡령했다는 소문 300억 원", "links": [], "flags": []}]}, "pre.0.desc"),
    ({"pre": [{"keyword": "가상 소문", "desc": "이백억 원이 오갔다는 말", "links": [], "flags": []}]}, "pre.0.desc"),
    ({"line": {"updated_at": "x", "source_kinds_ok": ["공식 발표 😀"], "source_kinds_failed": []}}, "line.source_kinds_ok.0"),
])
def test_day_texts_checked(kw, where):
    assert units.check_unit("day", _day())["errors"] == []
    errs = units.check_unit("day", _day(**kw))["errors"]
    assert any(e.startswith(where + ":") for e in errs), errs


# ── 검토 ──────────────────────────────────────────────────────────────
def test_review_needs_notes_file(desk):
    with pytest.raises(ValueError):
        revisions.add_review(I1, "문장 대조", "Claude Sonnet", "anthropic", "통과")
    with pytest.raises(ValueError):
        revisions.add_review(I1, "문장 대조", "Claude Sonnet", "anthropic", "통과", notes_path=str(paths.issue_file(I1)))
    ready(I1)
    assert revisions.review_state(*load(I1)) == "검토 완료"
    f = paths.issue_dir(I1) / model.load_issue(I1)["reviews"][1]["notes_path"]
    f.write_text("바꿔 쓴 원문", encoding="utf-8")                       # 원문을 바꾸면 그 검토 줄은 세지 않는다
    assert revisions.review_state(*load(I1)) == "검토 대기"


def test_review_family_and_hash(desk):
    add_review(I1, "문장 대조", "Claude Sonnet", "anthropic", "통과")
    add_review(I1, "해석 점검", "Claude Haiku", "anthropic", "통과")       # 해석 점검은 다른 계열이어야 한다
    assert revisions.review_state(*load(I1)) == "검토 대기"
    add_review(I1, "해석 점검", "가상 모델 G", "openai", "통과")
    assert revisions.review_state(*load(I1)) == "검토 완료"
    edit(I1, lambda i: claim(i, "c3").update(searched="시 교통 통계"))     # 검토 뒤 내용이 바뀌면 다시 대기
    assert revisions.review_state(*load(I1)) == "검토 대기"
    add_review(I1, "문장 대조", "Claude Sonnet", "anthropic", "통과")       # 문장 대조만 새로 하고 해석 점검은 옛 내용 그대로
    assert revisions.review_state(*load(I1)) == "검토 대기"


def test_followup_review_needs_snapshot_and_full_before(desk):
    h0 = ready(I2)
    edit(I2, lambda i: i["reviews"][0].update(findings=[{"field": "claims.c3.would_decide", "note": "범위"}]))
    edit(I2, lambda i: claim(i, "c3").update(would_decide="대법원의 확정 판결"))
    (revisions.snapshot_file(I2, h0)).unlink()                            # 이전 내용 사본이 없으면 이어받지 않는다
    add_review(I2, "수정 확인", "Claude Sonnet", "anthropic", "통과", before_hash=h0, addresses=["r1"])
    assert revisions.review_state(*load(I2)) == "검토 대기"


# ── 승인 문과 판 공개 판정의 층 ───────────────────────────────────────
@pytest.mark.parametrize("fn,msg", [
    (lambda i: i.update(reason=""), "reason"),
    (lambda i: i.update(publish={"state": "보류", "why": "검토 중"}), "publish.state"),
])
def test_approve_runs_checks(real, fn, msg):
    edit(I1, fn)
    ready(I1)
    r = approve(I1)
    assert r["code"] == 1 and msg in r["msg"]


def test_approve_needs_ready_state(real):
    ready(I1)
    edit(I1, lambda i: i.update(work_state="검토 대기"))
    r = approve(I1)
    assert r["code"] == 1 and "work_state" in r["msg"]


def test_same_rev_other_content(real):
    ready(I1)
    assert approve(I1)["code"] == 0
    edit(I1, lambda i: claim(i, "c3").update(searched="시 교통 통계"))
    ready(I1)
    r = approve(I1)
    assert r["code"] == 3 and "같은 판이 다른 내용" in r["msg"]


def _approved():
    ready(I1)
    assert approve(I1)["code"] == 0
    assert revisions.revision_publishable(I1, 1)[0]
    return revisions.rev_dir(I1, 1)


def _resync(d, fn):
    """고정 사본을 고친 뒤 발행 목록과 승인 기록의 해시까지 맞춘다 — 그 층 하나만 남게."""
    fn(d)
    fi, fe, appr = revisions.load_fixed(I1, 1)
    man = revisions.load_manifest()
    e = revisions.entry(man, "issue", I1, 1)
    e.update(content_hash=digest.content_hash(fi, fe), evidence_hash=digest.evidence_hash(fi, fe),
             body_hash=digest.body_hash(B.issue_body(fi, fe, rev_at=appr["approved_at"])))
    revisions.save_manifest(man)
    appr.update({k: e[k] for k in ("content_hash", "evidence_hash", "body_hash")})
    (d / "approval.json").write_text(json.dumps(appr, ensure_ascii=False), encoding="utf-8")


def test_publishable_layers(real):
    d = _approved()
    man = revisions.load_manifest()
    revisions.entry(man, "issue", I1, 1)["evidence_hash"] = "0" * 32
    assert revisions.revision_publishable(I1, 1, man) == (False, "고정 사본의 근거 해시가 발행 목록과 다르다")
    appr = json.loads((d / "approval.json").read_text(encoding="utf-8"))
    (d / "approval.json").write_text(json.dumps(dict(appr, request_id="다른 요청"), ensure_ascii=False), encoding="utf-8")
    assert revisions.revision_publishable(I1, 1)[1] == "승인 기록(approval.json)이 발행 목록과 다르다"
    (d / "approval.json").write_text(json.dumps(appr, ensure_ascii=False), encoding="utf-8")
    cap = d / "captures" / E1 / "source.html"
    cap.write_bytes(cap.read_bytes() + b" ")
    assert revisions.revision_publishable(I1, 1)[1].startswith("근거 사본이 바뀌면 무효")


def test_publishable_rechecks_fixed_copy(real):
    d = _approved()

    def blank_reason(d):
        i = model.load_yaml(d / "issue.yaml")
        i["reason"] = ""
        model.save_yaml(d / "issue.yaml", i)
    _resync(d, blank_reason)
    ok, why = revisions.revision_publishable(I1, 1)
    assert not ok and why.startswith("고정 사본이 검사를 통과하지 못한다")


def test_withdraw_all_then_reapprove(real):
    _approved()
    assert revisions.withdraw(I1, None, "편집자", "다시 확인")["code"] == 0
    assert not revisions.revision_publishable(I1, 1)[0]
    edit(I1, lambda i: i.update(revision=2, rev_line="찾아본 범위를 더 적었다."))
    ready(I1)
    assert approve(I1)["code"] == 0
    assert revisions.revision_publishable(I1, 2)[0] and not revisions.revision_publishable(I1, 1)[0]


# ── 화제 목록·복원판의 공개 판정 ─────────────────────────────────────
def test_unit_withdraw_and_fixed_copy(real):
    d = _day()
    model.save_yaml(units.unit_file("day", d["date"]), d)
    assert units.approve_unit("day", d["date"], 1, units.unit_hash("day", d), "편집자")["code"] == 0
    assert units.unit_publishable("day", d["date"])[0]
    f = units.rev_file("day", d["date"], 1)
    raw = f.read_text(encoding="utf-8")
    f.write_text(raw.replace("인상안을", "인상안 을"), encoding="utf-8")
    assert not units.unit_publishable("day", d["date"])[0]
    f.write_text(raw, encoding="utf-8")
    assert units.unit_publishable("day", d["date"])[0]
    assert revisions.withdraw(f"day:{d['date']}", None, "편집자", "내림")["code"] == 0
    assert not units.unit_publishable("day", d["date"])[0]


def test_restored_label_fixed(real):
    r = {"date": "2099-01-03", "revision": 1, "made_at": "x", "label": "오늘의 인기 문서", "source_url": "https://wiki.example/p",
         "items": [{"rank": 1, "article": "가상 도시", "views": 3}]}
    model.save_yaml(units.unit_file("restored", r["date"]), r)
    res = units.approve_unit("restored", r["date"], 1, units.unit_hash("restored", r), "편집자")
    assert res["code"] == 1 and "label" in res["msg"]


# ── 승인 지문의 민감도 ───────────────────────────────────────────────
@pytest.mark.parametrize("fn", [
    lambda e: e.update(observed=e["observed"] + " "),
    lambda e: e.update(observed=e["observed"].replace("400원", "500원")),
    lambda e: e["doc"].update(doc_stage="확정된 판단"),
    lambda e: e["doc"].update(admission={"kind": "인정", "scope": "시내버스 전체", "against_interest": True}),
    lambda e: e["doc"].update(speaker_role="제3기관"),
    lambda e: e["verification"]["capture"].update(sha256="c" * 64),
    lambda e: e["verification"]["recheck"].update(located="다른 대목"),
])
def test_content_hash_sensitive_to_evidence(desk, fn):
    issue, evs = load(I1)
    h = digest.content_hash(issue, evs)
    e = copy.deepcopy(evs[E1])
    fn(e)
    if e != evs[E1]:
        evs2 = dict(evs, **{E1: e})
        same_after_strip = digest._norm(e) == digest._norm(evs[E1])
        assert same_after_strip or digest.content_hash(issue, evs2) != h


def test_content_hash_missing_evidence_and_nfc(desk):
    import unicodedata
    issue, evs = load(I1)
    h = digest.content_hash(issue, evs)
    assert digest.content_hash(issue, {k: v for k, v in evs.items() if k != E2}) != h
    i2 = copy.deepcopy(issue)
    i2["what_new"] = unicodedata.normalize("NFD", i2["what_new"])
    assert digest.content_hash(i2, evs) == h


def test_content_hash_raw_located(desk):
    issue, _ = load(I1)
    eid = _raw_evidence(I1)
    evs = model.load_evidences(I1)
    issue["facts"][0]["evidence"].append(eid)
    h = digest.content_hash(issue, evs)
    evs[eid]["raw"]["located"] = "다른 줄"
    assert digest.content_hash(issue, evs) != h


# ── 공개 여부는 item_public 한 곳 ─────────────────────────────────────
@pytest.mark.parametrize("target", ["일반인", "공인의 사생활"])
def test_item_public_private_always_false(desk, target):
    issue, evs = load(I1)
    c = claim(issue, "c3")
    c.update(target_kind=target, publish="게시 가능")
    assert rules.item_public(issue, c) is False
    b = B.issue_body(issue, evs)
    assert c["gist"] not in json.dumps(b, ensure_ascii=False) and b["verdicts"]["hidden_claims"] == 1


def test_hidden_texts_include_parts(desk):
    issue, _ = load(I1)
    claim(issue, "c5")["publish"] = "보류"
    got = [t for w, t in B.hidden_texts(issue) if w == "claims.c5"]
    assert "연료비는 30% 올랐다." in got


# ── 번호 대장 ─────────────────────────────────────────────────────────
def test_ledger_lost_files_kept(desk):
    paths.ledger_file().unlink()
    assert ids.next_issue_ids("2099-01-01") == ["i20990101-03"]             # 폴더의 번호는 다시 주지 않는다
    with pytest.raises(ValueError):
        ids.next_evidence_ids(I1)                                           # 대장에 없는 이슈의 근거 번호는 주지 않는다
    issue, evs = load(I1)
    assert has(errors(issue, evs), "issue_id", "대장에 없는 번호다")


def test_ledger_numbers_from_files(desk):
    led = ids.load_ledger()
    led["evidence"][I1] = 1
    led["items"][I1]["c"] = 1
    paths.write_atomic(paths.ledger_file(), json.dumps(led, ensure_ascii=False))
    issue, evs = load(I1)
    errs = errors(issue, evs)
    assert has(errs, f"evidence.{E2}", "대장에 없는 번호다") and has(errs, "claims.c2", "대장에 없는 번호다")
    assert ids.next_evidence_ids(I1) == [I1 + "-e4"]                         # 파일에 있는 번호를 건너뛴다
    assert ids.next_item_ids(I1, "c") == ["c6"]


# ── 조합표 한 줄씩(그 줄만 어긋난 최소 자료) ──────────────────────────
def _ev(iid, eid, **kw):
    def f(issue, evs):
        evs[eid]["doc"].update(kw)
    return f


def _cl(cid, fn):
    def f(issue, evs):
        fn(claim(issue, cid))
    return f


def _lk(cid, **kw):
    return _cl(cid, lambda c: c["evidence"][0].update(kw))


def _add_counter(c):
    c["evidence"].append(dict(c["evidence"][0], stance="반대"))


def _fact_capture(issue, evs):
    gid = ids.next_item_ids(I2, "g")[0]
    issue["figures"].append({"id": gid, "kind": "공식 문서 캡처", "caption": "회수 공고", "alt": "회수 공고를 옮긴 그림", "evidence": I2 + "-e4",
                             "target_kind": "기관과 정책", "publish": "게시 가능"})


@pytest.mark.parametrize("iid,fn,path,msg", [
    (I1, _ev(I1, E2, doc_stage="작성자 자신의 발표"), f"claims.c1.evidence.{E2}", "확정된 판단이 아니다"),
    (I1, _ev(I1, E2, speaker_role="당사자"), f"claims.c1.evidence.{E2}", "권한 있는 제3기관의 문서가 아니다"),
    (I1, _ev(I1, E2, authority=False), f"claims.c1.evidence.{E2}", "권한 있는 제3기관의 문서가 아니다"),
    (I1, _lk("c1", passage_role="사실 기재"), f"claims.c1.evidence.{E2}", "작성자의 판단이 아니다"),
    (I1, _ev(I1, E2, doc_kind="수사 절차"), f"claims.c1.evidence.{E2}", rules.MSG_PROCEDURE),
    (I2, _ev(I2, F2, admission={"kind": "인정", "scope": "회수 대상 제품의 교환 비용 추산", "against_interest": False}),
     f"claims.c2.evidence.{F2}", "불리한 사실을 인정한 문서가 아니다"),
    (I2, _ev(I2, F2, speaker_role="제3기관"), f"claims.c2.evidence.{F2}", "당사자의 문서가 아니다"),
    (I1, _lk("c4", refers_to_original=False), f"claims.c4.evidence.{E1}", "가리키지 않는다"),
    (I1, _cl("c4", lambda c: c.update(counter_searched=False)), "claims.c4.counter_searched", rules.MSG_COUNTER),
    (I1, _cl("c4", _add_counter), "claims.c4.verdict", "반대 근거가 있으면 '확인'을 붙이지 않는다"),
    (I1, _cl("c4", lambda c: c.update(allegation=True)), "claims.c4.verdict", rules.MSG_ALLEGATION),
    (I1, _cl("c5", lambda c: c["parts"][1].update(verdict="확인", evidence=[dict(c["parts"][1]["evidence"][0], stance="지지")])),
     "claims.c5.parts", "하나 이상씩"),
    (I1, _cl("c5", lambda c: c["parts"][0]["evidence"][0].update(period="2099년 1월")), "claims.c5.parts.p1.verdict", "일부 기간"),
    (I1, _lk("c1", stance="중립"), f"claims.c1.evidence.{E2}", "연결의 stance 값"),
    (I2, _cl("c3", lambda c: c["evidence"][0].pop("addresses_cause")), f"claims.c3.evidence.{F3}", "addresses_cause(참·거짓)"),
    (I1, _cl("c5", lambda c: c["parts"][0].pop("core")), "claims.c5.parts.p1.core", "core: 참·거짓"),
    (I1, _cl("c5", lambda c: c["parts"][0].update(id="x1")), "claims.c5.parts", "p1 꼴이 아니다"),
    (I1, _cl("c5", lambda c: c["parts"].pop()), "claims.c5.parts", "둘 이상"),
    (I1, _cl("c5", lambda c: c["parts"][1].update(unit="원")), "claims.c5.parts.p2.verdict", "단위"),
    (I2, lambda i, e: i["event_check"].update(evidence=I2 + "-e4"), "event_check.evidence", "보도는 안 된다"),
    (I1, lambda i, e: i["titles"].update(chosen="후보에 없는 제목"), "titles.chosen", "후보 가운데 하나"),
    (I1, lambda i, e: i["so_far"].pop(), "so_far", "정확히 3개"),
    (I1, _cl("c3", lambda c: c.pop("party_position")), "claims.c3.party_position", "당사자 입장은"),
    (I1, lambda i, e: i.update(merged_into=I2), "merged_into", "합쳐진 이슈는 게시하지 않는다"),
    (I2, _fact_capture, "figures.g1.evidence", "공식 원문이나 기관 자료 근거에서만"),
])
def test_combination_rows(desk, iid, fn, path, msg):
    issue, evs = load(iid)
    fn(issue, evs)
    errs = errors(issue, evs)
    assert has(errs, path, msg), errs


def test_announce_exception_needs_recheck(desk):
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
    evs[eid]["verification"]["verified_at"] = ""                              # 원문 재검사를 통과하지 못하면 예외도 없다
    assert has(errors(issue, evs), f"claims.{c['id']}.verdict", rules.MSG_NO_OPPOSE)


def test_crime_title_exempt_needs_confirmed_ga(desk):
    issue, _ = load(I1)
    eid = add_official(I1, "한빛지방법원은 시 회계 담당자의 공금 횡령을 유죄로 확정했다.",
                       doc_of("한빛지방법원", kind="판결", court={"level": "대법원", "final": True}))
    evs = model.load_evidences(I1)
    c = new_claim(I1, issue, gist="시 회계 담당자의 공금 횡령이 확정됐다.", subject="한빛시 회계 담당자의 공금 횡령", scope="한빛시 회계",
                  allegation=True, target_kind="공인의 공적 활동")
    c["evidence"] = [link(eid, "지지", "가", c)]
    issue["titles"]["candidates"][0]["text"] = issue["titles"]["chosen"] = "버스 400원 인상, 시 회계 횡령 확정 판결도"
    issue["numbers"]["titles.candidates.0"] = issue["numbers"]["titles.candidates.0"][:1]   # 바꾼 제목에 없는 숫자 항목은 뺀다
    issue["titles"]["basis_claims"] = [c["id"]]
    assert errors(issue, evs) == []
    c["allegation"] = False                                                    # 의혹 표시가 없어도
    c["evidence"][0].update(basis="다", refers_to_original=True, passage_role="사실 기재")     # (가)가 아니면 예외가 없다
    errs = errors(issue, evs)
    assert not has(errs, f"claims.{c['id']}.verdict", "") and has(errs, "titles.chosen", style.MSG_CRIME)
