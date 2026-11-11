"""커뮤니티 목록 수집(community.py)과 커뮤니티·실시간 검색어 신호 회귀 테스트.

네트워크를 쓰지 않는다. 아래 HTML·JSON·RSS 조각은 실제 페이지에서 옮긴 것이 아니라 목록 구조만 본떠 지어낸 것이고,
제목·이름·숫자도 전부 지어낸 것이다(공개 저장소 — 실제 게시글 내용을 넣지 않는다).
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.pulse import community, rank, signals, snapshot, store  # noqa: E402

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)   # KST 21:00
SRC = {s["id"]: s for s in community.SOURCES}

SIGNAL_JSON = json.dumps({
    "now": 0,
    "top10": [{"rank": 1, "keyword": "가상시 공영주차장 요금 인상", "state": "n"},
              {"rank": 2, "keyword": "가상배우", "state": "s"},
              {"rank": 3, "keyword": "", "state": "n"}],
    "articles": [{"title": "받지 않는 포털 인기 기사", "link": "https://example.com/a"}],
}, ensure_ascii=False).encode()

BOBAE_HTML = """<html><body><table><tbody>
<tr itemscope itemtype="http://schema.org/Article">
  <td class="category"><a href="/list.php?code=x">가상분류</a></td>
  <td class="pl14"><a class="bsubject" href="/view?code=best&amp;No=101&amp;vdate=" itemprop="name">가상시 주차요금 &amp; 인상 논란</a>
    <a href="/view?code=best&amp;No=101&amp;cmt=1"><span class="Comment">(<strong class="totreply">1,204</strong>)</span></a></td>
  <td class="author02"><span class="author">가상닉</span></td>
  <td class="date">20:30</td>
  <td class="recomm"><font>57</font></td>
  <td class="count">3,210</td>
</tr>
<tr itemscope itemtype="http://schema.org/Article">
  <td class="pl14"><a class="bsubject" href="/view?code=best&amp;No=99" itemprop="name">어제 올라온 가상 글</a></td>
  <td class="date">11/10</td>
  <td class="recomm"><font></font></td>
  <td class="count">88</td>
</tr>
<tr itemscope itemtype="http://schema.org/Article"><td class="pl14">광고 줄 — 제목 링크 없음</td></tr>
</tbody></table></body></html>""".encode()

PPOMPPU_RSS = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"><channel><title>가상 게시판</title>
<item><title>가상 정책 두고 갑론을박</title>
<link>http://www.ppomppu.co.kr/zboard/view.php?id=issue&amp;no=5</link>
<description>본문 앞부분 — 저장하면 안 되는 지어낸 문장</description>
<author>가상작성자</author><pubDate>Wed, 11 Nov 2026 11:40:00 GMT</pubDate><hits> [4|1500|9|1]</hits></item>
<item><title>시각이 앞날인 가상 글</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=issue&amp;no=6</link>
<pubDate>Thu, 12 Nov 2026 11:40:00 GMT</pubDate></item>
</channel></rss>""".encode()


class Resp:
    def __init__(self, status=200, content=b""):
        self.status_code, self.content = status, content


class FakeGet:
    """요청 수를 센다. url → (상태, 본문) 또는 예외."""
    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        v = self.table[url]
        if isinstance(v, Exception):
            raise v
        return Resp(*v)


# ── 파서 ─────────────────────────────────────────────────────────────
def test_parse_signal_keywords_only():
    its = community.parse_signal(SIGNAL_JSON, SRC["signal_realtime"], NOW)
    assert [i["title"] for i in its] == ["가상시 공영주차장 요금 인상", "가상배우"]   # 빈 키워드·포털 기사는 받지 않는다
    assert all(i["kind"] == "trend" and i["tier"] == "T5" and i["source"] == "signal" for i in its)
    assert [i["rank"] for i in its] == [1, 2] and not its[0]["undated"]


