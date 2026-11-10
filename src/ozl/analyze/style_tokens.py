#!/usr/bin/env python3
"""슬라이드 프레임 → 스타일 토큰 (Phase 2A).

입력: private/frames/<video_id>/*.png (슬라이드 영역 크롭, 1080p 원본 기준)
측정:
  - 배경: 흰색 비율(밝기 ≥ 245) — 슬라이드 프레임 판별(흰 배경 ≥ 55%)
  - 색 팔레트: 비배경 픽셀을 32단계로 양자화해 상위 색(hex, 비율) — 제목 적갈색·강조 빨강·본문 검정 후보
  - 제목 밴드: 상단 0~14% 영역의 비배경 주색 → 제목 색 후보
  - 레이아웃: 좌/우 절반의 '잉크'(비배경) 밀도 → 좌 이미지·우 텍스트 비율, 상단 여백(첫 잉크 행 위치), 좌측 여백
  - 전환 리듬: index.json 의 전환 시각 간격 분포(장당 체류 초)
출력: tracks/syuka/analysis/style_tokens_syukaworld.md (집계) · private/style/style_tokens_raw.json
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
from collections import Counter

import numpy as np
from PIL import Image

from ozl.analyze.style_measure import classify

ROOT = pathlib.Path(__file__).resolve().parents[3]
FRAMES = ROOT / "private" / "frames"
OUT_MD = ROOT / "tracks" / "syuka" / "analysis" / "style_tokens_syukaworld.md"
OUT_RAW = ROOT / "private" / "style" / "style_tokens_raw.json"
WHITE = 245


def hexc(rgb) -> str:
    return "#%02X%02X%02X" % tuple(int(x) for x in rgb)


def quantize(arr: np.ndarray, step: int = 32) -> Counter:
    q = (arr // step) * step + step // 2
    keys = q[:, 0].astype(np.int64) * 65536 + q[:, 1].astype(np.int64) * 256 + q[:, 2].astype(np.int64)
    c = Counter(keys.tolist())
    return c


def key_to_hex(k: int) -> str:
    return "#%02X%02X%02X" % (k >> 16, (k >> 8) & 255, k & 255)


def analyze_frame(p: pathlib.Path) -> dict | None:
    im = Image.open(p).convert("RGB")
    a = np.asarray(im)
    if classify(a.astype(np.int16)) != "clean":  # 주석 도구 대화상자·흐림 프레임 제외(색·여백 오염원 — style_measure.py)
        return None
    h, w, _ = a.shape
    lum = a.mean(axis=2)
    white = lum >= WHITE
    white_ratio = float(white.mean())
    if white_ratio < 0.55:  # 흰 배경 슬라이드가 아닌 프레임(사진 풀샷·전환 중) 제외
        return None
    ink = ~white
    nonbg = a[ink]
    pal = quantize(nonbg) if len(nonbg) else Counter()
    # 채도 있는 색(빨강 계열)과 무채색 분리
    def sat(k):
        r, g, b = k >> 16, (k >> 8) & 255, k & 255
        return max(r, g, b) - min(r, g, b)
    chroma = Counter({k: v for k, v in pal.items() if sat(k) >= 60})
    gray = Counter({k: v for k, v in pal.items() if sat(k) < 60})
    # 제목 밴드(상단 14%)
    band = a[: int(h * 0.14)]
    bink = band[band.mean(axis=2) < WHITE]
    band_pal = quantize(bink) if len(bink) else Counter()
    band_chroma = Counter({k: v for k, v in band_pal.items() if sat(k) >= 60})
    # 레이아웃
    rows = ink.mean(axis=1)
    cols = ink.mean(axis=0)
    first_row = int(np.argmax(rows > 0.01)) if (rows > 0.01).any() else 0
    first_col = int(np.argmax(cols > 0.01)) if (cols > 0.01).any() else 0
    left = float(ink[:, : w // 2].mean())
    right = float(ink[:, w // 2 :].mean())
    return {
        "file": p.name, "w": w, "h": h, "white_ratio": round(white_ratio, 3), "ink_ratio": round(1 - white_ratio, 3),
        "top_margin_pct": round(first_row / h * 100, 1), "left_margin_pct": round(first_col / w * 100, 1),
        "left_ink": round(left, 3), "right_ink": round(right, 3),
        "chroma_top": [(key_to_hex(k), round(v / max(1, len(nonbg)), 4)) for k, v in chroma.most_common(4)],
        "gray_top": [(key_to_hex(k), round(v / max(1, len(nonbg)), 4)) for k, v in gray.most_common(3)],
        "title_band_chroma": [(key_to_hex(k), v) for k, v in band_chroma.most_common(2)],
    }


def main() -> int:
    vids = [d for d in FRAMES.iterdir() if d.is_dir() and (d / "index.json").exists()]
    per_video, all_frames = [], []
    for d in vids:
        idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
        frames = [analyze_frame(d / f) for f in idx.get("frames", [])]
        frames = [f for f in frames if f]
        times = sorted(int(f.split("_")[1].split(".")[0]) for f in idx.get("frames", []))
        gaps = [b - a for a, b in zip(times, times[1:]) if b - a > 0]
        per_video.append({"video_id": idx["video_id"], "title": idx.get("title"), "duration_sec": idx.get("duration_sec"),
                          "transitions": idx.get("transitions"), "frames_kept": idx.get("frames_kept"), "slide_frames": len(frames),
                          "dwell_median_sec": statistics.median(gaps) if gaps else None,
                          "slides_per_10min": round(len(frames) / max(1, idx.get("duration_sec", 1)) * 600, 1),
                          "frames": frames})
        all_frames.extend(frames)
    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    OUT_RAW.write_text(json.dumps(per_video, ensure_ascii=False, indent=1), encoding="utf-8")
    if not all_frames:
        print("슬라이드 프레임 없음")
        return 1
    chroma = Counter()
    gray = Counter()
    band = Counter()
    for f in all_frames:
        for hx, r in f["chroma_top"]:
            chroma[hx] += r
        for hx, r in f["gray_top"]:
            gray[hx] += r
        for hx, v in f["title_band_chroma"]:
            band[hx] += v
    n = len(all_frames)
    aspect = Counter(f"{round(f['w']/f['h'],2)}" for f in all_frames)
    lines = ["# 슈카월드 슬라이드 스타일 토큰 (집계 · 대표 30편 1080p 프레임)", "",
             f"- 분석 프레임 {n}개(흰 배경 ≥55% · 대화상자·흐림 프레임 제외) / 영상 {len(per_video)}편 · 크롭 비율 분포(w/h): {aspect.most_common(3)}",
             f"- 흰 배경 비율 중앙값 {statistics.median(f['white_ratio'] for f in all_frames):.2f} · 잉크(글·그림) 비율 중앙값 {statistics.median(f['ink_ratio'] for f in all_frames):.2f}",
             f"- 상단 여백 중앙값 {statistics.median(f['top_margin_pct'] for f in all_frames):.1f}% · 좌측 여백 중앙값 {statistics.median(f['left_margin_pct'] for f in all_frames):.1f}%",
             f"- 좌/우 잉크 밀도 중앙값 {statistics.median(f['left_ink'] for f in all_frames):.3f} / {statistics.median(f['right_ink'] for f in all_frames):.3f} (좌 이미지·우 텍스트면 좌 > 우)",
             f"- (참고) 추출 프레임 간격 중앙값 {statistics.median([v['dwell_median_sec'] for v in per_video if v['dwell_median_sec']]):.0f}초 · 10분당 {statistics.median([v['slides_per_10min'] for v in per_video]):.1f}장 — 장면 전환 검출 기준이라 실제 장수보다 적다. 장수·체류 시간의 정본은 `slide_structure_syukaworld.md`(촘촘 표본).",
             "", "## 유채색 팔레트(제목·강조 후보) — 32단계 양자화, 프레임 평균 비율 상위", "", "| hex | 평균 비율 |", "|---|---|"]
    for hx, r in chroma.most_common(8):
        lines.append(f"| `{hx}` | {r / n:.4f} |")
    lines += ["", "## 제목 밴드(상단 14%) 유채색 상위", "", "| hex | 가중치 |", "|---|---|"]
    for hx, v in band.most_common(5):
        lines.append(f"| `{hx}` | {v} |")
    lines += ["", "## 무채색(본문 검정·회색) 상위", "", "| hex | 평균 비율 |", "|---|---|"]
    for hx, r in gray.most_common(4):
        lines.append(f"| `{hx}` | {r / n:.4f} |")
    lines += ["", "## 영상별", "", "| 영상 | 길이(분) | 전환 | 보관 | 슬라이드 프레임 | 체류 중앙(초) | 10분당 장수 |", "|---|---|---|---|---|---|---|"]
    for v in sorted(per_video, key=lambda x: x["video_id"]):
        lines.append(f"| {v['video_id']} | {round((v['duration_sec'] or 0)/60)} | {v['transitions']} | {v['frames_kept']} | {v['slide_frames']} | {v['dwell_median_sec'] or '-'} | {v['slides_per_10min']} |")
    lines += ["", "※ 양자화 hex는 32단계 중심값이라 실제 색은 ±16 범위. 글자 색·크기·폰트의 정밀값은 `style_measure_syukaworld.md`(심지 색·폰트 대조)를 본다."]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:9]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
