#!/usr/bin/env python3
"""라이브 풀버전의 주제 세그먼트 경계와 브릿지 멘트 수집 (Phase 2A-2 구성 템플릿).

입력: private/meta/live_align_syukaworld.csv (클립→라이브 구간), private/transcripts/trading_export/syuka/<live>.json (세그먼트 타임스탬프)
산출:
  - private/style/bridges/<live_id>.md : 세그먼트 순서표 + 각 경계(시작·끝) 전후 45초 발화(비공개 — 전사 원문)
  - tracks/syuka/analysis/live_structure.md : 집계만(도입 길이·세그먼트 수·길이·간격·마무리 길이)
"""
from __future__ import annotations

import csv
import json
import pathlib
import statistics
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[3]
EXP = ROOT / "private" / "transcripts" / "trading_export" / "syuka"
ALIGN = ROOT / "private" / "meta" / "live_align_syukaworld.csv"
OUT_DIR = ROOT / "private" / "style" / "bridges"
OUT_MD = ROOT / "tracks" / "syuka" / "analysis" / "live_structure.md"
WIN = 45  # 경계 전후 초
COV_MIN = 0.12


def window_text(segs: list[dict], t: float, before: int = WIN, after: int = WIN) -> str:
    parts = [s["text"].strip() for s in segs if s["end"] >= t - before and s["start"] <= t + after]
    return " ".join(parts)


def main() -> int:
    rows = [r for r in csv.DictReader(ALIGN.open(encoding="utf-8")) if r["live_start"] and float(r["coverage"]) >= COV_MIN]
    by_live = defaultdict(list)
    for r in rows:
        by_live[r["live_id"]].append(r)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = []
    for live_id, clips in by_live.items():
        lj = json.loads((EXP / f"{live_id}.json").read_text(encoding="utf-8"))
        segs = lj.get("segments") or []
        dur = lj.get("duration_sec") or 0
        clips.sort(key=lambda r: float(r["live_start"]))
        intro = float(clips[0]["live_start"]) / 60
        outro = (dur - float(clips[-1]["live_end"])) / 60 if dur else None
        lens = [(float(c["live_end"]) - float(c["live_start"])) / 60 for c in clips]
        gaps = [(float(b["live_start"]) - float(a["live_end"])) / 60 for a, b in zip(clips, clips[1:])]
        lines = [f"# {lj.get('title')}", f"- live_id {live_id} · {lj.get('upload_at')} · {dur//60}분 · 세그먼트 {len(clips)}개 · 도입 {intro:.0f}분 · 마무리 {outro:.0f}분" if outro is not None else "", "",
                 "| # | 라이브 구간 | 길이(분) | 클립 제목 | 클립 공개일 |", "|---|---|---|---|---|"]
        for i, c in enumerate(clips, 1):
            lines.append(f"| {i} | {int(float(c['live_start']))//60:02d}:{int(float(c['live_start']))%60:02d}~{int(float(c['live_end']))//60:02d}:{int(float(c['live_end']))%60:02d} | {(float(c['live_end'])-float(c['live_start']))/60:.0f} | {c['clip_title']} | {c['clip_published_kst'][:10]} |")
        lines += ["", "## 경계 발화(전후 45초 · 전사 원문 · 비공개)", ""]
        if segs:
            lines += [f"### 도입 → 세그먼트 1 (t={int(float(clips[0]['live_start']))}s)", window_text(segs, float(clips[0]["live_start"])), ""]
            for i, (a, b) in enumerate(zip(clips, clips[1:]), 1):
                t_end, t_start = float(a["live_end"]), float(b["live_start"])
                lines += [f"### 세그먼트 {i} 끝 (t={int(t_end)}s)", window_text(segs, t_end), "",
                          f"### 세그먼트 {i+1} 시작 (t={int(t_start)}s)", window_text(segs, t_start), ""]
            lines += [f"### 세그먼트 {len(clips)} 끝 → 마무리 (t={int(float(clips[-1]['live_end']))}s)", window_text(segs, float(clips[-1]["live_end"])), ""]
        (OUT_DIR / f"{live_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        stats.append({"live_id": live_id, "date": lj.get("upload_at", "")[:10], "dur_min": dur / 60, "n": len(clips), "intro": intro, "outro": outro,
                      "seg_median": statistics.median(lens), "seg_min": min(lens), "seg_max": max(lens), "gap_median": statistics.median(gaps) if gaps else 0.0,
                      "covered_min": sum(lens)})
    stats.sort(key=lambda s: s["date"])
    md = ["# 슈카월드 일요 라이브 구조 (2026 · 집계)", "",
          f"- 라이브 {len(stats)}회 · 세그먼트(클립으로 공개된 주제) 평균 {statistics.mean(s['n'] for s in stats):.1f}개/회",
          f"- 도입(첫 주제 전 잡담·공지) 중앙값 {statistics.median(s['intro'] for s in stats):.0f}분 · 마무리(마지막 주제 후) 중앙값 {statistics.median(s['outro'] for s in stats if s['outro'] is not None):.0f}분",
          f"- 세그먼트 길이 중앙값 {statistics.median(s['seg_median'] for s in stats):.0f}분 (회차별 최단 중앙값 {statistics.median(s['seg_min'] for s in stats):.0f}분 · 최장 중앙값 {statistics.median(s['seg_max'] for s in stats):.0f}분)",
          f"- 세그먼트 사이 간격(전환·잡담) 중앙값 {statistics.median(s['gap_median'] for s in stats):.1f}분",
          f"- 클립으로 공개된 분량 / 라이브 전체 = {sum(s['covered_min'] for s in stats):.0f} / {sum(s['dur_min'] for s in stats):.0f} 분",
          "", "| 날짜 | 라이브(분) | 세그먼트 | 도입(분) | 세그 중앙(분) | 최단~최장 | 간격 중앙 | 마무리(분) |", "|---|---|---|---|---|---|---|---|"]
    for s in stats:
        md.append(f"| {s['date']} | {s['dur_min']:.0f} | {s['n']} | {s['intro']:.0f} | {s['seg_median']:.0f} | {s['seg_min']:.0f}~{s['seg_max']:.0f} | {s['gap_median']:.1f} | {s['outro']:.0f} |")
    md += ["", "※ 세그먼트 경계는 주중 클립 전사를 라이브 전사에 정렬해 얻은 5~95 백분위 구간(과소 추정 경향). 경계 전후 발화(브릿지 멘트) 원문은 비공개 `private/style/bridges/`."]
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
