#!/usr/bin/env python3
"""덱 사양 → 초안 pptx(+ 출처 부록 · 시각물 출처·검증표 · 발표자 노트) → 파워포인트 PDF → 쪽별 PNG → 러닝시트 md+PDF.

결정적 코드다. 문장은 사양에 있는 것만 옮기고 새로 짓지 않는다. 숫자 검사는 spec.check 가 맡고, 통과하지 못한 사양은 만들지 않는다.
글은 어절 단위로 미리 줄을 나눠 줄바꿈을 넣고 글상자의 자동 줄바꿈은 끈다(파워포인트가 한글 낱말 가운데서 끊지 않게).
그림은 내려받지 않는다 — 회색 자리에 '무엇을 · 어느 공식 출처에서'만 적는다.

    python -m ozl.render build <사양.yaml>   # private/decks/drafts/<card_id>_<ts>/
"""
from __future__ import annotations

import datetime as dt
import math
import re
import pathlib
import subprocess
import sys
from dataclasses import dataclass, field

from lxml import etree
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from ozl.render import deck
from ozl.render import spec as S
from ozl.research import cards as C

ROOT = S.ROOT
DRAFTS = ROOT / "private" / "decks" / "drafts"
MD2PDF = pathlib.Path.home() / "Claude" / "tools" / "md2pdf.py"

EMU_IN = 914400
GREY = RGBColor(0x66, 0x66, 0x66)
LIGHT = RGBColor(0x88, 0x88, 0x88)
SW, SH = deck.W / EMU_IN, deck.H / EMU_IN           # 13.333 × 7.5 in
ML = deck.M / EMU_IN                               # 좌우 여백 0.96in
FOOT_TOP = 6.92                                    # 출처 각주 줄 윗변(in)
BODY_BOTTOM = 6.85                                 # 본문 글상자가 내려갈 수 있는 끝(in)
PAD = 0.05                                         # 글상자 안쪽 좌우 여백(in · deck._text 와 같다)
TABLE_SIZE = 22                                    # 비교표 글자 크기(pt) — 표 양식은 미확정(토큰 '미확정' 항목)
APPX_SIZE = 10                                     # 부록 표 글자 크기(pt)
NO_GRID_STYLE = "{5940675A-B579-460E-94D1-54222C63F5DA}"  # 파워포인트 '스타일 없음, 표 눈금' — 기본 파랑 표 스타일을 쓰지 않는다


def _in(emu) -> float:
    return emu / EMU_IN


# ── 배치 계획(검사와 생성이 같은 계획을 쓴다) ─────────────────────────────
@dataclass
class Para:
    text: str
    color: RGBColor = deck.BODY_RGB
    bold: bool = False
    emph: list[str] = field(default_factory=list)  # 이 낱말들은 빨강 굵게
    lines: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class Box:
    name: str
    left: float
    top: float
    width: float
    height: float
    paras: list[Para]
    size: float = deck.SIZE
    spacing: float = deck.LINE
    align: object = PP_ALIGN.LEFT
    max_lines: int | None = None

    @property
    def line_h(self) -> float:  # pt — 파워포인트 배수 줄 간격의 기준은 글자 크기의 1.2배
        return self.size * 1.2 * self.spacing

    def capacity(self) -> int:
        if self.max_lines is not None:
            return self.max_lines
        return max(1, int((self.height * 72 - 0.1 * 72) / self.line_h + 0.15))

    def layout(self) -> int:
        width_pt = (self.width - 2 * PAD) * 72 * 0.98  # 2% 여유 — 폰트 힌팅 차이로 줄 끝이 넘지 않게
        n = 0
        for p in self.paras:
            mask = [m or p.bold for m in S.emphasis_mask(p.text, p.emph)]
            p.lines = S.wrap(p.text, width_pt, self.size, mask) or [(0, 0)]
            n += len(p.lines)
        return n

    def problems(self) -> list[str]:
        out = []
        n = self.layout()
        width_pt = (self.width - 2 * PAD) * 72
        for p in self.paras:
            mask = [m or p.bold for m in S.emphasis_mask(p.text, p.emph)]
            for a, b in p.lines:
                wpt = sum(S.measure(p.text[i], self.size, mask[i]) for i in range(a, b))
                if wpt > width_pt:
                    out.append(f"{self.name}: 어절 '{p.text[a:b]}' 이 줄 폭보다 길다")
        if n > self.capacity():
            out.append(f"{self.name}: {n}줄 — 글상자에 {self.capacity()}줄까지 들어간다(줄 넘침)")
        return out


@dataclass
class Img:
    left: float
    top: float
    width: float
    height: float
    what: str
    source: str
    caption: str = ""
    kind: str = "slot"  # slot = 종전 회색 자리(image) · chart = charts.render_chart PNG · capture = 기록의 원문 화면 그림
    ref: str = ""       # capture 의 claim_id


@dataclass
class Table:
    left: float
    top: float
    width: float
    widths: list[float]
    header: list[str]
    rows: list[list[str]]
    size: float = TABLE_SIZE
    emph: list[str] = field(default_factory=list)
    max_bottom: float = BODY_BOTTOM
    words_whole: bool = False  # 어절이 칸 폭을 넘으면 실패시키고, 수동 어절 줄바꿈 뒤 자동 줄바꿈을 끈다
    free_cols: frozenset = frozenset()  # 예외 칸(주소): 파워포인트가 글자 단위로 접게 둔다

    def whole(self, j: int) -> bool:
        return self.words_whole and j not in self.free_cols

    def cell_width_pt(self, w: float) -> float:
        return (w - 0.3) * 72  # 칸 안쪽 여백 0.16in + 파워포인트 줄바꿈 여유

    def row_heights(self) -> list[float]:
        """행 높이(in) 어림 — 파워포인트는 글이 넘치면 행을 늘리므로 미리 세어 쪽을 넘는지 본다."""
        out = []
        for row in [self.header] + self.rows:
            n = 1
            for j, (txt, w) in enumerate(zip(row, self.widths)):
                width_pt = self.cell_width_pt(w)
                lines = 0
                for part in str(txt).split("\n"):
                    ls = S.wrap(part, width_pt, self.size) or [(0, 0)]
                    if self.whole(j) and not _has_url(part):
                        lines += len(ls)
                        continue
                    for a, b in ls:  # 공백 없는 긴 덩어리(주소)는 파워포인트가 글자 단위로 접는다
                        lines += max(1, math.ceil(S.measure(part[a:b], self.size) / width_pt))
                n = max(n, lines)
            out.append(n * self.size * 1.2 / 72 + 0.12)
        return out

    def problems(self, name="표") -> list[str]:
        out = []
        if self.words_whole:
            for row in [self.header] + self.rows:
                for j, (txt, w) in enumerate(zip(row, self.widths)):
                    if not self.whole(j):
                        continue
                    for word in str(txt).split():
                        if _is_url(word):
                            continue  # 주소는 낱말이 아니라 파워포인트가 글자 단위로 접게 둔다(그 칸만 자동 줄바꿈을 켠다)
                        bold = row is self.header
                        if S.measure(word, self.size, bold) > self.cell_width_pt(w):
                            out.append(f"{name}: 어절 '{word}' 이 칸 폭보다 길다(낱말이 끊긴다 — 칸 너비를 넓히거나 줄여 쓴다)")
        if out:
            return out
        h = sum(self.row_heights())
        if self.top + h > self.max_bottom + 0.01:
            return [f"{name}: 표 높이 {h:.2f}in — 쪽 아래로 넘친다({self.top + h:.2f} > {self.max_bottom:.2f}in)"]
        return []


