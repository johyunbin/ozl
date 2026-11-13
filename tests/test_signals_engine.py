"""화제 엔진 B: 수집 DB(지어낸 자료) → engine.step → board.json 까지 끝에서 끝으로(설계 §9-1 일부, §9-3, §9-4, 명령).

제목은 모두 지어낸 것이다(가람시, 한빛전자, 누리은행 …). 기대값 옆의 계산은 손으로 했다.
"""
import hashlib
import json
import sqlite3

import pytest

from ozl.signals import __main__ as cli
from ozl.signals import board, engine, explain, store, wiki

import test_signals_kit as K

A = K.art
D1 = "2030-03-01"
TREND_URL = "https://trends.google.com/trending/rss?geo=KR"
X = "한빛전자, 가람시에 반도체 신공장 짓는다"
Y = "가람시 한빛전자 신공장 유치 확정"
FIVE = [(X, "연합뉴스", "09:00"), (Y, "한국경제", "09:30"), ("한빛전자 가람시 신공장에 3조 투입", "매일경제", "10:00"),
        ("가람시, 한빛전자 반도체 공장 유치에 들썩", "서울경제", "10:30"), ("한빛전자 가람시 공장 착공 내년 상반기", "머니투데이", "11:00")]


def trend(kw, traffic, published, news="", geo="kr"):
    return A(kw, "구글 트렌드", published, kind="trend", feed="trends_" + geo, url=TREND_URL,
             extra={"traffic": traffic, "trend_news": news}, lang="ko" if geo == "kr" else "en")


def pulse(tmp_path, items, runs, failed=None, name="p.db"):
    """failed: {실행 순번: [실패 피드 id …]}. 실행 기록의 feeds_failed 는 pulse 가 쓰는 꼴(상태 dict 목록)로 넣는다."""
    p = K.make_pulse(tmp_path / name, items, runs)
    if failed:
        con = sqlite3.connect(p)
        ids = [r[0] for r in con.execute("SELECT run_id FROM runs ORDER BY at")]
        for i, feeds in failed.items():
            con.execute("UPDATE runs SET feeds_failed=? WHERE run_id=?",
                        (json.dumps([{"id": f, "error": "HTTP 503"} for f in feeds]), ids[i]))
        con.commit()
        con.close()
    return p


def go(tmp_path, items, runs, failed=None, name="e.db", ov=None):
    pdb = pulse(tmp_path, items, runs, failed, "p_" + name)
    con = store.connect(tmp_path / name)
    out = None
    for r in runs:
        out = engine.step(con, pdb, r, overrides_path=ov)
    return con, out, pdb


def rows(b):
    return {c["issue_id"]: c for c in b["candidates"]}


def five(day=D1):
    return [A(t, o, f"{day}T{h}") for t, o, h in FIVE]


def approx(x):
    return pytest.approx(x, abs=1e-6)


# ── §9-1 경계 사례(끝에서 끝으로)
def test_case1_all_zero_day(tmp_path):
    """1: 출처 셋 성공, 기사·검색어·공공 원문 0건 → 후보 0, 두 구역 빈 줄."""
    _, out, _ = go(tmp_path, [], K.hourly(f"{D1}T09:00", f"{D1}T12:00"))
    b = out["board"]
    assert b["candidates"] == [] and b["missing"] == []
    for z in ("new", "ongoing"):
        assert b["zones"][z]["rows"] == [] and b["zones"][z]["empty_reason"] == "오늘 새로 잡힌 이슈가 없다"
    assert b["basis"] == "출처 3종 기준(언론, 검색, 공공 원문 · 위키백과 수집 없음)"


