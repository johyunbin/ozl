"""슈카월드 영상 자료 명령줄.

    python -m ozl.syuka catalog              # 영상 목록을 만들어 DB 에 넣고 수를 찍는다
    python -m ozl.syuka sample               # 표본 60편 → private/syuka/sample_60.json
    python -m ozl.syuka put <model> <파일>   # 추출 자료 한 건을 검사해 넣는다(걸리면 종료 코드 1). model=merged 면 합친 자료
                                             # 파일은 그 판의 폴더(schema.EXTRACT_DIRS)/<model>/<video_id>.json 이어야 한다
    python -m ozl.syuka agree [a b] [--schema-version N]
                                             # 두 모델 일치율(기본 opus sonnet, 최신 판) → private/syuka/agree_v<N>.json
                                             # 계산은 늘 최신 판 계산이다. 1판 자료에 --schema-version 1 이면 '새 계산만 적용한 값'
    python -m ozl.syuka status

1판의 원래 일치율 파일(1판 계산)은 private/syuka/agree.json 과 사본 agree_20261114_0602.json 이다. 덮어쓰지 않는다.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter

from . import agree, catalog, db, sample, schema

def agree_out(version: int = schema.SCHEMA_VERSION) -> pathlib.Path:
    return db.DB_PATH.parent / f"agree_v{version}.json"


def extract_dir(version: int = schema.SCHEMA_VERSION) -> pathlib.Path:
    return db.DB_PATH.parent / schema.EXTRACT_DIRS[version]


MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")


def cmd_catalog(con) -> int:
    rows = catalog.load_all()
    db.put_videos(con, rows)
    kinds = Counter(r["kind"] for r in rows)
    print(f"영상 {len(rows)}편 · " + " · ".join(f"{k} {kinds[k]}" for k in catalog.KINDS))
    print(f"전사 있음 {sum(r['has_transcript'] for r in rows)} · 업로드 목록에만 {sum(1 for r in rows if not r['in_transcripts'])}"
          f" · 전사 목록에만 {sum(1 for r in rows if not r['in_uploads'])}")
    for k in catalog.KINDS:
        sub = [r for r in rows if r["kind"] == k]
        print(f"  {k}: 전사 있음 {sum(r['has_transcript'] for r in sub)}/{len(sub)}")
    return 0


def cmd_sample(con) -> int:
    rows = [dict(r) for r in con.execute("SELECT * FROM videos")]
    if not rows:
        print("videos 표가 비었다 — 먼저 catalog", file=sys.stderr)
        return 1
    picks = sample.pick(rows, sample.load_tags())
    out = sample.write(picks, sample.OUT)
    print(f"표본 {len(picks)}편 → {out}")
    grid = Counter((r["upload_at"][:4], r["kind"]) for r in picks)
    for y in sorted({y for y, _ in grid}):
        print(f"  {y} 본편 {grid[(y, '본편')]:>2} · 생방송 전체 {grid[(y, '생방송 전체')]:>2}")
    print("  분야(기존 태그): " + ", ".join(f"{c} {n}" for c, n in Counter(r["stratum"].split("/")[-1] for r in picks if r["kind"] == "본편").most_common()))
    return 0


def cmd_put(con, model: str, path: str) -> int:
    if not MODEL_RE.match(model):
        print(f"model 이름이 이상하다: {model!r}(소문자·숫자·._-)", file=sys.stderr)
        return 1
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"파일을 읽지 못했다: {e}", file=sys.stderr)
        return 1
    v = db.video(con, doc.get("video_id", "")) if isinstance(doc, dict) else None
    errs = []
    if not v:
        errs.append("video_id: videos 표에 없다(catalog 먼저)")
    elif not v["has_transcript"]:
        errs.append("video_id: 전사가 없는 영상이다")
    if isinstance(doc, dict) and doc.get("model") not in (None, model):
        errs.append(f"model: 파일의 {doc.get('model')!r} 와 명령의 {model!r} 가 다르다")
    want = extract_dir() / model / f"{doc.get('video_id') if isinstance(doc, dict) else ''}.json"
    if pathlib.Path(path).resolve() != want.resolve():
        errs.append(f"파일 위치: {schema.SCHEMA_VERSION}판 자료는 {want} 에 둔다(1판 폴더는 건드리지 않는다)")
    transcript = catalog.read_transcript(v["transcript_path"]) if v and v["has_transcript"] else None
    errs += schema.check_file(doc, transcript, v["upload_at"] if v else None)
    if errs:
        print("\n".join(errs))
        return 1
    if model == "merged":
        db.put_merged(con, doc["video_id"], doc["schema_version"], doc["record"])
    else:
        db.put_record(con, doc["video_id"], model, doc["schema_version"], doc["record"], doc["seconds"])
    print(f"넣음 {doc['video_id']} · {model} · {doc['seconds']}초")
    return 0


def cmd_agree(con, a: str, b: str, version: int = schema.SCHEMA_VERSION) -> int:
    res = agree.compare(db.records(con, version), a, b)
    out = agree_out(version)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{version}판 자료 · 계산 {schema.SCHEMA_VERSION}판")
    print(f"{a} · {b} 두 모델이 다 있는 영상 {res['n_videos']}편(한쪽만 {len(res['only_one_model'])}) — 일치율, 기준 {agree.PASS_RATE:.0%}")
    for f, r in res["fields"].items():
        rate = "-" if r["rate"] is None else f"{r['rate']:.1%}"
        print(f"  {f:<13} {r['agree']:>3}/{r['n']:<3} {rate:>6} {'통과' if r['pass'] else '미달'}")
    print(f"  편당 걸린 시간(중앙값, 초): " + ", ".join(f"{m} {s}" for m, s in res["seconds_median"].items()))
    print(f"→ {out}")
    return 0


def cmd_status(con) -> int:
    kinds = dict(con.execute("SELECT kind, COUNT(*) FROM videos GROUP BY kind").fetchall())
    print(f"videos {sum(kinds.values())} · " + " · ".join(f"{k} {n}" for k, n in kinds.items()))
    for m, v, n, s in con.execute("SELECT model, schema_version, COUNT(*), ROUND(AVG(seconds)) FROM records "
                                  "GROUP BY model, schema_version ORDER BY schema_version, model"):
        print(f"records {m} {v}판: {n}건 · 평균 {s}초")
    print(f"merged {con.execute('SELECT COUNT(*) FROM merged').fetchone()[0]}건")
    print(f"표본 {'있음' if sample.OUT.exists() else '없음'} · 일치율 "
          + " · ".join(f"{v}판 {'있음' if agree_out(v).exists() else '없음'}" for v in sorted(schema.EXTRACT_DIRS)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ozl.syuka")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog")
    sub.add_parser("sample")
    p = sub.add_parser("put")
    p.add_argument("model")
    p.add_argument("path")
    p = sub.add_parser("agree")
    p.add_argument("models", nargs="*", default=["opus", "sonnet"])
    p.add_argument("--schema-version", type=int, default=schema.SCHEMA_VERSION, choices=sorted(schema.EXTRACT_DIRS))
    sub.add_parser("status")
    a = ap.parse_args(argv)
    con = db.connect(db.DB_PATH)
    try:
        if a.cmd == "catalog":
            return cmd_catalog(con)
        if a.cmd == "sample":
            return cmd_sample(con)
        if a.cmd == "put":
            return cmd_put(con, a.model, a.path)
        if a.cmd == "agree":
            if len(a.models) != 2:
                ap.error("agree 는 모델 두 개")
            return cmd_agree(con, *a.models, version=a.schema_version)
        return cmd_status(con)
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