def _is_url(word: str) -> bool:
    return word.startswith(("http://", "https://")) or "://" in word


def _has_url(text: str) -> bool:
    return any(_is_url(w) for w in str(text).split())


@dataclass
class Plan:
    boxes: list[Box] = field(default_factory=list)
    imgs: list[Img] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)


def _body_paras(items, emph) -> list[Para]:
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(Para(str(it.get("text", "")), deck.EMPH_RGB if it.get("red") else deck.BODY_RGB, bool(it.get("bold")), list(emph or [])))
        else:
            out.append(Para(str(it), emph=list(emph or [])))
    return out


def _title_box(sl) -> Box:
    left = _in(deck.TITLE_LEFT)
    return Box("제목", left, _in(deck.TITLE_TOP), SW - left - ML, _in(deck.px(60)), [Para(str(sl["title"]), deck.TITLE_RGB)], spacing=1.0, max_lines=1)


def _img(sl, left, top, width, height) -> Img | None:
    v = S.visual_of(sl)
    if v == "chart" and isinstance(sl["chart"], dict):
        ch = sl["chart"]
        return Img(left, top, width, height, str(ch.get("title", "")), str(ch.get("source", "")), kind="chart")
    if v == "capture":
        return Img(left, top, width, height, "원문 화면", "", kind="capture", ref=str(sl["capture"]).strip())
    im = sl.get("image")
    if not im or not isinstance(im, dict):
        return None
    return Img(left, top, width, height, str(im.get("what", "")), str(im.get("source", "")), str(im.get("caption") or ""))


def plan_slide(sl: dict) -> Plan:
    k = sl.get("kind")
    emph = sl.get("emphasis") or []
    p = Plan()
    img_l, img_t, img_w, img_h = ML, _in(deck.IMG_TOP), _in(deck.IMG_W), _in(deck.IMG_H)
    body_top = _in(deck.BODY_TOP)
    if k == "title_hook":
        p.boxes.append(Box("여는 제목", ML, 2.2, SW - 2 * ML, 2.0, [Para(str(sl["title"]), deck.TITLE_RGB, True, list(emph))], size=40, spacing=1.2, align=PP_ALIGN.CENTER))
        if sl.get("sub"):
            p.boxes.append(Box("부제", ML, 4.35, SW - 2 * ML, 1.3, [Para(str(sl["sub"]), emph=list(emph))], align=PP_ALIGN.CENTER))
        return p
    p.boxes.append(_title_box(sl))
    if k == "image_text":
        im = _img(sl, img_l, img_t, img_w, img_h)
        if im:
            p.imgs.append(im)
            x = img_l + img_w + _in(deck.GAP)
        else:
            x = ML
        p.boxes.append(Box("본문", x, body_top, SW - ML - x, BODY_BOTTOM - body_top, _body_paras(sl.get("body"), emph)))
    elif k == "quote_translation":
        im = _img(sl, img_l, img_t, 2.6, 1.7)
        x = ML + 3.2 if im else ML
        if im:
            p.imgs.append(im)
        paras = [Para(str(sl["en"]), emph=[])] + [Para(str(sl["ko"]), deck.EMPH_RGB, False, list(emph))] + _body_paras(sl.get("body"), emph)
        p.boxes.append(Box("원문·번역", x, body_top, SW - ML - x, BODY_BOTTOM - body_top, paras))
    elif k == "number":
        im = _img(sl, img_l, img_t, img_w, img_h)
        num = sl["number"]
        if im:
            p.imgs.append(im)
            x, align, top = img_l + img_w + _in(deck.GAP), PP_ALIGN.LEFT, body_top
        else:
            x, align, top = ML, PP_ALIGN.CENTER, 2.1
        w = SW - ML - x
        size = 44 if im else 60  # 그림 옆 글 기둥은 좁아 한 단 작게
        p.boxes.append(Box("큰 숫자", x, top, w, 1.25, [Para(str(num["value"]), deck.EMPH_RGB, True)], size=size, spacing=1.0, align=align, max_lines=1))
        y = top + 1.35
        if num.get("label"):
            p.boxes.append(Box("숫자 설명", x, y, w, 1.0, [Para(str(num["label"]), emph=list(emph))], spacing=1.2, align=align, max_lines=2))
            y += 1.1
        if sl.get("body"):
            p.boxes.append(Box("본문", x, y, w, BODY_BOTTOM - y, _body_paras(sl.get("body"), emph), align=align))
    elif k == "compare_table":
        t = sl["table"]
        header = [str(x) for x in t.get("header") or []]
        rows = [[str(x) for x in r] for r in t.get("rows") or []]
        rel = t.get("widths") or [1] * len(header)
        tw = SW - 2 * ML
        widths = [tw * r / sum(rel) for r in rel]
        tb = Table(ML, 1.75, tw, widths, header, rows, emph=list(emph), words_whole=True)
        p.tables.append(tb)
        if sl.get("body"):
            y = tb.top + sum(tb.row_heights()) + 0.2
            tb.max_bottom = BODY_BOTTOM - 0.6
            p.boxes.append(Box("표 아래 글", ML, y, tw, max(0.6, BODY_BOTTOM - y), _body_paras(sl.get("body"), emph), spacing=1.2))
    elif k == "quote_line":
        q = sl["quote"]
        p.boxes.append(Box("인용", ML + 0.5, 2.3, SW - 2 * ML - 1.0, 2.4, [Para(str(q["text"]), deck.EMPH_RGB, True, [])], size=36, spacing=1.3, align=PP_ALIGN.CENTER))
        if q.get("by"):
            p.boxes.append(Box("인용 출처", ML + 0.5, 4.85, SW - 2 * ML - 1.0, 0.8, [Para(str(q["by"]))], size=20, spacing=1.2, align=PP_ALIGN.CENTER))
    elif k == "closing":
        p.boxes.append(Box("본문", ML, body_top, SW - 2 * ML, BODY_BOTTOM - body_top, _body_paras(sl.get("body"), emph)))
    return p


