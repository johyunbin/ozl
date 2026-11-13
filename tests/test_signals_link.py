"""화제 엔진: 이슈 잇기, 번호 발급·재식별, 사람 판단(설계 §4-2 ~ §4-4). 제목은 전부 지어낸 것."""
from datetime import datetime

import pytest

from ozl.signals import config, overrides
from ozl.signals.link import Issue, Linker

import test_signals_kit as K

U, G = K.unit, K.groups


def linker(reg=None, ov=None, mode="step", prev=None, trend_hit=None, asof="2030-03-20T00:00:00+00:00"):
    return Linker(reg if reg is not None else {}, ov or overrides.Overrides(), asof, mode, 1, prev or {}, trend_hit)


def day1():
    return G([U("가람시 한빛전자 공장 화재…주민 대피", "매체A", "2030-03-01T09:00"),
              U("한빛전자 가람시 공장 화재 진화 중", "매체B", "2030-03-01T10:00")], "2030-03-01")


def test_new_issue_number_format_and_order():
    L = linker()
    gs = day1() + G([U("젠타은행 은하뱅크 합병 추진", "매체C", "2030-03-01T11:00"),
                     U("은하뱅크 젠타은행 합병 공식화", "매체D", "2030-03-01T12:00")], "2030-03-01")
    L.run_day("2030-03-01", gs)
    assert [g["issue_id"] for g in gs] == ["t20300301-001", "t20300301-002"]
    assert [h["kind"] for h in L.history] == ["발급", "발급"]


def test_single_family_group_is_not_an_issue_unless_official_or_trend():
    one = G([U("가람시 한빛전자 공장 화재", "매체A", "2030-03-01T09:00")], "2030-03-01")
    L = linker()
    L.run_day("2030-03-01", one)
    assert one[0]["issue_id"] is None
    off = G([U("가람시 한빛전자 공장 화재", "매체A", "2030-03-01T09:00"),
             U("가람시 한빛전자 공장 화재 현장 조사 착수 안내", "가람시청", "2030-03-01T09:30", kind="official")],
            "2030-03-01")
    L = linker()
    L.run_day("2030-03-01", off)
    assert off[0]["issue_id"] == "t20300301-001"
    tr = G([U("가람시 한빛전자 공장 화재", "매체A", "2030-03-01T09:00")], "2030-03-01")
    L = linker(trend_hit=lambda g: True)
    L.run_day("2030-03-01", tr)
    assert tr[0]["issue_id"] == "t20300301-001"


def test_next_day_followup_links_with_two_names_and_event_word():
    L = linker()
    L.run_day("2030-03-01", day1())
    g2 = G([U("한빛전자, 가람시 주민들에게 화재 피해 보상 약속하고 공장 재가동은 미뤄", "매체C", "2030-03-02T10:00"),
            U("가람시, 한빛전자 화재 피해 주민 지원센터 운영", "매체D", "2030-03-02T11:00")], "2030-03-02")
    L.run_day("2030-03-02", g2)
    assert g2[0]["issue_id"] == "t20300301-001"
    assert g2[0]["link"]["Ee"] == 2 and g2[0]["link"]["Et"] >= 1


def test_one_shared_name_does_not_link_across_days():
    L = linker()
    L.run_day("2030-03-01", day1())
    g2 = G([U("한빛전자 켐린폰 출시", "매체C", "2030-03-02T10:00"),
            U("한빛전자 켐린폰 신제품 공개", "매체D", "2030-03-02T11:00")], "2030-03-02")
    L.run_day("2030-03-02", g2)
    assert g2[0]["issue_id"] == "t20300302-001"


def test_dormant_issue_relinks_same_number_with_strict_rule():
    """9-1의 14번: 1일 이슈, 2~8일 기사 없음, 9일 같은 사건(고유명사 둘, 사건 낱말 둘, 제목 0.35 이상) → 같은 번호."""
    L = linker()
    L.run_day("2030-03-01", G([U("가람시 한빛전자 공장 화재로 주민 대피", "매체A", "2030-03-01T09:00"),
                              U("한빛전자 가람시 공장 화재 주민 대피 이틀째", "매체B", "2030-03-01T10:00")], "2030-03-01"))
    g9 = G([U("가람시 한빛전자 공장 화재 주민 대피 원인 결론", "매체C", "2030-03-09T10:00"),
            U("한빛전자 가람시 화재 대피 주민 귀가", "매체D", "2030-03-09T11:00")], "2030-03-09")
    L.run_day("2030-03-09", g9)
    assert g9[0]["issue_id"] == "t20300301-001" and g9[0]["link"]["gap"] == 8
    # 사건 낱말이 하나뿐이면 사흘 넘은 이슈에 붙지 않는다
    L2 = linker()
    L2.run_day("2030-03-01", G([U("가람시 한빛전자 공장 화재로 주민 대피", "매체A", "2030-03-01T09:00"),
                               U("한빛전자 가람시 공장 화재 주민 대피 이틀째", "매체B", "2030-03-01T10:00")], "2030-03-01"))
    g9b = G([U("가람시 한빛전자 새 공장 착공식", "매체C", "2030-03-09T10:00"),
             U("한빛전자 가람시 새 공장 착공", "매체D", "2030-03-09T11:00")], "2030-03-09")
    L2.run_day("2030-03-09", g9b)
    assert g9b[0]["issue_id"] == "t20300309-001"


