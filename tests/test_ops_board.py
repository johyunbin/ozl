"""고르기 화면이 화제 엔진의 board.json 을 읽는다 — 두 구역, 나머지 후보, 영문 접기, 없음·꼴 틀림이면 now.json 으로.

board 자료는 모두 지어낸 것이다(실제 기사 제목을 쓰지 않는다). 실제 서버를 127.0.0.1 의 빈 포트에 띄운다.
"""
from __future__ import annotations

import json
import re

import pytest

from test_ops_support import NOW, desk, ops, real_untouched  # noqa: F401

from ozl.ops import actions, candidates, queue

pytestmark = pytest.mark.usefixtures("real_untouched")


def _cand(iid, title, score, raw, *, lang="ko", zone=None, state=None, sens=("GREEN", ""), indirect=None,
          category="경제", outlets=3):
    return {
        "issue_id": iid, "aliases": [], "lang": lang, "title": title, "score": score, "score_raw": raw,
        "state": state, "day_n": 2, "first_day": "2098-12-31", "status_line": "2일째" + (f" · {state}" if state else ""),
        "new_thing": "", "parts": {}, "outlets_n": outlets, "articles_n": outlets + 1, "copies_n": 0,
        "kinds": ["언론"], "kinds_ok": ["언론", "검색", "공공 원문"], "missing": [], "category": category,
        "sensitivity": {"level": sens[0], "reason": sens[1]}, "person": False, "indirect": indirect,
        "links": [{"title": f"{title} 대표 기사", "url": f"https://news.example/{iid}", "outlet": "가상일보",
                   "at": "2099-01-01T09:00:00+09:00", "kind": "news"},
                  {"title": "주소가 이상한 기사", "url": "javascript:alert(1)", "outlet": "가상방송", "at": "", "kind": "news"}],
        "zone": zone,
    }


def fake_board() -> dict:
    cands = [
        _cand("t20990101-001", "가상 새 이슈 갑", 41, 40.6, zone="new", state="새로 뜸"),
        _cand("t20990101-002", "가상 새 이슈 을", 38, 38.2, zone="new", state="새로 뜸",
              sens=("YELLOW", "가상 민감 사유 하나")),
        _cand("t20981231-005", "가상 이어지는 이슈", 30, 29.5, zone="ongoing", state="커지는 중", category="국제"),
        _cand("t20981231-007", "가상 영문 이슈", 60, 59.9, lang="en", category="과학기술"),
        _cand("t20981231-008", "가상 민감 높은 이슈", 50, 49.5, sens=("RED", "가상 사유 둘")),
        _cand("t20981231-009", "가상 간접 포착 이슈", 12, 12.4,
              indirect={"n": 2, "label": "커뮤니티에서 화제라는 보도 2곳"}),
        _cand("t20990101-003", "가상 낮은 이슈", 5, 4.5),
        _cand("임시-0a1b2c3d", "가상 임시 번호 이슈", 3, 3.0),
    ]
    return {
        "schema": "ozl.board/1", "asof": "2099-01-01T11:05:00+09:00", "base_day": "2099-01-01",
        "base_day_partial": True, "decided_at": "2099-01-01T11:06:00+09:00", "calc_id": 7, "mode": "step",
        "versions": {}, "basis": "가상 기준", "sources": [], "missing": ["검색(오래됨, 마지막 성공 09:05)"],
        "zones": {"new": {"rows": ["t20990101-002", "t20990101-001"], "empty_reason": None,
                          "capped": [{"category": "경제", "skipped": 1}]},
                  "ongoing": {"rows": ["t20981231-005"], "empty_reason": None, "capped": []}},
        "candidates": cands, "searches_unmatched": [{"keyword": "가상단독검색어", "grade": 0.55, "day": "2099-01-01"}],
        "merge_hints": [], "note": "가상 엔진 문구",
    }


def write_board(o, d) -> None:
    p = o.tmp / "pulse_out" / "board.json"
    p.write_text(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False), encoding="utf-8")


def titles_in(page: str) -> list[str]:
    return [t.strip() for t in re.findall(r'<p class="title">([^<]+)', page)]


def test_board_zones_come_first_in_engine_order(ops):
    write_board(ops, fake_board())
    page = ops.client.get("/pick")[2]
    assert "옛 수집 목록" not in page
    assert page.index("<h2>새로 뜬 것</h2>") < page.index("<h2>이어지는 것</h2>") < page.index("<h2>그 밖의 후보</h2>")
    t = titles_in(page)
    # 새로 뜬 것은 엔진이 정한 차례(을 → 갑) 그대로, 나머지는 한국어를 점수순, 영문은 맨 아래 접힘
    assert t[:3] == ["가상 새 이슈 을", "가상 새 이슈 갑", "가상 이어지는 이슈"]
    assert t[3:6] == ["가상 민감 높은 이슈", "가상 간접 포착 이슈", "가상 낮은 이슈"]
    assert t[6] == "가상 영문 이슈"
    assert page.index("영문 이슈 1건") < page.index("가상 영문 이슈")
    assert "가상 임시 번호 이슈" not in page and "이슈 번호가 없는 후보 1건" in page
    assert "분야 상한으로 아래 목록으로 내린 것: 경제 1건" in page


