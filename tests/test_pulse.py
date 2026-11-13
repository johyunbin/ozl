"""OZL Pulse 회귀 테스트 — 신호·점수·주제 추적. 네트워크·비공개 자료 없이 임시 DB 만 쓴다. 기사 제목은 전부 지어낸 것이다."""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.pulse import rank, signals, snapshot, store  # noqa: E402

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def it(title, outlet, mins_ago=30, kind="news", tier="T3", lang="ko", **kw):
    ts = (NOW - timedelta(minutes=mins_ago)).isoformat()
    return {"title": title, "url": f"https://example.com/{abs(hash((title, outlet)))}", "outlet": outlet, "feed": outlet,
            "kind": kind, "tier": tier, "lang": lang, "published": ts, "undated": False, "summary": "", "ts": ts, **kw}


STORY = ["가상의 섬나라 중앙은행 기준금리 깜짝 인상 결정",
         "가상의 섬나라 중앙은행 기준금리 깜짝 인상…시장 충격",
         "가상의 섬나라 중앙은행 기준금리 깜짝 인상 배경은"]


# ── 신호 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("s,n", [("500+", 500), ("2,000+", 2000), ("1만+", 10000), ("20K+", 20000), ("1M+", 1_000_000), ("", None), ("많음", None)])
def test_parse_traffic(s, n):
    assert signals.parse_traffic(s) == n


def test_traffic_value_monotone_and_bounded():
    vals = [signals.traffic_value(n) for n in (None, 100, 1000, 10_000, 100_000, 10_000_000)]
    assert vals[0] == 0.4 and vals[-1] == 1.0
    assert vals[1:] == sorted(vals[1:])


def test_single_outlet_never_turns_volume_on():
    """기사 한 건(매체 한 곳)은 아무리 최신이어도 보도 신호가 켜지지 않는다."""
    v, _, vol = signals.volume_signal([it(STORY[0], "가상일보", 5)], NOW)
    assert v < rank.ON and vol["n_outlets"] == 1


def test_volume_rises_with_recent_burst():
    slow = [it(STORY[0], "가상일보", 300), it(STORY[1], "가상경제", 280)]
    burst = [it(STORY[0], "가상일보", 20), it(STORY[1], "가상경제", 10), it(STORY[2], "가상방송", 5)]
    v_slow, _, _ = signals.volume_signal(slow, NOW)
    v_burst, reasons, vol = signals.volume_signal(burst, NOW)
    assert v_burst > v_slow and v_burst >= rank.ON
    assert vol["recent_1h"] == 3 and any("지난 1시간 매체 3곳" in r for r in reasons)


def test_one_outlet_rapid_updates_not_a_burst():
    """한 매체의 1보·2보·종합은 속도로 세지 않는다(매체 단위)."""
    w = [it(STORY[0], "가상통신", 50), it(STORY[1], "가상통신", 30), it(STORY[2], "가상통신", 10), it(STORY[0], "가상일보", 300)]
    v, _, vol = signals.volume_signal(w, NOW)
    assert vol["recent_1h"] == 1 and v < rank.ON


def test_single_word_trend_needs_news_overlap():
    tok = {"가상의", "섬나라", "중앙은행", "기준금리", "인상"}
    lone = [{"title": "인상", "lang": "ko", "traffic": "5000+", "trend_news": "가상 배우 인상 깊은 연기 화제"}]
    backed = [{"title": "인상", "lang": "ko", "traffic": "5000+", "trend_news": "섬나라 중앙은행 금리 인상"}]
    assert signals.trend_matches(tok, "ko", lone) == []
    assert signals.trend_matches(tok, "ko", backed) == backed


def test_trend_word_must_be_in_topic():
    """급상승어가 주제 낱말에 없으면 딸린 기사 제목이 아무리 겹쳐도 붙이지 않는다."""
    tok = {"가상시", "부동산", "대책", "서울", "시장", "반응", "전망", "규제", "발표", "공급", "확대"}
    t = [{"title": "가상가수", "lang": "ko", "traffic": "1만+", "trend_news": "가상가수 서울 콘서트 시장 반응 전망"}]
    assert signals.trend_matches(tok, "ko", t) == []


def test_trend_own_word_not_counted_as_overlap():
    """급상승어 자신은 딸린 기사 겹침 수에 넣지 않는다 — 다른 낱말 하나만 겹치는 무관한 기사에 붙지 않게."""
    tok = {"가상전자", "평택", "반도체", "공장", "증설", "공개"}
    t = [{"title": "가상전자", "lang": "ko", "traffic": "5000+", "trend_news": "가상전자 휴대폰 신제품 공개 행사"}]
    assert signals.trend_matches(tok, "ko", t) == []


def test_trend_other_language_ignored():
    assert signals.trend_matches({"rate", "hike", "island"}, "en", [{"title": "인상", "lang": "ko", "trend_news": ""}]) == []


