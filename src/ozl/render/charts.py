#!/usr/bin/env python3
"""차트 사양(dict) → PNG. 덱 생성기의 그림 자리에 넣을 선·막대 차트를 그린다.

결정적 코드다. 글은 사양에 있는 것만 옮기고 새로 짓지 않는다. 숫자 꼬리표는 입력 표기를 그대로 찍는다
(반올림·쉼표 추가·단위 환산을 하지 않는다 — 숫자 검사기는 화면의 수량이 검증 기록의 표기와 글자 그대로 같기를 요구한다).

사양 모양
    {"kind": "line" | "bar",
     "title": "한 문장 제목",
     "unit": "달러/배럴",                     # 세로축 단위(필수)
     "period": "2098-01 ~ 2098-12",           # 기간 또는 기준 시점(필수)
     "series": [{"name": "가상 지표", "points": [["2098-01", 12.5], ["2098-12", "20.40", "20.40"]]}],
     "source": "가상 기관, 가상 통계",          # 그림 아래 출처 줄(필수)
     "claims": ["2099-01-02-am-01-c1"],       # 이 차트가 쓴 검증 기록 식별자(필수, 하나 이상)
     "transform": "",                         # 선택: 환산했으면 환산식을 글로(출처 줄 옆에 적힌다)
     "highlight": ["2098-12"],                # 선택: 값 꼬리표를 붙일 가로축 칸(모든 계열에 붙는다)
     "y_from_zero": True}                     # 선택(기본 True). 막대는 언제나 0에서 시작한다

점 = [가로축 칸, 값] 또는 [가로축 칸, 값, 표시 문자열]. 값은 수(int·float) 또는 수를 적은 문자열("20.40" · "1,234").
꼬리표 문자열은 표시 문자열 > 값이 문자열이면 그 문자열 > int 면 str(값) 순으로 정한다. float 는 파이썬이 끝자리 0을 지우므로
(20.40 → '20.4') 꼬리표를 붙일 float 점에는 표시 문자열(또는 문자열 값)을 요구한다.

판형: 기본 그림 크기는 덱의 왼쪽 그림 자리(deck.IMG_W × deck.IMG_H, 4.20×4.12in)와 같은 가로세로 비다.
글자 크기는 그 자리에 넣었을 때 슬라이드 위의 pt 로 정한다(slot_width_in 으로 다른 폭의 자리에 맞출 수 있다).

못 하는 것
  - 세로축 눈금 숫자는 matplotlib 이 정한 값이다(꼬리표가 아니다). chart_quantities 에 넣지 않는다.
  - 표시 문자열이 '1억 2,345' 처럼 한글 크기 단위를 쓰면 값과 같은지 검사하지 못한다(수만으로 된 표기만 대조한다).

    from ozl.render import charts
    errs = charts.validate_chart(spec)
    charts.render_chart(spec, "out.png")
    charts.chart_quantities(spec)   # 그림에 글자로 찍히는 수량 문자열 → 숫자 검사기에 넘긴다
"""
from __future__ import annotations

import math
import pathlib
import re
from decimal import Decimal, InvalidOperation

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.ft2font import FT2Font  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from ozl.render import deck  # noqa: E402
from ozl.render import numbers as N  # noqa: E402

EMU_IN = 914400
SLOT_W_IN = deck.IMG_W / EMU_IN            # 4.20in — build.plan_slide 의 왼쪽 그림 자리
SLOT_H_IN = deck.IMG_H / EMU_IN            # 4.12in
DEFAULT_SIZE_PX = (1200, round(1200 * SLOT_H_IN / SLOT_W_IN))  # 같은 비 · 슬라이드 위에서 약 286dpi

KINDS = ("line", "bar")
REQUIRED = ("kind", "title", "unit", "period", "series", "source", "claims")
OPTIONAL = ("transform", "highlight", "y_from_zero")
MAX_SERIES = 3

