"""고르기 단추 — 누를 때마다 actions.jsonl 이 정확히 한 줄, 상태 JSON 이 기대대로, 같은 요청 번호는 무증가(설계 4절, 11절).

실제 서버를 127.0.0.1 의 빈 포트에 띄우고 시험 자료 루트(임시 폴더)에만 쓴다. 제목은 지어낸 것이다.
"""
from __future__ import annotations

import os
import re

import pytest

from test_ops_support import NOW, desk, ops, real_untouched, tomorrow_clock  # noqa: F401

from ozl.ops import candidates, queue

pytestmark = pytest.mark.usefixtures("real_untouched")


def press(o, path, **fields):
    n = len(o.lines())
    st, r, _ = o.client.post(path, fields)
    return st, r, len(o.lines()) - n


def test_every_button_writes_one_line(ops):
    c = ops.client
    c.login()
    st, r, d = press(ops, "/pick/make", key="t:9000")
    assert (st, d) == (303, 1) and r.getheader("Location") == "/pick?m=1"
    q = ops.state("make_queue.json")["items"]
    assert len(q) == 1 and q[0]["state"] == "대기" and q[0]["topic_id"] == 9000 and q[0]["deck"] is False
    assert re.fullmatch(r"m20990101-0001", q[0]["job_id"])

    st, _, d = press(ops, "/pick/make", key="t:9001", deck="1")
    assert (st, d) == (303, 1)
    assert ops.state("make_queue.json")["items"][1]["deck"] is True

    st, _, d = press(ops, "/pick/later", key="t:9002")
    assert (st, d) == (303, 1)
    later = ops.state("later.json")["items"]
    assert later[0]["show_from"] == "2099-01-02" and later[0]["snapshot"]["title"] == "가상 주제 3번 소식"
    page = c.get("/pick")[2]
    assert "가상 주제 3번 소식" not in page                       # 오늘 목록에 없다

    st, _, d = press(ops, "/pick/discard", key="t:9003")
    assert (st, d) == (303, 1)
    page = c.get("/pick")[2]
    open_part, folded = page.split("버린 목록", 1)
    assert "가상 주제 4번 소식" not in open_part and "가상 주제 4번 소식" in folded

    st, _, d = press(ops, "/pick/restore", key="t:9003")
    assert (st, d) == (303, 1)
    assert ops.state("discarded.json")["items"] == []
    assert "가상 주제 4번 소식" in c.get("/pick")[2].split("버린 목록", 1)[0]

    st, _, d = press(ops, "/pick/keyword", text="  가상   키워드  ")
    assert (st, d) == (303, 1)
    kw = ops.state("keywords.json")["items"]
    assert kw[0]["text"] == "가상 키워드" and kw[0]["key"].startswith("k:")
    assert "직접 넣은 것" in c.get("/pick")[2]

    job = ops.state("make_queue.json")["items"][0]["job_id"]
    st, _, d = press(ops, "/pick/cancel", job_id=job)
    assert (st, d) == (303, 1)
    assert ops.state("make_queue.json")["items"][0]["state"] == "취소"

    acts = [x["action"] for x in ops.lines()]
    assert acts == ["make", "make", "later", "discard", "restore", "keyword", "cancel"]
    for line in ops.lines():
        assert set(line) <= {"at", "request_id", "action", "key", "title", "deck", "result", "job_id", "fp", "m"}

    # 내일이 되면 내일 볼 것이 맨 위
    ops.srv.cfg.clock = tomorrow_clock
    page = c.get("/pick")[2]
    first = page.index("<h2>")
    assert page[first:].startswith("<h2>오늘 다시 볼 것</h2>")
    assert page.index("가상 주제 3번 소식") < page.index("가상 주제 1번 소식")


def test_same_request_id_twice(ops):
    c = ops.client
    c.login()
    rid = os.urandom(16).hex()
    st, r1, _ = c.post("/pick/discard", {"key": "t:9005", "request_id": rid})
    snap = (ops.state("discarded.json"), len(ops.lines()))
    st2, r2, _ = c.post("/pick/discard", {"key": "t:9005", "request_id": rid})
    assert (st, st2) == (303, 303) and r1.getheader("Location") == r2.getheader("Location")
    assert (ops.state("discarded.json"), len(ops.lines())) == snap
    st3, _, _ = c.post("/pick/discard", {"key": "t:9006", "request_id": rid})
    assert st3 == 409
    assert (ops.state("discarded.json"), len(ops.lines())) == snap


