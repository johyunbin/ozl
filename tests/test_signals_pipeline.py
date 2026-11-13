"""화제 엔진: 묶기 단계 전체(수집 DB 읽기 → 저장), engine.db 구조, 기준 시각, 재계산(설계 §7, §8-2, §9-3, §9-4)."""
import hashlib
import sqlite3

import pytest

from ozl.signals import pipeline, source, store

import test_signals_kit as K

A = K.art


def _items():
    return [
        A("가람시 한빛전자 공장 화재…주민 대피", "연합뉴스", "2030-03-01T09:00"),
        A("한빛전자 가람시 공장 화재 진화 중", "한국경제", "2030-03-01T10:00"),
        A("[속보] 가람시 한빛전자 공장 화재…주민 대피", "SBS", "2030-03-01T09:05"),          # 전재
        A("젠타은행 은하뱅크 합병 추진", "매일경제", "2030-03-01T11:00"),
        A("은하뱅크 젠타은행 합병 공식화", "서울경제", "2030-03-01T12:00"),
        A("한빛전자, 가람시 주민들에게 화재 피해 보상 약속하고 공장 재가동은 미뤄", "조선일보", "2030-03-02T10:00"),
        A("가람시, 한빛전자 화재 피해 주민 지원센터 운영", "동아일보", "2030-03-02T11:00"),
    ]


def _run(tmp_path, items, runs, name="e.db", ov=None):
    pdb = K.make_pulse(tmp_path / ("p_" + name), items, runs)
    con = store.connect(tmp_path / name)
    res = None
    for r in runs:
        res = pipeline.step(con, pdb, r, overrides_path=ov)
    return con, res, pdb


def _dump(con):
    q = {"issues": "SELECT issue_id, lang, first_day, minted_at, seed_key, title, status, split_of FROM issues ORDER BY 1",
         "aliases": "SELECT old_id, new_id, at, reason FROM issue_aliases ORDER BY 1, 2",
         "groups": "SELECT g.group_id, g.day, g.final, g.members, g.copies, g.issue_id, c.asof FROM groups g "
                   "JOIN calc_runs c USING(calc_id) ORDER BY c.asof, g.group_id",
         "final": "SELECT day, finalized_at FROM final_days ORDER BY 1",
         "history": "SELECT issue_id, at, kind, detail FROM issue_history ORDER BY 1, 2, 3, 4"}
    return {k: [tuple(r) for r in con.execute(v)] for k, v in q.items()}


def test_schema_tables(tmp_path):
    con = store.connect(tmp_path / "e.db")
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names >= {"meta", "calc_runs", "articles", "copies", "groups", "issues", "issue_aliases", "issue_history",
                     "issue_trends", "issue_followups", "issue_entities", "issue_days", "final_days"}


def test_pulse_db_is_never_written(tmp_path):
    runs = K.hourly("2030-03-01T09:00", "2030-03-01T13:00")
    pdb = K.make_pulse(tmp_path / "p.db", _items(), runs)
    before = (pdb.stat().st_mtime_ns, hashlib.sha256(pdb.read_bytes()).hexdigest())
    con = store.connect(tmp_path / "e.db")
    for r in runs:
        pipeline.step(con, pdb, r)
    assert (pdb.stat().st_mtime_ns, hashlib.sha256(pdb.read_bytes()).hexdigest()) == before
    assert not (tmp_path / "p.db-wal").exists()


def test_copies_issue_and_new_day_link(tmp_path):
    con, res, _ = _run(tmp_path, _items(), K.hourly("2030-03-01T09:00", "2030-03-02T13:00"))
    io = pipeline.issue_of(res)
    k = {it["title"]: K.key_of(it) for it in _items()}
    fire = io[k["가람시 한빛전자 공장 화재…주민 대피"]]
    assert fire == "t20300301-001"
    assert io[k["[속보] 가람시 한빛전자 공장 화재…주민 대피"]] == fire               # 사본은 대표를 따라감
    assert io[k["가람시, 한빛전자 화재 피해 주민 지원센터 운영"]] == fire             # 다음 날 후속
    assert io[k["젠타은행 은하뱅크 합병 추진"]] == "t20300301-002"
    g = [g for g in res["frozen"] + res["groups"] if fire == g["issue_id"] and g["day"] == "2030-03-01"][0]
    assert "SBS" not in g["families"] and g["copies"]


