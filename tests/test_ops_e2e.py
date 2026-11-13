"""끝에서 끝: 지어낸 이슈가 고르기부터 게시본까지 한 번 끝까지 간다(설계 11절 test_ops_e2e, 기획안 밤 6).

시험 자료 루트(임시 폴더)에서 ① 후보 [만들기] → ② 실행기가 가짜 make(시험 폴더의 작은 파이썬)를 띄워 지어낸 이슈를
게시 대기로 두고 검토 둘을 더함 → ③ 승인 화면에 그 판이 보임 → ④ 틀린 해시 409, 맞는 해시 303, 같은 요청 다시 보내도 한 줄
→ ⑤ 미리보기용 내보내기에는 실리고 공개용(시험 연락처)에는 시험 승인이라 실리지 않음 → ⑥ 실제 폴더의 발행 목록은 그대로.
실제 claude 명령은 띄우지 않는다.
"""
from __future__ import annotations

import json
import sys

import pytest

from test_ops_approve import form_for, manifest
from test_ops_support import desk, ops, real_untouched  # noqa: F401

from ozl.issues import export, model
from ozl.ops import queue, runner, store

pytestmark = pytest.mark.usefixtures("real_untouched")
I1 = "i20990101-01"

FAKE_MAKE = '''"""가짜 make — 시험용. 실제 /ozl make 대신 대기열 명령과 이슈 명령만 부른다."""
import os, pathlib, subprocess, sys
job = sys.argv[1]
assert os.environ.get("OZL_OPS_RUNNER") == "1" and "CODEX_ALLOW_AUTOMATION" not in os.environ
py = sys.executable
def run(*a):
    subprocess.run([py, "-m", *a], check=True)
run("ozl.ops", "queue", "set", job, "--state", "실행 중")
from ozl.issues import model, paths
iid = "i20990101-01"
issue = model.load_issue(iid)
issue["work_state"] = "게시 대기"
model.save_issue(issue)
d = paths.issue_dir(iid) / "reviews"
d.mkdir(parents=True, exist_ok=True)
for kind, who, fam in (("문장 대조", "Claude Sonnet", "anthropic"), ("해석 점검", "가상 모델 G", "openai")):
    f = d / f"{kind}.md"
    f.write_text(kind + " 시험용으로 지어낸 검토 원문\\n", encoding="utf-8")
    run("ozl.issues", "review", "add", iid, "--kind", kind, "--by-model", who, "--family", fam, "--result", "통과",
        "--notes-path", str(f))
run("ozl.ops", "queue", "set", job, "--state", "끝남", "--issue", iid)
print("가짜 make 끝", job)
'''


def test_pick_to_published(ops, desk, tmp_path, monkeypatch):
    c = ops.client
    c.login()
    # ① 고르기에서 [만들기]
    st, r, _ = c.post("/pick/make", {"key": "t:9000"})
    assert st == 303 and r.getheader("Location") == "/pick?m=1"
    items = ops.state("make_queue.json")["items"]
    assert len(items) == 1 and items[0]["state"] == queue.WAITING
    jid = items[0]["job_id"]
    assert [x["action"] for x in ops.lines()] == ["make"]
    # ② 실행기(가짜 명령)
    fake = tmp_path / "fake_make.py"
    fake.write_text(FAKE_MAKE, encoding="utf-8")
    store.write_json(store.ops_file(runner.CONFIG), {"enabled": True, "timeout_min": 2, "argv": [sys.executable, str(fake), "{job_id}"]})
    said: list[str] = []
    assert runner.run_once(say=said.append) == 0
    j = queue.find(queue.load(), jid)
    assert (j["state"], j["issue_id"], j["exit"]) == (queue.DONE, I1, 0), (j, said)
    issue = model.load_issue(I1)
    assert issue["work_state"] == "게시 대기" and len(issue["reviews"]) == 2
    runs = store.read_jsonl(store.ops_dir() / "runner" / "runs.jsonl")
    assert len(runs) == 1 and runs[0]["exit"] == 0 and runs[0]["timed_out"] is False
    st, _, text = c.get("/pick")
    assert "끝남" in text
    # ③ 승인 화면에 그 판
    st, _, text = c.get("/approve")
    assert st == 200 and issue["titles"]["chosen"] in text
    f = form_for(text, I1)
    # ④ 틀린 해시 409 → 맞는 해시 303 → 같은 요청 다시
    bad = dict(f, hash=("0" if f["hash"][0] != "0" else "1") + f["hash"][1:], request_id="cd" * 16)
    assert c.post("/approve", bad)[0] == 409 and manifest()["entries"] == []
    st, r, _ = c.post("/approve", f)
    assert st == 303
    st, _, text = c.get(r.getheader("Location"))
    assert st == 200 and "승인했다" in text
    assert len(manifest()["entries"]) == 1
    snap = (manifest(), ops.lines("approvals.jsonl"), ops.lines())
    assert c.post("/approve", f)[0] == 303
    assert (manifest(), ops.lines("approvals.jsonl"), ops.lines()) == snap
    assert [x["http"] for x in snap[1]] == [409, 303]
    # ⑤ 공개용에는 시험 승인이 실리지 않고, 미리보기용에는 실린다
    monkeypatch.setenv(export.CONTACT_ENV, "test-contact@example.invalid")
    pub = export.export("public", desk / "out_pub")
    assert pub["counts"]["issues"] == 0, pub
    ids = [r["id"] for r in json.loads((desk / "out_pub" / "index.json").read_text())["issues"]]
    assert I1 not in ids
    prev = export.export("preview", desk / "out_prev")
    assert prev["code"] in (0, 4), prev
    ids = [r["id"] for r in json.loads((desk / "out_prev" / "index.json").read_text())["issues"]]
    assert I1 in ids
    assert json.loads((desk / "out_prev" / "meta.json").read_text())["test"] is True
    # ⑥ 실제 폴더 지문은 real_untouched 가 모듈 끝에서 본다