def test_case2_single_candidate(tmp_path):
    """2: 첫날 A=5, 검색 500+, 공공 없음 → v=0.530075, B=2/3, P=1/7, score 27(27.290717), 새로 뜸, 새로 뜬 것 1줄."""
    its = five() + [trend("한빛전자 신공장", "500+", f"{D1}T10:00", news=X)]
    _, out, _ = go(tmp_path, its, K.hourly(f"{D1}T09:00", f"{D1}T13:05"))
    b = out["board"]
    assert b["schema"] == "ozl.board/1" and b["base_day"] == D1 and b["base_day_partial"] is True
    r = rows(b)["t20300301-001"]
    assert r["parts"] == {"v": approx(0.530075), "H": approx(0.530075), "B": approx(0.666667), "P": approx(0.142857),
                          "D": 0.0, "A": 5, "g": 0.55, "w": None}
    assert (r["score"], r["score_raw"]) == (27, approx(27.290717))
    assert (r["state"], r["day_n"], r["status_line"], r["zone"]) == ("새로 뜸", 1, "1일째 · 새로 뜸", "new")
    assert (r["outlets_n"], r["articles_n"], r["copies_n"]) == (5, 5, 0)
    assert r["kinds"] == ["언론", "검색"] and r["kinds_ok"] == ["언론", "검색", "공공 원문"] and r["missing"] == []
    assert r["title"] == X and len(r["links"]) == 3 and r["links"][0]["kind"] == "news"
    assert b["zones"]["new"]["rows"] == ["t20300301-001"] and b["zones"]["ongoing"]["rows"] == []
    assert b["searches_unmatched"] == []
    assert "500+" not in json.dumps(b, ensure_ascii=False)          # 검색량 원래 표기는 싣지 않는다
    src = {s["kind"]: s for s in b["sources"]}
    assert src["검색"]["status"] == "성공" and src["위키백과"]["status"] == "꺼짐"
    assert src["언론"]["last_ok"] == "2030-03-01T13:05:00+09:00"


def test_case3_search_failed_end_to_end(tmp_path):
    """3: 2번에서 그날 trends_kr·trends_us 성공 실행 없음 → v=L(5)=0.521772, B=1/2, score 23, missing ['검색(실패)']."""
    its = five() + [trend("한빛전자 신공장", "500+", f"{D1}T10:00", news=X)]
    runs = K.hourly(f"{D1}T09:00", f"{D1}T13:05")
    _, out, _ = go(tmp_path, its, runs, failed={i: ["trends_kr", "trends_us"] for i in range(len(runs))})
    r = rows(out["board"])["t20300301-001"]
    assert r["parts"]["v"] == approx(0.521772) and r["parts"]["B"] == 0.5 and r["score"] == 23
    assert r["missing"] == ["검색(실패)"] and out["board"]["missing"] == ["검색(실패)"]
    assert r["kinds_ok"] == ["언론", "공공 원문"]


def test_case4_thirty_wire_copies(tmp_path):
    """4: 같은 제목 30건(매체 30곳, 30분 안) + 따로 쓴 다른 매체 기사 2건 → A=3, copies_n=29, v=0.6×0.403698/0.85=0.284963,
    100×(0.4×0.113985 + 0.083333 + 0.021429) = 15.035605 → 15."""
    its = [A(X, f"가상일보{i:02d}", f"{D1}T09:{i:02d}") for i in range(30)]
    its += [A(Y, "한국경제", f"{D1}T10:00"), A("한빛전자 가람시 신공장에 3조 투입", "매일경제", f"{D1}T10:30")]
    _, out, _ = go(tmp_path, its, K.hourly(f"{D1}T09:00", f"{D1}T12:00"))
    r = rows(out["board"])["t20300301-001"]
    assert (r["parts"]["A"], r["outlets_n"], r["copies_n"], r["articles_n"]) == (3, 3, 29, 32)
    assert r["parts"]["v"] == approx(0.284963) and r["score_raw"] == approx(15.035605) and r["score"] == 15


