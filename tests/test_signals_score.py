"""화제 엔진 B: 점수 산식·출처 상태·상태 판정·후속 사건·두 구역의 경계 사례(설계 §9-1 가운데 순수 함수로 보는 것).

기대값은 손으로 계산했다(위키 꺼짐 → 정상일 v = (0.6 L(A) + 0.25 g) / 0.85, B 분모 3).
L(1)=ln2/ln31=0.201849 · L(2)=0.319923 · L(3)=0.403698 · L(4)=ln5/ln31=0.468679 · L(5)=0.521772 · L(30)=L(100)=1.

계획 문서와 설계 문서가 갈린 곳(2026-11-14 Codex 검토 반영 뒤의 결정):
- P: 설계 §5-1 의 최근 7일 창 [d−6, d]. 계획 5-2 표의 식은 기간을 말하지 않는다(누적으로 세면 17일째 조용한 이슈가 16점).
- 다시 오름 (나): 계획 "이틀 넘게 최댓값의 0.3 미만이다가 … 새 후속 사건이 생김" — 사흘 낮았던 조건을 후속 사건에도 건다
  (설계 §6-1 도 이 문장으로 고쳤다).
"""
from datetime import timedelta

import pytest

from ozl.signals import board, category, config, followup, health, score, state

NEWS, SEARCH, OFF = score.NEWS, score.SEARCH, score.OFFICIAL
ALL3 = {NEWS, SEARCH, OFF}
D = "2030-03-10"


def day(n: int) -> str:
    return config.day_add(D, n)


def vals(**kw):
    base = dict(A=0, g=0.0, w=None, official=False, ok=ALL3, prev_H=0.0, v_hist={}, fe_hist={}, f=0, e=0,
                day=D, first_day=D)
    base.update(kw)
    return score.day_values(**base)


def approx(x):
    return pytest.approx(x, abs=1e-6)


# ── 산식 조각
def test_L_values():
    assert [round(score.L(a), 6) for a in (0, 1, 2, 3, 4, 5, 30, 100)] == \
        [0.0, 0.201849, 0.319923, 0.403698, 0.468679, 0.521772, 1.0, 1.0]


@pytest.mark.parametrize("raw, g", [("499+", 0.40), ("500+", 0.55), ("999", 0.55), ("1,000+", 0.70), ("4999", 0.70),
                                    ("5000+", 0.85), ("19999", 0.85), ("20000+", 1.0), ("200000+", 1.0),
                                    ("2만+", 1.0), ("5K+", 0.85), ("", 0.40), (None, 0.40), ("많음", 0.40)])
def test_grade_table_bounds(raw, g):
    """§5-2 등급 표: 499→0.40, 500→0.55, 4999→0.70, 5000→0.85, 19999→0.85, 20000→1.0, 못 읽음→0.40."""
    assert score.grade(raw) == g


def test_case9_half_up_rounding():
    """9번: H=0.4375(화면용 0.175), B=0.5, P=1, D=0.5 → 100×(0.07+0.125+0.15+0.10)=44.5 → 45(파이썬 round 는 44)."""
    s = score.s_raw(0.4375, 0.5, 1.0, 0.5)
    assert s == approx(44.5)
    assert score.display(s) == 45 and round(44.5) == 44
    assert score.display(None) is None


# ── §9-1 경계 사례(산식)
def test_case1b_zero_day_of_existing_issue():
    """1b: H(d−1)=0.5, 최근 7일 v≥0.1 인 날 3일, 오늘 A=0, g=0.
    v=0, H=0.7×0.5=0.35, B=0/3=0, P=3/7, D=0 → 100×(0.4×0.14 + 0.15×0.428571) = 12.028571 → 12."""
    r = vals(prev_H=0.5, first_day=day(-6), v_hist={day(-6): 0.05, day(-5): 0.3, day(-3): 0.15, day(-1): 0.2})
    assert (r["v"], r["H"], r["B"], r["D"]) == (0.0, approx(0.35), 0.0, 0.0)
    assert r["P"] == approx(3 / 7) and r["score_raw"] == approx(12.028571) and r["score"] == 12