def test_excluded_items_by_reason(tmp_path):
    its = _items() + [
        A("[부고] 가람시 인사", "연합뉴스", "2030-03-01T09:40"),
        A("가람시 옛 보도자료", "가람시청", "2030-02-20T09:00", kind="official", feed="moef", first_seen="2030-03-01T09:10"),
        A("가람시 커뮤니티 글", "커뮤니티", "2030-03-01T09:50", kind="community", feed="ppomppu"),
    ]
    pdb = K.make_pulse(tmp_path / "p.db", its, [])
    items, ex = source.load_items(pdb, K.kst("2030-03-01T13:00"))
    assert ex == {"소음 제목": 1, "옛 항목": 1, "종류": 1}
    assert len(items) == 5      # 받은 시각이 13시 전인 것만(둘째 날 기사 둘은 아직 없음)


@pytest.mark.real_ledger
def test_ledger_blocked_feed_is_excluded(tmp_path):
    its = [A("Hanbit Electronics Fire Spreads", "BBC", "2030-03-01T09:30", feed="bbc_world", lang="en"),
           A("가람시 한빛전자 공장 화재", "연합뉴스", "2030-03-01T09:00")]
    pdb = K.make_pulse(tmp_path / "p.db", its, [])
    items, ex = source.load_items(pdb, K.kst("2030-03-01T13:00"))
    assert ex == {"대장": 1} and [i["outlet"] for i in items] == ["연합뉴스"]


def test_asof_ignores_later_received_items_and_runs(tmp_path):
    runs = K.hourly("2030-03-01T09:00", "2030-03-01T13:30")
    T = runs[-1]
    con1, r1, _ = _run(tmp_path, _items(), runs, "a.db")
    later = [A("가람시 한빛전자 화재 원인은 합선", "경향신문", "2030-03-01T12:30", first_seen="2030-03-01T14:00"),
             A("젠타은행 합병 반대 노조", "머니투데이", "2030-03-01T13:30")]
    runs2 = runs + K.hourly("2030-03-01T14:00", "2030-03-01T16:30")
    pdb2 = K.make_pulse(tmp_path / "p2.db", _items() + later, runs2)
    con2 = store.connect(tmp_path / "b.db")
    for r in runs:
        r2 = pipeline.step(con2, pdb2, r)
    assert r1["asof"] == r2["asof"] == T.isoformat()
    assert _dump(con1) == _dump(con2)


def test_replay_twice_is_identical_and_view_mints_nothing(tmp_path):
    runs = K.hourly("2030-03-01T09:00", "2030-03-03T13:00", every_h=2)
    con1, _, pdb = _run(tmp_path, _items(), runs, "a.db")
    con2, _, _ = _run(tmp_path, _items(), runs, "b.db")
    assert _dump(con1) == _dump(con2)
    before = _dump(con1)
    v = pipeline.step(con1, pdb, K.kst("2030-03-03T14:30"), mode="view")
    assert v["mode"] == "view" and _dump(con1) == before


def test_finalized_day_is_frozen_and_late_items_counted(tmp_path):
    runs = K.hourly("2030-03-01T09:00", "2030-03-02T14:00", every_h=2)
    late = A("한빛전자 가람시 화재 늦은 보도", "경향신문", "2030-03-01T20:00", first_seen="2030-03-02T12:30")
    con, res, _ = _run(tmp_path, _items() + [late], runs)
    assert "2030-03-01" in store.final_days(con)
    frozen = [g for g in res["frozen"] + res["groups"] if g["day"] == "2030-03-01"]
    assert all(K.key_of(late) not in g["units"] for g in frozen)
    assert res["late"] == 1
    # 확정 뒤 단계를 더 돌려도 그날 그룹은 그대로
    snap = [(g["group_id"], g["units"], g["issue_id"]) for g in frozen]
    pdb2 = K.make_pulse(tmp_path / "p2.db", _items() + [late], runs + K.hourly("2030-03-02T15:00", "2030-03-02T19:00", 2))
    for r in K.hourly("2030-03-02T15:00", "2030-03-02T19:00", 2):
        res2 = pipeline.step(con, pdb2, r)
    assert [(g["group_id"], g["units"], g["issue_id"]) for g in res2["frozen"] if g["day"] == "2030-03-01"] == snap


