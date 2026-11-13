"""슈카 영상 목록 합치기 · 종류 구분 · DB 멱등 · 표본 재현성 — 지어낸 자료만(임시 폴더)."""
from __future__ import annotations

import csv
import json
from collections import Counter

import pytest

from ozl.syuka import __main__ as cli
from ozl.syuka import catalog, db, sample, schema


def _jsonl(p, rows):
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _index(p, rows):
    cols = ["channel", "video_id", "title", "upload_at", "duration_sec", "transcript_source", "status", "chars",
            "has_transcript", "has_segments", "is_live_full"]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


@pytest.fixture
def world(tmp_path):
    meta, tr = tmp_path / "meta", tmp_path / "transcripts"
    (tr / "trading_export" / "syuka").mkdir(parents=True)
    meta.mkdir()
    _jsonl(meta / "syukaworld_videos.jsonl", [
        {"video_id": "AAA", "title": "가상 본편", "published_at": "2025-01-01T10:00:00Z", "duration_sec": 1200,
         "kind": "video", "view_count": 999, "like_count": 9},
        {"video_id": "BBB", "title": "업로드에만", "published_at": "2025-02-01T10:00:00Z", "duration_sec": 45, "kind": "short"},
    ])
    _index(tr / "trading_export" / "index.csv", [
        {"channel": "syuka", "video_id": "AAA", "title": "x", "upload_at": "2025-01-01 19:00", "duration_sec": "1200",
         "transcript_source": "daglo", "chars": "5000", "has_transcript": "1"},
        {"channel": "syuka", "video_id": "CCC", "title": "전사에만", "upload_at": "2026-07-05 21:00", "duration_sec": "11000",
         "transcript_source": "daglo", "chars": "80000", "has_transcript": "1"},
        {"channel": "alex", "video_id": "ZZZ", "title": "다른 채널", "upload_at": "2026-07-05 21:00", "duration_sec": "600"},
    ])
    for vid in ("AAA", "CCC"):
        (tr / "trading_export" / "syuka" / f"{vid}.json").write_text(
            json.dumps({"video_id": vid, "text": "가상의 전사 본문", "segments": []}, ensure_ascii=False), encoding="utf-8")
    return tmp_path, meta, tr


def test_union_counts_one_sided(world):
    root, meta, tr = world
    rows = catalog.build(catalog.load_uploads(catalog.upload_files(meta)), catalog.load_index(tr / "trading_export" / "index.csv"),
                         tr, root)
    by = {r["video_id"]: r for r in rows}
    assert set(by) == {"AAA", "BBB", "CCC"}
    assert (by["BBB"]["in_uploads"], by["BBB"]["in_transcripts"], by["BBB"]["has_transcript"]) == (1, 0, 0)
    assert (by["CCC"]["in_uploads"], by["CCC"]["in_transcripts"], by["CCC"]["kind"]) == (0, 1, "생방송 전체")
    assert by["AAA"]["upload_at"] == "2025-01-01 19:00"  # UTC → KST
    assert by["AAA"]["transcript_path"] == "transcripts/trading_export/syuka/AAA.json"
    assert all("view_count" not in r and "like_count" not in r for r in rows)


@pytest.mark.parametrize("dur,kind,want", [
    (0, "video", "그 밖"), (45, "short", "쇼츠·짧은 클립"), (170, "video", "쇼츠·짧은 클립"), (200, "short", "쇼츠·짧은 클립"),
    (1500, "video", "본편"), (5400, "video", "생방송 전체"), (4000, "live", "생방송 전체"), (600, "live", "그 밖"),
    (7000, None, "생방송 전체"), (900, None, "본편"),
])
def test_classify(dur, kind, want):
    assert catalog.classify(dur, kind) == want


def _row(vid, year, kind, chars=5000):
    return {"video_id": vid, "title": "t", "upload_at": f"{year}-03-01 10:00", "kind": kind, "duration_sec": 1000,
            "chars": chars, "has_transcript": 1, "transcript_path": f"p/{vid}.json"}


def test_db_idempotent(tmp_path):
    con = db.connect(tmp_path / "s.db")
    rows = [_row("A1", 2020, "본편") | {"transcript_source": "daglo", "in_uploads": 1, "in_transcripts": 1}]
    db.put_videos(con, rows)
    db.put_videos(con, rows)
    rec = {"field": "역사"}
    db.put_record(con, "A1", "opus", 1, rec, 10)
    db.put_record(con, "A1", "opus", 1, rec, 12)
    db.put_merged(con, "A1", 1, rec)
    db.put_merged(con, "A1", 1, rec)
    assert [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("videos", "records", "merged")] == [1, 1, 1]
    assert db.records(con)[0]["seconds"] == 12
    cols = {r[1] for r in con.execute("PRAGMA table_info(videos)")}
    assert not cols & {"view_count", "like_count", "comment_count"}