def test_case2_single_candidate_values():
    """2: 첫날 A=5, 검색 500+(0.55), 공공 없음.
    v=(0.6×0.521772 + 0.25×0.55)/0.85 = (0.313063+0.1375)/0.85 = 0.530075, H=v, B=2/3, P=1/7, D=0
    → 100×(0.4×0.212030 + 0.25×0.666667 + 0.15×0.142857) = 27.290717 → 27."""
    r = vals(A=5, g=0.55)
    assert r["v"] == approx(0.530075) and r["H"] == approx(0.530075)
    assert r["B"] == approx(2 / 3) and r["P"] == approx(1 / 7) and r["D"] == 0
    assert r["score_raw"] == approx(27.290717) and r["score"] == 27
    assert r["present"] == [NEWS, SEARCH]


def test_case3_search_failed():
    """3: 검색 실패 → ok={언론, 공공}. v=0.6×0.521772/0.6=0.521772, B=1/2,
    100×(0.4×0.208709 + 0.125 + 0.021429) = 22.991214 → 23."""
    r = vals(A=5, g=0.55, ok={NEWS, OFF})
    assert r["v"] == approx(0.521772) and r["B"] == 0.5
    assert r["score_raw"] == approx(22.991214) and r["score"] == 23


def test_case3b_search_ok_no_keyword():
    """3b: A=5, g=0, 셋 성공. v=0.6×0.521772/0.85=0.368310, B=1/3,
    100×(0.4×0.147324 + 0.083333 + 0.021429) = 16.369148 → 16."""
    r = vals(A=5)
    assert r["v"] == approx(0.368310) and r["B"] == approx(1 / 3)
    assert r["score_raw"] == approx(16.369148) and r["score"] == 16


def test_case3c_news_failed():
    """3c: 언론 실패, g=0.70 → v=0.25×0.7/0.25=0.70, B=1/2(검색, 공공 중 검색),
    100×(0.4×0.28 + 0.125 + 0.021429) = 25.842857 → 26."""
    r = vals(A=0, g=0.70, ok={SEARCH, OFF})
    assert r["v"] == approx(0.70) and r["B"] == 0.5
    assert r["score_raw"] == approx(25.842857) and r["score"] == 26


def test_case3d_news_and_search_failed():
    """3d: 언론·검색 모두 실패 → v=없음, 점수=없음, H=H(d−1). 0 으로 쓰면 실패."""
    r = vals(A=3, g=0.7, ok={OFF}, prev_H=0.8, first_day=day(-2), v_hist={day(-2): 0.5, day(-1): 0.4})
    assert r["v"] is None and r["H"] == approx(0.8)
    assert r["score_raw"] is None and r["score"] is None


def test_case10_official_failure_raises_score():
    """10: 3b 와 같고 공공 원문만 실패 → B=1/2, 100×(0.058930+0.125+0.021429) = 20.535815 → 21 (3b 는 16)."""
    r = vals(A=5, ok={NEWS, SEARCH})
    assert r["v"] == approx(0.368310) and r["B"] == 0.5
    assert r["score_raw"] == approx(20.535815) and r["score"] == 21


@pytest.mark.parametrize("A", [30, 100])
def test_case11_outlet_cap(A):
    """11: A=30, A=100 → L=1, v=0.6/0.85=0.705882, 100×(0.4×0.282353 + 0.083333 + 0.021429)=21.770 → 22."""
    r = vals(A=A)
    assert r["v"] == approx(0.705882) and r["score"] == 22


def _run_series(As, window=None):
    """날마다 A 만 주고(g=0, 셋 성공) 이어서 계산한다."""
    first = day(0)
    rows, prev_H, vh = [], 0.0, {}
    for i, a in enumerate(As):
        d = day(i)
        r = vals(A=a, day=d, first_day=first, prev_H=prev_H, v_hist=dict(vh), p_window=window)
        rows.append(r)
        prev_H, vh[d] = r["H"], r["v"]
    return rows


