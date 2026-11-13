"""화제 엔진: 같은 주소, 전재 묶음, 하루치 그룹(설계 §2, §4-1). 제목은 전부 지어낸 것."""
import random
from datetime import timedelta

from ozl.signals import cluster, config, dedup, text
from ozl.signals.source import order_key

import test_signals_kit as K


def _a(title, outlet, published, summary="", url=None, kind="news", key=None, lang="ko", received=None):
    pub = K.kst(published)
    a = {"key": key or f"{outlet}|{title}", "title": title, "url": url or "", "canon": None, "outlet": outlet,
         "family": outlet, "feed": "x", "section": "", "kind": kind, "lang": lang, "summary": summary, "extra": {},
         "event_at": pub, "received_at": received or pub + timedelta(minutes=5), "undated": 0,
         "day": config.kst_day(pub)}
    from ozl.signals.urls import canon_url
    a["canon"] = canon_url(a["url"])
    a.update(text.analyze(title, lang))
    return a


def test_same_url_merges_and_keeps_earliest():
    x = _a("한빛전자 공장 신설", "가람일보", "2030-03-01T09:00", url="https://ga.example.test/n/1?utm_source=rss",
           received=K.kst("2030-03-01T09:05"))
    y = _a("한빛전자, 가람시 공장 신설 확정", "가람일보", "2030-03-01T09:30", url="https://www.ga.example.test/n/1?oc=1",
           received=K.kst("2030-03-01T10:05"))
    out = dedup.merge_same_url([y, x])
    assert len(out) == 1
    assert out[0]["title"] == "한빛전자 공장 신설" and out[0]["alt_titles"] == ["한빛전자, 가람시 공장 신설 확정"]


def test_trend_items_not_merged_by_feed_url():
    u = "https://trends.google.com/trending/rss?geo=KR"
    a = _a("가람시 축제", "trends_kr", "2030-03-01T09:00", url=u, kind="trend")
    b = _a("누리은행", "trends_kr", "2030-03-01T10:00", url=u, kind="trend")
    assert len(dedup.merge_same_url([a, b])) == 2


def test_thirty_wire_copies_count_once():
    """전재 30건(매체 30곳, 30분 안) + 따로 쓴 기사 2건 → 대표 1 + 사본 29, 그룹의 계열은 3."""
    arts = [_a("[속보] 한빛전자 가람시 공장서 큰불…주민 대피령", f"가상매체{i:02d}", f"2030-03-01T09:{i:02d}")
            for i in range(30)]
    arts += [_a("가람시 한빛전자 공장 화재 진화 중…원인 조사", "다른매체A", "2030-03-01T10:00"),
             _a("한빛전자 가람시 화재로 생산 차질 우려", "다른매체B", "2030-03-01T10:30")]
    copies = dedup.copy_groups(arts)
    assert len(copies) == 29
    assert {v["rep"] for v in copies.values()} == {arts[0]["key"]}
    units = [a for a in arts if a["key"] not in copies]
    groups = cluster.group_day(units, "2030-03-01")
    big = max(groups, key=lambda g: len(g["units"]))
    assert big["families"] == ["가상매체00", "다른매체A", "다른매체B"]


def test_hanja_only_copy_is_one():
    a = _a("美 솔라웨이브, 연지시 공장 건설 철회", "연합뉴스", "2030-03-01T08:00")
    b = _a("미국 솔라웨이브, 연지시 공장 건설 철회", "SBS", "2030-03-01T08:40")
    assert dedup.copy_groups([a, b]) == {b["key"]: {"rep": a["key"], "rule": "제목", "dice": 1.0}}


def test_summary_rule_and_its_limits():
    s1 = "(서울=연합뉴스) 김가상 기자 = 모아페이는 은하뱅크와 제휴해 해외 30개국에서 쓸 수 있는 간편결제 서비스를 출시한다고 밝혔다."
    s2 = "모아페이는 은하뱅크와 제휴해 해외 30개국에서 쓸 수 있는 간편결제 서비스를 출시한다고 밝혔습니다."
    a = _a("모아페이, 은하뱅크와 손잡고 해외 간편결제 출시", "연합뉴스", "2030-03-01T14:00", summary=s1)
    b = _a("은하뱅크·모아페이 해외 간편결제 서비스 공동 출시", "머니투데이", "2030-03-01T15:00", summary=s2)
    assert dedup.copy_groups([a, b])[b["key"]]["rule"] == "요약"
    short = _a("은하뱅크·모아페이 해외 간편결제 서비스 공동 출시", "머니투데이", "2030-03-01T15:00", summary="모아페이 제휴")
    assert dedup.copy_groups([a, short]) == {}
    late = _a("은하뱅크·모아페이 해외 간편결제 서비스 공동 출시", "머니투데이", "2030-03-02T16:00", summary=s2)
    assert dedup.copy_groups([a, late]) == {}       # 24시간 넘음


