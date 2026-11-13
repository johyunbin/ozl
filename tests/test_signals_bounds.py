"""화제 엔진: 임계값 경계 시험(2026-11-14 검토의 '시험 구멍' 반영). 경계 바로 아래·위 값을 하나씩 찔러, 임계값이나
비교 부호가 바뀌면 실패하게 한다. 제목·이름은 전부 지어낸 것이고, 정밀한 유사도가 필요한 곳은 서로 다른 글자를 늘어놓은
지어낸 문자열로 만든다(Dice 를 손으로 셀 수 있게).
"""
from __future__ import annotations

import types
from datetime import timedelta

import pytest

from ozl.signals import (board, category, cluster, config, days, dedup, followup, health, overrides, score, source,
                         state, text, urls)
from ozl.signals.link import Issue, Linker

import test_signals_kit as K
from test_signals_dedup import _a

D0 = "2030-03-01"


def dd(n: int) -> str:
    return config.day_add(D0, n)


def chars(n: int, start: int = 0) -> str:
    """서로 다른 한글 음절 n 개(겹치는 글자 두 개 묶음이 없다)."""
    return "".join(chr(0xAC00 + 3 * (start + i)) for i in range(n))


def bset(shared: int, total: int = 100, tag: str = "x") -> frozenset:
    """기준 묶음 BASE(b0..b99)와 shared 개를 공유하는 total 개짜리 묶음 → Dice = shared/100 (total=100 일 때)."""
    return frozenset([f"b{i}" for i in range(shared)] + [f"{tag}{i}" for i in range(total - shared)])


BASE = bset(100)


# ── 2단계 잇기 조건(link.match)
def _g(ents=(), terms=(), S=0.0, lang="ko"):
    return {"ent_fam": {e: ["f1"] for e in ents}, "term_fam": {t: ["f1"] for t in terms}, "title": "",
            "_gtb": bset(round(S * 100)), "lang": lang}


def _prof(gap, ents=("가", "나", "다"), terms=("ㄱ", "ㄴ", "ㄷ")):
    return {"ent": set(ents), "term": set(terms), "titles": [BASE], "gap": gap}


@pytest.mark.parametrize("gap, ents, terms, S, want", [
    # 사흘 안: Ee≥1 이고 S*≥0.55
    (1, ["가"], [], 0.54, False), (1, ["가"], [], 0.55, True),
    # 사흘 안: Ee≥2 이고 (Et≥1 또는 S*≥0.30)
    (1, ["가", "나"], [], 0.29, False), (1, ["가", "나"], [], 0.30, True), (1, ["가", "나"], ["ㄱ"], 0.0, True),
    (1, ["가"], ["ㄱ"], 0.30, False),
    # 어느 간격이든 제목만: S*≥0.80
    (1, [], [], 0.79, False), (1, [], [], 0.80, True), (10, [], [], 0.79, False), (10, [], [], 0.80, True),
    # 사흘 넘음: Ee≥2, Et≥2, S*≥0.30
    (4, ["가", "나"], ["ㄱ", "ㄴ"], 0.30, True), (4, ["가", "나"], ["ㄱ", "ㄴ"], 0.29, False),
    (4, ["가"], ["ㄱ", "ㄴ"], 0.50, False), (4, ["가", "나"], ["ㄱ"], 0.50, False),
    # 간격 3 과 4 의 갈림
    (3, ["가"], [], 0.55, True), (4, ["가"], [], 0.55, False),
    (3, ["가", "나"], ["ㄱ"], 0.30, True), (4, ["가", "나"], ["ㄱ"], 0.30, False),
])
def test_link_match_boundaries(gap, ents, terms, S, want):
    ok, Ee, Et, s = Linker.match(_g(ents, terms, S), _prof(gap))
    assert s == pytest.approx(S) and Ee == len(ents) and Et == len(terms)
    assert ok is want


# ── 후보 고르기와 프로필(link.candidates·_profile)
def _issue(iid, day, lang="ko", **kw):
    return Issue(iid, lang, day, "2030-03-01T00:00:00+00:00", 1, "seed-" + iid, "제목 " + iid, **kw)


def _grp(day, ents=None, terms=None, title="", tb=None, lang="ko", fams=("f1", "f2"), gid=None, units=None):
    g = {"day": day, "lang": lang, "ent_fam": {e: list(f) for e, f in (ents or {}).items()},
         "term_fam": {t: list(f) for t, f in (terms or {}).items()}, "title": title, "families": list(fams),
         "has_official": False, "group_id": gid or f"g-{day}-{title[:4]}-{sorted(ents or {})}",
         "seed": gid or f"s-{day}-{title}", "units": units or [gid or f"u-{day}-{title}"], "copies": [],
         "first_at": f"{day}T01:00:00+00:00"}
    if tb is not None:
        g["_gtb"] = tb
    return g


