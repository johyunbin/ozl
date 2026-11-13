"""scripts/youtube_stats_retention.py 시험. 자료는 전부 지어낸 것이다."""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import pathlib
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("yt_retention_under_test", ROOT / "scripts" / "youtube_stats_retention.py")
yr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(yr)

OLD = "2026-01-01T00:00:00+00:00"   # 기한 2026-01-31
NEW = "2026-01-20T00:00:00+00:00"   # 기한 2026-02-19
ASOF = "2026-02-05"


def _make(root: pathlib.Path) -> None:
    meta = root / "meta"
    meta.mkdir(parents=True)
    rows = [
        {"video_id": "vidAAAA0001", "title": "가상 영상 하나", "published_at": "2025-12-01T00:00:00Z",
         "view_count": 111, "like_count": 22, "comment_count": 3, "fetched_at": OLD},
        {"video_id": "vidBBBB0002", "title": "가상 영상 둘", "published_at": "2026-01-10T00:00:00Z",
         "view_count": 444, "like_count": 55, "comment_count": 6, "fetched_at": NEW},
    ]
    (meta / "chan_videos.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (meta / "chan_videos.summary.json").write_text(json.dumps(
        {"handle": "chan", "channel": {"channel_id": "UCfake", "title": "가상 채널", "video_count": 2, "subscriber_count": 1000},
         "fetched_at": OLD}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with (meta / "catalog_chan.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["video_id", "title", "published_kst", "view_count", "like_count", "comment_count", "fetched_at"])
        w.writerow(["vidAAAA0001", "가상 영상 하나", "2025-12-01 09:00", 111, 22, 3, OLD])
        w.writerow(["vidBBBB0002", "가상 영상 둘", "2026-01-10 09:00", 444, 55, 6, NEW])
    # 받은 시각 칸이 없는 표본 — video_id 로 다른 기록에서 추정한다
    with (meta / "sample_chan.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["video_id", "title", "view_count"])
        w.writerow(["vidAAAA0001", "가상 영상 하나", 111])
    # 영상 ID 도 받은 시각도 없는 파일 — 파일 수정 시각을 쓴다
    other = root / "frames"
    other.mkdir()
    (other / "summary.json").write_text(json.dumps([{"title": "가상 묶음", "view_count": 9}], ensure_ascii=False, indent=1), encoding="utf-8")
    t = time.mktime((2026, 1, 2, 12, 0, 0, 0, 0, -1))
    os.utime(other / "summary.json", (t, t))
    # 커뮤니티 조회수(views)는 유튜브 통계가 아니다
    (root / "community.json").write_text(json.dumps([{"title": "가상 글", "views": 5}]), encoding="utf-8")


def _snapshot(root: pathlib.Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_scan_finds_files_and_times(tmp_path, capsys):
    _make(tmp_path)
    docs = {d.rel(tmp_path): d for d in yr.discover(tmp_path)}
    assert set(docs) == {"meta/chan_videos.jsonl", "meta/chan_videos.summary.json", "meta/catalog_chan.csv",
                         "meta/sample_chan.csv", "frames/summary.json"}
    summ = docs["meta/chan_videos.summary.json"].recs[0]
    assert set(summ.fields) == {"subscriber_count", "video_count"} and summ.src == yr.SRC_PARENT
    samp = docs["meta/sample_chan.csv"].recs[0]
    assert samp.src == yr.SRC_VIDEO and samp.fetched == yr.parse_time(OLD)
    assert docs["frames/summary.json"].recs[0].src == yr.SRC_MTIME
    before = _snapshot(tmp_path)
    assert yr.main(["scan", "--root", str(tmp_path), "--records"]) == 0
    out = capsys.readouterr().out
    assert "받은 시각 불명 — 파일 수정 시각 사용" in out
    assert _snapshot(tmp_path) == before


def test_purge_without_apply_changes_nothing(tmp_path, capsys):
    _make(tmp_path)
    before = _snapshot(tmp_path)
    assert yr.main(["purge", "--root", str(tmp_path), "--asof", ASOF]) == 0
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / "out").exists()
    assert "미리 보기" in capsys.readouterr().out


def test_purge_apply_clears_only_expired_stats(tmp_path):
    _make(tmp_path)
    assert yr.main(["purge", "--root", str(tmp_path), "--asof", ASOF, "--apply"]) == 0
    meta = tmp_path / "meta"
    a, b = [json.loads(l) for l in (meta / "chan_videos.jsonl").read_text(encoding="utf-8").splitlines()]
    # 기한 지난 레코드: 통계만 비고 메타는 남는다
    assert (a["view_count"], a["like_count"], a["comment_count"]) == (None, None, None)
    assert a["video_id"] == "vidAAAA0001" and a["title"] == "가상 영상 하나" and a["published_at"] == "2025-12-01T00:00:00Z"
    assert a["fetched_at"] == OLD
    # 기한 전 레코드: 그대로
    assert (b["view_count"], b["like_count"], b["comment_count"]) == (444, 55, 6)

    s = json.loads((meta / "chan_videos.summary.json").read_text(encoding="utf-8"))
    assert s["channel"]["subscriber_count"] is None and s["channel"]["video_count"] is None
    assert s["channel"]["channel_id"] == "UCfake" and s["handle"] == "chan"

    rows = list(csv.DictReader((meta / "catalog_chan.csv").open(encoding="utf-8")))
    assert rows[0]["view_count"] == "" and rows[0]["like_count"] == "" and rows[0]["title"] == "가상 영상 하나"
    assert rows[1]["view_count"] == "444"
    assert list(rows[0].keys()) == ["video_id", "title", "published_kst", "view_count", "like_count", "comment_count", "fetched_at"]

    samp = list(csv.DictReader((meta / "sample_chan.csv").open(encoding="utf-8")))
    assert samp[0]["view_count"] == "" and samp[0]["video_id"] == "vidAAAA0001"
    assert json.loads((tmp_path / "frames" / "summary.json").read_text(encoding="utf-8"))[0]["view_count"] is None
    # 커뮤니티 views 는 건드리지 않는다
    assert json.loads((tmp_path / "community.json").read_text())[0]["views"] == 5

    # 원본 사본은 남기지 않고 기록만 남긴다
    assert not (tmp_path / "archive").exists()
    logs = list((tmp_path / "out").glob("youtube_stats_purge_*.json"))
    assert len(logs) == 1
    log = json.loads(logs[0].read_text(encoding="utf-8"))
    assert log["cells_purged"] == 3 + 2 + 3 + 1 + 1
    assert "444" not in logs[0].read_text(encoding="utf-8")
    # 다시 돌려도 지울 것이 없다
    assert yr.main(["purge", "--root", str(tmp_path), "--asof", ASOF]) == 0


def test_apply_refused_on_real_private(monkeypatch, capsys):
    monkeypatch.delenv("OZL_YT_PURGE_REAL", raising=False)
    real = ROOT / "private"
    if not real.is_dir():
        pytest.skip("이 기기에는 private 폴더가 없다")
    assert yr.main(["purge", "--root", str(real), "--asof", "2099-01-01", "--apply"]) == 2
    assert "거부" in capsys.readouterr().err
    # 상위 폴더·private 하위(out 밖)도 거부, private/out 아래는 허용
    assert yr.apply_refusal(ROOT)
    assert yr.apply_refusal(real / "meta")
    assert yr.apply_refusal(real / "out" / "trial") == ""


def test_apply_refusal_lifted_by_env(monkeypatch, tmp_path):
    fake_private = tmp_path / "private"
    fake_private.mkdir()
    monkeypatch.delenv("OZL_YT_PURGE_REAL", raising=False)
    assert yr.apply_refusal(fake_private, real_private=fake_private)
    monkeypatch.setenv("OZL_YT_PURGE_REAL", "1")
    assert yr.apply_refusal(fake_private, real_private=fake_private) == ""
