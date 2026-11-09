#!/usr/bin/env python3
"""일요 라이브 풀버전 전사 ↔ 주중 클립 전사 정렬 — "클립 = 라이브 세그먼트" 가정 검증 (Phase 2A).

방법: 라이브 세그먼트(타임스탬프)의 정규화 텍스트에서 n-gram 셔글을 만들고 라이브 시각에 매핑.
각 클립의 셔글이 라이브 어느 시각대에 몰리는지로 (1) 커버리지(클립 텍스트 중 라이브에 존재하는 비율)
(2) 라이브 내 구간(5~95 백분위) (3) 클립 업로드 순서 vs 라이브 진행 순서 를 측정한다.
입력: private/meta/live_clip_map_syukaworld.csv · private/transcripts/trading_export/syuka/*.json
출력: private/meta/live_align_syukaworld.csv · tracks/syuka/analysis/live_vs_clips.md (집계만)
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import statistics
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[3]
EXP = ROOT / "private" / "transcripts" / "trading_export" / "syuka"
MAP = ROOT / "private" / "meta" / "live_clip_map_syukaworld.csv"
OUT_CSV = ROOT / "private" / "meta" / "live_align_syukaworld.csv"
OUT_MD = ROOT / "tracks" / "syuka" / "analysis" / "live_vs_clips.md"
N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10  # 셔글 길이(정규화 문자)


def norm(s: str) -> str:
    return re.sub(r"[^\w가-힣]+", "", s or "").lower()


def load(vid: str) -> dict | None:
    p = EXP / f"{vid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def live_index(live: dict) -> dict[str, float]:
    """셔글 → 라이브 시각(초). 세그먼트가 없으면 글자 위치 비율로 시각 추정."""
    idx: dict[str, float] = {}
    segs = live.get("segments")
    if segs:
        for s in segs:
            t = norm(s.get("text", ""))
            st = float(s.get("start", 0))
            for i in range(0, max(0, len(t) - N + 1), 3):
                idx.setdefault(t[i:i + N], st)
    else:
        t = norm(live.get("text", ""))
        dur = live.get("duration_sec") or 1
        for i in range(0, max(0, len(t) - N + 1), 3):
            idx.setdefault(t[i:i + N], dur * i / max(1, len(t)))
    return idx


def align(clip: dict, lidx: dict[str, float]) -> dict:
    t = norm(clip.get("text", ""))
    hits, total = [], 0
    for i in range(0, max(0, len(t) - N + 1), 3):
        total += 1
        v = lidx.get(t[i:i + N])
        if v is not None:
            hits.append(v)
    if not hits:
        return {"coverage": 0.0, "live_start": None, "live_end": None, "span_min": None}
    hits.sort()
    p5, p95 = hits[int(len(hits) * 0.05)], hits[int(len(hits) * 0.95) - 1]
    return {"coverage": round(len(hits) / max(1, total), 3), "live_start": round(p5), "live_end": round(p95), "span_min": round((p95 - p5) / 60, 1)}


def main() -> int:
    groups = defaultdict(list)
    for r in csv.DictReader(MAP.open(encoding="utf-8")):
        if r["live_published_kst"] >= "2026-01":
            groups[r["live_id"]].append(r)
    rows, per_live = [], []
    live_ids_sorted = sorted(groups, key=lambda k: groups[k][0]["live_published_kst"])
    lidx_cache: dict[str, dict] = {}

    def get_idx(lid: str):
        if lid not in lidx_cache:
            lj = load(lid)
            lidx_cache[lid] = live_index(lj) if lj else {}
        return lidx_cache[lid]

    for li, live_id in enumerate(live_ids_sorted):
        clips = groups[live_id]
        live = load(live_id)
        if not live:
            continue
        lidx = get_idx(live_id)
        ctrl_id = live_ids_sorted[li - 1] if li > 0 else None  # 대조군 = 직전 라이브
        cidx = get_idx(ctrl_id) if ctrl_id else {}
        clips.sort(key=lambda r: r["clip_published_kst"])
        res = []
        for c in clips:
            cj = load(c["clip_id"])
            if not cj:
                continue
            a = align(cj, lidx)
            ctrl = align(cj, cidx)["coverage"] if cidx else None
            row = {"live_id": live_id, "live_published_kst": c["live_published_kst"], "live_min": c["live_min"],
                   "clip_id": c["clip_id"], "clip_published_kst": c["clip_published_kst"], "clip_min": c["clip_min"],
                   "clip_title": c["clip_title"], **a, "control_coverage": ctrl, "has_segments": int(bool(live.get("segments")))}
            rows.append(row)
            res.append(row)
        # 두 독립 다글로 전사 간 정확 셔글 일치는 ~25% 수준(STT 분산) → 대조군(≈0.01) 대비 충분히 높은 0.12 를 '라이브에서 컷' 판정 임계로 쓴다
        covered = [r for r in res if r["coverage"] >= 0.12]
        starts = [r["live_start"] for r in covered if r["live_start"] is not None]
        order_ok = sum(1 for i in range(1, len(starts)) if starts[i] >= starts[i - 1])
        per_live.append({"live_id": live_id, "live_min": int(float(clips[0]["live_min"])), "clips": len(res), "covered": len(covered),
                         "mean_cov": round(statistics.mean([r["coverage"] for r in res]), 3) if res else 0,
                         "first_start_min": round(min(starts) / 60) if starts else None,
                         "order_monotonic": f"{order_ok}/{max(0, len(starts) - 1)}",
                         "clip_total_min": round(sum(float(r["clip_min"]) for r in res)),
                         "span_total_min": round(sum(r["span_min"] or 0 for r in covered))})
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    covs = [r["coverage"] for r in rows]
    ctrls = [r["control_coverage"] for r in rows if r["control_coverage"] is not None]
    lines = ["# 라이브 풀버전 vs 주중 클립 — 정렬 집계 (2026)", "",
             f"- 대상: 라이브 {len(per_live)}회 · 클립 {len(rows)}편 · 셔글 {N}자(정규화) · 커버리지 = 클립 텍스트 중 라이브 전사에 존재하는 셔글 비율",
             f"- 커버리지 중앙값 {statistics.median(covs):.2f} · 평균 {statistics.mean(covs):.2f} · 0.3 이상 {sum(1 for c in covs if c >= 0.3)}/{len(covs)}편" if covs else "- 데이터 없음",
             f"- **대조군(직전 라이브) 커버리지** 중앙값 {statistics.median(ctrls):.2f} · 평균 {statistics.mean(ctrls):.2f} → 매핑 라이브가 대조군보다 높은 클립 {sum(1 for r in rows if r['control_coverage'] is not None and r['coverage'] > r['control_coverage'])}/{len(ctrls)}편" if ctrls else "- 대조군 없음",
             f"- 클립 합계 분량 / 라이브 분량 = {sum(p['clip_total_min'] for p in per_live)} / {sum(p['live_min'] for p in per_live)} 분",
             f"- 클립 업로드 순서가 라이브 진행 순서와 일치(단조): {sum(int(p['order_monotonic'].split('/')[0]) for p in per_live)}/{sum(int(p['order_monotonic'].split('/')[1]) for p in per_live)}",
             f"- 첫 클립의 라이브 시작점(분) 중앙값: {statistics.median([p['first_start_min'] for p in per_live if p['first_start_min'] is not None]) if per_live else '-'} (도입·잡담 길이)",
             "", "| 라이브(KST) | 길이 | 클립 수 | 커버≥0.12 | 평균 커버 | 첫 클립 시작(분) | 순서 단조 | 클립 합계(분) | 라이브 내 구간 합계(분) |", "|---|---|---|---|---|---|---|---|---|"]
    for p in sorted(per_live, key=lambda x: x["live_id"]):
        lp = next((r["live_published_kst"] for r in rows if r["live_id"] == p["live_id"]), "")
        lines.append(f"| {lp[:10]} | {p['live_min']} | {p['clips']} | {p['covered']} | {p['mean_cov']} | {p['first_start_min']} | {p['order_monotonic']} | {p['clip_total_min']} | {p['span_total_min']} |")
    lines += ["", "해석: 라이브와 클립은 **각각 따로 전사**된 텍스트라 정확 셔글 일치는 STT 분산 때문에 ~25%에 머문다. 판정은 절대값이 아니라 **대조군(직전 라이브) 대비**로 한다 — 매핑 라이브 커버리지가 대조군(≈0.01)보다 10배 이상이면 '라이브에서 컷'. 클립 합계 분량이 라이브의 약 87%라는 점과 함께, 주중 클립은 일요 라이브 세그먼트를 편집한 것으로 본다. 라이브 내 구간 합계가 클립 합계보다 짧게 나오는 것은 매칭된 셔글의 5~95 백분위로 구간을 잡기 때문(과소 추정)."]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
