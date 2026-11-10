"""슬라이드 분석 모듈 회귀 테스트 — 2026-11-10 코드 리뷰(Codex 2회)에서 나온 계산 결함이 되돌아오지 않게 묶어 둔다.
비공개 자료 없이 합성 입력만 쓴다."""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from ozl.analyze import compose_aggregate as ca  # noqa: E402
from ozl.analyze import slide_layout  # noqa: E402
from ozl.analyze.font_match import iou_best  # noqa: E402
from ozl.analyze.slide_dense import build_slides, fix_split_title  # noqa: E402
from ozl.analyze.slide_timeline import frame_text  # noqa: E402


def row(t, title=None, cls="clean", body=()):
    return {"t": t, "class": cls, "title": title, "body": [{"text": b, "x": 500, "y": 200 + 60 * i, "w": 300, "h": 36} for i, b in enumerate(body)],
            "white": 0.8, "title_box": [90, 60, 800, 92] if title else None}


A, B = "올해 여름은 유난히 비가 많이 내려 우산이 잘 팔렸다", "그런데 겨울에는 눈이 거의 오지 않아 제설 장비가 남았다"  # 지어낸 문장(실제 슬라이드 문구 아님)


def test_revisit_counted_once_and_dwell_follows_screen_time():
    rows = [row(0, A), row(3, A), row(6, B), row(9, B), row(12, A), row(15, A)]
    r = build_slides("v", rows, 18, step=3)
    assert len(r["slides"]) == 2
    assert r["revisits"] == 1  # A→B→A 는 재방문 한 번
    assert [s["dwell_sec"] for s in r["slides"]] == [12, 6]  # 화면에 떠 있던 시간(A 12초 · B 6초)


def test_titleless_sample_after_revisit_stays_on_current_slide():
    rows = [row(0, A, body=["본문 한 줄 입니다"]), row(3, B, body=["다른 본문 줄 입니다"]), row(6, A, body=["본문 한 줄 입니다"]), row(9, None, body=["본문 한 줄 입니다"])]
    r = build_slides("v", rows, 12, step=3)
    assert len(r["slides"]) == 2  # 제목이 빠진 표본은 지금 화면(A)에 붙는다 — 새 장을 만들지 않는다


def test_long_slide_with_one_clean_sample_is_not_flash():
    rows = [row(0, A)] + [row(3 * i, cls="dialog") for i in range(1, 10)]
    r = build_slides("v", rows, 30, step=3)
    assert r["slides"][0]["dwell_sec"] == 30 and r["slides"][0]["flash"] is False


def test_dwell_sum_equals_samples_after_first_clean():
    rows = [row(0, cls="faded"), row(3, A), row(6, cls="dialog"), row(9, B), row(12, B), row(15, cls="faded")]
    r = build_slides("v", rows, 18, step=3)
    assert sum(s["dwell_sec"] for s in r["slides"]) == (len(rows) - 1) * 3


def test_frame_text_joins_split_title_and_keeps_width():
    meas = {"title": {"top": 60, "h": 32, "x0": 90, "x1": 900}}
    ocr = {"lines": [{"text": "시장 상황", "conf": 1.0, "x": 90, "y": 58, "w": 200, "h": 36},
                     {"text": "급락", "conf": 1.0, "x": 400, "y": 58, "w": 80, "h": 36},
                     {"text": "본문 줄", "conf": 1.0, "x": 500, "y": 200, "w": 240, "h": 36}]}
    title, body = frame_text(meas, ocr)
    assert title == "시장 상황 급락"
    assert body == [{"text": "본문 줄", "x": 500, "y": 200, "w": 240, "h": 36}]


def test_fix_split_title_moves_title_band_lines():
    r = {"title": "시장 상황", "title_box": [90, 60, 900, 92], "body": [{"text": "반등", "x": 400, "y": 58, "h": 36}, {"text": "본문", "x": 500, "y": 200, "h": 36}]}
    out = fix_split_title(r)
    assert out["title"] == "시장 상황 반등" and [b["text"] for b in out["body"]] == ["본문"]


