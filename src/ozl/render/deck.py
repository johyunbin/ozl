#!/usr/bin/env python3
"""슈카월드 스타일 템플릿 덱 + 시제품 생성 (Phase 1A-4 D+3 게이트 / Phase 4 스캐폴딩).

토큰 v1(2026-11-10 · 대표 30편 정밀 측정 + 폰트 대조 — tracks/syuka/analysis/style_measure_syukaworld.md · private/style/style-guide.md §9):
  맑은 고딕 26pt(제목·본문 같은 크기 · 13.333in 슬라이드 기준) · 1.5줄 · 제목/강조 진한 빨강 #C00000 · 본문 검정 · 강조 = 빨강 / 굵게 / 빨강 굵게 · 배경 흰색.
슬라이드 타입: title_hook · image_text(좌 이미지/우 텍스트) · quote_translation(영문 원문→한글 번역) · two_images(2장+캡션) · compare_table · closing.
이미지는 Phase 4 전까지 출처 표기 플레이스홀더(회색 박스). python-pptx 1.0.2 — 베이스는 .pptx.

    python -m ozl.render.deck prototype   # private/decks/drafts/prototype_<ts>.pptx + .pdf + png/
"""
from __future__ import annotations

import datetime as dt
import pathlib
import subprocess
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt
from lxml import etree

ROOT = pathlib.Path(__file__).resolve().parents[3]
DRAFTS = ROOT / "private" / "decks" / "drafts"

RED = RGBColor(0xC0, 0x00, 0x00)  # 표준 '진한 빨강'. 스트림 측정값(굵은 획 심지) #C70D18 — 가는 획의 #AA131E 는 압축 번짐
TITLE_RGB = RED
BODY_RGB = RGBColor(0x00, 0x00, 0x00)  # 측정 #020202 (v0 의 #312E34 는 안티에일리어싱 섞인 중앙값이었다)
EMPH_RGB = RED
CAPTION_RGB = RGBColor(0x00, 0x00, 0x00)
PLACEHOLDER_RGB = RGBColor(0xE6, 0xE6, 0xE6)
FONT = "맑은 고딕"  # 폰트 대조 13줄: Malgun Gothic Regular 평균 IoU 0.68(차순위 0.42) · 굵게 = Malgun Gothic Bold IoU 0.83
SIZE = 26  # pt. em = 캔버스 폭의 2.72% → 13.333in 슬라이드에서 26.1pt. 제목·본문 동일
CAPTION_SIZE = 20  # 그림 밑 캡션(글자 높이 24~25px 군)
LINE = 1.5  # 줄 간격 59.4px = 1.79em ≈ 파워포인트 1.5줄(1.5 × 1.2em)


def set_run_font(run, name: str) -> None:
    """라틴(a:latin)뿐 아니라 동아시아(a:ea)·복합(a:cs) 서체까지 지정 — 빠뜨리면 LibreOffice/PowerPoint가 한글을 다른 폰트로 대체하거나 비운다."""
    rPr = run._r.get_or_add_rPr()
    latin = rPr.find(qn("a:latin"))
    if latin is None:
        latin = etree.SubElement(rPr, qn("a:latin"))
    latin.set("typeface", name)
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = etree.Element(qn(tag))
            latin.addnext(el)  # 스키마 순서: latin → ea → cs
            latin = el
        el.set("typeface", name)

W, H = Inches(13.333), Inches(7.5)  # 16:9 확정(1080p 전체 프레임에서 캔버스 1218×686px)
CANVAS_PX = 1218.0


def px(n: float) -> Emu:
    """원본 1080p 화면의 캔버스 픽셀 → 슬라이드 길이(EMU). 측정 좌표를 그대로 옮길 때 쓴다."""
    return Emu(int(round(n / CANVAS_PX * W)))


# 글상자 변 → 첫 글자 잉크까지의 거리(px · 26pt · 안쪽 여백 0.05in). replica 검증(파워포인트 렌더 vs 원본 프레임)에서 전 줄 ±1px 로 맞춘 값
INK_DX = 7.5         # 글상자 왼쪽 변 → 잉크 왼쪽
TITLE_INK_DY = 9.0   # 줄 간격 1.0 글상자 윗변 → 한글 잉크 윗변
BODY_INK_DY = 23.5   # 줄 간격 1.5 글상자 윗변 → 첫 줄 잉크 윗변

M = px(88)  # 좌측 여백: 그림 왼쪽 변 중앙값 88px(0.96in)
TITLE_LEFT = px(92 - INK_DX)  # 제목 글자 시작 중앙값 92px
TITLE_TOP = px(71 - TITLE_INK_DY)  # 제목 글자 윗변 중앙값 71px
IMG_TOP = px(176)  # 그림 윗변 중앙값 176px(1.93in)
BODY_TOP = px(211 - BODY_INK_DY)  # 첫 본문 줄 윗변 중앙값 211px
IMG_W, IMG_H = px(384), px(376)  # 좌 그림 폭·높이 중앙값(4.20×4.12in)
GAP = px(48 - INK_DX)  # 그림 오른쪽 변 → 글 기둥 잉크까지 48px