def test_official_without_coverage_stays_below_on():
    v, r = signals.official_signal([it("가상 통계청 고용 동향 발표", "가상통계청", kind="official", tier="T1")], set(), "ko", [], NOW)
    assert v < rank.ON and "보도 없음" in r[0]
    v2, _ = signals.official_signal([it("가상 통계청 고용 동향 발표", "가상통계청", kind="official", tier="T1"),
                                     it("가상 고용 동향 발표 취업자 증가", "가상일보")], set(), "ko", [], NOW)
    assert v2 == 1.0


def test_calendar_timed_event_window():
    ev = [{"date": "2026-11-11", "kst": "2026-11-11 22:30", "org": "가상기관", "title": "가상 물가지수"}]
    tok = {"가상", "물가지수"}
    at = datetime(2026, 11, 11, 13, 0, tzinfo=timezone.utc)   # KST 22:00 — 발표 30분 전
    far = datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)   # KST 12:00 — 10시간 전
    assert signals.calendar_hits(tok, "ko", ev, at) and not signals.calendar_hits(tok, "ko", ev, far)


def test_youtube_off_without_key(monkeypatch):
    monkeypatch.delenv("OZL_YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(signals.collect, "ROOT", pathlib.Path("/nonexistent"))
    vids, st = signals.fetch_youtube(NOW)
    assert vids == [] and not st["enabled"] and "꺼짐" in st["error"]


# ── 점수 ─────────────────────────────────────────────────────────────
def test_bonus_for_independent_signals():
    one, on1 = rank.combine({"search": 0.0, "volume": 0.9, "community": 0.0, "official": 0.0})
    two, on2 = rank.combine({"search": 0.6, "volume": 0.6, "community": 0.0, "official": 0.0})
    assert on1 == ["volume"] and set(on2) == {"volume", "search"}
    assert two > one   # 보도만 강한 주제보다 보도+검색이 함께 뜬 주제가 위


@pytest.mark.parametrize("r,p,m", [(1, None, "신규"), (3, 3, "-"), (1, 4, "▲3"), (5, 2, "▼3")])
def test_movement(r, p, m):
    assert rank.movement(r, p) == m


def test_noise_titles_dropped():
    w = [it("[부고] 가상인물씨 별세", "가상일보"), it("[부고] 가상인물씨 별세", "가상경제"),
         it("[가상뉴스 이 시각 헤드라인] - 18:00", "가상뉴스"), it("[가상뉴스 이 시각 헤드라인] - 18:00", "가상방송")]
    assert snapshot.score_clusters(w, [], [], [], NOW) == []


def test_multi_signal_story_outranks_press_release():
    w = [it(t, o, m) for t, o, m in zip(STORY, ["가상일보", "가상경제", "가상방송"], [40, 20, 10])]
    w.append(it("가상 기관 정례 브리핑 개최 안내", "가상기관", 10, kind="official", tier="T1"))
    trends = [{"title": "섬나라 기준금리", "lang": "ko", "traffic": "2만+", "trend_news": ""}]
    s = sorted(snapshot.score_clusters(w, trends, [], [], NOW), key=lambda x: x["score"], reverse=True)
    assert s[0]["c"]["items"][0]["title"] in STORY
    assert {"search", "volume"} <= set(s[0]["on"])
    assert all("브리핑" not in x["c"]["items"][0]["title"] for x in s)   # 매체 한 곳·보도 없는 보도자료는 순위에 오르지 않는다


# ── 주제 추적(DB) ─────────────────────────────────────────────────────
def test_topic_persists_across_runs(tmp_path):
    db, out = tmp_path / "p.db", tmp_path / "out"
    first = [it(STORY[0], "가상일보", 40), it(STORY[1], "가상경제", 30)]
    con = store.connect(db)
    store.add_items(con, first, NOW)
    con.commit()
    r1 = snapshot.run(fetch=False, now=NOW, db=db, out_dir=out, youtube=[])
    later = NOW + timedelta(hours=1)
    con = store.connect(db)
    store.add_items(con, [it(STORY[2], "가상방송", -50)], later)   # 한 시간 뒤 새 매체가 붙는다
    con.commit()
    r2 = snapshot.run(fetch=False, now=later, db=db, out_dir=out, youtube=[])
    assert r1["ok"] and r2["ok"]
    rows = store.connect(db).execute("SELECT topic_id, run_id, n_outlets FROM topic_hours ORDER BY run_id").fetchall()
    assert len({r["topic_id"] for r in rows}) == 1             # 같은 주제로 이어진다
    assert [r["n_outlets"] for r in rows] == [2, 3]


def cl(*toks_per_item):
    items = [{"_tok": set(t)} for t in toks_per_item]
    return {"lang": "ko", "items": items, "seed_tok": items[0]["_tok"], "tok": set().union(*[i["_tok"] for i in items])}


def test_short_titles_still_link():
    topic = [{"topic_id": 7, "lang": "ko", "seed_tok": {"가상회의", "개최"}}]
    assert snapshot.match_topics([cl({"가상회의", "개최"})], topic) == [7]
    assert snapshot.match_topics([cl({"개최", "가상총회"})], topic) == [None]   # 낱말 하나만 겹치면 잇지 않는다


def test_big_cluster_does_not_steal_topic():
    """낱말 몇 개가 여러 기사에 흩어져 걸친 큰 묶음보다, 기사 하나가 주제와 크게 겹치는 진짜 후속 묶음이 주제를 잇는다."""
    topic = [{"topic_id": 1, "lang": "ko", "seed_tok": {"가상은행", "금리", "인하", "결정"}}]
    real = cl({"가상은행", "금리", "인하", "결정", "배경"})
    big = cl({"가상은행", "실적", "발표", "분기"}, {"금리", "대출", "상품", "출시"}, {"인하", "행사", "할인", "쇼핑"},
             {"가상", "쇼핑", "행사"}, {"가상", "대출"})
    assert snapshot.match_topics([big, real], topic) == [None, 1]


def test_single_outlet_capped():
    w = [it("가상 배우 결혼 발표 화제", "가상연예")]
    trends = [{"title": "가상 배우 결혼", "lang": "ko", "traffic": "50만+", "trend_news": ""}]
    s = snapshot.score_clusters(w, trends, [], [], NOW)
    assert s and s[0]["score"] <= rank.SINGLE_CAP and any("상한" in r for r in s[0]["reasons"])


def test_failed_fetch_keeps_previous_output(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "now.json").write_text('{"keep": true}', encoding="utf-8")
    trend_only = [it("가상 급상승어", "가상트렌드", kind="trend", tier="T5")]   # 뉴스·기관 피드가 전부 죽고 트렌드만 받은 경우
    monkeypatch.setattr(snapshot, "fetch_all", lambda now: (trend_only, [{"id": "x", "outlet": "x", "error": "HTTP 503"}]))
    r = snapshot.run(fetch=True, now=NOW, db=tmp_path / "p.db", out_dir=out, youtube=[])
    assert not r["ok"] and (out / "now.json").read_text(encoding="utf-8") == '{"keep": true}'


def test_calendar_generic_word_alone_not_linked():
    ev = [{"date": "2026-11-11", "kst": "2026-11-11 22:30", "org": "가상기관", "title": "미국 가상물가지수(XPI)"}]
    at = datetime(2026, 11, 11, 13, 0, tzinfo=timezone.utc)
    assert not signals.calendar_hits({"미국", "가상항공", "노선", "취항"}, "ko", ev, at)
    assert signals.calendar_hits({"미국", "가상물가지수", "상승"}, "ko", ev, at)


def test_single_token_item_links_to_itself():
    topic = [{"topic_id": 3, "lang": "ko", "seed_tok": {"가상DB"}}]
    assert snapshot.match_topics([cl({"가상DB"})], topic) == [3]


def test_publish_failure_rolls_back_run(tmp_path, monkeypatch):
    db, out = tmp_path / "p.db", tmp_path / "out"
    con = store.connect(db)
    store.add_items(con, [it(STORY[0], "가상일보", 40), it(STORY[1], "가상경제", 30)], NOW)
    con.commit()
    real = snapshot.os.replace
    monkeypatch.setattr(snapshot.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        snapshot.run(fetch=False, now=NOW, db=db, out_dir=out, youtube=[])
    monkeypatch.setattr(snapshot.os, "replace", real)
    con = store.connect(db)
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM topic_hours").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2   # 받은 기사는 남는다
    assert not list(out.glob("*.tmp"))


def test_concurrent_run_refused(tmp_path):
    import fcntl
    out = tmp_path / "out"
    out.mkdir()
    with open(out / "run.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        r = snapshot.run(fetch=False, now=NOW, db=tmp_path / "p.db", out_dir=out, youtube=[])
    assert not r["ok"] and "진행 중" in r["error"]


def test_searches_carry_sensitivity(tmp_path):
    db, out = tmp_path / "p.db", tmp_path / "out"
    con = store.connect(db)
    store.add_items(con, [it(STORY[0], "가상일보", 40), it(STORY[1], "가상경제", 30),
                          it("가상어", "가상트렌드", 20, kind="trend", tier="T5", traffic="500+", trend_news="가상 기사 제목")], NOW)
    con.commit()
    snapshot.run(fetch=False, now=NOW, db=db, out_dir=out, youtube=[])
    d = __import__("json").loads((out / "now.json").read_text(encoding="utf-8"))
    assert d["searches"] and d["searches"][0]["sensitivity"]["level"] in ("GREEN", "YELLOW", "RED")


def test_youtube_signal_off_by_policy_sends_no_request(monkeypatch):
    """키가 있어도 유튜브 인기 영상은 받지 않는다(유튜브 API 정책 — 점수에 쓰지 않는다)."""
    monkeypatch.setenv("OZL_YOUTUBE_API_KEY", "지어낸-키")
    def boom(*a, **k):
        raise AssertionError("유튜브로 요청이 나갔다")
    monkeypatch.setattr(signals.requests, "get", boom)
    assert signals.YOUTUBE_SIGNAL_ENABLED is False
    vids, st = signals.fetch_youtube(NOW)
    assert vids == [] and st["enabled"] is False and st["error"] == signals.YOUTUBE_OFF_REASON
