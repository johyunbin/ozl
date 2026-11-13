"""화제 엔진: Codex 두 모델 검토(2026-11-14)의 재현 입력. 지적마다 고치기 전 코드에서 틀린 결과를 냈던 입력을 그대로 넣는다.
제목·이름은 전부 지어낸 것이다. 검토 원문과 결정: private/out/night_20261114/engine/review/(비공개).
"""
from __future__ import annotations

import copy
import shutil
from datetime import timedelta

import pytest

from ozl.signals import board, cluster, config, days, dedup, engine, followup, health, overrides, score, state, store, text
from ozl.signals.link import Issue, Linker, _gbig

import test_signals_kit as K

D0 = "2030-03-01"


def dd(n: int) -> str:
    return config.day_add(D0, n)


def blk(s: int, n: int) -> str:
    return "".join(chr(0xAC00 + s + i) for i in range(n))


# ── 가-2. 번호 재식별을 잇기보다 먼저, 겹침이 큰 쪽부터 일대일
def _grp(gid, units, at, ents=None, terms=None, fams=("f1", "f2"), title=None):
    return {"group_id": gid, "day": D0, "lang": "ko", "seed": units[0], "units": list(units), "copies": [],
            "families": list(fams), "sources": list(fams), "has_official": False,
            "ent_fam": {e: list(f) for e, f in (ents or {}).items()},
            "term_fam": {t: list(f) for t, f in (terms or {}).items()},
            "title": title or blk(hash(gid) % 5000 * 3, 12), "first_at": f"{D0}T{at}:00+00:00"}


def _linker(reg, prev):
    return Linker(reg, overrides.Overrides(), "2030-03-01T12:00:00+00:00", "step", 2, prev, None)


def test_reidentify_before_linking_keeps_own_number():
    """astra 9: 같은 날 G1·G2(둘 다 2계열, 이름 {한빛, 가람}, 제목 Dice 0). 첫 단계에 '화재'가 G1 에서 1계열뿐이라
    001·002 를 따로 받는다. 다음 단계에 G1 기사가 늘어 '화재'가 2계열이 되면, 고치기 전에는 G2 가 001 에 먼저 붙어
    002 가 흡수됐다(별칭 002 → 001). 이제 G2 는 자기 번호(구성원 그대로)를 먼저 찾는다."""
    names = {"한빛": ["f1", "f2"], "가람": ["f1", "f2"]}
    g1 = _grp("g1", ["a1", "a2"], "01:00", names, {"화재": ["f1"]}, title="화재발생")
    g2 = _grp("g2", ["b1", "b2"], "02:00", names, {"화재": ["f1", "f2"]}, title="주민대피")
    L1 = _linker({}, {})
    L1.run_day(D0, [g1, g2])
    assert (g1["issue_id"], g2["issue_id"]) == ("t20300301-001", "t20300301-002")
    reg = copy.deepcopy(L1.registry)
    g1b = _grp("g1", ["a1", "a2", "a3"], "01:00", names, {"화재": ["f1", "f2"]}, title="화재발생")
    g2b = _grp("g2", ["b1", "b2"], "02:00", names, {"화재": ["f1", "f2"]}, title="주민대피")
    L2 = _linker(reg, {"t20300301-001": {"a1", "a2"}, "t20300301-002": {"b1", "b2"}})
    L2.run_day(D0, [g1b, g2b])
    L2.finish({D0})
    assert (g1b["issue_id"], g2b["issue_id"]) == ("t20300301-001", "t20300301-002")
    assert L2.aliases == [] and reg["t20300301-002"].status == "active"
    assert g2b["link"]["rule"] == "재식별"


def test_bigger_fragment_keeps_number_one_to_one():
    """sol 4: 직전 001 의 구성원 {a1,a2,b1..b4}, 씨앗 b1. 다시 묶으니 이른 A={a1,a2}, 늦은 B={b1..b4}.
    고치기 전에는 시각순으로 A 가 001 을 차지했다. 겹침이 큰 B(씨앗 포함)가 001, A 는 새 번호."""
    reg = {"t20300301-001": Issue("t20300301-001", "ko", D0, "x", 1, "b1", "옛 제목")}
    A = _grp("gA", ["a1", "a2"], "01:00")
    B = _grp("gB", ["b1", "b2", "b3", "b4"], "03:00")
    L = _linker(reg, {"t20300301-001": {"a1", "a2", "b1", "b2", "b3", "b4"}})
    L.run_day(D0, [A, B])
    assert B["issue_id"] == "t20300301-001" and A["issue_id"] == "t20300301-002"