def test_view_mode_issues_temp_ids_and_keeps_registry():
    reg = {}
    L = linker(reg, mode="view")
    gs = day1()
    L.run_day("2030-03-01", gs)
    assert gs[0]["issue_id"].startswith("임시-") and reg == {} and L.history == []


def test_reidentify_previous_step_number():
    reg = {"t20300301-001": Issue("t20300301-001", "ko", "2030-03-01", "x", 1, "매체A|가람시 한빛전자 공장 화재…주민 대피", "t")}
    gs = day1()
    keys = set(gs[0]["units"])
    L = linker(reg, prev={"t20300301-001": {sorted(keys)[0]}})
    L.run_day("2030-03-01", gs)
    assert gs[0]["issue_id"] == "t20300301-001" and L.minted == []


def test_unclaimed_provisional_numbers_become_alias_or_vanish():
    gs = day1()
    keys = set(gs[0]["units"])
    reg = {"t20300301-001": Issue("t20300301-001", "ko", "2030-03-01", "x", 1, "다른씨앗1", "a"),
           "t20300301-002": Issue("t20300301-002", "ko", "2030-03-01", "x", 1, "다른씨앗2", "b"),
           "t20300301-003": Issue("t20300301-003", "ko", "2030-03-01", "x", 1, "다른씨앗3", "c")}
    prev = {"t20300301-001": set(keys), "t20300301-002": set(keys), "t20300301-003": {"사라진|기사"}}
    L = linker(reg, prev=prev)
    L.run_day("2030-03-01", gs)
    L.finish({"2030-03-01"})
    assert gs[0]["issue_id"] == "t20300301-001"
    assert reg["t20300301-002"].status == "absorbed"
    assert L.aliases == [{"old_id": "t20300301-002", "new_id": "t20300301-001", "at": L.asof_iso, "reason": "잠정 묶음 흡수"}]
    assert reg["t20300301-003"].status == "vanished"
    assert {(h["issue_id"], h["kind"]) for h in L.history} >= {("t20300301-002", "흡수"), ("t20300301-003", "사라짐(잠정)")}


def test_numbers_are_never_reused():
    reg = {"t20300301-001": Issue("t20300301-001", "ko", "2030-03-01", "x", 1, "s", "t", status="vanished")}
    L = linker(reg)
    gs = day1()
    L.run_day("2030-03-01", gs)
    assert gs[0]["issue_id"] == "t20300301-002"


def _ov(tmp_path, body, asof):
    p = tmp_path / "ov.yaml"
    p.write_text(body, encoding="utf-8")
    return overrides.load(p, K.kst(asof))


def test_overrides_respect_asof(tmp_path):
    body = """
- {at: "2030-03-02T10:00:00+09:00", by: 사용자, action: merge, keep: t20300301-001, absorb: [t20300301-002], reason: 같은 화재}
- {at: "2030-03-02T11:00:00+09:00", by: 사용자, action: not_same, issues: [t20300301-001, t20300301-003], reason: 다름}
- {at: "2030-03-02T12:00:00+09:00", by: 사용자, action: end, issue: t20300301-004, reason: 종료}
- {at: "2030-03-02T13:00:00+09:00", by: 사용자, action: reopen, issue: t20300301-004, reason: 재개}
"""
    assert _ov(tmp_path, body, "2030-03-02T09:05").merges == []
    o = _ov(tmp_path, body, "2030-03-02T10:05")
    assert o.resolve("t20300301-002", "2030-03-02") == "t20300301-001"
    assert o.resolve("t20300301-002", "2030-03-01") == "t20300301-002"     # 지난 날짜는 고치지 않는다
    o = _ov(tmp_path, body, "2030-03-02T12:30")
    assert o.blocked_with("t20300301-001") == {"t20300301-003"} and o.ended == {"t20300301-004"}
    assert _ov(tmp_path, body, "2030-03-02T13:30").ended == set()
    assert o.sha != "없음"


