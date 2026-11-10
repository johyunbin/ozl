#!/usr/bin/env python3
"""원본 프레임의 글줄과 후보 폰트 렌더를 겹쳐 폰트·크기를 판별 (Phase 2A).

입력: private/style/font_samples.json — [{"frame": "<video_id>/<file>.png", "top": 행 근사값, "text": "줄 전체 글자", "x_min": 선택}]
       (슬라이드 문구라 비공개 폴더에 둔다)
방법: 줄의 잉크 마스크를 얻고(행 근사값 ±8px 안에서 줄 경계 재탐색) 후보 폰트로 같은 문장을 렌더 →
       ① 가로/세로 비율 차(글자 폭 = 폰트 고유) ② 같은 상자로 맞춘 뒤 마스크 IoU(±2px 이동 최대값) ③ 잉크 높이로 역산한 폰트 크기(px·pt)
출력: private/style/fontmatch/report.json · 비교 이미지 private/style/fontmatch/compare_<n>.png · 표준출력 순위표

    python -m ozl.analyze.font_match
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[3]
FRAMES = ROOT / "private" / "frames"
OUT = ROOT / "private" / "style" / "fontmatch"
SAMPLES = ROOT / "private" / "style" / "font_samples.json"
PT_PER_PX = 960.0 / 1218.0  # 13.333in 슬라이드 = 캔버스 1218px (style_measure 와 같은 기준)

NANUM_TTC = next(iter(pathlib.Path("/System/Library/AssetsV2").glob("com_apple_MobileAsset_Font*/*/AssetData/NanumGothic.ttc")), None)
UF = pathlib.Path.home() / "Library" / "Fonts"


def candidates() -> list[tuple[str, callable]]:
    c: list[tuple[str, callable]] = []
    if NANUM_TTC:
        for i, w in enumerate(("Regular", "Bold", "ExtraBold")):
            c.append((f"NanumGothic {w}", lambda s, i=i: ImageFont.truetype(str(NANUM_TTC), s, index=i)))
    for f, n in (("NanumSquareL.otf", "NanumSquare Light"), ("NanumSquareR.otf", "NanumSquare Regular"), ("NanumSquareB.otf", "NanumSquare Bold"),
                 ("NanumSquareEB.otf", "NanumSquare ExtraBold")):
        if (UF / f).exists():
            c.append((n, lambda s, f=f: ImageFont.truetype(str(UF / f), s)))
    for f, n, weights in (("NotoSansKR-VariableFont_wght.ttf", "Noto Sans KR", (300, 400, 500, 700)), ("PretendardVariable.ttf", "Pretendard", (300, 400, 500, 700))):
        if (UF / f).exists():
            for w in weights:
                def mk(s, f=f, w=w):
                    ft = ImageFont.truetype(str(UF / f), s)
                    ft.set_variation_by_axes([w])
                    return ft
                c.append((f"{n} {w}", mk))
    sd = pathlib.Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
    if sd.exists():
        for i in range(0, 18, 2):
            try:
                nm = ImageFont.truetype(str(sd), 20, index=i).getname()
            except Exception:  # noqa: BLE001
                break
            c.append((f"{nm[0]} {nm[1]}", lambda s, i=i: ImageFont.truetype(str(sd), s, index=i)))
    ag = pathlib.Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf")
    if ag.exists():
        c.append(("AppleGothic", lambda s: ImageFont.truetype(str(ag), s)))
    # 오피스 번들 폰트(설치돼 있으면 제자리에서 읽기만 — 복사·재배포 안 함): 맑은 고딕·굴림·돋움
    office = next((d for d in (pathlib.Path(f"/Applications/Microsoft {a}.app/Contents/Resources/DFonts") for a in ("PowerPoint", "Word", "Excel")) if d.exists()), None)
    if office:
        for f, n in (("malgun.ttf", "Malgun Gothic Regular"), ("malgunbd.ttf", "Malgun Gothic Bold"), ("malgunsl.ttf", "Malgun Gothic Semilight")):
            if (office / f).exists():
                c.append((n, lambda s, f=f: ImageFont.truetype(str(office / f), s)))
        if (office / "gulim.ttc").exists():
            for i in range(4):
                try:
                    nm = ImageFont.truetype(str(office / "gulim.ttc"), 20, index=i).getname()
                except Exception:  # noqa: BLE001
                    break
                c.append((f"{nm[0]} {nm[1]}", lambda s, i=i: ImageFont.truetype(str(office / "gulim.ttc"), s, index=i)))
    # 추가 폰트 폴더(있으면): private/style/fonts_extra/*.ttf|otf — 내려받은 후보를 넣어 두면 함께 비교
    extra = ROOT / "private" / "style" / "fonts_extra"
    if extra.exists():
        for p in sorted(list(extra.glob("*.ttf")) + list(extra.glob("*.otf"))):
            c.append((p.stem, lambda s, p=p: ImageFont.truetype(str(p), s)))
    return c


def ink_mask(a: np.ndarray) -> np.ndarray:
    a = a.astype(np.int16)
    lum = a.mean(axis=2)
    red = (a[..., 0] >= 120) & (a[..., 1] <= 120) & (a[..., 0] - np.maximum(a[..., 1], a[..., 2]) >= 50)
    return (lum < 140) | red


def target_line(frame: pathlib.Path, top: int, x_min: int = 0, x_max: int | None = None) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    a = np.asarray(Image.open(frame).convert("RGB"))
    m = ink_mask(a)
    m[:, :x_min] = False
    if x_max:
        m[:, x_max:] = False
    rows = m.sum(axis=1) >= 2
    y = top
    while y < a.shape[0] - 1 and not rows[y]:  # 줄 안으로 진입
        y += 1
    y0 = y
    while y0 > 0 and rows[y0 - 1]:
        y0 -= 1
    y1 = y
    while y1 < a.shape[0] - 1 and rows[y1 + 1]:
        y1 += 1
    cols = np.where(m[y0 : y1 + 1].any(axis=0))[0]
    x0, x1 = int(cols[0]), int(cols[-1])
    return m[y0 : y1 + 1, x0 : x1 + 1], (x0, y0, x1 + 1, y1 + 1)


def render(font_fn, text: str, size: int = 160) -> np.ndarray:
    ft = font_fn(size)
    w = int(ft.getlength(text)) + size * 2
    im = Image.new("L", (w, size * 3), 255)
    ImageDraw.Draw(im).text((size, size), text, font=ft, fill=0)
    m = np.asarray(im) < 128
    ys, xs = np.where(m.any(axis=1))[0], np.where(m.any(axis=0))[0]
    return m[ys[0] : ys[-1] + 1, xs[0] : xs[-1] + 1]


def iou_best(t: np.ndarray, r: np.ndarray, shift: int = 2) -> float:
    h, w = t.shape
    rr = np.asarray(Image.fromarray((r * 255).astype(np.uint8)).resize((w, h), Image.LANCZOS)) >= 110
    best = 0.0
    big = 2 * shift
    tp = np.pad(t, big)  # 두 마스크를 넉넉한 같은 캔버스에 놓고 비교 — 이동으로 상자 밖에 나간 잉크도 합집합에 남는다
    for dy in range(-shift, shift + 1):
        for dx in range(-shift, shift + 1):
            sp = np.zeros_like(tp)
            sp[big + dy : big + dy + h, big + dx : big + dx + w] = rr
            u = (tp | sp).sum()
            if u:
                best = max(best, float((tp & sp).sum() / u))
    return best


def main() -> int:
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    cands = candidates()
    OUT.mkdir(parents=True, exist_ok=True)
    report, agg = [], {}
    for n, s in enumerate(samples):
        t, box = target_line(FRAMES / s["frame"], s["top"], s.get("x_min", 0), s.get("x_max"))
        th, tw = t.shape
        rows = []
        for name, fn in cands:
            try:
                r = render(fn, s["text"])
            except Exception as e:  # noqa: BLE001
                print(f"[{name}] 렌더 실패: {e}", file=sys.stderr)
                continue
            rh, rw = r.shape
            aspect_err = (rw / rh) / (tw / th) - 1
            size_px = 160 * th / rh
            rows.append({"font": name, "aspect_err": round(aspect_err, 4), "iou": round(iou_best(t, r), 4),
                         "size_px": round(size_px, 2), "size_pt": round(size_px * PT_PER_PX, 2), "ink_ratio_t": round(float(t.mean()), 3), "ink_ratio_r": round(float(r.mean()), 3)})
        rows.sort(key=lambda x: -x["iou"])
        report.append({"sample": n, "text": s["text"], "box": box, "target_wh": [tw, th], "rank": rows})
        for x in rows:
            agg.setdefault(x["font"], []).append(x)
        print(f"\n[{n}] {s['text']}  상자 {box} ({tw}×{th})")
        for x in rows[:6]:
            print(f"   {x['font']:<28} IoU {x['iou']:.3f}  폭비 오차 {x['aspect_err']:+.1%}  크기 {x['size_px']:.1f}px = {x['size_pt']:.1f}pt  잉크 {x['ink_ratio_t']:.2f}/{x['ink_ratio_r']:.2f}")
        # 비교 이미지: 원본 줄 + 상위 5개 후보(같은 폭으로 맞춤)
        top5 = rows[:5]
        scale = 3
        cell_h = th * scale + 26
        sheet = Image.new("RGB", (tw * scale + 20, cell_h * (len(top5) + 1) + 10), "white")
        dr = ImageDraw.Draw(sheet)
        lab = ImageFont.truetype(str(UF / "NanumSquareR.otf"), 16) if (UF / "NanumSquareR.otf").exists() else ImageFont.load_default()
        a = np.asarray(Image.open(FRAMES / s["frame"]).convert("RGB"))[box[1] : box[3], box[0] : box[2]]
        sheet.paste(Image.fromarray(a).resize((tw * scale, th * scale), Image.LANCZOS), (10, 24))
        dr.text((10, 4), "원본 프레임", font=lab, fill=(0, 0, 0))
        for k, x in enumerate(top5):
            fn = dict(cands)[x["font"]]
            r = render(fn, s["text"])
            rim = Image.fromarray(((~r) * 255).astype(np.uint8)).resize((tw * scale, th * scale), Image.LANCZOS)
            y = cell_h * (k + 1)
            sheet.paste(rim.convert("RGB"), (10, y + 24))
            dr.text((10, y + 4), f"{x['font']} · IoU {x['iou']:.3f} · 폭비 {x['aspect_err']:+.1%} · {x['size_pt']:.1f}pt", font=lab, fill=(160, 0, 0))
        sheet.save(OUT / f"compare_{n}.png")
    print("\n== 후보별 평균(전 표본) ==")
    summ = sorted(((k, float(np.mean([x["iou"] for x in v])), float(np.mean([abs(x["aspect_err"]) for x in v])), float(np.median([x["size_pt"] for x in v])))
                   for k, v in agg.items()), key=lambda x: -x[1])
    for k, iou, ae, pt in summ[:12]:
        print(f"   {k:<28} 평균 IoU {iou:.3f} · 평균 |폭비 오차| {ae:.1%} · 크기 중앙 {pt:.1f}pt")
    (OUT / "report.json").write_text(json.dumps({"samples": report, "summary": summ}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