def test_case5_same_article_in_feed_and_trend(tmp_path):
    """5: O1 기사 X, O2 기사 Y, 급상승(200+)의 trend_news = X 제목 → A=2, articles_n=2, g=0.40,
    v=(0.6×0.319923+0.25×0.4)/0.85=0.343475, B=2/3, 100×(0.4×0.137390+0.166667+0.021429)=24.305127 → 24."""
    its = [A(X, "연합뉴스", f"{D1}T09:00"), A(Y, "한국경제", f"{D1}T09:30"),
           trend("한빛전자 신공장", "200+", f"{D1}T10:00", news=X)]
    _, out, _ = go(tmp_path, its, K.hourly(f"{D1}T09:00", f"{D1}T12:00"))
    r = rows(out["board"])["t20300301-001"]
    assert (r["parts"]["A"], r["articles_n"], r["parts"]["g"]) == (2, 2, 0.4)
    assert r["parts"]["v"] == approx(0.343475) and r["score_raw"] == approx(24.305127) and r["score"] == 24
    assert r["indirect"] is None


def test_case6_sns_word_only_marks_indirect(tmp_path):
    """6: 5번의 두 제목 끝에 'SNS서 화제'를 붙임 → kinds, B, score 5번과 같음(24), indirect.n=2, 그룹 구성도 같음."""
    x2, y2 = X + " SNS서 화제", Y + " SNS서 화제"
    its = [A(x2, "연합뉴스", f"{D1}T09:00"), A(y2, "한국경제", f"{D1}T09:30"),
           trend("한빛전자 신공장", "200+", f"{D1}T10:00", news=x2)]
    _, out, _ = go(tmp_path, its, K.hourly(f"{D1}T09:00", f"{D1}T12:00"))
    r = rows(out["board"])["t20300301-001"]
    assert r["score"] == 24 and r["kinds"] == ["언론", "검색"] and r["parts"]["B"] == approx(2 / 3)
    assert r["indirect"] == {"n": 2, "label": "커뮤니티에서 화제라는 보도 2곳"}
    gs = [g for g in out["res"]["groups"] if g["issue_id"] == "t20300301-001"]
    assert len(gs) == 1 and len(gs[0]["units"]) == 2


@pytest.mark.parametrize("last_ok_run, status, v", [(4, "오래됨", 0.431711), (0, "오래됨", 0.431711),
                                                     (-1, "실패", 0.319923)])
def test_case8_stale_or_failed_search(tmp_path, last_ok_run, status, v):
    """8 (가) 검색 마지막 성공이 asof 9시간 전 → 오래됨: g=0.70 그대로, v=0.431711, score 26.
    (나) 13시간 전(그날 00:05) → 그날 성공이 있으므로 오래됨, 관측값 그대로(2026-11-14 검토 반영).
    (다) 그날 검색 성공이 하나도 없음 → 실패: v=L(2)=0.319923."""
    runs = K.hourly(f"{D1}T00:00", f"{D1}T13:05")          # 00:05 … 13:05
    its = [A(X, "연합뉴스", f"{D1}T00:30"), A(Y, "한국경제", f"{D1}T00:40"),
           trend("한빛전자 신공장", "1000+", f"{D1}T00:50", news=X)]
    failed = {i: ["trends_kr", "trends_us"] for i in range(last_ok_run + 1, len(runs))}
    _, out, _ = go(tmp_path, its, runs, failed=failed)
    r = rows(out["board"])["t20300301-001"]
    assert r["parts"]["v"] == approx(v)
    assert r["missing"][0].startswith(f"검색({status}")
    if status == "오래됨":
        hm = f"{last_ok_run:02d}:05"
        assert r["missing"] == [f"검색(오래됨, 마지막 성공 {hm})"] and r["parts"]["g"] == 0.7 and r["score"] == 26


