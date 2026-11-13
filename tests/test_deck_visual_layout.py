"""덱 화면 다듬기 회귀 테스트 — 원문 캡처 그림(대목만 · 글자 크기 · 낱말 줄바꿈 · capture_focus) · PDF 띠 · 부록 시각물 검증표 ·
수량 덩어리 줄바꿈 · 차트 부제 줄바꿈. 네트워크 없이 돈다. 예시 문장과 숫자는 전부 지어낸 것이다."""
from __future__ import annotations

import pathlib
import re
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.render import build as B  # noqa: E402
from ozl.render import charts as G  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.research import capture as K  # noqa: E402
from test_capture import _pdf  # noqa: E402
from test_deck_visuals import CID, SENTENCE, URL, desk, errors, line_chart, machine_claim, slide, spec_of  # noqa: E402,F401

FONT = G.pick_font()["path"]
SIZE = (1200, 1177)


def _lines(placed) -> list[str]:
    rows: dict[float, str] = {}
    for x, y, ch, _ in placed:
        rows[y] = rows.get(y, "") + ch
    return [rows[y].strip() for y in sorted(rows)]


def _plan(before, phrase, after, focus=None, size=SIZE):
    return K._passage_plan(before, phrase, after, size, FONT, focus)


# ── G1 원문 캡처 그림: 대목 글만 · 12pt 이상 · 낱말 단위 줄바꿈 ─────────────────
def test_passage_image_has_only_the_passage_and_the_note(tmp_path):
    text = "앞 문장은 가상의 머리말이다. " + SENTENCE + " 뒤 문장도 가상의 꼬리말이다. " + "가상의 덧말이 길게 이어진다. " * 10
    m = K.find_phrase(text, SENTENCE)["matches"][0]
    meta = {"url": URL, "fetched_at": "2099-01-02T10:00:00+09:00", "sha256": "ab" * 32}
    r = K.evidence_image(CID, tmp_path / "x.html", "html", text, SENTENCE, m["offset"], meta, tmp_path / "e.png", font_path=FONT)
    assert r["path"] and r["view"] == "text_passage" and r["pt"] >= 12
    big, note, placed, spans, pt = _plan(m["before"], SENTENCE, m["after"])
    drawn = "".join(ch for *_, ch, _ in placed)
    for leaked in (CID, URL, "sha256", "abab", "받은 시각", "원래 화면"):
        assert leaked not in drawn                              # 내부 정보는 그림에 없다(부록 표가 맡는다)
    assert SENTENCE.replace(" ", "") in drawn.replace(" ", "")
    assert "가상의 덧말" not in drawn                            # 문맥은 앞뒤 한 문장 안팎
    assert K.PASSAGE_NOTE == "원문의 글을 옮겨 그린 것 · 화면 모양은 원문과 다름"


def test_passage_font_floor_and_failure():
    mid = "가상의 섬 감자 수확량은 해마다 조금씩 늘어 왔다고 가상 통계청이 밝혔다. " * 9
    p = _plan("", mid.strip(), "")
    assert p is not None and 9 <= p[4] < 12                   # 길면 글자를 줄이되 9pt 아래로는 안 간다
    assert _plan("", ("가상의 긴 문장이 이어진다. " * 200).strip(), "") is None    # 최소로도 안 들어가면 실패


def test_english_wraps_at_word_boundaries_and_quantities_stay_together():
    phrase = ("Our imaginary potato cooperative now reaches 70% of the islanders within 7 miles of an Imaginaryco storage "
              "depot, and the cooperative spent about 4억 1,000만 달러 on new greenhouses.")
    big, note, placed, spans, pt = _plan("", phrase, "")
    lines = _lines(placed)
    words = set(phrase.split())
    for ln in lines:
        for w in ln.split():
            assert w in words, (w, lines)                       # 낱말 가운데서 끊긴 조각이 없다
    joined = "\n".join(lines)
    assert "7 miles" in joined and "4억 1,000만 달러" in joined    # 수량 덩어리는 한 줄


def test_hangul_wraps_by_eojeol():
    phrase = "가상의 섬 통계청은 올해 감자와 당근과 양파의 수확량을 한꺼번에 집계해 발표했다고 밝혔다. " * 2
    lines = _lines(_plan("", phrase.strip(), "")[2])
    words = set(phrase.split())
    assert all(w in words for ln in lines for w in ln.split())