def layout_problems(sl: dict) -> list[str]:
    if sl.get("kind") not in S.KINDS:
        return []
    out = []
    try:
        pl = plan_slide(sl)
        for b in pl.boxes:
            out += b.problems()
        for t in pl.tables:
            out += t.problems()
    except (KeyError, TypeError, AttributeError, ValueError, ZeroDivisionError, OverflowError) as e:  # 삼키지 않는다 — 검사를 통과한 사양이 빌드에서 깨지면 안 된다
        return [f"배치 실패({type(e).__name__}: {e}) — 필수 칸이 빠졌거나 모양이 틀렸다"]
    if sl.get("kind") == "title_hook" and sl.get("image"):
        out.append("여는 제목 장에는 그림 자리를 두지 않는다(image_text 로 따로 둔다)")
    return out


# ── pptx 쓰기 ────────────────────────────────────────────────────────────
def _style_run(r, size, bold, color):
    f = r.font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = color
    deck.set_run_font(r, deck.FONT)


def _write_para(para, p: Para, size: float):
    mask = [m or p.bold for m in S.emphasis_mask(p.text, p.emph)]
    emph_mask = S.emphasis_mask(p.text, p.emph)
    for li, (a, b) in enumerate(p.lines):
        if li:
            para.add_line_break()
        i = a
        while i < b:
            j = i
            while j < b and emph_mask[j] == emph_mask[i]:
                j += 1
            r = para.add_run()
            r.text = p.text[i:j]
            _style_run(r, size, mask[i], deck.EMPH_RGB if emph_mask[i] else p.color)
            i = j


