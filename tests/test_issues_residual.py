"""검증자 재현으로 남은 구멍(astra-7·astra-8·agy-2·sol-6·sol-12)과 고치며 생긴 과잉 차단(키워드 수량, 같은 해시의 지적 해소) 시험.
자료는 전부 지어낸 것이다(가상의 한빛시, 가상의 갑 후보). 네트워크를 쓰지 않는다."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import body as B  # noqa: E402
from ozl.issues import check, mask, numbers, revisions, units  # noqa: E402
from test_issues_check import I1, desk, errors, has, load  # noqa: E402,F401
from test_issues_hardening import _day, _elect  # noqa: E402
from test_issues_revisions import add_review, ready  # noqa: E402

E1, E2 = I1 + "-e1", I1 + "-e2"
IN_WINDOW = "2099-04-05T10:00:00+09:00"
OFFICIAL_A = {"a": {"value": "400원", "kind": "공식", "evidence": E1}}
COUNT_2 = {"kind": "셈", "of": ["운송 적자", "연료비 상승"], "evidence": E1}
COUNT_1 = {"kind": "셈", "of": ["운송 적자"], "evidence": E1}


def _fact_number(value, formula, inputs, unit="원"):
    issue, evs = load(I1)
    f = issue["facts"][0]
    f["text"] = f"한빛시 요금 값은 {value}이다."
    f["numbers"] = [{"value": value, "kind": "계산", "unit": unit, "rounding": "그대로", "formula": formula, "inputs": inputs}]
    return issue, evs


# ── astra-7 · agy-2 · sol-6: 1 을 이어 붙이거나 셈 입력에 거듭제곱을 곱해 출처 없는 값을 만들지 못한다 ──
@pytest.mark.parametrize("value,formula,inputs,unit", [
    ("402원", "a + 1 + 1", OFFICIAL_A, "원"),
    ("800원", "(1+1)*a", OFFICIAL_A, "원"),
    ("1200원", "a*(1+1+1)", OFFICIAL_A, "원"),
    ("40원", "a/(1+1+1+1+1+1+1+1+1+1)", OFFICIAL_A, "원"),
    ("4001원", "a*10 + 1", OFFICIAL_A, "원"),
    ("401원", "a + 1", OFFICIAL_A, "원"),
    ("4000원", "a*(10*1)", OFFICIAL_A, "원"),
    ("-400원", "-a", OFFICIAL_A, "원"),
    ("-400원", "0 - a", OFFICIAL_A, "원"),
    ("2억 건", "a * 100000000", {"a": COUNT_2}, "건"),
    ("200%", "a * 100", {"a": COUNT_2}, "%"),
])
def test_formula_constant_bypass_rejected(desk, value, formula, inputs, unit):
    issue, evs = _fact_number(value, formula, inputs, unit)
    assert has(errors(issue, evs), "facts.f1.text", "계산 값"), errors(issue, evs)


@pytest.mark.parametrize("value,formula,inputs,unit", [
    ("4년", "결산연도 - 근거연도 + 1", {"결산연도": {"value": "2098년", "kind": "공식", "evidence": E2},
                                    "근거연도": {"value": "2095년", "kind": "공식", "evidence": E1}}, "년"),
    ("4원", "a / 100", OFFICIAL_A, "원"),
    ("50%", "a / b * 100", {"a": COUNT_1, "b": COUNT_2}, "%"),
])
def test_formula_legit_constants_pass(desk, value, formula, inputs, unit):
    issue, evs = _fact_number(value, formula, inputs, unit)
    issue["facts"][0]["evidence"] = [E1, E2]
    errs = [e for e in errors(issue, evs) if e[0] == "facts.f1.text" and "계산 값" in e[1]]
    assert errs == [], errs


# ── astra-8 · sol-6: 유니코드 빼기 기호의 부호 ──
@pytest.mark.parametrize("text,want", [("−2억 원", -2e8), ("－2억 원", -2e8), ("−3", -3.0), ("−1억 5천만 원", -1.5e8), ("‒7%", -7.0)])
def test_to_number_unicode_minus(text, want):
    assert numbers.to_number(text) == want


def test_computed_unicode_minus_sign(desk):
    issue, evs = _fact_number("−4억 원", "a * 1000000", OFFICIAL_A)
    assert has(errors(issue, evs), "facts.f1.text", "다시 계산한 값"), errors(issue, evs)
    issue, evs = _fact_number("4억 원", "a * 1000000", OFFICIAL_A)
    assert not has(errors(issue, evs), "facts.f1.text", "계산 값"), errors(issue, evs)


# ── sol-12: 가림 기간에 출처의 발행처·주소에 든 판세 낱말도 가린다 ──
def test_mask_source_publisher(desk):
    issue, evs = load(I1)
    _elect(issue)
    evs[E1]["source"]["publisher"] = "가상 지지율 연구소"
    body = B.issue_body(issue, evs)
    assert "지지율" in json.dumps(body, ensure_ascii=False)
    out = mask.apply(body, IN_WINDOW)
    assert "지지율" not in json.dumps(out, ensure_ascii=False)


# ── 과잉 차단: 숫자가 이름의 일부인 키워드는 받고, 수량은 계속 막는다 ──
NAME_KWS = ["5G 요금", "2차전지", "3기 신도시", "가상병19", "G7 회의", "4대강", "2099 시장 선거", "1인 가구", "VIRUS-19", "K2 전차"]
QTY_KWS = ["200억 원", "버스 요금 400원", "30% 인상", "12명", "400", "2배", "1위", "−3", "주 4.5일제", "400 원", "3,000",
           "요금 400", "2099년 400원", "이백억 원", "5천 명", "1.5", "40%p"]


@pytest.mark.parametrize("kw", NAME_KWS)
def test_keyword_name_with_digits_ok(desk, kw):
    issue, evs = load(I1)
    issue["keywords"].append(kw)
    assert not has(errors(issue, evs), "keywords.3", check.MSG_KW_QTY), errors(issue, evs)
    assert not units.check_unit("day", _day(new=[{"keyword": kw, "state": "정리 전"}]))["errors"]


@pytest.mark.parametrize("kw", QTY_KWS)
def test_keyword_quantity_still_rejected(desk, kw):
    issue, evs = load(I1)
    issue["keywords"].append(kw)
    assert has(errors(issue, evs), "keywords.3", "키워드"), errors(issue, evs)
    assert units.check_unit("day", _day(new=[{"keyword": kw, "state": "정리 전"}]))["errors"]


def test_status_line_still_no_numbers(desk):
    d = _day(new=[{"issue_id": I1, "status_line": "5G 요금이 바뀌었다."}])
    assert units.check_unit("day", d)["errors"]


# ── 같은 내용에 적힌 지적은 그 지적을 가리킨 뒤의 통과로만 풀린다(반려는 내용을 고쳐야 풀린다) ──
def test_objection_resolved_by_addressing_pass(desk):
    ready(I1)
    r = add_review(I1, "해석 점검", "가상 모델 G", "openai", "지적", findings=[{"field": "claims.c1", "note": "표현 확인"}])
    assert revisions.review_state(*load(I1)) == "검토 대기"
    add_review(I1, "해석 점검", "가상 모델 G", "openai", "통과")                 # 지적을 가리키지 않은 통과는 풀지 않는다
    assert revisions.review_state(*load(I1)) == "검토 대기"
    add_review(I1, "문장 대조", "Claude Sonnet", "anthropic", "통과", addresses=[r["id"]])   # 다른 종류의 통과도 풀지 않는다
    assert revisions.review_state(*load(I1)) == "검토 대기"
    add_review(I1, "해석 점검", "가상 모델 G", "openai", "통과", addresses=[r["id"]])
    assert revisions.review_state(*load(I1)) == "검토 완료"


def test_rejection_not_resolved_by_pass(desk):
    ready(I1)
    r = add_review(I1, "해석 점검", "가상 모델 G", "openai", "반려", findings=[{"field": "claims.c1", "note": "핵심 오류"}])
    add_review(I1, "해석 점검", "가상 모델 G", "openai", "통과", addresses=[r["id"]])
    assert revisions.review_state(*load(I1)) == "검토 대기"


# ── 실제 자료 루트의 다른 이름(대소문자만 다른 경로)에서는 '시험' 승인을 실제 발행 목록에 쓰지 않는다 ──
def test_approve_refused_on_case_alias_of_real_root(desk, monkeypatch):
    import os

    from ozl.issues import paths
    alias = desk.parent / desk.name.swapcase()
    if alias.as_posix() == desk.as_posix() or not os.path.isdir(alias) or not os.path.samefile(alias, desk):
        pytest.skip("대소문자를 가리는 파일 시스템")
    monkeypatch.setattr(paths, "real_root", lambda: desk)
    monkeypatch.setenv(paths.ENV, str(alias))
    assert not paths.is_real_root() and paths.is_alias_of_real_root()
    h = ready(I1)
    r = revisions.approve(I1, 1, h, revisions.TEST_BY)
    assert r["code"] == 2 and "다른 이름" in r["msg"]
    assert not revisions.load_manifest()["entries"]