# ── G2 capture_focus ──────────────────────────────────────────────────────
def test_focus_marks_only_the_phrase():
    big, note, placed, spans, pt = _plan("앞 문장이다.", SENTENCE, "뒤 문장이다.", focus="18,250")
    marked = "".join(ch for *_, ch, st in placed if st == "mark")
    assert marked == "18,250" and spans == [(SENTENCE.index("18,250"), SENTENCE.index("18,250") + 6)]
    assert {st for *_, st in placed} == {"ctx", "norm", "mark"}
    _, _, placed, spans, _ = _plan("", SENTENCE, "", focus=["2098년 12월", "18,250"])
    assert "".join(ch for *_, ch, st in placed if st == "mark") == "2098년 12월18,250"
    _, _, placed, spans, _ = _plan("", SENTENCE, "")
    assert spans is None and all(st == "mark" for *_, ch, st in placed if ch != " ")   # 안 쓰면 대목 전체
    with pytest.raises(ValueError):
        K.focus_spans(SENTENCE, "19,250")
    assert K.focus_spans("가상  감자\n값", "감자 값") == [(3, 7)]          # 공백만 정리해 비교


def test_focus_outside_passage_fails_check(desk):
    c = machine_claim(desk)
    assert errors(slide(capture=CID, capture_focus="18,250"), {CID: c}) == []
    assert errors(slide(capture=CID, capture_focus=["2098년 12월", "18,250"]), {CID: c}) == []
    errs = errors(slide(capture=CID, capture_focus="19,250"), {CID: c})
    assert any("capture_focus '19,250'" in e and "대목 안에" in e for e in errs), errs
    assert any("capture_focus 는" in e for e in errors(slide(capture=CID, capture_focus=["", "18,250"]), {CID: c}))
    assert any("capture 를 쓴 쪽에서만" in e for e in errors(slide(chart=line_chart(), capture_focus="18,250"), {CID: c}))


def test_focus_reaches_the_drawing_in_build(desk, monkeypatch):
    c = machine_claim(desk)
    seen = []
    real = K.evidence_image
    monkeypatch.setattr(K, "evidence_image", lambda *a, **k: seen.append(k.get("focus")) or real(*a, **k))
    B.build_pptx(spec_of([slide(capture=CID, capture_focus="18,250")]), {CID: c}, {"card_id": "x"}, desk / "o" / "d.pptx")
    assert seen == ["18,250"]


# ── G3 PDF 띠 ─────────────────────────────────────────────────────────────
@pytest.mark.skipif(not (shutil.which("pdftoppm") and shutil.which("pdftotext")), reason="poppler 없음")
def test_pdf_band_spans_text_area_and_focus_marks_words(tmp_path):
    p = tmp_path / "a.pdf"
    lines = ["Imaginary Island harvest note for a test page only.", "Carrot harvest was 4,321 tonnes as well.",
             "A filler line that reaches a little further right."] + ["Filler line."] * 10
    _pdf(p, lines)
    plan = K._pdf_band_plan(p, 1, "Carrot harvest was 4,321 tonnes as well.", 0, 1)
    pw, ph, words = K._pdf_words(p, 1)
    assert plan["mode"] == "band"
    x0, y0, x1, y1 = plan["box"]
    assert x0 <= min(w[0] for w in words) and x1 >= max(w[2] for w in words)   # 쪽 글 영역 전체 폭(오른쪽이 잘리지 않는다)
    assert len(plan["marks"]) == 7
    fp = K._pdf_band_plan(p, 1, "Carrot harvest was 4,321 tonnes as well.", 0, 1, focus="4,321 tonnes")
    assert [w[4] for w in fp["marks"]] == ["4,321", "tonnes"]
    r = K._pdf_band(p, 1, plan, tmp_path / "b.png")
    from PIL import Image
    with Image.open(r["path"]) as g:
        assert g.width >= K.BAND_TARGET_PX * 0.95 and r["view"] == "pdf_band"
    small = K._pdf_band_plan(p, 1, "Carrot harvest was 4,321 tonnes as well.", 0, 1, slot_width_in=1.0)
    assert small["mode"] == "redraw" and "옮겨 그렸다" in small["note"]     # 자리에 넣어 글자가 작으면 대목을 다시 그린다