def draw_box(slide, b: Box):
    b.layout()
    tb = slide.shapes.add_textbox(Inches(b.left), Inches(b.top), Inches(b.width), Inches(b.height))
    tb.name = b.name
    tf = tb.text_frame
    tf.word_wrap = False  # 줄은 어절 단위로 이미 나눴다
    tf.margin_left = tf.margin_right = Inches(PAD)
    for i, p in enumerate(b.paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = b.align
        para.line_spacing = b.spacing
        _write_para(para, p, b.size)
    return tb


def draw_img(slide, im: Img):
    box = slide.shapes.add_shape(1, Inches(im.left), Inches(im.top), Inches(im.width), Inches(im.height))
    box.name = "그림 자리"
    box.fill.solid()
    box.fill.fore_color.rgb = deck.PLACEHOLDER_RGB
    box.line.color.rgb = RGBColor(0xBB, 0xBB, 0xBB)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, (txt, sz, bold) in enumerate([("그림 자리", 14, True), (im.what, 12, False), ("출처: " + im.source, 10, False)]):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = PP_ALIGN.CENTER
        r = para.add_run()
        r.text = txt
        _style_run(r, sz, bold, LIGHT if i == 0 else GREY)
    if im.caption:
        cb = Box("캡션", im.left, im.top + im.height + 0.08, im.width, 0.8, [Para(im.caption)], size=deck.CAPTION_SIZE, spacing=1.2, align=PP_ALIGN.CENTER)
        draw_box(slide, cb)


VISUALS_DIR = "visuals"   # 산출 폴더 안 — 렌더한 차트 PNG
CREDIT_SIZE = 11          # 원문 캡처 아래 출처 줄(pt)


def chart_png_size(im: Img) -> tuple[int, int]:
    """그림 자리와 같은 가로세로 비의 픽셀 크기. 왼쪽 그림 자리(charts.SLOT_W_IN × SLOT_H_IN)면 charts.DEFAULT_SIZE_PX 그대로."""
    from ozl.render import charts as G
    if abs(im.width - G.SLOT_W_IN) < 1e-6 and abs(im.height - G.SLOT_H_IN) < 1e-6:
        return G.DEFAULT_SIZE_PX
    w = G.DEFAULT_SIZE_PX[0]
    return w, round(w * im.height / im.width)


def capture_credit(c: dict) -> str:
    """원문 캡처 아래 출처 줄: 원문 주소의 호스트만(검사가 붙이는 구조 글 — 부록의 링크·기준 시점 칸처럼 숫자 대조에서 뺀다).
    받은 시각은 화면에서 읽을 일이 없어 부록 「시각물 출처·검증표」가 맡는다(2026-11-13 구성 평가)."""
    import urllib.parse
    cap = ((c.get("verification") or {}).get("capture") or {}) if isinstance(c.get("verification"), dict) else {}
    url = str(cap.get("final_url") or cap.get("url") or (c.get("source") or {}).get("url") or "")
    host = urllib.parse.urlsplit(url).hostname or url
    return "원문: " + host


def fit_inside(img_w: int, img_h: int, box_w: float, box_h: float) -> tuple[float, float, float, float]:
    """(왼쪽 띄움, 위 띄움, 폭, 높이) in — 비율을 지켜 자리 안쪽에 맞춘다(잘리지 않는다)."""
    k = min(box_w / img_w, box_h / img_h)
    w, h = img_w * k, img_h * k
    return (box_w - w) / 2, (box_h - h) / 2, w, h


def draw_visual(slide, im: Img, png: pathlib.Path | None, credit: str = ""):
    """chart·capture 그림을 그림 자리에 넣는다. png 가 없으면(초안 모드 그림 대기) 회색 자리에 대기 문구를 적는다."""
    if png is None:
        draw_img(slide, Img(im.left, im.top, im.width, im.height, f"그림 대기 — {im.ref.rsplit('-', 1)[-1]} 원문 화면 그림이 아직 없다", credit or "원문 캡처"))
        return None
    if im.kind == "chart":
        pic = slide.shapes.add_picture(str(png), Inches(im.left), Inches(im.top), Inches(im.width), Inches(im.height))
        pic.name = "차트"
        return pic
    from PIL import Image
    with Image.open(png) as g:
        pw, ph = g.size
    dx, dy, w, h = fit_inside(pw, ph, im.width, im.height)
    pic = slide.shapes.add_picture(str(png), Inches(im.left + dx), Inches(im.top + dy), Inches(w), Inches(h))
    pic.name = "원문 캡처"
    pic.line.color.rgb = RGBColor(0xBB, 0xBB, 0xBB)
    pic.line.width = Pt(0.75)
    if credit:
        size = CREDIT_SIZE
        while size > 8 and S.measure(credit, size) > (im.width - 2 * PAD) * 72:
            size -= 1
        b = Box("원문 캡처 출처", im.left, im.top + dy + h + 0.06, im.width, 0.35, [Para(credit, GREY)], size=size, spacing=1.0, align=PP_ALIGN.CENTER, max_lines=1)
        draw_box(slide, b)
    return pic


def _no_grid(tbl):
    tblPr = tbl._tbl.tblPr
    tblPr.set("firstRow", "0")
    tblPr.set("bandRow", "0")
    sid = tblPr.find(qn("a:tableStyleId"))
    if sid is None:
        sid = etree.SubElement(tblPr, qn("a:tableStyleId"))
    sid.text = NO_GRID_STYLE


def draw_table(slide, t: Table, header_rgb=deck.EMPH_RGB):
    heights = t.row_heights()
    gf = slide.shapes.add_table(len(t.rows) + 1, len(t.header), Inches(t.left), Inches(t.top), Inches(t.width), Inches(sum(heights)))
    gf.name = "표"
    tbl = gf.table
    _no_grid(tbl)
    for j, w in enumerate(t.widths):
        tbl.columns[j].width = Inches(w)
    for i, h in enumerate(heights):
        tbl.rows[i].height = Inches(h)
    for i, row in enumerate([t.header] + t.rows):
        for j, txt in enumerate(row):
            cell = tbl.cell(i, j)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            if i == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(0xF2, 0xF2, 0xF2)
            tf = cell.text_frame
            tf.word_wrap = not t.whole(j) or _has_url(str(txt))  # 어절 줄바꿈을 미리 넣은 칸은 자동 줄바꿈을 끈다(주소 칸·주소가 든 칸만 예외)
            width_pt = t.cell_width_pt(t.widths[j])
            for k, part in enumerate(str(txt).split("\n")):
                para = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                para.line_spacing = 1.0
                p = Para(part, header_rgb if i == 0 else deck.BODY_RGB, i == 0, [] if i == 0 else t.emph)
                mask = [m or p.bold for m in S.emphasis_mask(p.text, p.emph)]
                p.lines = S.wrap(p.text, width_pt, t.size, mask) or [(0, 0)]
                # 문단 끝 표시의 글자 크기도 표 크기로 — 비워 두면 기본 18pt 가 빈 칸의 행 높이를 키워 표가 쪽 아래로 넘친다
                para._p.get_or_add_endParaRPr().set("sz", str(int(round(t.size * 100))))
                if not part:
                    continue
                _write_para(para, p, t.size)
    return gf


def _footnote(slide, text: str):
    b = Box("출처 각주", ML, FOOT_TOP, SW - 2 * ML, 0.5, [Para(text, GREY)], size=11, spacing=1.0, max_lines=2)
    draw_box(slide, b)


footnote_text = S.footnote_text  # 각주 글을 만드는 함수는 하나 — 검사(spec.check)와 생성이 같이 쓴다


def notes_text(sl: dict, claims: dict, stage: str) -> str:
    lines = [f"[{stage} · {sl.get('kind')}]"]
    if S.visual_of(sl) == "chart":
        ch = sl["chart"]
        lines.append(f"그림: 차트({ch.get('kind')}) · 쓴 기록 {', '.join(map(str, ch.get('claims') or []))} — " + chart_limit(ch, claims))
    elif S.visual_of(sl) == "capture":
        lines.append(f"그림: 원문 캡처 {sl['capture']} — {capture_credit(claims.get(str(sl['capture'])) or {})}")
    ids = [str(x) for x in sl.get("claim_ids") or []]
    if ids:
        lines.append("claim_id: " + ", ".join(ids))
        for cid in ids:
            c = claims.get(cid) or {}
            lines.append(f"- {cid}: {c.get('text', '')} (출처 {(c.get('source') or {}).get('url', '')})")
    for cv in sl.get("conversions") or []:
        lines.append(f"환산: '{cv.get('shown')}' ← {cv.get('claim_id')} '{cv.get('source')}' — {cv.get('basis')}")
    if sl.get("notes"):
        lines.append("메모: " + str(sl["notes"]).strip())
    if sl.get("spoken"):
        lines.append("말로만: " + str(sl["spoken"]).strip())
    if sl.get("transition"):
        lines.append("넘어가기: " + str(sl["transition"]).strip())
    return "\n".join(lines)


CHART_LIMIT = "값이 사본에 있는지만 프로그램이 봤다. 칸과 값의 짝은 문장 대조에서 본다."
CHART_LIMIT_NO_COPY = "값이 기록의 observed·text 에 있는지만 프로그램이 봤다(사본 없는 기록). 칸과 값의 짝은 문장 대조에서 본다."


def chart_limit(ch: dict, claims: dict) -> str:
    """러닝시트·노트의 차트 줄 — 무엇을 프로그램이 봤고 무엇을 못 봤는가."""
    has_copy = any(S.copy_text(claims.get(str(c)) or {})[0] for c in ch.get("claims") or [])
    return (CHART_LIMIT if has_copy else CHART_LIMIT_NO_COPY) + (" 세로축이 0에서 시작하지 않는다(y_from_zero: false)." if ch.get("y_from_zero") is False else "")


# ── 부록 ────────────────────────────────────────────────────────────────
_URL = re.compile(r"\(?https?://[^\s)]+\)?")


def locator_text(loc: str) -> str:
    """부록 '문서 위치' 칸 — 기록의 primary_doc_locator 에 섞인 주소는 빼고(주소는 링크 칸에만) 남은 설명만. 기록 파일은 고치지 않는다."""
    t = _URL.sub("", str(loc or ""))
    t = re.sub(r"\s*[·,]\s*(?=[·,]|$)", "", t)
    t = re.sub(r"·(?=\S)", "· ", t)  # 가운뎃점으로만 이어진 긴 덩어리를 어절로 나눈다(부록 칸의 어절 검사)
    t = re.sub(r"\s{2,}", " ", t).strip(" ·,")
    return t


def source_rows(spec: dict, claims: dict, card: dict, pending=None) -> list[list[str]]:
    """pending: 초안 모드의 {쪽: [claim_id]} (또는 claim_id 집합). 검증 대기 기록의 행과, 검증 대기 쪽에서 인용한 보도 행에 [검증 대기]를 붙인다."""
    pend_pages = set(pending) if isinstance(pending, dict) else set()
    pending_ids = {c for v in pending.values() for c in v} if isinstance(pending, dict) else set(pending or ())
    """출처 부록 행 = 인용된 클레임마다 [클레임 · 기관 · 문서 위치 · 링크 · 기준 시점 · 쓰인 쪽] + 카드 sources 중 refs 로 쓴 보도."""
    pages: dict[str, list[int]] = {}
    ref_pages: dict[str, list[int]] = {}
    for i, sl in enumerate(spec.get("slides") or [], 1):
        for cid in sl.get("claim_ids") or []:
            pages.setdefault(str(cid), []).append(i)
        for ref in sl.get("refs") or []:
            ref_pages.setdefault(str(ref), []).append(i)

    def key(cid):
        m = C.CLAIM_ID.match(cid)
        return (m.group(1), int(m.group(2))) if m else (cid, 0)

    rows = []
    for cid in sorted(pages, key=key):
        c = claims.get(cid) or {}
        src = c.get("source") or {}
        chk = c.get("checks") or {}
        short = cid.rsplit("-", 1)[-1] + (f"\n{PENDING_MARK}" if cid in (pending_ids or set()) else "")
        rows.append([short, str(src.get("publisher") or ""), locator_text(chk.get("primary_doc_locator")), str(src.get("url") or ""),
                     str(chk.get("base_period") or "").replace("~", " ~ "), ", ".join(map(str, pages[cid]))])   # 범위는 띄어 쓴다(칸에서 줄을 바꿀 수 있게)
        for x in c.get("cross_check") or []:  # 교차 출처도 부록에 — 화면에서 '다른 보도'로 인용한 문장을 거슬러 갈 수 있게
            if isinstance(x, dict) and x.get("url"):
                rows.append([short.split("\n")[0] + " 교차" + (f"\n{PENDING_MARK}" if cid in (pending_ids or set()) else ""),
                             str(x.get("publisher") or ""), "교차 출처", str(x["url"]), "", ", ".join(map(str, pages[cid]))])
    by_name = {s.get("name"): s for s in spec.get("press_sources") or [] if isinstance(s, dict)}
    by_name.update({s.get("name"): s for s in card.get("sources") or []})  # 카드 sources 가 우선
    for ref, pg in ref_pages.items():
        s = by_name.get(ref) or {}
        mark = f"\n{PENDING_MARK}" if pend_pages & set(pg) else ""
        doc = s.get("tier") in S.DOC_TIERS   # 각주(footnote_text)와 같은 기준 — 기업·기관 문서는 보도로 부르지 않는다
        rows.append([("자료" if doc else "보도") + mark, ref,
                     "검증 기록 없음 — " + ("문서 인용(숫자 근거 아님)" if doc else "보도 인용"), str(s.get("url") or ""), "", ", ".join(map(str, pg))])
    return rows


def visual_rows(spec: dict, pending: dict[int, list[str]] | None = None) -> list[list[str]]:
    """그림 자리마다 한 행. 초안 모드에서 원 슬라이드가 검증 대기면 쪽 칸에 [검증 대기]를 붙인다(부록에서도 표시가 빠지지 않게)."""
    rows = []
    for i, sl in enumerate(spec.get("slides") or [], 1):
        im = sl.get("image")
        if not im:
            continue
        rows.append([str(i) + (f"\n{PENDING_MARK}" if i in (pending or {}) else ""), str(im.get("what", "")), str(im.get("source", "")), "", "", "" if im.get("map") else "해당 없음"])
    return rows


def _fetched(at) -> str:
    """받은 시각 '2026-11-13T08:02:23+09:00' → '2026-11-13 08:02'(한 어절이 칸 폭을 넘지 않게)."""
    t = str(at or "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", t)
    return f"{m.group(1)} {m.group(2)}" if m else t


CAPTURE_VIEW = {"text_passage": "원문의 글을 옮겨 그림", "pdf_band": "PDF 쪽에서 자름", "pdf_page": "PDF 쪽 전체"}


def visual_check_rows(spec: dict, claims: dict, pending=None, views: dict[int, str] | None = None) -> list[list[str]]:
    """차트·원문 캡처마다 한 행. 그림 안에서 뺀 내부 정보(기록 번호·주소·받은 시각·사본 해시)를 이 표가 맡는다.
    views = 빌드 때 실제로 그린 그림의 종류(쪽 → evidence_image 의 view). 없으면(검사 때) 사본 종류로 어림한다."""
    rows = []
    for i, sl in enumerate(spec.get("slides") or [], 1):
        v = S.visual_of(sl)
        pg = str(i) + (f"\n{PENDING_MARK}" if i in (pending or {}) else "")
        if v == "chart" and isinstance(sl["chart"], dict):
            ch = sl["chart"]
            ids = ", ".join(str(c).rsplit("-", 1)[-1] for c in ch.get("claims") or [])
            has_copy = any(S.copy_text(claims.get(str(c)) or {})[0] for c in ch.get("claims") or [])
            # '확인'은 사람이 대조한 일에만 쓴다(완성본 평가 기준 가8) — 프로그램과 에이전트가 한 일은 '대조'로 적는다.
            scope = ("값이 사본에 있는지는 프로그램이 대조" if has_copy else "값이 기록 observed·text 에 있는지는 프로그램이 대조") + \
                " · 칸과 값의 짝은 문장 대조에서 봄" + (" · 세로축이 0에서 시작하지 않음" if ch.get("y_from_zero") is False else "")
            rows.append([pg, f"차트({'선' if ch.get('kind') == 'line' else '막대'})", f"{ch.get('title', '')} · 기록 {ids}",
                         f"단위 {ch.get('unit', '')} · 기간 {ch.get('period', '')}", "", scope])
        elif v == "capture":
            cid = str(sl["capture"]).strip()
            c = claims.get(cid) or {}
            cap = ((c.get("verification") or {}).get("capture") or {}) if isinstance(c.get("verification"), dict) else {}
            url = str(cap.get("final_url") or cap.get("url") or (c.get("source") or {}).get("url") or "")
            view = (views or {}).get(i) or ("pdf_band" if cap.get("kind") == "pdf" else "text_passage")
            label = CAPTURE_VIEW.get(view, view)
            if view == "text_passage" and cap.get("kind") == "pdf":
                label = "PDF 의 글을 옮겨 그림"
            sha = str(cap.get("sha256") or "")[:12]
            rows.append([pg, "원문 캡처", f"기록 {cid.rsplit('-', 1)[-1]}", url, f"{_fetched(cap.get('fetched_at'))} · sha256 {sha}", label])
    return rows


PENDING_MARK = "[검증 대기]"
WAIT_MARK = "[그림 대기]"   # 초안 모드: capture 기록의 원문 화면 그림이 아직 없다
SRC_HEADER = ["클레임", "기관", "문서 위치", "링크", "기준 시점", "쪽"]
SRC_WIDTHS = [1.0, 1.9, 3.0, 3.3, 1.2, 1.01]
VIS_HEADER = ["쪽", "무엇을", "어느 공식 출처에서", "역검색", "400% 확대", "지도 표기"]
VIS_WIDTHS = [1.2, 3.3, 3.9, 1.0, 1.0, 1.01]
VC_HEADER = ["쪽", "종류", "무엇을", "원문 주소 · 단위·기간", "받은 시각 · 사본", "검증 범위 · 그림"]
VC_WIDTHS = [0.8, 1.1, 2.5, 3.3, 1.7, 2.01]
VC_FOOT = "원문 캡처 그림에는 대목 글만 둔다 — 기록 번호·원문 주소·받은 시각·사본 sha256 은 이 표가 맡는다. 차트의 값은 사본(또는 기록)에 그 표기로 있는지만 프로그램이 봤다."


def appendix_tables(spec: dict, claims: dict, card: dict | None, pending=None, views=None) -> list[tuple]:
    """부록 표 (제목, 머리, 폭, 행) — 검사와 빌드가 같은 목록을 쓴다. 시각물 표: 회색 그림 자리(image)가 있거나 차트·캡처가 없으면 종전 표,
    차트·원문 캡처가 있으면 그 검증표."""
    out = [("부록 · 출처", SRC_HEADER, SRC_WIDTHS, source_rows(spec, claims, card or {}, pending))]
    img_rows = visual_rows(spec, pending)
    vc_rows = visual_check_rows(spec, claims, pending, views)
    if img_rows or not vc_rows:
        out.append(("부록 · 시각물 출처·검증표", VIS_HEADER, VIS_WIDTHS, img_rows))
    if vc_rows:
        out.append(("부록 · 시각물 출처·검증표(차트·원문 캡처)", VC_HEADER, VC_WIDTHS, vc_rows))
    return out


def _appx_table(header, rows, widths, top, bottom) -> Table:
    free = frozenset({SRC_HEADER.index("링크")}) if header is SRC_HEADER else frozenset({VC_HEADER.index("원문 주소 · 단위·기간")}) if header is VC_HEADER else frozenset()
    return Table(ML, top, sum(widths), widths, header, rows, size=APPX_SIZE, max_bottom=bottom, words_whole=True, free_cols=free)


def paginate(header, rows, widths, top=1.45, bottom=BODY_BOTTOM) -> list[Table]:
    out, cur = [], []
    for r in rows:
        t = _appx_table(header, cur + [r], widths, top, bottom)
        if cur and any("넘친다" in e for e in t.problems()):
            out.append(_appx_table(header, cur, widths, top, bottom))
            cur = [r]
        else:
            cur.append(r)
    if cur or not out:
        out.append(_appx_table(header, cur, widths, top, bottom))
    return out


# 부록 출처 표의 칸 구분 — 한곳에 모아 둔다.
#   대조 칸: 수량 주장이 실릴 수 있는 일반 글. 그 기록의 observed·text 에 같은 숫자가 있어야 한다.
#   구조 칸: 원문 안의 자리·형식을 가리키는 표기라 숫자가 기록 본문에 있을 수 없다 — 숫자 검사에서 뺀다.
#            (문서 위치 = primary_doc_locator 의 쪽·조·문단·표 번호. 쪽 = 쓰인 슬라이드 번호. 링크 = 주소. 기준 시점 = base_period.
#             클레임 = 약칭. '교차 출처(T3)'·'검증 기록 없음 — 보도 인용' 같은 생성 문구.)
#   보도 행의 이름은 본편 각주(footnote_text)에서, 시각물 표의 무엇을·출처는 본편 그림 자리(visible_text)에서 이미 검사한다.
APPX_CHECKED = ("기관", "교차 출처 기관")
APPX_STRUCTURAL = ("클레임", "문서 위치", "링크", "기준 시점", "쪽", "생성 문구")


def appendix_number_errors(spec: dict, claims: dict, card: dict | None) -> list[str]:
    """부록에 찍히는 대조 칸(APPX_CHECKED)의 숫자 검사. 구조 칸(APPX_STRUCTURAL)은 보지 않는다."""
    out = []
    idents = spec.get("identifiers") or []
    cids: dict[str, None] = {}
    for sl in spec.get("slides") or []:
        for cid in sl.get("claim_ids") or []:
            cids[str(cid)] = None
    for cid in cids:
        c = claims.get(cid) or {}
        pool = S.source_tokens(c)
        cells = [("기관", (c.get("source") or {}).get("publisher"))]
        cells += [("교차 출처 기관", x.get("publisher")) for x in c.get("cross_check") or [] if isinstance(x, dict)]
        for label, txt in cells:
            assert label in APPX_CHECKED
            toks = [t.canon for t in S.N.claim_tokens(_URL.sub("", S._s(txt)), idents)]
            miss = [t for t in dict.fromkeys(toks) if t not in pool]
            if miss:
                out.append(f"부록·출처 {cid.rsplit('-', 1)[-1]} {label}: 숫자 {miss} 가 그 기록의 observed·text 에 없다 — '{S._s(txt)[:60]}'")
    return out


def appendix_problems(spec: dict, claims: dict, card: dict | None, pending=None) -> list[str]:
    """부록 표 검사 — 일반 글 칸의 숫자(appendix_number_errors) · 어절이 칸 폭을 넘으면 실패(주소만 예외) · 한 행이 한 쪽을 넘쳐도 실패."""
    out = appendix_number_errors(spec, claims, card)
    for title, header, widths, rows in appendix_tables(spec, claims, card, pending):
        title = title.replace(" · ", "·")
        for t in paginate(header, rows, widths):
            for e in t.problems(title):
                if e not in out:
                    out.append(e)
    return out


# ── 덱 ──────────────────────────────────────────────────────────────────

def draw_pending(slide, ids: list[str]):
    """아직 '확인'도 「원문 일치」도 아닌 기록을 인용한 슬라이드 — 오른쪽 위에 빨간 테두리 딱지(초안 모드 전용)."""
    waits = [str(c)[len(S.WAIT_IMAGE):] for c in ids if str(c).startswith(S.WAIT_IMAGE)]  # 원문 화면 그림 대기(capture)
    ids = list(dict.fromkeys("보도" if str(c).startswith("보도:") else str(c).split(" ")[0] for c in ids if not str(c).startswith(S.WAIT_IMAGE)))  # 'c13 교차' → 'c13' · 사양 보도 → '보도' · 중복 제거
    parts = [PENDING_MARK + " " + ", ".join(c.rsplit("-", 1)[-1] for c in ids)] if ids else []
    if waits:
        parts.append(WAIT_MARK + " " + ", ".join(c.rsplit("-", 1)[-1] for c in dict.fromkeys(waits)))
    label = " · ".join(parts)
    w = min(SW - 2 * ML, max(3.3, S.measure(label, 14, True) / 72 + 0.4))  # 글이 딱지 밖으로 나가지 않게 폭을 맞춘다
    box = slide.shapes.add_shape(1, Inches(SW - ML - w), Inches(0.12), Inches(w), Inches(0.42))
    box.name = "검증 대기"
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xFF, 0xF2, 0xCC)
    box.line.color.rgb = deck.EMPH_RGB
    box.line.width = Pt(2)
    tf = box.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para = tf.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    r = para.add_run()
    r.text = label
    _style_run(r, 14, True, deck.EMPH_RGB)


