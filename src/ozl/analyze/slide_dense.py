#!/usr/bin/env python3
"""촘촘 표본으로 슬라이드 전수 목록 만들기 (Phase 2A · 장 경계 — slide_timeline 의 대체 입력).

왜: 장면 전환 검출 + pHash 중복 제거(collect/frames.py)는 배치가 같은 슬라이드(좌 그림 + 우 글)를 같은 장으로 보고 지운다.
     정답 대조(slide_boundary_check) 결과 한 편에서 제목 68장 중 26장(38%)을 놓쳤다 → 일정 간격으로 전부 뽑아 제목 문장으로 가른다.
흐름(영상 1편): yt-dlp 720p → ffmpeg 3초마다 슬라이드 영역(1152×680 으로 맞춤) → 프레임 분류·제목 줄 측정(style_measure.measure)
     → clean 프레임 문자 인식(직전 인식 프레임과 거의 같으면 재사용) → 제목이 같은 표본을 한 장으로 묶음 → 장마다 대표 프레임 1장 보관 → 영상·임시 프레임 삭제.
출력(비공개): private/dense/<video_id>.json(표본 열) · private/slides_dense/<video_id>.json(슬라이드 — slide_timeline 과 같은 꼴) · private/frames_dense/<video_id>/s<no>_<t>.png
부하: nice 19 · yt-dlp sleep. 재개 가능(끝난 영상은 건너뜀).

    python -m ozl.analyze.slide_dense private/meta/sample30_syukaworld.csv [--part 0/2]
    python -m ozl.analyze.slide_dense rebuild      # 저장된 표본 열로 슬라이드 목록만 다시 묶기
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import shutil
import subprocess
import sys
from collections import Counter

import numpy as np
from PIL import Image

from ozl.analyze.slide_timeline import BODY_SIM, TITLE_SIM, frame_text, is_latin, norm, sim
from ozl.analyze.style_measure import measure
from ozl.research import ledger

ROOT = pathlib.Path(__file__).resolve().parents[3]
TMP = ROOT / "private" / "dense" / "_tmp"
DENSE = ROOT / "private" / "dense"
SLIDES = ROOT / "private" / "slides_dense"
REP = ROOT / "private" / "frames_dense"
BIN = ROOT / "tools" / "ocr" / "ocr"
STEP = 3          # 초
SAME_THUMB = 1.2  # 64×38 회색 축소본의 평균 절대 차이가 이보다 작으면 같은 화면 → 문자 인식 재사용


def sh(cmd, **kw):
    return subprocess.run(["nice", "-n", "19", *cmd], capture_output=True, text=True, **kw)


def thumb(p: pathlib.Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("L").resize((64, 38), Image.BILINEAR)).astype(np.int16)


def sample(vid: str) -> tuple[list[dict], dict[int, pathlib.Path], float]:
    d = TMP / vid
    d.mkdir(parents=True, exist_ok=True)
    video = d / "v.mp4"
    if not video.exists() and not any(d.glob("f_*.png")):
        ledger.require("youtube_video_download")   # 대장에서 유튜브 내려받기가 허용이 아니면 Blocked — 요청하지 않는다
        r = sh(["yt-dlp", "-q", "--no-warnings", "--sleep-requests", "2", "--sleep-interval", "3", "--throttled-rate", "100K",
                "-f", "bv*[height<=720][vcodec^=avc1][ext=mp4]/bv*[height<=720][ext=mp4]", "-o", str(video), f"https://www.youtube.com/watch?v={vid}"], timeout=5400)
        if not video.exists():
            raise RuntimeError(f"yt-dlp 실패: {r.stderr[-200:]}")
    dur = 0.0
    if video.exists():
        pr = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)])
        dur = float(pr.stdout.strip() or 0)
    if not any(d.glob("f_*.png")):
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vf", f"fps=1/{STEP},crop=iw*0.60:ih*0.63:0:0,scale=1152:680:flags=lanczos", str(d / "f_%05d.png")], timeout=5400)
    video.unlink(missing_ok=True)
    files = sorted(d.glob("f_*.png"))
    meas = {p.name: measure(p) for p in files}
    # 문자 인식: clean 만, 직전 인식 프레임과 거의 같으면 재사용
    todo, reuse, last_t = [], {}, None
    last_name = None
    for p in files:
        if meas[p.name]["class"] != "clean":
            last_t = None
            continue
        t = thumb(p)
        if last_t is not None and float(np.abs(t - last_t).mean()) < SAME_THUMB:
            reuse[p.name] = last_name
        else:
            todo.append(p)
            last_t, last_name = t, p.name
    ocr = {}
    for i in range(0, len(todo), 40):
        r = sh([str(BIN), *[str(p) for p in todo[i : i + 40]]], timeout=1800)
        for line in r.stdout.splitlines():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            ocr[pathlib.Path(o["file"]).name] = o
    rows, paths = [], {}
    for k, p in enumerate(files):
        m = meas[p.name]
        row = {"t": k * STEP, "class": m["class"], "title": None, "body": [], "white": m.get("white_ratio"), "title_box": None}
        if m["class"] == "clean":
            o = ocr.get(p.name) or ocr.get(reuse.get(p.name, ""))
            if o:
                title, body = frame_text(m, o)
                row.update({"title": title, "body": body, "ocr_reused": p.name in reuse})
            if m.get("title"):
                tb = m["title"]
                row["title_box"] = [tb["x0"], tb["top"], tb["x1"], tb["top"] + tb["h"]]
        rows.append(row)
        paths[row["t"]] = p
    return rows, paths, dur or len(files) * STEP


def fix_split_title(r: dict) -> dict:
    """초기 실행분 보정: 제목 띠(title_box) 안에 있는데 본문으로 빠진 인식 줄을 제목 뒤에 잇는다."""
    tb = r.get("title_box")
    if not tb or not r.get("body"):
        return r
    keep, extra = [], []
    for b in r["body"]:
        cy = b["y"] + b["h"] / 2
        (extra if tb[1] - 10 <= cy <= tb[3] + 10 and b["x"] < tb[2] else keep).append(b)
    if extra:
        r = dict(r)
        r["title"] = " ".join([r["title"] or ""] + [b["text"] for b in sorted(extra, key=lambda b: b["x"])]).strip() or None
        r["body"] = keep
    return r


def build_slides(vid: str, rows: list[dict], dur: float, step: int = STEP) -> dict:
    rows = [fix_split_title(r) for r in rows]
    slides: list[dict] = []
    cur = None  # 지금 화면에 있는 슬라이드(재방문하면 예전 슬라이드로 돌아간다)
    revisits = 0
    for r in rows:
        if r["class"] != "clean":
            if cur is not None:
                cur["sec"] += step  # 대화상자·흐림 표본은 직전 슬라이드가 떠 있던 시간으로 친다
            continue
        nt = norm(r["title"] or "")
        nb = norm(" ".join(b["text"] for b in r["body"]))
        hit = None
        if nt:
            if cur is not None and sim(nt, cur["nt"]) >= TITLE_SIM:
                hit = cur
            else:
                best = max(slides, key=lambda s: sim(nt, s["nt"]), default=None)
                if best is not None and best["nt"] and sim(nt, best["nt"]) >= TITLE_SIM:
                    hit = best
                    revisits += 1
        elif cur is not None and ((not cur["nt"] and (sim(nb, cur["nb"]) >= BODY_SIM or (not nb and not cur["nb"]))) or (cur["nt"] and nb and sim(nb, cur["nb"]) >= BODY_SIM)):
            hit = cur  # 제목 없는 표본: 지금 슬라이드와 본문이 같으면(둘 다 글이 없어도) 같은 장
        if hit is None:
            hit = {"nt": nt, "nb": nb, "rows": [], "sec": 0}
            slides.append(hit)
        hit["rows"].append(r)
        hit["sec"] += step
        cur = hit
        if len(nb) >= len(hit["nb"]):
            hit["nb"] = nb
        if len(nt) > len(hit["nt"]):
            hit["nt"] = nt
    out = []
    for i, s in enumerate(slides):
        rs = s["rows"]
        best = max(rs, key=lambda r: (sum(len(b["text"]) for b in r["body"]), r["t"]))
        titles = Counter(r["title"] for r in rs if r["title"])
        body = best["body"]
        white = best.get("white") or 0
        out.append({"no": i + 1, "t_first": rs[0]["t"], "t_last": rs[-1]["t"], "dwell_sec": s["sec"], "n_samples": len(rs), "flash": s["sec"] < 2 * step,
                    "builds": len({sum(1 for b in r["body"] if 26 <= b["h"] <= 52) for r in rs}),
                    "title": titles.most_common(1)[0][0] if titles else None, "body": [b["text"] for b in body],
                    "body_boxes": [[b["x"], b["y"], b.get("w", 0), b["h"]] for b in body], "title_box": best.get("title_box"),
                    "body_text_lines": sum(1 for b in body if 26 <= b["h"] <= 52), "best_t": best["t"], "sample_ts": [r["t"] for r in rs], "white_ratio": white,
                    "kind": "media" if white < 0.35 else "slide",
                    "has_en": any(is_latin(b["text"]) and 26 <= b["h"] <= 52 and len(b["text"]) >= 15 for b in body),
                    "has_num": any(re.search(r"\d", b["text"]) for b in body), "body_chars": sum(len(b["text"]) for b in body)})
    return {"video_id": vid, "duration_sec": int(dur), "step_sec": step, "n_samples": len(rows),
            "classes": dict(Counter(r["class"] for r in rows)), "revisits": revisits, "slides": out}


def process(vid: str) -> dict:
    sp = SLIDES / f"{vid}.json"
    if sp.exists():
        return json.loads(sp.read_text(encoding="utf-8"))
    rows, paths, dur = sample(vid)
    res = build_slides(vid, rows, dur)
    rep = REP / vid
    rep.mkdir(parents=True, exist_ok=True)
    for s in res["slides"]:
        src = paths.get(s["best_t"])
        if src and src.exists():
            name = f"s{s['no']:03d}_{s['best_t']:05d}.png"
            shutil.copyfile(src, rep / name)
            s["best_frame"] = name
    DENSE.mkdir(parents=True, exist_ok=True)
    SLIDES.mkdir(parents=True, exist_ok=True)
    (DENSE / f"{vid}.json").write_text(json.dumps({"video_id": vid, "step_sec": STEP, "rows": rows}, ensure_ascii=False), encoding="utf-8")
    sp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(TMP / vid, ignore_errors=True)
    return res


def rebuild() -> int:
    """저장된 표본 열(private/dense/*.json)만으로 슬라이드 목록을 다시 묶는다 — 묶음 로직을 고쳤을 때 영상을 다시 받지 않기 위함.
    대표 프레임은 이미 저장된 것 중 그 슬라이드의 표본 시각과 맞는 것을 다시 잇는다(없으면 비움)."""
    n = 0
    for p in sorted(DENSE.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        vid = d["video_id"]
        sp = SLIDES / f"{vid}.json"
        dur = json.loads(sp.read_text(encoding="utf-8"))["duration_sec"] if sp.exists() else len(d["rows"]) * d.get("step_sec", STEP)
        res = build_slides(vid, d["rows"], dur, d.get("step_sec", STEP))
        saved = {int(f.stem.split("_")[1]): f.name for f in (REP / vid).glob("s*_*.png")} if (REP / vid).exists() else {}
        by_t = {r["t"]: fix_split_title(r) for r in d["rows"]}
        for s in res["slides"]:
            t = s["best_t"] if s["best_t"] in saved else next((x for x in reversed(s["sample_ts"]) if x in saved), None)
            if t is not None:
                s["best_frame"] = saved[t]
                if t != s["best_t"]:  # 대표 프레임이 다른 표본이면 제목 상자도 그 표본의 것으로(안 맞추면 재인식 때 제목이 본문에 섞인다)
                    s["title_box"] = by_t[t].get("title_box")
                    s["rep_t"] = t
        sp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        n += 1
        sl = [x for x in res["slides"] if not x["flash"]]
        print(f"[{vid}] 슬라이드 {len(sl)}(+순간 {len(res['slides']) - len(sl)}) · 대표 프레임 {sum(1 for x in sl if x.get('best_frame'))}/{len(sl)} · 재방문 {res['revisits']}", file=sys.stderr)
    print(f"rebuilt {n}")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["rebuild"]:
        return rebuild()
    rows = list(csv.DictReader(open(argv[0], encoding="utf-8")))
    part = (0, 1)
    if "--part" in argv:
        a, b = argv[argv.index("--part") + 1].split("/")
        part = (int(a), int(b))
    vids = [r["video_id"] for i, r in enumerate(rows) if i % part[1] == part[0]]
    ok = 0
    for vid in vids:
        try:
            r = process(vid)
        except Exception as e:  # noqa: BLE001
            print(f"[{vid}] 실패: {e}", file=sys.stderr, flush=True)
            continue
        ok += 1
        sl = [s for s in r["slides"] if not s["flash"]]
        print(f"[{vid}] 표본 {r['n_samples']} · 슬라이드 {len(sl)}(+순간 {len(r['slides']) - len(sl)}) · 제목 있음 {sum(1 for s in sl if s['title'])} · {r['duration_sec'] // 60}분", file=sys.stderr, flush=True)
    print(f"done {ok}/{len(vids)}")
    return 0 if ok == len(vids) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
