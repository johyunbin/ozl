#!/usr/bin/env python3
"""daily/·claims 를 docs/daily/ 로 동기화해 MkDocs 가 빌드할 수 있게 한다 (공개 승인 카드만 — Phase 3에서 필터 구현)."""
from __future__ import annotations
import pathlib, shutil
ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC, DST = ROOT / "daily", ROOT / "docs" / "daily"
if DST.exists():
    shutil.rmtree(DST)
DST.mkdir(parents=True)
files = sorted(SRC.rglob("*.md"), reverse=True)
for f in files:
    shutil.copy2(f, DST / f.name)
lines = ["# 일일 데스크", ""] + [f"- [{f.stem}]({f.name})" for f in files] or ["# 일일 데스크", "", "아직 발행된 보고서가 없습니다."]
(DST / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"synced {len(files)} reports")
