"""이슈 브리핑 — 후보 묶기·기사 붙이기·번호 발급·덱 검사. 네트워크·비공개 자료 없이 지어낸 항목만 쓴다."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.briefs import candidates as C  # noqa: E402
from ozl.briefs import deck as D  # noqa: E402

EXAMPLE = yaml.safe_load((ROOT / "skills" / "ozl-news" / "deck_example.yaml").read_text(encoding="utf-8"))


def item(title, kind, feed, source=None, **kw):
    return {"title": title, "kind": kind, "feed": feed, "source": source, "lang": "ko", "outlet": kw.pop("outlet", feed),
            "url": f"https://example.invalid/{abs(hash(title))}", "tier": "T5" if kind != "news" else "T3",
            "ts": kw.pop("ts", "2026-11-11T12:00:00+00:00"), **kw}


SIG = item("가상시험 수석 부정행위 의혹", "trend", "signal_realtime", "signal", rank=2)
POST1 = item("가상시험 수석 점수 이상하다", "community", "bobae_best", "bobaedream", views=9000, votes=120, comments=40)
POST2 = item("가상시험 수석 부정행위 정리", "community", "ppomppu_free", "ppomppu", views=3000, votes=30, comments=10)
CHAT = item("퇴근길 가상 일기", "community", "bobae_best", "bobaedream", views=200, votes=1, comments=0)
LONE = item("임신", "trend", "trends_kr", "google", traffic="500+", trend_news="가상 병원 이야기")
NEWS_OK = item("가상시험 수석 부정행위 의혹 확산", "news", "yna", outlet="가상일보")
NEWS_BAD = item("가상기업 3분기 영업이익 증가", "news", "hk", outlet="가상경제")


def test_signal_and_posts_merge_into_one_issue():
    out = C.build([SIG, POST1, POST2, NEWS_OK, NEWS_BAD])
    top = out[0]
    assert top["label"] == SIG["title"]
    assert {p["site"] for p in top["posts"]} == {"bobaedream", "ppomppu"}
    assert [n["outlet"] for n in top["news"]] == ["가상일보"]   # 무관한 실적 기사는 붙지 않는다


def test_small_lone_post_dropped_but_hot_post_kept():
    out = C.build([CHAT, POST1])
    labels = [c["label"] for c in out]
    assert CHAT["title"] not in labels and POST1["title"] in labels


def test_single_word_trend_does_not_glue_unrelated():
    out = C.build([LONE, POST1])
    assert len(out) == 2   # '임신' 한 낱말로 무관한 글과 묶이지 않는다


def test_trend_news_words_do_not_attach_news():
    tr = item("가상전선", "trend", "trends_kr", "google", traffic="5000+", trend_news="가상증권 3분기 영업이익 증가")
    out = C.build([tr, NEWS_BAD])
    assert out[0]["news"] == []


def test_post_heat_not_capped():
    a = C.post_heat({"views": 5000, "votes": 50, "comments": 10})
    b = C.post_heat({"views": 20000, "votes": 300, "comments": 80})
    assert b > a > 0.6


def test_sensitive_flagged_not_dropped():
    pol = item("가상당 탄핵 공방 격화", "community", "ppomppu_issue", "ppomppu", views=8000, votes=90, comments=50)
    out = C.build([pol])
    assert out and out[0]["posts"][0]["politics"] is True


# ── 번호 ───────────────────────────────────────────────────────────
def test_ids_never_reused(tmp_path):
    ledger = tmp_path / "issued.json"
    a = D.issue("pm", "2026-11-11", 2, ledger, tmp_path)
    assert a == ["2026-11-11-pm-b01", "2026-11-11-pm-b02"]
    b = D.issue("pm", "2026-11-11", 1, ledger, tmp_path)   # 파일을 만들지 않았어도 대장에 있으면 다음 번호
    assert b == ["2026-11-11-pm-b03"]
    (tmp_path / "2026-11-11").mkdir()
    (tmp_path / "2026-11-11" / "2026-11-11-pm-b07.yaml").write_text("x: 1", encoding="utf-8")
    assert D.issue("pm", "2026-11-11", 1, ledger, tmp_path) == ["2026-11-11-pm-b08"]
    assert D.issue("am", "2026-11-11", 1, ledger, tmp_path) == ["2026-11-11-am-b01"]


# ── 검사 ───────────────────────────────────────────────────────────
def test_example_passes():
    err, _ = D.check(EXAMPLE)
    assert err == []


def bad(mutate):
    d = copy.deepcopy(EXAMPLE)
    mutate(d)
    return D.check(d)[0]


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["slides"][2].update(verdict="아마도"), "verdict"),
    (lambda d: d["slides"][2].pop("why"), "why 없음"),
    (lambda d: d["slides"][3].update(sources=[]), "근거(sources)"),
    (lambda d: d["sources"].append({"id": "s9", "outlet": "가상커뮤니티", "title": "글", "url": "https://www.bobaedream.co.kr/view?No=1", "opened_at": "x"}), "커뮤니티"),
    (lambda d: d["slides"][1].update(sources=["s99"]), "s99"),
    (lambda d: d["slides"].pop(0), "첫 장은 cover"),
    (lambda d: d.update(summary=["하나"]), "summary"),
    (lambda d: d["slides"][1].update(sources=[]), "숫자 장"),
])
def test_check_catches(mutate, needle):
    assert any(needle in e for e in bad(mutate))


def test_real_id_and_filename(tmp_path):
    d = copy.deepcopy(EXAMPLE)
    d.pop("example")
    d["brief_id"] = "2026-11-11-pm-b01"
    assert any("파일 이름" in e for e in D.check(d, "2026-11-11-pm-b02")[0])
    assert D.check(d, "2026-11-11-pm-b01")[0] == []


def test_listing_skips_broken(tmp_path):
    day = tmp_path / "2026-11-11"
    day.mkdir()
    good = copy.deepcopy(EXAMPLE); good.pop("example"); good["brief_id"] = "2026-11-11-pm-b01"
    broken = copy.deepcopy(good); broken["brief_id"] = "2026-11-11-pm-b02"; broken["slides"][2]["verdict"] = "아마도"
    for d in (good, broken):
        (day / f"{d['brief_id']}.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    out = D.listing(root=tmp_path)
    assert [x["brief_id"] for x in out] == ["2026-11-11-pm-b01"]
    assert out[0]["verdicts"] == {"근거 없음": 1, "사실과 다름": 1}
    json.dumps(out, ensure_ascii=False)


# ── 검토에서 재현한 사례(회귀) ─────────────────────────────────────
@pytest.mark.parametrize("url", [
    "https://m.bobaedream.co.kr/view?No=1", "https://WWW.PPOMPPU.CO.KR:443/zboard/view.php",
    "https://bobaedream.co.kr./view", "bobaedream.co.kr/view?no=1",
    "https://www.google.com/url?q=https%3A%2F%2Fwww.bobaedream.co.kr%2Fview%3FNo%3D1",
    "https://web.archive.org/web/2026/https://www.clien.net/service/board/park/1",
    "https://cafe.naver.com/x/1", "https://blog.naver.com/x/1", "https://youtu.be/abc", "https://t.co/abc",
    "https://\uff58.com/status/1", "https://bobaedream\u3002co.kr/view",
])
def test_community_urls_caught(url):
    assert D.is_community(url)


@pytest.mark.parametrize("url", ["https://www.yna.co.kr/view/AKR1", "https://news.example.invalid/a?ref=bob",
                                 "https://news.example.invalid/a?utm_source=facebook.com"])
def test_news_urls_not_flagged(url):
    assert not D.is_community(url)


def test_source_without_scheme_is_error():
    assert any("http(s)" in e for e in bad(lambda d: d["sources"][0].update(url="www.example.invalid/a")))


def test_no_chain_through_bridge_post():
    a = item("가상아파트 가격 폭등 논란", "community", "bobae_best", "bobaedream", views=9000, votes=100, comments=30)
    bridge = item("가상아파트 가격 연예인 의혹", "community", "ppomppu_free", "ppomppu", views=500, votes=5, comments=2)
    c = item("연예인 의혹 가상배우 해명", "community", "bobae_best", "bobaedream", views=8000, votes=90, comments=20)
    out = C.build([a, bridge, c])
    assert all(len(x["posts"]) <= 2 for x in out)   # 다리 글 하나로 세 글이 한 이슈가 되지 않는다


def test_trend_news_words_do_not_link_posts():
    tr = item("가상전선", "trend", "trends_kr", "google", traffic="5000+", trend_news="가상증권 3분기 영업이익 증가")
    post = item("3분기 영업이익 어닝 서프라이즈 가상종목", "community", "bobae_best", "bobaedream", views=9000, votes=100, comments=30)
    assert len(C.build([tr, post])) == 2


def test_signal_rank_outside_top10_not_negative():
    s = item("가상 키워드 열다섯", "trend", "signal_realtime", "signal", rank=15)
    assert C.build([s])[0]["parts"]["signal"] == 0


def test_example_flag_in_real_file_is_error():
    d = copy.deepcopy(EXAMPLE); d["brief_id"] = "2026-11-11-pm-b01"
    assert any("example" in e for e in D.check(d, "2026-11-11-pm-b01")[0])


@pytest.mark.parametrize("doc", [[1, 2], {"sources": "x"}, {"slides": [1]}, {"summary": "abc"}])
def test_check_never_raises(doc):
    err, _ = D.check(doc)
    assert err


def test_listing_survives_broken_yaml(tmp_path):
    day = tmp_path / "2026-11-11"; day.mkdir()
    (day / "2026-11-11-pm-b01.yaml").write_text("headline: [깨진", encoding="utf-8")
    assert D.listing(root=tmp_path) == []


def test_cards_each_need_source():
    def m(d):
        d["slides"].insert(2, {"type": "cards", "step": "비교", "title": "가상 숫자 카드",
                               "items": [{"value": "1건", "label": "가", "sources": ["s1"]}, {"value": "2건", "label": "나"}]})
    assert any("숫자 카드" in e for e in bad(m))


def test_number_needs_slide_sources():
    def m(d):
        d["slides"][1]["sources"] = []
        d["slides"][1]["items"] = [{"sources": ["s1"]}]
    assert any("숫자 장" in e for e in bad(m))


@pytest.mark.parametrize("date", ["2026-11-1", "2026/11/11", "20261111"])
def test_ids_reject_bad_date(tmp_path, date):
    with pytest.raises(ValueError):
        D.issue("pm", date, 1, tmp_path / "l.json", tmp_path)


def test_two_topic_anchor_does_not_bridge():
    both = item("가상시험 부정행위 의혹 가상감독 경질", "community", "bobae_best", "bobaedream", views=50000, votes=500, comments=200)
    exam = item("가상시험 부정행위 의혹 정리", "community", "ppomppu_free", "ppomppu", views=9000, votes=100, comments=30)
    coach = item("가상감독 경질 이유", "community", "bobae_best", "bobaedream", views=8000, votes=90, comments=20)
    out = C.build([both, exam, coach])
    assert all(not ({exam["title"], coach["title"]} <= {p["title"] for p in c["posts"]}) for c in out)


def test_generic_overlap_does_not_attach_news():
    post = item("가상반도체 3분기 영업이익 증가", "community", "bobae_best", "bobaedream", views=9000, votes=100, comments=30)
    other = item("가상식품 3분기 영업이익 증가", "news", "hk", outlet="가상경제")
    assert C.build([post, other])[0]["news"] == []


def test_real_deck_without_sensitivity_warns():
    d = copy.deepcopy(EXAMPLE)
    d.pop("example")
    d["brief_id"] = "2026-11-11-pm-b01"
    d.pop("sensitivity", None)
    err, warn = D.check(d, "2026-11-11-pm-b01")
    assert err == [] and any("sensitivity 없음" in w for w in warn)
    d["sensitivity"] = {"level": "GREEN", "reasons": []}
    assert not any("sensitivity" in w for w in D.check(d, "2026-11-11-pm-b01")[1])
    assert not any("sensitivity" in w for w in D.check(EXAMPLE)[1])      # 형식 예시는 묻지 않는다