def _pool():
    rows, tags, n = [], {}, 0
    for y in range(2018, 2027):
        for c in ("금융·증시", "국제·지정학", "사회·문화", "역사·과학·기술", "국내 경제·정책", "기타"):
            for _ in range(4):
                n += 1
                rows.append(_row(f"m{n}", y, "본편"))
                tags[f"m{n}"] = c
        if y in (2018, 2019, 2022, 2026):
            rows += [_row(f"l{y}{i}", y, "생방송 전체") for i in range(5)]
    rows += [_row("tiny", 2020, "본편", chars=2000), _row("sh", 2020, "쇼츠·짧은 클립")]
    return rows, tags


def test_sample_reproducible_and_spread():
    rows, tags = _pool()
    a, b = sample.pick(rows, tags, seed=7), sample.pick(rows, tags, seed=7)
    assert [r["video_id"] for r in a] == [r["video_id"] for r in b]
    assert len(a) == 60 and len({r["video_id"] for r in a}) == 60
    kinds = Counter(r["kind"] for r in a)
    assert kinds == {"본편": 48, "생방송 전체": 12}
    assert Counter(r["upload_at"][:4] for r in a if r["kind"] == "생방송 전체") == {"2018": 3, "2019": 3, "2022": 3, "2026": 3}
    per_year = Counter(r["upload_at"][:4] for r in a if r["kind"] == "본편")
    assert max(per_year.values()) - min(per_year.values()) <= 1
    per_cat = Counter(r["stratum"].split("/")[-1] for r in a if r["kind"] == "본편")
    assert "기타" not in per_cat and max(per_cat.values()) - min(per_cat.values()) <= 1
    assert not {"tiny", "sh"} & {r["video_id"] for r in a}
    assert [r["video_id"] for r in sample.pick(rows, tags, seed=8)] != [r["video_id"] for r in a]


def test_quotas_reassign_shortfall():
    assert sample.quotas(["a", "b", "c"], 9, {"a": 1, "b": 10, "c": 10}) == {"a": 1, "b": 4, "c": 4}