def test_case8_old_official_and_yesterdays_trend(tmp_path):
    """8 (다) 발행 시각이 받은 시각보다 80시간 앞선 공공 원문 → 점수에 없음, excluded.옛 항목 +1.
    (라) 어제 오른 검색어 → 오늘 g 에 없음(어제 줄에만)."""
    d2 = "2030-03-02"
    its = [A(X, "연합뉴스", f"{D1}T09:00"), A(Y, "한국경제", f"{D1}T09:30"),
           trend("한빛전자 신공장", "1000+", f"{D1}T10:00", news=X),
           A("한빛전자, 가람시 신공장 착공식 열어", "매일경제", f"{d2}T09:00"),
           A("가람시 한빛전자 신공장 착공…지역 기대", "서울경제", f"{d2}T09:30"),
           A("가람시 한빛전자 신공장 보조금 공고", "가람시청", "2030-02-27T00:00", kind="official", feed="moef_press",
             first_seen=f"{d2}T08:00")]        # 받은 시각보다 104시간 앞섬
    con, out, _ = go(tmp_path, its, K.hourly(f"{D1}T09:00", f"{d2}T11:05", every_h=2))
    iid = "t20300301-001"
    by = {r["day"]: r for r in out["rows"] if r["issue_id"] == iid}
    assert by[D1]["g"] == 0.7 and by[d2]["g"] == 0.0
    assert rows(out["board"])[iid]["kinds"] == ["언론"]
    ex = json.loads(con.execute("SELECT excluded FROM calc_runs ORDER BY calc_id DESC LIMIT 1").fetchone()[0])
    assert ex.get("옛 항목") == 1


def test_case14_dormant_issue_wakes_with_same_number(tmp_path):
    """14: 1일 이슈, 2~8일 기사 없음(8일 휴면), 9일 같은 사건(고유명사 둘, 사건 낱말 둘, 제목 0.35) → 같은 번호, 다시 오름, 이력 '깨어남'.
    v(1)=v(9)=0.6×L(2)/0.85=0.225828. 8일: 7일째 이상이고 2~8일 v=0 → 휴면.
    9일: 6~8일 v=0 < 0.3×0.225828, v(9) ≥ 0.5×0.225828 → 다시 오름."""
    its = [A("가람시 한빛전자 공장 화재로 주민 대피", "연합뉴스", "2030-03-01T09:00"),
           A("한빛전자 가람시 공장 화재 주민 대피 이틀째", "한국경제", "2030-03-01T10:00"),
           A("가람시 한빛전자 공장 화재 주민 대피 원인 결론", "매일경제", "2030-03-09T10:00"),
           A("한빛전자 가람시 화재 대피 주민 귀가", "서울경제", "2030-03-09T11:00")]
    runs = K.hourly("2030-03-01T13:00", "2030-03-10T13:05", every_h=24)
    con, out, _ = go(tmp_path, its, runs)
    q = "SELECT day, v, state FROM issue_days WHERE issue_id='t20300301-001' AND final=1 ORDER BY day"
    days = {d: (v, s) for d, v, s in con.execute(q)}
    assert days["2030-03-01"][0] == approx(0.225828)
    assert days["2030-03-08"] == (0.0, "휴면")
    assert days["2030-03-09"][1] == "다시 오름"
    kinds = [k for (k,) in con.execute("SELECT kind FROM issue_history WHERE issue_id='t20300301-001' ORDER BY at")]
    assert "휴면" in kinds and "깨어남" in kinds
    assert [i for (i,) in con.execute("SELECT issue_id FROM issues")] == ["t20300301-001"]


def test_case22_merge_override_on_board(tmp_path):
    """22: merge at=10:00 → 09:05 판은 두 이슈, 10:05 판부터 하나(합쳐진 번호는 별칭)."""
    its = [A("가람시 한빛전자 공장 화재…주민 대피", "연합뉴스", f"{D1}T07:00"),
           A("한빛전자 가람시 공장 화재 진화 중", "한국경제", f"{D1}T07:30"),
           A("켐텍화학 덴포시 공장 폭발", "매일경제", f"{D1}T08:00"),
           A("덴포시 켐텍화학 공장 폭발 사고 수습", "서울경제", f"{D1}T08:20")]
    ov = tmp_path / "ov.yaml"
    ov.write_text('- {at: "2030-03-01T10:00:00+09:00", by: 사용자, action: merge, keep: t20300301-001, '
                  'absorb: [t20300301-002], reason: 같은 사건}\n', encoding="utf-8")
    runs = [K.kst(f"{D1}T09:05"), K.kst(f"{D1}T10:05")]
    pdb = pulse(tmp_path, its, runs)
    con = store.connect(tmp_path / "e.db")
    b9 = engine.step(con, pdb, runs[0], overrides_path=ov)["board"]
    b10 = engine.step(con, pdb, runs[1], overrides_path=ov)["board"]
    assert sorted(rows(b9)) == ["t20300301-001", "t20300301-002"]
    assert sorted(rows(b10)) == ["t20300301-001"] and rows(b10)["t20300301-001"]["aliases"] == ["t20300301-002"]
    assert rows(b10)["t20300301-001"]["outlets_n"] == 4


