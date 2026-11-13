"""화제 엔진: 묶기 정답 60쌍(설계 §9-2, 계획 7-4 '묶기 기준'). 제목은 전부 지어낸 것.

60쌍의 기사와 지지 기사를 가상의 2주(2030-03-01~14)에 놓은 수집 DB 하나를 만들고 6시간마다 단계를 돌린 뒤
쌍마다 두 기사가 같은 이슈(별칭 풀어서)인지 본다. 기준: 잘못 합친 것 3쌍 이하, 지나치게 가른 것 9쌍 이하.
기준은 기본 설정(묶기 보정 둘을 켬)으로 맞추고, 설계 그대로(보정을 끈 재생)의 결과도 함께 기록한다.
"""
import pytest

from ozl.signals import config, measure, pipeline, store, text

import test_signals_kit as K

MAX_FALSE_MERGE = 3
MAX_OVER_SPLIT = 9

# 기본 설정(묶기 보정 둘을 켠 것 · 2026-11-14 부터)에서 잰 값.
DEFAULT_FALSE_MERGE = ["p09"]
DEFAULT_OVER_SPLIT = ["f09", "r02", "r03", "r05"]

# 설계 그대로(보정 둘을 끈 재생)에서 2026-11-14 에 잰 값. 어긋난 쌍 목록을 남겨 둔다(정답은 고치지 않는다).
# 보정을 켜면 p01~p15(같은 인물의 다른 사건) 가운데 p09 만 남고, 대신 r03·r05(재상승)가 갈린다.
BASELINE_FALSE_MERGE = ["p01", "p02", "p03", "p04", "p05", "p08", "p09", "p10", "p11", "p12", "p13", "p14", "p15"]
BASELINE_OVER_SPLIT = ["f09", "r02"]

DESIGN_FLAGS = {"LINK_S_WITHOUT_NAMES": False, "ROLE_WORDS_NOT_TERMS": False}


def _replay(tmp_path, name, flags=None):
    """60쌍을 재생한다. flags 를 주면 그 설정으로 돌리고 끝나면 되돌린다(낱말 자료 캐시도 비운다)."""
    flags = flags or {}
    saved = {k: getattr(config, k) for k in flags}
    for k, v in flags.items():
        setattr(config, k, v)
    text.resources.cache_clear()
    try:
        items, meta = K.gold_items()
        runs = K.hourly("2030-03-01T00:00", "2030-03-16T13:00", every_h=6)
        pdb = K.make_pulse(tmp_path / f"p_{name}.db", items, runs)
        con = store.connect(tmp_path / f"e_{name}.db")
        res = None
        for r in runs:
            res = pipeline.step(con, pdb, r)
        io = pipeline.issue_of(res)
        al = store.aliases(con)
    finally:
        for k, v in saved.items():
            setattr(config, k, v)
        text.resources.cache_clear()
    return con, res, meta, io, al


@pytest.fixture(scope="module")
def default(tmp_path_factory):
    return _replay(tmp_path_factory.mktemp("gold"), "default")


@pytest.fixture(scope="module")
def design(tmp_path_factory):
    return _replay(tmp_path_factory.mktemp("gold_design"), "design", DESIGN_FLAGS)


def test_gold_has_sixty_pairs_of_the_planned_mix():
    from collections import Counter
    g = K.load_gold()
    assert len(g) == 60
    assert Counter(p["kind"] for p in g) == {"같은사건": 15, "같은인물다른사건": 15, "전재": 10, "후속": 10,
                                             "동명이인": 5, "재상승": 5}
    assert sum(p["same_issue"] for p in g) == 40
    assert all(p.get("why") for p in g)


def test_all_days_finalized(default):
    con = default[0]
    assert {f"2030-03-{d:02d}" for d in range(1, 14)} <= store.final_days(con)


def test_copy_pairs_share_copy_group_and_count_once(default):
    con, res, meta, io, al = default
    groups = res["frozen"] + res["groups"]
    for cp in meta["copy_pairs"]:
        g = [g for g in groups if cp["a_key"] in g["units"]]
        assert g, cp["id"]
        assert cp["b_key"] in g[0]["copies"], cp["id"]               # 같은 전재 묶음(대표 a, 사본 b)
        assert cp["b_key"] not in g[0]["units"], cp["id"]            # 단위가 아니므로 계열 수(A)에 들지 않는다
        assert cp["b_outlet"] not in g[0]["families"], cp["id"]


def test_pair_criteria(default):
    """기본 설정이 기준(잘못 합침 3쌍 이하, 지나치게 가름 9쌍 이하)을 맞춘다."""
    con, res, meta, io, al = default
    pe = measure.pair_errors(meta["pairs"], io, al)
    assert len(pe["false_merge"]) <= MAX_FALSE_MERGE and len(pe["over_split"]) <= MAX_OVER_SPLIT


def test_pair_errors_match_recorded_default(default):
    """기본 설정의 어긋난 쌍. 바뀌면(좋아지든 나빠지든) 이 목록과 보고를 함께 고친다."""
    con, res, meta, io, al = default
    pe = measure.pair_errors(meta["pairs"], io, al)
    assert pe["false_merge"] == DEFAULT_FALSE_MERGE
    assert pe["over_split"] == DEFAULT_OVER_SPLIT


def test_unit_errors_default(default):
    con, res, meta, io, al = default
    ue = measure.unit_errors(meta["labels"], io, al)
    print(f"\n묶음 단위 오류(기본 설정): 갈림 {ue['split']}, 섞임 {ue['mixed']}")
    assert ue["split"] == 4 and ue["mixed"] == 1


def test_pair_errors_match_recorded_baseline(design):
    """설계 그대로(보정 둘을 끈 재생)의 결과를 기록해 둔다. 기본 설정과 무엇이 달라졌는지 보이게 남긴다."""
    con, res, meta, io, al = design
    pe = measure.pair_errors(meta["pairs"], io, al)
    assert pe["false_merge"] == BASELINE_FALSE_MERGE
    assert pe["over_split"] == BASELINE_OVER_SPLIT
    assert len(pe["false_merge"]) > MAX_FALSE_MERGE        # 설계 그대로는 기준에 못 미친다(켠 까닭)


def test_unit_errors_are_counted(design):
    con, res, meta, io, al = design
    ue = measure.unit_errors(meta["labels"], io, al)
    print(f"\n묶음 단위 오류(설계 그대로): 갈림 {ue['split']}, 섞임 {ue['mixed']}")
    assert ue["split"] == 2 and ue["mixed"] == 13


def test_measure_functions_on_toy_data():
    io = {"a": "t1", "b": "t1", "c": "t2", "d": None, "e": "t3"}
    pairs = [{"id": "x", "a_key": "a", "b_key": "b", "same_issue": False},
             {"id": "y", "a_key": "a", "b_key": "c", "same_issue": True},
             {"id": "z", "a_key": "c", "b_key": "e", "same_issue": True}]
    assert measure.pair_errors(pairs, io, {"t3": "t2"}) == {"false_merge": ["x"], "over_split": ["y"]}
    ue = measure.unit_errors({"a": "E1", "b": "E2", "c": "E1", "d": "E1"}, io)
    assert ue["split"] == 2 and ue["mixed"] == 1