def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    return prs


def _blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _text(slide, left, top, width, height, runs, size=SIZE, align=PP_ALIGN.LEFT, line_spacing=LINE):
    """runs: list of (text, {'bold':bool,'color':RGBColor,'size':int}) 또는 '\n' 으로 문단 구분."""
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.05)
    para = tf.paragraphs[0]
    para.alignment = align
    para.line_spacing = line_spacing
    for item in runs:
        if item == "\n":
            para = tf.add_paragraph()
            para.alignment = align
            para.line_spacing = line_spacing
            continue
        text, st = item if isinstance(item, tuple) else (item, {})
        r = para.add_run()
        r.text = text
        f = r.font
        f.size = Pt(st.get("size", size))
        f.bold = st.get("bold", False)
        f.color.rgb = st.get("color", BODY_RGB)
        set_run_font(r, FONT)
    return tb


def title(slide, text):
    return _text(slide, TITLE_LEFT, TITLE_TOP, W - TITLE_LEFT - M, px(60), [(text, {"color": TITLE_RGB, "size": SIZE})], line_spacing=1.0)


def placeholder_image(slide, left, top, width, height, caption=None, source="이미지 출처: (공식 프레스킷/기관 원본 URL 기재)"):
    box = slide.shapes.add_shape(1, left, top, width, height)  # 1 = 사각형
    box.fill.solid()
    box.fill.fore_color.rgb = PLACEHOLDER_RGB
    box.line.color.rgb = RGBColor(0xBB, 0xBB, 0xBB)
    box.text_frame.text = "이미지"
    box.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    r0 = box.text_frame.paragraphs[0].runs[0]
    r0.font.size = Pt(14)
    r0.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    set_run_font(r0, FONT)
    if caption:
        _text(slide, left, top + height + Inches(0.08), width, Inches(0.9), [(caption, {"size": CAPTION_SIZE})], align=PP_ALIGN.CENTER, line_spacing=1.2)
    _text(slide, left, top + height + (Inches(1.0) if caption else Inches(0.05)), width, Inches(0.3), [(source, {"size": 9, "color": RGBColor(0x99, 0x99, 0x99)})], line_spacing=1.0)
    return box


def slide_title_hook(prs, hook, sub=None):
    s = _blank(prs)
    _text(s, M, Inches(2.4), W - 2 * M, Inches(1.4), [(hook, {"color": TITLE_RGB, "size": 40, "bold": True})], align=PP_ALIGN.CENTER, line_spacing=1.2)
    if sub:
        _text(s, M, Inches(3.9), W - 2 * M, Inches(0.8), [(sub, {"size": SIZE})], align=PP_ALIGN.CENTER)
    return s


def slide_image_text(prs, ttl, body_runs, caption=None):
    s = _blank(prs)
    title(s, ttl)
    placeholder_image(s, M, IMG_TOP, IMG_W, IMG_H, caption)
    _text(s, M + IMG_W + GAP, BODY_TOP, W - 2 * M - IMG_W - GAP, Inches(4.8), body_runs)
    return s


def slide_quote_translation(prs, ttl, en, ko_runs, flag_caption=None):
    s = _blank(prs)
    title(s, ttl)
    placeholder_image(s, M, IMG_TOP, Inches(2.6), Inches(1.7), flag_caption, source="이미지 출처: 공식 국기/로고 (기관 CI 가이드)")
    # 영문 원문(검정) 바로 아래 한글 번역(빨강) — 원본은 한 글상자 안에서 줄을 이어 쓴다
    _text(s, M + Inches(3.2), BODY_TOP, W - 2 * M - Inches(3.2), Inches(4.8), [(en, {}), "\n", *ko_runs])
    return s


def slide_two_images(prs, ttl, cap1, cap2, note_runs=None):
    s = _blank(prs)
    title(s, ttl)
    w = (W - 2 * M - Inches(0.4)) / 2
    placeholder_image(s, M, IMG_TOP, w, Inches(3.0), cap1)
    placeholder_image(s, M + w + Inches(0.4), IMG_TOP, w, Inches(3.0), cap2)
    if note_runs:
        _text(s, M, Inches(6.2), W - 2 * M, Inches(0.8), note_runs)
    return s


def slide_closing(prs, ttl, bullets, sources):
    s = _blank(prs)
    title(s, ttl)
    runs = []
    for i, b in enumerate(bullets):
        if i:
            runs.append("\n")
        runs.extend(b if isinstance(b, list) else [(b, {})])
    _text(s, M, BODY_TOP, W - 2 * M, Inches(3.8), runs)
    _text(s, M, Inches(6.4), W - 2 * M, Inches(0.9), [("출처: " + " · ".join(sources), {"size": 11, "color": RGBColor(0x77, 0x77, 0x77)})], line_spacing=1.2)
    return s


