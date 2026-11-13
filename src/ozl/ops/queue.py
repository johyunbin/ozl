"""만들기 대기열 `ops/make_queue.json`(설계 7절).

쓰는 함수는 부르는 쪽이 운영 잠금(`store.ops_lock`)을 쥔 채로 부른다. 잠금을 직접 거는 것은 `set_state` 하나뿐이다
(명령 `queue set` 과 실행기가 서버 밖에서 부르는 입구).
"""
from __future__ import annotations

import re
from datetime import datetime

from . import store

FILE = "make_queue.json"
EMPTY = {"schema": 1, "items": []}
WAITING, RUNNING, DONE, STOPPED, FAILED, TIMEOUT, ABORTED, CANCELLED = (
    "대기", "실행 중", "끝남", "멈춤", "실패", "시간 초과", "중단됨", "취소")
STATES = (WAITING, RUNNING, DONE, STOPPED, FAILED, TIMEOUT, ABORTED, CANCELLED)
ACTIVE = (WAITING, RUNNING)
JOB_ID = re.compile(r"m[0-9]{8}-[0-9]{4}")          # \d 는 유니코드 숫자도 받으므로 ASCII 만 쓴다
ISSUE_ID = re.compile(r"i[0-9]{8}-[0-9]{2}")
TOPIC_ID = re.compile(r"t[0-9]{8}-[0-9]{3,4}")    # 화제 엔진의 이슈 번호. 옛 수집기의 주제 번호(정수)도 받는다
BROKEN_MSG = "대기열 파일이 깨졌다 — private/desk/ops/make_queue.json 확인"


class QueueBroken(ValueError):
    """대기열 파일을 읽지 못함. 문장은 BROKEN_MSG 하나(파일은 덮어쓰지 않는다)."""

    def __init__(self) -> None:
        super().__init__(BROKEN_MSG)


def load() -> dict:
    """깨진 파일은 QueueBroken. 줄 가운데 사전(dict)이 아닌 것은 버리고 읽는다."""
    try:
        d = store.read_json(store.ops_file(FILE), EMPTY)
    except (ValueError, UnicodeDecodeError) as e:
        raise QueueBroken() from e
    if not isinstance(d, dict) or not isinstance(d.get("items", []), list):
        raise QueueBroken()
    d["items"] = [j for j in d.get("items", []) if isinstance(j, dict)]
    return d


def save(d: dict) -> None:
    store.write_json(store.ops_file(FILE), d)


def active_for_key(d: dict, key: str) -> dict | None:
    return next((j for j in d["items"] if j.get("key") == key and j.get("state") in ACTIVE), None)


def next_job_id(d: dict, now: datetime) -> str:
    day = store.now_kst(now).strftime("%Y%m%d")
    n = 0
    for j in d["items"]:
        m = re.fullmatch(r"m([0-9]{8})-([0-9]{4})", j.get("job_id", ""))
        if m and m.group(1) == day:
            n = max(n, int(m.group(2)))
    return f"m{day}-{n + 1:04d}"


def enqueue(d: dict, *, key: str, kind: str, title: str, topic_id, keyword, deck: bool, request_id: str,
            now: datetime) -> tuple[dict, bool]:
    """같은 key 가 대기·실행 중이면 (그 항목, False). 아니면 새 항목을 더하고 (항목, True). 저장은 부르는 쪽이."""
    if not (topic_id is None or (isinstance(topic_id, int) and not isinstance(topic_id, bool))
            or (isinstance(topic_id, str) and TOPIC_ID.fullmatch(topic_id))):
        raise ValueError("주제 번호 꼴이 아니다")
    cur = active_for_key(d, key)
    if cur is not None:
        return cur, False
    job = {"job_id": next_job_id(d, now), "key": key, "kind": kind, "title": title, "topic_id": topic_id,
           "keyword": keyword, "deck": bool(deck), "pressed_at": store.iso(now), "request_id": request_id,
           "state": WAITING, "started_at": None, "ended_at": None, "exit": None, "log": None, "issue_id": None, "note": ""}
    d["items"].append(job)
    return job, True


def find(d: dict, job_id: str) -> dict | None:
    return next((j for j in d["items"] if j.get("job_id") == job_id), None)


def claim(job_id: str | None = None, *, now: datetime | None = None) -> dict | None:
    """운영 잠금 안에서 `대기` 인 항목 하나를 골라 바로 `실행 중` 으로 바꾼다(고르기와 바꾸기를 한 번에).

    job_id 를 주면 그 항목이 아직 `대기` 일 때만. 아니면 가장 오래된 `대기`. 없으면 None.
    """
    with store.ops_lock():
        d = load()
        if job_id is not None:
            j = find(d, job_id)
            j = j if j is not None and j.get("state") == WAITING else None
        else:
            j = next((x for x in d["items"] if x.get("state") == WAITING), None)
        if j is None:
            return None
        j["state"], j["started_at"] = RUNNING, store.iso(now)
        save(d)
        return dict(j)


def annotate(job_id: str, **extra) -> None:
    """상태는 그대로 두고 log 같은 칸만 적는다."""
    with store.ops_lock():
        d = load()
        j = find(d, job_id)
        if j is None:
            return
        for k, v in extra.items():
            if k in ("log",):
                j[k] = v
        save(d)


def set_state(job_id: str, state: str, *, issue_id: str | None = None, note: str | None = None,
              now: datetime | None = None, **extra) -> dict:
    """운영 잠금을 걸고 한 항목의 상태를 바꾼다. 없는 항목·없는 상태는 ValueError."""
    if state not in STATES:
        raise ValueError("없는 상태")
    if issue_id is not None and not ISSUE_ID.fullmatch(issue_id):
        raise ValueError("이슈 번호 꼴이 아니다")
    with store.ops_lock():
        d = load()
        j = find(d, job_id)
        if j is None:
            raise ValueError("없는 대기열 항목")
        j["state"] = state
        if state == RUNNING and not j.get("started_at"):
            j["started_at"] = store.iso(now)
        if state not in ACTIVE and not j.get("ended_at"):
            j["ended_at"] = store.iso(now)
        if issue_id is not None:
            j["issue_id"] = issue_id
        if note is not None:
            j["note"] = note
        for k, v in extra.items():
            if k in ("exit", "log", "started_at", "ended_at"):
                j[k] = v
        save(d)
        return dict(j)