# ── §9-3 기준 시각
def _three_days():
    its = []
    for d, (a, b) in {"2030-03-01": (X, Y), "2030-03-02": ("한빛전자, 가람시 신공장 착공식 열어", "가람시 한빛전자 신공장 착공…지역 기대"),
                      "2030-03-03": ("한빛전자 가람시 신공장 첫 장비 반입", "가람시 한빛전자 공장 장비 반입 시작")}.items():
        its += [A(a, "연합뉴스", f"{d}T09:00"), A(b, "한국경제", f"{d}T10:00")]
    its += [A("젠타은행 은하뱅크 합병 추진", "매일경제", "2030-03-02T11:00"),
            A("은하뱅크 젠타은행 합병 공식화", "서울경제", "2030-03-02T12:00"),
            A("가람시 한빛전자 신공장 지역 상권 기대", "동아일보", "2030-03-02T20:00", first_seen="2030-03-03T09:30"),
            trend("한빛전자 신공장", "2000+", "2030-03-01T10:00", news=X)]
    return its


def _snap(con, b):
    days = [tuple(r) for r in con.execute("SELECT issue_id, day, final, A, g, v, H, B, P, D, score_raw, score, state, "
                                          "missing, category FROM issue_days ORDER BY issue_id, day, calc_id")]
    bb = {k: v for k, v in b.items() if k not in ("decided_at", "calc_id")}
    return days, json.dumps(bb, ensure_ascii=False, sort_keys=True)


def test_asof_guarantee_with_later_data(tmp_path):
    """9-3: 사흘치로 asof=T 까지 계산한 결과와, 나흘째 자료·둘째 날 기사를 늦게 받은 것·T 뒤 실행·T 뒤 사람 판단을 더한 수집 DB 로
    asof=T 까지 다시 계산한 결과가 같다. 이어서 나흘째까지 계산해도 확정된 첫날·둘째 날 값은 그대로다."""
    runs = K.hourly("2030-03-01T09:00", "2030-03-03T22:00", every_h=3)
    T = runs[-1]
    ov = tmp_path / "ov.yaml"
    ov.write_text('- {at: "2030-03-04T09:00:00+09:00", by: 사용자, action: end, issue: t20300301-001, reason: 시험}\n',
                  encoding="utf-8")
    con1, out1, _ = go(tmp_path, _three_days(), runs, name="a.db", ov=ov)
    late = A("한빛전자 가람시 신공장 둘째 날 늦은 보도", "경향신문", "2030-03-02T15:00", first_seen="2030-03-04T03:00")
    day4 = [A("한빛전자 가람시 신공장 시운전", "연합뉴스", "2030-03-04T09:00"),
            A("가람시 한빛전자 신공장 시운전 돌입", "한국경제", "2030-03-04T10:00")]
    runs2 = runs + K.hourly("2030-03-04T01:00", "2030-03-04T13:00", every_h=3)
    pdb2 = pulse(tmp_path, _three_days() + [late] + day4, runs2, name="p2.db")
    con2 = store.connect(tmp_path / "b.db")
    for r in runs:
        out2 = engine.step(con2, pdb2, r, overrides_path=ov)
    assert out2["board"]["asof"] == out1["board"]["asof"]
    assert _snap(con2, out2["board"]) == _snap(con1, out1["board"])
    final_before = [tuple(r) for r in con1.execute("SELECT * FROM issue_days WHERE final=1 ORDER BY issue_id, day")]
    assert {r[1] for r in final_before} == {"2030-03-01", "2030-03-02"}
    for r in runs2[len(runs):]:
        out2 = engine.step(con2, pdb2, r, overrides_path=ov)
    final_after = [tuple(r) for r in con2.execute("SELECT * FROM issue_days WHERE final=1 AND day<='2030-03-02' "
                                                  "ORDER BY issue_id, day")]
    assert final_after == final_before
    assert out2["res"]["late"] >= 1
    assert rows(out2["board"])["t20300301-001"]["zone"] is None          # T 뒤 사람 판단(종료)은 T 뒤에만


