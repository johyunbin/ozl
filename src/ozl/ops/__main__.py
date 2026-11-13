#!/usr/bin/env python3
"""OZL 운영 명령.

    python -m ozl.ops serve [--port 8765] [--host 127.0.0.1] [--allow-host <tailnet 이름>] [--preview-dir P]
    python -m ozl.ops token [--rotate] [--show]
    python -m ozl.ops runner --once [--desk-root P] [--dry-run]
    python -m ozl.ops queue list | show <job_id> | set <job_id> --state <상태> [--issue <이슈 번호>] [--note <한 줄>]

서버는 127.0.0.1(또는 ::1)에만 묶는다. tailnet 이름은 `private/ops/server.json` 의 allow_hosts 나 --allow-host 로 준다.
이 기기 밖(tailnet 이름)으로 들어온 읽기는 로그인을 거친다. 풀려면 server.json 의 open_read_hosts 에 그 이름을 적는다.
토큰은 `token --show` 만 터미널에 찍는다. 서버는 토큰을 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from . import auth, queue, runner, server, store

SERVER_JSON = server.PRIVATE_OPS / "server.json"


def load_server_json(p: pathlib.Path = SERVER_JSON) -> dict:
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return d if isinstance(d, dict) else {}


def _resolve(v: str | None) -> pathlib.Path | None:
    if not v:
        return None
    p = pathlib.Path(v)
    return p if p.is_absolute() else server.paths.ROOT / p


def _names(v) -> tuple[str, ...]:
    """server.json 의 이름 목록. 목록이 아니거나 문자열이 아닌 칸은 무시한다(빈 목록 = 모두 로그인)."""
    return tuple(x for x in v if isinstance(x, str) and x.strip()) if isinstance(v, list) else ()


def cmd_serve(a) -> int:
    if a.desk_root:
        os.environ["OZL_DESK_ROOT"] = str(pathlib.Path(a.desk_root).resolve())
    sj = load_server_json(_resolve(a.server_json) or SERVER_JSON)
    cfg = server.Config(port=a.port, host=a.host,
                        allow_hosts=tuple(a.allow_host or sj.get("allow_hosts") or ()),
                        open_read_hosts=_names(sj.get("open_read_hosts")),
                        approver=str(sj.get("approver") or "사용자"))
    pv = _resolve(a.preview_dir) or _resolve(sj.get("preview_dir"))
    if pv:
        cfg.preview_dir = pv
    if a.token_file:
        cfg.token_path = _resolve(a.token_file)
    if a.log_file:
        cfg.log_path = _resolve(a.log_file)
    if a.pulse_out:
        cfg.pulse_out = _resolve(a.pulse_out)
    try:
        httpd = server.make_server(cfg)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"시작하지 않는다: {e}", file=sys.stderr)
        return 2
    host = f"[{a.host}]" if ":" in a.host else a.host
    print(f"http://{host}:{httpd.server_address[1]}/ops", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def cmd_token(a) -> int:
    p = _resolve(a.token_file) or (server.PRIVATE_OPS / "token")
    if a.rotate or not p.exists():
        auth.write_token(p)
        print("토큰을 새로 만들었다(지난 세션은 모두 끝난다)." if a.rotate else "토큰을 만들었다.")
    try:
        tok = auth.read_token(p)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"토큰 파일: {p} (권한 600)")
    if a.show:
        print(tok)
    return 0


def _desk(a) -> None:
    if getattr(a, "desk_root", None):
        os.environ["OZL_DESK_ROOT"] = str(pathlib.Path(a.desk_root).resolve())


def cmd_runner(a) -> int:
    _desk(a)
    try:
        return runner.run_once(dry_run=a.dry_run)
    except (RuntimeError, queue.QueueBroken) as e:
        print(str(e), file=sys.stderr)
        return 2


def cmd_queue(a) -> int:
    _desk(a)
    try:
        return _cmd_queue(a)
    except (RuntimeError, queue.QueueBroken) as e:      # 깨진 대기열·별칭 루트: 스택 대신 한 문장
        print(str(e), file=sys.stderr)
        return 2


def _cmd_queue(a) -> int:
    if a.action == "list":
        with store.ops_lock():
            items = queue.load()["items"]
        for j in items:
            print(f'{j.get("job_id")}\t{j.get("state")}\t{j.get("kind")}\t{j.get("pressed_at")}\t{j.get("issue_id") or "-"}\t{j.get("title")}')
        if not items:
            print("대기열이 비었다.")
        return 0
    if not a.job_id or not queue.JOB_ID.fullmatch(a.job_id):
        print("대기열 번호(m<날짜>-<4자리>)를 준다.", file=sys.stderr)
        return 2
    if a.action == "show":
        with store.ops_lock():
            j = queue.find(queue.load(), a.job_id)
        if j is None:
            print("없는 대기열 항목이다.", file=sys.stderr)
            return 2
        print(json.dumps(j, ensure_ascii=False, indent=1))
        return 0
    if not a.state:
        print("--state 를 준다(" + ", ".join(queue.STATES) + ").", file=sys.stderr)
        return 2
    try:
        j = queue.set_state(a.job_id, a.state, issue_id=a.issue, note=a.note)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f'{j["job_id"]}: {j["state"]}' + (f' ({j["issue_id"]})' if j.get("issue_id") else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ozl.ops")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="운영 화면 서버")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1", choices=list(server.BIND_OK))
    s.add_argument("--allow-host", action="append", help="쓰기를 받을 tailnet 이름(여러 번)")
    s.add_argument("--preview-dir")
    s.add_argument("--server-json")
    s.add_argument("--token-file")
    s.add_argument("--log-file")
    s.add_argument("--pulse-out", help="now.json 이 있는 폴더(시험용)")
    s.add_argument("--desk-root", help="자료 루트(시험용 · OZL_DESK_ROOT)")
    t = sub.add_parser("token", help="로그인 토큰 만들기·바꾸기·보기")
    t.add_argument("--rotate", action="store_true")
    t.add_argument("--show", action="store_true")
    t.add_argument("--token-file")
    r = sub.add_parser("runner", help="만들기 대기열에서 한 건을 꺼내 /ozl make 를 띄운다(기본 꺼짐)")
    r.add_argument("--once", action="store_true", required=True)
    r.add_argument("--dry-run", action="store_true", help="띄울 명령만 보인다")
    r.add_argument("--desk-root")
    q = sub.add_parser("queue", help="만들기 대기열 보기·상태 바꾸기")
    q.add_argument("action", choices=["list", "show", "set"])
    q.add_argument("job_id", nargs="?")
    q.add_argument("--state", choices=list(queue.STATES))
    q.add_argument("--issue")
    q.add_argument("--note")
    q.add_argument("--desk-root")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        return cmd_serve(a)
    if a.cmd == "token":
        return cmd_token(a)
    if a.cmd == "runner":
        return cmd_runner(a)
    if a.cmd == "queue":
        return cmd_queue(a)
    return 1


if __name__ == "__main__":
    sys.exit(main())