def render_visuals(spec: dict, claims: dict, vis_dir: pathlib.Path) -> dict[int, tuple[pathlib.Path | None, str, str]]:
    """쪽 번호 → (넣을 PNG | None, 출처 줄). chart 와 capture 모두 vis_dir 에 그때 새로 그린다(capture 는 해시가 확인된 사본에서 — capture_png)."""
    from ozl.render import charts as G
    out: dict[int, tuple[pathlib.Path | None, str]] = {}
    for idx, sl in enumerate(spec.get("slides") or [], 1):
        v = S.visual_of(sl)
        if v not in ("chart", "capture"):
            continue
        ims = [im for im in plan_slide(sl).imgs if im.kind == v]
        if not ims:
            continue
        im = ims[0]
        if v == "chart":
            vis_dir.mkdir(parents=True, exist_ok=True)
            png = G.render_chart(sl["chart"], vis_dir / f"{idx:02d}_chart.png", size_px=chart_png_size(im), slot_width_in=im.width)
            out[idx] = (png, "", "chart")
        else:
            c = claims.get(im.ref) or {}
            png, view = capture_png(c, vis_dir / f"{idx:02d}_capture.png", chart_png_size(im), sl.get("capture_focus"))
            out[idx] = (png, capture_credit(c), view)
    return out