def test_make_twice_one_queue_line(ops):
    c = ops.client
    c.login()
    assert press(ops, "/pick/make", key="t:9004")[0] == 303
    st, r, d = press(ops, "/pick/make", key="t:9004", deck="1")
    assert (st, d) == (303, 1) and r.getheader("Location") == "/pick?m=2"
    assert len(ops.state("make_queue.json")["items"]) == 1
    assert [x["result"] for x in ops.lines()] == ["처리", "이미 대기열에 있음"]
    page = c.get("/pick")[2]
    row = page[page.index("가상 주제 5번 소식") - 400: page.index("가상 주제 5번 소식") + 900]
    assert "대기열에 있음(1월 1일 12:00)" in row and "슈카 덱도 만들기" not in row


def test_twelve_open_rest_folded_and_unlinked(ops):
    c = ops.client
    c.login()
    page = c.get("/pick")[2]
    assert "나머지 3건" in page
    head, fold = page.split("나머지 3건", 1)
    assert head.count('<li class="row">') == 12
    assert "검색 급상승: 가상검색어" in head
    assert "주제로 묶이지 않은 검색어 1건" in fold and "따로검색어" in fold
    assert "민감: 주의: 가상 사유 갑" in page and "민감: 높음: 가상 사유 을" in page and "민감: 없음" in page
    assert "흐름 정리 전" in page and "주장 정리 전" in page and "슈카 정리 전" in page
    # 묶이지 않은 검색어도 만들기로 대기열에
    key = candidates.search_key("ko", "따로검색어")
    assert press(ops, "/pick/make", key=key)[0] == 303
    j = ops.state("make_queue.json")["items"][0]
    assert (j["kind"], j["keyword"], j["topic_id"]) == ("search", "따로검색어", None)


def test_discard_hides_same_title_under_new_key(ops, tmp_path):
    c = ops.client
    c.login()
    press(ops, "/pick/discard", key="t:9007")
    import json
    from test_ops_support import fake_now
    d = fake_now()
    d["topics"][7]["topic_id"] = 9999              # 묶음이 다시 나뉘어 번호가 바뀜
    d["topics"][7]["title"] = "가상 주제 8번  소식!"
    (ops.srv.cfg.pulse_out / "now.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert "가상 주제 8번  소식!" not in c.get("/pick")[2].split("버린 목록", 1)[0]


def test_bad_fields_and_cancel_non_waiting(ops):
    c = ops.client
    c.login()
    n = len(ops.lines())
    assert c.post("/pick/keyword", {"text": "가" * 81})[0] == 400
    assert c.post("/pick/make", {"key": "t:abc"})[0] == 400
    assert c.post("/pick/make", {"key": "t:9000", "request_id": "xyz"})[0] == 400
    assert c.post("/pick/make", {"key": "t:9000", "title": "본문의 제목"})[0] == 400
    assert c.post("/pick/cancel", {"job_id": "m20990101-0042"})[0] == 409
    assert len(ops.lines()) == n
    st, r, d = press(ops, "/pick/make", key="t:123456")          # 재료에 없는 후보
    assert (st, d) == (303, 1) and ops.lines()[-1]["result"] == "없는 후보"
    assert ops.state("make_queue.json")["items"] == []


def test_queue_set_state_locks_and_validates(desk):
    with pytest.raises(ValueError):
        queue.set_state("m20990101-0001", "없는 상태")
    from ozl.ops import store
    with store.ops_lock():
        d = queue.load()
        queue.enqueue(d, key="t:1", kind="topic", title="가상", topic_id=1, keyword=None, deck=False,
                      request_id="0" * 32, now=NOW)
        queue.save(d)
    j = queue.set_state("m20990101-0001", queue.RUNNING, now=NOW)
    assert j["state"] == "실행 중" and j["started_at"]
    j = queue.set_state("m20990101-0001", queue.DONE, issue_id="i20990101-01", now=NOW)
    assert j["issue_id"] == "i20990101-01" and j["ended_at"]
