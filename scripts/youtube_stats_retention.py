#!/usr/bin/env python3
"""유튜브 통계 보관 기한 점검·삭제 도구.

유튜브 API 개발자 정책은 채널 소유자의 승인 없이 받은 통계(조회수·좋아요 수·댓글 수·구독자 수 등)를
30일 넘게 보관하지 못하게 한다. 이 도구는 폴더 아래에서 그런 통계 칸이 든 파일을 찾아
레코드마다 받은 시각과 기한(받은 시각 + 30일)을 보여 주고, 기한이 지난 레코드의 통계 칸만 비운다.

    python scripts/youtube_stats_retention.py scan  --root <폴더> [--records]
    python scripts/youtube_stats_retention.py purge --root <폴더> --asof YYYY-MM-DD [--apply]

- 읽는 형식: json · jsonl · csv. 저장소에서 통계가 실제로 나온 형식이 이 셋뿐이다
  (private/meta 의 *_videos.jsonl·*.summary.json·catalog_*.csv·sample30_*.csv, private/frames 의 summary.json·*/index.json).
  sqlite(private/pulse/pulse.db)의 views 는 커뮤니티 글 조회수라 유튜브 통계가 아니다. 칸 이름도 views 라 여기 잡히지 않는다.
- 통계 칸: view_count·like_count·comment_count·subscriber_count·dislike_count·favorite_count 와 그 API 원래 이름(viewCount 등).
  video_count(videoCount)는 같은 묶음에 다른 통계 칸이 있을 때만 통계로 본다(채널 statistics 에서 온 값).
- 받은 시각을 찾는 순서: 레코드의 fetched_at → 상위 묶음(파일)의 fetched_at → 같은 video_id 의 다른 기록 가운데 가장 이른 받은 시각
  → 파일 수정 시각("받은 시각 불명 — 파일 수정 시각 사용"으로 표시).
- 기한이 지났다는 뜻: 기한의 한국 날짜가 --asof 날짜와 같거나 그 앞이다(그날 돌리면 그날 기한인 것까지 지운다).
- 지우는 방법: json·jsonl 은 값을 null 로, csv 는 빈 칸으로 바꾼다. 칸 이름과 다른 칸(영상 ID·제목·게시일 등)은 그대로 둔다.
  원본 사본은 남기지 않는다(지워야 하는 자료의 사본이 되므로). 대신 지운 칸 수와 파일별 요약을
  <root>/out/youtube_stats_purge_<타임코드>.json 에 남긴다.
- 안전장치: --root 가 저장소의 실제 private/ 이거나 그 상위 폴더, 또는 private/out/ 밖의 private/ 하위 폴더이면 --apply 를 거부한다.
  환경 변수 OZL_YT_PURGE_REAL=1 이 있을 때만 허용한다.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
REAL_PRIVATE = ROOT / "private"
KST = timezone(timedelta(hours=9))
RETENTION = timedelta(days=30)

STAT_KEYS = {
    "view_count", "like_count", "comment_count", "subscriber_count", "dislike_count", "favorite_count",
    "viewCount", "likeCount", "commentCount", "subscriberCount", "dislikeCount", "favoriteCount",
}
COMPANION_KEYS = {"video_count", "videoCount"}
TIME_KEYS = ("fetched_at",)
ID_KEYS = ("video_id",)
# 건너뛰는 폴더: 전사·음성·원문 사본은 통계가 없고 크다. out·archive 는 이 도구의 기록 자리다.
SKIP_DIRS = {"transcripts", "audio", "captures", "out", "archive", ".git", ".venv", "venv", "node_modules", "__pycache__"}
EXTS = {".json", ".jsonl", ".csv"}

SRC_RECORD = "레코드의 fetched_at"
SRC_PARENT = "상위 묶음의 fetched_at"
SRC_VIDEO = "같은 영상의 다른 기록에서 추정(가장 이른 시각)"
SRC_MTIME = "받은 시각 불명 — 파일 수정 시각 사용"


# ── 시각 ────────────────────────────────────────────────────────────────
def parse_time(v) -> datetime | None:
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip().replace("Z", "+00:00")
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=KST)


def kst(t: datetime) -> str:
    return t.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def has_value(v) -> bool:
    return v is not None and v != ""


# ── 레코드 ──────────────────────────────────────────────────────────────
class Rec:
    """통계 칸이 든 묶음 하나(json 의 dict 하나, csv 의 행 하나)."""

    def __init__(self, obj: dict, fields: list[str], fetched: datetime | None, src: str | None, video_id: str | None):
        self.obj = obj
        self.fields = fields          # 이 묶음의 통계 칸 이름(값이 비었어도 포함)
        self.fetched = fetched
        self.src = src
        self.video_id = video_id

    def filled(self) -> list[str]:
        return [k for k in self.fields if has_value(self.obj.get(k))]


def stat_fields(d: dict) -> list[str]:
    core = [k for k in d if k in STAT_KEYS]
    if not core:
        return []
    return core + [k for k in d if k in COMPANION_KEYS]


def walk_json(obj, inherited: tuple[datetime, str] | None, out: list[Rec]) -> None:
    if isinstance(obj, dict):
        own = next((parse_time(obj.get(k)) for k in TIME_KEYS if parse_time(obj.get(k))), None)
        here = (own, SRC_RECORD) if own else ((inherited[0], SRC_PARENT) if inherited else None)
        fs = stat_fields(obj)
        if fs:
            vid = next((obj[k] for k in ID_KEYS if isinstance(obj.get(k), str)), None)
            out.append(Rec(obj, fs, here[0] if here else None, here[1] if here else None, vid))
        nxt = (here[0], SRC_PARENT) if here else None
        for v in obj.values():
            if isinstance(v, (dict, list)):
                walk_json(v, nxt, out)
    elif isinstance(obj, list):
        for v in obj:
            walk_json(v, inherited, out)


class Doc:
    """통계가 든 파일 하나. 읽을 때의 모양(들여쓰기·줄바꿈·BOM)을 기억해 같은 모양으로 다시 쓴다."""

    def __init__(self, path: pathlib.Path, fmt: str):
        self.path = path
        self.fmt = fmt
        self.recs: list[Rec] = []
        self.mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=KST)
        self.raw_lines: list = []      # jsonl: dict 또는 원문 줄(읽지 못한 줄)
        self.data = None               # json: 전체 객체
        self.indent: int | None = None
        self.ascii = False
        self.trailing_nl = True
        self.header: list[str] = []    # csv
        self.rows: list[dict] = []
        self.bom = False
        self.eol = "\n"
        self.bad_lines = 0

    def rel(self, root: pathlib.Path) -> str:
        return str(self.path.relative_to(root))


def load(path: pathlib.Path) -> Doc | None:
    raw = path.read_bytes()
    if not any(k.encode() in raw for k in STAT_KEYS):
        return None
    text = raw.decode("utf-8-sig") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8", errors="strict")
    ext = path.suffix.lower()
    if ext == ".jsonl":
        d = Doc(path, "jsonl")
        d.trailing_nl = text.endswith("\n")
        d.ascii = "\\u" in text and not any(ord(c) > 127 for c in text)
        for line in text.splitlines():
            if not line.strip():
                d.raw_lines.append(line)
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                d.raw_lines.append(line)
                d.bad_lines += 1
                continue
            d.raw_lines.append(o)
            walk_json(o, None, d.recs)
    elif ext == ".json":
        try:
            o = json.loads(text)
        except json.JSONDecodeError:
            return None
        d = Doc(path, "json")
        d.data = o
        d.trailing_nl = text.endswith("\n")
        d.ascii = "\\u" in text and not any(ord(c) > 127 for c in text)
        lines = text.splitlines()
        if len(lines) > 1:
            sp = len(lines[1]) - len(lines[1].lstrip(" "))
            d.indent = sp or None
        walk_json(o, None, d.recs)
    elif ext == ".csv":
        d = Doc(path, "csv")
        d.bom = raw.startswith(b"\xef\xbb\xbf")
        d.eol = "\r\n" if b"\r\n" in raw else "\n"
        rd = csv.DictReader(io.StringIO(text, newline=""))
        d.header = list(rd.fieldnames or [])
        fs = stat_fields({k: None for k in d.header})
        if not fs:
            return None
        for row in rd:
            d.rows.append(row)
            own = next((parse_time(row.get(k)) for k in TIME_KEYS if parse_time(row.get(k))), None)
            vid = next((row[k] for k in ID_KEYS if row.get(k)), None)
            d.recs.append(Rec(row, fs, own, SRC_RECORD if own else None, vid))
    else:
        return None
    return d if d.recs else None


def discover(root: pathlib.Path) -> list[Doc]:
    docs: list[Doc] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(n for n in dirnames if n not in SKIP_DIRS and not n.startswith("."))
        for fn in sorted(filenames):
            p = pathlib.Path(dirpath) / fn
            if p.suffix.lower() not in EXTS or p.is_symlink():
                continue
            try:
                d = load(p)
            except (OSError, UnicodeDecodeError):
                continue
            if d:
                docs.append(d)
    resolve_times(docs)
    return docs


def resolve_times(docs: list[Doc]) -> None:
    """받은 시각이 없는 레코드에 같은 영상의 가장 이른 받은 시각, 그것도 없으면 파일 수정 시각을 붙인다."""
    first: dict[str, datetime] = {}
    for d in docs:
        for r in d.recs:
            if r.fetched and r.video_id:
                if r.video_id not in first or r.fetched < first[r.video_id]:
                    first[r.video_id] = r.fetched
    for d in docs:
        for r in d.recs:
            if r.fetched:
                continue
            if r.video_id and r.video_id in first:
                r.fetched, r.src = first[r.video_id], SRC_VIDEO
            else:
                r.fetched, r.src = d.mtime, SRC_MTIME


def deadline(r: Rec) -> datetime:
    return r.fetched + RETENTION


def expired(r: Rec, asof: date) -> bool:
    return deadline(r).astimezone(KST).date() <= asof


# ── 다시 쓰기 ────────────────────────────────────────────────────────────
def save(d: Doc) -> None:
    if d.fmt == "jsonl":
        out = [l if isinstance(l, str) else json.dumps(l, ensure_ascii=d.ascii) for l in d.raw_lines]
        body = "\n".join(out) + ("\n" if d.trailing_nl else "")
        data = body.encode("utf-8")
    elif d.fmt == "json":
        body = json.dumps(d.data, ensure_ascii=d.ascii, indent=d.indent) + ("\n" if d.trailing_nl else "")
        data = body.encode("utf-8")
    else:
        buf = io.StringIO(newline="")
        w = csv.DictWriter(buf, fieldnames=d.header, lineterminator=d.eol, extrasaction="ignore")
        w.writeheader()
        w.writerows(d.rows)
        data = (b"\xef\xbb\xbf" if d.bom else b"") + buf.getvalue().encode("utf-8")
    tmp = d.path.with_name(d.path.name + ".tmp_purge")
    tmp.write_bytes(data)
    os.replace(tmp, d.path)


# ── 안전장치 ────────────────────────────────────────────────────────────
def apply_refusal(root: pathlib.Path, real_private: pathlib.Path = REAL_PRIVATE) -> str:
    """--apply 를 거부할 이유. 빈 문자열이면 허용."""
    if os.environ.get("OZL_YT_PURGE_REAL") == "1":
        return ""
    r, rp = root.resolve(), real_private.resolve()
    if r == rp or rp.is_relative_to(r):
        return f"--root 가 실제 private 폴더({rp})이거나 그것을 품은 폴더다. 실제 자료를 지우려면 OZL_YT_PURGE_REAL=1 을 함께 준다."
    if r.is_relative_to(rp) and not r.is_relative_to(rp / "out"):
        return f"--root 가 실제 private 폴더 안({r})이다. 시험 사본은 {rp / 'out'} 아래에 둔다. 실제 자료를 지우려면 OZL_YT_PURGE_REAL=1 을 함께 준다."
    return ""


# ── 명령 ────────────────────────────────────────────────────────────────
def summarize(d: Doc, root: pathlib.Path) -> dict:
    fields = sorted({k for r in d.recs for k in r.fields})
    times = sorted(r.fetched for r in d.recs)
    srcs = sorted({r.src for r in d.recs})
    return {
        "path": d.rel(root), "format": d.fmt, "records": len(d.recs),
        "filled_cells": sum(len(r.filled()) for r in d.recs), "fields": fields,
        "fetched_min": kst(times[0]), "fetched_max": kst(times[-1]),
        "deadline_min": kst(times[0] + RETENTION), "sources": srcs,
    }


def cmd_scan(root: pathlib.Path, records: bool) -> int:
    docs = discover(root)
    if not docs:
        print(f"통계 칸이 든 파일이 없다: {root}")
        return 0
    print(f"폴더: {root}  (시각은 한국 시간, 기한 = 받은 시각 + 30일)")
    print("| 파일 | 형식 | 레코드 | 값 있는 칸 | 통계 칸 | 받은 시각 | 가장 이른 기한 | 받은 시각 근거 |")
    print("|---|---|---|---|---|---|---|---|")
    for d in docs:
        s = summarize(d, root)
        span = s["fetched_min"] if s["fetched_min"] == s["fetched_max"] else f"{s['fetched_min']} ~ {s['fetched_max']}"
        print(f"| {s['path']} | {s['format']} | {s['records']} | {s['filled_cells']} | {', '.join(s['fields'])} "
              f"| {span} | {s['deadline_min']} | {' / '.join(s['sources'])} |")
        if d.bad_lines:
            print(f"  읽지 못한 줄 {d.bad_lines}개는 건드리지 않는다: {s['path']}")
    if records:
        print("\n| 파일 | video_id | 받은 시각 | 기한 | 값 있는 칸 | 근거 |")
        print("|---|---|---|---|---|---|")
        for d in docs:
            for r in d.recs:
                print(f"| {d.rel(root)} | {r.video_id or '-'} | {kst(r.fetched)} | {kst(deadline(r))} | {len(r.filled())} | {r.src} |")
    total = sum(len(r.filled()) for d in docs for r in d.recs)
    print(f"\n파일 {len(docs)}개, 레코드 {sum(len(d.recs) for d in docs)}개, 값 있는 통계 칸 {total}개.")
    return 0


def cmd_purge(root: pathlib.Path, asof: date, apply: bool) -> int:
    if apply:
        why = apply_refusal(root)
        if why:
            print(f"거부: {why}", file=sys.stderr)
            return 2
    docs = discover(root)
    report = []
    total = 0
    for d in docs:
        hit = [r for r in d.recs if expired(r, asof) and r.filled()]
        kept = [r for r in d.recs if not expired(r, asof) and r.filled()]
        by_field: dict[str, int] = {}
        for r in hit:
            for k in r.filled():
                by_field[k] = by_field.get(k, 0) + 1
        n = sum(by_field.values())
        total += n
        report.append({
            "path": d.rel(root), "format": d.fmt, "records": len(d.recs),
            "records_purged": len(hit), "cells_purged": n, "cells_by_field": by_field,
            "records_kept_with_stats": len(kept),
            "kept_earliest_deadline": kst(min(deadline(r) for r in kept)) if kept else None,
            "time_sources": sorted({r.src for r in hit}),
        })
        if apply and hit:
            for r in hit:
                for k in r.filled():
                    r.obj[k] = None if d.fmt != "csv" else ""
            save(d)
    word = "지웠다" if apply else "지울 것"
    print(f"폴더: {root}  기준일: {asof} (기한 날짜가 기준일 이하인 레코드)  {'적용' if apply else '미리 보기 — 파일은 바뀌지 않는다'}")
    print("| 파일 | 레코드 | 기한 지난 레코드 | 지울 칸 | 칸별 | 남는 통계 레코드(가장 이른 기한) | 받은 시각 근거 |")
    print("|---|---|---|---|---|---|---|")
    for s in report:
        fields = ", ".join(f"{k} {v}" for k, v in sorted(s["cells_by_field"].items())) or "-"
        keep = f"{s['records_kept_with_stats']} ({s['kept_earliest_deadline']})" if s["records_kept_with_stats"] else "0"
        print(f"| {s['path']} | {s['records']} | {s['records_purged']} | {s['cells_purged']} | {fields} | {keep} "
              f"| {' / '.join(s['time_sources']) or '-'} |")
    print(f"\n통계 칸 {total}개를 {word}.")
    if apply:
        stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
        log = root / "out" / f"youtube_stats_purge_{stamp}.json"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps({
            "run_at": datetime.now(KST).isoformat(timespec="seconds"), "root": str(root.resolve()),
            "asof": asof.isoformat(), "retention_days": RETENTION.days, "cells_purged": total,
            "files": [s for s in report if s["cells_purged"] or s["records_kept_with_stats"]],
            "note": "원본 사본은 남기지 않았다. 값만 비웠고 칸 이름과 다른 칸은 그대로다.",
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"기록: {log}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="유튜브 통계 보관 기한(30일) 점검·삭제")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="통계가 든 파일과 받은 시각·기한을 보여 준다(아무것도 바꾸지 않는다)")
    s.add_argument("--root", required=True)
    s.add_argument("--records", action="store_true", help="레코드별 표도 낸다")
    p = sub.add_parser("purge", help="기한 지난 레코드의 통계 칸을 비운다(--apply 없으면 미리 보기)")
    p.add_argument("--root", required=True)
    p.add_argument("--asof", required=True, help="기준일 YYYY-MM-DD")
    p.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root)
    if not root.is_dir():
        print(f"폴더가 없다: {root}", file=sys.stderr)
        return 2
    if a.cmd == "scan":
        return cmd_scan(root, a.records)
    try:
        asof = date.fromisoformat(a.asof)
    except ValueError:
        print(f"--asof 는 YYYY-MM-DD 형식이어야 한다: {a.asof}", file=sys.stderr)
        return 2
    return cmd_purge(root, asof, a.apply)


if __name__ == "__main__":
    sys.exit(main())