def capture_png(c: dict, out: pathlib.Path, size_px: tuple[int, int], focus=None) -> tuple[pathlib.Path | None, str]:
    """원문 캡처를 빌드 때 새로 그린다 — 기록이 받아들여지고(acceptance_error 빈 문자열), 해시가 확인된 사본에서, 대조한 자리(match.target)의 그림.
    기록의 verification.image 는 쓰지 않는다(아무 PNG 로 바꿔 넣을 수 있다). 그리지 못하면 None(그림 대기 자리)."""
    from ozl.research import capture as K
    if not c or S.acceptance_error(c):
        return None, ""
    target = S.capture_target(c)
    src = C.copy_source(c)
    if not target or not src["ok"]:
        return None, ""
    cap = src["cap"]
    r = K.evidence_image(str(c.get("claim_id")), src["path"], src["kind"], src["text"], str(c.get("observed") or ""), target["offset"],
                         S.capture_meta(cap), out, size_px=size_px, focus=focus)
    return (pathlib.Path(r["path"]), str(r.get("view") or "")) if r.get("path") else (None, "")


def visual_label(sl: dict, waiting: bool = False) -> str:
    v = S.visual_of(sl)
    if v == "chart":
        return f"차트({'선' if sl['chart'].get('kind') == 'line' else '막대'})"
    if v == "capture":
        return f"원문 캡처 {str(sl['capture']).rsplit('-', 1)[-1]}" + (" " + WAIT_MARK if waiting else "")
    if v == "image":
        return "그림 자리(회색)"
    return "없음"


