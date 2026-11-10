#!/usr/bin/env python3
"""clean 프레임 전체를 macOS Vision 으로 문자 인식 (Phase 2A-2 재료).

입력: private/style/style_measure_raw.json(프레임 분류) · tools/ocr/ocr(swiftc 로 빌드: `swiftc -O tools/ocr/ocr.swift -o tools/ocr/ocr`)
출력: private/ocr/<video_id>.jsonl — 프레임당 한 줄 {"file", "w", "h", "lines":[{text, conf, x, y, w, h}]} (슬라이드 문구 = 비공개)
이미 끝난 영상은 건너뛴다(재개 가능). 부하: nice 19 · 순차.

    python -m ozl.analyze.slide_ocr
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
FRAMES = ROOT / "private" / "frames"
RAW = ROOT / "private" / "style" / "style_measure_raw.json"
OUT = ROOT / "private" / "ocr"
BIN = ROOT / "tools" / "ocr" / "ocr"
BATCH = 40


def main() -> int:
    if not BIN.exists():
        print(f"{BIN} 없음 — swiftc -O tools/ocr/ocr.swift -o tools/ocr/ocr", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    for v in raw:
        vid = v["video_id"]
        files = [f["file"] for f in v["frames"] if f["class"] == "clean"]
        out = OUT / f"{vid}.jsonl"
        if out.exists() and sum(1 for ln in out.open(encoding="utf-8") if ln.strip() and not json.loads(ln).get("error")) >= len(files):
            continue  # 실패 행({"error": true})이 섞여 있으면 완료로 치지 않고 다시 돈다(인식된 글자에 "error" 가 들어 있는 정상 행은 센다)
        rows = []
        for i in range(0, len(files), BATCH):
            paths = [str(FRAMES / vid / f) for f in files[i : i + BATCH]]
            r = subprocess.run(["nice", "-n", "19", str(BIN), *paths], capture_output=True, text=True, timeout=1200)
            for line in r.stdout.splitlines():
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d["file"] = pathlib.Path(d["file"]).name
                if d.get("error"):
                    print(f"[{vid}] 인식 실패: {d['file']}", file=sys.stderr)
                    continue
                rows.append(d)
        out.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in rows) + "\n", encoding="utf-8")
        print(f"[{vid}] {len(rows)}/{len(files)}장", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