def _linker(reg):
    return Linker(reg, overrides.Overrides(), "2030-06-01T00:00:00+00:00", "step", 9, {}, None)


def test_title_only_group_without_shared_names_joins_issue():
    """공통 이름이 없어도 제목 Dice 0.85 면 후보에 들고 붙는다(S* ≥ 0.80)."""
    t1 = chars(41)
    t2 = chars(37) + chars(4, 900)          # 앞 37자 공유: 36/40 묶음 → Dice 0.90 이상
    assert text.dice(text.norm_title(t1), text.norm_title(t2)) >= 0.85
    L = _linker({"t20300301-001": _issue("t20300301-001", D0)})
    L.add_group("t20300301-001", _grp(D0, title=t1))
    g = _grp(dd(1), title=t2, fams=("f3", "f4"))
    assert L.candidates(g, dd(1)) == ["t20300301-001"]
    L.run_day(dd(1), [g])
    assert g["issue_id"] == "t20300301-001"


def test_profile_window_families_seeds_titles_and_dormant_limit():
    iid = "t20300301-001"
    L = _linker({iid: _issue(iid, D0)})
    L.add_group(iid, _grp(D0, ents={"감마": ["f1", "f2"], "씨앗": ["f1"]}, title="첫"))
    L.add_group(iid, _grp(dd(1), ents={"알파": ["f1", "f2"], "외톨": ["f1"]}, title="둘"))
    L.add_group(iid, _grp(dd(7), ents={"베타": ["f1", "f2"]}, title="셋"))
    p = L.profile(iid, dd(8))
    assert "알파" in p["ent"] and "베타" in p["ent"]          # 마지막 날(7일)에서 6일 앞(1일)까지 = 7일
    assert "감마" not in p["ent"]                              # 8일 앞은 빠진다
    assert "외톨" not in p["ent"]                              # 계열 1곳뿐인 낱말은 빠진다(첫날 씨앗이 아니면)
    p2 = L.profile(iid, dd(2))
    assert "씨앗" in p2["ent"]                                 # 첫날 씨앗 그룹의 고유명사는 계열 1곳이어도 들어간다
    # 휴면 보존 90일: 마지막 그룹 뒤 90일째는 잇기 대상, 91일째는 아님
    L2 = _linker({iid: _issue(iid, D0)})
    L2.add_group(iid, _grp(D0, ents={"감마": ["f1", "f2"]}))
    assert L2.profile(iid, dd(90)) is not None
    assert L2.profile(iid, dd(91)) is None


def test_profile_keeps_latest_twenty_titles():
    iid = "t20300301-001"
    L = _linker({iid: _issue(iid, D0)})
    tbs = [frozenset({f"t{i}a", f"t{i}b"}) for i in range(21)]
    for i, tb in enumerate(tbs):
        L.add_group(iid, _grp(D0, title=f"제목{i}", tb=tb))
    p = L.profile(iid, dd(1))
    assert len(p["titles"]) == 20 and tbs[0] not in p["titles"] and tbs[20] in p["titles"]


def _two_issues(tb_a, tb_b, terms_a=None):
    reg = {"t20300301-001": _issue("t20300301-001", D0), "t20300301-002": _issue("t20300301-002", D0)}
    L = _linker(reg)
    L.add_group("t20300301-001", _grp(D0, ents={"가": ["f1", "f2"], "나": ["f1", "f2"]},
                                      terms=terms_a or {}, tb=tb_a, gid="ga"))
    L.add_group("t20300301-002", _grp(D0, ents={"가": ["f1", "f2"], "나": ["f1", "f2"]}, tb=tb_b, gid="gb"))
    return L


def test_best_issue_order_ee_et_then_S_then_earlier_number():
    g = lambda: _grp(dd(1), ents={"가": ["f3"], "나": ["f3"]}, terms={"사건": ["f3"]}, tb=BASE, gid="new")
    # (Ee+Et) 가 큰 쪽이 S 보다 먼저: 001 은 사건 낱말 겹침(Ee+Et=3, S 0.40), 002 는 (2, 0.60)
    L = _two_issues(bset(40, tag="a"), bset(60, tag="q"), terms_a={"사건": ["f1", "f2"]})
    x = g()
    L.run_day(dd(1), [x])
    assert x["issue_id"] == "t20300301-001"
    # 같은 (Ee+Et) 면 S 가 큰 쪽
    L = _two_issues(bset(40, tag="a"), bset(60, tag="q"))
    x = g()
    L.run_day(dd(1), [x])
    assert x["issue_id"] == "t20300301-002"
    # 같은 (Ee+Et, S) 면 번호가 이른 쪽
    L = _two_issues(bset(50, tag="a"), bset(50, tag="q"))
    x = g()
    L.run_day(dd(1), [x])
    assert x["issue_id"] == "t20300301-001"