def build_pptx(spec: dict, claims: dict, card: dict, out: pathlib.Path, pending: dict[int, list[str]] | None = None) -> dict:
    prs = deck.new_deck()
    pending = pending or {}
    labels = spec.get("source_labels") or {}
    visuals = render_visuals(spec, claims, out.parent / VISUALS_DIR)
    for idx, sl in enumerate(spec["slides"], 1):
        s = deck._blank(prs)
        pl = plan_slide(sl)
        for im in pl.imgs:
            if im.kind in ("chart", "capture") and idx in visuals:
                draw_visual(s, im, *visuals[idx][:2])
            else:
                draw_img(s, im)
        for b in pl.boxes:
            draw_box(s, b)
        for t in pl.tables:
            draw_table(s, t)
        ft = footnote_text(sl, claims, card, labels)
        if ft:
            _footnote(s, ft)
        nt = notes_text(sl, claims, str(sl.get("stage")))
        if idx in pending:
            draw_pending(s, pending[idx])
            recs = [c for c in pending[idx] if not str(c).startswith(S.WAIT_IMAGE)]
            waits = [c[len(S.WAIT_IMAGE):] for c in pending[idx] if str(c).startswith(S.WAIT_IMAGE)]
            nt = (f"{PENDING_MARK} 검증 전·대기 폴더 기록: {', '.join(recs)}\n" if recs else "") + \
                 (f"{WAIT_MARK} 원문 화면 그림이 아직 없다: {', '.join(waits)}\n" if waits else "") + nt
        s.notes_slide.notes_text_frame.text = nt
    n_main = len(spec["slides"])
    appx = []
    views = {i: v[2] for i, v in visuals.items() if v[2] and v[2] != "chart"}
    for title, header, widths, rows in appendix_tables(spec, claims, card, pending, views):
        pages = paginate(header, rows, widths)
        for k, t in enumerate(pages, 1):
            s = deck._blank(prs)
            marked = [r[0].split("\n")[0] for r in t.rows if PENDING_MARK in r[0]]
            if marked:  # 이 쪽 표에 검증 대기 행이 있으면 쪽 딱지도 붙인다(출처 표 = 클레임 약칭 · 시각물 표 = 원 슬라이드 번호)
                draw_pending(s, marked if header is SRC_HEADER else [f"{m}쪽" for m in marked])
            ttl = title + (f" ({k}/{len(pages)})" if len(pages) > 1 else "")
            draw_box(s, _title_box({"title": ttl}))
            draw_table(s, t, header_rgb=deck.BODY_RGB)
            if header is VC_HEADER:
                _footnote(s, VC_FOOT)
            if header is VIS_HEADER:
                _footnote(s, "역검색(Google Lens·TinEye) · 400% 확대 검수 · 지도 동해·독도·국경 표기는 사람이 확인하고 칸을 채운다. 공식 보도자료실·프레스킷·기관 CI·라이선스 스톡만 쓴다(방법론 5절).")
            s.notes_slide.notes_text_frame.text = f"[부록] {title} — 검증 기록(claims)과 사양의 그림 자리에서 자동으로 만들었다."
            appx.append(ttl)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return {"main": n_main, "appendix": appx, "total": n_main + len(appx)}