def test_parse_bobae_list():
    its = community.parse_bobae(BOBAE_HTML, SRC["bobae_best"], NOW)
    assert len(its) == 2
    a, b = its
    assert a["title"] == "가상시 주차요금 & 인상 논란"
    assert a["url"] == "https://www.bobaedream.co.kr/view?code=best&No=101&vdate="
    assert (a["votes"], a["views"], a["comments"]) == (57, 3210, 1204)
    assert a["published"] == (NOW - timedelta(minutes=30)).isoformat()   # KST 20:30
    assert a["kind"] == "community" and a["tier"] == "T5" and a["source"] == "bobaedream" and a["summary"] == ""
    assert "votes" not in b and b["views"] == 88 and "comments" not in b
    assert b["published"] == datetime(2026, 11, 10, tzinfo=community.KST).astimezone(timezone.utc).isoformat()


@pytest.mark.parametrize("s,expect", [
    ("20:30", datetime(2026, 11, 11, 11, 30, tzinfo=timezone.utc)),
    ("23:50", datetime(2026, 11, 10, 14, 50, tzinfo=timezone.utc)),   # 지금(KST 21:00)보다 뒤면 어제 글
    ("26.11.09", datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc)),
    ("12/31", datetime(2025, 12, 30, 15, 0, tzinfo=timezone.utc)),     # 앞날 날짜는 지난해
    ("어제", None), ("", None), ("13/45", None), ("24:10", None), ("2:99", None)])
def test_bobae_time(s, expect):
    assert community.bobae_time(s, NOW) == expect


def test_parse_ppomppu_rss_drops_body_and_marks_politics():
    its = community.parse_ppomppu(PPOMPPU_RSS, SRC["ppomppu_issue"], NOW)
    a, b = its
    assert a["summary"] == "" and "본문" not in json.dumps(its, ensure_ascii=False)   # description 은 버린다
    assert (a["comments"], a["views"], a["votes"]) == (4, 1500, 9)
    assert a["url"].startswith("https://www.ppomppu.co.kr/") and a["politics"] is True
    assert a["published"] == datetime(2026, 11, 11, 11, 40, tzinfo=timezone.utc).isoformat() and not a["undated"]
    assert b["undated"] and b["published"] == NOW.isoformat() and "views" not in b   # 앞날 시각은 믿지 않는다
    free = community.parse_ppomppu(PPOMPPU_RSS, SRC["ppomppu_free"], NOW)
    assert "politics" not in free[0]


def test_parse_ppomppu_euc_kr_declared():
    raw = PPOMPPU_RSS.decode("utf-8").replace('encoding="UTF-8"', 'encoding="euc-kr"').replace("—", "-").encode("cp949")
    its = community.parse_ppomppu(raw, SRC["ppomppu_free"], NOW)
    assert its[0]["title"] == "가상 정책 두고 갑론을박"


def test_bobae_title_entities_unescaped_once():
    raw = BOBAE_HTML.replace("가상시 주차요금 &amp; 인상 논란".encode(), "가상 &amp;lt;표시&amp;gt; 글".encode())
    assert community.parse_bobae(raw, SRC["bobae_best"], NOW)[0]["title"] == "가상 &lt;표시&gt; 글"   # 페이지에 '&lt;' 로 보이던 글자는 그대로 남는다


# ── 요청 · 실패 처리 ───────────────────────────────────────────────────
def table_ok():
    return {SRC["signal_realtime"]["url"]: (200, SIGNAL_JSON), SRC["bobae_best"]["url"]: (200, BOBAE_HTML),
            SRC["ppomppu_free"]["url"]: (200, PPOMPPU_RSS), SRC["ppomppu_issue"]["url"]: (200, PPOMPPU_RSS)}