# ── §9-4 이슈 번호
def _dump(con):
    q = {"issues": "SELECT issue_id, lang, first_day, minted_at, seed_key, title, status FROM issues ORDER BY 1",
         "aliases": "SELECT * FROM issue_aliases ORDER BY 1, 2",
         "days": "SELECT issue_id, day, final, A, g, v, H, B, P, D, score_raw, score, state FROM issue_days "
                 "ORDER BY issue_id, day, calc_id"}
    return {k: [tuple(r) for r in con.execute(v)] for k, v in q.items()}


def test_replay_twice_and_step_by_step_are_identical(tmp_path):
    runs = K.hourly("2030-03-01T09:00", "2030-03-03T22:00", every_h=3)
    pdb = pulse(tmp_path, _three_days(), runs)
    s1 = engine.replay(pdb, tmp_path / "r1.db", "2030-03-01", "2030-03-03", board_out=tmp_path / "b1.json")
    s2 = engine.replay(pdb, tmp_path / "r2.db", "2030-03-01", "2030-03-03", board_out=tmp_path / "b2.json")
    assert s1["steps"] == len(runs) and s1["issues_by_day"] == s2["issues_by_day"]
    a, b = store.connect(tmp_path / "r1.db"), store.connect(tmp_path / "r2.db")
    assert _dump(a) == _dump(b)
    assert engine.compare(tmp_path / "r1.db", tmp_path / "r2.db") == []
    c = store.connect(tmp_path / "s.db")
    for r in runs:
        engine.catch_up(c, pdb, r)
    assert _dump(c) == _dump(a)
    # view(실행 시각이 아닌 asof)는 번호 대장을 바꾸지 않고 날짜별 값도 쓰지 않는다
    before = _dump(c)
    v = engine.catch_up(c, pdb, K.kst("2030-03-03T23:30"))
    assert v["board"]["mode"] == "view" and _dump(c) == before


# ── 명령·explain·wiki
def test_cli_run_board_explain_replay(tmp_path, monkeypatch, capsys):
    its = five() + [trend("한빛전자 신공장", "500+", f"{D1}T10:00", news=X)]
    runs = K.hourly(f"{D1}T09:00", f"{D1}T13:05")
    pdb = pulse(tmp_path, its, runs)
    out = tmp_path / "out" / "board.json"
    monkeypatch.setenv("OZL_PULSE_DB", str(pdb))
    monkeypatch.setenv("OZL_ENGINE_DB", str(tmp_path / "engine.db"))
    monkeypatch.setenv("OZL_BOARD_OUT", str(out))
    monkeypatch.setenv("OZL_ENGINE_OVERRIDES", str(tmp_path / "없음.yaml"))
    assert cli.main(["run", "--asof", "2030-03-01T13:05:00+09:00"]) == 0
    b = json.loads(out.read_text(encoding="utf-8"))
    assert b["mode"] == "step" and rows(b)["t20300301-001"]["score"] == 27
    assert (tmp_path / "out" / "engine.lock").exists()
    capsys.readouterr()
    assert cli.main(["explain", "t20300301-001", "--json"]) == 0
    ex = json.loads(capsys.readouterr().out)
    lines = ex["days"][-1]["lines"]
    assert "v = (0.60×L(5)=0.313063 + 0.25×0.55=0.137500) / 0.85 = 0.530075" in lines
    assert "H = 0.7×0 + 0.530075 = 0.530075 → 화면용 0.212030" in lines
    assert "B = |{언론, 검색}| / |{언론, 검색, 공공 원문}| = 2/3" in lines
    assert lines[-1].endswith("= 27.290717 → 27")
    out2 = tmp_path / "b2.json"
    assert cli.main(["board", "--out", str(out2)]) == 0
    b2 = json.loads(out2.read_text(encoding="utf-8"))
    assert {k: v for k, v in b2.items() if k != "decided_at"} == {k: v for k, v in b.items() if k != "decided_at"}
    assert cli.main(["run", "--asof", "2030-03-01T13:30:00+09:00"]) == 0          # 실행 시각이 아니면 보기 전용
    assert json.loads(out.read_text(encoding="utf-8"))["mode"] == "view"
    r1, r2 = tmp_path / "r1.db", tmp_path / "r2.db"
    assert cli.main(["replay", "--from", D1, "--to", D1, "--db", str(r1), "--out", str(tmp_path / "rb.json")]) == 0
    assert cli.main(["replay", "--from", D1, "--to", D1, "--db", str(r2), "--out", str(tmp_path / "rb2.json"),
                     "--check-against", str(r1)]) == 0
    text = explain.render(explain.explain(store.connect(r1), "t20300301-001"))
    assert "위키백과 수집 없음" in text and "t20300301-001" in text