def test_case12_P_counts_only_the_last_seven_days(monkeypatch):
    """12(설계 §9-1): 1~7일 매일 A=5(v=0.368310), 8~17일 0.
    7일째 H = 0.368310×(1−0.7⁷)/0.3 = 1.126593, P=7/7 → 100×(0.4×0.450637+0.083333+0.15)=41.36 → 41.
    17일째 H = 1.126593×0.7¹⁰ = 0.031823. P 는 최근 7일 [11일, 17일] 에 v≥0.1 인 날이 없어 0
    → 100×(0.4×0.012729) = 0.509 → 1. 8일째는 [2일, 8일] 의 6일 → P=6/7.
    (첫날부터 누적해 세면 17일째 P=1 → 15.509176 → 16 — 오래전 활동이 15점을 계속 받는다. Codex 검토 1번)"""
    assert config.P_WINDOW_DAYS == 7
    rows = _run_series([5] * 7 + [0] * 10)
    assert rows[6]["H"] == approx(1.126593) and rows[6]["P"] == 1.0 and rows[6]["score"] == 41
    assert rows[7]["P"] == approx(6 / 7)
    assert rows[13]["P"] == 0.0 and rows[12]["P"] == approx(1 / 7)        # 7일째 활동은 13일째까지 창에 든다
    assert rows[16]["H"] == approx(0.031823) and rows[16]["P"] == 0.0
    assert rows[16]["score_raw"] == pytest.approx(0.509176, abs=2e-6) and rows[16]["score"] == 1
    monkeypatch.setattr(config, "P_WINDOW_DAYS", None)                     # None = 첫날부터(설정으로만 남김)
    cum = _run_series([5] * 7 + [0] * 10)
    assert cum[16]["P"] == 1.0 and cum[16]["score"] == 16


def test_case7_spread_counts_one_followup():
    """7: 둘째 날 A=4, f=1 → D=0.2. v(1)=0.368310(A=5), v(2)=0.6×0.468679/0.85=0.330832,
    H=0.7×0.368310+0.330832=0.588649, P=2/7 → 100×(0.4×0.235460+0.083333+0.042857+0.04)=26.037435 → 26."""
    r = vals(A=4, f=1, day=day(1), first_day=day(0), prev_H=0.368310, v_hist={day(0): 0.368310})
    assert r["v"] == approx(0.330832) and r["H"] == approx(0.588649) and r["D"] == approx(0.2)
    assert r["score_raw"] == pytest.approx(26.037435, abs=2e-6) and r["score"] == 26   # 손 계산은 중간값을 여섯째 자리에서 끊음
    two = vals(A=4, f=2, day=day(1), first_day=day(0), prev_H=0.368310, v_hist={day(0): 0.368310})
    assert two["score"] == 30          # f 를 2로 세면 30


def test_D_window_counts_only_recent_first_appearances():
    """D 는 [d−6, d] 에 처음 생긴 f, e 만 더한다(설계 §5-4 · 계획은 기간을 말하지 않음)."""
    r = vals(day=day(10), first_day=day(0), fe_hist={day(2): (3, 4), day(5): (1, 0), day(9): (0, 2)}, e=1)
    assert r["D"] == approx(min(1, (2 * 1 + 0 + 2 + 1) / 10))      # day(2) 는 창 밖


def test_case8_stale_and_failed_values():
    """8 (가) 검색 오래됨 → 관측값 그대로: A=2, g=0.70 → v=(0.6×0.319923+0.25×0.7)/0.85=0.431711,
    100×(0.4×0.172684 + 0.166667 + 0.021429) = 25.716892 → 26. (나) 실패 → v=L(2)=0.319923."""
    a = vals(A=2, g=0.70, ok=ALL3)
    assert a["v"] == approx(0.431711) and a["score_raw"] == approx(25.716892) and a["score"] == 26
    b = vals(A=2, g=0.70, ok={NEWS, OFF})
    assert b["v"] == approx(0.319923)


# ── 출처 상태(§5-3)
def _runs(*hours_before, end=None, failed=()):
    end = end or config.parse_ts("2030-03-10T15:00:00+00:00")
    return [{"at_dt": end - timedelta(hours=h), "error": None, "feeds_failed": list(failed)} for h in hours_before]


TARGETS = {NEWS: ["n1", "n2", "n3"], SEARCH: ["s_kr", "s_us"], OFF: ["o1"], score.WIKI: []}


@pytest.mark.parametrize("minutes, want", [(359, "성공"), (360, "성공"), (361, "오래됨"), (12 * 60, "오래됨"),
                                           (12 * 60 + 1, "오래됨")])
def test_status_boundaries(minutes, want):
    """9-5: 마지막 성공이 5시간 59분·정확히 6시간 전 성공, 6시간 1분 전 오래됨.
    12시간 넘게 멈춰도 그날 안에 성공이 있으면 오래됨(관측값을 쓴다 · 2026-11-14 검토 반영). 실패는 그날 성공이 없을 때만."""
    asof = config.parse_ts("2030-03-10T15:00:00+00:00")          # 3-11 00:00 KST = 3-10 의 끝
    runs = [{"at_dt": asof - timedelta(minutes=minutes), "error": None, "feeds_failed": []},
            {"at_dt": asof - timedelta(minutes=minutes - 1), "error": None,
             "feeds_failed": [{"id": "s_kr", "error": "HTTP 503"}, {"id": "s_us", "error": "HTTP 503"}]}]
    st = health.day_status(runs, TARGETS, config.kst_day(asof - timedelta(minutes=minutes)), asof)
    assert st[SEARCH]["status"] == want
    assert st[score.WIKI]["status"] == "꺼짐"


