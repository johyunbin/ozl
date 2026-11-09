#!/usr/bin/env python3
"""공개본 추출 게이트.

검사 대상(pre-commit files 필터): tracks/syuka/decks/*.pptx · daily/*.md · docs/*.md · tracks/**/*.md
- pptx: 발표자 노트·숨김 슬라이드가 남아 있으면 실패(공개본은 export 로 제거해야 함)
- md: 비공개 전사 코퍼스(private/transcripts/**/*.json 의 text, private/pilot/**/*.txt)와 연속 N자(정규화) 일치하면 실패
  · 코퍼스 셔글은 private/.gate_shingles.pkl 에 캐시(index.csv mtime 기준 무효화)
Phase 4 에서 내장 미디어 출처 메타 검사 추가 예정.
"""
from __future__ import annotations

import json
import pathlib
import pickle
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANS = ROOT / "private" / "transcripts"
PILOT = ROOT / "private" / "pilot"
CACHE = ROOT / "private" / ".gate_shingles.pkl"
N = 20        # 셔글 길이(정규화 문자)
STRIDE = 7    # 코퍼스 셔글 추출 간격 — md 쪽은 1칸씩 훑으므로 임의 위치 인용도 N+STRIDE 자 이상이면 반드시 걸린다
MIN_HITS = 1


def norm(s: str) -> str:
    return re.sub(r"[^\w가-힣]+", "", s or "").lower()


def check_pptx(p: pathlib.Path) -> list[str]:
    try:
        from pptx import Presentation
    except ImportError:
        return ["python-pptx 미설치 — 검사 불가"]
    prs = Presentation(str(p))
    errs = []
    for i, s in enumerate(prs.slides, 1):
        if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
            errs.append(f"slide {i}: 발표자 노트 잔존")
        if s._element.get("show") == "0":
            errs.append(f"slide {i}: 숨김 슬라이드 잔존")
    return errs


def _corpus_signature() -> str:
    idx = TRANS / "trading_export" / "index.csv"
    parts = [str(idx.stat().st_mtime_ns) if idx.exists() else "0"]
    parts.append(str(sum(1 for _ in PILOT.rglob("*.txt")) if PILOT.exists() else 0))
    return "|".join(parts)


def _build_shingles() -> set[int]:
    sh: set[int] = set()
    files = list(TRANS.rglob("*.json")) if TRANS.exists() else []
    for f in files:
        try:
            t = norm(json.loads(f.read_text(encoding="utf-8")).get("text", ""))
        except Exception:  # noqa: BLE001
            continue
        for k in range(0, max(0, len(t) - N), STRIDE):
            sh.add(hash(t[k:k + N]))
    if PILOT.exists():
        for f in PILOT.rglob("*.txt"):
            t = norm(f.read_text(encoding="utf-8", errors="ignore"))
            for k in range(0, max(0, len(t) - N), STRIDE):
                sh.add(hash(t[k:k + N]))
    return sh


def transcript_shingles() -> set[int]:
    sig = _corpus_signature()
    if CACHE.exists():
        try:
            d = pickle.loads(CACHE.read_bytes())
            if d.get("sig") == sig and d.get("N") == N and d.get("stride") == STRIDE:
                return d["sh"]
        except Exception:  # noqa: BLE001
            pass
    sh = _build_shingles()
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(pickle.dumps({"sig": sig, "N": N, "stride": STRIDE, "sh": sh}))
    except Exception:  # noqa: BLE001
        pass
    return sh


def check_md(p: pathlib.Path, sh: set[int]) -> list[str]:
    if not sh:
        return []
    t = norm(p.read_text(encoding="utf-8", errors="ignore"))
    hits = []
    for k in range(0, max(0, len(t) - N)):
        if hash(t[k:k + N]) in sh:
            hits.append(t[k:k + N])
            if len(hits) >= 5:
                break
    return [f"전사 전문 인용 의심 {len(hits)}건 이상 (예: {hits[0]!r})"] if len(hits) >= MIN_HITS else []


def main(argv: list[str]) -> int:
    sh = None
    bad = 0
    for a in argv:
        p = pathlib.Path(a)
        if not p.exists():
            continue
        if p.suffix == ".pptx":
            errs = check_pptx(p)
        elif p.suffix == ".md":
            if sh is None:
                sh = transcript_shingles()
            errs = check_md(p, sh)
        else:
            continue
        for e in errs:
            print(f"[publish-gate] {p}: {e}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