def test_copy_of_finalized_rep_follows_its_issue(tmp_path):
    its = _items() + [A("가람시 한빛전자 공장 화재…주민 대피", "경향신문", "2030-03-02T08:00")]   # 전날 기사의 전재
    con, res, _ = _run(tmp_path, its, K.hourly("2030-03-01T09:00", "2030-03-02T13:00", 2))
    k = K.key_of(its[-1])
    io = pipeline.issue_of(res)
    assert io[k] == "t20300301-001"


def test_merge_override_by_steps(tmp_path):
    """9-1의 22번: merge 를 at=10:00 으로 적으면 09:05 단계는 두 이슈, 10:05 단계부터 하나. 09:05 를 다시 봐도 둘."""
    its = [A("가람시 한빛전자 공장 화재…주민 대피", "연합뉴스", "2030-03-01T07:00"),
           A("한빛전자 가람시 공장 화재 진화 중", "한국경제", "2030-03-01T07:30"),
           A("켐텍화학 덴포시 공장 폭발", "매일경제", "2030-03-01T08:00"),
           A("덴포시 켐텍화학 공장 폭발 사고 수습", "서울경제", "2030-03-01T08:20")]
    ov = tmp_path / "ov.yaml"
    ov.write_text('- {at: "2030-03-01T10:00:00+09:00", by: 사용자, action: merge, keep: t20300301-001, '
                  'absorb: [t20300301-002], reason: 같은 사건}\n', encoding="utf-8")
    runs = [K.kst("2030-03-01T09:05"), K.kst("2030-03-01T10:05")]
    pdb = K.make_pulse(tmp_path / "p.db", its, runs)
    con = store.connect(tmp_path / "e.db")
    r9 = pipeline.step(con, pdb, runs[0], overrides_path=ov)
    k3 = K.key_of(its[2])
    assert pipeline.issue_of(r9)[k3] == "t20300301-002"
    r10 = pipeline.step(con, pdb, runs[1], overrides_path=ov)
    assert pipeline.issue_of(r10)[k3] == "t20300301-001"
    assert store.aliases(con) == {"t20300301-002": "t20300301-001"}
    again = pipeline.step(con, pdb, runs[0], mode="view", overrides_path=ov)
    assert pipeline.issue_of(again)[k3] == "t20300301-002"


def test_analysis_cache_respects_dict_version(tmp_path):
    con = store.connect(tmp_path / "e.db")
    a = K.unit("가람시 한빛전자 화재", "연합뉴스", "2030-03-01T09:00")
    store.put_articles(con, [a], "옛판")
    assert store.get_analysis(con, [a["key"]], "옛판")[a["key"]]["entities"] == a["entities"]
    assert store.get_analysis(con, [a["key"]], "새판") == {}


def test_registry_roundtrip(tmp_path):
    from ozl.signals.link import Issue
    con = store.connect(tmp_path / "e.db")
    reg = {"t20300301-001": Issue("t20300301-001", "ko", "2030-03-01", "2030-03-01T00:05:00+00:00", 3, "k", "제목")}
    store.save_registry(con, reg)
    reg["t20300301-001"].status = "vanished"
    store.save_registry(con, reg)
    got = store.load_registry(con)
    assert got["t20300301-001"].status == "vanished" and got["t20300301-001"].minted_calc == 3
    assert store.load_registry(con, asof="2030-02-28T00:00:00+00:00") == {}
    assert isinstance(con, sqlite3.Connection)