def test_english_group_does_not_join_korean_issue():
    iid = "t20300301-001"
    L = _linker({iid: _issue(iid, D0)})
    L.add_group(iid, _grp(D0, ents={"Zentra": ["f1", "f2"], "Velo": ["f1", "f2"]}, tb=BASE))
    g = _grp(dd(1), ents={"Zentra": ["f3"], "Velo": ["f3"]}, tb=BASE, lang="en", fams=("f3",))
    assert L.candidates(g, dd(1)) == []
    L.run_day(dd(1), [g])
    assert g["issue_id"] is None


# ── 번호 발급·재식별·흡수
def test_next_id_is_max_plus_one():
    L = _linker({"t20300301-001": _issue("t20300301-001", D0), "t20300301-003": _issue("t20300301-003", D0)})
    assert L._next_id(D0) == "t20300301-004"


@pytest.mark.parametrize("overlap, want", [(50, True), (49, False)])
def test_reidentify_overlap_boundary(overlap, want):
    iid = "t20300301-001"
    prev = {f"k{i}" for i in range(100)}
    keys = {f"k{i}" for i in range(overlap)} | {f"n{i}" for i in range(100 - overlap)}
    L = Linker({iid: _issue(iid, D0)}, overrides.Overrides(), "x", "step", 1, {iid: prev}, None)
    got = L._reidentify({"lang": "ko"}, D0, keys)
    assert (got == iid) is want


def test_reidentify_skips_split_children():
    iid = "t20300301-002"
    L = Linker({iid: _issue(iid, D0, split_of="t20300301-001")}, overrides.Overrides(), "x", "step", 1,
               {iid: {"k1", "k2"}}, None)
    assert L._reidentify({"lang": "ko"}, D0, {"k1", "k2"}) is None


@pytest.mark.parametrize("prev, now, owner, want", [
    ({"k1", "k2"}, {"k1"}, "t20300301-002", "absorbed"),                   # 1/2 = 0.5
    ({"k1", "k2", "k3"}, {"k1"}, "t20300301-002", "vanished"),             # 1/3
    ({"k1", "k2"}, {"k1", "k2"}, "임시-abcdef12", "vanished"),              # 임시 번호로는 흡수하지 않는다
])
def test_finish_absorb_threshold_and_temp_ids(prev, now, owner, want):
    iid = "t20300301-001"
    reg = {iid: _issue(iid, D0), "t20300301-002": _issue("t20300301-002", D0)}
    L = Linker(reg, overrides.Overrides(), "x", "step", 1, {iid: prev}, None)
    L.members_now[owner] = set(now)
    L.claimed.add("t20300301-002")
    L.finish({D0})
    assert reg[iid].status == want


# ── 상태 판정(§6-1)
def _st(vs, d_idx=None, prev=None, f_new=0, partial=False):
    hist = {dd(i): v for i, v in enumerate(vs)}
    d = dd(len(vs) - 1 if d_idx is None else d_idx)
    return state.state_of(d, D0, hist, prev, f_new, partial=partial)


@pytest.mark.parametrize("vs, prev, want", [
    ([0.30], None, ("새로 뜸", 4)), ([0.29], None, (None, None)),
    ([0.35, 0.30], "새로 뜸", ("새로 뜸", 8)),                       # 이틀째는 새로 뜸 규칙을 다시 쓰지 않는다
    ([1.0, 0.90], "새로 뜸", ("정점", 6)), ([1.0, 0.89], "새로 뜸", ("새로 뜸", 8)),
    ([1.0, 0.8, 0.69], "정점", ("식는 중", 7)), ([1.0, 0.8, 0.70], "정점", ("정점", 8)),
    ([0.5, 1.0, 0.6], "정점", ("정점", 8)),                            # 하루만 내림 → 식는 중 아님
    ([1.0, 0.85, 0.8], "정점", ("정점", 8)),                           # 최댓값의 0.7 이상이면 식는 중 아님
    ([1.0, 0.29, 0.29, 0.29, 0.50], "식는 중", ("다시 오름", 3)),
    ([1.0, 0.29, 0.29, 0.29, 0.49], "식는 중", ("식는 중", 8)),
    ([1.0, 0.29, 0.30, 0.29, 0.60], "식는 중", ("식는 중", 8)),         # 사흘 가운데 하루가 0.3 이상
    ([1.0, 0.0, 0.1, 0.2, 0.6], "식는 중", ("다시 오름", 3)),            # 다시 오름이 커지는 중보다 앞
    ([0.05, 0, 0, 0, 0, 0, 0], None, ("휴면", 2)),                     # 7일째
    ([0.05, 0, 0, 0, 0, 0], None, (None, None)),                       # 6일째는 아직
    ([0.05, 0, 0, 0.15, 0, 0, 0], "식는 중", ("식는 중", 8)),            # 0.15 인 날이 있으면 휴면 아님
    ([0.05, 0, 0, 0.1, 0, 0, 0], "식는 중", ("식는 중", 8)),             # 정확히 0.1 도 휴면을 막는다
])
def test_state_rule_boundaries(vs, prev, want):
    assert _st(vs, prev=prev) == want