def test_status_half_of_feeds_is_success_and_missing_labels():
    asof = config.parse_ts("2030-03-10T06:00:00+00:00")          # 15:00 KST
    one = [{"at_dt": asof, "error": None, "feeds_failed": [{"id": "s_kr", "error": "x"}]}]
    assert health.day_status(one, TARGETS, "2030-03-10", asof)[SEARCH]["status"] == "성공"     # 2개 가운데 1개 = 절반
    both = [{"at_dt": asof - timedelta(hours=8), "error": None, "feeds_failed": []},
            {"at_dt": asof, "error": None, "feeds_failed": [{"id": "s_kr"}, {"id": "s_us"}]}]
    st = health.day_status(both, TARGETS, "2030-03-10", asof)
    assert st[SEARCH]["status"] == "오래됨"
    assert health.missing_labels(st) == ["검색(오래됨, 마지막 성공 07:00)"]
    err = [{"at_dt": asof, "error": "뉴스·기관 항목 0개", "feeds_failed": []}]
    st2 = health.day_status(err, TARGETS, "2030-03-10", asof)
    assert st2[NEWS]["status"] == "실패" and "언론(실패)" in health.missing_labels(st2)


def test_status_no_run_today_is_failure():
    asof = config.parse_ts("2030-03-10T16:00:00+00:00")          # 3-11 01:00 KST
    runs = [{"at_dt": config.parse_ts("2030-03-10T14:30:00+00:00"), "error": None, "feeds_failed": []}]   # 3-10 23:30
    assert health.day_status(runs, TARGETS, "2030-03-11", asof)[NEWS]["status"] == "실패"
    assert health.day_status(runs, TARGETS, "2030-03-10", asof)[NEWS]["status"] == "성공"


def test_feed_table_last_ok_and_failure_streak():
    t0 = config.parse_ts("2030-03-10T00:00:00+00:00")
    runs = [{"at_dt": t0 + timedelta(hours=h), "error": None,
             "feeds_failed": [{"id": "n2", "error": "HTTP 503"}] if h >= 1 else []} for h in range(4)]
    tab = {r["feed"]: r for r in health.feed_table(runs, TARGETS)}
    assert tab["n1"]["last_ok"] == t0 + timedelta(hours=3) and tab["n1"]["fail_since"] is None
    assert tab["n2"]["last_ok"] == t0 and tab["n2"]["fail_since"] == t0 + timedelta(hours=1)
    assert tab["n2"]["error"] == "HTTP 503"


# ── 상태(§6-1)
def _states(vs, f=None, partial_last=False):
    out, prev = [], None
    for i, v in enumerate(vs):
        d = day(i)
        hist = {day(j): vs[j] for j in range(i + 1)}
        st, rule = state.state_of(d, day(0), hist, prev, (f or {}).get(i, 0), partial=partial_last and i == len(vs) - 1)
        out.append((st, rule))
        prev = st
    return out


def test_case13_rises_again():
    """13: v [0.80, 0.05, 0.02, 0.01, 0.60] → 5일째 다시 오름(사흘 < 0.3×0.8=0.24, 0.60 ≥ 0.5×0.8=0.40)."""
    s = _states([0.80, 0.05, 0.02, 0.01, 0.60])
    assert s[0] == ("새로 뜸", 4) and s[4] == ("다시 오름", 3)
    assert s[3][0] == "식는 중"              # 0.01 < 0.02 < 0.05, 0.01 < 0.56


def test_state_priority_order():
    # 다시 오름이 커지는 중보다 먼저: [0.8, 0.05, 0.1, 0.2, 0.5] 는 둘 다 맞지만 다시 오름
    assert _states([0.8, 0.05, 0.1, 0.2, 0.5])[4] == ("다시 오름", 3)
    # 휴면이 다시 오름보다 먼저: 최댓값 0.15, 사흘 0.045 미만, 오늘 0.08(≥0.075), 8일째이고 최근 7일 모두 0.1 미만 → 휴면
    assert _states([0.15, 0.09, 0.05, 0.03, 0.02, 0.01, 0.02, 0.08])[7] == ("휴면", 2)
    # 정점: 0.9×최댓값 이상이고 더 오르지 않음
    assert _states([0.3, 0.5, 0.48])[2] == ("정점", 6)
    # 커지는 중
    assert _states([0.2, 0.3, 0.4])[2] == ("커지는 중", 5)
    # 첫날 v < 0.3 이면 상태 칸이 빈다
    assert _states([0.2])[0] == (None, None)


