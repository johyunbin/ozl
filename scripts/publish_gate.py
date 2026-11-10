#!/usr/bin/env python3
"""공개본 추출 게이트.

검사 대상(pre-commit files 필터): tracks/syuka/decks/*.pptx · daily·docs·tracks 의 md·json · src·tests·scripts·tools 의 소스 · README.md
- pptx: 발표자 노트·숨김 슬라이드가 남아 있으면 실패(공개본은 export 로 제거해야 함)
- md: 비공개 전사 코퍼스(private/transcripts/**/*.json 의 text, private/pilot/**/*.txt)와 연속 N자(정규화) 일치하면 실패
  · 코퍼스 셔글은 private/.gate_shingles.pkl 에 캐시(index.csv mtime 기준 무효화)
- md: 비공개 슬라이드 문구(문자 인식 결과 — private/slides_dense/*.json 의 title·body, private/ocr/*.jsonl)와 연속 N_SLIDE자 일치해도 실패
  · 슬라이드 줄은 짧아서(제목 중앙값 27자) 전사보다 짧은 창을 쓴다. 화면 필기 도구의 대화상자 문구(UI 글자)는 코퍼스에서 뺀다
Phase 4 에서 내장 미디어 출처 메타 검사 추가 예정.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import pickle
import re
import sys


def h64(s: str) -> int:
    """프로세스 간 안정적인 64비트 해시 — 내장 hash()는 솔트가 매 프로세스 달라 캐시와 불일치(2026-11-09 자가검증에서 적발)."""
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "little")

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANS = ROOT / "private" / "transcripts"
PILOT = ROOT / "private" / "pilot"
CACHE = ROOT / "private" / ".gate_shingles.pkl"
SLIDES = ROOT / "private" / "slides_dense"
OCR = ROOT / "private" / "ocr"
N = 20        # 셔글 길이(정규화 문자)
N_SLIDE = 14  # 슬라이드 문구용 창(정규화 문자) — 코퍼스가 작아 1칸 간격으로 전부 넣는다
SLIDE_MIN_HANGUL = 8  # 창 안에 한글이 이만큼 있어야 대조한다 — 'financialtimes' 같은 매체명·영문 고유명사 오탐 방지(2026-11-10 docs/sources.md 에서 실증)
SLIDE_MIN_HITS = 2    # 연속 15자 이상 겹칠 때만 인용으로 본다
UI_TEXT = re.compile(r"저장하시겠습니까|저장하지 않은 변경|저장하지 않음")
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
    parts = ["v4-blake2b-slides-hangul", str(idx.stat().st_mtime_ns) if idx.exists() else "0"]
    parts.append(str(sum(1 for _ in PILOT.rglob("*.txt")) if PILOT.exists() else 0))
    for d in (SLIDES, OCR):
        fs = sorted(d.glob("*.json*")) if d.exists() else []
        parts.append(f"{len(fs)}:{max((f.stat().st_mtime_ns for f in fs), default=0)}")
    return "|".join(parts)


def _slide_lines():
    if SLIDES.exists():
        for f in SLIDES.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for s in d.get("slides", []):
                yield s.get("title") or ""
                yield from (s.get("body") or [])
    if OCR.exists():
        for f in OCR.glob("*.jsonl"):
            for line in f.open(encoding="utf-8"):
                try:
                    d = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                for ln in d.get("lines", []):
                    yield ln.get("text", "")


def _build_slide_shingles() -> set[int]:
    sh: set[int] = set()
    for raw in _slide_lines():
        if UI_TEXT.search(raw):
            continue
        t = norm(raw)
        for k in range(0, max(0, len(t) - N_SLIDE + 1)):
            w = t[k:k + N_SLIDE]
            if sum(1 for c in w if "가" <= c <= "힣") >= SLIDE_MIN_HANGUL:
                sh.add(h64(w))
    return sh


def _build_shingles() -> set[int]:
    sh: set[int] = set()
    files = list(TRANS.rglob("*.json")) if TRANS.exists() else []
    for f in files:
        try:
            t = norm(json.loads(f.read_text(encoding="utf-8")).get("text", ""))
        except Exception:  # noqa: BLE001
            continue
        for k in range(0, max(0, len(t) - N), STRIDE):
            sh.add(h64(t[k:k + N]))
    if PILOT.exists():
        for f in PILOT.rglob("*.txt"):
            t = norm(f.read_text(encoding="utf-8", errors="ignore"))
            for k in range(0, max(0, len(t) - N), STRIDE):
                sh.add(h64(t[k:k + N]))
    return sh


def transcript_shingles() -> tuple[set[int], set[int]]:
    sig = _corpus_signature()
    if CACHE.exists():
        try:
            d = pickle.loads(CACHE.read_bytes())
            if d.get("sig") == sig and d.get("N") == N and d.get("stride") == STRIDE and d.get("N_SLIDE") == N_SLIDE:
                return d["sh"], d["slide_sh"]
        except Exception:  # noqa: BLE001
            pass
    sh, slide_sh = _build_shingles(), _build_slide_shingles()
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(pickle.dumps({"sig": sig, "N": N, "stride": STRIDE, "N_SLIDE": N_SLIDE, "sh": sh, "slide_sh": slide_sh}))
    except Exception:  # noqa: BLE001
        pass
    return sh, slide_sh


def check_md(p: pathlib.Path, sh: set[int], slide_sh: set[int] | None = None) -> list[str]:
    t = norm(p.read_text(encoding="utf-8", errors="ignore"))
    errs = []
    for name, corpus, n, need in (("전사 전문", sh, N, MIN_HITS), ("슬라이드 문구", slide_sh or set(), N_SLIDE, SLIDE_MIN_HITS)):
        if not corpus:
            continue
        hits, run, best_run = [], 0, 0
        for k in range(0, max(0, len(t) - n + 1)):
            if h64(t[k:k + n]) in corpus:
                run += 1
                best_run = max(best_run, run)
                if run == need:  # 창이 need 개 연달아 맞아야(= n + need - 1 자 연속 일치) 한 건으로 친다
                    hits.append(t[k - need + 1:k + n])
                    if len(hits) >= 5:
                        break
            else:
                run = 0
        if hits:
            errs.append(f"{name} 인용 의심 {len(hits)}건 이상 (예: {hits[0]!r})")
    return errs


def main(argv: list[str]) -> int:
    sh = slide_sh = None
    bad = 0
    for a in argv:
        p = pathlib.Path(a)
        if not p.exists():
            continue
        if p.suffix == ".pptx":
            errs = check_pptx(p)
        elif p.suffix in (".md", ".py", ".json", ".txt", ".swift", ".yml", ".yaml", ".toml", ".sh"):  # 소스·데이터 파일도 대조(2026-11-10: deck.py 시제품 예시에 슬라이드 제목이 들어가 있던 것을 md 전용 게이트가 못 잡았다)
            if sh is None:
                sh, slide_sh = transcript_shingles()
            errs = check_md(p, sh, slide_sh)
        else:
            continue
        for e in errs:
            print(f"[publish-gate] {p}: {e}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