# 색: 덱 강조색(#C00000)을 첫 계열로 두고, 색각 이상에서도 밝기·색상으로 갈리는 진한 파랑·중간 회색을 더한다.
# 선은 색 말고 선 모양·표식으로도 가른다(실선·파선·점선 / 원·네모·세모).
ACCENT = "#C00000"
SERIES_COLORS = (ACCENT, "#1F4E79", "#7F7F7F")
LINE_STYLES = ("-", "--", ":")
MARKERS = ("o", "s", "^")
MUTED_BAR = "#BFBFBF"     # 막대 한 계열에 꼬리표가 있을 때 나머지 막대
TEXT = "#000000"
SUBTLE = "#595959"
FOOT = "#808080"
GRID = "#E3E3E3"
ZERO = "#404040"

# 글자 크기(pt · 그림을 자리에 넣었을 때 슬라이드 위의 크기). 덱 본문 26pt · 캡션 20pt · 출처 각주 약 10pt
TITLE_PT = 15
SUB_PT = 11
TICK_PT = 10
LABEL_PT = 11
LEGEND_PT = 10
FOOT_PT = 8.5
NOTE_PT = 8.5

# 덱 글꼴 '맑은 고딕'(deck.FONT)에 가까운 순서. Office 묶음에 든 맑은 고딕이 있으면 그것, 없으면 macOS 기본 한글 고딕.
_FONT_CANDIDATES = (
    ("/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts/malgun.ttf", "malgunbd.ttf"),
    ("/Applications/Microsoft Word.app/Contents/Resources/DFonts/malgun.ttf", "malgunbd.ttf"),
    ("/Applications/Microsoft Excel.app/Contents/Resources/DFonts/malgun.ttf", "malgunbd.ttf"),
    ("~/Library/Fonts/malgun.ttf", "malgunbd.ttf"),
    ("/Library/Fonts/malgun.ttf", "malgunbd.ttf"),
    ("C:/Windows/Fonts/malgun.ttf", "malgunbd.ttf"),
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", None),
    ("~/Library/Fonts/NanumSquareR.otf", "NanumSquareB.otf"),
    ("/Library/Fonts/NanumSquareR.otf", "NanumSquareB.otf"),
)
_FALLBACK_FAMILY = "DejaVu Sans"  # matplotlib 동봉 — 한글 글꼴에 없는 기호(− 등)를 받는다
_font_cache: dict | None = None


# ── 글꼴 ─────────────────────────────────────────────────────────────────
def _has_hangul(path: str) -> bool:
    try:
        return FT2Font(path).get_char_index(ord("가")) != 0
    except Exception:  # 읽지 못하는 글꼴 파일은 후보에서 뺀다
        return False


def _register(path: str) -> str:
    font_manager.fontManager.addfont(path)
    return font_manager.FontProperties(fname=path).get_name()


def pick_font() -> dict:
    """{'family': 이름, 'path': 파일, 'bold_path': 파일|None, 'faces': [FT2Font…]} — 한글 글리프가 있는 첫 후보.
    후보가 하나도 없으면 설치된 글꼴 가운데 한글이 있는 것을 찾고, 그것도 없으면 RuntimeError(네모 글자를 그리지 않는다)."""
    global _font_cache
    if _font_cache is not None:
        return _font_cache
    chosen = None
    for reg, bold in _FONT_CANDIDATES:
        p = pathlib.Path(reg).expanduser()
        if p.is_file() and _has_hangul(str(p)):
            b = p.with_name(bold) if bold else None
            chosen = (str(p), str(b) if b and b.is_file() and _has_hangul(str(b)) else None)
            break
    if chosen is None:
        for f in font_manager.findSystemFonts():
            if _has_hangul(f):
                chosen = (f, None)
                break
    if chosen is None:
        raise RuntimeError("한글 글리프가 있는 글꼴을 찾지 못했다 — 맑은 고딕이나 다른 한글 글꼴을 설치하라")
    family = _register(chosen[0])
    if chosen[1]:
        _register(chosen[1])
    fallback = font_manager.findfont(font_manager.FontProperties(family=_FALLBACK_FAMILY), fallback_to_default=True)
    _font_cache = {"family": family, "path": chosen[0], "bold_path": chosen[1],
                   "faces": [FT2Font(chosen[0]), FT2Font(fallback)]}
    return _font_cache