def test_rises_again_by_followup_needs_three_low_days_per_plan():
    """다시 오름 (나): 계획 문장 그대로 '이틀 넘게 최댓값의 0.3 미만이다가 새 후속 사건이 생김'."""
    s = _states([0.8, 0.1, 0.1, 0.1, 0.2], f={4: 1})
    assert s[4] == ("다시 오름", 3)
    s2 = _states([0.8, 0.5, 0.1, 0.1, 0.2], f={4: 1})          # 낮은 날이 이틀뿐
    assert s2[4][0] != "다시 오름"


def test_case18_partial_today_keeps_yesterday_state():
    """18: 어제 v=0.5(1일째, 새로 뜸), 오늘 09시까지 v=0.1 → v(D) < v(D−1) 이라 상태는 어제 것."""
    assert _states([0.5, 0.1], partial_last=True)[1] == ("새로 뜸", 8)
    # 진행 중인 날로는 식는 중·휴면을 새로 판정하지 않는다
    assert _states([0.5, 0.6, 0.55, 0.3], partial_last=True)[3][0] == "정점"


def test_state_none_value_keeps_previous():
    assert state.state_of(day(1), day(0), {day(0): 0.5, day(1): None}, "새로 뜸", 0) == ("새로 뜸", 8)


def test_ended_override_wins():
    assert state.state_of(day(1), day(0), {day(0): 0.5, day(1): 0.9}, "새로 뜸", 0, ended=True) == ("종료", 1)


# ── 후속 사건과 새 인물·기관(§5-4)
def G(title, fams, terms, ents=None, d=day(1)):
    tf = {t: sorted(fams) for t in terms}
    ef = {e: sorted(fams) for e in (ents or [])}
    return {"group_id": "g" + title, "day": d, "seed": title, "units": [title], "copies": [], "title": title,
            "families": sorted(fams), "sources": sorted(fams), "term_fam": tf, "ent_fam": ef,
            "first_at": d + "T00:00:00+00:00"}


def test_case7_split_subevent_counts_once():
    """7: 둘째 날 새 하위 사건이 G2a{O1,O2,O3}, G2b{O2,O3,O4} 로 갈림, new_terms 에 같은 낱말 하나 → 단위 하나, 계열 4 → f=1."""
    hist = [G("가람시 한빛전자 신공장 유치 확정", {"O1", "O2", "O3", "O4", "O5"}, ["공장", "유치"], d=day(0))]
    g2a = G("한빛전자 노조 파업 돌입 첫날", {"O1", "O2", "O3"}, ["노조", "파업"])
    g2b = G("파업 이틀째 가람시 협상 난항", {"O2", "O3", "O4"}, ["파업", "협상"])
    units = followup.followups(day(1), day(0), [g2a, g2b], hist)
    assert len(units) == 1 and units[0]["families"] == ["O1", "O2", "O3", "O4"]
    assert followup.followups(day(0), day(0), hist, []) == []              # 첫날은 세지 않는다


def test_followup_needs_three_families_and_new_title():
    hist = [G("가람시 한빛전자 신공장 유치 확정", {"O1", "O2"}, ["공장", "유치"], d=day(0))]
    small = G("한빛전자 노조 파업 돌입", {"O1", "O2"}, ["노조", "파업"])
    assert followup.followups(day(1), day(0), [small], hist) == []          # 계열 2곳
    same = G("가람시 한빛전자 신공장 유치 확정 발표", {"O1", "O2", "O3"}, ["공장", "유치", "발표식"])
    assert followup.followups(day(1), day(0), [same], hist) == []           # 어제 제목을 다시 쓴 것(Dice ≥ 0.5)