def test_late_article_split_keeps_seed_side_on_old_number():
    """astra 10(1단계 묶기부터): 직전 [z@08, a@09, b@10, c@11, d@12] → 001. 늦게 받은 x@07 이 더해져
    [x, a] 와 [z, b, c, d] 로 갈리면, 고치기 전에는 [x, a](겹침 1)가 001, 씨앗 z 를 가진 쪽이 002 였다."""
    C, X, Z = blk(0, 40), blk(100, 60), blk(200, 60)
    x, z, a = C + X, C + Z, C + X[:30] + Z[:30]
    b, c, d = [C + Z[:40] + blk(s, 20) for s in (300, 400, 500)]

    def u(t, outlet, hh):
        it = K.unit(t, outlet, f"{D0}T{hh}:00")
        it["entities"], it["terms"] = [], []
        return it
    before = [u(z, "매체Z", "08"), u(a, "매체A", "09"), u(b, "매체B", "10"), u(c, "매체C", "11"), u(d, "매체D", "12")]
    gs = cluster.group_day(before, D0)
    assert len(gs) == 1
    L1 = Linker({}, overrides.Overrides(), "x", "step", 1, {}, None)
    L1.run_day(D0, gs)
    assert gs[0]["issue_id"] == "t20300301-001"
    prev = {"t20300301-001": set(gs[0]["units"])}
    after = [u(x, "매체X", "07")] + [copy.deepcopy(v) for v in before]
    for v in after:
        v.pop("_tb", None)
    gs2 = cluster.group_day(after, D0)
    by_seed = {g["seed"]: g for g in gs2}
    assert len(gs2) == 2
    L2 = Linker(copy.deepcopy(L1.registry), overrides.Overrides(), "y", "step", 2, prev, None)
    L2.run_day(D0, gs2)
    seed_side = by_seed[after[1]["key"]]          # z 를 씨앗으로 하는 쪽
    assert seed_side["issue_id"] == "t20300301-001"
    assert by_seed[after[0]["key"]]["issue_id"] == "t20300301-002"


def test_reid_respects_human_merge():
    """사람의 합치기 판단으로 다른 번호에 들어간 번호는 재식별해도 합친 번호로 간다(고치기 전과 같다)."""
    reg = {"t20300301-001": Issue("t20300301-001", "ko", D0, "x", 1, "k1", "가"),
           "t20300301-002": Issue("t20300301-002", "ko", D0, "x", 1, "m1", "나")}
    ov = overrides.Overrides()
    ov.merges.append({"keep": "t20300301-001", "absorb": ["t20300301-002"], "day": D0, "at": "x", "reason": ""})
    g = _grp("gm", ["m1", "m2"], "01:00")
    L = Linker(reg, ov, "x", "step", 2, {"t20300301-002": {"m1", "m2"}}, None)
    L.run_day(D0, [g])
    assert g["issue_id"] == "t20300301-001"


# ── 가-9(ㄱ). 프로필은 그룹이 들어온 차례와 무관하다
def test_profile_same_whatever_order_groups_are_added():
    """astra 11·sol 12: 같은 날 실제 시각 00~20시 그룹 21개를 정방향·역방향으로 넣으면 고치기 전에는 최근 제목 20개와
    씨앗 고유명사가 달랐다."""
    iid = "t20300301-001"
    gs = []
    for h in range(21):
        g = _grp(f"g{h:02d}", [f"k{h}"], f"{h:02d}:00", ents={("알파" if h == 0 else f"이름{h}"): ["f1"]},
                 title=blk(h * 50 * 3, 10))
        gs.append(g)
    nxt = _grp("gn", ["n1"], "23:00", title=gs[0]["title"])
    nxt["day"] = dd(1)
    out = []
    for order in (gs, list(reversed(gs))):
        L = Linker({iid: Issue(iid, "ko", D0, "x", 1, "k0", "t")}, overrides.Overrides(), "x", "step", 1, {}, None)
        for g in order:
            L.add_group(iid, g)
        p = L.profile(iid, dd(1))
        out.append((sorted(map(sorted, p["titles"])), sorted(p["ent"]), Linker.match(nxt, p)))
    assert out[0] == out[1]
    assert "알파" in out[0][1]                         # 씨앗 = 가장 이른 그룹(00시)
    assert _gbig(gs[0]) not in [frozenset(t) for t in out[0][0]]  # 가장 이른 제목이 20개 밖으로 밀린다
    assert out[0][2][0] is False


