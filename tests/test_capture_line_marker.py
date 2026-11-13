"""통째 대목 검사(passage_bounds_error)의 줄 머리 기호 — 정부 문서의 '□ ', 'ㅇ ', '○ ', '▲ ', '※ ', '- ' 뒤를 대목의 시작으로 받는다.
부호로도 읽히는 기호(-, ▲, △) 뒤의 수는 그대로 거부한다. 글은 모두 지어낸 것이다(가상의 한빛시)."""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.research import capture as K  # noqa: E402


def _bounds(text: str, passage: str) -> str:
    norm, _ = K.normalize(text)
    q, _ = K.normalize(passage)
    assert norm.count(q) == 1, (norm, q)
    s = norm.index(q)
    return K.passage_bounds_error(text, s, s + len(q))


@pytest.mark.parametrize("text,passage", [
    ("가상 시정 안내\n□ 한빛시는 요금 체계를 고친다.\nㅇ 시내버스 기본요금을 올린다.", "한빛시는 요금 체계를 고친다."),
    ("가상 시정 안내\n□ 한빛시는 요금 체계를 고친다.\nㅇ 시내버스 기본요금을 올린다.", "시내버스 기본요금을 올린다."),
    ("가상 시정 안내\n○ 세부 사항은 따로 알린다.", "세부 사항은 따로 알린다."),
    ("가상 시정 안내\n▲ 세부 사항은 따로 알린다.", "세부 사항은 따로 알린다."),
    ("가상 시정 안내\n※ 세부 사항은 따로 알린다.", "세부 사항은 따로 알린다."),
    ("가상 시정 안내\n- 세부 사항은 따로 알린다.", "세부 사항은 따로 알린다."),
    ("가상 시정 안내\n○세부 사항은 따로 알린다.", "세부 사항은 따로 알린다."),          # 기호에 붙여 쓴 대목
    ("□ 한빛시는 요금 체계를 고친다.", "한빛시는 요금 체계를 고친다."),                    # 글의 처음
    ("요금을 고친다. ○ 세부 사항은 따로 알린다.", "세부 사항은 따로 알린다."),             # 문장 끝 뒤의 기호
    ("가상 시정 안내\n□ 한빛시는 요금 체계를 고친다\nㅇ 다음 줄", "한빛시는 요금 체계를 고친다"),   # 마침표 없는 항목 줄
])
def test_line_marker_starts_passage(text, passage):
    assert _bounds(text, passage) == ""


@pytest.mark.parametrize("text,passage,why", [
    ("성장률은\n- 0.8%다.", "0.8%다.", "문장 중간"),                         # 줄 머리의 '-' 뒤 수는 부호로 본다
    ("성장률은\n▲ 3.2%다.", "3.2%다.", "문장 중간"),
    ("성장률은\n-$3 million.", "$3 million.", "낱말 중간"),
    ("가상 □ 세부 사항은 따로 알린다.", "세부 사항은 따로 알린다.", "문장 중간"),       # 줄 머리가 아닌 기호
    ("값 - 세부 사항은 따로 알린다.", "세부 사항은 따로 알린다.", "문장 중간"),
    ("성장률은 − 0.8%다. 끝.", "0.8%다.", "문장 중간"),
    ("가상 시정 안내\n□ 한빛시는 요금 체계를 고친다.", "요금 체계를 고친다.", "문장 중간"),   # 기호 뒤 문장의 중간
])
def test_line_marker_does_not_open_other_starts(text, passage, why):
    err = _bounds(text, passage)
    assert err and why in err, err