def test_state_dormant_comes_before_rises_again():
    """후속 사건이 있어도 최근 7일 v 가 모두 0.1 미만이면 휴면(규칙 2가 3보다 앞)."""
    assert _st([1.0, 0, 0, 0, 0, 0, 0, 0], prev="식는 중", f_new=1) == ("휴면", 2)


def test_state_partial_day_and_missing_value_branches():
    # v 없음 → 직전 상태(0 으로 보면 휴면이 되는 날)
    hist = {dd(i): v for i, v in enumerate([0.05, 0, 0, 0, 0, 0])} | {dd(6): None}
    assert state.state_of(dd(6), D0, hist, "식는 중") == ("식는 중", 8)
    # 진행 중인 오늘이 어제보다 낮으면 새로 판정하지 않는다
    assert _st([1.0, 0.8, 0.5], prev="정점", partial=True) == ("정점", 8)
    assert _st([1.0, 0.8, 0.5], prev="정점") == ("식는 중", 7)
    # 진행 중인 날로는 휴면·식는 중을 새로 정하지 않는다(v 가 어제와 같아 첫 갈래는 지나간다)
    assert _st([0.05, 0, 0, 0, 0, 0, 0], prev="식는 중", partial=True) == ("식는 중", 8)
    assert _st([0.05, 0, 0, 0, 0, 0, 0], prev="식는 중") == ("휴면", 2)
    # 진행 중인 오늘이 어제보다 낮으면 정점으로도 새로 정하지 않는다
    assert _st([1.0, 0.95, 0.92], prev="커지는 중", partial=True) == ("커지는 중", 8)
    assert _st([1.0, 0.95, 0.92], prev="커지는 중") == ("정점", 6)
    # 진행 중이어도 오르면 새로 판정한다
    assert _st([0.2, 0.3, 0.4], prev=None, partial=True) == ("커지는 중", 5)


# ── 두 구역(§6-2)
def _c(iid, day_n=1, v=0.5, v_prev=None, score_raw=50.0, cat="경제", indirect=False, vdays=2, level="GREEN",
       st=None):
    return {"issue_id": iid, "lang": "ko", "state": st, "day_n": day_n, "category": cat,
            "sensitivity": {"level": level}, "indirect": {"n": 1} if indirect else None, "score_raw": score_raw,
            "_z": {"v": v, "v_prev": v_prev, "vdays": vdays, "ended": False}}


CATS = ["정치", "사회", "경제", "국제", "과학기술", "연예", "스포츠"]


def test_zone_row_limits():
    new = [_c(f"n{i:02d}", v=0.5 + i / 100, cat=CATS[i % 7]) for i in range(12)]
    old = [_c(f"o{i:02d}", day_n=3, v=0.5, score_raw=50 + i, cat=CATS[i % 7]) for i in range(12)]
    z = board.zones(new + old, False)
    assert len(z["new"]["rows"]) == 4 and len(z["ongoing"]["rows"]) == 6


def test_zone_new_order_vnew_then_indirect_then_score_then_id():
    cs = [_c("t5", v=0.4, score_raw=80, cat="사회"), _c("t4", v=0.4, score_raw=80, cat="경제"),
          _c("t3", v=0.4, score_raw=90, cat="국제"), _c("t2", v=0.4, indirect=True, score_raw=10, cat="연예"),
          _c("t1", v=0.5, score_raw=1, cat="스포츠")]
    assert board.zones(cs, False)["new"]["rows"] == ["t1", "t2", "t3", "t4"]


def test_zone_day2_uses_yesterday_v_and_day3_moves_to_ongoing():
    a = _c("a", day_n=2, v=0.05, v_prev=0.6)
    b = _c("b", day_n=3, v=0.5, cat="사회")
    z = board.zones([a, b], False)
    assert z["new"]["rows"] == ["a"] and z["ongoing"]["rows"] == ["b"]


def test_zone_ongoing_sorted_by_score_and_sensitivity():
    cs = [_c("t1", day_n=4, score_raw=10, cat="정치"), _c("t2", day_n=4, score_raw=30, cat="사회"),
          _c("t3", day_n=4, score_raw=20, cat="경제", level="YELLOW"), _c("t4", day_n=4, score_raw=90, level="RED")]
    assert board.zones(cs, False)["ongoing"]["rows"] == ["t2", "t3", "t1"]


