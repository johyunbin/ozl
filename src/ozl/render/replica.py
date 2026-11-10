#!/usr/bin/env python3
"""원본 프레임 한 장을 측정 좌표 그대로 재현해 렌더와 겹쳐 보는 검증 (Phase 2A 검증 항목).

  build   : private/style/replica_spec.json(프레임·줄 좌표·문구 — 비공개) → private/style/replica/replica_<ts>.pptx
  compare : 렌더 PDF(파워포인트 내보내기) → 캔버스 해상도(1218×686) PNG → 원본 프레임과 줄 단위 대조 + 겹침 이미지
보정값(글상자 변 → 첫 글자 잉크까지의 거리)은 compare 결과로 정해 deck.py 상수에 반영한다.

    python -m ozl.render.replica build
    python -m ozl.render.replica compare <pdf>
    python -m ozl.render.replica verify      # build → 파워포인트 PDF 내보내기 → compare
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image
from pptx.util import Inches

from ozl.render import deck

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = ROOT / "private" / "style" / "replica_spec.json"
OUT = ROOT / "private" / "style" / "replica"
FRAMES = ROOT / "private" / "frames"
CW, CH = 1218, 686

INK_DX, TITLE_INK_DY, BODY_INK_DY = deck.INK_DX, deck.TITLE_INK_DY, deck.BODY_INK_DY  # 보정 상수 정본 = deck.py


def _runs(items):
    out = []
    for text, st in items:
        d = {}
        if st.get("red"):
            d["color"] = deck.EMPH_RGB
        if st.get("bold"):
            d["bold"] = True
        if st.get("size"):
            d["size"] = st["size"]
        out.append((text, d))
    return out


def build() -> pathlib.Path:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    prs = deck.new_deck()
    s = deck._blank(prs)
    t = spec["title"]
    truns = [(x, {**y, "color": deck.TITLE_RGB}) for x, y in _runs(t["runs"])]
    deck._text(s, deck.px(t["x0"] - INK_DX), deck.px(t["top"] - TITLE_INK_DY), deck.W - deck.px(t["x0"]), deck.px(60), truns, line_spacing=1.0)
    if spec.get("image"):
        x0, y0, x1, y1 = spec["image"]
        deck.placeholder_image(s, deck.px(x0), deck.px(y0), deck.px(x1 - x0), deck.px(y1 - y0), source="")
    b = spec["body"]
    runs = []
    for i, line in enumerate(b["lines"]):
        if i:
            runs.append("\n")
        runs.extend(_runs(line))
    deck._text(s, deck.px(b["x0"] - INK_DX), deck.px(b["top"] - BODY_INK_DY), deck.W - deck.px(b["x0"]) , Inches(5), runs)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"replica_{dt.datetime.now():%Y%m%d_%H%M%S}.pptx"
    prs.save(str(out))
    return out


def _ink(a: np.ndarray) -> np.ndarray:
    a = a.astype(np.int16)
    red = (a[..., 0] >= 120) & (a[..., 1] <= 120) & (a[..., 0] - np.maximum(a[..., 1], a[..., 2]) >= 50)
    return (a.mean(axis=2) < 140) | red


def _lines(m: np.ndarray, x_min: int, x_max: int, y_min: int, y_max: int) -> list[tuple[int, int, int, int]]:
    sub = m[y_min:y_max, x_min:x_max]
    rows = sub.sum(axis=1) >= 2
    d = np.diff(np.concatenate(([0], rows.astype(np.int8), [0])))
    out = []
    for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
        if e - s < 12:
            continue
        cols = np.where(sub[s:e].any(axis=0))[0]
        out.append((int(cols[0]) + x_min, int(s) + y_min, int(cols[-1]) + x_min + 1, int(e) + y_min))
    return out


def compare(pdf: pathlib.Path) -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    png = pdf.with_suffix("")
    subprocess.run(["pdftoppm", "-png", "-f", "1", "-l", "1", "-scale-to-x", str(CW), "-scale-to-y", str(CH), str(pdf), str(png)], check=True)
    rp = next(pdf.parent.glob(pdf.stem + "*.png"))
    r = np.asarray(Image.open(rp).convert("RGB"))
    o_full = np.asarray(Image.open(FRAMES / spec["frame"]).convert("RGB"))
    h, w, _ = o_full.shape
    r = r[:h, :w]
    mo, mr = _ink(o_full), _ink(r)
    b = spec["body"]
    regions = {"title": (0, w, 0, spec["title"]["top"] + 60), "body": (b["x0"] - 20, w, b["top"] - 30, h)}
    print(f"렌더 {rp.name} · 원본 {spec['frame']}")
    worst = 0.0
    for name, (xa, xb, ya, yb) in regions.items():
        lo, lr = _lines(mo, xa, xb, ya, yb), _lines(mr, xa, xb, ya, yb)
        print(f"[{name}] 원본 {len(lo)}줄 · 렌더 {len(lr)}줄")
        for a_, b_ in zip(lo, lr):
            dx, dy, dw, dh = b_[0] - a_[0], b_[1] - a_[1], (b_[2] - b_[0]) - (a_[2] - a_[0]), (b_[3] - b_[1]) - (a_[3] - a_[1])
            worst = max(worst, abs(dx), abs(dy))
            print(f"   원본 x {a_[0]:>4}~{a_[2]:<4} y {a_[1]:>3}~{a_[3]:<3} | 렌더 x {b_[0]:>4}~{b_[2]:<4} y {b_[1]:>3}~{b_[3]:<3} | Δx {dx:+d} Δy {dy:+d} Δ폭 {dw:+d}({dw / max(1, a_[2] - a_[0]):+.1%}) Δ높이 {dh:+d}")
    xa, xb, ya, yb = regions["body"]
    inter = (mo[ya:yb, xa:xb] & mr[ya:yb, xa:xb]).sum()
    union = (mo[ya:yb, xa:xb] | mr[ya:yb, xa:xb]).sum()
    print(f"본문 글자 마스크 IoU {inter / max(1, union):.3f} · 최대 위치 오차 {worst:.0f}px")
    # 겹침 이미지: 원본 = 빨강, 렌더 = 파랑, 겹침 = 검정
    ov = np.full((h, w, 3), 255, np.uint8)
    ov[mo & ~mr] = (230, 40, 40)
    ov[mr & ~mo] = (40, 90, 230)
    ov[mo & mr] = (0, 0, 0)
    Image.fromarray(ov).save(OUT / (pdf.stem + "_overlay.png"))
    side = Image.new("RGB", (w, h * 2 + 6), "white")
    side.paste(Image.fromarray(o_full), (0, 0))
    side.paste(Image.fromarray(r), (0, h + 6))
    side.save(OUT / (pdf.stem + "_side.png"))
    print(OUT / (pdf.stem + "_overlay.png"))
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "compare":
        return compare(pathlib.Path(argv[1]))
    pptx = build()
    print(pptx)
    if argv and argv[0] == "verify":  # build → 파워포인트 PDF → compare 한 번에
        from ozl.render.ppt_export import export_pdf
        pdf = export_pdf(pptx)
        return compare(pdf) if pdf else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
