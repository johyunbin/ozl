"""단추 동작과 `actions.jsonl` 기록(설계 4절 "단추와 기록", 2절 규칙).

쓰는 순서: 운영 잠금 → 요청 번호 확인 → 상태 JSON 원자적 쓰기 → actions.jsonl 한 줄 → 색인 → 잠금 풀기.
제목은 본문에서 받지 않고 key 로 재료에서 다시 찾는다. 기록에는 동작 칸만 적는다(csrf·token·pre 는 칸 목록에 없다).
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from datetime import datetime

from . import auth, candidates as C, queue, store

ACTIONS_FILE = "actions.jsonl"
# t: 뒤는 옛 수집기의 숫자 주제 번호, 또는 화제 엔진의 이슈 번호(t20261114-003 꼴).
KEY_RE = r"(t:(?:[0-9]{1,12}|t[0-9]{8}-[0-9]{3,4})|q:[0-9a-f]{12}|k:[0-9a-f]{8})"
KEYWORD_MAX = 80

# 알림 번호 — 주소에는 번호만 싣는다(사용자 글을 주소에 싣지 않는다).
MSG = {
    1: "만들기 대기열에 넣었다.",
    2: "이미 대기열에 있다.",
    3: "내일 다시 보이게 했다.",
    4: "버렸다. 아래 버린 목록에서 되살릴 수 있다.",
    5: "되살렸다.",
    6: "직접 넣은 것에 더했다.",
    7: "이미 처리한 요청이다.",
    8: "그 후보를 지금 목록에서 찾지 못했다.",
    9: "대기열에서 취소했다.",
    10: "로그인했다.",
    11: "로그아웃했다.",
    14: "버린 후보다. 아래 버린 목록에서 되살린 뒤 다시 누른다.",
}
RESULT_DONE, RESULT_ALREADY, RESULT_QUEUED, RESULT_MISSING = "처리", "이미 처리", "이미 대기열에 있음", "없는 후보"
RESULT_DISCARDED = "버린 후보"


class Conflict(Exception):
    """409 — 같은 요청 번호에 다른 내용, 또는 대기가 아닌 항목 취소."""


class BadForm(Exception):
    """400 — 칸 모양이 틀림."""


@dataclass
class Outcome:
    m: int
    result: str
    job_id: str | None = None


def _need(form: dict, name: str, pattern: str | None = None) -> str:
    v = form.get(name)
    if v is None or (pattern and not re.fullmatch(pattern, v)):
        raise BadForm(name)
    return v


def parse(action: str, form: dict) -> dict:
    """요청 번호를 뺀 동작 칸들. 지문의 재료이기도 하다."""
    rid = form.get("request_id")
    if not auth.request_id_ok(rid):
        raise BadForm("request_id")
    allowed = {"request_id", "csrf"}
    if action == "make":
        f = {"action": "make", "key": _need(form, "key", KEY_RE), "deck": form.get("deck", "") == "1"}
        if form.get("deck", "") not in ("", "1"):
            raise BadForm("deck")
        allowed |= {"key", "deck"}
    elif action in ("later", "discard", "restore"):
        f = {"action": action, "key": _need(form, "key", KEY_RE)}
        allowed |= {"key"}
    elif action == "keyword":
        text = " ".join(_need(form, "text").split())
        if not 1 <= len(text) <= KEYWORD_MAX:
            raise BadForm("text")
        f = {"action": "keyword", "key": C.keyword_key(text), "text": text}
        allowed |= {"text"}
    elif action == "cancel":
        f = {"action": "cancel", "job_id": _need(form, "job_id", queue.JOB_ID.pattern)}
        allowed |= {"job_id"}
    else:
        raise BadForm("action")
    if set(form) - allowed:
        raise BadForm("extra")
    return f


def run(action: str, form: dict, *, now: datetime, out_dir: pathlib.Path, index: store.RequestIndex) -> Outcome:
    f = parse(action, form)
    rid = form["request_id"]
    fp = store.fingerprint(f)
    with store.ops_lock():
        seen = index.lookup(rid)
        if seen is not None:
            if seen[0] != fp:
                raise Conflict("same id, different content")
            return Outcome(seen[1] or 7, RESULT_ALREADY)
        out = _apply(f, rid, now, out_dir)
        rec = {"at": store.iso(now), "request_id": rid, "action": f["action"], "key": f.get("key") or out.pop("key", None),
               "title": out.pop("title", None), "deck": bool(f.get("deck", False)), "result": out["result"],
               "fp": fp, "m": out["m"]}
        if out.get("job_id"):
            rec["job_id"] = out["job_id"]
        store.append_jsonl(store.ops_file(ACTIONS_FILE), rec)
        index.remember(rid, fp, out["m"])
        return Outcome(out["m"], out["result"], out.get("job_id"))


def _apply(f: dict, rid: str, now: datetime, out_dir: pathlib.Path) -> dict:
    a = f["action"]
    st = C.load_state()
    if a == "cancel":
        d = queue.load()
        j = queue.find(d, f["job_id"])
        if j is None or j.get("state") != queue.WAITING:
            raise Conflict("not waiting")
        j["state"], j["ended_at"], j["note"] = queue.CANCELLED, store.iso(now), "운영 화면에서 취소"
        queue.save(d)
        return {"m": 9, "result": RESULT_DONE, "job_id": j["job_id"], "title": j.get("title"), "key": j.get("key")}
    if a == "keyword":
        items = st["keywords"]["items"]
        if any(i.get("key") == f["key"] for i in items):
            return {"m": 7, "result": RESULT_ALREADY, "title": f["text"]}
        items.append({"key": f["key"], "text": f["text"], "at": store.iso(now), "request_id": rid})
        store.write_json(store.ops_file("keywords.json"), st["keywords"])
        return {"m": 6, "result": RESULT_DONE, "title": f["text"]}
    key = f["key"]
    if a == "restore":
        items = st["discarded"]["items"]
        hit = [i for i in items if i.get("key") == key]
        if not hit:
            return {"m": 7, "result": RESULT_ALREADY, "title": None}
        st["discarded"]["items"] = [i for i in items if i.get("key") != key]
        store.write_json(store.ops_file("discarded.json"), st["discarded"])
        return {"m": 5, "result": RESULT_DONE, "title": hit[0].get("title")}
    if a in ("make", "later"):
        gone = st["discarded"]["items"]
        hit = next((i for i in gone if i.get("key") == key), None)
        if hit is not None:                        # 열어 둔 옛 화면에서 누른 경우. 되살리기를 거친다
            return {"m": 14, "result": RESULT_DISCARDED, "title": hit.get("title")}
    cand = C.find(key, now, out_dir, state=st)
    if cand is None:
        return {"m": 8, "result": RESULT_MISSING, "title": None}
    if a in ("make", "later"):
        nt = C.norm_title(cand.title)
        hit = next((i for i in st["discarded"]["items"] if nt and i.get("norm_title") == nt), None)
        if hit is not None:
            return {"m": 14, "result": RESULT_DISCARDED, "title": cand.title}
    if a == "make":
        d = queue.load()
        job, created = queue.enqueue(d, key=key, kind=cand.kind, title=cand.title,
                                     topic_id=cand.raw_ref.get("topic_id"), keyword=cand.raw_ref.get("keyword"),
                                     deck=f["deck"], request_id=rid, now=now)
        if not created:
            return {"m": 2, "result": RESULT_QUEUED, "job_id": job["job_id"], "title": cand.title}
        queue.save(d)
        return {"m": 1, "result": RESULT_DONE, "job_id": job["job_id"], "title": cand.title}
    if a == "later":
        items = [i for i in st["later"]["items"] if i.get("key") != key]
        items.append({"key": key, "title": cand.title, "snapshot": C.snapshot_of(cand),
                      "show_from": C.tomorrow(now), "at": store.iso(now)})
        st["later"]["items"] = items
        store.write_json(store.ops_file("later.json"), st["later"])
        return {"m": 3, "result": RESULT_DONE, "title": cand.title}
    if a == "discard":
        items = st["discarded"]["items"]
        if any(i.get("key") == key for i in items):
            return {"m": 7, "result": RESULT_ALREADY, "title": cand.title}
        items.append({"key": key, "title": cand.title, "norm_title": C.norm_title(cand.title),
                      "at": store.iso(now), "request_id": rid})
        store.write_json(store.ops_file("discarded.json"), st["discarded"])
        if any(i.get("key") == key for i in st["later"]["items"]):
            st["later"]["items"] = [i for i in st["later"]["items"] if i.get("key") != key]
            store.write_json(store.ops_file("later.json"), st["later"])
        return {"m": 4, "result": RESULT_DONE, "title": cand.title}
    raise BadForm("action")