def test_zone_category_cap_exact_and_odd_limit(monkeypatch):
    new = [_c(f"n{i}", v=0.9 - i / 100) for i in range(6)]
    old = [_c(f"o{i}", day_n=3, score_raw=90 - i) for i in range(8)]
    z = board.zones(new + old, False)
    assert z["new"]["rows"] == ["n0", "n1"] and z["new"]["capped"] == [{"category": "경제", "skipped": 4}]
    assert z["ongoing"]["rows"] == ["o0", "o1", "o2"]
    monkeypatch.setattr(config, "ZONE_NEW_MAX", 5)
    assert len(board.zones(new, False)["new"]["rows"]) == 2           # 5 // 2 = 2 (올림이면 3)


def test_zone_other_category_is_not_capped():
    cs = [_c(f"n{i}", v=0.9 - i / 100, cat=category.OTHER) for i in range(5)]
    z = board.zones(cs, False)
    assert len(z["new"]["rows"]) == 4 and z["new"]["capped"] == []


# ── 전재 묶기(dedup.copy_relation)
def _pair(ta, tb, hours, sa="", sb="", lang_b="ko", kind="news"):
    a = _a(ta, "매체A", "2030-03-01T00:00", summary=sa)
    b = _a(tb, "매체B", "2030-03-01T00:00", summary=sb, lang=lang_b, kind=kind)
    b["event_at"] = a["event_at"] + timedelta(hours=hours)
    if kind != "news":
        a["kind"] = kind
    return dedup.copy_relation(a, b)


TITLE = "가람시 한빛전자 신공장 착공 소식에 주민들 기대감"


@pytest.mark.parametrize("hours, want", [(11 + 59 / 60, "제목"), (12 + 1 / 60, None)])
def test_copy_title_rule_hours(hours, want):
    r = _pair(TITLE, TITLE, hours)
    assert (r[0] if r else None) == want


S50 = chars(51, 100)


def _summary_pair(prefix: int, title_shared: int = 21, hours: float = 1.0, minlen: int = 51):
    ta = chars(21)
    tb = chars(title_shared) + chars(21 - title_shared, 700)
    sa = S50[:minlen]
    sb = S50[:prefix] + chars(minlen - prefix, 400) if prefix < minlen else S50[:minlen]
    return _pair(ta, tb, hours, sa, sb)


def test_copy_summary_rule_boundaries():
    # 요약 Dice: 51자끼리 앞 k 자 공유 → (k−1)/50. 39자 → 0.76, 37자 → 0.72
    assert text.dice(text.norm_summary(S50[:51]), text.norm_summary(S50[:39] + chars(12, 400))) == pytest.approx(38 / 50)
    assert _summary_pair(39, title_shared=9)[0] == "요약"          # 요약 0.76, 제목 (9−1)/20 = 0.40
    assert _summary_pair(37, title_shared=9) is None                # 요약 0.72 < 0.75
    assert _summary_pair(39, title_shared=8) is None                # 제목 0.35 < 0.40
    assert _summary_pair(39, title_shared=9, hours=23 + 59 / 60)[0] == "요약"
    assert _summary_pair(39, title_shared=9, hours=24 + 1 / 60) is None


@pytest.mark.parametrize("n, want", [(40, "요약"), (39, None)])
def test_copy_summary_min_length(n, want):
    r = _summary_pair(n, title_shared=9, minlen=n)
    assert (r[0] if r else None) == want


def test_copy_needs_same_language_and_news():
    assert _pair(TITLE, TITLE, 0.5, lang_b="en") is None
    assert _pair(TITLE, TITLE, 0.5, kind="official") is None


def test_copy_tie_goes_to_earlier_representative():
    core = chars(30)
    r1 = _a(chars(4, 500) + core, "매체A", "2030-03-01T09:00")
    r2 = _a(core + chars(4, 600), "매체B", "2030-03-01T09:01")
    a = _a(core, "매체C", "2030-03-01T09:30")
    for x in (r1, r2, a):
        x["entities"] = []       # 지어낸 글자열을 Kiwi 가 저마다 다른 이름으로 낸다. 고유명사가 같은 제목끼리의 동점만 본다
    assert dedup.copy_relation(r1, r2) is None
    dedup._prep(a)
    assert text.dice(r1["_tb"], a["_tb"]) == text.dice(r2["_tb"], a["_tb"])
    out = dedup.copy_groups([r1, r2, a])
    assert out == {a["key"]: {"rep": r1["key"], "rule": "제목", "dice": round(text.dice(r1["_tb"], a["_tb"]), 6)}}


def test_same_url_official_items_merge():
    u = "https://gov.example.test/press/77"
    x = _a("가람시 보조금 공고", "가람시청", "2030-03-01T09:00", url=u, kind="official")
    y = _a("가람시 보조금 공고(정정)", "가람시청", "2030-03-01T10:00", url=u + "?utm_source=rss", kind="official")
    assert len(dedup.merge_same_url([x, y])) == 1