def test_one_request_per_enabled_source_and_disabled_never_requested():
    get = FakeGet(table_ok())
    items, sts = community.fetch_all(NOW, get=get)
    enabled = [s for s in community.SOURCES if s["enabled"]]
    assert sorted(u for u, _ in get.calls) == sorted(s["url"] for s in enabled)   # 소스마다 정확히 한 번
    assert all(h["User-Agent"] == community.collect.UA["User-Agent"] for _, h in get.calls)
    assert not any("clien" in u for u, _ in get.calls)
    clien = next(s for s in sts if s["id"] == "clien_park")
    assert clien["enabled"] is False and clien["error"].startswith("꺼짐")
    assert {s["id"]: s["entries"] for s in sts if s["enabled"]} == {"signal_realtime": 2, "bobae_best": 2, "ppomppu_free": 2, "ppomppu_issue": 2}
    assert len(items) == 8


def test_failures_recorded_and_others_continue():
    t = table_ok()
    t[SRC["signal_realtime"]["url"]] = (429, b"")
    t[SRC["bobae_best"]["url"]] = ConnectionError("x")
    t[SRC["ppomppu_free"]["url"]] = (200, b"<rss><channel></channel></rss>")
    t[SRC["ppomppu_issue"]["url"]] = (200, b"not xml <")
    get = FakeGet(t)
    items, sts = community.fetch_all(NOW, get=get)
    by = {s["id"]: s for s in sts}
    assert by["signal_realtime"]["error"] == "HTTP 429" and by["signal_realtime"]["http"] == 429
    assert by["bobae_best"]["error"] == "ConnectionError"
    assert by["ppomppu_free"]["error"].startswith("항목 0개")
    assert by["ppomppu_issue"]["error"] == "ParseError"
    assert items == [] and len(get.calls) == 4   # 실패해도 다시 시도하지 않는다


# ── 신호 ─────────────────────────────────────────────────────────────
def post(title, source, outlet, **kw):
    return {"title": title, "outlet": outlet, "source": source, "kind": "community", "tier": "T5", "lang": "ko", **kw}


def test_community_value_by_sites_and_posts():
    assert signals.community_value(0, 0) == 0.0
    assert signals.community_value(1, 1) < rank.ON          # 글 하나로는 켜지지 않는다
    assert signals.community_value(1, 3) >= rank.ON
    assert signals.community_value(2, 2) > signals.community_value(1, 4)
    assert signals.community_value(3, 3) == 1.0 and signals.community_value(5, 20) == 1.0


def test_community_signal_counts_distinct_sites():
    tok = {"가상시", "주차요금", "인상"}
    two_boards = [post("a", "ppomppu", "뽐뿌 자유게시판"), post("b", "ppomppu", "뽐뿌 정치자유게시판", politics=True)]
    v1, r1 = signals.community_signal(two_boards, tok, "ko", [])
    assert v1 == signals.community_value(1, 2)               # 같은 사이트의 두 게시판은 한 곳
    assert "커뮤니티 1곳 글 2건" in r1[0] and "정치 게시판 글 포함" in r1
    v2, r2 = signals.community_signal(two_boards + [post("c", "bobaedream", "보배드림 베스트")], tok, "ko", [])
    assert v2 == signals.community_value(2, 3) and v2 >= rank.ON
    hn = [{"title": "x", "outlet": "Hacker News", "kind": "community", "lang": "en"}]   # source 칸 없는 기존 피드는 매체 이름으로 센다
    assert signals.community_signal(hn, set(), "en", [])[0] == signals.community_value(1, 1)


def sig_kw(title, r):
    return {"title": title, "lang": "ko", "kind": "trend", "source": "signal", "rank": r}


def test_signal_keyword_adds_search_signal():
    tok = signals.collect.toks("가상시 공영주차장 요금 인상 결정에 시민 반발", "ko")
    v, reasons, hits = signals.search_signal(tok, "ko", [sig_kw("가상시 공영주차장 요금 인상", 1)])
    assert v == signals.signal_rank_value(1) and v >= rank.ON
    assert "실시간 검색어" in reasons[0] and "1위" in reasons[0] and len(hits) == 1
    v10, _, _ = signals.search_signal(tok, "ko", [sig_kw("가상시 공영주차장 요금 인상", 10)])
    assert v10 < v