# ── 가-9(ㄴ). DayCalc 는 날짜를 안에서 정렬한다
def _calc(day_list, sens=None, monkeypatch=None):
    iid = "t20300301-001"
    a1 = K.unit("가람시 한빛전자 공장 화재", "매체A", f"{D0}T09:00")
    a2 = K.unit("한빛전자 가람시 공장 화재 진화", "매체B", f"{dd(1)}T09:00")
    g1 = {"issue_id": iid, "day": D0, "first_at": f"{D0}T00:00:00+00:00", "seed": a1["key"], "units": [a1["key"]],
          "copies": [], "families": ["매체A", "매체C"], "has_official": False, "lang": "ko", "title": a1["title"],
          "ent_fam": {}, "term_fam": {}, "group_id": "g1"}
    g2 = dict(g1, day=dd(1), first_at=f"{dd(1)}T00:00:00+00:00", seed=a2["key"], units=[a2["key"]],
              families=["매체B"], title=a2["title"], group_id="g2")
    res = {"overrides": overrides.Overrides(), "registry": {iid: Issue(iid, "ko", D0, "x", 1, a1["key"], a1["title"])},
           "articles": {a1["key"]: a1, a2["key"]: a2}, "frozen": [], "groups": [g1, g2], "late_copies": {}, "copies": {}}
    ok = {d: {k: {"status": health.SUCCESS, "last_ok": K.kst(f"{d}T10:00")} for k in score.KINDS} for d in (D0, dd(1))}
    c = days.DayCalc(res, [], ok, K.kst(f"{dd(1)}T23:00"), day_list, set())
    c.run()
    return {(r["issue_id"], r["day"]): r for r in c.out_rows}


def test_daycalc_sorts_days():
    """sol 13: 날짜 목록이 [3/2, 3/1] 이면 고치기 전에는 3/2 의 H 가 달랐다(0.142 대 0.242)."""
    a, b = _calc([D0, dd(1)]), _calc([dd(1), D0])
    assert a.keys() == b.keys()
    assert [a[k]["H"] for k in sorted(a)] == [b[k]["H"] for k in sorted(b)]


# ── 가-9(ㄷ). cluster 를 먼저 불러도 dedup 이 멈추지 않는다
def test_cluster_prep_then_copy_relation():
    """astra 12·sol 11: cluster.prep_unit 이 '_tb' 만 붙인 뒤 copy_relation 을 부르면 KeyError: 'norm_summary'."""
    s = "가나다라마바사아자차카타파하" * 4
    a = K.unit("한빛전자 공장 화재 발생 주민 긴급 대피", "매체A", f"{D0}T09:00", summary=s)
    b = K.unit("가람시 한빛전자 화재 현장 조사 결과 발표", "매체B", f"{D0}T09:00", summary=s)
    clean = dedup.copy_relation(copy.deepcopy(a), copy.deepcopy(b))
    cluster.prep_unit(a)
    assert dedup.copy_relation(a, b) == clean


# ── 가-3. 다시 오름은 그날 하루만
def _states(vs, f=None):
    out, prev = [], None
    for i in range(len(vs)):
        hist = {dd(j): vs[j] for j in range(i + 1)}
        st = state.state_of(dd(i), D0, hist, prev, (f or {}).get(i, 0))
        out.append(st)
        prev = st[0]
    return out