def running_sheet(spec: dict, card: dict, claims: dict, ts: str, pending: dict[int, list[str]] | None = None) -> str:
    pending = pending or {}
    slides = spec["slides"]
    total = sum(int(sl.get("seconds") or 0) for sl in slides)
    why = str(spec.get("why_this") or "").strip()
    cited = {str(c) for sl in slides for c in sl.get("claim_ids") or []}
    machine = sorted(c for c in cited if C.grade_label(claims.get(c) or {}) == C.GRADE_MACHINE)
    basis = ("숫자는 전부 사람이 대조한 검증 기록(claim_id)에서만" if not machine else
             f"숫자는 전부 검증 기록(claim_id)에서만 — 사람 대조 '{C.GRADE_HUMAN}' {len(cited) - len(machine)}건 · 기계 대조 「{C.GRADE_MACHINE}」 {len(machine)}건"
             f"({', '.join(c.rsplit('-', 1)[-1] for c in machine)} · 사람이 원문을 본 것은 아니다)")
    lines = [
        f"# 러닝시트 — {card.get('card_id', spec.get('card_id'))}",
        "",
        f"왜 이 소재를 골랐는가: {why if why else '＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿ (지원자가 한 줄로 쓴다)'}",
        "",
        f"초안 {ts} · 본편 {len(slides)}장 · 예상 발화 {total // 60}분 {total % 60}초 · " + (basis if not pending else f"**초안 모드 — [검증 대기] 기록을 인용한 쪽 {len(pending)}장({', '.join(map(str, pending))}쪽). 엄격 모드를 통과하기 전에는 제출·발행하지 않는다**") + " · 말은 진행자 말투로 바꿔 읽어도 된다(수치·인용·단서는 그대로).",
        "",
        "## 장별 진행",
        "",
        "| 쪽 | 단계 | 제목 | 말로만 할 핵심 문장 | 넘어가는 멘트 | 초 | 근거 | 그림 |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def cell(x):
        return str(x or "").replace("|", "／").replace("\n", " ").strip()

    t = 0
    for i, sl in enumerate(slides, 1):
        sec = int(sl.get("seconds") or 0)
        t += sec
        ids = ", ".join(str(c).rsplit("-", 1)[-1] + (f"「{C.GRADE_MACHINE}」" if str(c) in machine else "") for c in sl.get("claim_ids") or []) + (" [검증 대기]" if any(not str(c).startswith(S.WAIT_IMAGE) for c in pending.get(i, [])) else "")
        waiting = any(str(c).startswith(S.WAIT_IMAGE) for c in pending.get(i, []))
        lines.append(f"| {i} | {cell(sl.get('stage'))} | {cell(sl.get('title'))} | {cell(sl.get('spoken'))} | {cell(sl.get('transition'))} | {sec} | {ids} | {cell(visual_label(sl, waiting))} |")
    charts_ = [(i, sl["chart"]) for i, sl in enumerate(slides, 1) if S.visual_of(sl) == "chart"]
    if charts_:
        lines += ["", "## 차트", ""]
        for i, ch in charts_:
            lines.append(f"- {i}쪽 차트({'선' if ch.get('kind') == 'line' else '막대'}) · 쓴 기록 "
                         f"{', '.join(str(c).rsplit('-', 1)[-1] for c in ch.get('claims') or [])}: {chart_limit(ch, claims)}")
    lines += ["", "## 단계별 시간", "", "| 단계 | 장수 | 초 |", "|---|---|---|"]
    agg: dict[str, list[int]] = {}
    order: list[str] = []
    for sl in slides:
        st = str(sl.get("stage"))
        if st not in agg:
            agg[st] = [0, 0]
            order.append(st)
        agg[st][0] += 1
        agg[st][1] += int(sl.get("seconds") or 0)
    for st in order:
        lines.append(f"| {st} | {agg[st][0]} | {agg[st][1]} |")
    if spec.get("qa"):
        lines += ["", "## 예상 돌발 질문", ""]
        for q in spec["qa"]:
            lines.append(f"- **{cell(q.get('q'))}** — {cell(q.get('a'))}")
    lines += ["", "## 쓰지 않는 말(카드 리스크에서)", ""]
    for r in card.get("risks") or []:
        lines.append(f"- {cell(r)}")
    return "\n".join(lines) + "\n"


def resolve_card(card_id) -> dict:
    """card_id 는 형식이 맞고 카드 정본이 실제로 있어야 한다(없는 카드를 빈 카드로 대신하지 않는다)."""
    if not card_id or not C.CARD_ID.match(str(card_id)):
        raise SystemExit(f"card_id '{card_id}' 가 카드 ID 형식(YYYY-MM-DD-am|pm|wk-NN)이 아니다")
    if not C.card_path(str(card_id)).exists():
        raise SystemExit(f"카드 {card_id} 가 없다({C.card_path(str(card_id))})")
    return C.load_card(str(card_id))


def out_paths(card_id: str, ts: str, draft: bool) -> tuple[pathlib.Path, pathlib.Path]:
    stem = f"{card_id}_{ts}" + ("_draft" if draft else "")
    raw = DRAFTS / stem
    outdir = raw.resolve()
    if outdir.parent != DRAFTS.resolve():
        raise SystemExit(f"출력 경로 {outdir} 가 {DRAFTS} 바로 아래가 아니다")
    if raw.is_symlink() or raw.exists():
        raise SystemExit(f"출력 폴더 {raw} 가 이미 있다(링크 포함) — 덮어쓰지 않는다")
    return outdir, outdir / f"{stem}.pptx"


def safe_new_file(outdir: pathlib.Path, path: pathlib.Path) -> pathlib.Path:
    """최종 출력 파일은 새 폴더 바로 아래의 새 파일이어야 한다. 이미 있거나(링크 포함) 실제 경로가 폴더 밖이면 거부한다."""
    if path.is_symlink() or path.exists():
        raise SystemExit(f"출력 파일 {path} 가 이미 있다(링크 포함) — 덮어쓰지 않는다")
    if path.resolve().parent != outdir.resolve():
        raise SystemExit(f"출력 파일 {path} 의 실제 경로가 {outdir} 밖이다")
    return path


def build(spec_path: pathlib.Path, export: bool = True, draft: bool = False, claims_dirs=()) -> dict:
    spec_path = pathlib.Path(spec_path).resolve()
    sp = S.load_spec(spec_path)
    card = resolve_card(sp.get("card_id"))
    claims, staged = S.load_claims(S.cited_ids(sp), claims_dirs)
    rep = S.check(sp, claims, S.load_template(), card, layout_problems, draft=draft, staged=staged, appendix_fn=appendix_problems)
    if not rep.ok:
        raise SystemExit("사양 검사 실패 — build 하지 않는다:\n" + "\n".join(rep.errors))
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir, pptx = out_paths(str(sp["card_id"]), ts, draft)
    outdir.mkdir(parents=False, exist_ok=False)
    md = outdir / f"running_sheet_{ts}{'_draft' if draft else ''}.md"
    for f in (pptx, md, pptx.with_suffix(".pdf"), md.with_suffix(".pdf"), outdir / (pptx.stem + "_png"), outdir / VISUALS_DIR):
        safe_new_file(outdir, f)
    info = build_pptx(sp, claims, card, pptx, rep.pending if draft else None)
    md.write_text(running_sheet(sp, card, claims, ts, rep.pending if draft else None), encoding="utf-8")
    info.update(dir=str(outdir), pptx=str(pptx), md=str(md), warnings=rep.warnings)
    if draft:
        info["pending_slides"] = len(rep.pending)
    if export:
        pdf, pngs = deck.to_pdf_png(pptx)
        info.update(pdf=str(pdf) if pdf else None, pngs=len(pngs))
        if MD2PDF.exists():
            r = subprocess.run(["python3", str(MD2PDF), str(md), "--theme", "doc", "--footer-title"], capture_output=True, text=True, timeout=300)
            info["sheet_pdf"] = str(md.with_suffix(".pdf")) if md.with_suffix(".pdf").exists() else f"실패: {(r.stderr or r.stdout)[-300:]}"
    return info
