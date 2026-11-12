"""기계 대조(「원문 일치」) 기록을 덱이 쓸 때의 규칙 — 2026-11-13 Codex 검토에서 나온 두 오통과의 회귀 테스트.
예시 문장과 수치는 전부 지어낸 것이다."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import test_capture as T  # noqa: E402
from test_capture import desk  # noqa: E402,F401  (pytest fixture)
from ozl.render import spec as S  # noqa: E402
from ozl.research import cards as C  # noqa: E402


def _machine_claim(tmp, text):
    claim = T.base_claim()
    claim["text"] = text
    T.prepare(tmp, claim)
    assert C.machine_verify(T.CID)["ok"]
    return C.load_yaml(C.claim_path(T.CID))


def _slide(shown):
    return {"stage": "근거 수치", "kind": "image_text", "title": "감자", "body": [f"수확량은 {shown}으로 늘었다"], "claim_ids": [T.CID]}


def test_machine_record_backs_only_what_was_matched_against_the_copy(desk):
    """기계 대조 기록의 숫자 근거는 사본과 대조한 observed 뿐이다. 쓴 쪽 문장(text)에만 있는 숫자는 근거가 못 된다."""
    c = _machine_claim(desk, "가상의 섬 2098년 감자 수확량은 9,999톤이다.")      # text 의 숫자는 원문(4,321톤)과 다르다
    assert S.acceptance_error(c) == ""
    assert S.number_errors(_slide("4,321톤"), {T.CID: c}) == []
    assert S.number_errors(_slide("9,999톤"), {T.CID: c}) != []
    assert S.basis_texts(c) == [c["observed"]]


def test_human_checked_and_old_records_keep_text_as_basis():
    old = {**T.base_claim(), "text": "가상의 섬 2098년 감자 수확량은 9,999톤이다.", "status": "verified",
           "human_verified": True, "human_verified_at": "x", "human_verified_by": "y"}
    assert S.number_errors(_slide("9,999톤"), {T.CID: old}) == []                 # 사람이 문장까지 본 기록은 종전 그대로
    pending = {**T.base_claim(), "text": "가상의 섬 2098년 감자 수확량은 9,999톤이다."}
    assert len(S.basis_texts(pending)) == 2                                        # verification 묶음이 없는 옛 기록도 종전 그대로


def test_strict_mode_reruns_record_validation_for_machine_records(desk):
    """등급을 올릴 때 걸리는 기록 검사(validate_claim)를 덱 엄격 모드도 다시 한다 — 파일에 verified 라고 고쳐 쓴 것으로는 못 넘는다."""
    c = _machine_claim(desk, "가상의 섬 2098년 감자 수확량은 4,321톤이다.")
    assert S.acceptance_error(c) == ""
    c["checks"]["unit_ok"] = False                                                # 올린 뒤에 검사 칸을 고쳐 쓴 경우
    assert C.validate_claim(c, deep=True) != []
    why = S.acceptance_error(c)
    assert why and "증거가 맞지 않는다" in why
    errs, _ = S.claim_state_errors([T.CID], {T.CID: c})
    assert errs


def test_base_period_range_is_rendered_with_spaces():
    """범위로 적은 기준 시점은 양끝을 풀어 띄어 쓴다(부록 표의 칸에서 줄을 바꿀 수 있게)."""
    assert S.base_period_text("2098-01~2098-09") == "2098년 1월 ~ 2098년 9월"
    assert S.base_period_text("2098-Q3") == "2098년 3분기" and S.base_period_text("2098") == "2098년"