def test_rises_again_only_that_day():
    """astra 3·sol 8: v=[0.8, 0.05, 0.02, 0.01, 0.6, 0.5, 0.5]. 고치기 전에는 6·7일째도 규칙 8 로 다시 오름이 남았다."""
    s = _states([0.8, 0.05, 0.02, 0.01, 0.6, 0.5, 0.5])
    assert s[4] == ("다시 오름", 3)
    assert s[5] == (None, None) and s[6] == (None, None)  # 커지는 중·정점·식는 중 어느 것도 아니면 상태 없음
    s = _states([0.8, 0.05, 0.02, 0.01, 0.6, 0.7, 0.8])
    assert s[6] == ("커지는 중", 5)


# ── 가-4. 새 인물·기관은 언론 계열 둘 이상
def test_new_entity_needs_two_news_families():
    """astra 4: 새 이름이 언론 1곳과 공공 원문 1곳에 나왔다. 고치기 전에는 e=1."""
    g = {"term_fam": {}, "ent_fam": {"홍길동": ["공공:기관1", "언론1"]}, "families": ["언론1"]}
    assert followup.new_entities(dd(1), D0, [g], []) == []
    g2 = {"term_fam": {}, "ent_fam": {"홍길동": ["언론2", "언론1"]}, "families": ["언론1", "언론2"]}
    assert followup.new_entities(dd(1), D0, [g, g2], []) == [{"entity": "홍길동", "families": ["언론1", "언론2"]}]


# ── 가-6. 요약 정규화에서 꼬리를 뗀다
def test_summary_tail_marker_is_removed():
    """astra 7: 요약 38자 + '(종합)'. 고치기 전에는 정규화 길이 40 이라 전재('요약')로 묶였다."""
    ta = "".join(chr(0xb000 + i) for i in range(21))
    tb = ta[:9] + "".join(chr(0xb500 + i) for i in range(12))
    summ = "".join(chr(0xac00 + i) for i in range(38)) + "(종합)"
    assert text.norm_summary(summ) == "".join(chr(0xac00 + i) for i in range(38))
    a = K.unit(ta, "매체A", f"{D0}T09:00", summary=summ)
    b = K.unit(tb, "매체B", f"{D0}T09:00", summary=summ)
    a["entities"] = b["entities"] = []
    assert dedup.copy_relation(a, b) is None
    assert text.norm_summary("[가람일보] 본문 앞부분(1보)") == "본문앞부분"


# ── 가-11. 숫자나 고유 표지만 다른 속보
@pytest.mark.parametrize("x, y", [
    ("[속보] 1공장 화재, 근로자 3명 부상", "[속보] 2공장 화재, 근로자 3명 부상"),
    ("[속보] A역 열차 운행 중단…승객 불편", "[속보] B역 열차 운행 중단…승객 불편"),
])
def test_breaking_titles_differing_only_in_marks_are_not_copies(x, y):
    a = K.unit(x, "매체A", f"{D0}T09:00")
    b = K.unit(y, "매체B", f"{D0}T10:00")
    assert text.dice(text.norm_title(x), text.norm_title(y)) >= config.COPY_TITLE_DICE
    assert dedup.copy_relation(a, b) is None
    assert dedup.copy_groups([a, b]) == {}


def test_same_breaking_title_is_still_a_copy():
    t = "[속보] 쿤사시 큰솔화학 공장서 유독가스 누출…주민 대피령"
    a, b = K.unit(t, "매체A", f"{D0}T09:00"), K.unit(t, "매체B", f"{D0}T09:02")
    assert dedup.copy_relation(a, b)[0] == "제목"
    c = K.unit("[속보] 美 한빛전자 3분기 영업이익 2조", "매체A", f"{D0}T09:00")
    d = K.unit("미국 한빛전자 3분기 영업이익 2조", "매체B", f"{D0}T09:05")
    assert dedup.copy_relation(c, d)[0] == "제목"           # 한자 약칭만 다름(4b)


