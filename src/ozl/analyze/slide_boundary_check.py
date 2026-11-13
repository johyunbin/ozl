#!/usr/bin/env python3
"""장 경계 정답 대조 — 장면 전환 검출(PySceneDetect)이 놓친 슬라이드를 촘촘한 표본으로 잰다 (Phase 2A-1 '정답 표본').

방법: 영상을 720p 로 다시 받아 4초마다 슬라이드 영역을 뽑고(1152×680 으로 맞춤) → clean 프레임만 문자 인식 → 제목 문장 열을 만든다.
       2표본 이상(≥ 8초) 연속으로 보인 제목 = 실제로 화면에 있던 슬라이드. 이것을 slide_timeline 의 고유 슬라이드 제목과 대조한다.
출력: private/style/slide_boundary_check.md · private/style/boundary/<video_id>.json   (제목 문구 포함 → 비공개)
부하: nice 19 · yt-dlp sleep · 영상은 끝나면 삭제.

    python -m ozl.analyze.slide_boundary_check <video_id> [<video_id> ...]
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

from ozl.analyze.slide_timeline import TITLE_SIM, frame_text, norm, sim
from ozl.analyze.style_measure import measure
from ozl.research import ledger

ROOT = pathlib.Path(__file__).resolve().parents[3]
TMP = ROOT / "private" / "style" / "boundary" / "_tmp"
OUT = ROOT / "private" / "style" / "boundary"
SLIDES = ROOT / "private" / "slides"
BIN = ROOT / "tools" / "ocr" / "ocr"
STEP = 4  # 초


def sh(cmd, **kw):
    return subprocess.run(["nice", "-n", "19", *cmd], capture_output=True, text=True, **kw)


def dense_titles(vid: str) -> list[dict]:
    d = TMP / vid
    d.mkdir(parents=True, exist_ok=True)
    video = d / "v.mp4"
    if not video.exists():
        ledger.require("youtube_video_download")   # 대장에서 유튜브 내려받기가 허용이 아니면 Blocked — 요청하지 않는다
        r = sh(["yt-dlp", "-q", "--no-warnings", "--sleep-requests", "2", "--sleep-interval", "3", "--throttled-rate", "100K",
                "-f", "bv*[height<=720][vcodec^=avc1][ext=mp4]/bv*[height<=720][ext=mp4]", "-o", str(video), f"https://www.youtube.com/watch?v={vid}"], timeout=3600)
        if not video.exists():
            raise RuntimeError(f"yt-dlp 실패: {r.stderr[-200:]}")
    if not any(d.glob("f_*.png")):
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vf", f"fps=1/{STEP},crop=iw*0.60:ih*0.63:0:0,scale=1152:680:flags=lanczos", str(d / "f_%05d.png")], timeout=3600)
    files = sorted(d.glob("f_*.png"))
    meas = {p.name: measure(p) for p in files}
    clean = [p for p in files if meas[p.name]["class"] == "clean"]
    ocr = {}
    for i in range(0, len(clean), 40):
        r = sh([str(BIN), *[str(p) for p in clean[i : i + 40]]], timeout=1200)
        for line in r.stdout.splitlines():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            ocr[pathlib.Path(o["file"]).name] = o
    rows = []
    for k, p in enumerate(files):
        m = meas[p.name]
        title = None
        if m["class"] == "clean" and p.name in ocr:
            title, _ = frame_text(m, ocr[p.name])
        rows.append({"t": k * STEP, "class": m["class"], "title": title})
    video.unlink(missing_ok=True)
    return rows


def check(vid: str) -> dict:
    rows = dense_titles(vid)
    # 연속 표본에서 같은 제목 → 구간
    runs: list[dict] = []
    for r in rows:
        if not r["title"]:
            continue
        nt = norm(r["title"])
        if runs and sim(nt, runs[-1]["n"]) >= TITLE_SIM:
            runs[-1]["t1"] = r["t"]
            runs[-1]["k"] += 1
        else:
            runs.append({"title": r["title"], "n": nt, "t0": r["t"], "t1": r["t"], "k": 1})
    # 같은 제목이 대화상자·흐림을 사이에 두고 다시 나온 경우 합치기
    uniq: list[dict] = []
    for r in runs:
        hit = next((u for u in uniq if sim(r["n"], u["n"]) >= TITLE_SIM), None)
        if hit:
            hit["t1"] = max(hit["t1"], r["t1"])
            hit["k"] += r["k"]
        else:
            uniq.append(dict(r))
    solid = [u for u in uniq if u["k"] >= 2]
    tl = json.loads((SLIDES / f"{vid}.json").read_text(encoding="utf-8"))
    tl_titles = [norm(s["title"]) for s in tl["slides"] if s["title"]]
    missed = [u for u in solid if max((sim(u["n"], t) for t in tl_titles), default=0) < TITLE_SIM]
    extra = [s["title"] for s in tl["slides"] if s["title"] and max((sim(norm(s["title"]), u["n"]) for u in uniq), default=0) < TITLE_SIM]
    cls = {c: sum(1 for r in rows if r["class"] == c) for c in ("clean", "dialog", "faded")}
    res = {"video_id": vid, "samples": len(rows), "classes": cls, "dense_titles": len(solid), "timeline_titled": len(tl_titles), "timeline_slides": len(tl["slides"]),
           "missed": [{"title": u["title"], "t0": u["t0"], "t1": u["t1"], "sec": (u["k"]) * STEP} for u in missed], "timeline_only": extra}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{vid}.json").write_text(json.dumps({**res, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(TMP / vid, ignore_errors=True)
    return res


def main(argv: list[str]) -> int:
    results = []
    for vid in argv:
        try:
            r = check(vid)
        except Exception as e:  # noqa: BLE001
            print(f"[{vid}] 실패: {e}", file=sys.stderr, flush=True)
            continue
        results.append(r)
        print(f"[{vid}] 촘촘 표본 제목 {r['dense_titles']} · 타임라인 제목 {r['timeline_titled']} · 놓침 {len(r['missed'])} · 타임라인에만 {len(r['timeline_only'])}", file=sys.stderr, flush=True)
    if not results:
        return 1
    L = ["# 장 경계 정답 대조 (촘촘 표본 4초 간격 vs 장면 전환 검출)", "",
         "| 영상 | 표본 | clean/dialog/faded | 촘촘 표본 제목(≥8초) | 타임라인 제목 | 놓친 슬라이드 | 놓침 비율 | 타임라인에만 |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        c = r["classes"]
        L.append(f"| {r['video_id']} | {r['samples']} | {c['clean']}/{c['dialog']}/{c['faded']} | {r['dense_titles']} | {r['timeline_titled']} | {len(r['missed'])} | {len(r['missed']) / max(1, r['dense_titles']):.0%} | {len(r['timeline_only'])} |")
    tot_d, tot_m = sum(r["dense_titles"] for r in results), sum(len(r["missed"]) for r in results)
    L += ["", f"- 합계: 촘촘 표본 제목 {tot_d}장 중 놓침 {tot_m}장 = **{tot_m / max(1, tot_d):.1%}**", "", "## 놓친 슬라이드", ""]
    for r in results:
        for m in r["missed"]:
            L.append(f"- {r['video_id']} {m['t0']}~{m['t1']}s({m['sec']}초): {m['title']}")
    (ROOT / "private" / "style" / "slide_boundary_check.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