def test_boundary_agreement_is_maximum_matching():
    a = {"_stages": [{"slide_from": 1}, {"slide_from": 3}, {"slide_from": 4}]}
    b = {"_stages": [{"slide_from": 1}, {"slide_from": 2}, {"slide_from": 3}]}
    assert ca.agreement(a, b, tol=1) == (2, 2, 2)


def _doc(n, stages, non_slide=()):
    roles = {i: {"no": i, "role": "non_slide" if i in non_slide else "quote", "source_type": "foreign_press"} for i in range(1, n + 1)}
    st = [{"stage": k, "slide_from": a, "slide_to": b} for k, a, b in stages]
    return {"video_id": "x", "_slides": [{"no": i, "title": None} for i in range(1, n + 1)], "_stages": st, "_roles": roles,
            "_real": [i for i in roles if i not in non_slide], "reversals": [], "humor_slides": [], "korea_link": {}}


def test_stage_share_sums_repeated_stage_within_video():
    d = _doc(10, [("hook", 1, 1), ("development", 2, 4), ("turn", 5, 6), ("development", 7, 9), ("closing", 10, 10)])
    agg = ca.aggregate([d])
    assert agg["st"]["development"]["share"] == [0.6]  # 3장 + 3장 = 60% (구간별 30% 가 아니다)
    assert agg["st"]["development"]["count"] == 2 and agg["st"]["development"]["videos"] == 1


def test_non_slide_excluded_consistently():
    d = _doc(10, [("hook", 1, 2), ("development", 3, 10)], non_slide=range(1, 9))
    agg = ca.aggregate([d])
    assert agg["n_slides"] == [2] and sum(agg["roles"].values()) == 2
    name, hit, n = next(x for x in ca.rule_hits([d]) if x[0].startswith("외신"))
    assert (hit, n) == (1, 1)  # 실제 슬라이드 2장이 모두 외신 → 100%


def test_load_rejects_reversed_stage_range(tmp_path, monkeypatch):
    slides, comp = tmp_path / "slides", tmp_path / "compose"
    slides.mkdir(), comp.mkdir()
    (slides / "v.json").write_text(json.dumps({"slides": [{"no": i} for i in range(1, 11)]}))
    (comp / "v.json").write_text(json.dumps({"video_id": "v", "slide_roles": [{"no": i, "role": "quote"} for i in range(1, 11)],
                                             "stages": [{"stage": "hook", "slide_from": 1, "slide_to": 12}, {"stage": "closing", "slide_from": 13, "slide_to": 10}]}))
    monkeypatch.setattr(ca, "SLIDES", slides)
    assert ca.load(comp)[0]["_valid"] is False


def test_iou_counts_ink_shifted_outside_box():
    t = np.array([[0, 0, 1], [1, 0, 0]], bool)
    r = np.array([[0, 1, 0], [1, 0, 1]], bool)
    h, w = t.shape
    best = 0.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            T, S = np.zeros((h + 4, w + 4), bool), np.zeros((h + 4, w + 4), bool)
            T[2 : 2 + h, 2 : 2 + w] = t
            S[2 + dy : 2 + dy + h, 2 + dx : 2 + dx + w] = r
            best = max(best, (T & S).sum() / (T | S).sum())
    assert iou_best(t, r, shift=1) == pytest.approx(best)


def test_layout_vertical_stack_before_left_right():
    a = np.full((680, 1152, 3), 255, np.uint8)
    a[150:420, 80:1000] = (40, 90, 160)  # 위쪽 그림
    body = [[60, 500, 340, 36], [60, 544, 340, 36]]  # 아래쪽 글 두 줄
    assert slide_layout.classify(a, None, body)["layout"] == "image_stack"