# ── 가-7. board 는 반올림 전 값으로 정렬
def _row(iid, raw, day_n=5):
    return {"issue_id": iid, "score": 20, "score_raw": raw, "state": None, "v": 0.2, "H": 1, "B": 1, "P": 1, "D": 0,
            "A": 1, "g": 0, "w": None, "kinds_present": [], "kinds_ok": [], "missing": [], "category": "기타",
            "sensitivity": {}, "person": False,
            "detail": {"active": True, "row": {"issue_id": iid, "lang": "ko", "title": "t", "day_n": day_n,
                                               "first_day": D0, "status_line": "", "new_thing": "", "outlets_n": 1,
                                               "articles_n": 1, "copies_n": 0, "indirect": None, "links": [],
                                               "_z": {"v": 0.2, "v_prev": 0.2, "vdays": 3, "ended": False}}}}


def test_board_sorts_on_unrounded_score():
    """astra 8·sol 7: 001=20.0000001, 002=20.0000004 → 원값 순서 002, 001(고치기 전에는 001, 002)."""
    meta = {"failed_both": False, "asof": "", "base_day": "", "partial": True, "decided_at": "", "calc_id": 1,
            "mode": "step", "versions": {}, "basis": "", "sources": [], "missing": [], "unmatched": [], "merge_hints": []}
    b = board.build(meta, [_row("t20300301-001", 20.0000001), _row("t20300301-002", 20.0000004)], {})
    assert [c["issue_id"] for c in b["candidates"]] == ["t20300301-002", "t20300301-001"]
    assert b["zones"]["ongoing"]["rows"] == ["t20300301-002", "t20300301-001"]
    assert all("_raw" not in c for c in b["candidates"])


# ── 가-8. 민감 판정은 그날 기사만
def test_sensitivity_uses_that_day_only(monkeypatch):
    seen = []

    def fake(arts):
        seen.append(sorted(a["key"] for a in arts))
        return {"level": "GREEN", "reasons": []}
    monkeypatch.setattr(days, "sensitivity", fake)
    rows = _calc([D0, dd(1)])
    assert rows[("t20300301-001", dd(1))]
    day2 = [s for s in seen if any(k.startswith("매체B") for k in s)]
    assert day2 and all(not any(k.startswith("매체A") for k in s) for s in day2)   # 둘째 날 판정에 첫날 기사가 없다


# ── 가-10. 이름 끝의 '서'
def test_name_ending_in_seo_is_not_cut_into_another_name():
    """sol 15: '미르문서'(가상 회사)와 '미르문'(다른 가상 회사)이 고치기 전에는 둘 다 '미르문'이 되어 E=2 로 묶였다."""
    e1 = text.analyze("미르문서 가람시 공장 화재", "ko")["entities"]
    e2 = text.analyze("미르문 가람시 직원 파업", "ko")["entities"]
    assert "미르문서" in e1 and "미르문" in e2 and set(e1) & set(e2) == {"가람시"}
    assert "가람경찰서" in text.analyze("가람경찰서 수사 착수", "ko")["entities"]
    # 헤드라인의 '에서' 줄임은 그대로 뗀다
    assert "한마음병원" in text.analyze("한마음병원서 화재", "ko")["entities"]
    assert "덴린병원" in text.analyze("쿤린시 덴린병원서 수술 중 환자 사망", "ko")["entities"]


# ── 마-4. 언어 이름 같은 일반 낱말은 새 인물·기관이 아니다
def test_language_and_role_words_are_not_entities():
    for t, w in (("이란 외무부 한국어로 비판 성명", "한국어"), ("한빛전자 임시 대표 선임", "임시")):
        r = text.analyze(t, "ko")
        assert w not in r["entities"]


# ── 마-1. 대표 제목과 링크, 마-2. 어제 값
def test_representative_title_prefers_widest_non_red_group(monkeypatch):
    iid = "t20300301-001"
    seed = {"group_id": "gs", "seed": "s", "families": ["a", "b"], "day": D0, "first_at": "1", "units": [], "copies": [],
            "title": "씨앗 제목"}
    wide = dict(seed, group_id="gw", seed="w", families=["a", "b", "c", "d"], day=dd(1), title="넓은 제목")
    other = dict(seed, group_id="go", seed="o", families=["a", "b", "c"], day=dd(1), title="다른 제목")
    c = days.DayCalc.__new__(days.DayCalc)
    c.reg = {iid: Issue(iid, "ko", D0, "x", 1, "s", "씨앗 제목")}
    level = {"gs": "GREEN", "gw": "GREEN", "go": "GREEN"}
    c._gsens = lambda g: level[g["group_id"]]
    assert c.rep_group(iid, [seed, wide, other])["title"] == "넓은 제목"
    level["gw"] = "RED"
    assert c.rep_group(iid, [seed, wide, other])["title"] == "씨앗 제목"
    level["gs"] = "RED"
    assert c.rep_group(iid, [seed, wide, other])["title"] == "다른 제목"


