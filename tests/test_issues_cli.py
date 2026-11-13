"""명령 종료 코드 시험 — 시험 폴더에서 `.venv/bin/python -m ozl.issues` 를 실제로 돌린다(지어낸 예시 두 건)."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import model, paths  # noqa: E402
from test_issues_check import I1, I2, desk  # noqa: E402,F401

PY = ROOT / ".venv" / "bin" / "python"


def cli(root, *args, contact=None):
    env = {k: v for k, v in os.environ.items() if k != "OZL_REPORT_CONTACT"}
    env.update(OZL_DESK_ROOT=str(root), PYTHONPATH=str(ROOT / "src"))
    if contact is not None:
        env["OZL_REPORT_CONTACT"] = contact
    p = subprocess.run([str(PY if PY.exists() else sys.executable), "-m", "ozl.issues", *args], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def test_commands_exit_codes(desk):
    for iid in (I1, I2):
        i = model.load_issue(iid)
        i["work_state"] = "게시 대기"
        model.save_issue(i)
    assert cli(desk, "check", "--all", "--public")[0] == 1                       # 게시 대기인데 검토가 없다
    for iid in (I1, I2):
        nd = paths.issue_dir(iid) / "reviews"
        nd.mkdir(parents=True, exist_ok=True)
        (nd / "a.md").write_text("문장 대조 원문(지어낸 것)\n", encoding="utf-8")
        (nd / "b.md").write_text("해석 점검 원문(지어낸 것)\n", encoding="utf-8")
        assert cli(desk, "review", "add", iid, "--kind", "문장 대조", "--by-model", "Claude Sonnet", "--family", "anthropic",
                   "--result", "통과")[0] == 1                                     # 검토 원문 없이는 줄을 더하지 않는다
        assert cli(desk, "review", "add", iid, "--kind", "문장 대조", "--by-model", "Claude Sonnet", "--family", "anthropic",
                   "--result", "통과", "--notes-path", str(nd / "a.md"))[0] == 0
        assert cli(desk, "review", "add", iid, "--kind", "해석 점검", "--by-model", "가상 모델 G", "--family", "openai",
                   "--result", "통과", "--notes-path", str(nd / "b.md"))[0] == 0
    assert cli(desk, "check", "--all", "--public")[0] == 0
    code, out = cli(desk, "hash", I1)
    assert code == 0
    h = out.split()[-1]
    assert cli(desk, "approve", I1, "--rev", "1", "--hash", h, "--by", "편집자")[0] == 2
    assert cli(desk, "approve", I1, "--rev", "2", "--hash", h, "--by", "시험")[0] == 3
    assert cli(desk, "approve", I1, "--rev", "1", "--hash", h, "--by", "시험")[0] == 0
    code, out = cli(desk, "approve", I1, "--rev", "1", "--hash", h, "--by", "시험")
    assert code == 0 and "이미 승인됨" in out
    assert cli(desk, "status")[0] == 0
    assert cli(desk, "export", "--preview", "--out", str(desk / "pv"))[0] == 0
    assert cli(desk, "export", "--public", "--out", str(desk / "pub"))[0] == 2
    code, out = cli(desk, "export", "--public", "--out", str(desk / "pub"), contact="report@example.invalid")
    assert code == 0 and "이슈 0건" in out                                         # 시험 승인은 공개용에 나가지 않는다
    assert cli(desk, "withdraw", I1, "--by", "시험", "--reason", "시험 내림")[0] == 0
    assert cli(desk, "withdraw", I2, "--by", "시험", "--reason", "시험 내림")[0] == 2     # 발행 목록에 없다
    code, out = cli(desk, "ids", "--date", "2099-02-01", "--n", "2")
    assert code == 0 and out.split() == ["i20990201-01", "i20990201-02"]
    code, out = cli(desk, "new", "--date", "2099-02-01", "--slug", "sample-issue", "--example")
    assert code == 0 and out.strip() == "i20990201-03"
    assert cli(desk, "new", "--date", "2099-02-01", "--slug", "sample-issue")[0] == 2   # 같은 주소 이름
    assert cli(desk, "check", "i20990201-03")[0] == 0
    assert cli(desk, "check")[0] == 2
    assert cli(desk, "links")[0] == 0
    assert not (paths.real_root() / "issues" / "i20990201-03").exists()