def _missing_glyphs(text: str) -> list[str]:
    faces = pick_font()["faces"]
    out = []
    for ch in set(text):
        if ch.isspace():
            continue
        if all(f.get_char_index(ord(ch)) == 0 for f in faces):
            out.append(ch)
    return sorted(out)


# ── 값 읽기 ──────────────────────────────────────────────────────────────
_PLAIN_NUM = re.compile(r"^[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?$")


def _parse_value(v) -> float | None:
    """수 또는 수를 적은 문자열 → float. 읽지 못하면 None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, str):
        s = v.strip()
        if not s or not _PLAIN_NUM.match(s) or not re.search(r"\d", s):
            return None
        try:
            f = float(Decimal(s.replace(",", "").replace("−", "-")))
        except InvalidOperation:
            return None
        return f if math.isfinite(f) else None
    return None


def _label(pt) -> str | None:
    """점의 꼬리표 문자열(입력 표기 그대로). float 값에 표시 문자열이 없으면 None."""
    if len(pt) >= 3 and isinstance(pt[2], str):
        return pt[2]
    v = pt[1]
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    return None


_DISPLAY = re.compile(r"^([+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*([^\d]*)$")


def _decimal_of(v) -> Decimal | None:
    try:
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return Decimal(v)
        if isinstance(v, float):
            return Decimal(repr(v))
        if isinstance(v, str):
            return Decimal(v.strip().replace(",", "").replace("−", "-"))
    except InvalidOperation:
        return None
    return None


def _display_matches(display: str, value) -> bool | None:
    """표시 문자열이 '[부호]숫자(쉼표 허용)[.소수]' 뒤에 숫자 없는 단위 꼬리만 붙은 꼴(4명 · 123.93 · 1,644,131 · -70.9%)이면
    그 수가 좌표값과 Decimal 로 정확히 같은지. 그 꼴이 아니면(1억 2,345 · 약 4명) None — 검사가 오류로 본다(표시 문자열로 실제 값을 숨기지 못하게)."""
    m = _DISPLAY.match(display.strip())
    if not m:
        return None
    try:
        shown = Decimal(m.group(1).replace(",", "").replace("−", "-"))
    except InvalidOperation:
        return None
    want = _decimal_of(value)
    if want is None:
        return None
    return shown == want


# ── 검사 ─────────────────────────────────────────────────────────────────
def _nonempty_str(x) -> bool:
    return isinstance(x, str) and x.strip() != ""


def validate_chart(spec) -> list[str]:
    """사양의 문제를 한글 문구 목록으로 돌려준다. 빈 목록이면 그릴 수 있다."""
    if not isinstance(spec, dict):
        return ["차트 사양은 dict 여야 한다"]
    errs: list[str] = []
    for k in REQUIRED:
        if k not in spec:
            errs.append(f"필수 칸 '{k}' 이 없다")
    for k in spec:
        if k not in REQUIRED and k not in OPTIONAL:
            errs.append(f"모르는 칸 '{k}' — 오타인지 확인하라(쓸 수 있는 칸: {', '.join(REQUIRED + OPTIONAL)})")
    kind = spec.get("kind")
    if "kind" in spec and kind not in KINDS:
        errs.append(f"kind 는 line 또는 bar 여야 한다(받은 값: {kind!r})")
    for k, what in (("title", "제목"), ("unit", "단위"), ("period", "기간"), ("source", "출처")):
        if k in spec and not _nonempty_str(spec[k]):
            errs.append(f"{what}('{k}')이 비었거나 문자열이 아니다")
    if "transform" in spec and not isinstance(spec["transform"], str):
        errs.append("환산식('transform')은 문자열이어야 한다(환산하지 않았으면 빈 문자열)")
    if "claims" in spec:
        cl = spec["claims"]
        if not isinstance(cl, list) or not cl:
            errs.append("쓴 검증 기록('claims')이 하나 이상 있어야 한다")
        elif not all(_nonempty_str(c) for c in cl):
            errs.append("검증 기록 식별자('claims')에 비었거나 문자열이 아닌 것이 있다")
    yz = spec.get("y_from_zero", True)
    if not isinstance(yz, bool):
        errs.append("y_from_zero 는 true 또는 false 여야 한다")
    elif kind == "bar" and yz is False:
        errs.append("막대 차트는 세로축이 언제나 0에서 시작한다 — y_from_zero: false 를 쓸 수 없다")

    xs_all: list[list[str]] = []
    if "series" in spec:
        series = spec["series"]
        if not isinstance(series, list) or not series:
            errs.append("계열('series')이 비었다")
            series = []
        elif len(series) > MAX_SERIES:
            errs.append(f"계열은 {MAX_SERIES}개까지다(받은 수: {len(series)})")
        names = []
        for si, s in enumerate(series, 1):
            tag = f"계열 {si}"
            if not isinstance(s, dict):
                errs.append(f"{tag}: dict 여야 한다")
                continue
            if not _nonempty_str(s.get("name")):
                errs.append(f"{tag}: 이름('name')이 비었다")
            else:
                tag = f"계열 '{s['name']}'"
                names.append(s["name"])
            extra = set(s) - {"name", "points"}
            if extra:
                errs.append(f"{tag}: 모르는 칸 {sorted(extra)}")
            pts = s.get("points")
            if not isinstance(pts, list) or not pts:
                errs.append(f"{tag}: 점('points')이 없다")
                continue
            if kind == "line" and len(pts) < 2:
                errs.append(f"{tag}: 선 차트는 점이 둘 이상이어야 한다(점 {len(pts)}개)")
            xs = []
            for pi, pt in enumerate(pts, 1):
                if not isinstance(pt, (list, tuple)) or len(pt) not in (2, 3):
                    errs.append(f"{tag} 점 {pi}: [가로축 칸, 값] 또는 [가로축 칸, 값, 표시 문자열] 꼴이어야 한다")
                    continue
                x, v = pt[0], pt[1]
                if not _nonempty_str(x):
                    errs.append(f"{tag} 점 {pi}: 가로축 칸이 비었거나 문자열이 아니다")
                else:
                    xs.append(x)
                fv = _parse_value(v)
                if fv is None:
                    errs.append(f"{tag} 점 {pi}({x}): 값 {v!r} 이 수가 아니다")
                if len(pt) == 3:
                    if not _nonempty_str(pt[2]):
                        errs.append(f"{tag} 점 {pi}({x}): 표시 문자열이 비었거나 문자열이 아니다")
                    elif fv is not None:
                        same = _display_matches(pt[2], v)
                        if same is None:
                            errs.append(f"{tag} 점 {pi}({x}): 표시 문자열 '{pt[2]}' 은 [부호]숫자(쉼표)[.소수] 뒤에 숫자 없는 단위 꼬리만 붙은 꼴이어야 한다"
                                        " — 값과 같은지 판정할 수 없다")
                        elif not same:
                            errs.append(f"{tag} 점 {pi}({x}): 표시 문자열 '{pt[2]}' 이 값 {v!r} 과 다르다")
            if len(set(xs)) != len(xs):
                errs.append(f"{tag}: 가로축 칸이 겹친다")
            xs_all.append(xs)
        if len(set(names)) != len(names):
            errs.append("계열 이름이 겹친다")
        if len(xs_all) > 1:
            lens = [len(x) for x in xs_all]
            if len(set(lens)) > 1:
                errs.append(f"계열마다 점 수가 다르다({lens}) — 같은 가로축 칸을 같은 순서로 적어야 한다")
            elif any(x != xs_all[0] for x in xs_all[1:]):
                errs.append("계열마다 가로축 칸 또는 그 순서가 다르다")

    hl = spec.get("highlight", [])
    if not isinstance(hl, list) or not all(_nonempty_str(h) for h in hl):
        errs.append("꼬리표 칸('highlight')은 가로축 칸 문자열의 목록이어야 한다")
    elif xs_all:
        known = set().union(*map(set, xs_all))
        for h in hl:
            if h not in known:
                errs.append(f"꼬리표 칸 '{h}' 이 가로축에 없다")
        if not errs:
            for s in spec["series"]:
                for pt in s["points"]:
                    if pt[0] in hl and _label(pt) is None:
                        errs.append(f"계열 '{s['name']}' 점 {pt[0]}: 꼬리표를 붙일 소수 값은 표시 문자열(셋째 칸)이나 문자열 값으로 적어야 한다"
                                    f" — {pt[1]!r} 을 그대로 찍으면 원문 표기와 달라질 수 있다")
    return errs


# ── 그림에 찍히는 글 ─────────────────────────────────────────────────────
def _source_line(spec) -> str:
    line = f"출처: {spec['source'].strip()}"
    tr = (spec.get("transform") or "").strip()
    if tr:
        line += f" · 환산: {tr}"
    return line


def _sub_line(spec) -> str:
    return f"단위: {spec['unit'].strip()} · 기간: {spec['period'].strip()}"


def _labels(spec) -> list[tuple[int, int, str]]:
    """(계열 번호, 점 번호, 꼬리표 문자열) — 꼬리표 칸에 든 점만."""
    hl = set(spec.get("highlight") or [])
    out = []
    for si, s in enumerate(spec["series"]):
        for pi, pt in enumerate(s["points"]):
            if pt[0] in hl:
                out.append((si, pi, _label(pt)))
    return out


def _drawn_texts(spec) -> list[str]:
    """꼬리표를 뺀, 그림에 글자로 찍히는 사양 글(눈금 숫자·고정 문구 제외)."""
    texts = [spec["title"], _sub_line(spec), _source_line(spec)]
    multi = len(spec["series"]) > 1
    for s in spec["series"]:
        if multi:
            texts.append(s["name"])
    texts += [pt[0] for pt in spec["series"][0]["points"]]
    return texts


def chart_quantities(spec) -> list[str]:
    """그림에 글자로 찍히는 수량 문자열: 사양 글(제목·단위·기간·출처·환산·계열 이름·가로축 칸)에서 numbers 판독부가 수량·기간·수량
    낱말로 읽은 표기(달력 꼴은 빼고, 조각은 넣는다) + 꼬리표 문자열(입력 표기 그대로). 눈금 숫자는 넣지 않는다.
    사양이 검사를 통과하지 못하면 ValueError."""
    errs = validate_chart(spec)
    if errs:
        raise ValueError("차트 사양 오류: " + " / ".join(errs))
    out: list[str] = []
    for t in _drawn_texts(spec):
        norm = N.normalize(t)
        for tok in N.claim_tokens(norm):
            out.append(norm[tok.start:tok.end])
    out += [lab for _, _, lab in _labels(spec)]
    return out


# ── 그리기 ───────────────────────────────────────────────────────────────
def _text_w(fig, renderer, s: str, size: float, bold: bool = False) -> float:
    t = fig.text(0, 0, s, fontsize=size, fontweight="bold" if bold else "normal")
    w = t.get_window_extent(renderer).width
    t.remove()
    return w


def _wrap(fig, renderer, text: str, size: float, max_px: float, bold: bool = False) -> list[str]:
    """어절 단위로 줄을 나눈다. 한 어절이 줄보다 길면 글자 단위로 끊는다."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        cand = f"{cur} {word}" if cur else word
        if _text_w(fig, renderer, cand, size, bold) <= max_px:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in word:
            if cur and _text_w(fig, renderer, cur + ch, size, bold) > max_px:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
    if cur:
        lines.append(cur)
    return lines or [""]


