"""비공개 기록 백업 묶음 — 지어낸 자료로만 시험한다."""
import hashlib
import importlib.util
import json
import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("private_bundle", ROOT / "scripts" / "private_bundle.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


def make_db(p: pathlib.Path) -> None:
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE items (key TEXT PRIMARY KEY, title TEXT, feed TEXT)")
    con.execute("CREATE TABLE runs (run_id INTEGER PRIMARY KEY, at TEXT)")
    con.executemany("INSERT INTO items VALUES (?,?,?)", [("a", "가상일보 기사", "fake_news"), ("b", "가상 게시판 글", "fake_board"),
                                                         ("c", "가상경제 기사", "fake_news")])
    con.execute("INSERT INTO runs VALUES (1, '2026-01-01T00:00:00+00:00')")
    con.commit()
    con.close()


def test_snapshot_leaves_out_off_feeds_and_restores(tmp_path):
    db = tmp_path / "p.db"
    make_db(db)
    info = B.snapshot_db(db, tmp_path / "backup", {"fake_board"})
    assert info["integrity_check"] == "ok" and info["removed_off_feed_items"] == 1 and info["counts"] == {"items": 2, "runs": 1}
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3   # 원본은 그대로다
    con = B.restore_dump(tmp_path / "backup" / info["file"], tmp_path / "r.db")
    assert con.execute("SELECT COUNT(*) FROM items WHERE feed='fake_board'").fetchone()[0] == 0
    assert B.table_counts(con) == info["counts"]


def desk_with_records(root: pathlib.Path) -> pathlib.Path:
    desk = root / "desk"
    (desk / "claims" / "2026-01-01").mkdir(parents=True)
    (desk / "cards").mkdir()
    copy = b"fake official page"
    h = hashlib.sha256(copy).hexdigest()
    (desk / "claims" / "2026-01-01" / "x-c1.yaml").write_text(f"claim_id: x-c1\nverification:\n  capture:\n    sha256: {h}\n", encoding="utf-8")
    (desk / "cards" / "x.yaml").write_text("card_id: x\n", encoding="utf-8")
    (desk / "captures").mkdir()
    (desk / "captures" / "page.html").write_bytes(copy)
    return desk


def test_manifest_and_verify_catch_changed_record(tmp_path):
    desk = desk_with_records(tmp_path)
    mf = B.build_manifest(desk)
    assert mf["n_files"] == 2 and mf["n_copy_hashes"] == 1
    (desk / "evidence_manifest.json").write_text(json.dumps(mf), encoding="utf-8")
    make_db(tmp_path / "p.db")
    B.snapshot_db(tmp_path / "p.db", tmp_path / "backup", set())
    (desk / "captures" / "page.html").unlink()   # 백업에는 원문 사본이 없다
    (desk / "captures").rmdir()
    ok = B.verify(tmp_path)
    assert ok["ok"] and ok["records"] == {"listed": 2, "missing": 0, "changed": 0, "copy_hashes": 1} and ok["db"]["integrity_check"] == "ok"
    (desk / "cards" / "x.yaml").write_text("card_id: x\ntitle: 바뀜\n", encoding="utf-8")
    bad = B.verify(tmp_path)
    assert not bad["ok"] and bad["records"]["changed"] == 1


def test_check_paths_flags_copies_and_youtube_stats(tmp_path):
    desk = desk_with_records(tmp_path)
    hashes = B.copy_hashes(B.build_manifest(desk))
    (tmp_path / "desk" / "issues" / "i1" / "r1" / "captures").mkdir(parents=True)
    (tmp_path / "desk" / "issues" / "i1" / "r1" / "captures" / "a.pdf").write_bytes(b"x")
    (tmp_path / "plan").mkdir()
    (tmp_path / "plan" / "renamed_copy.bin").write_bytes(b"fake official page")   # 폴더 밖에 놓인 사본
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "videos.json").write_text('[{"video_id": "fakeVid0001", "viewCount": "123"}]', encoding="utf-8")
    (tmp_path / "plan" / "note.md").write_text("조회 기록 없음", encoding="utf-8")
    bad = B.check_paths(tmp_path, ["desk/issues/i1/r1/captures/a.pdf", "plan/renamed_copy.bin", "meta/videos.json", "plan/note.md",
                                    "desk/cards/x.yaml"], hashes)
    assert len(bad) == 3
    assert any("원문 사본 폴더" in b for b in bad) and any("해시가 같은" in b for b in bad) and any("유튜브 통계" in b for b in bad)
