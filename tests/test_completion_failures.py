"""완성 경로가 막혔을 때 정해진 순서로 가는지 — 끝에서 끝까지 잇는 시험(2026-11-13 · 차례 5b 4단계).
F1 원문이 열리지 않을 때: 받기 실패 → 기록은 pending 그대로 → machine_verify 거부 → 엄격 검사가 그 기록의 숫자를 받지 않는다.
F3 끊겼다 다시 돌 때: 진행 기록 명령을 시작 → 단계 표시 → 다른 세션 거부 → 만료 뒤 이어 받기 → 카드 변경 경고 → 완성 → 재시작 거부.
(F2 다른 계열 무응답은 절차서 §5 ②의 순서로 정한다 — 라이브 표면은 시험 목적으로 돌리지 않는다.)
비공개 자료 없이 임시 폴더의 합성 카드·기록만 쓴다. 예시 문장은 전부 지어낸 것이다."""
from __future__ import annotations

import pathlib
import sys
import urllib.error
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import test_deck_visuals as V  # noqa: E402
from test_deck_visuals import desk  # noqa: E402,F401  (pytest fixture)
from ozl.render import build as B  # noqa: E402
from ozl.render import progress as P  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.render.__main__ import main as render_main  # noqa: E402
from ozl.research import capture as K  # noqa: E402
from ozl.research import cards as C  # noqa: E402


# ── F1 원문이 열리지 않을 때 ─────────────────────────────────────────────
def _blocked(u, d):
    return K.fetch(u, d, opener=lambda req, t: (_ for _ in ()).throw(urllib.error.HTTPError(u, 403, "no", {}, None)))


def test_f1_unopenable_source_keeps_number_out_of_deck(desk):
    c = V.base_claim()
    got = K.capture_claim(c, desk / "captures", C.ROOT, fetcher=_blocked, shot=False)
    assert got["capture"]["ok"] is False and got["match"]["found"] is False      # 열지 못함은 예외가 아니라 결과다
    c["verification"] = {"method": "machine", **got, "author": {"by": "agent-a", "located": ""},
                         "recheck": {"by": "agent-b", "located": V.SENTENCE, "checks": {"unit": "원", "as_of": "2098년", "status": "확정",
                                                                                         "population": "가상", "speaker": "가상 섬 통계청"},
                                     "at": "2099-01-02T10:00:00+09:00"}, "verified_at": ""}
    C.save_yaml(C.claim_path(V.CID), c)
    r = C.machine_verify(V.CID)
    assert not r["ok"] and r["reasons"]
    saved = C.load_yaml(C.claim_path(V.CID))
    assert saved["status"] == "pending" and saved["human_verified"] is False   # 등급이 오르지 않는다
    assert S.acceptance_error(saved)                                           # 엄격 모드는 이 기록을 받지 않는다
    sp = V.spec_of([V.slide(body=["감자 값은 18,250이다"])])
    rep = S.check(sp, {V.CID: saved}, V.TEMPLATE, layout_fn=B.layout_problems)
    assert not rep.ok and any(V.CID in e for e in rep.errors)                  # 그 수치를 쓴 장은 통과하지 못한다 → 절차서 '막혔을 때의 순서'


# ── F3 끊겼다 다시 돌 때 ─────────────────────────────────────────────────
def _card():
    return {"card_id": V.CARD, "date": "2099-01-02", "slot": "am", "titles": ["지어낸 감자 이야기"], "state": "채택", "history": []}


def test_f3_progress_cli_crash_resume_and_no_double_build(desk, tmp_path, capsys, monkeypatch):
    C.save_yaml(C.card_path(V.CARD), _card())
    t = [datetime(2099, 1, 2, 9, 0, tzinfo=P.KST)]
    monkeypatch.setattr(P, "now", lambda: t[0])

    def run(*args):
        rc = render_main(["progress", V.CARD, *args])
        cap = capsys.readouterr()
        return rc, cap.out + cap.err

    rc, out = run("--start", "--by", "세션-가")
    assert rc == 0 and "진행 중 · 세션-가" in out
    for step in ("명제", "원문", "기록"):
        t[0] += timedelta(minutes=10)
        assert run("--mark", step, "--by", "세션-가", "--note", f"지어낸 {step} 메모")[0] == 0
    rc, out = run("--start", "--by", "세션-나")                                 # 세션-가가 살아 있는 동안
    assert rc == 1 and "진행 중" in out and "--resume" in out

    t[0] += timedelta(hours=P.LEASE_HOURS + 1)                                  # 세션-가가 죽고 기록이 만료됐다
    card = _card()
    card["titles"] = ["바뀐 지어낸 제목"]                                       # 그 사이 카드가 바뀌었다
    C.save_yaml(C.card_path(V.CARD), card)
    rc, out = run("--resume", "--by", "세션-나")
    assert rc == 0 and "마지막 단계: 기록" in out and "주의: 마지막 단계 뒤에 카드나 기록이 바뀌었다" in out
    assert "남은 단계: " + " → ".join(P.STEPS[3:]) in out                        # 재대조부터 정해진 순서로 잇는다

    assert run("--mark", "재대조")[0] == 1                                       # 이어 받은 뒤에도 이름 없이는 적지 못한다
    for step in P.STEPS[3:-1]:
        t[0] += timedelta(minutes=5)
        assert run("--mark", step, "--by", "세션-나")[0] == 0
    final = tmp_path / "final"
    final.mkdir()
    rc, out = run("--done", "--final", str(final), "--by", "세션-나")
    assert rc == 0 and "완성" in out
    st = P.load(V.CARD)
    assert [s["step"] for s in P.run_steps(st)] == list(P.STEPS) and st["by"] == "세션-나"
    rc, out = run("--start", "--by", "세션-다")                                 # 같은 카드를 두 번 만들지 않는다
    assert rc == 1 and "완성본" in out
    with pytest.raises(SystemExit) as e:                                         # 정해진 단계 이름 밖은 받지 않는다(argparse)
        render_main(["progress", V.CARD, "--mark", "아무 단계"])
    assert e.value.code == 2
