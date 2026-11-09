#!/usr/bin/env python3
"""전사 엔진 파일럿 — Trading 보유 다글로 전사 vs whisper.cpp large-v3-turbo (OZL Phase 1A-3).

연도×길이 층화 5편을 골라 오디오(m4a)를 받고 whisper.cpp(Metal)로 전사한 뒤,
기존 다글로 전사와 정규화 문자열 유사도·숫자 토큰 일치율·처리 시간·최대 메모리를 기록한다.
부하 규칙: nice 19 · 스레드 6 · 순차 1편씩 · yt-dlp sleep.
출력: private/pilot/<video_id>/{audio.m4a, whisper.txt, whisper.vtt, daglo.txt, compare.json} + private/pilot/report.md
"""
from __future__ import annotations

import csv
import difflib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
EXPORT = ROOT / "private" / "transcripts" / "trading_export"
PILOT = ROOT / "private" / "pilot"
MODEL = ROOT / "private" / "models" / "ggml-large-v3-turbo.bin"
YEARS = ["2019", "2021", "2023", "2025", "2026"]


def pick_samples() -> list[dict]:
    rows = list(csv.DictReader((EXPORT / "index.csv").open(encoding="utf-8")))
    picks = []
    for y in YEARS:
        cands = [r for r in rows if r["channel"] == "syuka" and r["transcript_source"] == "daglo"
                 and (r["upload_at"] or "").startswith(y) and 900 <= int(r["duration_sec"] or 0) <= 3600]
        if not cands:
            continue
        cands.sort(key=lambda r: int(r["duration_sec"]))
        picks.append(cands[len(cands) // 2])  # 길이 중앙값
    return picks


def norm(s: str) -> str:
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", s)
    s = re.sub(r"[^\w가-힣]+", "", s)
    return s.lower()


def numbers(s: str) -> list[str]:
    return re.findall(r"\d[\d,\.]*", s)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def transcribe(vid: str, d: pathlib.Path) -> dict:
    audio = d / "audio.m4a"
    if not audio.exists():
        r = run(["yt-dlp", "-q", "--no-warnings", "--sleep-requests", "2", "-f", "bestaudio[ext=m4a]/bestaudio",
                 "-o", str(d / "audio.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"])
        if r.returncode != 0:
            return {"error": "yt-dlp: " + r.stderr[-300:]}
        got = next(d.glob("audio.*"), None)
        if got and got != audio:
            got.rename(audio)
    wav = d / "audio16k.wav"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
    t0 = time.time()
    r = run(["/usr/bin/time", "-l", "nice", "-n", "19", "whisper-cli", "-m", str(MODEL), "-l", "ko", "-t", "6",
             "-f", str(wav), "-otxt", "-ovtt", "-of", str(d / "whisper"), "-nt"])
    elapsed = time.time() - t0
    rss = None
    m = re.search(r"(\d+)\s+maximum resident set size", r.stderr)
    if m:
        rss = int(m.group(1)) / (1024 ** 3) if int(m.group(1)) > 1e8 else int(m.group(1)) / (1024 ** 2)  # macOS는 bytes
    wav.unlink(missing_ok=True)
    return {"elapsed_sec": round(elapsed, 1), "max_rss_gb": round(rss, 2) if rss else None, "rc": r.returncode}


def compare(whisper_txt: str, daglo_txt: str, head: int = 20000) -> dict:
    a, b = norm(whisper_txt)[:head], norm(daglo_txt)[:head]
    ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    na, nb = set(numbers(whisper_txt)), set(numbers(daglo_txt))
    return {
        "char_similarity": round(ratio, 4),
        "len_whisper": len(whisper_txt), "len_daglo": len(daglo_txt),
        "numbers_whisper": len(na), "numbers_daglo": len(nb),
        "numbers_jaccard": round(len(na & nb) / max(1, len(na | nb)), 4),
        "numbers_only_in_daglo": sorted(nb - na)[:15], "numbers_only_in_whisper": sorted(na - nb)[:15],
    }


def main() -> int:
    if not MODEL.exists():
        sys.exit(f"모델 없음: {MODEL}")
    PILOT.mkdir(parents=True, exist_ok=True)
    picks = pick_samples()
    report = []
    for r in picks:
        vid = r["video_id"]
        d = PILOT / vid
        d.mkdir(exist_ok=True)
        daglo = json.loads((EXPORT / "syuka" / f"{vid}.json").read_text(encoding="utf-8"))["text"]
        (d / "daglo.txt").write_text(daglo, encoding="utf-8")
        print(f"[{vid}] {r['upload_at'][:10]} {int(r['duration_sec'])//60}분 — 전사 시작", file=sys.stderr, flush=True)
        meta = transcribe(vid, d)
        if "error" in meta:
            report.append({"video_id": vid, **meta})
            continue
        wtxt = (d / "whisper.txt").read_text(encoding="utf-8") if (d / "whisper.txt").exists() else ""
        cmp_ = compare(wtxt, daglo)
        rt = int(r["duration_sec"]) / meta["elapsed_sec"] if meta["elapsed_sec"] else None
        row = {"video_id": vid, "upload_at": r["upload_at"], "duration_sec": int(r["duration_sec"]), "title": r["title"],
               **meta, "speed_x_realtime": round(rt, 1) if rt else None, **cmp_}
        report.append(row)
        (d / "compare.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{vid}] 완료 {meta['elapsed_sec']}s ({row['speed_x_realtime']}x) sim={cmp_['char_similarity']} numJ={cmp_['numbers_jaccard']}", file=sys.stderr, flush=True)
    (PILOT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 전사 파일럿 — 다글로(Trading 보유) vs whisper.cpp large-v3-turbo", "",
             "| 영상 | 게시 | 길이 | Whisper 시간 | 배속 | 최대 RSS | 문자 유사도 | 숫자 Jaccard | 숫자 다글로만 | 숫자 Whisper만 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in report:
        if "error" in r:
            lines.append(f"| {r['video_id']} | - | - | 실패 | | | | | {r['error'][:60]} | |")
            continue
        lines.append(f"| {r['video_id']} | {r['upload_at'][:10]} | {r['duration_sec']//60}분 | {r['elapsed_sec']}s | {r['speed_x_realtime']}x | {r['max_rss_gb']}GB | {r['char_similarity']} | {r['numbers_jaccard']} | {len(r['numbers_only_in_daglo'])} | {len(r['numbers_only_in_whisper'])} |")
    lines += ["", "※ 문자 유사도는 공백·구두점 제거 후 앞 2만 자 SequenceMatcher. 숫자 집합은 전문 기준. 수동 10분 구간 대조는 `private/pilot/<id>/{daglo,whisper}.txt` 로 별도 수행."]
    (PILOT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
