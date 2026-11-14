"""출처 대장으로 요청을 막는 장치 — 지어낸 대장과 가짜 요청 함수만 쓴다(마지막 시험만 실제 두 파일을 읽는다)."""
from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from ozl.pulse import community, signals, snapshot, store
from ozl.research import collect, ledger

pytestmark = pytest.mark.real_ledger   # conftest 의 '모두 허용' 바꿔 끼우기를 쓰지 않는다

NOW = datetime(2026, 11, 14, 3, 0, tzinfo=timezone.utc)
REAL = pathlib.Path(collect.HERE / "sources_ledger.yaml")

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>
<item><title>가상시 공영주차장 요금 인상 결정</title><link>https://example.com/a</link><pubDate>Sat, 14 Nov 2026 02:30:00 +0000</pubDate></item>
</channel></rss>""".encode("utf-8")


def write_ledger(tmp_path: pathlib.Path, sources: dict, monkeypatch=None) -> pathlib.Path:
    p = tmp_path / "ledger.yaml"
    p.write_text(yaml.safe_dump({"checked": "2026-11-14", "sources": sources}, allow_unicode=True), encoding="utf-8")
    if monkeypatch is not None:
        monkeypatch.setattr(ledger, "PATH", p)
    return p


class Resp:
    def __init__(self, status=200, content=RSS):
        self.status_code, self.content = status, content

    def json(self):
        return {"items": []}


class FakeGet:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, url, *a, **k):
        self.calls.append(url)
        return Resp()


@pytest.fixture
def fake_get(monkeypatch):
    g = FakeGet()
    monkeypatch.setattr(collect.requests, "get", g)   # collect·signals·community 가 같은 requests 모듈을 쓴다
    return g


def feed(fid, outlet=None, kind="news"):
    return {"id": fid, "outlet": outlet or fid, "url": f"https://example.com/{fid}.xml", "tier": "T3", "lang": "ko", "kind": kind}


ALLOW = {"collect": "허용", "score_use": "허용"}


# ── 판정 읽기 ─────────────────────────────────────────────────────────
def test_verdict_reading(tmp_path):
    p = write_ledger(tmp_path, {"a": ALLOW, "b": {"collect": "금지"}, "c": {"collect": "조건부 허용"}, "d": {"collect": " 허용 "},
                                "e": {"collect": None}, "f": "줄이 dict 가 아님"})
    assert ledger.verdict("a", "collect", p) == "허용" and ledger.allowed("a", "collect", p)
    assert ledger.verdict("b", "collect", p) == "금지" and ledger.off_reason("b", "collect", p) == "꺼짐(대장: 금지)"
    assert ledger.verdict("c", "collect", p) == "불명"            # 세 낱말이 아닌 값은 불명
    assert ledger.verdict("d", "collect", p) == "허용"            # 앞뒤 공백만 떼어 읽는다
    assert ledger.verdict("e", "collect", p) == "불명"
    assert ledger.verdict("f", "collect", p) == "불명"
    assert ledger.verdict("a", "publish", p) == "불명"            # 적지 않은 칸
    assert ledger.verdict("zzz", "collect", p) == "불명" and ledger.off_reason("zzz", "collect", p) == "꺼짐(대장: 불명)"
    assert ledger.verdict(None, "collect", p) == "불명"


def test_broken_or_missing_ledger_allows_nothing(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("sources: [이건: 목록\n  깨짐", encoding="utf-8")
    assert ledger.load(bad) == {} and not ledger.allowed("a", "collect", bad)
    lst = tmp_path / "list.yaml"
    lst.write_text("sources:\n  - a\n", encoding="utf-8")
    assert ledger.load(lst) == {}
    assert ledger.load(tmp_path / "없음.yaml") == {}


def test_ledger_cache_key_is_mtime_and_size(tmp_path):
    """같은 크기로 값만 바꿔도(수정 시각이 다르면), 수정 시각을 되돌려도(크기가 다르면) 다시 읽는다."""
    p = write_ledger(tmp_path, {"a": {"collect": "금지"}})
    assert not ledger.allowed("a", "collect", p)
    st = p.stat()
    p.write_text(p.read_text(encoding="utf-8").replace("금지", "허용"), encoding="utf-8")   # 같은 바이트 수
    assert p.stat().st_size == st.st_size
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert ledger.allowed("a", "collect", p)
    st2 = p.stat()
    p.write_text(p.read_text(encoding="utf-8").replace("허용", "금지") + "# 덧붙임\n", encoding="utf-8")
    os.utime(p, ns=(st2.st_atime_ns, st2.st_mtime_ns))                  # 수정 시각은 그대로, 크기만 다르다
    assert not ledger.allowed("a", "collect", p)


def test_ledger_reloads_after_edit(tmp_path):
    p = write_ledger(tmp_path, {"a": {"collect": "금지"}})
    assert not ledger.allowed("a", "collect", p)
    p.write_text(yaml.safe_dump({"sources": {"a": {"collect": "허용"}, "pad": {"collect": "금지"}}}, allow_unicode=True), encoding="utf-8")
    assert ledger.allowed("a", "collect", p)


# ── 요청 막기 ─────────────────────────────────────────────────────────
def test_feeds_not_allowed_send_no_request(tmp_path, monkeypatch, fake_get):
    write_ledger(tmp_path, {"ok": ALLOW, "banned": {"collect": "금지"}, "unknown": {"collect": "불명"}, "odd": {"collect": "모름"}}, monkeypatch)
    feeds = [feed("ok"), feed("banned"), feed("unknown"), feed("odd"), feed("not_in_ledger")]   # 전부 enabled(켜 둠)
    monkeypatch.setattr(collect, "load_config", lambda: {"feeds": feeds, "channels": []})
    items, sts = snapshot.fetch_all(NOW)
    assert fake_get.calls == ["https://example.com/ok.xml"]          # 허용 하나만 요청한다
    by = {s["id"]: s for s in sts}
    assert by["banned"]["error"] == "꺼짐(대장: 금지)" and by["banned"]["enabled"] is False and by["banned"]["http"] is None
    assert by["unknown"]["error"] == by["odd"]["error"] == by["not_in_ledger"]["error"] == "꺼짐(대장: 불명)"
    assert by["ok"]["error"] is None and by["ok"]["entries"] == 1
    assert {i["feed"] for i in items} == {"ok"}


def test_feed_missing_from_ledger_not_requested(tmp_path, monkeypatch, fake_get):
    write_ledger(tmp_path, {"other": ALLOW}, monkeypatch)
    items, st = collect.fetch_feed(feed("새피드"), NOW)
    assert fake_get.calls == [] and items == [] and st["error"] == "꺼짐(대장: 불명)" and st["enabled"] is False


def test_no_ledger_file_no_request_anywhere(tmp_path, monkeypatch, fake_get):
    monkeypatch.setattr(ledger, "PATH", tmp_path / "없는_대장.yaml")
    monkeypatch.setattr(collect, "load_config", lambda: {"feeds": [feed("a"), feed("trends_kr", kind="trend")],
                                                         "channels": [{"id": "syukaworld", "name": "채널", "url": "https://example.com/ch"}]})
    monkeypatch.setattr(collect, "DESK", tmp_path / "desk")
    monkeypatch.setattr(collect.coverage, "load_catalog", lambda: [])
    monkeypatch.setattr(community, "SOURCES", [{**s, "enabled": True} for s in community.SOURCES])
    monkeypatch.setattr(signals, "YOUTUBE_SIGNAL_ENABLED", True)
    monkeypatch.setenv("OZL_YOUTUBE_API_KEY", "지어낸-키")
    md = collect.collect("am", "2026-11-14", now=NOW)
    snapshot.fetch_all(NOW)
    _, csts = community.fetch_all(NOW)
    _, yst = signals.fetch_youtube(NOW)
    assert fake_get.calls == []                                       # 요청 0건
    assert all(s["error"] == "꺼짐(대장: 불명)" for s in csts) and yst["error"] == "꺼짐(대장: 불명)"
    d = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
    assert all(f["enabled"] is False and f["error"] == "꺼짐(대장: 불명)" for f in d["feeds"])
    text = md.read_text(encoding="utf-8")
    assert "받지 못한 피드" not in text and "출처 대장으로 끈 피드 3곳" in text   # 꺼짐은 실패로 세지 않는다
    assert not (collect.DESK / "latest_uploads.json").exists()


def test_community_switch_and_ledger_both_required(tmp_path, monkeypatch, fake_get):
    srcs = [{"id": "on_ok", "source": "x", "outlet": "가", "url": "https://example.com/1", "parser": "ppomppu", "enabled": True},
            {"id": "on_banned", "source": "y", "outlet": "나", "url": "https://example.com/2", "parser": "ppomppu", "enabled": True},
            {"id": "off_ok", "source": "z", "outlet": "다", "url": "https://example.com/3", "parser": "ppomppu", "enabled": False}]
    write_ledger(tmp_path, {"on_ok": ALLOW, "on_banned": {"collect": "금지"}, "off_ok": ALLOW}, monkeypatch)
    _, sts = community.fetch_all(NOW, get=fake_get, sources=srcs)
    assert fake_get.calls == ["https://example.com/1"]
    by = {s["id"]: s for s in sts}
    assert by["on_banned"]["error"] == "꺼짐(대장: 금지)" and by["on_banned"]["enabled"] is False
    assert by["off_ok"]["error"] == "꺼짐(약관)"                       # 기존 스위치가 먼저다


def test_youtube_switch_on_but_ledger_banned_sends_no_request(tmp_path, monkeypatch, fake_get):
    write_ledger(tmp_path, {"youtube_popular_kr": {"collect": "금지"}}, monkeypatch)
    monkeypatch.setattr(signals, "YOUTUBE_SIGNAL_ENABLED", True)
    monkeypatch.setenv("OZL_YOUTUBE_API_KEY", "지어낸-키")
    vids, st = signals.fetch_youtube(NOW)
    assert fake_get.calls == [] and vids == [] and st["error"] == "꺼짐(대장: 금지)" and st["enabled"] is False


def test_snapshot_does_not_count_ledger_off_as_failure(tmp_path, monkeypatch, fake_get):
    write_ledger(tmp_path, {"a": ALLOW, "b": ALLOW, "banned": {"collect": "금지", "score_use": "금지"}}, monkeypatch)
    monkeypatch.setattr(collect, "load_config", lambda: {"feeds": [feed("a", "가상일보"), feed("b", "가상경제"), feed("banned")], "channels": []})
    r = snapshot.run(fetch=True, now=NOW, db=tmp_path / "p.db", out_dir=tmp_path / "out", youtube=[])
    assert r["ok"] and r["failed"] == 0 and len(fake_get.calls) == 2


# ── 점수에서 빼기 ─────────────────────────────────────────────────────
def item(title, fid, outlet, kind="news", mins=30):
    ts = (NOW - timedelta(minutes=mins)).isoformat()
    return {"title": title, "url": f"https://example.com/{fid}/{abs(hash(title))}", "summary": "", "published": ts, "undated": False,
            "feed": fid, "outlet": outlet, "tier": "T3", "lang": "ko", "kind": kind, "section": ""}


def test_stored_items_without_score_use_left_out(tmp_path, monkeypatch):
    write_ledger(tmp_path, {"a": ALLOW, "b": ALLOW,
                            "c": {"collect": "허용", "score_use": "금지"}, "d": {"collect": "허용", "score_use": "불명"},
                            "tr": {"collect": "허용", "score_use": "불명"}}, monkeypatch)
    db = tmp_path / "p.db"
    con = store.connect(db)
    rows = [item("가상시 공영주차장 요금 인상 결정", "a", "가상일보"), item("가상시 공영주차장 요금 인상 확정", "b", "가상경제"),
            item("가상 항만 물동량 석달 연속 감소", "c", "가상신문"), item("가상 항만 물동량 석달 연속 감소세", "d", "가상방송"),
            item("가상 항만 물동량 감소 논란", "not_in_ledger", "가상라디오"),
            item("가상시 공영주차장", "tr", "가상트렌드", kind="trend")]
    store.add_items(con, rows, NOW)
    con.commit()
    out = tmp_path / "out"
    r = snapshot.run(fetch=False, now=NOW, db=db, out_dir=out)
    assert r["ok"]
    d = json.loads((out / "now.json").read_text(encoding="utf-8"))
    assert d["n_window"] == 2                                          # a·b 만 창에 든다
    assert [t["outlets"] for t in d["topics"]] == [["가상경제", "가상일보"]]
    assert d["searches"] == []                                         # score_use 불명인 급상승어도 쓰지 않는다
    feeds_seen = {i["outlet"] for t in d["topics"] for i in t["items"]}
    assert not feeds_seen & {"가상신문", "가상방송", "가상라디오", "가상트렌드"}


# ── 칸 고르기: 요청은 collect 칸만 본다 ──────────────────────────────
SPLIT = {"col_banned": {"collect": "금지", "score_use": "허용"}, "col_ok": {"collect": "허용", "score_use": "불명"}}


def test_feed_request_reads_collect_column_not_score_use(tmp_path, monkeypatch, fake_get):
    write_ledger(tmp_path, SPLIT, monkeypatch)
    _, st1 = collect.fetch_feed(feed("col_banned"), NOW)
    assert fake_get.calls == [] and st1["error"] == "꺼짐(대장: 금지)"
    _, st2 = collect.fetch_feed(feed("col_ok"), NOW)
    assert fake_get.calls == ["https://example.com/col_ok.xml"] and st2["error"] is None


def test_community_request_reads_collect_column(tmp_path, monkeypatch, fake_get):
    write_ledger(tmp_path, SPLIT, monkeypatch)
    srcs = [{"id": i, "source": i, "outlet": i, "url": f"https://example.com/{i}", "parser": "ppomppu", "enabled": True}
            for i in ("col_banned", "col_ok")]
    _, sts = community.fetch_all(NOW, get=fake_get, sources=srcs)
    assert fake_get.calls == ["https://example.com/col_ok"]
    assert {s["id"]: s["error"] for s in sts}["col_banned"] == "꺼짐(대장: 금지)"


@pytest.mark.parametrize("row, calls", [({"collect": "금지", "score_use": "허용"}, 0), ({"collect": "허용", "score_use": "불명"}, 1)])
def test_youtube_request_reads_collect_column(tmp_path, monkeypatch, fake_get, row, calls):
    write_ledger(tmp_path, {"youtube_popular_kr": row}, monkeypatch)
    monkeypatch.setattr(signals, "YOUTUBE_SIGNAL_ENABLED", True)
    monkeypatch.setenv("OZL_YOUTUBE_API_KEY", "지어낸-키")
    signals.fetch_youtube(NOW)
    assert len(fake_get.calls) == calls


# ── 채널: 대장의 키는 채널 id 그대로 ──────────────────────────────────
CH = {"id": "syukaworld", "name": "채널", "url": "https://example.com/ch"}


def test_channel_allowed_by_its_own_id_is_requested(tmp_path, monkeypatch, fake_get):
    write_ledger(tmp_path, {"syukaworld": ALLOW}, monkeypatch)
    _, sts = collect.fetch_uploads({"channels": [CH]}, NOW)
    assert fake_get.calls == ["https://example.com/ch"] and sts[0].get("enabled") is not False


def test_channel_key_with_prefix_does_not_open_it(tmp_path, monkeypatch, fake_get):
    write_ledger(tmp_path, {"channel_syukaworld": ALLOW}, monkeypatch)
    _, sts = collect.fetch_uploads({"channels": [CH]}, NOW)
    assert fake_get.calls == [] and sts[0]["error"] == "꺼짐(대장: 불명)"


# ── 손으로 돌리는 유튜브 도구 ─────────────────────────────────────────
def test_video_download_tools_blocked_by_ledger(tmp_path, monkeypatch):
    from ozl.analyze import slide_boundary_check, slide_dense
    from ozl.collect import frames, youtube_meta
    from ozl.transcribe import pilot
    write_ledger(tmp_path, {"youtube_video_download": {"collect": "금지"}, "youtube_data_api_meta": {"collect": "불명"}}, monkeypatch)
    ran = []
    for mod in (frames, slide_dense, slide_boundary_check):
        monkeypatch.setattr(mod, "sh", lambda cmd, **kw: ran.append(cmd))
        monkeypatch.setattr(mod, "TMP", tmp_path / mod.__name__)
    monkeypatch.setattr(pilot, "run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr(youtube_meta.requests, "get", lambda *a, **k: ran.append(a))
    assert frames.download("vid0000") is None
    with pytest.raises(ledger.Blocked):
        slide_dense.sample("vid0000")
    with pytest.raises(ledger.Blocked):
        slide_boundary_check.dense_titles("vid0000")
    d = tmp_path / "pilot"
    d.mkdir()
    assert "출처 대장" in pilot.transcribe("vid0000", d)["error"]
    with pytest.raises(ledger.Blocked):
        youtube_meta.get("videos", "지어낸-키", id="vid0000")
    assert ran == []                                                   # 내려받기·API 요청 0건


def test_every_request_site_goes_through_ledger():
    """src 안에서 밖으로 요청을 보내는 파일은 모두 대장을 거친다. 새 요청 지점이 생기면 여기서 걸린다."""
    root = pathlib.Path(collect.__file__).resolve().parents[1]
    pat = ("requests.get", "requests.post", "requests.Session", "urlopen(", "\"yt-dlp\"", "httpx.")
    exempt = {"research/capture.py": "카드 원문 주소(1차 출처 문서)를 받는 경로 — 대장의 출처 단위가 아니다"}
    hits, missing = [], []
    for f in sorted(root.rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        text = f.read_text(encoding="utf-8")
        if not any(p in text for p in pat):
            continue
        hits.append(rel)
        if rel in exempt:
            continue
        if "ledger.allowed(" not in text and "ledger.require(" not in text:
            missing.append(rel)
    assert missing == []
    assert {"research/collect.py", "pulse/signals.py", "pulse/community.py", "collect/frames.py"} <= set(hits)   # 검색이 헛돌지 않는다


# ── 저장분 점수 빼기: 수집 직후(fetch=True) ───────────────────────────
@pytest.mark.parametrize("score_use, n", [("불명", 0), ("허용", 1)])
def test_fresh_trends_need_score_use(tmp_path, monkeypatch, fake_get, score_use, n):
    write_ledger(tmp_path, {"a": ALLOW, "tr": {"collect": "허용", "score_use": score_use}}, monkeypatch)
    monkeypatch.setattr(collect, "load_config", lambda: {"feeds": [feed("a", "가상일보"), feed("tr", "가상트렌드", kind="trend")], "channels": []})
    out = tmp_path / "out"
    r = snapshot.run(fetch=True, now=NOW, db=tmp_path / "p.db", out_dir=out, youtube=[])
    assert r["ok"] and len(fake_get.calls) == 2                       # 둘 다 collect 허용이라 요청은 나간다
    d = json.loads((out / "now.json").read_text(encoding="utf-8"))
    assert len(d["searches"]) == n                                     # 점수에는 score_use 허용일 때만


# ── 아침 발굴(collect.collect)·보고서·이슈 후보 ────────────────────────
def test_morning_collect_leaves_out_unscorable_items(tmp_path, monkeypatch, fake_get):
    write_ledger(tmp_path, {"a": ALLOW, "c": {"collect": "허용", "score_use": "불명"},
                            "tr": {"collect": "허용", "score_use": "금지"}, "banned": {"collect": "금지"}}, monkeypatch)
    monkeypatch.setattr(collect, "load_config", lambda: {"feeds": [feed("a", "가상일보"), feed("c", "가상신문"),
                                                                   feed("tr", "가상트렌드", kind="trend"), feed("banned")], "channels": []})
    monkeypatch.setattr(collect, "DESK", tmp_path / "desk")
    monkeypatch.setattr(collect.coverage, "load_catalog", lambda: [])
    md = collect.collect("am", "2026-11-14", now=NOW)
    d = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
    assert len(fake_get.calls) == 3
    assert d["n_items_window"] == 1 and d["n_items_unscored"] == 2 and d["trends"] == []
    assert {o for c in d["clusters"] for o in c["outlets"]} == {"가상일보"}
    assert "항목 2건은 점수와 이 요약에서 뺐다" in md.read_text(encoding="utf-8")


def test_report_stats_do_not_count_ledger_off_as_failure(tmp_path, monkeypatch):
    from ozl.research import report
    desk = tmp_path / "desk"
    (desk / "2026-11-14_am").mkdir(parents=True)
    feeds = [{"id": "a", "outlet": "가", "error": None}, {"id": "b", "outlet": "나", "error": "HTTP 500"},
             {"id": "x", "outlet": "다", "error": "꺼짐(대장: 금지)", "enabled": False},
             {"id": "y", "outlet": "라", "error": "꺼짐(대장: 불명)", "enabled": False}]
    (desk / "2026-11-14_am" / "candidates.json").write_text(json.dumps(
        {"feeds": feeds, "clusters": [], "n_items_window": 0, "n_clusters": 0, "window_hours": 24, "generated_at": "2026-11-14T07:00"}), encoding="utf-8")
    monkeypatch.setattr(report.C, "DESK", desk)
    st = report._stats("2026-11-14", "am")
    assert (st["feeds_ok"], st["feeds"], st["feeds_off"]) == (1, 2, 2)
    assert report._off_note(st) == "(출처 대장으로 끈 2곳 제외)"


def test_brief_candidates_leave_out_unscorable_items(tmp_path, monkeypatch):
    from ozl.briefs import candidates
    write_ledger(tmp_path, {"a": ALLOW, "c": {"collect": "허용", "score_use": "금지"}, "d": {"collect": "허용", "score_use": "불명"}}, monkeypatch)
    db = tmp_path / "p.db"
    con = store.connect(db)
    store.add_items(con, [item("가상시 공영주차장 요금 인상 결정", "a", "가상일보"), item("가상 항만 물동량 감소", "c", "가상신문"),
                          item("가상 항만 물동량 감소세", "d", "가상방송"), item("가상 항만 물동량 논란", "not_in_ledger", "가상라디오")], NOW)
    con.commit()
    got = []
    monkeypatch.setattr(candidates, "build", lambda items, top: got.extend(items) or [])
    monkeypatch.setattr(candidates.pcommunity, "off_feeds", lambda: set())
    candidates.run("am", "2026-11-14", now=NOW, db=db, out_root=tmp_path / "briefs")
    assert {i["feed"] for i in got} == {"a"}


def test_collect_main_does_not_list_ledger_off_as_failed(tmp_path, monkeypatch, capsys):
    out = tmp_path / "candidates.md"
    out.with_suffix(".json").write_text(json.dumps({"n_clusters": 0, "feeds": [
        {"outlet": "가", "error": None}, {"outlet": "다", "error": "꺼짐(대장: 금지)", "enabled": False}]}), encoding="utf-8")
    monkeypatch.setattr(collect, "collect", lambda *a, **k: out)
    assert collect.main(["--slot", "am"]) == 0
    line = capsys.readouterr().out
    assert "피드 1/1(대장으로 끈 1곳 제외)" in line and "실패:" not in line


# ── 실제 파일 ─────────────────────────────────────────────────────────
def test_every_feed_id_is_in_real_ledger():
    """실제 feeds.yaml 의 모든 피드·채널 id, 커뮤니티 소스, 유튜브 인기가 실제 대장에 줄을 갖는다."""
    real = ledger.load(REAL)
    assert real, "대장을 읽지 못했다"
    cfg = yaml.safe_load((collect.HERE / "feeds.yaml").read_text(encoding="utf-8"))
    ids = [f["id"] for f in cfg["feeds"]] + [c["id"] for c in cfg.get("channels", [])] + \
        [s["id"] for s in community.SOURCES] + ["youtube_popular_kr"]
    missing = [i for i in ids if i not in real]
    assert missing == []
    for i in ids:   # 각 줄의 collect 칸이 세 낱말 가운데 하나다(오타로 조용히 불명이 되지 않게)
        assert real[i].get("collect") in ledger.VERDICTS, i


# ── 운영 판단(policy): 불명으로 남은 쓰임을 정해진 조건에서만 연다 ─────────────
RULE = {"rss_counting": {"enabled": True, "scope": "feeds", "when": {"collect": "허용"}, "uses": ["score_use", "store", "backup"], "note": "지어낸 규칙"}}


def write_ledger_with_policy(tmp_path, sources, policy, feeds, monkeypatch):
    p = tmp_path / "ledger.yaml"
    p.write_text(yaml.safe_dump({"checked": "2026-11-14", "policy": policy, "sources": sources}, allow_unicode=True), encoding="utf-8")
    f = tmp_path / "feeds.yaml"
    f.write_text(yaml.safe_dump({"feeds": [{"id": i} for i in feeds]}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(ledger, "PATH", p)
    monkeypatch.setattr(ledger, "FEEDS_PATH", f)
    return p


def test_policy_opens_unknown_use_only_under_its_conditions(tmp_path, monkeypatch):
    src = {"a": {"collect": "허용", "score_use": "불명", "store": "불명", "publish": "불명"},
           "b": {"collect": "허용", "score_use": "금지"},
           "c": {"collect": "불명", "score_use": "불명"},
           "d": {"collect": "허용", "score_use": "불명"}}   # 피드 목록에 없는 출처
    write_ledger_with_policy(tmp_path, src, RULE, ["a", "b", "c"], monkeypatch)
    assert ledger.verdict_source("a", "score_use") == ("허용", "운영 판단: rss_counting")
    assert ledger.allowed("a", "store") and not ledger.allowed("a", "publish")   # uses 에 없는 쓰임은 그대로 불명이다
    assert ledger.verdict_source("a", "collect") == ("허용", "대장")
    assert ledger.verdict("b", "score_use") == "금지"        # 금지는 풀리지 않는다
    assert ledger.verdict("c", "score_use") == "불명"        # 수집이 허용이 아니다
    assert ledger.verdict("d", "score_use") == "불명"        # 피드 목록 밖이다
    assert ledger.verdict("없는출처", "score_use") == "불명"
    assert ledger.scorable()({"feed": "a"}) and not ledger.scorable()({"feed": "b"})


@pytest.mark.parametrize("broken", [
    {"rss_counting": {**RULE["rss_counting"], "enabled": False}},
    {"rss_counting": {**RULE["rss_counting"], "enabled": "true"}},      # 참값 그 자체가 아니면 꺼진 것으로 본다
    {"rss_counting": {k: v for k, v in RULE["rss_counting"].items() if k != "scope"}},
    {"rss_counting": {**RULE["rss_counting"], "scope": "all"}},
    {"rss_counting": {**RULE["rss_counting"], "when": {}}},
    {"rss_counting": {**RULE["rss_counting"], "uses": "score_use"}},
    {},
])
def test_policy_that_is_off_or_malformed_opens_nothing(tmp_path, monkeypatch, broken):
    write_ledger_with_policy(tmp_path, {"a": {"collect": "허용", "score_use": "불명"}}, broken, ["a"], monkeypatch)
    assert ledger.verdict("a", "score_use") == "불명"


@pytest.mark.parametrize("use", ["collect", "publish", "commercial", "agent_read"])
def test_policy_cannot_open_collect_or_publish(tmp_path, monkeypatch, use):
    """운영 판단으로는 수집, 공개, 수익을 열 수 없다. 원문 근거로만 연다."""
    rule = {"x": {"enabled": True, "scope": "feeds", "when": {"score_use": "허용"}, "uses": [use]}}
    write_ledger_with_policy(tmp_path, {"a": {use: "불명", "score_use": "허용"}}, rule, ["a"], monkeypatch)
    assert ledger.verdict("a", use) == "불명"


def test_real_ledger_policy_reaches_only_allowed_feeds():
    """실제 대장: 운영 판단은 수집이 허용으로 확인된 피드의 score_use 와 store 만 연다. 금지는 그대로다."""
    L = ledger.load(REAL)
    uses = ("collect", "score_use", "store", "publish", "commercial", "backup", "agent_read")
    opened = [(i, u) for i in L for u in uses if ledger.verdict_source(i, u, REAL)[1] != "대장"]
    assert opened, "실제 대장에 운영 판단이 없다"
    assert {u for _, u in opened} <= {"score_use", "store", "backup"}
    assert all(ledger._raw(L[i], "collect") == "허용" and i in ledger.feed_ids() for i, _ in opened)
    assert not any(ledger._raw(L[i], u) == "금지" for i, u in opened)


# ── 사용자 결정(user_override) ───────────────────────────────────────
def _write_override(tmp_path, rule):
    p = tmp_path / "overrides.yaml"
    p.write_text(yaml.safe_dump({"overrides": {"src_blocked": rule}}, allow_unicode=True), encoding="utf-8")
    return p


GOOD_RULE = {"uses": ["collect"], "decided_by": "사용자", "decided_at": "2026-01-02 03:04",
             "scope": "지어낸 범위", "until": "2026-12-31"}


def test_user_override_opens_require_only(tmp_path, monkeypatch, capsys):
    write_ledger(tmp_path, {"src_blocked": {"collect": "금지", "score_use": "금지"}}, monkeypatch)
    ov = _write_override(tmp_path, GOOD_RULE)
    with pytest.raises(ledger.Blocked):
        ledger.require("src_blocked")                                   # 결정 파일을 넘기지 않으면 막힌다
    assert ledger.user_override("src_blocked", "collect", ov, today="2026-06-01") == GOOD_RULE
    monkeypatch.setattr(ledger, "OVERRIDES_PATH", ov)
    monkeypatch.setattr(ledger, "_today", lambda: "2026-06-01")
    ledger.require("src_blocked")                                       # 지나간다
    assert "사용자 결정으로 진행한다" in capsys.readouterr().err
    assert ledger.allowed("src_blocked", "collect") is False            # 자동 수집이 묻는 쪽은 그대로 막힌다
    assert ledger.verdict("src_blocked", "collect") == "금지"
    with pytest.raises(ledger.Blocked):
        ledger.require("src_blocked", "score_use")                      # 풀지 않은 쓰임은 막힌다


@pytest.mark.parametrize("change", [
    {"until": "2026-05-31"},            # 기한이 지남
    {"until": ""},                      # 기한 없음
    {"decided_by": "모델"},             # 사용자가 정한 것이 아님
    {"scope": ""},                      # 범위 없음
    {"decided_at": ""},                 # 정한 때 없음
    {"uses": ["store"]},                # 다른 쓰임
    {"uses": "collect"},                # 목록이 아님
])
def test_user_override_needs_every_field(tmp_path, change):
    ov = _write_override(tmp_path, {**GOOD_RULE, **change})
    assert ledger.user_override("src_blocked", "collect", ov, today="2026-06-01") is None


def test_user_override_missing_or_broken_file(tmp_path):
    assert ledger.user_override("src_blocked", "collect", tmp_path / "none.yaml") is None
    bad = tmp_path / "bad.yaml"
    bad.write_text("overrides: [1, 2", encoding="utf-8")
    assert ledger.user_override("src_blocked", "collect", bad) is None