def test_title_dice_between_08_and_09_is_not_copy():
    a = _a("한빛전자 가람시 배터리 공장 신설 2조원 투자", "가람일보", "2030-03-01T09:00")
    b = _a("한빛전자 가람시 배터리 공장 신설 2조원 투입 결정", "누리신문", "2030-03-01T09:20")
    d = text.dice(text.norm_title(a["title"]), text.norm_title(b["title"]))
    assert 0.8 <= d < 0.9
    assert dedup.copy_groups([a, b]) == {}


def test_copy_chain_is_not_followed():
    """A-B, B-C 는 전재 관계지만 A-C 는 아니면 C 는 A 의 묶음에 들지 않는다(대표와만 견준다)."""
    a = _a("가람시 한빛전자 공장 큰불 주민 대피 명령", "매체A", "2030-03-01T09:00")
    b = _a("가람시 한빛전자 공장 큰불 주민 대피 명령 내려", "매체B", "2030-03-01T09:10")
    c = _a("가람시 한빛전자 공장 큰불 주민 대피 명령 내려져 혼란", "매체C", "2030-03-01T09:20")
    ta, tb, tc = (text.norm_title(x["title"]) for x in (a, b, c))
    assert text.dice(ta, tb) >= 0.9 and text.dice(tb, tc) >= 0.9 and text.dice(ta, tc) < 0.9
    cp = dedup.copy_groups([a, b, c])
    assert cp[b["key"]]["rep"] == a["key"] and c["key"] not in cp


def test_link_conditions_boundaries():
    assert cluster.linked(2, 0.30, 100) and not cluster.linked(2, 0.29, 0)
    assert cluster.linked(1, 0.53, 100) and not cluster.linked(1, 0.529, 0)
    assert cluster.linked(0, 0.63, 24) and not cluster.linked(0, 0.63, 24.01) and not cluster.linked(0, 0.629, 0)


def test_one_shared_name_does_not_link():
    a = _a("김하람 해밀시장, 시청사 이전 계획 발표", "가람일보", "2030-03-01T09:00")
    b = _a("배우 김하람, 새 드라마 주연 확정", "누리신문", "2030-03-01T10:00")
    gs = cluster.group_day([a, b], "2030-03-01")
    assert len(gs) == 2


def test_group_chain_prevention_needs_seed_or_two_members():
    a = _a("가람시 한빛전자 공장 화재 발생", "매체A", "2030-03-01T09:00")
    b = _a("한빛전자 가람시 화재에 젠타은행 은하뱅크 대출 점검", "매체B", "2030-03-01T09:30")
    c = _a("젠타은행 은하뱅크 대출 점검 확대", "매체C", "2030-03-01T10:00")
    e = cluster.pair_values
    assert cluster.linked(*e(a, b)) and cluster.linked(*e(b, c)) and not cluster.linked(*e(a, c))
    gs = cluster.group_day([a, b, c], "2030-03-01")
    assert [len(g["units"]) for g in gs] == [2, 1]


def test_group_order_is_deterministic():
    arts = [_a(f"가람시 한빛전자 공장 화재 {i}보", f"매체{i}", f"2030-03-01T09:{i:02d}") for i in range(8)]
    arts += [_a("누리은행 금리 인하", "매체X", "2030-03-01T09:30"), _a("누리은행 금리 인하 단행", "매체Y", "2030-03-01T09:31")]
    want = [(g["group_id"], g["units"]) for g in cluster.group_day(sorted(arts, key=order_key), "2030-03-01")]
    for seed in range(3):
        sh = arts[:]
        random.Random(seed).shuffle(sh)
        assert [(g["group_id"], g["units"]) for g in cluster.group_day(sh, "2030-03-01")] == want
    assert want[0][0].startswith("g20300301-") and len(want[0][0]) == len("g20300301-") + 8


def test_languages_grouped_separately():
    a = _a("Hanbit Electronics Recall Widens", "W1", "2030-03-01T09:00", lang="en")
    b = _a("Hanbit Electronics Recall Widens", "W2", "2030-03-01T09:05", lang="en")
    c = _a("한빛전자 리콜 확대", "가람일보", "2030-03-01T09:10")
    gs = cluster.group_day([a, b, c], "2030-03-01")
    assert sorted((g["lang"], len(g["units"])) for g in gs) == [("en", 2), ("ko", 1)]
