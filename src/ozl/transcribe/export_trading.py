#!/usr/bin/env python3
"""Trading 원장(trading.db youtube_content + contents/youtube/<ch>/*.json)의 전사를 OZL 로 읽기 전용 export.

- 텍스트는 DB, 세그먼트(start/end/text)는 md_path 가 가리키는 Trading JSON 에서 가져온다(없으면 text만).
- 산출: private/transcripts/trading_export/<channel>/<video_id>.json · index.csv (멱등·증분: 기존 파일은 chars 가 같으면 건너뜀)
- Trading 에는 절대 쓰지 않는다(sqlite 읽기 전용 URI).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
# Trading 저장소 위치: 환경변수 OZL_TRADING_ROOT 가 있으면 그것, 없으면 홈 아래 Trading.
TRADING = pathlib.Path(os.environ.get("OZL_TRADING_ROOT") or (pathlib.Path.home() / "Trading"))
DB = TRADING / "trading.db"
OUT = ROOT / "private" / "transcripts" / "trading_export"
CHANNELS = ("syuka", "moneycomics", "alex")
MIN_CHARS = 500


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m ozl.transcribe.export_trading",
        description=(
            "Trading 원장(trading.db youtube_content, 읽기 전용)의 전사를 "
            f"{OUT} 로 내보낸다(채널 {', '.join(CHANNELS)} · 증분). 인자 없이 돌린다."
        ),
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # --help 와 모르는 인자는 여기서 끝난다(본 동작인 내보내기 쓰기 전에). 2026-11-14.
    _parse_args(argv)
    if not DB.exists():
        print(f"Trading DB 없음: {DB} (OZL_TRADING_ROOT 로 위치 지정)", file=sys.stderr)
        return 1
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    idx, stats = [], {}
    for ch in CHANNELS:
        d = OUT / ch
        d.mkdir(parents=True, exist_ok=True)
        n_new = n_skip = n_seg = 0
        for r in c.execute("select * from youtube_content where channel=?", (ch,)):
            row = dict(r)
            text = row.get("transcript_text") or ""
            has = len(text) > MIN_CHARS
            segs = None
            if has and row.get("md_path"):
                p = TRADING / row["md_path"]
                if p.exists():
                    try:
                        j = json.loads(p.read_text(encoding="utf-8"))
                        segs = j.get("segments") or None
                    except Exception:  # noqa: BLE001
                        segs = None
            if has:
                out = d / f"{row['video_id']}.json"
                if out.exists():
                    try:
                        old = json.loads(out.read_text(encoding="utf-8"))
                        if len(old.get("text", "")) == len(text) and bool(old.get("segments")) == bool(segs):
                            n_skip += 1
                            idx.append(_idx_row(ch, row, text, has, segs))
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                out.write_text(json.dumps({
                    "video_id": row["video_id"], "channel": ch, "title": row["title"], "upload_at": row["upload_at"],
                    "duration_sec": row["duration"], "transcript_source": row["transcript_source"], "caption_lang": row["caption_lang"],
                    "status": row["status"], "trading_md_path": row["md_path"], "exported_at": now,
                    "text": text, "segments": segs,
                }, ensure_ascii=False), encoding="utf-8")
                n_new += 1
                n_seg += bool(segs)
            idx.append(_idx_row(ch, row, text, has, segs))
        stats[ch] = {"written": n_new, "skipped": n_skip, "with_segments(new)": n_seg}
    if not idx:
        print("youtube_content 에 대상 채널 행이 없다 — index.csv 를 그대로 둔다", file=sys.stderr)
        return 1
    with (OUT / "index.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(idx[0].keys()))
        w.writeheader()
        w.writerows(idx)
    print(json.dumps({"exported_at": now, "rows": len(idx), **stats}, ensure_ascii=False))
    return 0


def _idx_row(ch, row, text, has, segs):
    return {"channel": ch, "video_id": row["video_id"], "title": row["title"], "upload_at": row["upload_at"],
            "duration_sec": row["duration"], "transcript_source": row["transcript_source"] or "", "status": row["status"],
            "chars": len(text), "has_transcript": int(has), "has_segments": int(bool(segs)),
            "is_live_full": int((row["duration"] or 0) >= 5400)}


if __name__ == "__main__":
    sys.exit(main())
