#!/usr/bin/env python3
"""대표 영상의 슬라이드 프레임 추출 (OZL Phase 1A-2).

흐름(영상 1편):
  yt-dlp 1080p mp4 → ffmpeg 로 슬라이드 영역 크롭·축소 프록시(2fps) → PySceneDetect ContentDetector 로 전환 시각 검출
  → 원본 1080p 에서 해당 시각 프레임을 크롭 PNG 로 저장 → imagehash(pHash) 중복 제거 → index.json → 원본 영상 삭제.
부하: nice 19 · 순차 1편 · yt-dlp sleep. 산출은 private/frames/<video_id>/ (비공개).

    python -m ozl.collect.frames private/meta/sample30_syukaworld.csv [--crop 0.56x0.65] [--threshold 12]
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
FRAMES = ROOT / "private" / "frames"
TMP = FRAMES / "_tmp"


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["nice", "-n", "19", *cmd], text=True, capture_output=True, **kw)


def download(vid: str) -> pathlib.Path | None:
    TMP.mkdir(parents=True, exist_ok=True)
    out = TMP / f"{vid}.mp4"
    if out.exists():
        return out
    r = sh(["yt-dlp", "-q", "--no-warnings", "--sleep-requests", "2", "--sleep-interval", "3",
            "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b", "--merge-output-format", "mp4",
            "-o", str(TMP / f"{vid}.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"])
    if r.returncode != 0:
        print(f"[{vid}] yt-dlp 실패: {r.stderr[-200:]}", file=sys.stderr)
        return None
    return out if out.exists() else next(TMP.glob(f"{vid}.*"), None)


def probe(video: pathlib.Path) -> tuple[int, int, float]:
    r = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(video)])
    d = json.loads(r.stdout)
    s = d["streams"][0]
    return int(s["width"]), int(s["height"]), float(d["format"]["duration"])


def detect(video: pathlib.Path, cw: float, ch: float, threshold: float, vid: str) -> list[float]:
    proxy = TMP / f"{vid}_proxy.mp4"
    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
        "-vf", f"crop=iw*{cw}:ih*{ch}:0:0,scale=640:-2,fps=2", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", str(proxy)])
    from scenedetect import ContentDetector, SceneManager, open_video
    v = open_video(str(proxy))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold, min_scene_len=4))  # 2fps → 2초
    sm.detect_scenes(v, show_progress=False)
    scenes = sm.get_scene_list()
    times = [s[0].get_seconds() for s in scenes]
    if times and times[0] > 1.0:
        times.insert(0, 0.5)
    proxy.unlink(missing_ok=True)
    return times


def grab(video: pathlib.Path, t: float, cw: float, ch: float, out: pathlib.Path) -> bool:
    r = sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t + 0.8:.2f}", "-i", str(video),
            "-vf", f"crop=iw*{cw}:ih*{ch}:0:0", "-frames:v", "1", str(out)])
    return r.returncode == 0 and out.exists()


def dedupe(paths: list[pathlib.Path], max_dist: int = 6) -> list[pathlib.Path]:
    from PIL import Image
    import imagehash
    kept, hashes = [], []
    for p in paths:
        try:
            h = imagehash.phash(Image.open(p))
        except Exception:  # noqa: BLE001
            p.unlink(missing_ok=True)
            continue
        if any(h - k <= max_dist for k in hashes):
            p.unlink(missing_ok=True)
            continue
        hashes.append(h)
        kept.append(p)
    return kept


def process(vid: str, cw: float, ch: float, threshold: float, meta: dict) -> dict:
    d = FRAMES / vid
    if (d / "index.json").exists():
        return json.loads((d / "index.json").read_text(encoding="utf-8"))
    d.mkdir(parents=True, exist_ok=True)
    video = download(vid)
    if not video:
        return {"video_id": vid, "error": "download"}
    w, h, dur = probe(video)
    t0 = time.time()
    times = detect(video, cw, ch, threshold, vid)
    paths = []
    for i, t in enumerate(times):
        out = d / f"{i:04d}_{int(t):05d}.png"
        if grab(video, t, cw, ch, out):
            paths.append(out)
    kept = dedupe(paths)
    idx = {"video_id": vid, **meta, "width": w, "height": h, "duration_sec": round(dur), "crop": f"{cw}x{ch}", "threshold": threshold,
           "transitions": len(times), "frames_kept": len(kept), "frames": [p.name for p in kept], "elapsed_sec": round(time.time() - t0, 1)}
    (d / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    video.unlink(missing_ok=True)
    return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--crop", default="0.60x0.63")
    ap.add_argument("--threshold", type=float, default=12.0)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    cw, ch = (float(x) for x in a.crop.split("x"))
    rows = list(csv.DictReader(open(a.csv, encoding="utf-8")))
    if a.limit:
        rows = rows[: a.limit]
    results = []
    for r in rows:
        vid = r["video_id"]
        print(f"[{vid}] {r.get('stratum','')} {r.get('published_kst','')[:10]} {r.get('duration_min','')}분 시작", file=sys.stderr, flush=True)
        res = process(vid, cw, ch, a.threshold, {k: r.get(k) for k in ("stratum", "published_kst", "duration_min", "view_count", "topic", "title")})
        results.append(res)
        print(f"[{vid}] 전환 {res.get('transitions')} → 보관 {res.get('frames_kept')} ({res.get('elapsed_sec')}s)", file=sys.stderr, flush=True)
    (FRAMES / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r for r in results if "error" not in r]
    print(f"done: {len(ok)}/{len(results)} · frames {sum(r['frames_kept'] for r in ok)} · avg transitions {sum(r['transitions'] for r in ok)/max(1,len(ok)):.0f}")
    shutil.rmtree(TMP, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