def test_candidate_row_carries_yesterday_values():
    rows = _calc([D0, dd(1)])
    cand = rows[("t20300301-001", dd(1))]["detail"]["row"]
    assert cand["prev_day"]["day"] == D0 and cand["prev_day"]["outlets_n"] == 2
    assert cand["title"] == "가람시 한빛전자 공장 화재"                 # 계열이 가장 많은 그룹(첫날, 2곳)
    assert cand["links"][0]["outlet"] == "매체A"


# ── 마-6. engine.db 정리(prune)
def test_prune_keeps_past_boards_and_next_steps_identical(tmp_path):
    """정리 뒤에도 지난 시각의 board(rebuild_board), 이어지는 단계의 계산, 최신 explain 이 같다."""
    D1 = "2030-03-01"
    its = [K.art("가람시 한빛전자 공장 화재…주민 대피", "연합뉴스", f"{D1}T09:00"),
           K.art("한빛전자 가람시 공장 화재 진화 중", "SBS", f"{D1}T10:00"),
           K.art("한빛전자, 가람시 화재 피해 보상 약속", "매일경제", "2030-03-02T09:00"),
           K.art("가람시, 한빛전자 화재 피해 주민 지원", "한국경제", "2030-03-02T10:00"),
           K.art("한빛전자 가람시 공장 재가동 연기", "서울경제", "2030-03-03T09:00"),
           K.art("가람시 한빛전자 공장 재가동 연기 결정", "동아일보", "2030-03-03T10:00")]
    runs = K.hourly(f"{D1}T08:00", "2030-03-04T14:00", every_h=3)
    pdb = K.make_pulse(tmp_path / "p.db", its, runs)
    a_db, b_db = tmp_path / "a.db", tmp_path / "b.db"
    con = store.connect(a_db)
    for t in runs[:-4]:
        engine.step(con, pdb, t, "step")
    con.close()
    shutil.copy(a_db, b_db)
    cb = store.connect(b_db)
    n = store.prune(cb)
    assert n["groups"] > 0 and n["issue_days"] > 0
    ca = store.connect(a_db)
    for t in runs[:-4]:
        x, y = engine.rebuild_board(ca, t), engine.rebuild_board(cb, t)
        assert {k: v for k, v in x.items() if k != "decided_at"} == {k: v for k, v in y.items() if k != "decided_at"}
    for t in runs[-4:]:
        x = engine.step(ca, pdb, t, "step")["board"]
        y = engine.step(cb, pdb, t, "step")["board"]
        assert {k: v for k, v in x.items() if k != "decided_at"} == {k: v for k, v in y.items() if k != "decided_at"}
    for q in ("SELECT issue_id, first_day, seed_key, status FROM issues ORDER BY 1", "SELECT * FROM issue_aliases ORDER BY 1",
              "SELECT * FROM issue_days WHERE final=1 ORDER BY issue_id, day"):
        assert [tuple(r) for r in ca.execute(q)] == [tuple(r) for r in cb.execute(q)]
    from ozl.signals import explain
    ea, eb = explain.explain(ca, "t20300301-001"), explain.explain(cb, "t20300301-001")
    assert ea == eb


def test_extra_mark_on_one_side_is_still_a_copy():
    """한쪽에만 표지가 더 있는 것(앞에 매체·나라 이름을 붙인 전재)은 바꿔 끼운 표지가 아니라 전재로 둔다."""
    a = K.unit('[속보] "한빛전자 이사회, 대표 해임 준비…이르면 오늘 회의"', "매체A", f"{D0}T09:00")
    b = K.unit('[속보] XYZ "한빛전자 이사회, 대표 해임 준비…이르면 오늘 회의"', "매체B", f"{D0}T09:05")
    assert dedup.copy_relation(a, b)[0] == "제목"
