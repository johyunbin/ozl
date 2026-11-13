"""화제 엔진: 2026-11-14 검토 지적을 끝에서 끝으로 막는 시험(지난 시각 보기, 확정 시각 뒤 검색어, 전재 사본과 간접 포착).
제목은 전부 지어낸 것이다."""
import pytest

from ozl.signals import engine, store

import test_signals_kit as K
from test_signals_engine import A, D1, X, Y, go, pulse, rows, trend

D2 = "2030-03-02"


def test_view_before_last_step_does_not_mix_later_finals(tmp_path):
    """마지막 단계보다 이른 기준 시각: 보기 전용 계산을 하지 않고(확정 행을 asof 로 자를 수 없다) 그 앞 단계의 판을 돌려준다.
    라이브 board.json 은 덮어쓰지 않는다. engine.step(view) 를 직접 부르면 멈춘다(IndexError 가 아니라 까닭을 말하는 오류)."""
    its = [A(X, "연합뉴스", f"{D1}T09:00"), A(Y, "한국경제", f"{D1}T09:30"),
           A("한빛전자 가람시 신공장 착공 연기", "매일경제", f"{D2}T09:00"),
           A("가람시 한빛전자 신공장 착공 미뤄져", "서울경제", f"{D2}T09:30")]
    runs = K.hourly(f"{D1}T09:00", "2030-03-03T14:00", every_h=2)
    con, out, pdb = go(tmp_path, its, runs)
    assert D1 in store.final_days(con) and D2 in store.final_days(con)
    live = tmp_path / "board.json"
    live.write_text("라이브", encoding="utf-8")
    past = K.kst(f"{D2}T10:30")
    got = engine.catch_up(con, pdb, past, board_out=live)
    assert got["past"] is True and live.read_text(encoding="utf-8") == "라이브"
    b = got["board"]
    assert b["asof"] <= past.astimezone(K.config.KST).isoformat() and b["base_day"] == D2
    assert b == engine.rebuild_board(con, past)
    with pytest.raises(ValueError, match="마지막 단계"):
        engine.step(con, pdb, K.kst(f"{D1}T10:30"), "view")


def test_trend_received_after_final_time_is_not_in_final_day(tmp_path):
    """확정 시각(다음날 12:00) 뒤에 받은 검색어는 그날 확정 행의 g 에 들지 않는다(단계가 그 뒤에 처음 돌아도)."""
    its = [A(X, "연합뉴스", f"{D1}T09:00"), A(Y, "한국경제", f"{D1}T09:30"),
           trend("한빛전자 신공장", "1000+", f"{D1}T20:00", news=X)]
    its[-1]["first_seen"] = K.kst(f"{D2}T12:30").isoformat()
    con, out, _ = go(tmp_path, its, [K.kst(f"{D1}T10:05"), K.kst(f"{D2}T13:05")])
    g = con.execute("SELECT g FROM issue_days WHERE issue_id='t20300301-001' AND day=? AND final=1", (D1,)).fetchone()
    assert g[0] == 0.0


def test_copies_are_not_counted_as_indirect_outlets(tmp_path):
    """간접 포착 매체 수는 대표 기사만 센다. 같은 제목의 전재 사본(다른 매체)은 세지 않는다."""
    x2 = X + " SNS서 화제"
    its = [A(x2, "연합뉴스", f"{D1}T09:00"), A(x2, "한국경제", f"{D1}T09:05"), A(Y, "매일경제", f"{D1}T09:30")]
    _, out, _ = go(tmp_path, its, K.hourly(f"{D1}T09:00", f"{D1}T12:00"))
    r = rows(out["board"])["t20300301-001"]
    assert r["copies_n"] == 1
    assert r["indirect"] == {"n": 1, "label": "커뮤니티에서 화제라는 보도 1곳"}


def test_sns_word_does_not_glue_different_events(tmp_path):
    """'SNS서 화제'만 같은 서로 다른 두 사건은 한 묶음이 되지 않는다."""
    its = [A("가람시 한빛전자 공장 SNS서 화제", "연합뉴스", f"{D1}T09:00"),
           A("누리은행 젠타카드 혜택 SNS서 화제", "한국경제", f"{D1}T09:10")]
    _, out, _ = go(tmp_path, its, K.hourly(f"{D1}T09:00", f"{D1}T12:00"))
    gs = out["res"]["groups"]
    assert len(gs) == 2 and all(len(g["units"]) == 1 for g in gs)