def _fmt_tick(x, _pos) -> str:
    if abs(x) < 1e-12:
        return "0"
    return f"{x:,.6f}".rstrip("0").rstrip(".")


def render_chart(spec, out_path, size_px: tuple[int, int] = DEFAULT_SIZE_PX, slot_width_in: float = SLOT_W_IN) -> pathlib.Path:
    """사양을 검사하고 PNG 를 쓴다. 검사 오류나 글꼴에 없는 글자가 있으면 ValueError(그리지 않는다).
    size_px = (가로, 세로) 픽셀. slot_width_in = 이 그림이 놓일 슬라이드 위 자리의 폭(in) — 글자 pt 의 기준."""
    errs = validate_chart(spec)
    if errs:
        raise ValueError("차트 사양 오류: " + " / ".join(errs))
    w_px, h_px = int(size_px[0]), int(size_px[1])
    if w_px < 200 or h_px < 200:
        raise ValueError(f"그림 크기가 너무 작다({w_px}×{h_px}px)")
    font = pick_font()
    labels = _labels(spec)
    missing = _missing_glyphs("".join(_drawn_texts(spec) + [lab for *_, lab in labels]))
    if missing:
        raise ValueError(f"글꼴에 없는 글자가 있다(네모로 찍힌다): {' '.join(missing)}")

    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    dpi = w_px / slot_width_in
    rc = {"font.family": [font["family"], _FALLBACK_FAMILY], "axes.unicode_minus": False,
          "svg.fonttype": "none", "figure.facecolor": "white"}
    with plt.rc_context(rc):
        fig = plt.figure(figsize=(w_px / dpi, h_px / dpi), dpi=dpi)
        try:
            _draw(fig, spec, labels, w_px, h_px)
            fig.savefig(out, dpi=dpi, facecolor="white")
        finally:
            plt.close(fig)
    return out


