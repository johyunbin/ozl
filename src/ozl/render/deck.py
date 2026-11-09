#!/usr/bin/env python3
"""슈카월드 스타일 템플릿 덱 + 시제품 생성 (Phase 1A-4 D+3 게이트 / Phase 4 스캐폴딩).

토큰(측정 v0, private/style/style-guide.md): 제목 #A32122 · 본문 #312E34 · 강조 #A32122 볼드 · 배경 흰색.
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

TITLE_RGB = RGBColor(0xA3, 0x21, 0x22)
BODY_RGB = RGBColor(0x31, 0x2E, 0x34)
EMPH_RGB = RGBColor(0xA3, 0x21, 0x22)
CAPTION_RGB = RGBColor(0x31, 0x2E, 0x34)
PLACEHOLDER_RGB = RGBColor(0xE6, 0xE6, 0xE6)
FONT = "NanumSquareOTF"  # 임시(설치 OTF·LibreOffice 렌더 가능) — 폰트 판별 후 교체(맑은 고딕/나눔바른고딕 후보)


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

W, H = Inches(13.333), Inches(7.5)  # 16:9 (슬라이드 비율은 30편 집계 후 확정)
M = Inches(0.6)  # 좌우 여백


def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    return prs


def _blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _text(slide, left, top, width, height, runs, size=20, align=PP_ALIGN.LEFT, line_spacing=1.5):
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
    return _text(slide, M, Inches(0.45), W - 2 * M, Inches(0.8), [(text, {"color": TITLE_RGB, "size": 26})], line_spacing=1.1)


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
        _text(slide, left, top + height + Inches(0.08), width, Inches(0.9), [(caption, {"size": 16})], align=PP_ALIGN.CENTER, line_spacing=1.3)
    _text(slide, left, top + height + (Inches(1.0) if caption else Inches(0.05)), width, Inches(0.3), [(source, {"size": 9, "color": RGBColor(0x99, 0x99, 0x99)})], line_spacing=1.0)
    return box


def slide_title_hook(prs, hook, sub=None):
    s = _blank(prs)
    _text(s, M, Inches(2.4), W - 2 * M, Inches(1.4), [(hook, {"color": TITLE_RGB, "size": 40, "bold": True})], align=PP_ALIGN.CENTER, line_spacing=1.2)
    if sub:
        _text(s, M, Inches(3.9), W - 2 * M, Inches(0.8), [(sub, {"size": 20})], align=PP_ALIGN.CENTER)
    return s


def slide_image_text(prs, ttl, body_runs, caption=None):
    s = _blank(prs)
    title(s, ttl)
    img_w = Inches(5.6)
    placeholder_image(s, M, Inches(1.6), img_w, Inches(3.6), caption)
    _text(s, M + img_w + Inches(0.5), Inches(1.7), W - 2 * M - img_w - Inches(0.5), Inches(4.5), body_runs, size=20)
    return s


def slide_quote_translation(prs, ttl, en, ko_runs, flag_caption=None):
    s = _blank(prs)
    title(s, ttl)
    placeholder_image(s, M, Inches(1.9), Inches(2.6), Inches(1.7), flag_caption, source="이미지 출처: 공식 국기/로고 (기관 CI 가이드)")
    _text(s, M + Inches(3.2), Inches(1.7), W - 2 * M - Inches(3.2), Inches(1.6), [(en, {"size": 20})], size=20, line_spacing=1.4)
    _text(s, M + Inches(3.2), Inches(3.4), W - 2 * M - Inches(3.2), Inches(2.8), ko_runs, size=20)
    return s


def slide_two_images(prs, ttl, cap1, cap2, note_runs=None):
    s = _blank(prs)
    title(s, ttl)
    w = (W - 2 * M - Inches(0.4)) / 2
    placeholder_image(s, M, Inches(1.6), w, Inches(3.2), cap1)
    placeholder_image(s, M + w + Inches(0.4), Inches(1.6), w, Inches(3.2), cap2)
    if note_runs:
        _text(s, M, Inches(6.3), W - 2 * M, Inches(0.8), note_runs, size=18)
    return s


def slide_closing(prs, ttl, bullets, sources):
    s = _blank(prs)
    title(s, ttl)
    runs = []
    for i, b in enumerate(bullets):
        if i:
            runs.append("\n")
        runs.extend(b if isinstance(b, list) else [(b, {})])
    _text(s, M, Inches(1.7), W - 2 * M, Inches(3.8), runs, size=22, line_spacing=1.6)
    _text(s, M, Inches(6.4), W - 2 * M, Inches(0.9), [("출처: " + " · ".join(sources), {"size": 11, "color": RGBColor(0x77, 0x77, 0x77)})], line_spacing=1.2)
    return s


def add_notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


E = lambda t: (t, {"bold": True, "color": EMPH_RGB})  # noqa: E731
B = lambda t: (t, {"bold": True})  # noqa: E731


def build_prototype() -> pathlib.Path:
    """시제품: 2026-11-07 클립(스페인 열차 사고·유럽 철도 인프라) 구성을 5장으로 재현 — 레이아웃·토큰 검증용(제출본 아님)."""
    prs = new_deck()
    s1 = slide_title_hook(prs, "100년 된 장비를 아직도 쓰고 있는 유럽의 현실", "스페인 열차 참사, 왜 반복되는가")
    add_notes(s1, "훅: 질문형 + 의외의 숫자(100년). 시작 멘트 '한번 알아보도록 하겠습니다'. [시제품 — 사실 검증 전]")
    s2 = slide_two_images(prs, "사건 당일 같은 역에서 6분 간격으로 출발한 두 열차",
                          "오전 7시 54분 출발\n마드리드발 세비야행", "오전 8시 00분 출발\n마드리드발 세비야행",
                          [("1월 사고 당시 ", {}), E("46명이 사망"), ("하고 ", {}), E("292명이 부상"), ("당했다.", {})])
    add_notes(s2, "claim: 사망 46·부상 292 — T1(스페인 내무부/교통부 발표) 원문 확인 필요. 배지 [확인] 전까지 pending.")
    s3 = slide_image_text(prs, "이걸 전혀 파악하지 못한 안전 관리 시스템까지 총체적 난국",
                          [("원래는 전압 측정을 통해 문제가 있는 철로 구간이 자동으로 점검 대상에 등록되지만 ", {}),
                           B("현지 기술진은 해당 시스템에 문제가 많아 등록되지 않았다고 밝혔다."), ],
                          caption=None)
    add_notes(s3, "출처: 현지 보도(T3) 2건 교차 또는 ADIF 공식 발표(T1) 역추적. 단독이면 [OOO 단독 / 반론 대기].")
    s4 = slide_quote_translation(prs, "100년 넘은 유물을 그대로 활용하는 프랑스",
                                 "today's network is the fruit of more than 120 years of investment (생략)",
                                 [("프랑스 철도 신호소의 ", {}), E("3분의 1은 여전히 기계식 레버"), ("로 1930년대 기술을 사용한다. 프랑스 철도는 평균 30년 이상 되었고 일부 노선은 40년이 넘었다. ", {}),
                                  E("일부 장비들은 120년의 세월을 견뎠다.")],
                                 flag_caption="프랑스")
    add_notes(s4, "영문 원문 → 한글 번역 병기 패턴. 원문 출처(SNCF Réseau 보고서 p.?) locator 필수.")
    s5 = slide_closing(prs, "정리: 낡은 인프라, 비용의 문제인가 의지의 문제인가",
                       [[("유럽 철도는 ", {}), E("투자 부족"), ("보다 ", {}), E("유지보수 우선순위"), ("의 문제가 크다는 지적", {})],
                        [("중국은 2005년 독일에서 기술을 사서 ", {}), E("20년 만에 5만 km"), (" — 비교 대상이 바뀌었다", {})],
                        [("한국 철도는? → 다음 주제에서 ", {}), B("코레일 노후 차량 비율"), ("로 이어집니다", {})]],
                       ["스페인 교통부·ADIF 발표(T1)", "SNCF Réseau 연차보고서(T1)", "Reuters 2026-01(T3)", "中国国家铁路集团 2025 연보(T1)"])
    add_notes(s5, "마무리: 한 줄 회고 + 추측형 전망 + 다음 주제 브릿지('자, 좋습니다'). 숨김 슬라이드에 원문 캡처 첨부 예정.")
    DRAFTS.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DRAFTS / f"prototype_spain_rail_{ts}.pptx"
    prs.save(str(out))
    return out


SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def to_pdf_png(pptx: pathlib.Path) -> tuple[pathlib.Path | None, list[pathlib.Path]]:
    outdir = pptx.parent
    r = subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(pptx)], capture_output=True, text=True, timeout=180)
    pdf = pptx.with_suffix(".pdf")
    if not pdf.exists():
        print("PDF 변환 실패:", r.stderr[-300:], file=sys.stderr)
        return None, []
    pngs = []
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf))
        pngdir = outdir / (pptx.stem + "_png")
        pngdir.mkdir(exist_ok=True)
        for i in range(len(doc)):
            img = doc[i].render(scale=1.0).to_pil()
            p = pngdir / f"slide_{i+1:02d}.png"
            img.save(p)
            pngs.append(p)
    except Exception as e:  # noqa: BLE001
        print("PNG 렌더 실패:", e, file=sys.stderr)
    return pdf, pngs


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
