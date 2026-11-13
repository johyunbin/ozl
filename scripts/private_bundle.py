#!/usr/bin/env python3
"""비공개 기록 백업 묶음 — 수집 DB 스냅숏, 근거 해시 목록, 올릴 목록 검사, 복원본 검사.

  python scripts/private_bundle.py snapshot-db         # 수집 DB 를 일관되게 떠서 private/backup/ 에 덤프(gz)로 둔다
  python scripts/private_bundle.py manifest            # 카드·기록 파일의 해시 목록을 private/desk/evidence_manifest.json 에 쓴다
  python scripts/private_bundle.py check-staged        # 올리려는 목록에 원문 사본이나 유튜브 통계가 섞였는지 본다
  python scripts/private_bundle.py verify <복원 폴더>   # 원격에서 다시 받은 묶음을 검사한다

원문 사본 파일은 백업 대상이 아니다. 복원본에서는 기록(yaml)이 목록의 해시와 같은지만 본다.
사본 파일을 다시 해시하는 검사는 이 맥의 원본에서 한다(`python -m ozl.research ...` 의 기계 대조).
꺼 둔 소스(약관)에서 전에 받아 둔 항목은 스냅숏에서 뺀다 — 원본 DB 는 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

PRIVATE = ROOT / "private"
KST = timezone(timedelta(hours=9))
HASH_RE = re.compile(r"\bsha256:\s*['\"]?([0-9a-f]{64})\b")
YT_STAT_RE = re.compile(r"[\"']?(viewCount|likeCount|commentCount|subscriberCount|view_count|like_count|comment_count)[\"']?\s*[:=,]")
COPY_DIRS = {"captures", "sources"}   # 원문 사본이 놓이는 폴더 이름(깊이와 관계없이)
TEXT_EXT = {".md", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".txt"}


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(KST)).astimezone(KST).strftime("%Y%m%d_%H%M%S")


# ── 수집 DB 스냅숏 ────────────────────────────────────────────────────
def table_counts(con: sqlite3.Connection) -> dict:
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def snapshot_db(src_db: pathlib.Path, out_dir: pathlib.Path, off_feeds: set[str], now: datetime | None = None) -> dict:
    """원본을 잠그지 않고 일관된 사본을 떠서(sqlite 백업 API) 꺼 둔 소스의 항목을 뺀 뒤 SQL 덤프(gz)로 남긴다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = stamp(now)
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td) / "copy.db"
        src = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            src.close()
        removed = 0
        if off_feeds and "items" in table_counts(dst):
            q = ",".join("?" * len(off_feeds))
            removed = dst.execute(f"DELETE FROM items WHERE feed IN ({q})", sorted(off_feeds)).rowcount
            dst.commit()
        integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
        counts = table_counts(dst)
        gz = out_dir / f"pulse_{ts}.sql.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as f:
            for line in dst.iterdump():
                f.write(line + "\n")
        dst.close()
    info = {"made_at": ts, "source": str(src_db.name), "integrity_check": integrity, "counts": counts,
            "removed_off_feed_items": removed, "off_feeds": sorted(off_feeds), "file": gz.name, "sha256": sha256_file(gz)}
    (out_dir / f"pulse_{ts}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


def restore_dump(gz: pathlib.Path, dest: pathlib.Path) -> sqlite3.Connection:
    con = sqlite3.connect(dest)
    with gzip.open(gz, "rt", encoding="utf-8") as f:
        con.executescript(f.read())
    return con


# ── 근거 해시 목록 ────────────────────────────────────────────────────
def record_files(desk: pathlib.Path) -> list[pathlib.Path]:
    out = []
    for sub in ("cards", "claims", "issues"):
        d = desk / sub
        if d.is_dir():
            out += [p for p in d.rglob("*.yaml") if not (COPY_DIRS & set(p.relative_to(desk).parts))]
    return sorted(out)


def build_manifest(desk: pathlib.Path) -> dict:
    files = []
    for p in record_files(desk):
        text = p.read_text(encoding="utf-8", errors="replace")
        files.append({"path": str(p.relative_to(desk)), "sha256": sha256_file(p), "copy_hashes": sorted(set(HASH_RE.findall(text)))})
    return {"made_at": stamp(), "n_files": len(files), "n_copy_hashes": len({h for f in files for h in f["copy_hashes"]}), "files": files}


def copy_hashes(manifest: dict) -> set[str]:
    return {h for f in manifest.get("files", []) for h in f.get("copy_hashes", [])}


# ── 올릴 목록 검사 ────────────────────────────────────────────────────
def check_paths(root: pathlib.Path, rel_paths: list[str], hashes: set[str]) -> list[str]:
    """올리려는 파일 가운데 원문 사본(폴더 이름 또는 해시로 판정)이나 유튜브 통계 칸이 든 것."""
    bad = []
    for rel in rel_paths:
        p = root / rel
        parts = set(pathlib.PurePosixPath(rel).parts[:-1])
        if COPY_DIRS & parts:
            bad.append(f"원문 사본 폴더 안의 파일: {rel}")
            continue
        if not p.is_file():
            continue
        if hashes and sha256_file(p) in hashes:
            bad.append(f"원문 사본과 해시가 같은 파일: {rel}")
            continue
        if p.suffix.lower() in TEXT_EXT and p.stat().st_size <= 20_000_000:
            if YT_STAT_RE.search(p.read_text(encoding="utf-8", errors="replace")):
                bad.append(f"유튜브 통계 칸이 든 파일: {rel}")
    return bad


def staged_paths(repo: pathlib.Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=off", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                         check=True, capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip()]


# ── 복원본 검사 ───────────────────────────────────────────────────────
def verify(restored: pathlib.Path, baseline: pathlib.Path | None = None) -> dict:
    res: dict = {"restored": str(restored), "problems": []}
    desk = restored / "desk"
    mf = desk / "evidence_manifest.json"
    if not mf.is_file():
        res["problems"].append("근거 해시 목록이 없다: desk/evidence_manifest.json")
        return res
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    missing, changed = [], []
    for f in manifest["files"]:
        p = desk / f["path"]
        if not p.is_file():
            missing.append(f["path"])
        elif sha256_file(p) != f["sha256"]:
            changed.append(f["path"])
        elif sorted(set(HASH_RE.findall(p.read_text(encoding="utf-8", errors="replace")))) != f["copy_hashes"]:
            changed.append(f["path"])
    res["records"] = {"listed": manifest["n_files"], "missing": len(missing), "changed": len(changed), "copy_hashes": manifest["n_copy_hashes"]}
    res["problems"] += [f"기록 없음: {p}" for p in missing[:10]] + [f"기록이 목록과 다름: {p}" for p in changed[:10]]
    extra = [p for p in desk.rglob("*") if p.is_file() and COPY_DIRS & set(p.relative_to(desk).parts[:-1])]
    res["copies_in_backup"] = len(extra)
    res["problems"] += [f"백업에 원문 사본이 있다: {p.relative_to(restored)}" for p in extra[:10]]

    dumps = sorted((restored / "backup").glob("pulse_*.sql.gz"))
    if not dumps:
        res["problems"].append("수집 DB 덤프가 없다: backup/pulse_*.sql.gz")
    else:
        gz = dumps[-1]
        side = json.loads(gz.with_name(gz.name.replace(".sql.gz", ".json")).read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            con = restore_dump(gz, pathlib.Path(td) / "r.db")
            integ = con.execute("PRAGMA integrity_check").fetchone()[0]
            counts = table_counts(con)
            con.close()
        res["db"] = {"file": gz.name, "integrity_check": integ, "counts": counts, "sha256_ok": sha256_file(gz) == side["sha256"],
                     "counts_ok": counts == side["counts"]}
        if integ != "ok":
            res["problems"].append(f"DB 무결성 검사 실패: {integ}")
        if not res["db"]["sha256_ok"] or not res["db"]["counts_ok"]:
            res["problems"].append("DB 덤프가 기록(해시나 건수)과 다르다")

    if baseline and baseline.is_file():
        from ozl.research import cards as C
        saved = (C.DESK, C.CARDS, C.CLAIMS)
        try:
            C.DESK, C.CARDS, C.CLAIMS = desk, desk / "cards", desk / "claims"
            now_vals = {}
            for c in C.all_cards():
                cl = C.claims_for(c["card_id"])
                now_vals[c["card_id"]] = {"publishable": C.publishable(c, cl), "digest": C.content_digest(c, cl)}
        finally:
            C.DESK, C.CARDS, C.CLAIMS = saved
        base = json.loads(baseline.read_text(encoding="utf-8"))
        diff = sorted(k for k in set(base) | set(now_vals)
                      if (base.get(k) or {}).get("publishable") != (now_vals.get(k) or {}).get("publishable")
                      or (base.get(k) or {}).get("digest") != (now_vals.get(k) or {}).get("digest"))
        res["publishable"] = {"cards": len(now_vals), "published": sorted(k for k, v in now_vals.items() if v["publishable"]), "differs": diff}
        res["problems"] += [f"공개 판정 값이 기준선과 다름: {k}" for k in diff[:10]]
    res["ok"] = not res["problems"]
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="비공개 기록 백업 묶음")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot-db", help="수집 DB 를 일관되게 떠서 덤프로 둔다")
    s.add_argument("--db", type=pathlib.Path, default=PRIVATE / "pulse" / "pulse.db")
    s.add_argument("--out", type=pathlib.Path, default=PRIVATE / "backup")
    m = sub.add_parser("manifest", help="카드·기록 파일의 해시 목록을 쓴다")
    m.add_argument("--desk", type=pathlib.Path, default=PRIVATE / "desk")
    c = sub.add_parser("check-staged", help="올리려는 목록에 원문 사본이나 유튜브 통계가 섞였는지 본다")
    c.add_argument("--repo", type=pathlib.Path, default=PRIVATE)
    v = sub.add_parser("verify", help="원격에서 다시 받은 묶음을 검사한다")
    v.add_argument("restored", type=pathlib.Path)
    v.add_argument("--baseline", type=pathlib.Path)
    a = ap.parse_args(argv)

    if a.cmd == "snapshot-db":
        from ozl.pulse import community
        info = snapshot_db(a.db, a.out, community.off_feeds())
        print(json.dumps(info, ensure_ascii=False))
        return 0 if info["integrity_check"] == "ok" else 1
    if a.cmd == "manifest":
        mf = build_manifest(a.desk)
        (a.desk / "evidence_manifest.json").write_text(json.dumps(mf, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: mf[k] for k in ("made_at", "n_files", "n_copy_hashes")}, ensure_ascii=False))
        return 0
    if a.cmd == "check-staged":
        mf_path = a.repo / "desk" / "evidence_manifest.json"
        hashes = copy_hashes(json.loads(mf_path.read_text(encoding="utf-8"))) if mf_path.is_file() else set()
        paths = staged_paths(a.repo)
        bad = check_paths(a.repo, paths, hashes)
        print(json.dumps({"staged": len(paths), "problems": bad}, ensure_ascii=False, indent=1))
        return 1 if bad else 0
    res = verify(a.restored, a.baseline)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