def add_notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


E = lambda t: (t, {"bold": True, "color": EMPH_RGB})  # noqa: E731
R = lambda t: (t, {"color": EMPH_RGB})  # noqa: E731  빨강 보통 굵기(번역문·핵심 문장 — 본문 줄의 35%)
B = lambda t: (t, {"bold": True})  # noqa: E731


def build_prototype() -> pathlib.Path:
    """시제품: 슬라이드 타입 5종의 레이아웃·토큰 확인용. 문구는 전부 지어낸 예시다(실제 방송 슬라이드 문구를 옮기지 않는다 — 공개 저장소).
    실제 프레임과의 대조는 비공개 사양을 읽는 replica.py 가 맡는다."""
    prs = new_deck()
    s1 = slide_title_hook(prs, "우리 동네 가로수는 왜 전부 같은 나무일까", "[예시] 주제를 여는 질문 한 줄")
    add_notes(s1, "여는 장: 질문형 제목 카드. [시제품 — 문구는 지어낸 예시]")
    s2 = slide_two_images(prs, "같은 길, 다른 계절에 찍은 두 장면",
                          "봄에 찍은 사진\n[예시 캡션]", "가을에 찍은 사진\n[예시 캡션]",
                          [("여기에 ", {}), E("핵심 수치 하나"), ("와 ", {}), E("핵심 수치 둘"), ("을 넣는다.", {})])
    add_notes(s2, "그림 2장 + 캡션 + 한 줄 요약. 수치는 claim 레코드에서 가져온다.")
    s3 = slide_image_text(prs, "그런데 관리 기록을 보면 이야기가 달라진다",
                          [("본문은 어절 단위로 끊어 다섯 줄 안팎으로 쓴다.", {}), "\n",
                           B("강조할 문장은 굵게 한 줄로 따로 둔다.")],
                          caption=None)
    add_notes(s3, "좌 그림 + 우 글(전체의 70%). 제목은 접속어로 시작하는 문장.")
    s4 = slide_quote_translation(prs, "해외 기사는 이렇게 전했다",
                                 "An example sentence quoted from a foreign article goes here.",
                                 [R("외신 원문 바로 아래에 번역을 빨강으로 붙이고, "), E("핵심 구절만 굵게"), R(" 표시한다.")],
                                 flag_caption="[예시]")
    add_notes(s4, "영문 원문(검정) → 한글 번역(빨강) → 핵심(빨강 굵게). 원문 출처 locator 필수.")
    s5 = slide_closing(prs, "정리: 답은 하나가 아니다",
                       [[("첫째 줄에는 ", {}), E("가장 중요한 발견"), ("을 쓴다", {})],
                        [("둘째 줄에는 ", {}), E("비교에서 나온 차이"), ("를 쓴다", {})],
                        [("셋째 줄은 ", {}), B("다음 주제로 넘어가는 질문"), ("으로 닫는다", {})]],
                       ["[예시] 기관 발표(T1)", "[예시] 통계 원자료(T1)", "[예시] 외신 기사(T3)"])
    add_notes(s5, "닫는 장: 요약 대신 열린 질문. 숨김 슬라이드에 원문 캡처 첨부 예정.")
    DRAFTS.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DRAFTS / f"prototype_sample_{ts}.pptx"
    prs.save(str(out))
    return out


SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def to_pdf_png(pptx: pathlib.Path) -> tuple[pathlib.Path | None, list[pathlib.Path]]:
    """pptx → PDF → PNG. 파워포인트(맑은 고딕·줄 간격이 원본 엔진과 동일)를 먼저 쓰고, 없거나 실패하면 LibreOffice 로 대체한다."""
    outdir = pptx.parent
    from ozl.render.ppt_export import export_pdf
    pdf = None
    try:
        pdf = export_pdf(pptx)
    except Exception as e:  # noqa: BLE001
        print("파워포인트 내보내기 실패 → LibreOffice 대체:", e, file=sys.stderr)
    if pdf is None:
        r = subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(pptx)], capture_output=True, text=True, timeout=180)
        pdf = pptx.with_suffix(".pdf")
        if not pdf.exists():
            print("PDF 변환 실패:", r.stderr[-300:], file=sys.stderr)
            return None, []
    pngdir = outdir / (pptx.stem + "_png")
    pngdir.mkdir(exist_ok=True)
    r = subprocess.run(["pdftoppm", "-png", "-scale-to-x", str(int(CANVAS_PX)), "-scale-to-y", "686", str(pdf), str(pngdir / "slide")], capture_output=True, text=True)
    if r.returncode != 0:
        print("PNG 렌더 실패:", r.stderr[-300:], file=sys.stderr)
    return pdf, sorted(pngdir.glob("slide*.png"))


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "prototype"
    if cmd == "prototype":
        pptx = build_prototype()
        pdf, pngs = to_pdf_png(pptx)
        print(pptx)
        print(pdf)
        for p in pngs:
            print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