def test_replay_refuses_live_db_without_reset(tmp_path, monkeypatch):
    pdb = pulse(tmp_path, [], K.hourly(f"{D1}T09:00", f"{D1}T10:00"))
    live = tmp_path / "engine.db"
    store.connect(live).close()
    monkeypatch.setenv("OZL_PULSE_DB", str(pdb))
    monkeypatch.setenv("OZL_ENGINE_DB", str(live))
    assert cli.main(["replay", "--from", D1, "--to", D1, "--db", str(live), "--out", str(tmp_path / "b.json")]) == 2
    assert cli.main(["replay", "--from", D1, "--to", D1, "--db", str(live), "--out", str(tmp_path / "b.json"),
                     "--reset"]) == 0
    assert list(tmp_path.glob("engine.db.bak_*"))


def test_board_written_atomically(tmp_path):
    p = tmp_path / "x" / "board.json"
    board.write({"schema": "ozl.board/1", "a": "가"}, p)
    assert json.loads(p.read_text(encoding="utf-8"))["a"] == "가" and not list(p.parent.glob("*.tmp"))


def test_wiki_collector_is_off_without_contact(monkeypatch):
    called = []
    monkeypatch.setattr(wiki, "CONTACT", "")
    assert wiki.enabled() is False
    assert wiki.top_articles("2030-03-01", http_get=lambda *a, **k: called.append(a)) is None
    assert called == []
    # 연락처가 있어도 대장 collect 가 허용이 아니면 보내지 않는다
    monkeypatch.setattr(wiki, "CONTACT", "ops@example.test")
    monkeypatch.setattr(wiki, "_ledger_ok", lambda: False)
    assert wiki.enabled() is False and wiki.top_articles("2030-03-01", http_get=lambda *a, **k: called.append(a)) is None
    assert called == []
    monkeypatch.setattr(wiki, "_ledger_ok", lambda: True)
    fake = {"items": [{"articles": [{"article": "가람시", "rank": 1}, {"article": "특수:검색", "rank": 2}]}]}
    got = wiki.top_articles("2030-03-01", http_get=lambda url, headers: (called.append(url) or fake))
    assert got == [{"article": "가람시", "rank": 1}] and "ops@example.test" not in called[0]


def test_engine_never_writes_pulse_db(tmp_path):
    runs = K.hourly(f"{D1}T09:00", f"{D1}T12:00")
    pdb = pulse(tmp_path, five(), runs)
    before = (pdb.stat().st_mtime_ns, hashlib.sha256(pdb.read_bytes()).hexdigest())
    con = store.connect(tmp_path / "e.db")
    for r in runs:
        engine.step(con, pdb, r)
    assert (pdb.stat().st_mtime_ns, hashlib.sha256(pdb.read_bytes()).hexdigest()) == before