def test_case15_new_entities_need_two_families():
    """15: 둘째 날 계열 1곳 기사에 새 이름 10개, 계열 2곳 기사에 새 이름 1개 → e=1, D=0.1."""
    hist = [G("가람시 한빛전자 신공장", {"O1", "O2"}, ["공장"], ["가람시", "한빛전자"], d=day(0))]
    one = G("주변 이름 열 개", {"O3"}, [], [f"가상인물{i}" for i in range(10)])
    two = G("누리은행 참여", {"O1", "O2"}, ["참여"], ["누리은행", "한빛전자"])
    ents = followup.new_entities(day(1), day(0), [one, two], hist)
    assert [e["entity"] for e in ents] == ["누리은행"]
    assert vals(e=len(ents), day=day(1), first_day=day(0))["D"] == approx(0.1)


# ── 분야(§6-3)
def test_category_scores_and_tie_order():
    arts = [{"title": "가람시 야구 결승 우승", "section": "종합"}, {"title": "한빛전자 주가 급등", "section": "증시"}]
    cat, pts = category.category_of(arts)
    assert pts["스포츠"] == 2 and pts["경제"] == 3 and cat == "경제"
    assert category.category_of([{"title": "평범한 소식", "section": "종합"}])[0] == "기타"
    # 정치 낱말 + 나라 이름(한국 제외) + 국내 표지 없음 → 국제로 센다
    assert category.category_of([{"title": "일본 국회 해산", "section": "종합"}])[0] == "국제"
    assert category.category_of([{"title": "국회 예산안 처리", "section": "종합"}])[0] == "정치"


# ── 두 구역(§6-2)
def cand(iid, cat="경제", v=0.5, v_prev=None, day_n=1, s=10.0, indirect=None, st="새로 뜸", vdays=1, lang="ko",
         level="GREEN", ended=False):
    return {"issue_id": iid, "lang": lang, "state": st, "day_n": day_n, "score_raw": s, "category": cat,
            "indirect": {"n": indirect, "label": ""} if indirect else None, "sensitivity": {"level": level, "reason": ""},
            "_z": {"v": v, "v_prev": v_prev, "vdays": vdays, "ended": ended}}


def test_case16_category_cap():
    """16: 새로 뜬 것 후보 v 순 스포츠 4, 경제 1 → 스포츠, 스포츠, 경제(3줄), capped 스포츠 2(4줄 구역의 절반=2)."""
    cs = [cand(f"t-{i}", "스포츠", v=0.9 - 0.1 * i) for i in range(4)] + [cand("t-9", "경제", v=0.4)]
    z = board.zones(cs, failed_both=False)
    assert z["new"]["rows"] == ["t-0", "t-1", "t-9"]
    assert z["new"]["capped"] == [{"category": "스포츠", "skipped": 2}]


def test_case17_indirect_breaks_ties():
    z = board.zones([cand("t-1", v=0.4, s=30), cand("t-2", v=0.4, s=10, indirect=2)], failed_both=False)
    assert z["new"]["rows"] == ["t-2", "t-1"]


def test_zone_conditions():
    cs = [cand("new-low", v=0.05),                                         # v 0.1 미만
          cand("new-yday", day_n=2, v=0.02, v_prev=0.5),                   # 2일째는 max(오늘, 어제)
          cand("red", v=0.9, level="RED"), cand("ended", v=0.9, ended=True), cand("en", v=0.9, lang="en"),
          cand("on-1", day_n=3, v=0.2, vdays=2, s=40, st="정점"),
          cand("on-cold", day_n=5, v=0.2, vdays=1, s=50),                  # 사흘째 이상인데 v≥0.1 인 날이 하루뿐
          cand("on-dorm", day_n=9, v=0.0, v_prev=0.2, vdays=3, s=60, st="휴면"),
          cand("on-2", day_n=4, v=0.05, v_prev=0.15, vdays=3, s=20, st="식는 중")]
    z = board.zones(cs, failed_both=False)
    assert z["new"]["rows"] == ["new-yday"]
    assert z["ongoing"]["rows"] == ["on-1", "on-2"]


def test_case1_and_3d_empty_reasons():
    z = board.zones([], failed_both=False)
    assert z["new"]["empty_reason"] == z["ongoing"]["empty_reason"] == "오늘 새로 잡힌 이슈가 없다"
    z2 = board.zones([cand("x", v=0.05)], failed_both=False)
    assert z2["new"]["empty_reason"] == "조건(v 0.1 이상)을 넘는 이슈가 없다"
    z3 = board.zones([cand("x", v=None)], failed_both=True)
    assert z3["new"]["empty_reason"] == z3["ongoing"]["empty_reason"] == "수집 실패로 오늘 값을 내지 못했다"