def _draw(fig, spec, labels, W: int, H: int) -> None:
    r = fig.canvas.get_renderer()
    pt2px = fig.dpi / 72
    pad = 0.035 * W                  # 좌우 바깥 여백(px)
    inner = W - 2 * pad
    kind = spec["kind"]
    series = spec["series"]
    xs = [pt[0] for pt in series[0]["points"]]
    vals = [[_parse_value(pt[1]) for pt in s["points"]] for s in series]
    multi = len(series) > 1

    # 위: 제목 · 단위/기간 · (범례)
    y = H - 0.03 * H
    for line in _wrap(fig, r, spec["title"].strip(), TITLE_PT, inner, bold=True):
        fig.text(pad / W, y / H, line, fontsize=TITLE_PT, fontweight="bold", color=TEXT, va="top", ha="left")
        y -= TITLE_PT * 1.3 * pt2px
    y -= 0.15 * TITLE_PT * pt2px
    for line in _wrap(fig, r, _sub_line(spec), SUB_PT, inner):
        fig.text(pad / W, y / H, line, fontsize=SUB_PT, color=SUBTLE, va="top", ha="left")
        y -= SUB_PT * 1.3 * pt2px
    legend_top = y - 0.25 * SUB_PT * pt2px
    if multi:
        y = legend_top - LEGEND_PT * 1.9 * pt2px
    y -= 0.6 * SUB_PT * pt2px
    axes_top = y

    # 아래: 출처 줄
    foot_lines = _wrap(fig, r, _source_line(spec), FOOT_PT, inner)
    yb = 0.025 * H
    for line in reversed(foot_lines):
        fig.text(pad / W, yb / H, line, fontsize=FOOT_PT, color=FOOT, va="bottom", ha="left")
        yb += FOOT_PT * 1.3 * pt2px
    foot_top = yb + 0.5 * FOOT_PT * pt2px

    ax = fig.add_axes((0.15, foot_top / H + 0.1, 0.8, max(0.1, axes_top / H - foot_top / H - 0.1)))
    idx = list(range(len(xs)))
    hl_by_series: dict[int, dict[int, str]] = {}
    for si, pi, lab in labels:
        hl_by_series.setdefault(si, {})[pi] = lab
    handles = []

    if kind == "line":
        for si, (s, v) in enumerate(zip(series, vals)):
            (h,) = ax.plot(idx, v, color=SERIES_COLORS[si], linestyle=LINE_STYLES[si], linewidth=2.2,
                           marker=MARKERS[si], markersize=3.5 if len(idx) > 6 else 5, label=s["name"], zorder=3)
            handles.append(h)
            for pi in hl_by_series.get(si, {}):
                ax.plot([pi], [v[pi]], marker=MARKERS[si], markersize=7, color=SERIES_COLORS[si], zorder=4)
        ax.set_xlim(-0.4, len(idx) - 0.6)
    else:
        n = len(series)
        width = 0.8 / n
        single_hl = n == 1 and bool(hl_by_series)
        for si, (s, v) in enumerate(zip(series, vals)):
            pos = [i - 0.4 + width * (si + 0.5) for i in idx]
            if single_hl:
                colors = [ACCENT if i in hl_by_series.get(0, {}) else MUTED_BAR for i in idx]
            else:
                colors = SERIES_COLORS[si]
            h = ax.bar(pos, v, width=width * 0.88, color=colors, label=s["name"], zorder=3)
            handles.append(h)
        ax.set_xlim(-0.6, len(idx) - 0.4)

    # 세로축 범위
    allv = [x for v in vals for x in v]
    lo, hi = min(allv), max(allv)
    yz = spec.get("y_from_zero", True)
    if yz or kind == "bar":
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    head = 0.16 if labels else 0.06
    if yz or kind == "bar":
        span = (hi - lo) or 1.0
        yhi = hi + span * head if hi > 0 else 0.0
        ylo = lo - span * head if lo < 0 else 0.0
        if yhi == ylo:
            yhi = 1.0
    else:
        span = (hi - lo) or (abs(hi) * 0.1 or 1.0)
        yhi, ylo = hi + span * max(head, 0.08), lo - span * max(head, 0.08)
    ax.set_ylim(ylo, yhi)
    if kind == "bar" or ylo < 0 < yhi:
        ax.axhline(0, color=ZERO, linewidth=0.9, zorder=2)

    # 꼬리표: 막대는 막대 끝 바깥, 선은 가운데 점이면 위(여러 계열이면 낮은 쪽은 아래), 처음·끝 점이면 점 옆에 둔다
    end_anns: list[tuple] = []   # (annotation, 점 번호, 글 폭 px)
    gap_pt = 4
    for si, pi, lab in labels:
        v = vals[si][pi]
        style = dict(fontsize=LABEL_PT, fontweight="bold", zorder=5, textcoords="offset points", annotation_clip=False)
        if kind == "line":
            color = SERIES_COLORS[si]
            if pi in (0, len(idx) - 1):
                right = pi == len(idx) - 1
                a = ax.annotate(lab, (pi, v), xytext=(7 if right else -7, 0), color=color,
                                ha="left" if right else "right", va="center", **style)
                a.set_in_layout(False)  # 자리는 _fit_end_labels 가 가로축 범위로 따로 잡는다
                end_anns.append((a, pi, _text_w(fig, r, lab, LABEL_PT, bold=True)))
                continue
            above = True
            if multi:
                others = [vals[o][pi] for o in range(len(series)) if o != si]
                above = v >= max(others)
            ax.annotate(lab, (pi, v), xytext=(0, gap_pt + 2 if above else -gap_pt - 2), color=color,
                        ha="center", va="bottom" if above else "top", **style)
        else:
            n = len(series)
            x = pi - 0.4 + (0.8 / n) * (si + 0.5)
            color = ACCENT if n == 1 else SERIES_COLORS[si]
            ax.annotate(lab, (x, v), xytext=(0, gap_pt if v >= 0 else -gap_pt), color=color,
                        ha="center", va="bottom" if v >= 0 else "top", **style)

    # 축 꾸밈: 가로 눈금선만 옅게, 테두리는 아래만
    ax.grid(axis="y", color=GRID, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#BFBFBF")
    ax.spines["bottom"].set_visible(not (kind == "bar"))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_tick))
    ax.tick_params(axis="y", length=0, labelsize=TICK_PT, labelcolor=SUBTLE, pad=4)
    ax.tick_params(axis="x", length=3 if kind == "line" else 0, color="#BFBFBF", labelsize=TICK_PT, labelcolor=SUBTLE)

    # 가로축 칸 글: 선은 겹치지 않게 솎고(처음·끝은 남긴다), 막대는 칸 폭에 맞춰 줄을 나눈다
    fig_ax = ax.get_position()
    ax_w_px = fig_ax.width * W
    if kind == "line":
        lw = (max(_text_w(fig, r, x, TICK_PT) for x in xs) + 6 * pt2px) * 1.25  # 끝 꼬리표 자리로 칸이 좁아질 몫
        step = max(1, math.ceil(lw / (ax_w_px / max(1, len(xs)))))
        shown = list(range(0, len(xs), step))
        if shown[-1] != len(xs) - 1:
            if (len(xs) - 1 - shown[-1]) * (ax_w_px / len(xs)) < lw:
                shown[-1] = len(xs) - 1
            else:
                shown.append(len(xs) - 1)
        ax.set_xticks(shown)
        ax.set_xticklabels([xs[i] for i in shown])
    else:
        slot = ax_w_px / len(xs) * 0.95
        ax.set_xticks(idx)
        ax.set_xticklabels(["\n".join(_wrap(fig, r, x, TICK_PT, slot)) for x in xs], linespacing=1.1)

    if multi:
        fig.legend(handles=handles, labels=[s["name"] for s in series], loc="upper left",
                   bbox_to_anchor=(pad / W - 0.01, legend_top / H), ncol=len(series), frameon=False,
                   fontsize=LEGEND_PT, handlelength=2.4, columnspacing=1.4, borderaxespad=0, borderpad=0.2)

    if not yz and kind == "line":
        ax.text(1.0, 1.0, "세로축이 0에서 시작하지 않음", transform=ax.transAxes, fontsize=NOTE_PT,
                color=FOOT, ha="right", va="bottom")

    # 눈금 글이 그림 밖으로 나가지 않게 축 자리를 맞춘다(두 번 잰다)
    for _ in range(2):
        fig.canvas.draw()
        pos = ax.get_position()
        tb = ax.get_tightbbox(r)
        ax_bb = ax.get_window_extent(r)
        left_over = ax_bb.x0 - tb.x0                       # 세로축 눈금 글 폭
        right_over = max(0.0, tb.x1 - ax_bb.x1)            # 끝 칸 글이 오른쪽으로 넘친 폭
        bottom_over = ax_bb.y0 - tb.y0                     # 가로축 칸 글 높이
        top_over = max(0.0, tb.y1 - ax_bb.y1)              # 0 아님 표시 같은 축 위 글
        x0 = (pad + left_over) / W
        x1 = (W - pad - right_over) / W
        y0 = (foot_top + bottom_over + 0.2 * TICK_PT * pt2px) / H
        y1 = (axes_top - top_over) / H
        ax.set_position((x0, y0, max(0.1, x1 - x0), max(0.1, y1 - y0)))
        if end_anns:
            _fit_end_labels(ax, end_anns, len(idx), W, pt2px)
        if abs(pos.x0 - x0) < 1e-4 and abs(pos.y0 - y0) < 1e-4 and abs(pos.y1 - y1) < 1e-4:
            break
    if end_anns:
        fig.canvas.draw()
        _separate_end_labels(ax, end_anns, pt2px)