def test_signal_keyword_single_word_not_linked():
    tok = signals.collect.toks("가상배우 신작 촬영 시작", "ko")
    v, reasons, hits = signals.search_signal(tok, "ko", [sig_kw("가상배우", 2)])
    assert v == 0.0 and not hits


def test_signal_and_google_take_max():
    tok = signals.collect.toks("가상시 공영주차장 요금 인상 결정", "ko")
    google = {"title": "공영주차장 요금", "lang": "ko", "kind": "trend", "traffic": "100만+", "trend_news": "가상시 요금 인상"}
    v, reasons, hits = signals.search_signal(tok, "ko", [google, sig_kw("가상시 공영주차장 요금 인상", 5)])
    assert v == 1.0 and len(reasons) == 2 and len(hits) == 2


# ── snapshot 연결 ─────────────────────────────────────────────────────
def news(title, outlet, mins=30):
    ts = (NOW - timedelta(minutes=mins)).isoformat()
    return {"title": title, "url": "https://example.com/" + outlet, "summary": "", "published": ts, "undated": False,
            "feed": outlet, "outlet": outlet, "tier": "T3", "lang": "ko", "kind": "news", "section": ""}


def test_run_with_community_option(tmp_path, monkeypatch):
    feed = [news("가상시 공영주차장 요금 인상 결정", "가상일보"), news("가상시 공영주차장 요금 인상 확정", "가상경제")]
    monkeypatch.setattr(snapshot, "fetch_all", lambda now: (list(feed), []))
    calls = []
    get = FakeGet({SRC["signal_realtime"]["url"]: (200, SIGNAL_JSON), SRC["bobae_best"]["url"]: (200, BOBAE_HTML),
                   SRC["ppomppu_free"]["url"]: (503, b""), SRC["ppomppu_issue"]["url"]: (200, PPOMPPU_RSS)})
    real = community.fetch_all
    monkeypatch.setattr(snapshot.community_mod, "fetch_all", lambda now: calls.append(now) or real(now, get=get))
    out = tmp_path / "out"
    r0 = snapshot.run(fetch=True, now=NOW, db=tmp_path / "p.db", out_dir=out, youtube=[])
    assert r0["ok"] and calls == [] and r0["community"] == []   # 옵션 없이는 커뮤니티를 받지 않는다(매시 실행)

    r = snapshot.run(fetch=True, now=NOW + timedelta(minutes=1), db=tmp_path / "p.db", out_dir=out, youtube=[], community=True)
    assert r["ok"] and len(calls) == 1 and len(get.calls) == 4
    assert {s["id"]: s["error"] for s in r["community"]}["ppomppu_free"] == "HTTP 503"
    d = json.loads((out / "now.json").read_text(encoding="utf-8"))
    assert any(f["id"] == "ppomppu_free" for f in d["feeds_failed"])
    assert not any(f["id"] == "clien_park" for f in d["feeds_failed"])   # 꺼 둔 소스는 실패로 세지 않는다
    sig = [s for s in d["searches"] if s["source"] == "signal"]
    assert [s["rank"] for s in sig] == [1, 2]
    top = d["topics"][0]
    assert any("실시간 검색어" in x for x in top["reasons"]) and "가상시 공영주차장 요금 인상" in top["trend_hits"]

    con = store.connect(tmp_path / "p.db")
    rows = [w for w in store.window_items(con, NOW + timedelta(minutes=1), 6) if w.get("source") == "bobaedream"]
    assert rows and rows[0]["votes"] == 57 and rows[0]["comments"] == 1204 and rows[0]["kind"] == "community"
    pol = [w for w in store.window_items(con, NOW + timedelta(minutes=1), 6) if w.get("politics")]
    assert pol and all(w["outlet"] == "뽐뿌 정치자유게시판" for w in pol)
