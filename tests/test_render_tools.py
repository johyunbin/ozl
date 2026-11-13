"""덱 검토 묶음(ozl.render.bundle)과 완성 절차 진행 기록(ozl.render.progress) 테스트.
비공개 자료 없이 임시 폴더의 합성 카드·기록만 쓴다. 예시 문장은 전부 지어낸 것이다."""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import test_deck_visuals as V  # noqa: E402
from test_deck_visuals import desk  # noqa: E402,F401  (pytest fixture)
from ozl.render import bundle as BU  # noqa: E402
from ozl.render import progress as P  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.render.__main__ import main as render_main  # noqa: E402
from ozl.research import cards as C  # noqa: E402

CARD = V.CARD


def _card(card_id=CARD):
    """진행 기록이 지문을 계산할 수 있는 최소 카드(검사용이 아니다)."""
    return {"card_id": card_id, "date": "2099-01-02", "slot": "am", "titles": ["지어낸 감자 이야기"], "state": "채택", "history": []}


# ── 검토 묶음 ────────────────────────────────────────────────────────
def test_bundle_lists_screen_text_footnote_and_records(desk):
    c = V.machine_claim(desk, image=False)
    sp = V.spec_of([V.slide(chart=V.line_chart()), V.slide(capture=V.CID, capture_focus=c["observed"][:6], refs=["지어낸 일보"])])
    sp["source_labels"] = {V.CID: "가상 섬 통계청 보고서"}
    claims, _ = S.load_claims(BU.all_cited(sp))
    text = BU.render(sp, claims, None, "ab" * 32, "통과 · 실패 0 · 경고 0", "지어낸_사양.yaml")
    assert "sha256 abababababababab" in text and "엄격 검사: 통과" in text
    assert "[차트 line] 가상의 섬 감자 값" in text and "차트에 찍히는 수량" in text
    assert f"[원문 캡처] 기록 {V.CID.rsplit('-', 1)[-1]}" in text and "refs: 지어낸 일보" in text
    assert "각주: 출처: 가상 섬 통계청 보고서" in text
    assert f"observed: 「{c['observed']}」" in text and "등급 원문 일치" in text and "말한 쪽 가상 섬 통계청" in text
    assert "독립 재대조 에이전트에게 주지 않는다" in text


def test_bundle_all_cited_adds_chart_and_capture_records():
    sp = {"slides": [{"claim_ids": ["2099-01-02-am-01-c1"]}, {"chart": {"claims": ["2099-01-02-am-01-c2"]}},
                     {"capture": "2099-01-02-am-01-c3"}]}
    assert BU.all_cited(sp) == ["2099-01-02-am-01-c1", "2099-01-02-am-01-c2", "2099-01-02-am-01-c3"]
    assert S.cited_ids(sp) == ["2099-01-02-am-01-c1"]                 # 검사기의 인용 목록은 차트·캡처 기록을 따로 센다


def test_bundle_refuses_output_outside_private(desk, tmp_path, capsys):
    V.machine_claim(desk, image=False)
    spec = tmp_path / "spec.yaml"
    import yaml
    spec.write_text(yaml.safe_dump(V.spec_of([V.slide()]), allow_unicode=True), encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}_outside.md"         # 시험에서는 C.DESK.parent(= tmp_path)가 private 자리다
    assert render_main(["bundle", str(spec), "--out", str(outside)]) == 1
    assert "private/ 밖에는 쓰지 않는다" in capsys.readouterr().err and not outside.exists()
    out = C.DESK / "builds" / CARD / "reviews" / "b.md"
    render_main(["bundle", str(spec), "--out", str(out)])
    assert out.exists() and "# 검토 묶음" in out.read_text(encoding="utf-8")


# ── 진행 기록 ────────────────────────────────────────────────────────
def test_progress_start_mark_done_and_no_double_build(desk, tmp_path):
    C.save_yaml(C.card_path(CARD), _card())
    t0 = datetime(2099, 1, 2, 9, 0, tzinfo=P.KST)
    P.start(CARD, "세션-가", at=t0)
    with pytest.raises(ValueError, match="진행 중"):
        P.start(CARD, "세션-나", at=t0 + timedelta(hours=1))       # 만료 전에는 다른 세션이 시작하지 못한다
    P.mark(CARD, "명제", "명제 둘", at=t0 + timedelta(minutes=5))
    final = tmp_path / "final"
    final.mkdir()
    st = P.done(CARD, str(final), at=t0 + timedelta(hours=2))
    assert st["status"] == P.DONE and st["final"] == str(final) and [s["step"] for s in st["steps"]] == ["명제", "산출"]
    with pytest.raises(ValueError, match="완성본"):
        P.start(CARD, "세션-나", at=t0 + timedelta(hours=3))       # 같은 카드를 두 번 만들지 않는다
    assert P.start(CARD, "세션-나", force=True, at=t0 + timedelta(hours=3))["status"] == P.IN_PROGRESS


def test_progress_lease_expires_and_digest_change_is_reported(desk):
    C.save_yaml(C.card_path(CARD), _card())
    t0 = datetime(2099, 1, 2, 9, 0, tzinfo=P.KST)
    P.start(CARD, "세션-가", at=t0)
    P.mark(CARD, "기록", at=t0 + timedelta(minutes=1))
    card = _card()
    card["titles"] = ["바뀐 지어낸 제목"]
    C.save_yaml(C.card_path(CARD), card)
    assert "마지막 단계 뒤에 카드나 기록이 바뀌었다" in P.summary(P.load(CARD), CARD)
    later = t0 + timedelta(hours=P.LEASE_HOURS + 1)
    assert not P.lease_alive(P.load(CARD), later)
    st = P.start(CARD, "세션-나", at=later)                          # 세션이 죽어 남은 '진행 중'은 만료 뒤 다시 시작할 수 있다
    assert st["by"] == "세션-나" and st["steps"][-1]["step"] == "다시 시작"


def test_progress_rejects_unknown_step_and_bad_card_id(desk):
    C.save_yaml(C.card_path(CARD), _card())
    P.start(CARD)
    with pytest.raises(ValueError, match="단계 이름"):
        P.mark(CARD, "아무 단계")
    with pytest.raises(ValueError):
        P.state_path("../밖")
    assert P.state_path(CARD) == C.DESK / "builds" / CARD / "state.yaml"
