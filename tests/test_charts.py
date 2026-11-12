"""차트 그리기(src/ozl/render/charts.py) 회귀 테스트.
예시 자료는 전부 지어낸 것이다(가상 지표·가상 기관 — 실제 회사·기관의 수치 아님)."""
from __future__ import annotations

import copy
import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.render import charts as CH  # noqa: E402


def png_size(path: pathlib.Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", head[16:24])


def line_spec(**kw):
    base = {"kind": "line", "title": "가상 지표 갑이 열두 달 사이 올랐다", "unit": "가상 단위", "period": "2098-01 ~ 2098-12",
            "series": [{"name": "가상 지표 갑", "points": [["2098-01", 10], ["2098-06", "12.50"], ["2098-12", 17.25, "17.25"]]}],
            "source": "가상 통계청, 가상 월간 통계", "claims": ["2099-01-02-am-01-c1"], "transform": "", "highlight": ["2098-12"]}
    base.update(kw)
    return base


def bar_spec(**kw):
    base = {"kind": "bar", "title": "가상 지역별 증감", "unit": "%", "period": "2098년",
            "series": [{"name": "증감률", "points": [["북부", "4.5"], ["남부", "-3.20"], ["서부", 2]]}],
            "source": "가상 협회", "claims": ["2099-01-02-am-01-c2"], "highlight": ["남부"]}
    base.update(kw)
    return base


# ── 정상 경로 ────────────────────────────────────────────────────────────
def test_line_renders_at_requested_size(tmp_path):
    out = CH.render_chart(line_spec(), tmp_path / "a" / "line.png", size_px=(900, 600))
    assert out.is_file() and out.stat().st_size > 0
    assert png_size(out) == (900, 600)


def test_default_size_matches_slot_ratio(tmp_path):
    out = CH.render_chart(line_spec(), tmp_path / "line.png")
    w, h = png_size(out)
    assert (w, h) == CH.DEFAULT_SIZE_PX
    assert abs(w / h - CH.SLOT_W_IN / CH.SLOT_H_IN) < 0.01


def test_bar_with_negative_values(tmp_path):
    spec = bar_spec()
    assert CH.validate_chart(spec) == []
    out = CH.render_chart(spec, tmp_path / "bar.png", size_px=(800, 800))
    assert png_size(out) == (800, 800) and out.stat().st_size > 0


def test_two_series_line_and_bar(tmp_path):
    pts_a = [["1분기", 3], ["2분기", 5], ["3분기", 4]]
    pts_b = [["1분기", 2], ["2분기", -1], ["3분기", 6]]
    series = [{"name": "가상 갑", "points": pts_a}, {"name": "가상 을", "points": pts_b}]
    for kind in ("line", "bar"):
        spec = line_spec(kind=kind, series=copy.deepcopy(series), highlight=["3분기"])
        assert CH.validate_chart(spec) == []
        out = CH.render_chart(spec, tmp_path / f"{kind}2.png", size_px=(700, 700))
        assert png_size(out) == (700, 700)
    assert CH.chart_quantities(spec)[-2:] == ["4", "6"]


def test_line_not_from_zero_allowed(tmp_path):
    out = CH.render_chart(line_spec(y_from_zero=False), tmp_path / "nz.png", size_px=(600, 600))
    assert out.is_file()


# ── 꼬리표 문자열은 입력 표기 그대로 ─────────────────────────────────────
def test_quantities_keep_input_notation():
    spec = line_spec(highlight=["2098-01", "2098-06", "2098-12"])
    q = CH.chart_quantities(spec)
    assert q[-3:] == ["10", "12.50", "17.25"]  # 반올림·끝자리 0 지우기 없음
    spec = line_spec(series=[{"name": "가상", "points": [["가", 1234567, "1234567"], ["나", "1,234.50"]]}], highlight=["가", "나"])
    assert CH.chart_quantities(spec)[-2:] == ["1234567", "1,234.50"]  # 쉼표 추가·제거 없음
    assert CH.chart_quantities(bar_spec())[-1] == "-3.20"


def test_quantities_include_numbers_in_title_and_source():
    spec = line_spec(title="가상 지표가 3년 만에 25% 올랐다", transform="가상 단위 = 원래 값 × 2", highlight=[])
    q = CH.chart_quantities(spec)
    assert "3년" in q and "25%" in q and "2" in q
    assert "2098-01" not in q  # 달력 꼴(기간·가로축 칸)은 수량이 아니다


def test_no_highlight_no_labels():
    assert CH.chart_quantities(line_spec(highlight=[])) == []


# ── 검사 반례 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", ["unit", "period", "source", "claims", "title", "series", "kind"])
def test_missing_required(key):
    spec = line_spec()
    del spec[key]
    errs = CH.validate_chart(spec)
    assert any(f"'{key}'" in e for e in errs)


@pytest.mark.parametrize("key,val,needle", [
    ("unit", "  ", "단위"),
    ("claims", [], "검증 기록"),
    ("claims", [""], "검증 기록"),
    ("series", [], "계열"),
    ("kind", "pie", "kind"),
    ("y_from_zero", "no", "y_from_zero"),
    ("highlight", ["2097-01"], "가로축에 없다"),
    ("transform", None, "환산식"),
])
def test_bad_fields(key, val, needle):
    errs = CH.validate_chart(line_spec(**{key: val}))
    assert any(needle in e for e in errs), errs


def test_unknown_key_is_error():
    assert any("모르는 칸" in e for e in CH.validate_chart(line_spec(hilight=["2098-12"])))


def test_empty_points():
    errs = CH.validate_chart(line_spec(series=[{"name": "가상", "points": []}]))
    assert any("점('points')이 없다" in e for e in errs)


@pytest.mark.parametrize("v", ["열", None, True, float("nan"), float("inf"), "1.2.3", [1]])
def test_non_numeric_value(v):
    errs = CH.validate_chart(line_spec(series=[{"name": "가상", "points": [["가", v], ["나", 2]]}], highlight=[]))
    assert any("수가 아니다" in e for e in errs), errs


def test_single_point_line():
    errs = CH.validate_chart(line_spec(series=[{"name": "가상", "points": [["가", 1]]}], highlight=[]))
    assert any("둘 이상" in e for e in errs)
    # 막대는 하나여도 된다
    assert CH.validate_chart(bar_spec(series=[{"name": "가상", "points": [["가", 1]]}], highlight=[])) == []


def test_series_length_mismatch():
    series = [{"name": "갑", "points": [["가", 1], ["나", 2], ["다", 3]]}, {"name": "을", "points": [["가", 1], ["나", 2]]}]
    errs = CH.validate_chart(line_spec(series=series, highlight=[]))
    assert any("점 수가 다르다" in e for e in errs)


def test_series_x_order_mismatch():
    series = [{"name": "갑", "points": [["가", 1], ["나", 2]]}, {"name": "을", "points": [["나", 1], ["가", 2]]}]
    assert any("순서" in e for e in CH.validate_chart(line_spec(series=series, highlight=[])))


def test_duplicate_x_and_names():
    errs = CH.validate_chart(line_spec(series=[{"name": "갑", "points": [["가", 1], ["가", 2]]}], highlight=[]))
    assert any("겹친다" in e for e in errs)
    series = [{"name": "갑", "points": [["가", 1], ["나", 2]]}, {"name": "갑", "points": [["가", 1], ["나", 2]]}]
    assert any("이름이 겹친다" in e for e in CH.validate_chart(line_spec(series=series, highlight=[])))


def test_too_many_series():
    series = [{"name": f"계열{i}", "points": [["가", 1], ["나", 2]]} for i in range(4)]
    assert any("까지다" in e for e in CH.validate_chart(line_spec(series=series, highlight=[])))


def test_bad_point_shape():
    errs = CH.validate_chart(line_spec(series=[{"name": "갑", "points": [["가"], ["나", 2, "2", "x"]]}], highlight=[]))
    assert sum("꼴이어야 한다" in e for e in errs) == 2


def test_display_string_must_match_value():
    errs = CH.validate_chart(line_spec(series=[{"name": "갑", "points": [["가", 12.5, "12.6"], ["나", 2]]}], highlight=[]))
    assert any("값" in e and "다르다" in e for e in errs)
    # 같은 값의 다른 표기(끝자리 0·쉼표·%)는 받는다
    ok = line_spec(series=[{"name": "갑", "points": [["가", 12.5, "12.50"], ["나", 1234, "1,234"], ["다", 3, "3%"]]}], highlight=[])
    assert CH.validate_chart(ok) == []


def test_highlighted_float_needs_display_string():
    spec = line_spec(series=[{"name": "갑", "points": [["가", 12.5], ["나", 2]]}], highlight=["가"])
    assert any("표시 문자열" in e for e in CH.validate_chart(spec))
    spec["highlight"] = ["나"]  # int 는 그대로 찍어도 같다
    assert CH.validate_chart(spec) == []


def test_bar_y_from_zero_false_is_error(tmp_path):
    spec = bar_spec(y_from_zero=False)
    assert any("0에서 시작" in e for e in CH.validate_chart(spec))
    with pytest.raises(ValueError):
        CH.render_chart(spec, tmp_path / "x.png")
    assert not (tmp_path / "x.png").exists()


def test_render_refuses_invalid_spec(tmp_path):
    with pytest.raises(ValueError, match="차트 사양 오류"):
        CH.render_chart(line_spec(source=""), tmp_path / "x.png")
    with pytest.raises(ValueError):
        CH.chart_quantities(line_spec(claims=[]))


def test_not_a_dict():
    assert CH.validate_chart([]) == ["차트 사양은 dict 여야 한다"]


# ── 글꼴 ─────────────────────────────────────────────────────────────────
def test_font_has_hangul_and_minus():
    f = CH.pick_font()
    assert CH._has_hangul(f["path"])
    assert CH._missing_glyphs("가상 지표 −3.2% ~ · ×") == []


def test_missing_glyph_refused(tmp_path):
    spec = line_spec(source="가상 협회 \uA9C1")  # 어느 글꼴에도 없는 글자 → 네모로 찍지 않고 거절
    with pytest.raises(ValueError, match="글꼴에 없는 글자"):
        CH.render_chart(spec, tmp_path / "x.png")
