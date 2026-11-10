#!/usr/bin/env python3
"""clean 프레임 → 고유 슬라이드 타임라인 (Phase 2A · 장 경계 — 구 방식. 장수 집계의 정본은 slide_dense.py + slide_structure.py).

⚠️ 입력 프레임(collect/frames.py)은 장면 전환 검출 + pHash 중복 제거를 거쳐 실제 슬라이드의 약 44%를 놓친다(slide_boundary_check).
   여기의 제목 묶음·문자열 유틸(frame_text·norm·sim·is_latin)은 slide_dense 가 그대로 쓴다.

같은 슬라이드라도 부분 공개(줄이 하나씩 늘어남)·필기·선택 상자 때문에 프레임이 여러 장 잡힌다.
슈카월드 슬라이드는 장마다 제목 문장이 다르므로 **제목 줄(문자 인식)이 같은 프레임 = 같은 슬라이드**로 묶는다.
제목이 없는 프레임은 직전 슬라이드와 본문이 겹치면 같은 장, 아니면 새 장.

입력: private/style/style_measure_raw.json · private/ocr/<video_id>.jsonl · private/frames/<video_id>/index.json
출력: private/slides/<video_id>.json(슬라이드별 문구·시각 — 비공개) · tracks/syuka/analysis/slide_structure_syukaworld.md(집계만)

    python -m ozl.analyze.slide_timeline
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics
import sys
from collections import Counter
from difflib import SequenceMatcher

ROOT = pathlib.Path(__file__).resolve().parents[3]
FRAMES = ROOT / "private" / "frames"
RAW = ROOT / "private" / "style" / "style_measure_raw.json"
OCR = ROOT / "private" / "ocr"
OUT = ROOT / "private" / "slides"
OUT_MD = ROOT / "private" / "style" / "slide_structure_scenedetect.md"  # 장면 전환 기반(구) 집계 — 공개 집계는 slide_structure.py(촘촘 표본)가 쓴다

TITLE_SIM = 0.78   # 제목 문자열 유사도(정규화 후) 이 이상이면 같은 슬라이드
BODY_SIM = 0.6     # 제목 없는 프레임: 직전 슬라이드 본문과의 유사도
MIN_CONF = 0.3


def norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s).lower()


def sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def is_latin(s: str) -> bool:
    letters = re.findall(r"[A-Za-z가-힣]", s)
    return bool(letters) and sum(1 for c in letters if c.isascii()) / len(letters) >= 0.7 and len(letters) >= 8


def frame_text(meas: dict, ocr: dict) -> tuple[str | None, list[dict]]:
    """측정된 제목 줄 상자와 겹치는 인식 줄 = 제목. 나머지 = 본문(위→아래, 왼→오른쪽)."""
    lines = [ln for ln in ocr.get("lines", []) if ln["conf"] >= MIN_CONF and len(ln["text"].strip()) >= 2]
    parts, body = [], []
    t = meas.get("title")
    for ln in sorted(lines, key=lambda x: (x["y"], x["x"])):
        cy = ln["y"] + ln["h"] / 2
        if t and t["top"] - 10 <= cy <= t["top"] + t["h"] + 10 and ln["x"] < t["x1"]:
            parts.append(ln)  # 제목 줄이 여러 인식 상자로 나뉘어도 전부 제목으로 잇는다(첫 상자만 쓰면 서로 다른 장이 한 장으로 합쳐진다)
        else:
            body.append({"text": ln["text"].strip(), "x": ln["x"], "y": ln["y"], "w": ln["w"], "h": ln["h"]})
    title = " ".join(ln["text"].strip() for ln in sorted(parts, key=lambda x: x["x"])) or None
    return title, body


def build(v: dict) -> dict | None:
    vid = v["video_id"]
    op = OCR / f"{vid}.jsonl"
    if not op.exists():
        return None
    ocr = {}
    for line in op.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            ocr[d["file"]] = d
    frames = []
    for f in v["frames"]:
        if f["class"] != "clean" or f["file"] not in ocr:
            continue
        title, body = frame_text(f, ocr[f["file"]])
        frames.append({"file": f["file"], "t": int(f["file"].split("_")[1].split(".")[0]), "title": title, "body": body,
                       "layout": f.get("layout"), "n_images": len(f.get("images") or [])})
    frames.sort(key=lambda x: x["t"])
    groups: list[dict] = []
    order = 0
    revisits = 0
    for fr in frames:
        nt = norm(fr["title"] or "")
        nb = norm(" ".join(b["text"] for b in fr["body"]))
        hit = None
        if nt:
            best = max(groups, key=lambda g: sim(nt, g["ntitle"]), default=None)
            if best is not None and sim(nt, best["ntitle"]) >= TITLE_SIM:
                hit = best
        elif groups and sim(nb, groups[-1]["nbody"]) >= BODY_SIM:
            hit = groups[-1]
        if hit is None:
            order += 1
            hit = {"no": order, "ntitle": nt, "nbody": nb, "frames": []}
            groups.append(hit)
        elif hit is not groups[-1] and hit["frames"] and groups[-1]["frames"]:
            revisits += 1
            groups.remove(hit)  # 다시 돌아온 슬라이드를 '최근'으로 — 순서는 no(첫 등장)로 보존
            groups.append(hit)
        hit["frames"].append(fr)
        if len(nb) >= len(hit["nbody"]):
            hit["nbody"] = nb
        if nt and len(nt) > len(hit["ntitle"]):
            hit["ntitle"] = nt
    groups.sort(key=lambda g: g["no"])
    dur = v.get("duration_sec") or 0
    slides = []
    for i, g in enumerate(groups):
        best = max(g["frames"], key=lambda fr: sum(len(b["text"]) for b in fr["body"]))
        titles = Counter(fr["title"] for fr in g["frames"] if fr["title"])
        t0 = min(fr["t"] for fr in g["frames"])
        nxt = min((min(fr["t"] for fr in h["frames"]) for h in groups[i + 1 :]), default=dur)
        body = best["body"]
        slides.append({"no": g["no"], "t_first": t0, "t_last": max(fr["t"] for fr in g["frames"]), "dwell_sec": max(0, nxt - t0),
                       "n_frames": len(g["frames"]), "builds": len({len(fr["body"]) for fr in g["frames"]}),
                       "title": titles.most_common(1)[0][0] if titles else None, "body": [b["text"] for b in body],
                       "body_text_lines": sum(1 for b in body if 26 <= b["h"] <= 52),  # 본문 크기(26pt 안팎) 줄만
                       "layout": best["layout"], "n_images": best["n_images"], "best_frame": best["file"],
                       "has_en": any(is_latin(b["text"]) and 26 <= b["h"] <= 52 and len(b["text"]) >= 15 for b in body),  # 본문 크기 줄만(그림·차트 속 영문 제외)
                       "has_num": any(re.search(r"\d", b["text"]) for b in body),
                       "body_chars": sum(len(b["text"]) for b in body)})
    return {"video_id": vid, "duration_sec": dur, "n_clean": len(frames), "revisits": revisits, "slides": slides}


def med(xs, nd=1):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), nd) if xs else None


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else None


def main() -> int:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    vids = []
    for v in raw:
        r = build(v)
        if r is None:
            continue
        (OUT / f"{r['video_id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        vids.append(r)
    if not vids:
        print("문자 인식 결과 없음 — python -m ozl.analyze.slide_ocr 먼저", file=sys.stderr)
        return 1
    S = [s for r in vids for s in r["slides"]]
    per10 = [len(r["slides"]) / max(1, r["duration_sec"]) * 600 for r in vids]
    n_slides = [len(r["slides"]) for r in vids]
    dwell = [s["dwell_sec"] for s in S if s["dwell_sec"] > 0]
    titled = [s for s in S if s["title"]]
    tl = [len(s["title"]) for s in titled]
    lay = Counter(s["layout"] for s in S)
    thirds = [Counter(), Counter(), Counter()]
    en_by_third = [[0, 0], [0, 0], [0, 0]]
    for r in vids:
        n = len(r["slides"])
        for i, s in enumerate(r["slides"]):
            k = min(2, i * 3 // max(1, n))
            thirds[k][s["layout"]] += 1
            en_by_third[k][0] += int(s["has_en"])
            en_by_third[k][1] += 1
    L = ["# 슈카월드 슬라이드 구조 (대표 30편 · 고유 슬라이드 기준 집계)", "",
         "clean 프레임을 문자 인식한 뒤 **제목 문장이 같은 프레임을 한 장으로 묶어** 센 값이다(부분 공개·필기·선택 상자 변형을 한 장으로 합침).",
         "슬라이드 문구는 공개하지 않는다. 방법 = `src/ozl/analyze/slide_ocr.py`(macOS Vision) · `slide_timeline.py`.", "",
         "## 1. 장수와 리듬", "",
         f"- 영상 {len(vids)}편 · clean 프레임 {sum(r['n_clean'] for r in vids)}장 → **고유 슬라이드 {len(S)}장** (프레임/슬라이드 = {sum(r['n_clean'] for r in vids) / len(S):.2f})",
         f"- 편당 슬라이드 수 중앙값 **{med(n_slides)}장** (하위 10% {pct(n_slides, 0.1)} · 상위 10% {pct(n_slides, 0.9)}) · 영상 길이 중앙값 {med([r['duration_sec'] / 60 for r in vids])}분",
         f"- 10분당 슬라이드 중앙값 **{med(per10)}장** → 30분 세그먼트 ≈ {med(per10) * 3:.0f}장",
         f"- 장당 체류 시간 중앙값 **{med(dwell)}초** (하위 10% {pct(dwell, 0.1)}초 · 상위 10% {pct(dwell, 0.9)}초 · 평균 {statistics.mean(dwell):.0f}초)",
         f"- 부분 공개: 한 장이 2단계 이상으로 나뉘어 잡힌 비율 {sum(1 for s in S if s['builds'] >= 2) / len(S):.0%} · 앞 장으로 되돌아간 횟수 편당 중앙값 {med([r['revisits'] for r in vids])}회", "",
         "## 2. 한 장의 분량", "",
         f"- 제목 있는 슬라이드 {len(titled)}/{len(S)}장({len(titled) / len(S):.0%}) · 제목 길이 중앙값 **{med(tl)}자** (하위 10% {pct(tl, 0.1)}자 · 상위 10% {pct(tl, 0.9)}자 · 공백 포함)",
         f"- 본문 크기 글줄 수 중앙값 **{med([s['body_text_lines'] for s in S])}줄** (상위 10% {pct([s['body_text_lines'] for s in S], 0.9)}줄) · 인식된 전체 글자 수 중앙값 {med([s['body_chars'] for s in S])}자(그림·도표 속 글자 포함 · 상위 10% {pct([s['body_chars'] for s in S], 0.9)}자)",
         f"- **영문 원문 줄(본문 크기)이 있는 슬라이드 {sum(1 for s in S if s['has_en']) / len(S):.0%}** · 숫자가 있는 슬라이드 {sum(1 for s in S if s['has_num']) / len(S):.0%}", "",
         "## 3. 레이아웃 (고유 슬라이드 기준)", "", "| 유형 | 장수 | 비율 | 앞 1/3 | 가운데 | 뒤 1/3 |", "|---|---|---|---|---|---|"]
    for k, n in lay.most_common():
        L.append(f"| {k} | {n} | {n / len(S):.0%} | " + " | ".join(f"{thirds[i][k] / max(1, sum(thirds[i].values())):.0%}" for i in range(3)) + " |")
    e3 = [f"{a / max(1, b):.0%}" for a, b in en_by_third]
    L += ["", f"- 영문 원문 슬라이드 비율: 앞 1/3 {e3[0]} · 가운데 {e3[1]} · 뒤 1/3 {e3[2]}", "",
          "## 4. 영상별", "", "| 영상 | 길이(분) | clean 프레임 | 고유 슬라이드 | 10분당 | 체류 중앙(초) | 영문 원문 비율 |", "|---|---|---|---|---|---|---|"]
    for r in vids:
        sl = r["slides"]
        L.append(f"| {r['video_id']} | {round(r['duration_sec'] / 60)} | {r['n_clean']} | {len(sl)} | {len(sl) / max(1, r['duration_sec']) * 600:.1f} | {med([s['dwell_sec'] for s in sl if s['dwell_sec'] > 0])} | {sum(1 for s in sl if s['has_en']) / max(1, len(sl)):.0%} |")
    L += ["", "※ 장면 전환 검출이 놓친 슬라이드(직전 장과 거의 같은 화면)는 빠질 수 있어 장수는 하한에 가깝다. 정답 표본 대조 결과는 `private/style/slide_boundary_check.md`."]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:22]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
