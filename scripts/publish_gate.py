#!/usr/bin/env python3
"""공개본 추출 게이트 (Phase 0 골격).

검사 대상: tracks/syuka/decks/*.pptx · daily/*.md · docs/*.md
- pptx: 발표자 노트·숨김 슬라이드가 남아 있으면 실패(공개본은 export 스크립트로 제거해야 함)
- md: private/transcripts 의 전사 전문과 연속 20자 이상 일치하면 실패(인용 차단) — 전사가 없으면 건너뜀
Phase 4 에서 내장 미디어 출처 메타 검사 추가 예정.
"""
from __future__ import annotations
import sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANS = ROOT / "private" / "transcripts"


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


def _transcript_shingles(n: int = 20) -> set[str]:
    sh: set[str] = set()
    if not TRANS.exists():
        return sh
    for f in TRANS.rglob("*.txt"):
        t = f.read_text(encoding="utf-8", errors="ignore").replace("\n", " ")
        for k in range(0, max(0, len(t) - n), 10):
            sh.add(t[k:k + n])
    return sh


def check_md(p: pathlib.Path, shingles: set[str]) -> list[str]:
    if not shingles:
        return []
    t = p.read_text(encoding="utf-8", errors="ignore").replace("\n", " ")
    hits = [s for s in shingles if s in t]
    return [f"전사 전문 인용 의심 {len(hits)}건 (예: {hits[0]!r})"] if hits else []


def main(argv: list[str]) -> int:
    shingles = None
    bad = 0
    for a in argv:
        p = pathlib.Path(a)
        if not p.exists():
            continue
        if p.suffix == ".pptx":
            errs = check_pptx(p)
        elif p.suffix == ".md":
            if shingles is None:
                shingles = _transcript_shingles()
            errs = check_md(p, shingles)
        else:
            continue
        for e in errs:
            print(f"[publish-gate] {p}: {e}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
