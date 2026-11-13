"""보안 검토 지적을 막는 시험 — 별칭 자료 루트, 실행기 권한 규칙, 세션 무효화, 느린 본문, 유니코드 숫자,
실행기 상태, 고아 자식, 동시 요청, 권한 비트, 깨진 대기열, 버린 후보.

쓰기는 모두 임시 폴더(시험 자료 루트)에만 한다. 실제 자료 루트는 stat 만 하고 `real_untouched` 가 앞뒤를 비교한다.
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import pytest

from test_ops_support import REAL_DESK, desk, ops, real_untouched, start  # noqa: F401

from ozl.issues import paths
from ozl.issues import reviews as RV
from ozl.ops import __main__ as M
from ozl.ops import approvals, auth, queue, runner, server, store

pytestmark = pytest.mark.usefixtures("real_untouched")
NOW = datetime(2099, 1, 1, 3, 0, tzinfo=timezone.utc)
PY = sys.executable


def enqueue(n: int = 1) -> list[str]:
    ids = []
    with store.ops_lock():
        d = queue.load()
        for i in range(n):
            job, _ = queue.enqueue(d, key=f"t:{9000 + i}", kind="topic", title=f"가상 주제 {i}", topic_id=9000 + i,
                                   keyword=None, deck=False, request_id=f"{i:032x}", now=NOW)
            ids.append(job["job_id"])
        queue.save(d)
    return ids


def job(job_id: str) -> dict:
    return queue.find(queue.load(), job_id)


def config(**kw) -> None:
    store.write_json(store.ops_file(runner.CONFIG), {"enabled": True, "timeout_min": 1, **kw})


def raw(port: int, head: bytes, body: bytes = b"", wait: float = 8.0) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=wait)
    try:
        s.sendall(head + body)
        out = b""
        while True:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                return out + b"<<timeout>>"
            if not chunk:
                return out
            out += chunk
    finally:
        s.close()


# ---------- 실제 자료 루트의 별칭 ----------

def _case_insensitive() -> bool:
    p = REAL_DESK.parent / "DESK"
    return REAL_DESK.exists() and p.exists()


@pytest.mark.skipif(not _case_insensitive(), reason="대소문자를 가리는 파일 시스템")
def test_case_alias_of_real_root_refused(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV, str(REAL_DESK.parent / "DESK"))
    assert store.root_alias()                      # paths.is_real_root() 는 여기서 거짓이다(issues 쪽 보고 대상)
    with pytest.raises(RuntimeError):
        with store.ops_lock():
            pass
    with pytest.raises(RuntimeError):
        store.require_safe_root()
    assert runner.run_once(dry_run=True, say=lambda s: None) == 2
    tok = tmp_path / "token"
    auth.write_token(tok)
    with pytest.raises(RuntimeError):
        server.make_server(server.Config(port=0, token_path=tok, log_path=tmp_path / "a.log", preview_dir=None))
    with pytest.raises(RuntimeError):
        approvals.handle({"request_id": "0" * 32, "kind": "issue", "target": "i20990101-01", "rev": "1",
                          "hash": "0" * 64}, now=NOW, index=store.RequestIndex(), approver="사용자")
    assert M.main(["queue", "list"]) == 2


def test_symlink_alias_refused(monkeypatch, tmp_path):
    real = tmp_path / "real"
    (real / "issues").mkdir(parents=True)
    monkeypatch.setattr(paths, "real_root", lambda: real)
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv(paths.ENV, str(link / "."))
    monkeypatch.setattr(paths, "is_real_root", lambda: False)     # 문자열 비교가 놓친 경우를 흉내 낸다
    assert store.root_alias()
    other = tmp_path / "other"
    other.mkdir()
    (other / "issues").symlink_to(real / "issues")               # issues 만 실제를 가리키는 경우
    monkeypatch.setenv(paths.ENV, str(other))
    assert store.root_alias()
    with pytest.raises(RuntimeError):
        with store.ops_lock():
            pass
    assert not (other / "ops").exists() and not (real / "ops").exists()


def test_plain_test_root_is_not_alias(desk):
    assert not store.root_alias()


def test_issues_private_helpers_exist():
    # approvals.missing_reviews 가 issues.reviews 의 비공개 함수에 기댄다. 이름이 바뀌면 /approve 가 500 이 된다
    assert callable(getattr(RV, "_notes_ok", None)) and callable(getattr(RV, "_same", None))


# ---------- 실행기 권한 규칙 ----------

def test_runner_denies_approve_token_codex(desk):
    cfg = dict(runner.DEFAULT, allowed_tools=["Bash(.venv/bin/python -m ozl.*)", "mcp__hyunbin-multimodel__multimodel_request"])
    cmd = runner.build_cmd(cfg, "m20990101-0001")
    deny = cmd[cmd.index("--disallowedTools") + 1:cmd.index("--allowedTools")]
    assert deny and deny == runner.disallowed()
    must = ["Bash(*ozl.issues approve*)", "Bash(*ozl.issues withdraw*)", "Bash(*export*--public*)", "Bash(*ozl.ops token*)",
            "Bash(*mm_request*codex*)", "Bash(*surface*codex*)", "Bash(codex*)", "mcp__hyunbin-multimodel__multimodel_request",
            "Read(private/ops/**)", "Edit(private/ops/**)", "Write(private/ops/**)",
            "Edit(private/desk/issues/manifest.json)", "Write(private/desk/issues/manifest.json)",
            "Edit(private/desk/issues/*/revisions/**)", "Edit(private/desk/ops/**)",
            f"Edit(/{paths.real_root().resolve()}/issues/manifest.json)", f"Edit(/{desk.resolve()}/issues/manifest.json)",
            f"Read(/{paths.ROOT / 'private' / 'ops'}/**)"]
    for r in must:
        assert r in deny, r
    allowed = cmd[cmd.index("--allowedTools") + 1:-1]
    assert allowed == ["Bash(.venv/bin/python -m ozl.*)"]                # codex 를 부를 수 있는 MCP 는 허용 목록에서 뺀다
    assert not any("issue.yaml" in r or "evidence" in r or "reviews" in r for r in deny)   # make 가 쓰는 곳은 막지 않는다


def test_child_gets_resolved_desk_root(desk, tmp_path, monkeypatch):
    link = tmp_path / "desk_link"
    link.symlink_to(desk)
    monkeypatch.setenv(paths.ENV, str(link))
    (jid,) = enqueue()
    out = tmp_path / "env.json"
    config(argv=[PY, "-c", "import json, os, sys; json.dump(os.environ.get('OZL_DESK_ROOT'), open(sys.argv[1], 'w'))",
                 str(out), "{job_id}"])
    assert runner.run_once(say=lambda s: None) == 0
    assert json.loads(out.read_text()) == str(desk.resolve()) != str(link)


# ---------- 실행기 상태 ----------

@pytest.mark.parametrize("cur,issue,code,want", [
    (queue.DONE, "i20990101-01", 0, (queue.DONE, None)),
    (queue.DONE, None, 0, (queue.STOPPED, "이슈 번호 없이 끝났다")),
    (queue.RUNNING, None, 0, (queue.STOPPED, "이슈 번호 없이 끝났다")),
    (queue.RUNNING, "i20990101-01", 0, (queue.STOPPED, "make 가 상태를 바꾸지 않고 끝났다")),
    (queue.FAILED, None, 0, (queue.FAILED, None)),
    (queue.STOPPED, None, 0, (queue.STOPPED, None)),
    (queue.CANCELLED, None, 0, (queue.CANCELLED, None)),
    (queue.RUNNING, None, 3, (queue.FAILED, "종료 코드 3")),
])
def test_final_state(cur, issue, code, want):
    assert runner.final_state(cur, issue, code, False, 60) == want
    assert runner.final_state(cur, issue, code, True, 60)[0] == queue.TIMEOUT


def test_failed_by_make_not_overwritten(desk):
    (jid,) = enqueue()
    script = ("import subprocess, sys; subprocess.run([sys.executable, '-m', 'ozl.ops', 'queue', 'set', sys.argv[1], "
              "'--state', '실패', '--note', '가상 실패'], check=True)")
    config(argv=[PY, "-c", script, "{job_id}"])
    assert runner.run_once(say=lambda s: None) == 0
    assert job(jid)["state"] == queue.FAILED and job(jid)["note"] == "가상 실패"


def test_claim_is_atomic_and_respects_cancel(desk, monkeypatch):
    a, b = enqueue(2)
    queue.set_state(a, queue.CANCELLED)
    assert queue.claim(a) is None and job(a)["state"] == queue.CANCELLED
    calls = []
    real_set = queue.set_state
    monkeypatch.setattr(queue, "set_state", lambda jid, st, **kw: (calls.append(st), real_set(jid, st, **kw))[1])
    config(argv=[PY, "-c", "pass", "{job_id}"])
    assert runner.run_once(say=lambda s: None) == 0
    assert queue.RUNNING not in calls                       # 실행 중으로 바꾸는 일은 claim 이 잠금 안에서만 한다
    assert job(a)["state"] == queue.CANCELLED and job(b)["state"] == queue.STOPPED


def test_previous_child_alive_blocks_new_launch(desk):
    a, b = enqueue(2)
    queue.set_state(a, queue.RUNNING)
    p = subprocess.Popen([PY, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        store.write_json(runner.runner_dir() / runner.CURRENT, {"job_id": a, "pgid": p.pid, "started_at": "가상"})
        config(argv=[PY, "-c", "pass", "{job_id}"])
        out: list[str] = []
        assert runner.run_once(say=out.append) == 0
        assert "아직 돈다" in out[0] and job(a)["state"] == queue.RUNNING and job(b)["state"] == queue.WAITING
    finally:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
    assert runner.run_once(say=lambda s: None) == 0
    assert job(a)["state"] == queue.ABORTED and job(b)["state"] == queue.STOPPED
    assert not (runner.runner_dir() / runner.CURRENT).exists()


def test_concurrent_set_state(desk):
    ids = enqueue(20)
    ts = [threading.Thread(target=queue.set_state, args=(j, queue.DONE)) for j in ids]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(job(j)["state"] == queue.DONE for j in ids)


# ---------- 깨진 대기열 ----------

def test_broken_queue_one_sentence(ops, capsys):
    p = store.ops_file(queue.FILE)
    store.ensure_dir(p.parent)
    p.write_text("{깨짐", encoding="utf-8")
    st, _, text = ops.client.get("/ops")
    assert st == 503 and queue.BROKEN_MSG in text
    assert M.main(["queue", "list"]) == 2 and queue.BROKEN_MSG in capsys.readouterr().err
    assert runner.run_once(dry_run=True, say=lambda s: None) == 2
    assert p.read_text(encoding="utf-8") == "{깨짐"
    p.write_text(json.dumps({"schema": 1, "items": ["x", None]}), encoding="utf-8")
    assert ops.client.get("/pick")[0] == 200 and ops.client.get("/ops")[0] == 200
    assert runner.run_once(dry_run=True, say=lambda s: None) == 0


# ---------- 서버: 세션, 시간 제한, 길이, 동시 요청, 권한 ----------

def test_logout_revokes_cookie_server_side(ops):
    c = ops.client
    c.login()
    saved_cookie, saved_csrf = c.cookie, c.csrf
    assert c.post("/pick/later", {"key": "t:9000"})[0] == 303
    assert c.post("/logout", {})[0] == 303
    c.cookie, c.csrf = saved_cookie, saved_csrf                 # 다른 곳이 받아 간 같은 쿠키를 다시 쓴다
    assert c.post("/pick/later", {"key": "t:9001"})[0] == 401
    key = auth.session_key(c.token)
    forged = auth.make_session(key)                             # 서명은 맞지만 서버가 발급하지 않은 세션
    rnd = forged.split(".")[1]
    st, _, _ = c.req("POST", "/pick/later", form={"key": "t:9001", "request_id": os.urandom(16).hex(),
                                                  "csrf": auth.csrf_for(key, rnd)}, headers={"Cookie": f"ozl_ops={forged}"})
    assert st == 401
    assert auth.check_session(key, auth.make_session(key, time.time() - 13 * 3600)) is None


def test_slow_body_is_cut(ops, monkeypatch):
    monkeypatch.setattr(server.Handler, "timeout", 1)
    c = ops.client
    c.login()
    head = (f"POST /pick/keyword HTTP/1.1\r\nHost: {c.host}\r\nOrigin: http://{c.host}\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\nContent-Length: 8000\r\n\r\n").encode()
    t0 = time.monotonic()
    out = raw(ops.port, head, b"ab", wait=8)
    assert b"<<timeout>>" not in out and time.monotonic() - t0 < 6
    assert c.get("/ops")[0] == 200
    assert ops.srv.request_queue_size >= 64 and server.Handler.timeout == 1


def test_unicode_digits_are_411_not_500(ops):
    c = ops.client
    c.login()
    head = (f"POST /pick/keyword HTTP/1.1\r\nHost: {c.host}\r\nOrigin: http://{c.host}\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\nContent-Length: ").encode() + b"\xb2\r\n\r\n"
    out = raw(ops.port, head)
    assert out.startswith(b"HTTP/1.0 411") or out.startswith(b"HTTP/1.1 411"), out[:40]
    assert ops.srv.last_error is None
    key = auth.session_key(c.token)
    assert auth.check_session(key, "²." + "0" * 32 + "." + "0" * 64) is None
    assert c.get("/ops?m=%C2%B2")[0] == 200 and ops.srv.last_error is None
    assert not queue.JOB_ID.fullmatch("m١٢345678-0001")


def test_twenty_concurrent_posts(ops):
    c = ops.client
    c.login()
    res: list[int] = []

    def one(i: int) -> None:
        res.append(c.post("/pick/keyword", {"text": f"가상 동시 {i}"})[0])

    ts = [threading.Thread(target=one, args=(i,)) for i in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert res == [303] * 20
    lines = ops.lines()
    assert len(lines) == 20 and len({x["request_id"] for x in lines}) == 20
    assert len(ops.state("keywords.json")["items"]) == 20


def test_dir_and_file_modes(ops):
    c = ops.client
    c.login()
    assert c.post("/pick/make", {"key": "t:9000"})[0] == 303
    assert stat.S_IMODE(ops.ops.stat().st_mode) == 0o700
    for name in ("make_queue.json", "actions.jsonl"):
        assert stat.S_IMODE((ops.ops / name).stat().st_mode) == 0o600, name


def test_duplicate_unrelated_field_is_400(ops):
    c = ops.client
    c.login()
    st, _, _ = c.req("POST", "/pick/make", body=f"key=t%3A9000&deck=1&deck=1&request_id={os.urandom(16).hex()}&csrf={c.csrf}")
    assert st == 400 and not ops.state("make_queue.json")["items"]


def test_running_cancel_is_409(ops):
    c = ops.client
    c.login()
    assert c.post("/pick/make", {"key": "t:9000"})[0] == 303
    jid = ops.state("make_queue.json")["items"][0]["job_id"]
    queue.set_state(jid, queue.RUNNING)
    assert c.post("/pick/cancel", {"job_id": jid})[0] == 409
    assert ops.state("make_queue.json")["items"][0]["state"] == queue.RUNNING


def test_discarded_candidate_cannot_be_made(ops):
    c = ops.client
    c.login()
    assert c.post("/pick/discard", {"key": "t:9001"})[0] == 303
    for path in ("/pick/make", "/pick/later"):
        st, r, _ = c.post(path, {"key": "t:9001"})
        assert st == 303 and r.getheader("Location") == "/pick?m=14", path
    assert not ops.state("make_queue.json")["items"] and not ops.state("later.json")["items"]
    assert c.post("/pick/restore", {"key": "t:9001"})[0] == 303
    assert c.post("/pick/make", {"key": "t:9001"})[2] is not None
    assert len(ops.state("make_queue.json")["items"]) == 1


def test_real_manifest_unchanged_marker():
    # real_untouched 가 모듈 앞뒤로 발행 목록 해시·승인 수·ops 폴더 유무를 비교한다. 여기서는 그 고정점이 읽히는지만 본다
    man = REAL_DESK / "issues" / "manifest.json"
    assert not man.exists() or json.loads(man.read_text(encoding="utf-8")) is not None
    assert isinstance(pathlib.Path(paths.real_root()), pathlib.Path)