def test_cli_put_and_agree(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "private" / "syuka" / "syuka.db")
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    (tmp_path / "t.json").write_text(json.dumps({"text": "가나다라마바사아자차카타파하 가상의 문장을 길게 이어 붙인 전사입니다"},
                                                ensure_ascii=False), encoding="utf-8")
    con = db.connect(db.DB_PATH)
    db.put_videos(con, [_row("V1", 2024, "본편") | {"transcript_path": "t.json", "transcript_source": "daglo",
                                                   "in_uploads": 1, "in_transcripts": 1}])
    con.close()
    rec = {"topic_line": "가상 주제", "question": "왜 그런가?", "field": "역사", "intro_style": "질문으로 출발",
           "stages": ["하나", "둘", "셋"], "claims": [{"point": f"요지{i}", "value": None, "unit": None} for i in range(3)],
           "people": ["가상 인물"], "orgs": [], "countries": ["한국"], "korea_link": {"level": "직접", "line": "한국 이야기"},
           "event_period": {"start": "2024-01", "end": "2024-02"}, "sensitive": [], "notes": ""}
    ex = tmp_path / "private" / "syuka" / schema.EXTRACT_DIRS[schema.SCHEMA_VERSION]
    for m in ("opus", "sonnet"):
        f = ex / m / "V1.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"video_id": "V1", "schema_version": schema.SCHEMA_VERSION, "seconds": 30, "record": rec},
                                ensure_ascii=False), encoding="utf-8")
        assert cli.main(["put", m, str(f)]) == 0
    bad = ex / "opus" / "bad.json"
    bad.write_text(json.dumps({"video_id": "V1", "schema_version": schema.SCHEMA_VERSION, "seconds": 30,
                               "record": rec | {"notes": "가나다라마바사아자차카타파하가상의"}}, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["put", "opus", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "옮김" in out and "파일 위치" in out  # 이름이 video_id 와 다르다
    assert cli.main(["agree", "opus", "sonnet"]) == 0
    res = json.loads((tmp_path / "private" / "syuka" / f"agree_v{schema.SCHEMA_VERSION}.json").read_text(encoding="utf-8"))
    assert res["n_videos"] == 1 and res["all_pass"] and res["schema_versions"] == [schema.SCHEMA_VERSION]


def _v2_world(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr(db, "DB_PATH", root / "private" / "syuka" / "syuka.db")
    monkeypatch.setattr(catalog, "ROOT", root)
    (root / "t.json").write_text(json.dumps({"text": "가상의 전사 본문입니다"}, ensure_ascii=False), encoding="utf-8")
    con = db.connect(db.DB_PATH)
    db.put_videos(con, [_row(v, 2024, "본편") | {"transcript_path": "t.json", "transcript_source": "daglo",
                                                 "in_uploads": 1, "in_transcripts": 1} for v in ("V1", "V2")])
    return con


def _rec(**kw):
    rec = {"topic_line": "가상 주제", "question": "왜 그런가?", "field": "기업·증시", "intro_style": "개인 경험으로 출발",
           "stages": ["하나", "둘", "셋"], "claims": [{"point": f"요지{i}", "value": None, "unit": None} for i in range(3)],
           "people": ["가상 인물"], "orgs": [], "countries": ["한국"], "korea_link": {"level": "직접", "line": "한국 이야기"},
           "event_period": {"start": "2024-01", "end": "2024-02"}, "sensitive": [], "notes": ""}
    return rec | kw


def test_v2_put_keeps_v1_rows_and_agree_by_version(tmp_path, monkeypatch, capsys):
    con = _v2_world(tmp_path, monkeypatch)
    # 1판 행: 1판 값(합치기 전 분야 · 바꾸기 전 도입 방식)
    v1a = _rec(field="증시·투자", intro_style="개인 경험이나 잡담으로 출발", people=["트럼프"])
    v1b = _rec(field="기업·산업", intro_style="개인 경험이나 잡담으로 출발", people=["도널드 트럼프"])
    for vid in ("V1", "V2"):
        db.put_record(con, vid, "opus", 1, v1a, 10)
        db.put_record(con, vid, "sonnet", 1, v1b, 10)
    con.close()
    ex = tmp_path / "private" / "syuka" / schema.EXTRACT_DIRS[2]
    for m, rec in (("opus", _rec()), ("sonnet", _rec(field="해외 경제"))):
        f = ex / m / "V1.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"video_id": "V1", "schema_version": 2, "seconds": 5, "record": rec}, ensure_ascii=False),
                     encoding="utf-8")
        assert cli.main(["put", m, str(f)]) == 0
    # 1판 폴더에 둔 2판 파일은 받지 않는다
    old = tmp_path / "private" / "syuka" / schema.EXTRACT_DIRS[1] / "opus" / "V2.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"video_id": "V2", "schema_version": 2, "seconds": 5, "record": _rec()}, ensure_ascii=False),
                   encoding="utf-8")
    assert cli.main(["put", "opus", str(old)]) == 1
    # 1판 파일(schema_version 1)은 2판 폴더에 있어도 받지 않는다
    f1 = ex / "opus" / "V2.json"
    f1.write_text(json.dumps({"video_id": "V2", "schema_version": 1, "seconds": 5, "record": v1a}, ensure_ascii=False),
                  encoding="utf-8")
    assert cli.main(["put", "opus", str(f1)]) == 1
    con = db.connect(db.DB_PATH)
    assert dict(con.execute("SELECT schema_version, COUNT(*) FROM records GROUP BY schema_version").fetchall()) == {1: 4, 2: 2}
    con.close()
    capsys.readouterr()
    assert cli.main(["agree"]) == 0                             # 기본 = 최신 판
    r2 = json.loads((tmp_path / "private" / "syuka" / "agree_v2.json").read_text(encoding="utf-8"))
    assert r2["n_videos"] == 1 and r2["fields"]["field"]["rate"] == 0.0 and r2["fields"]["intro_style"]["rate"] == 1.0
    assert cli.main(["agree", "opus", "sonnet", "--schema-version", "1"]) == 0
    r1 = json.loads((tmp_path / "private" / "syuka" / "agree_v1.json").read_text(encoding="utf-8"))
    # 1판 자료에 2판 계산: 합친 분야는 같게, 트럼프/도널드 트럼프는 같은 사람
    assert r1["n_videos"] == 2 and r1["schema_versions"] == [1]
    assert all(r1["fields"][f]["rate"] == 1.0 for f in ("field", "intro_style", "people"))
    assert not (tmp_path / "private" / "syuka" / "agree.json").exists()   # 1판 원래 파일 이름은 쓰지 않는다
