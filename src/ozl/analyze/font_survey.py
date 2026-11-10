#!/usr/bin/env python3
"""영상별 글자 크기 조사 — 문자 인식된 한글 줄을 맑은 고딕으로 렌더해 폭으로 em 을 역산 (Phase 2A · font_match 의 전수판).

font_match 는 사람이 문구를 적어 준 13줄(영상 2편)만 봤다. 독립 검증에서 영상마다 em 이 다르다는 지적이 나와 30편 전체를 잰다.
방법: private/ocr/<video_id>.jsonl 에서 본문 크기·한글 위주·신뢰도 높은 줄을 영상당 최대 60줄 고른다 →
       원본 줄의 잉크 폭 ÷ 같은 문구의 렌더 폭 = em(px). 한글은 Regular·Bold 의 글자 폭이 같아 굵기와 무관하다.
       문자 인식 오류로 문구가 다르면 폭이 어긋나므로 겹침(IoU) ≥ 0.5 인 줄만 쓴다.
출력: private/style/font_survey.json · 표준출력 요약 (집계는 style_measure 보고서 §5 가 읽어 싣는다)

    python -m ozl.analyze.font_survey
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics
import sys

import numpy as np
from PIL import ImageFont

from ozl.analyze.font_match import FRAMES, iou_best, render, target_line

ROOT = pathlib.Path(__file__).resolve().parents[3]
OCR = ROOT / "private" / "ocr"
RAW = ROOT / "private" / "style" / "style_measure_raw.json"
OUT = ROOT / "private" / "style" / "font_survey.json"
CANVAS_W = 1218.0
PER_VIDEO = 60

OFFICE = next((d for d in (pathlib.Path(f"/Applications/Microsoft {a}.app/Contents/Resources/DFonts") for a in ("PowerPoint", "Word", "Excel")) if d.exists()), None)


def hangul_ratio(s: str) -> float:
    t = re.sub(r"\s", "", s)
    return sum(1 for c in t if "가" <= c <= "힣") / max(1, len(t))


def main() -> int:
    if OFFICE is None or not (OFFICE / "malgun.ttf").exists():
        print("맑은 고딕(오피스 번들) 없음", file=sys.stderr)
        return 1
    reg = lambda s: ImageFont.truetype(str(OFFICE / "malgun.ttf"), s)  # noqa: E731
    raw = {v["video_id"]: v for v in json.loads(RAW.read_text(encoding="utf-8"))}
    res = []
    for op in sorted(OCR.glob("*.jsonl")):
        vid = op.stem
        cands = []
        for line in op.open(encoding="utf-8"):
            if not line.strip():
                continue
            d = json.loads(line)
            for ln in d.get("lines", []):
                t = ln["text"].strip()
                if ln["conf"] >= 0.9 and 30 <= ln["h"] <= 50 and 10 <= len(t) <= 34 and hangul_ratio(t) >= 0.85 and ln["x"] > 60 and ln["y"] > 120:
                    cands.append((d["file"], ln, t))
        step = max(1, len(cands) // PER_VIDEO)
        ems, used = [], 0
        for f, ln, t in cands[::step][:PER_VIDEO]:
            try:
                m, box = target_line(FRAMES / vid / f, int(ln["y"] + ln["h"] / 2), max(0, ln["x"] - 14), min(1152, ln["x"] + ln["w"] + 14))
            except Exception:  # noqa: BLE001
                continue
            th, tw = m.shape
            if not (20 <= th <= 44) or tw < 150:
                continue
            r = render(reg, t)
            iou = iou_best(m, r)
            used += 1
            if iou >= 0.5:
                ems.append(160 * tw / r.shape[1])
        pit = [p["pitch"] for f in raw[vid]["frames"] if f["class"] == "clean" for p in f.get("pitches", []) if 20 <= p["h"] <= 40 and 1.4 <= p["pitch"] / p["h"] <= 2.4]
        if len(ems) >= 5:
            em = statistics.median(ems)
            q = np.percentile(ems, [25, 75])
            res.append({"video_id": vid, "n": len(ems), "tried": used, "em_px": round(em, 2), "iqr": [round(float(q[0]), 2), round(float(q[1]), 2)],
                        "pt_13in": round(em / CANVAS_W * 960, 2), "pitch_px": statistics.median(pit) if pit else None,
                        "pitch_em": round(statistics.median(pit) / em, 3) if pit else None})
            print(f"[{vid}] {len(ems)}/{used}줄 · em {em:.2f}px(IQR {q[0]:.2f}~{q[1]:.2f}) = {em / CANVAS_W * 960:.1f}pt · 줄 간격 {statistics.median(pit) if pit else '-'}px = {statistics.median(pit) / em if pit else 0:.2f}em", flush=True)
        else:
            print(f"[{vid}] 표본 부족({len(ems)}/{used})", flush=True)
    ems = [r["em_px"] for r in res]
    summ = {"videos": len(res), "em_px_median": round(statistics.median(ems), 2), "em_px_min": min(ems), "em_px_max": max(ems),
            "pt_13in_median": round(statistics.median(ems) / CANVAS_W * 960, 2), "pt_13in_range": [round(min(ems) / CANVAS_W * 960, 1), round(max(ems) / CANVAS_W * 960, 1)],
            "pitch_em_median": round(statistics.median([r["pitch_em"] for r in res if r["pitch_em"]]), 3),
            "pitch_em_range": [min(r["pitch_em"] for r in res if r["pitch_em"]), max(r["pitch_em"] for r in res if r["pitch_em"])]}
    OUT.write_text(json.dumps({"summary": summ, "videos": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