def test_board_row_facts_and_head_line(ops):
    write_board(ops, fake_board())
    page = ops.client.get("/pick")[2]
    assert "기준 시각 1월 1일 11:05" in page and "1월 1일 값은 아직 확정 전" in page
    assert "출처 누락: 검색(오래됨, 마지막 성공 09:05)" in page
    assert candidates.FACT_NOTE in page
    assert "점수 41" in page and "상태 새로 뜸" in page and "매체 계열 오늘 3곳" in page and "분야 국제" in page
    assert "기준일" not in page and "정하지 않음" not in page
    assert "상태 없음" in page                                   # 상태가 빈 후보(가상 민감 높은 이슈 등)
    assert "민감 주의: 가상 민감 사유 하나" in page and "민감 높음: 가상 사유 둘" in page
    assert page.count('<span class="tag">민감</span>') == 2
    assert "간접 포착: 커뮤니티에서 화제라는 보도 2곳" in page
    assert 'href="https://news.example/t20990101-001"' in page and "javascript:" not in page
    assert "정리 전" not in page
    assert "가상단독검색어" in page and "이슈와 묶이지 않은 급상승 검색어" in page


def test_make_queues_engine_issue_id(ops):
    write_board(ops, fake_board())
    c = ops.client
    c.login()
    st, r, _ = c.post("/pick/make", {"key": "t:t20990101-001"})
    assert st == 303 and r.getheader("Location") == "/pick?m=1"
    j = ops.state("make_queue.json")["items"][-1]
    assert (j["kind"], j["topic_id"], j["title"]) == ("topic", "t20990101-001", "가상 새 이슈 갑")
    assert "대기열에 있음" in c.get("/pick")[2]
    assert c.post("/pick/make", {"key": "t:9000"})[0] == 303          # board 에 없는 옛 번호는 없는 후보(꼴은 맞다)
    assert c.post("/pick/make", {"key": "t:t2099-1"})[0] == 400


def test_later_and_discard_hide_zone_rows(ops):
    write_board(ops, fake_board())
    c = ops.client
    c.login()
    assert c.post("/pick/later", {"key": "t:t20990101-002"})[0] == 303
    assert c.post("/pick/discard", {"key": "t:t20981231-005"})[0] == 303
    head = c.get("/pick")[2].split("버린 목록", 1)[0]
    assert "가상 새 이슈 을" not in head and "가상 이어지는 이슈" not in head
    assert "가상 새 이슈 갑" in head


def test_no_board_falls_back_to_now(ops):
    page = ops.client.get("/pick")[2]
    assert "화제 엔진 결과(board.json)가 없다. 옛 수집 목록(now.json)을 보인다." in page
    assert "가상 주제 1번 소식" in page and "<h2>수집 후보</h2>" in page and "새로 뜬 것" not in page


@pytest.mark.parametrize("bad", [
    "{not json",
    {"schema": "ozl.board/2", "candidates": [], "zones": {}},
    {"schema": "ozl.board/1", "candidates": {"a": 1}, "zones": {}},
    {"schema": "ozl.board/1", "candidates": [], "zones": {"new": {"rows": "t20990101-001"}}},
    {"schema": "ozl.board/1", "candidates": [{"issue_id": "t20990101-001", "score": "높음"}], "zones": {}},
])
def test_bad_board_falls_back_to_now(ops, bad):
    write_board(ops, bad)
    page = ops.client.get("/pick")[2]
    assert "옛 수집 목록(now.json)을 보인다." in page
    assert ("읽지 못했다" in page) or ("꼴이 맞지 않는다" in page)
    assert "가상 주제 1번 소식" in page


def test_key_and_topic_id_patterns():
    ok = ["t:9000", "t:t20990101-001", "t:t20990101-1234", "q:0123456789ab", "k:01234567"]
    bad = ["t:t2099-001", "t:t20990101-01", "t:임시-0a1b2c3d", "t:abc", "t:t20990101-00a"]
    assert all(re.fullmatch(actions.KEY_RE, k) for k in ok)
    assert not any(re.fullmatch(actions.KEY_RE, k) for k in bad)
    d = {"items": []}
    kw = dict(key="t:x", kind="topic", title="가상", keyword=None, deck=False, request_id="r", now=NOW)
    queue.enqueue(d, topic_id=9000, **kw)
    queue.enqueue(d, topic_id="t20990101-001", **{**kw, "key": "t:y"})
    queue.enqueue(d, topic_id=None, **{**kw, "key": "t:z"})
    for b in ("t2099-1", "9000", True, 1.5):
        with pytest.raises(ValueError):
            queue.enqueue(d, topic_id=b, **{**kw, "key": "t:w"})


def test_board_row_shows_yesterday_beside_partial_today(ops):
    """진행 중인 날(오늘)에는 아침에 거의 모든 줄이 0곳이라, 어제 값을 함께 보인다(마-2)."""
    b = fake_board()
    b["candidates"][0].update({"outlets_n": 0, "kinds": [],
                               "prev_day": {"day": "2098-12-31", "outlets_n": 5, "articles_n": 9,
                                            "kinds": ["언론", "검색"], "kinds_ok": ["언론", "검색", "공공 원문"],
                                            "score": 30, "state": "새로 뜸"}})
    write_board(ops, b)
    page = ops.client.get("/pick")[2]
    assert "매체 계열 오늘 0곳, 어제 5곳" in page and "출처 종류 오늘 0/3, 어제 2/3" in page
    b["base_day_partial"] = False
    write_board(ops, b)
    page = ops.client.get("/pick")[2]
    assert "1월 1일 매체 계열 0곳" in page and "어제 5곳" not in page and "1월 1일 출처 종류 0/3" in page