# ── 별칭(text)·합치기 판단 따라가기(overrides)
@pytest.fixture
def fake_aliases(monkeypatch):
    R = dict(text.resources())
    R["amap"] = {**R["amap"], "가상시": "가상광역시", "벨로니아": "벨로니아공화국", "zentracorp": "젠트라",
                 "중": "중국", "물가지수": "가상물가지표"}
    R["canon"] = set(R["amap"].values())
    monkeypatch.setattr(text, "resources", lambda: R)
    return R


def test_alias_two_eojeol_particle_english_case(fake_aliases):
    assert "가상광역시" in text.analyze("가상 시 신공장 착공", "ko")["entities"]
    assert "벨로니아공화국" in text.analyze("한빛전자 벨로니아에서 공장 착공", "ko")["entities"]
    assert "젠트라" in text.analyze("ZENTRA CORP shares jump", "en")["entities"]
    # 일반명사로 읽히는 별칭은 조사를 뗀 꼴로만 찾힌다(고유명사 보강 단계가 대신 잡지 않는다)
    for p in ("가", "를", "에서"):
        assert "가상물가지표" in text.analyze(f"정부 물가지수{p} 다시 논의", "ko")["entities"]


def test_one_letter_alias_is_not_used(fake_aliases):
    a = text.analyze("가람시 신공장 계획 검토 중", "ko")
    assert "중국" not in a["entities"] and "중국" not in a["terms"]


def test_indirect_word_is_not_an_entity():
    a = text.analyze("가람시 한빛전자 SNS서 화제", "ko")
    assert "SNS" not in a["entities"] and a["indirect"]


def test_override_resolve_follows_chain_and_last_merge():
    ov = overrides.Overrides(merges=[{"keep": "B", "absorb": ["A"], "day": D0},
                                     {"keep": "C", "absorb": ["B"], "day": D0}])
    assert ov.resolve("A", D0) == "C"
    ov2 = overrides.Overrides(merges=[{"keep": "B", "absorb": ["A"], "day": D0},
                                      {"keep": "C", "absorb": ["A"], "day": D0}])
    assert ov2.resolve("A", D0) == "C"


# ── 점수 산식 가장자리(score)
def test_score_parts_are_capped_at_one():
    assert score.h_screen(10) == 1.0 and score.p_value(9) == 1.0 and score.d_value(15, 0) == 1.0
    assert score.s_raw(10, 1.0, score.p_value(9), score.d_value(10, 10)) == pytest.approx(100.0)


def test_P_counts_exactly_point_one_and_not_before_first_day():
    hist = {dd(-1): 0.9, D0: 0.1, dd(1): 0.0999}
    assert score.p_days(hist, dd(1), D0, None) == [D0]


def test_D_window_edges():
    r = score.day_values(A=0, g=0.0, w=None, official=False, ok={score.NEWS}, prev_H=0.0, v_hist={},
                         fe_hist={dd(4): (1, 0), dd(3): (0, 4)}, f=0, e=0, day=dd(10), first_day=D0)
    assert r["f_sum"] == 1 and r["e_sum"] == 0                    # d−6 은 들고 d−7 은 빠진다


def test_present_kinds_and_B_edges():
    assert score.present_kinds(1, 0.0, None, False) == [score.NEWS]
    assert score.b_value(score.present_kinds(0, 0.0, None, True), {score.NEWS, score.SEARCH, score.OFFICIAL}) \
        == pytest.approx(1 / 3)
    assert score.b_value([score.NEWS], set()) is None
    r = score.day_values(A=3, g=0.0, w=None, official=False, ok=set(), prev_H=0.2, v_hist={}, fe_hist={}, f=0, e=0,
                         day=D0, first_day=D0)
    assert r["B"] is None and r["score"] is None and r["v"] is None and r["H"] == 0.2


def _fake_calc(rows, statuses=None, status_of=None):
    fake = types.SimpleNamespace(rows=rows, statuses=statuses or {}, status_of=status_of)
    fake._v_missing = lambda d: days.DayCalc._v_missing(fake, d)
    fake._carry_H = lambda H, last, y: days.DayCalc._carry_H(fake, H, last, y)
    return fake


def test_quiet_issue_H_carry_uses_gap_to_yesterday():
    fake = _fake_calc({"i": {D0: {"H": 1.0, "v": 0.5, "state": "정점"}}})
    prev_H, *_ = days.DayCalc.prev(fake, ["i"], "i", dd(5))
    assert prev_H == pytest.approx(0.7 ** 4)                       # 마지막 줄(0일) → 어제(4일): 4일