# ── G4 부록 시각물 검증표 ──────────────────────────────────────────────────
def test_appendix_rows_for_chart_and_capture(desk):
    c = machine_claim(desk)
    sp = spec_of([slide(chart=line_chart(y_from_zero=False)), slide(capture=CID)])
    rows = B.visual_check_rows(sp, {CID: c})
    assert rows[0][:3] == ["3", "차트(선)", "가상의 섬 감자 값 · 기록 c1"]
    assert rows[0][3] == "단위 원 · 기간 2098-01 ~ 2098-12" and "칸과 값의 짝은 문장 대조에서 확인" in rows[0][5] and "0에서 시작하지 않음" in rows[0][5]
    cap = c["verification"]["capture"]
    assert rows[1][:4] == ["4", "원문 캡처", "기록 c1", URL]
    assert rows[1][4] == f"{cap['fetched_at'][:10]} {cap['fetched_at'][11:16]} · sha256 {cap['sha256'][:12]}" and rows[1][5] == "원문의 글을 옮겨 그림"
    assert B.visual_check_rows(sp, {CID: c}, views={4: "pdf_band"})[1][5] == "PDF 쪽에서 자름"
    titles = [t[0] for t in B.appendix_tables(sp, {CID: c}, {})]
    assert titles[-2:] == ["부록 · 시각물 출처·검증표", "부록 · 시각물 출처·검증표(차트·원문 캡처)"]    # 회색 그림 자리 표는 그대로 둔다
    bare = {**sp, "slides": [{k: v for k, v in x.items() if k != "image"} for x in sp["slides"]]}
    assert [t[0] for t in B.appendix_tables(bare, {CID: c}, {})][-1:] == ["부록 · 시각물 출처·검증표(차트·원문 캡처)"]
    assert "부록 · 시각물 출처·검증표" not in [t[0] for t in B.appendix_tables(bare, {CID: c}, {})]   # 빈 표를 내지 않는다
    out = desk / "o" / "d.pptx"
    info = B.build_pptx(sp, {CID: c}, {"card_id": "x"}, out)
    from pptx import Presentation
    last = list(Presentation(str(out)).slides)[-1]
    cells = [cl.text for sh in last.shapes if sh.has_table for r in sh.table.rows for cl in r.cells]
    assert info["appendix"][-1].startswith("부록 · 시각물 출처·검증표(차트·원문 캡처)") and URL in cells and "차트(선)" in cells
    assert B.appendix_problems(sp, {CID: c}, {}) == []


# ── G5 수량 덩어리 줄바꿈 ──────────────────────────────────────────────────
def _fake(text, size, bold=False):
    return len(text) * size


@pytest.mark.parametrize("text,chunk", [
    ("가상 행사의 방문객은 약 5만 명이었다고 한다", "약 5만 명이었다고"),
    ("가상 회사의 매출은 약 4억 1,000만 달러로 늘었다", "약 4억 1,000만 달러로"),
    ("가상 설비 취득은 8억 9,700만 달러였다", "8억 9,700만 달러였다"),
    ("가상 서비스는 2022년 11월에 시작했다", "2022년 11월에"),
    ("가상 매장 넓이는 9,500만 제곱피트다", "9,500만 제곱피트다"),
])
def test_wrap_keeps_quantity_chunks_on_one_line(text, chunk):
    for width in range(60, 400, 10):
        got = [text[a:b] for a, b in S.wrap(text, width, 10, measure_fn=_fake)]
        if _fake(chunk, 10) <= width:
            assert any(chunk in g for g in got), (width, got)    # 덩어리가 들어갈 폭이면 덩어리째 한 줄
        assert " ".join(got) == text


def test_wrap_long_chunk_breaks_before_then_inside():
    text = "값 약 4억 1,000만 달러로"
    got = [text[a:b] for a, b in S.wrap(text, 60, 10, measure_fn=_fake)]
    assert got[0] == "값" and " ".join(got) == text           # 덩어리 앞에서 바꾸고, 줄보다 길면 그 안을 어절로


def test_qty_groups_do_not_swallow_ordinary_words():
    t = "1월 1,120원에서 11월 1,905원까지 3 원문을 본다"
    ws = [(m.start(), m.end()) for m in re.finditer(r"\S+", t)]
    assert [[t[a:b] for a, b in g] for g in S.qty_groups(t, ws)] == [["1월"], ["1,120원에서"], ["11월"], ["1,905원까지"], ["3"], ["원문을"], ["본다"]]


# ── G6 차트 부제: 구분자에서만 줄바꿈 ───────────────────────────────────────
def test_chart_subtitle_breaks_only_at_separators():
    import matplotlib.pyplot as plt
    with plt.rc_context({"font.family": [G.pick_font()["family"], "DejaVu Sans"]}):
        fig = plt.figure(figsize=(4.2, 4.12), dpi=100)
        r = fig.canvas.get_renderer()
        text = "단위: 억 원 · 기간: 2025년 3분기 · 2026년 2분기 · 2026년 3분기"
        widest = max(G._text_w(fig, r, x, G.SUB_PT) for x in text.split(" · "))
        for px in (widest + 1, widest + 40, widest * 1.6, widest * 2.5):
            lines = G._wrap_items(fig, r, text, G.SUB_PT, px)
            items = [x.strip(" ·") for ln in lines for x in ln.split(" · ")]
            assert items == text.split(" · "), (px, lines)       # 한 항목('2026년 3분기')은 줄 사이에서 갈리지 않는다
        plt.close(fig)