def test_merge_override_attaches_to_keep(tmp_path):
    reg = {"t20300301-001": Issue("t20300301-001", "ko", "2030-03-01", "x", 1, "s1", "a"),
           "t20300301-002": Issue("t20300301-002", "ko", "2030-03-01", "x", 1, "s2", "b")}
    ov = _ov(tmp_path, '- {at: "2030-03-02T08:00:00+09:00", action: merge, keep: t20300301-001, absorb: [t20300301-002]}',
             "2030-03-02T09:05")
    L = linker(reg, ov=ov)
    L.add_group("t20300301-002", day1()[0])
    g2 = G([U("한빛전자, 가람시 주민들에게 화재 피해 보상 약속하고 공장 재가동은 미뤄", "매체C", "2030-03-02T10:00"),
            U("가람시, 한빛전자 화재 피해 주민 지원센터 운영", "매체D", "2030-03-02T11:00")], "2030-03-02")
    L.run_day("2030-03-02", g2)
    assert g2[0]["issue_id"] == "t20300301-001"


def test_split_override_mints_and_forces(tmp_path):
    reg = {"t20300301-001": Issue("t20300301-001", "ko", "2030-03-01", "x", 1, "s1", "가람시 화재")}
    g2 = G([U("한빛전자, 가람시 주민들에게 화재 피해 보상 약속하고 공장 재가동은 미뤄", "매체C", "2030-03-02T10:00"),
            U("가람시, 한빛전자 화재 피해 주민 지원센터 운영", "매체D", "2030-03-02T11:00")], "2030-03-02")
    gid = g2[0]["group_id"]
    ov = _ov(tmp_path, f'- {{at: "2030-03-02T08:00:00+09:00", action: split, issue: t20300301-001, groups: [{gid}], reason: 별개}}',
             "2030-03-02T09:05")
    L = linker(reg, ov=ov)
    L.add_group("t20300301-001", day1()[0])
    L.run_day("2030-03-02", g2)
    assert g2[0]["issue_id"] == "t20300302-001"
    assert reg["t20300302-001"].split_of == "t20300301-001"
    assert {(h["issue_id"], h["kind"]) for h in L.history} >= {("t20300302-001", "갈라짐"), ("t20300301-001", "갈라짐")}
    # 다음 단계(같은 판단)에서는 다시 발급하지 않는다
    L2 = linker(reg, ov=ov)
    assert L2.split_ids[ov.splits[0]["sig"]] == "t20300302-001" and L2.minted == []


def test_not_same_blocks_previous_owner(tmp_path):
    reg = {"t20300301-001": Issue("t20300301-001", "ko", "2030-03-01", "x", 1, "s1", "a"),
           "t20300302-001": Issue("t20300302-001", "ko", "2030-03-02", "x", 1, "s2", "b")}
    ov = _ov(tmp_path, '- {at: "2030-03-02T08:00:00+09:00", action: not_same, issues: [t20300301-001, t20300302-001]}',
             "2030-03-02T09:05")
    g2 = G([U("한빛전자, 가람시 주민들에게 화재 피해 보상 약속하고 공장 재가동은 미뤄", "매체C", "2030-03-02T10:00"),
            U("가람시, 한빛전자 화재 피해 주민 지원센터 운영", "매체D", "2030-03-02T11:00")], "2030-03-02")
    L = linker(reg, ov=ov, prev={"t20300302-001": set(g2[0]["units"])})
    L.add_group("t20300301-001", day1()[0])
    L.run_day("2030-03-02", g2)
    assert g2[0]["issue_id"] == "t20300302-001"


@pytest.mark.parametrize("gap_day, ok", [("2030-03-04", True), ("2030-03-05", False)])
def test_gap_three_days_boundary(gap_day, ok):
    """사흘(gap ≤ 3)까지는 가까운 규칙(고유명사 둘 + 사건 낱말 하나), 넘으면 사건 낱말 둘이 필요하다."""
    L = linker()
    L.run_day("2030-03-01", day1())
    gd = G([U("한빛전자, 가람시에 화재 보상 약속", "매체C", gap_day + "T10:00"),
            U("가람시, 한빛전자 화재 지원센터 운영", "매체D", gap_day + "T11:00")], gap_day)
    L.run_day(gap_day, gd)
    assert (gd[0]["issue_id"] == "t20300301-001") is ok