def test_quiet_issue_H_carry_keeps_H_on_failed_days():
    """줄을 쓰지 않고 건너뛴 날 가운데 언론과 검색이 모두 실패한 날(v=없음)은 H 를 줄이지 않는다(§5-1).
    Codex 검토 재현: 3/15 에 H=1, 3/16~19 언론·검색 실패, 3/20 복귀 → prev_H 는 1(고치기 전 0.7⁴=0.2401)."""
    D = "2030-03-15"
    failed = {k: {"status": health.FAILED, "last_ok": None} for k in (score.NEWS, score.SEARCH)}
    failed[score.OFFICIAL] = {"status": health.SUCCESS, "last_ok": K.kst(f"{D}T10:00")}
    fake = _fake_calc({"i": {D: {"H": 1.0, "v": None, "state": "정점"}}},
                      status_of=lambda d: failed if "2030-03-16" <= d <= "2030-03-19" else None)
    prev_H, *_ = days.DayCalc.prev(fake, ["i"], "i", "2030-03-20")
    assert prev_H == pytest.approx(1.0)
    # 실패한 날이 하루뿐이면 나머지 사흘만 줄인다
    fake = _fake_calc({"i": {D: {"H": 1.0, "v": None, "state": "정점"}}},
                      status_of=lambda d: failed if d == "2030-03-17" else None)
    prev_H, *_ = days.DayCalc.prev(fake, ["i"], "i", "2030-03-20")
    assert prev_H == pytest.approx(0.7 ** 3)


def _calc_for(day_n):
    iid = "t20300301-001"
    g = {"issue_id": iid, "day": D0, "first_at": f"{D0}T01:00:00+00:00", "seed": "s", "units": [], "copies": [],
         "families": [], "has_official": False, "lang": "ko", "title": "가람시 공장", "ent_fam": {}, "term_fam": {},
         "group_id": "g1"}
    res = {"overrides": overrides.Overrides(), "registry": {iid: _issue(iid, D0)}, "articles": {}, "frozen": [g],
           "groups": [], "late_copies": {}, "copies": {}}
    d = dd(day_n)
    ok = {k: {"status": health.SUCCESS, "last_ok": K.kst(f"{d}T10:00")} for k in score.KINDS}
    asof = K.kst(f"{d}T23:00")
    c = days.DayCalc(res, [], {d: ok}, asof, [d], set())
    c.run()
    return [r for r in c.out_rows if r["issue_id"] == iid]


def test_quiet_issue_stops_after_fourteen_days():
    assert len(_calc_for(14)) == 1 and _calc_for(15) == []


# ── 후속 사건·새 인물(followup)
def _fg(gid, title, terms, fams, units=()):
    return {"group_id": gid, "seed": gid, "title": title, "term_fam": terms, "families": list(fams),
            "first_at": f"{dd(1)}T01:00:00+00:00", "units": list(units), "ent_fam": {}}


HIST_T = chars(51, 2000)


@pytest.mark.parametrize("fams, n", [(("f1", "f2"), 0), (("f1", "f2", "f3"), 1), (("f1", "f2", "f3", "f4"), 1)])
def test_followup_needs_three_families(fams, n):
    hist = [_fg("h", HIST_T, {"화재": ["f1", "f2"]}, ("f1", "f2"))]
    g = _fg("g", chars(20, 3000), {"보상": ["f1", "f2"]}, fams)
    assert len(followup.followups(dd(1), D0, [g], hist)) == n


@pytest.mark.parametrize("shared, n", [(25, 1), (26, 0)])
def test_followup_title_dice_boundary(shared, n):
    """이전 제목과 Dice (k−1)/50: 25자 공유 → 0.48 → 후속, 26자 → 0.50 → 아님."""
    hist = [_fg("h", HIST_T, {"화재": ["f1", "f2"]}, ("f1", "f2"))]
    t = HIST_T[:shared] + chars(51 - shared, 2500)
    g = _fg("g", t, {"보상": ["f1", "f2"]}, ("f1", "f2", "f3"))
    assert len(followup.followups(dd(1), D0, [g], hist)) == n


def test_followup_new_term_needs_two_families():
    hist = [_fg("h", HIST_T, {"화재": ["f1", "f2"]}, ("f1", "f2"))]
    g = _fg("g", chars(20, 3000), {"보상": ["f1"]}, ("f1", "f2", "f3"))
    assert followup.followups(dd(1), D0, [g], hist) == []


def test_followup_groups_joined_by_stage_one_link():
    hist = [_fg("h", HIST_T, {"화재": ["f1", "f2"]}, ("f1", "f2"))]
    u1 = K.unit("가람시 한빛전자 피해 주민 보상 합의", "f3", f"{dd(1)}T09:00")
    u2 = K.unit("가람시 한빛전자 피해 주민 보상 합의", "f5", f"{dd(1)}T10:00")
    arts = {u1["key"]: u1, u2["key"]: u2}
    g1 = _fg("g1", chars(20, 3000), {"보상": ["f3", "f4"]}, ("f3", "f4"), [u1["key"]])
    g2 = _fg("g2", chars(20, 3300), {"합의": ["f5", "f6"]}, ("f5", "f6"), [u2["key"]])
    out = followup.followups(dd(1), D0, [g1, g2], hist, arts)
    assert len(out) == 1 and out[0]["groups"] == ["g1", "g2"]
    assert followup.followups(dd(1), D0, [g1, g2], hist, None) == []


