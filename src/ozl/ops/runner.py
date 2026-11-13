"""만들기 실행기 — 대기열에서 한 건을 꺼내 화면 없는 Claude Code 로 `/ozl make <job_id>` 를 띄운다(설계 7절).

기본은 꺼짐이다. 설정 `ops/runner.json` 의 enabled 가 참이 아니고 `--dry-run` 도 아니면 아무 파일도 만들지 않고 끝난다.
Codex 를 부르지 않는다: 명령의 `--disallowedTools`, 환경에서 뺀 `CODEX_ALLOW_AUTOMATION`, make 절차의 금지 줄 세 군데.
같은 `--disallowedTools` 가 승인·공개 내보내기 명령, 발행 목록·고정 사본·운영 파일 직접 쓰기, 토큰 읽기도 막는다(`disallowed()`).
이 규칙은 Claude Code 의 도구 권한 규칙이라 명령을 돌려 쓰면 빠져나갈 수 있다. 마지막 방어는 사람이 하는 승인이다.
명령 줄에는 job_id 만 넣는다(제목과 키워드는 make 가 `queue show` 로 읽는다). 시험용 `argv` 는 시험 자료 루트에서만 받는다.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import pathlib
import shlex
import signal
import subprocess
import time
from datetime import datetime
from typing import Callable

from ozl.issues import paths

from . import queue, store

CONFIG = "runner.json"
DEFAULT = {"enabled": False, "timeout_min": 90, "claude": "/Users/hyunbin/.local/bin/claude", "model": "opus",
           "permission_mode": "acceptEdits", "allowed_tools": [], "argv": None}
CODEX_RULES = ["Bash(codex*)", "Bash(*codex_smart*)", "Bash(*codex exec*)", "Bash(*/codex *)", "Bash(*mm_request*codex*)",
               "Bash(*surface*codex*)", "mcp__hyunbin-multimodel__multimodel_request"]
APPROVE_RULES = ["Bash(*ozl.issues approve*)", "Bash(*ozl.issues withdraw*)", "Bash(*export*--public*)",
                 "Bash(*ozl.ops token*)", "Bash(*private/ops*)", "Bash(*manifest.json*)", "Bash(*approval.json*)",
                 "Bash(*make_queue.json*)", "Bash(*revisions.approve*)", "Bash(*approve_unit*)"]
DISALLOWED = CODEX_RULES + APPROVE_RULES      # 자료 루트에 매이지 않는 규칙. 경로 규칙은 disallowed() 가 더한다
# make 가 쓰는 곳(issue.yaml, evidence/, captures/, reviews/)은 막지 않는다. 막는 곳만 적는다(거부 규칙이 허용보다 앞선다).
DESK_BLOCK = ("issues/manifest.json", "issues/issued_ids.json", "issues/.lock", "issues/*/revisions/**", "ops/**",
              "cards/**", "claims/**")
TERM_GRACE = 30.0          # SIGTERM 뒤 SIGKILL 까지 기다리는 초
DROP_ENV = ("CODEX_ALLOW_AUTOMATION",)


def runner_dir() -> pathlib.Path:
    return store.ops_dir() / "runner"


def load_config() -> dict:
    p = store.ops_file(CONFIG)
    cfg = dict(DEFAULT)
    if p.exists():
        d = store.read_json(p, {})
        if isinstance(d, dict):
            cfg.update(d)
    return cfg


def _abs_rule(p: pathlib.Path) -> str:
    return "/" + str(p)          # Claude Code 규칙의 절대 경로는 `//` 로 시작한다


def disallowed() -> list[str]:
    """명령의 --disallowedTools. 시험 루트든 실제 루트든 실제 자료 루트의 막는 곳도 함께 막는다."""
    rules = list(DISALLOWED)
    roots = []
    for r in (paths.desk_root().resolve(), paths.real_root().resolve()):
        if r not in roots:
            roots.append(r)
    for r in roots:
        for rel in DESK_BLOCK:
            for tool in ("Edit", "Write"):
                rules.append(f"{tool}({_abs_rule(r / rel)})")
    for rel in DESK_BLOCK:
        for tool in ("Edit", "Write"):
            rules.append(f"{tool}(private/desk/{rel})")
    ops_private = paths.ROOT / "private" / "ops"
    for tool in ("Read", "Edit", "Write"):
        rules += [f"{tool}(private/ops/**)", f"{tool}({_abs_rule(ops_private)}/**)"]
    return rules


def build_cmd(cfg: dict, job_id: str) -> list[str]:
    if not queue.JOB_ID.fullmatch(job_id):
        raise ValueError("대기열 번호 꼴이 아니다")
    if cfg.get("argv"):
        return [str(a).replace("{job_id}", job_id) for a in cfg["argv"]]
    cmd = [str(cfg["claude"]), "-p", f"/ozl make {job_id}", "--model", str(cfg.get("model") or "opus"),
           "--permission-mode", str(cfg.get("permission_mode") or "acceptEdits"), "--disallowedTools", *disallowed()]
    allowed = [str(t) for t in cfg.get("allowed_tools") or [] if str(t) not in CODEX_RULES]
    if allowed:
        cmd += ["--allowedTools", *allowed]
    return cmd + ["--no-session-persistence"]


def child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    env["OZL_OPS_RUNNER"] = "1"
    env[paths.ENV] = str(paths.desk_root().resolve())
    return env


CURRENT = "current.json"


def _current_path() -> pathlib.Path:
    return runner_dir() / CURRENT


def _previous_alive() -> dict | None:
    """앞선 실행기가 남긴 current.json 의 프로세스 그룹이 아직 살아 있으면 그 내용, 아니면 None(남은 파일은 지운다)."""
    p = _current_path()
    if not p.exists():
        return None
    try:
        cur = store.read_json(p, {})
        pgid = int(cur.get("pgid"))
    except (ValueError, TypeError, AttributeError):
        p.unlink(missing_ok=True)
        return None
    if pgid > 1 and _group_alive(pgid):
        return cur
    p.unlink(missing_ok=True)
    return None


def _oldest_waiting(d: dict) -> dict | None:
    return next((j for j in d["items"] if j.get("state") == queue.WAITING), None)


@contextlib.contextmanager
def _try_lock():
    d = store.ensure_dir(runner_dir())
    f = open(d / ".lock", "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()


def _mark_aborted(now: datetime | None) -> None:
    with store.ops_lock():
        d = queue.load()
        hit = False
        for j in d["items"]:
            if j.get("state") == queue.RUNNING:
                j["state"], j["note"] = queue.ABORTED, "실행 중이었는데 잠금을 쥔 실행기가 없었다"
                j["ended_at"] = j.get("ended_at") or store.iso(now)
                hit = True
        if hit:
            queue.save(d)


def _kill_group(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_once(*, dry_run: bool = False, say: Callable[[str], None] = print, now: datetime | None = None) -> int:
    cfg = load_config()
    if cfg.get("enabled") is not True and not dry_run:
        say("실행기가 꺼져 있다(ops/runner.json 의 enabled).")
        return 0
    if store.root_alias():
        say(store.ALIAS_MSG)
        return 2
    if cfg.get("argv") and paths.is_real_root():
        say("시험용 argv 는 시험 자료 루트에서만 받는다. 실제 자료 루트에서는 돌지 않는다.")
        return 2
    try:
        timeout = float(cfg.get("timeout_min") or DEFAULT["timeout_min"]) * 60
    except (TypeError, ValueError):
        say("timeout_min 이 숫자가 아니다.")
        return 2
    if dry_run:
        try:
            job = _oldest_waiting(queue.load())
        except queue.QueueBroken as e:
            say(str(e))
            return 2
        if job is None:
            say("대기열이 비었다.")
            return 0
        say("띄울 명령: " + shlex.join(build_cmd(cfg, job["job_id"])))
        say("환경 변수: 부모 환경에서 " + ", ".join(DROP_ENV) + " 를 빼고 OZL_OPS_RUNNER, " + paths.ENV + " 를 넣는다")
        say(f"시간 상한: {timeout / 60:g}분")
        return 0
    with _try_lock() as got:
        if not got:
            say("다른 실행이 돈다.")
            return 0
        prev = _previous_alive()
        if prev is not None:          # 앞선 실행기가 죽어도 새 세션의 자식은 돈다. 두 make 가 같은 자료 루트에 쓰지 않게
            say(f"앞선 실행이 아직 돈다({prev.get('job_id')}). 새로 띄우지 않는다.")
            return 0
        try:
            _mark_aborted(now)
            job = queue.claim(now=now)       # 고르기와 `실행 중` 으로 바꾸기를 한 잠금 안에서
        except queue.QueueBroken as e:
            say(str(e))
            return 2
        if job is None:
            say("대기열이 비었다.")
            return 0
        return _launch(cfg, job["job_id"], timeout, say)


def final_state(cur: str | None, issue_id: str | None, code: int | None, timed_out: bool,
                timeout: float) -> tuple[str, str | None]:
    """자식이 끝난 뒤의 대기열 상태. make 가 남긴 실패·멈춤·취소는 덮어쓰지 않는다. 이슈 번호 없는 `끝남` 은 `멈춤`."""
    if timed_out:
        return queue.TIMEOUT, f"시간 상한({timeout / 60:g}분)을 넘어 멈췄다"
    if cur in (queue.FAILED, queue.STOPPED, queue.CANCELLED, queue.TIMEOUT, queue.ABORTED):
        return cur, None
    if code != 0:
        return queue.FAILED, f"종료 코드 {code}"
    if cur == queue.DONE:
        return (queue.DONE, None) if issue_id else (queue.STOPPED, "이슈 번호 없이 끝났다")
    if not issue_id:
        return queue.STOPPED, "이슈 번호 없이 끝났다"
    return queue.STOPPED, "make 가 상태를 바꾸지 않고 끝났다"


def _launch(cfg: dict, job_id: str, timeout: float, say: Callable[[str], None]) -> int:
    cmd = build_cmd(cfg, job_id)
    logs = store.ensure_dir(runner_dir() / "logs")
    started = store.iso()
    log = logs / f"{job_id}_{datetime.now():%Y%m%d_%H%M%S}.log"
    rel = paths.rel_or_abs(log)
    queue.annotate(job_id, log=rel)
    timed_out, code = False, None
    with open(log, "ab") as out:
        os.chmod(log, 0o600)
        proc = subprocess.Popen(cmd, cwd=str(paths.ROOT), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True, env=child_env())
        pgid = proc.pid
        store.write_json(_current_path(), {"job_id": job_id, "pgid": pgid, "started_at": started})
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(pgid, signal.SIGTERM)
            try:
                code = proc.wait(timeout=TERM_GRACE)
            except subprocess.TimeoutExpired:
                _kill_group(pgid, signal.SIGKILL)
                code = proc.wait()
        if _group_alive(pgid):
            _kill_group(pgid, signal.SIGTERM)
            time.sleep(0.2)
            _kill_group(pgid, signal.SIGKILL)
    _current_path().unlink(missing_ok=True)
    ended = store.iso()
    with store.ops_lock():
        cur_job = queue.find(queue.load(), job_id) or {}
    state, note = final_state(cur_job.get("state"), cur_job.get("issue_id"), code, timed_out, timeout)
    queue.set_state(job_id, state, note=note, exit=code, ended_at=ended)
    store.append_jsonl(runner_dir() / "runs.jsonl", {"job_id": job_id, "started_at": started, "ended_at": ended, "exit": code,
                                                    "timed_out": timed_out, "log": rel, "dry_run": False})
    say(f"{job_id}: {state}")
    return 0