def _fit_end_labels(ax, end_anns, n: int, W: int, pt2px: float) -> None:
    """처음·끝 점 옆 꼬리표가 들어갈 만큼 가로축 범위를 넓힌다(px 로 재서 데이터 단위로 바꾼다)."""
    ext_l = max([w for _, pi, w in end_anns if pi == 0] or [0])
    ext_r = max([w for _, pi, w in end_anns if pi == n - 1] or [0])
    ext_l = ext_l + 10 * pt2px if ext_l else 0
    ext_r = ext_r + 10 * pt2px if ext_r else 0
    ax_w = ax.get_position().width * W
    span = (n - 1) + 0.8
    dpp = span / max(1.0, ax_w - ext_l - ext_r)
    ax.set_xlim(-0.4 - ext_l * dpp, n - 1 + 0.4 + ext_r * dpp)


def _separate_end_labels(ax, end_anns, pt2px: float) -> None:
    """같은 끝 점에 붙은 꼬리표들이 세로로 겹치지 않게 벌린다."""
    need = LABEL_PT * 1.25  # pt
    for side in {pi for _, pi, _ in end_anns}:
        group = [(a, ax.transData.transform(a.xy)[1] / pt2px) for a, pi, _ in end_anns if pi == side]
        group.sort(key=lambda g: g[1])
        ys = [y for _, y in group]
        for i in range(1, len(ys)):
            if ys[i] - ys[i - 1] < need:
                ys[i] = ys[i - 1] + need
        shift = (sum(y for _, y in group) - sum(ys)) / len(ys)  # 무리 전체를 원래 중심에 맞춘다
        for (a, y0), y in zip(group, ys):
            a.xyann = (a.xyann[0], y + shift - y0)
