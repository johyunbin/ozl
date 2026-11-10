#!/usr/bin/env python3
"""촘촘 표본 슬라이드 목록(private/slides_dense) → 레이아웃 판정 · 라벨 입력 · 공개 집계 (Phase 2A).

1) 대표 프레임에 slide_layout.classify 를 돌려 layout 을 채운다(문자 인식 글 상자를 뺀 잉크 = 그림).
2) 구성 라벨용 입력 private/slides_label/<video_id>.json: 3초 미만 순간 화면을 빼고 1..N 으로 번호를 다시 매긴 가벼운 목록.
3) 공개 집계 tracks/syuka/analysis/slide_structure_syukaworld.md (슬라이드 문구는 싣지 않는다).

    python -m ozl.analyze.slide_structure
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics
import subprocess
import sys
from collections import Counter

import numpy as np
from PIL import Image

from ozl.analyze.slide_layout import classify
from ozl.analyze.slide_timeline import is_latin

ROOT = pathlib.Path(__file__).resolve().parents[3]
DENSE = ROOT / "private" / "slides_dense"
REP = ROOT / "private" / "frames_dense"
LABEL = ROOT / "private" / "slides_label"
BOUNDARY = ROOT / "private" / "style" / "boundary"
BIN = ROOT / "tools" / "ocr" / "ocr"
OUT_MD = ROOT / "tracks" / "syuka" / "analysis" / "slide_structure_syukaworld.md"
DIALOG_RE = re.compile(r"저장하시겠습니까|저장하지 않은 변경|저장하지 않음")


def med(xs, nd=1):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), nd) if xs else None


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else None


def reocr(r: dict) -> None:
    """대표 프레임을 다시 문자 인식해 글줄 상자(폭 포함)를 채운다 — slide_dense 초기 실행분은 상자 폭이 0 으로 저장됐다."""
    vid = r["video_id"]
    todo = [s for s in r["slides"] if s.get("best_frame") and (REP / vid / s["best_frame"]).is_file() and not s.get("boxes_ok")]
    for i in range(0, len(todo), 40):
        batch = todo[i : i + 40]
        out = subprocess.run(["nice", "-n", "19", str(BIN), *[str(REP / vid / s["best_frame"]) for s in batch]], capture_output=True, text=True, timeout=1800)
        res = {}
        for line in out.stdout.splitlines():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            res[pathlib.Path(o["file"]).name] = o
        for s in batch:
            o = res.get(s["best_frame"])
            if not o:
                continue
            tb = s.get("title_box")
            body = []
            for ln in sorted((x for x in o.get("lines", []) if x["conf"] >= 0.3 and len(x["text"].strip()) >= 2), key=lambda x: (x["y"], x["x"])):
                cy = ln["y"] + ln["h"] / 2
                if tb and tb[1] - 10 <= cy <= tb[3] + 10 and ln["x"] < tb[2]:
                    continue  # 제목 줄
                body.append(ln)
            s["body"] = [ln["text"].strip() for ln in body]
            s["body_boxes"] = [[ln["x"], ln["y"], ln["w"], ln["h"]] for ln in body]
            s["boxes_ok"] = True
            s.pop("layout", None)


def enrich(r: dict) -> dict:
    vid = r["video_id"]
    reocr(r)
    for s in r["slides"]:
        keep = [i for i, t in enumerate(s["body"]) if not DIALOG_RE.search(t)]
        s["overlay_rep"] = len(keep) != len(s["body"])  # 대표 프레임에 저장 대화상자가 비친 경우
        s["body"] = [s["body"][i] for i in keep]
        s["body_boxes"] = [s["body_boxes"][i] for i in keep] if s.get("body_boxes") else []
        s["body_text_lines"] = sum(1 for b in s["body_boxes"] if 26 <= b[3] <= 52)
        s["body_chars"] = sum(len(t) for t in s["body"])
        s["has_en"] = any(is_latin(t) and 26 <= b[3] <= 52 and len(t) >= 15 for t, b in zip(s["body"], s["body_boxes"]))
        s["has_num"] = any(re.search(r"\d", t) for t in s["body"])
        fp = REP / vid / s.get("best_frame", "")
        if "layout" not in s and fp.is_file():
            a = np.asarray(Image.open(fp).convert("RGB"))
            c = classify(a, s.get("title_box"), s["body_boxes"], s.get("white_ratio"))
            s["layout"], s["graphics"] = c["layout"], c["graphics"]
            if c["layout"] == "media":
                s["kind"] = "media"
    return r


def label_input(r: dict) -> dict:
    out, n = [], 0
    for s in r["slides"]:
        if s["flash"]:
            continue
        n += 1
        out.append({"no": n, "t_first": s["t_first"], "dwell_sec": s["dwell_sec"], "kind": s["kind"], "title": s["title"],
                    "body": [t for t, b in zip(s["body"], s["body_boxes"]) if 26 <= b[3] <= 52],
                    "small_text": [t for t, b in zip(s["body"], s["body_boxes"]) if not 26 <= b[3] <= 52][:12],
                    "layout": s.get("layout"), "has_en": s["has_en"]})
    return {"video_id": r["video_id"], "duration_sec": r["duration_sec"], "slides": out}


def main() -> int:
    LABEL.mkdir(parents=True, exist_ok=True)
    vids = []
    for p in sorted(DENSE.glob("*.json")):
        r = enrich(json.loads(p.read_text(encoding="utf-8")))
        p.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        (LABEL / p.name).write_text(json.dumps(label_input(r), ensure_ascii=False, indent=1), encoding="utf-8")
        vids.append(r)
    if not vids:
        print("private/slides_dense 비어 있음 — python -m ozl.analyze.slide_dense 먼저", file=sys.stderr)
        return 1
    V = len(vids)
    per_video = []
    for r in vids:
        sl = [s for s in r["slides"] if not s["flash"] and s["kind"] == "slide"]
        per_video.append((r, sl))
    S = [s for _, sl in per_video for s in sl]
    n_slides = [len(sl) for _, sl in per_video]
    per10 = [len(sl) / max(1, r["duration_sec"]) * 600 for r, sl in per_video]
    dwell = [s["dwell_sec"] for s in S if s["dwell_sec"] > 0]
    titled = [s for s in S if s["title"]]
    tl = [len(s["title"]) for s in titled]
    lay = Counter(s.get("layout") or "unknown" for s in S)
    thirds, en3 = [Counter(), Counter(), Counter()], [[0, 0], [0, 0], [0, 0]]
    for _, sl in per_video:
        n = len(sl)
        for i, s in enumerate(sl):
            k = min(2, i * 3 // max(1, n))
            thirds[k][s.get("layout") or "unknown"] += 1
            en3[k][0] += int(s["has_en"])
            en3[k][1] += 1
    flash = sum(1 for r in vids for s in r["slides"] if s["flash"])
    media = sum(1 for r in vids for s in r["slides"] if not s["flash"] and s["kind"] == "media")
    cls = Counter()
    for r in vids:
        cls.update(r["classes"])
    tot = sum(cls.values())
    L = ["# 슈카월드 슬라이드 구조 (대표 30편 · 촘촘 표본 기준 집계)", "",
         f"영상을 {vids[0]['step_sec']}초마다 뽑아 문자 인식하고 **제목 문장이 같은 표본을 한 장으로 묶어** 센 값이다. 슬라이드 문구는 공개하지 않는다.",
         "방법 = `src/ozl/analyze/slide_dense.py`(표본·문자 인식·묶음) · `slide_layout.py`(레이아웃) · `slide_structure.py`(집계).", "",
         "## 1. 장수와 리듬", "",
         f"- 영상 {V}편 · 표본 {tot}장(clean {cls['clean'] / tot:.0%} · 대화상자 {cls['dialog'] / tot:.0%} · 흐림·빈 화면 {cls['faded'] / tot:.0%}) → **슬라이드 {len(S)}장** (그 밖에 전체 화면 영상·사진 {media}장 · {vids[0]['step_sec'] * 2}초 미만 순간 화면 {flash}장 제외)",
         f"- 편당 슬라이드 중앙값 **{med(n_slides)}장** (하위 10% {pct(n_slides, 0.1)} · 상위 10% {pct(n_slides, 0.9)}) · 영상 길이 중앙값 {med([r['duration_sec'] / 60 for r in vids])}분",
         f"- 10분당 슬라이드 중앙값 **{med(per10)}장** → 30분 한 주제 ≈ **{med(per10) * 3:.0f}장**",
         f"- 장당 체류 시간 중앙값 **{med(dwell)}초** (하위 10% {pct(dwell, 0.1)}초 · 상위 10% {pct(dwell, 0.9)}초 · 평균 {statistics.mean(dwell):.0f}초)",
         f"- 한 장 안에서 줄이 늘어나는 부분 공개가 잡힌 슬라이드 {sum(1 for s in S if s['builds'] >= 2) / len(S):.0%} · 앞 장으로 되돌아간 횟수 편당 중앙값 {med([r['revisits'] for r in vids])}회", "",
         "## 2. 한 장의 분량", "",
         f"- 제목 있는 슬라이드 {len(titled)}/{len(S)}장({len(titled) / len(S):.0%}) · 제목 길이 중앙값 **{med(tl)}자** (하위 10% {pct(tl, 0.1)}자 · 상위 10% {pct(tl, 0.9)}자 · 공백 포함)",
         f"- 본문 크기 글줄 수 중앙값 **{med([s['body_text_lines'] for s in S])}줄** (상위 10% {pct([s['body_text_lines'] for s in S], 0.9)}줄) · 인식된 전체 글자 수 중앙값 {med([s['body_chars'] for s in S])}자(그림·도표 속 글자 포함)",
         f"- **영문 원문 줄(본문 크기)이 있는 슬라이드 {sum(1 for s in S if s['has_en']) / len(S):.0%}** (앞 1/3 {en3[0][0] / max(1, en3[0][1]):.0%} · 가운데 {en3[1][0] / max(1, en3[1][1]):.0%} · 뒤 1/3 {en3[2][0] / max(1, en3[2][1]):.0%}) · 숫자가 있는 슬라이드 {sum(1 for s in S if s['has_num']) / len(S):.0%}", "",
         "## 3. 레이아웃", "",
         "문자 인식으로 찾은 제목·본문 글줄을 지운 뒤 남는 잉크 덩어리를 그림으로 본다. 표본 24장을 눈으로 대조했을 때 20장이 맞았다(틀린 4장은 도표·배너).", "",
         "| 유형 | 장수 | 비율 | 앞 1/3 | 가운데 | 뒤 1/3 |", "|---|---|---|---|---|---|"]
    names = {"image_left": "좌 그림 + 우 글", "text_only": "글만", "image_stack": "그림과 글 위아래", "image_full": "그림 위주(글 1줄 이하)", "image_pair": "그림 2장", "image_right": "우 그림 + 좌 글"}
    for k, n in lay.most_common():
        L.append(f"| {names.get(k, k)} | {n} | {n / len(S):.0%} | " + " | ".join(f"{thirds[i][k] / max(1, sum(thirds[i].values())):.0%}" for i in range(3)) + " |")
    L += ["", "## 4. 영상별", "", "| 영상 | 길이(분) | 슬라이드 | 10분당 | 체류 중앙(초) | 영문 원문 비율 |", "|---|---|---|---|---|---|"]
    for r, sl in per_video:
        L.append(f"| {r['video_id']} | {round(r['duration_sec'] / 60)} | {len(sl)} | {len(sl) / max(1, r['duration_sec']) * 600:.1f} | {med([s['dwell_sec'] for s in sl if s['dwell_sec'] > 0])} | {sum(1 for s in sl if s['has_en']) / max(1, len(sl)):.0%} |")
    bc = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(BOUNDARY.glob("*.json"))] if BOUNDARY.exists() else []
    if bc:
        d, m = sum(b["dense_titles"] for b in bc), sum(len(b["missed"]) for b in bc)
        L += ["", "## 5. 왜 촘촘 표본인가", "",
              f"처음에는 장면 전환 검출(PySceneDetect) 뒤 비슷한 이미지를 지우는 방식(pHash)으로 프레임을 뽑았다. 영상 {len(bc)}편을 4초 간격 표본과 대조하니 제목 {d}장 가운데 **{m}장({m / max(1, d):.0%})을 놓치고 있었다.** 좌 그림 + 우 글 배치가 되풀이되어 서로 다른 슬라이드가 같은 이미지로 판정된 것이 원인이다. 스타일 측정(색·폰트·여백)은 놓친 장이 있어도 값이 변하지 않지만, 장수와 구성은 촘촘 표본으로 다시 셌다."]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:26]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