def test_new_entity_needs_two_families():
    g = {"ent_fam": {"새이름": ["f1"], "둘째": ["f1", "f2"]}}
    assert [e["entity"] for e in followup.new_entities(dd(1), D0, [g], [])] == ["둘째"]


# ── 수집 상태 대상·기준 시각(health·source)
def test_targets_respect_enabled_and_ledger(monkeypatch):
    meta = {"n_on": {"kind": "news", "enabled": True}, "n_off": {"kind": "news", "enabled": False},
            "n_nocol": {"kind": "news", "enabled": True}, "n_noscore": {"kind": "news", "enabled": True}}
    monkeypatch.setattr(source, "feeds_meta", lambda: meta)
    deny = {("n_nocol", "collect"), ("n_noscore", "score_use")}
    tg = health.targets(lambda fid, use: (fid, use) not in deny)
    assert tg[score.NEWS] == ["n_on"]


def test_status_ignores_runs_after_the_day():
    """닫힌 날의 상태에 다음 날 실행을 넣지 않는다."""
    tg = {score.NEWS: ["n1"], score.SEARCH: [], score.WIKI: [], score.OFFICIAL: []}
    after = [{"at_dt": K.kst(f"{dd(1)}T01:00"), "error": None, "feeds_failed": []}]
    st = health.day_status(after, tg, D0, K.kst(f"{dd(1)}T13:00"))
    assert st[score.NEWS]["status"] == health.FAILED


def test_half_day_failure_keeps_observed_values():
    """언론 피드가 00:05~10:05 에 성공하고 11시부터 실패한 날: 다음날 13시에 봐도 오래됨(마지막 성공 10:05), 실패 아님."""
    tg = {score.NEWS: ["n1"], score.SEARCH: [], score.WIKI: [], score.OFFICIAL: []}
    runs = [{"at_dt": t, "error": None, "feeds_failed": [] if t <= K.kst(f"{D0}T10:30") else [{"id": "n1"}]}
            for t in K.hourly(f"{D0}T00:00", f"{dd(1)}T13:00")]
    for asof in (K.kst(f"{D0}T22:05"), K.kst(f"{dd(1)}T13:05")):
        st = health.day_status([r for r in runs if r["at_dt"] <= asof], tg, D0, asof)
        assert st[score.NEWS]["status"] == health.STALE
        assert health.missing_labels(st) == ["언론(오래됨, 마지막 성공 10:05)"]
        assert score.NEWS in health.ok_kinds(st)


def test_item_received_exactly_at_asof_is_read(tmp_path):
    it = K.art("가람시 한빛전자 공장 화재", "연합뉴스", f"{D0}T09:00", first_seen=f"{D0}T10:05")
    pdb = K.make_pulse(tmp_path / "p.db", [it], [])
    got, _ = source.load_items(pdb, K.kst(f"{D0}T10:05"), scorable=lambda d: True)
    assert len(got) == 1
    got, _ = source.load_items(pdb, K.kst(f"{D0}T10:04"), scorable=lambda d: True)
    assert got == []


# ── 분야·주소
def test_category_tie_section_only_and_domestic_marker():
    assert category.category_of([{"title": "가람시 국회의원 경찰 조사", "section": ""}])[0] == "정치"
    assert category.category_of([{"title": "가람시 소식", "section": "경제"}])[0] == category.OTHER
    assert category.category_of([{"title": "한국 국회, 미국 대사 초청 간담회", "section": ""}])[0] == "정치"
    assert category.category_of([{"title": "미국 국회 예산안 표결", "section": ""}])[0] == "국제"


def test_canon_url_keeps_blank_query_values():
    assert urls.canon_url("https://ex.test/a?id=7&flag=") != urls.canon_url("https://ex.test/a?id=7")


def test_stage_one_link_is_unchanged_by_this_file():
    """1단계 연결 조건은 정답 60쌍이 지킨다. 여기서는 경계 한 쌍씩만 본다."""
    assert cluster.linked(1, config.G_E1_S, 30) and not cluster.linked(1, config.G_E1_S - 0.001, 30)
    assert cluster.linked(2, config.G_E2_S, 30) and not cluster.linked(2, config.G_E2_S - 0.001, 30)
    assert cluster.linked(0, config.G_E0_S, config.G_E0_T) and not cluster.linked(0, config.G_E0_S, config.G_E0_T + 0.01)