def test_publish_gate_needs_consecutive_windows():
    import publish_gate as pg

    line = "올해여름은유난히비가많이내려우산이잘팔렸다고한다"  # 지어낸 문장
    sh = {pg.h64(line[k : k + pg.N_SLIDE]) for k in range(len(line) - pg.N_SLIDE + 1)}

    class P:
        def __init__(self, text):
            self.text = text

        def read_text(self, **kw):
            return self.text

    assert pg.check_md(P(f"인용: {line}"), set(), sh)  # 한 줄을 그대로 옮기면 걸린다
    assert not pg.check_md(P(f"{line[:pg.N_SLIDE]} 그리고 한참 뒤 {line[-pg.N_SLIDE:]}"), set(), sh)  # 떨어진 14자 두 토막은 인용이 아니다


def test_publish_gate_transcript_ignores_english_names_but_catches_korean_quote():
    """전사에서 읽어 준 영문 기관명은 코퍼스에 넣지 않는다(2026-11-10 발행처 오탐) — 한국어 인용은 그대로 잡는다."""
    import publish_gate as pg

    spoken = pg.norm(  # 지어낸 방송 문장 — 영문 기관명을 그대로 읽은 대목과 한국어 설명이 섞여 있다
        "자 여기 보시면 Federal Reserve Bank of Exampletown 자료인데요 "
        "작년 겨울에는 붕어빵 가게가 골목마다 하나씩 생겼다가 봄이 되자 한꺼번에 사라졌다고 합니다"
    )
    sh = {pg.h64(w) for k in range(pg.STRIDE) for w in pg.transcript_windows(spoken[k:])}  # 모든 위치를 넣어 STRIDE 영향 제거
    assert all(pg._hangul(w) >= pg.TRANS_MIN_HANGUL for w in pg.transcript_windows(spoken))

    class P:
        def __init__(self, text):
            self.text = text

        def read_text(self, **kw):
            return self.text

    assert not pg.check_md(P("publisher: Federal Reserve Bank of Exampletown (원자료)"), sh, set())  # 영문 기관명만 겹치면 통과
    assert pg.check_md(P("인용: 작년 겨울에는 붕어빵 가게가 골목마다 하나씩 생겼다가 봄이 되자"), sh, set())  # 한국어 문장을 옮기면 걸린다


def test_publish_gate_transcript_numbers_heavy_quote_caught_at_every_phase():
    """숫자·티커가 많은 한국어 문장도 33자 이상 옮기면 STRIDE 위상과 상관없이 걸린다(독립 리뷰 반례 — 정렬 창만 보던 필터는 39자를 놓쳤다)."""
    import publish_gate as pg

    sent = "그래서 S&P500 지수가 2024년 4분기 GDP 3.2% 성장 발표 직후 NASDAQ 100 선물이 1,250포인트 올랐습니다 이건 정말 놀라운 일이죠"  # 지어낸 문장
    quote = "4년 4분기 GDP 3.2% 성장 발표 직후 NASDAQ 100 선물이 1,250포인트 올랐습니"  # 정규화 39자 — 정렬 창만 보던 필터는 phase 1 에서 놓쳤다(전수 탐색)

    class P:
        def __init__(self, text):
            self.text = text

        def read_text(self, **kw):
            return self.text

    for phase in range(pg.STRIDE):
        t = "0" * phase + pg.norm(sent)  # 앞에 글자를 덧대 STRIDE 정렬 위치를 바꾼다
        sh = {pg.h64(w) for w in pg.transcript_windows(t)}
        assert pg.check_md(P(f"인용: {quote}"), sh, set()), f"phase {phase} 에서 놓침"


def test_publish_gate_transcript_windows_include_last_window():
    import publish_gate as pg

    t = "가" * pg.STRIDE + "나" * pg.N  # 끝 창(시작 위치 = STRIDE)만 '나' 20자 — range 끝값이 빠지면 놓친다
    assert "나" * pg.N in set(pg.transcript_windows(t))
