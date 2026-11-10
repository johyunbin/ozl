#!/usr/bin/env python3
"""슬라이드 프레임 정밀 측정 (Phase 2A · style_tokens 보완).

style_tokens.py(32단계 양자화 집계)가 못 잡는 것을 잰다.
  - 프레임 분류: dialog(주석 도구의 '작업을 저장하시겠습니까?' 대화상자 + 화면 흐림) / faded(흐림·빈 화면) / clean
  - clean 프레임만: 제목 줄(위치·글자 높이·심지 색) · 본문 줄(글자 높이·줄 간격·색·획 굵기) · 그림 영역(좌표·폭) · 레이아웃 유형
좌표계: 프레임(1152×680) = 1080p 화면의 좌상단 0.60×0.63 크롭. 슬라이드 캔버스 = 화면 좌상단 1218×686px(1080p 전체 프레임 2장 실측 · 16:9)
       → 13.333×7.5in 슬라이드로 보면 1px = 960pt/1218 = 0.788pt. 프레임은 캔버스의 왼쪽 94.6%·위쪽 99.1%를 담는다.
출력: private/style/style_measure_raw.json(프레임별) · tracks/syuka/analysis/style_measure_syukaworld.md(집계만 · 공개)

    python -m ozl.analyze.style_measure
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
from collections import Counter

import cv2
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[3]
FRAMES = ROOT / "private" / "frames"
OUT_RAW = ROOT / "private" / "style" / "style_measure_raw.json"
OUT_MD = ROOT / "tracks" / "syuka" / "analysis" / "style_measure_syukaworld.md"

CANVAS_W, CANVAS_H = 1218.0, 686.0  # 1080p 화면에서 슬라이드 캔버스 픽셀(전체 프레임 실측)
PT_PER_PX = 960.0 / CANVAS_W
IN_PER_PX = 13.333 / CANVAS_W
BOLD_RATIO = 0.085  # 획 굵기/글자 높이 경계: 보통 2px/30px=0.067 · 굵게 3~4px/30px=0.10~0.13 (분포의 골)

# 대화상자 서명(1152×680 기준 실측): 버튼 회녹색 (211,221,219) ±5 · 내부 청백색 R 244~250, G·B ≥ 253
BTN_MIN_RATIO = 3000 / (1152 * 680)
CYAN_MIN_RATIO = 20000 / (1152 * 680)
FADED_P05 = 100  # 밝기 하위 0.5% 값이 이 이상이면 어두운 잉크가 없는 흐림·빈 화면


def classify(a: np.ndarray) -> str:
    n = a.shape[0] * a.shape[1]
    btn = ((abs(a[..., 0] - 211) <= 5) & (abs(a[..., 1] - 221) <= 5) & (abs(a[..., 2] - 219) <= 5)).sum() / n
    cy = ((a[..., 0] >= 244) & (a[..., 0] <= 250) & (a[..., 1] >= 253) & (a[..., 2] >= 253)).sum() / n
    if btn >= BTN_MIN_RATIO and cy >= CYAN_MIN_RATIO:
        return "dialog"
    p05 = np.percentile(a.mean(axis=2), 0.5)
    if btn >= BTN_MIN_RATIO * 0.27 and cy >= CYAN_MIN_RATIO * 2 and p05 >= 25:
        return "dialog"  # 대화상자가 나타나거나 사라지는 중(버튼색이 덜 찼고 글자가 반쯤 흐려짐) — 독립 검증에서 clean 으로 새던 프레임
    if p05 >= FADED_P05:
        return "faded"
    nw = (a[..., 1] >= 250) & (a[..., 2] >= 250) & (a[..., 0] >= 240)
    if nw.mean() >= 0.3 and np.median(a[..., 0][nw]) <= 250:
        return "faded"  # 화면 전체가 청백색(248,255,255)인 빈 필기 화면
    return "clean"


def hexc(rgb) -> str:
    return "#%02X%02X%02X" % tuple(int(round(float(x))) for x in rgb)


def masks(a: np.ndarray):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=2), a.min(axis=2)
    lum = a.mean(axis=2)
    red = (r >= 130) & (g <= 95) & (b <= 95) & (r - np.maximum(g, b) >= 70)
    black = (lum <= 110) & ((mx - mn) <= 40)
    nonwhite = (lum < 240) | ((mx - mn) > 25)
    return red, black, nonwhite


def image_boxes(nonwhite: np.ndarray, block: int = 8) -> list[tuple[int, int, int, int]]:
    """꽉 찬(밀도 ≥ 0.9) 블록의 연결 성분 중 큰 것 = 사진·그림. 반환 (x0, y0, x1, y1) 픽셀."""
    h, w = nonwhite.shape
    hb, wb = h // block, w // block
    dens = nonwhite[: hb * block, : wb * block].reshape(hb, block, wb, block).mean(axis=(1, 3))
    dense = (dens >= 0.9).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(dense, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw >= 10 and bh >= 8 and area >= 0.6 * bw * bh:
            out.append((int(x * block), int(y * block), int((x + bw) * block), int((y + bh) * block)))
    return out


def stroke_width(m: np.ndarray) -> float | None:
    """가로 방향 연속 잉크 길이의 중앙값 ≈ 세로획 굵기(px)."""
    runs = []
    for row in m:
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        s, e = np.where(d == 1)[0], np.where(d == -1)[0]
        runs.extend((e - s).tolist())
    runs = [x for x in runs if 2 <= x <= 14]
    return float(statistics.median(runs)) if len(runs) >= 8 else None


def core_color(a: np.ndarray, m: np.ndarray) -> list[int] | None:
    """안티에일리어싱을 피하려고 마스크를 1px 침식한 '심지' 픽셀의 중앙값 색."""
    er = cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    px = a[er] if er.sum() >= 30 else None
    if px is None:
        return None
    return [int(x) for x in np.median(px, axis=0)]


def text_lines(a: np.ndarray, red: np.ndarray, black: np.ndarray, boxes) -> list[dict]:
    h, w = red.shape
    ink = red | black
    for x0, y0, x1, y1 in boxes:
        ink[max(0, y0 - 6) : y1 + 6, max(0, x0 - 6) : x1 + 6] = False
    rows = ink.sum(axis=1) >= 3
    d = np.diff(np.concatenate(([0], rows.astype(np.int8), [0])))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    lines = []
    for s, e in zip(starts, ends):
        hh = int(e - s)
        if not 12 <= hh <= 70:
            continue
        seg = ink[s:e]
        cols = np.where(seg.any(axis=0))[0]
        if len(cols) < 20:
            continue
        x0, x1 = int(cols[0]), int(cols[-1])
        n_ink = int(seg.sum())
        n_red = int((red[s:e] & seg).sum())
        rr = n_red / max(1, n_ink)
        m = (red[s:e] & seg) if rr >= 0.5 else (black[s:e] & seg)
        lines.append({"top": int(s), "h": hh, "x0": x0, "x1": x1, "red_ratio": round(rr, 3),
                      "stroke": stroke_width(m), "color": core_color(a[s:e], m)})
    return lines


def measure(p: pathlib.Path) -> dict:
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
    h, w, _ = a.shape
    cls = classify(a)
    out = {"file": p.name, "class": cls}
    if cls != "clean":
        return out
    red, black, nonwhite = masks(a)
    boxes = image_boxes(nonwhite)
    lines = text_lines(a, red, black, boxes)
    title = next((ln for ln in lines if ln["top"] < 0.2 * h and ln["red_ratio"] >= 0.6 and ln["x0"] < 0.35 * w), None)
    body = [ln for ln in lines if title is None or ln["top"] > title["top"] + title["h"]]
    pitches = []
    for p1, p2 in zip(body, body[1:]):
        if abs(p1["x0"] - p2["x0"]) <= 12 and 0.75 <= p2["h"] / p1["h"] <= 1.33:
            pitches.append({"pitch": p2["top"] - p1["top"], "h": (p1["h"] + p2["h"]) / 2})
    big = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), default=None)
    layout = "text_only"
    if big:
        bw, cx = (big[2] - big[0]) / w, (big[0] + big[2]) / 2 / w
        layout = "image_full" if bw >= 0.7 else ("image_left" if cx < 0.45 else ("image_right" if cx > 0.6 else "image_center"))
        if len(boxes) >= 2:
            sec = sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))[1]
            if (sec[2] - sec[0]) * (sec[3] - sec[1]) >= 0.5 * (big[2] - big[0]) * (big[3] - big[1]):
                layout = "image_pair"
    out.update({"title": title, "body": body, "pitches": pitches, "images": boxes, "layout": layout,
                "white_ratio": round(float((a.mean(axis=2) >= 245).mean()), 3)})
    return out


def med(xs, nd=1):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), nd) if xs else None


def main() -> int:
    per_video = []
    for d in sorted(FRAMES.iterdir()):
        if not (d / "index.json").exists():
            continue
        idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
        fr = [measure(d / f) for f in idx.get("frames", [])]
        per_video.append({"video_id": idx["video_id"], "duration_sec": idx.get("duration_sec"), "frames": fr})
    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    OUT_RAW.write_text(json.dumps(per_video, ensure_ascii=False), encoding="utf-8")

    allf = [f for v in per_video for f in v["frames"]]
    cls = Counter(f["class"] for f in allf)
    clean = [f for f in allf if f["class"] == "clean"]
    titled = [f for f in clean if f.get("title")]
    t = [f["title"] for f in titled]
    tcol = [x["color"] for x in t if x["color"]]
    body = [ln for f in clean for ln in f["body"]]
    main_body = [ln for ln in body if 20 <= ln["h"] <= 40]  # 표 안 잔글씨·대형 숫자 제외한 본문 줄
    red_b = [ln for ln in main_body if ln["red_ratio"] >= 0.5]
    blk_b = [ln for ln in main_body if ln["red_ratio"] < 0.1]
    pitches = [p for f in clean for p in f["pitches"] if 20 <= p["h"] <= 40 and 1.0 <= p["pitch"] / p["h"] <= 2.6]
    lay = Counter(f["layout"] for f in clean)
    bigs = []
    for f in clean:
        if f["layout"] in ("image_left", "image_right") and f["images"]:
            b = max(f["images"], key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            bigs.append(b)

    def col_med(cols):
        return hexc(np.median(np.array(cols), axis=0)) if cols else "-"

    def hist(vals, lo, hi, step=2):
        c = Counter(int(v // step * step) for v in vals if lo <= v <= hi)
        tot = sum(c.values()) or 1
        return " · ".join(f"{k}~{k + step - 1}px {c[k] / tot:.0%}" for k in sorted(c) if c[k] / tot >= 0.04)

    def stroke_split(lines):
        """획 굵기/글자 높이 비율로 보통·굵게를 가른다(BOLD_RATIO)."""
        r = [ln["stroke"] / ln["h"] for ln in lines if ln["stroke"]]
        bold = sum(1 for x in r if x >= BOLD_RATIO)
        return len(r), bold

    n_b, bold_b = stroke_split(blk_b)
    n_r, bold_r = stroke_split(red_b)
    n = len(allf)
    L = ["# 슈카월드 슬라이드 정밀 측정 (대표 30편 1080p 프레임 · 집계)", "",
         "측정 좌표계: 프레임 1152×680px = 1080p 화면의 좌상단 0.60×0.63 · 슬라이드 캔버스 1218×686px(16:9 · 1080p 전체 프레임 실측) · 13.333×7.5in 슬라이드 기준 1px ≈ 0.788pt = 0.0109in.",
         "글자 높이는 한 줄의 잉크 높이(px)이며 폰트 크기(pt)가 아니다. pt 환산은 폰트 대조(§5 · `font_match`) 결과를 쓴다.", "",
         "## 1. 프레임 분류", "",
         f"- 전체 {n}장 / 영상 {len(per_video)}편 → **clean {cls['clean']}장({cls['clean'] / n:.0%})** · dialog {cls['dialog']}장({cls['dialog'] / n:.0%}) · faded {cls['faded']}장({cls['faded'] / n:.0%})",
         "- dialog = 화면 주석 도구의 저장 확인 대화상자가 뜬 채 슬라이드가 흐려진 프레임(필기를 지울 때마다 발생). 색·여백 집계에서 제외해야 한다 — 포함하면 제목색이 연분홍으로, 무채색 상위가 대화상자 회색으로 오염된다.", "",
         "## 2. 제목 줄", "",
         f"- 검출 {len(titled)}장 / clean {len(clean)}장({len(titled) / max(1, len(clean)):.0%})",
         f"- 심지 색 중앙값 **{col_med(tcol)}** (안티에일리어싱 제외 · {len(tcol)}장)",
         f"- 글자 높이 중앙값 **{med([x['h'] for x in t])}px** · 분포: {hist([x['h'] for x in t], 12, 70)}",
         f"- 윗변 위치 중앙값 {med([x['top'] for x in t])}px = 캔버스 높이의 {med([x['top'] / CANVAS_H * 100 for x in t])}% ({med([x['top'] * IN_PER_PX for x in t], 2)}in)",
         f"- 왼쪽 시작 중앙값 {med([x['x0'] for x in t])}px = 캔버스 폭의 {med([x['x0'] / CANVAS_W * 100 for x in t])}% ({med([x['x0'] * IN_PER_PX for x in t], 2)}in)",
         f"- 획 굵기/글자 높이 중앙값 {med([x['stroke'] / x['h'] for x in t if x['stroke']], 3)}", "",
         "## 3. 본문 줄 (글자 높이 20~40px)", "",
         f"- 줄 수 {len(main_body)} · 검정 {len(blk_b)}줄({len(blk_b) / max(1, len(main_body)):.0%}) · 빨강 {len(red_b)}줄({len(red_b) / max(1, len(main_body)):.0%}) · 혼합 {len(main_body) - len(blk_b) - len(red_b)}줄",
         f"- 검정 심지 색 중앙값 **{col_med([ln['color'] for ln in blk_b if ln['color']])}** · 빨강 심지 색 중앙값 **{col_med([ln['color'] for ln in red_b if ln['color']])}**",
         f"- 굵은 빨강(획 ≥ 4px) 심지 색 중앙값 **{col_med([ln['color'] for ln in red_b if ln['color'] and (ln['stroke'] or 0) >= 4])}** — 가는 획은 영상 압축으로 어둡게 번져 과소 측정되므로 굵은 획 값이 원색에 가장 가깝다(표준 '진한 빨강' #C00000 근방)",
         f"- 글자 높이 중앙값 **{med([ln['h'] for ln in main_body])}px** · 분포: {hist([ln['h'] for ln in main_body], 20, 40)}",
         f"- 줄 간격(윗변~윗변) 중앙값 **{med([p['pitch'] for p in pitches])}px** · 줄 간격/글자 높이 중앙값 {med([p['pitch'] / p['h'] for p in pitches], 2)} ({len(pitches)}쌍)",
         f"- 굵게 비율(획/높이 ≥ {BOLD_RATIO}): 검정 {bold_b}/{n_b}줄({bold_b / max(1, n_b):.0%}) · 빨강 {bold_r}/{n_r}줄({bold_r / max(1, n_r):.0%})", "",
         "## 4. 레이아웃 (사진형 그림만 — 참고용)", "",
         "아래 표는 꽉 찬 사각 사진만 그림으로 잡는다. 흰 배경 위의 로고·오려낸 인물·문서 캡처·도표는 놓치므로 `text_only` 가 과대, `image_left` 가 과소다(독립 검증에서 확인). 레이아웃 분포의 정본은 문자 인식으로 글을 뺀 뒤 판정하는 `slide_structure_syukaworld.md` 다.", "",
         "| 유형 | 장수 | 비율 |", "|---|---|---|"]
    for k, v in lay.most_common():
        L.append(f"| {k} | {v} | {v / max(1, len(clean)):.0%} |")
    if bigs:
        L += ["", f"- 좌/우 그림(주 그림 1개) {len(bigs)}장: 폭 중앙값 {med([(b[2] - b[0]) for b in bigs])}px = 캔버스 폭의 {med([(b[2] - b[0]) / CANVAS_W * 100 for b in bigs])}% ({med([(b[2] - b[0]) * IN_PER_PX for b in bigs], 2)}in) · 높이 중앙값 {med([(b[3] - b[1]) for b in bigs])}px ({med([(b[3] - b[1]) * IN_PER_PX for b in bigs], 2)}in)",
              f"- 그림 왼쪽 변 중앙값 {med([b[0] for b in bigs])}px({med([b[0] * IN_PER_PX for b in bigs], 2)}in) · 윗변 중앙값 {med([b[1] for b in bigs])}px({med([b[1] * IN_PER_PX for b in bigs], 2)}in)"]
    il = [f for f in clean if f["layout"] == "image_left" and f["images"]]
    col_x0, gaps, nlines = [], [], []
    for f in il:
        b = max(f["images"], key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        right = [ln for ln in f["body"] if 20 <= ln["h"] <= 40 and ln["x0"] > b[2]]
        if right:
            x0 = statistics.median(ln["x0"] for ln in right)
            col_x0.append(x0)
            gaps.append(x0 - b[2])
            nlines.append(len(right))
    if col_x0:
        L += [f"- 좌 그림 슬라이드의 글 기둥({len(col_x0)}장): 왼쪽 시작 중앙값 {med(col_x0)}px({med([x * IN_PER_PX for x in col_x0], 2)}in) · 그림과의 간격 중앙값 {med(gaps)}px({med([g * IN_PER_PX for g in gaps], 2)}in) · 장당 본문 줄 수 중앙값 {med(nlines)}줄(상위 10% {sorted(nlines)[int(len(nlines) * 0.9)]}줄)",
              f"- 첫 본문 줄 윗변 중앙값 {med([min(ln['top'] for ln in f['body'] if 20 <= ln['h'] <= 40) for f in il if any(20 <= ln['h'] <= 40 for ln in f['body'])])}px"]
    fm = ROOT / "private" / "style" / "fontmatch" / "report.json"
    if fm.exists():
        rep = json.loads(fm.read_text(encoding="utf-8"))
        ems = [s_["rank"][0]["size_px"] / (1 + s_["rank"][0]["aspect_err"]) for s_ in rep["samples"]]
        L += ["", "## 5. 폰트 대조 (`font_match` · 표본 줄을 후보 폰트로 렌더해 겹침 비교)", "",
              f"- 표본 {len(rep['samples'])}줄 · 후보 {len(rep['summary'])}종(설치 폰트 + 오피스 번들 폰트)",
              "", "| 후보 | 평균 겹침(IoU) | 평균 폭비 오차 |", "|---|---|---|"]
        for k, iou, ae, _ in rep["summary"][:6]:
            L.append(f"| {k} | {iou:.3f} | {ae:.1%} |")
        L += ["", f"- 표본 13줄(영상 2편)의 폭 기준 글자 크기(em) 중앙값 {statistics.median(ems):.2f}px(범위 {min(ems):.2f}~{max(ems):.2f})"]
    fs = ROOT / "private" / "style" / "font_survey.json"
    if fs.exists():
        sv = json.loads(fs.read_text(encoding="utf-8"))
        sm, vs = sv["summary"], sv["videos"]
        L += ["", "### 영상별 글자 크기 (`font_survey` · 문자 인식된 한글 줄을 맑은 고딕으로 렌더해 폭으로 역산)", "",
              f"- 영상 {sm['videos']}편 · 편당 {min(v['n'] for v in vs)}~{max(v['n'] for v in vs)}줄 · **em 중앙값 {sm['em_px_median']}px = 13.333in 슬라이드 {sm['pt_13in_median']}pt** · 영상별 범위 {sm['em_px_min']}~{sm['em_px_max']}px({sm['pt_13in_range'][0]}~{sm['pt_13in_range'][1]}pt)",
              "- 한 영상 안에서는 사분위 범위가 ±0.05px 안팎으로 일정하고, 같은 날 방송에서 나온 클립끼리는 값이 같다 → 차이는 글자 크기가 아니라 **방송 회차별 송출 배율**이다(전체 프레임 3장에서 캔버스도 1190×682 · 1213×704 · 1219×687 로 달랐다). 원본 파일의 pt 는 영상만으로 확정할 수 없고, 26pt 는 화면상 겉보기의 중앙값이다.",
              f"- **줄 간격 ÷ em 은 30편 모두 {sm['pitch_em_range'][0]}~{sm['pitch_em_range'][1]}(중앙값 {sm['pitch_em_median']})** → 배율과 무관하게 파워포인트 '1.5줄'(1.5 × 1.2em = 1.80em)"]
    L += ["", "## 6. 영상별 분류", "", "| 영상 | 길이(분) | 전체 | clean | dialog | faded | clean 10분당 |", "|---|---|---|---|---|---|---|"]
    for v in per_video:
        c = Counter(f["class"] for f in v["frames"])
        L.append(f"| {v['video_id']} | {round((v['duration_sec'] or 0) / 60)} | {len(v['frames'])} | {c['clean']} | {c['dialog']} | {c['faded']} | {c['clean'] / max(1, v['duration_sec'] or 1) * 600:.1f} |")
    cl10 = [Counter(f["class"] for f in v["frames"])["clean"] / max(1, v["duration_sec"] or 1) * 600 for v in per_video]
    L += ["", f"- clean 프레임 10분당 중앙값 {statistics.median(cl10):.1f}장 — ⚠️ 이 프레임 집합은 장면 전환 검출 + 유사 이미지 제거를 거쳐 실제 슬라이드의 절반 가까이를 놓친다. **장수·체류 시간은 촘촘 표본으로 다시 센 `slide_structure_syukaworld.md` 를 본다.** 색·폰트·크기·여백 측정에는 영향이 없다.",
          "", "※ 줄 검출은 가로 투영이라 2단 배치(표 옆 글)에서는 줄이 합쳐질 수 있다. 수치는 중앙값·분포로만 읽는다."]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:32]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
