"""만들기 실행기와 queue 명령(설계 7절, 11절) — 실제 claude 명령은 띄우지 않는다.

`--dry-run` 은 Popen 을 가로채 0회인지 보고, 나머지는 시험 폴더의 가짜 명령(argv)만 띄운다.
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from datetime import datetime, timezone

import pytest

from test_ops_support import desk, real_untouched  # noqa: F401

from ozl.issues import paths
from ozl.ops import __main__ as M
from ozl.ops import queue, runner, store

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


def config(**kw) -> None:
    store.write_json(store.ops_file(runner.CONFIG), {"enabled": True, "timeout_min": 1, **kw})


def tree(d) -> dict:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()} if d.exists() else {}


def job(job_id: str) -> dict:
    return queue.find(queue.load(), job_id)


def test_disabled_makes_no_files(desk):
    enqueue()
    before = tree(desk)
    out: list[str] = []
    assert runner.run_once(say=out.append) == 0
    assert tree(desk) == before and "꺼져" in out[0]
    store.write_json(store.ops_file(runner.CONFIG), {"enabled": "true"})     # 참(true)이 아니면 꺼짐
    before = tree(desk)
    assert runner.run_once(say=out.append) == 0 and tree(desk) == before


def test_dry_run_shows_command_only(desk, monkeypatch, capsys):
    (jid,) = enqueue()
    calls = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: calls.append(a))
    before = tree(desk)
    assert M.main(["runner", "--once", "--desk-root", str(desk), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "-p" in out and f"'/ozl make {jid}'" in out and "--model opus" in out and "--no-session-persistence" in out
    for d in runner.DISALLOWED:
        assert d in out
    assert "--disallowedTools" in out and "CODEX_ALLOW_AUTOMATION" in out and "90분" in out
    assert calls == [] and tree(desk) == before


def test_command_shape():
    cmd = runner.build_cmd(dict(runner.DEFAULT, allowed_tools=["Read"]), "m20990101-0001")
    assert cmd[:3] == [runner.DEFAULT["claude"], "-p", "/ozl make m20990101-0001"]
    assert cmd[cmd.index("--disallowedTools") + 1:cmd.index("--allowedTools")] == runner.disallowed()
    assert cmd[-1] == "--no-session-persistence"
    with pytest.raises(ValueError):
        runner.build_cmd(runner.DEFAULT, "m1; rm -rf x")


def test_lock_held_elsewhere(desk):
    (jid,) = enqueue()
    config(argv=[PY, "-c", "print(1)"])
    d = store.ensure_dir(runner.runner_dir())
    with open(d / ".lock", "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        out: list[str] = []
        assert runner.run_once(say=out.append) == 0
    assert "다른 실행" in out[0] and job(jid)["state"] == queue.WAITING
    assert not (d / "runs.jsonl").exists()


def test_real_root_refuses_argv(desk, monkeypatch):
    monkeypatch.setattr(paths, "real_root", lambda: desk)
    assert paths.is_real_root()
    (jid,) = enqueue()
    config(argv=[PY, "-c", "print(1)"])
    assert runner.run_once(say=lambda s: None) == 2 and job(jid)["state"] == queue.WAITING


def test_exit_codes_env_and_records(desk, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_ALLOW_AUTOMATION", "1")
    a, b = enqueue(2)
    env_out = tmp_path / "env.json"
    script = ("import json, os, sys; json.dump({k: os.environ.get(k) for k in ('OZL_OPS_RUNNER', 'OZL_DESK_ROOT', "
              "'CODEX_ALLOW_AUTOMATION')}, open(sys.argv[1], 'w')); print('가짜 make', sys.argv[2])")
    config(argv=[PY, "-c", script, str(env_out), "{job_id}"])
    assert runner.run_once(say=lambda s: None) == 0
    j = job(a)
    assert j["state"] == queue.STOPPED and j["exit"] == 0 and j["note"] == "이슈 번호 없이 끝났다"
    env = json.loads(env_out.read_text())
    assert env == {"OZL_OPS_RUNNER": "1", "OZL_DESK_ROOT": str(desk.resolve()), "CODEX_ALLOW_AUTOMATION": None}
    log = paths.ROOT / j["log"] if not os.path.isabs(j["log"]) else j["log"]
    assert f"가짜 make {a}" in open(log, encoding="utf-8").read()
    config(argv=[PY, "-c", "import sys; sys.exit(3)"])
    assert runner.run_once(say=lambda s: None) == 0
    assert job(b)["state"] == queue.FAILED and job(b)["exit"] == 3
    runs = store.read_jsonl(runner.runner_dir() / "runs.jsonl")
    assert [r["job_id"] for r in runs] == [a, b] and [r["exit"] for r in runs] == [0, 3]
    assert all(set(r) == {"job_id", "started_at", "ended_at", "exit", "timed_out", "log", "dry_run"} for r in runs)
    out: list[str] = []
    assert runner.run_once(say=out.append) == 0 and "비었다" in out[0]


def test_make_state_kept_and_stale_running_aborted(desk):
    a, b = enqueue(2)
    queue.set_state(a, queue.RUNNING)                                   # 잠금을 쥔 실행기 없이 실행 중인 항목
    script = ("import subprocess, sys; subprocess.run([sys.executable, '-m', 'ozl.ops', 'queue', 'set', sys.argv[1], "
              "'--state', '멈춤', '--note', '가상 까닭'], check=True)")
    config(argv=[PY, "-c", script, "{job_id}"])
    assert runner.run_once(say=lambda s: None) == 0
    assert job(a)["state"] == queue.ABORTED
    assert job(b)["state"] == queue.STOPPED and job(b)["note"] == "가상 까닭"


def test_timeout_kills_group(desk, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "TERM_GRACE", 2.0)
    (jid,) = enqueue()
    pid_file = tmp_path / "child.pid"
    script = ("import subprocess, sys, time; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
              "open(sys.argv[1], 'w').write(str(p.pid)); time.sleep(60)")
    config(argv=[PY, "-c", script, str(pid_file)], timeout_min=0.02)
    t0 = time.monotonic()
    assert runner.run_once(say=lambda s: None) == 0
    assert time.monotonic() - t0 < 20
    j = job(jid)
    assert j["state"] == queue.TIMEOUT
    assert store.read_jsonl(runner.runner_dir() / "runs.jsonl")[0]["timed_out"] is True
    child = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("자식 프로세스가 남았다")


def test_queue_cli(desk, capsys):
    (jid,) = enqueue()
    assert M.main(["queue", "list"]) == 0 and jid in capsys.readouterr().out
    assert M.main(["queue", "show", jid]) == 0 and json.loads(capsys.readouterr().out)["title"] == "가상 주제 0"
    assert M.main(["queue", "set", jid, "--state", "실행 중"]) == 0
    assert M.main(["queue", "set", jid, "--state", "끝남", "--issue", "i20990101-01", "--note", "덱은 따로"]) == 0
    j = job(jid)
    assert (j["state"], j["issue_id"], j["note"]) == ("끝남", "i20990101-01", "덱은 따로") and j["started_at"] and j["ended_at"]
    assert M.main(["queue", "set", jid, "--state", "실행 중", "--issue", "../x"]) == 2
    assert M.main(["queue", "show", "m1"]) == 2
    with pytest.raises(SystemExit):
        M.main(["queue", "set", jid, "--state", "없는 상태"])
