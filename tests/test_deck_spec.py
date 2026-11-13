"""덱 사양 검사·초안 생성(src/ozl/render/spec.py · build.py) 회귀 테스트.
비공개 자료 없이 합성 입력만 쓴다. 예시 문장과 숫자는 전부 지어낸 것이다(실제 카드·방송 문구 아님)."""
from __future__ import annotations

import copy
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.render import build as B  # noqa: E402
from ozl.render import spec as S  # noqa: E402

TEMPLATE = S.load_template()
CID = "2099-01-02-am-01-c1"
CID2 = "2099-01-02-am-01-c2"


def claim(cid=CID, text="가상의 섬 감자 수확량은 2098년 1,234톤으로 전년보다 12% 늘었다.", observed="1,234 t · up 12%", hv=True):
    return {"claim_id": cid, "card_id": "2099-01-02-am-01", "text": text, "observed": observed, "human_verified": hv,
            "source": {"url": "https://example.org/potato.pdf", "publisher": "가상 섬 통계청", "tier": "T1"},
            "checks": {"base_period": "2098", "primary_doc_locator": "표 3"}}


CLAIMS = {CID: claim(), CID2: claim(CID2, "가상의 섬 당근 수확량은 3,300만 개다.", "33 million carrots")}


def slide(**kw):
    base = {"stage": "배경", "kind": "image_text", "title": "감자 이야기", "body": ["감자는 땅속에서 자란다"], "seconds": 20}
    base.update(kw)
    return base


def spec_of(slides):
    stages = ["여는 장", "배경", "반전", "전개", "반전", "근거 수치", "비교", "반전", "전개", "닫는 장"]
    out = [slide(stage=s, kind="closing" if s == "닫는 장" else "image_text") for s in stages]
    return {"card_id": "2099-01-02-am-01", "slides": out[:2] + slides + out[2:]}


# ── 숫자 규칙 세 가지 ──────────────────────────────────────────────────
def test_number_without_claim_ids_fails():
    errs = S.number_errors(slide(body=["수확량이 1,234톤이다"]), CLAIMS)
    assert any("claim_ids 가 없다" in e for e in errs)


def test_cited_claim_not_human_verified_fails():
    claims = {CID: claim(hv=False)}
    errs = S.number_errors(slide(body=["수확량이 1,234톤이다"], claim_ids=[CID]), claims)
    assert any("사람 대조 전" in e for e in errs)
    errs = S.number_errors(slide(body=["숫자 없는 줄"], claim_ids=["2099-01-02-am-01-c9"]), claims)
    assert any("찾지 못했다" in e for e in errs)


def test_numbers_in_title_table_and_number_slide_are_checked():
    sl = {"stage": "근거 수치", "kind": "compare_table", "title": "표", "table": {"header": ["항목", "값"], "rows": [["감자", "9,999톤"]]}, "claim_ids": [CID]}
    assert S.number_errors(sl, CLAIMS)
    sl = {"stage": "근거 수치", "kind": "number", "title": "감자", "number": {"value": "1,234톤", "label": "전년보다 13% 증가"}, "claim_ids": [CID]}
    assert any("13%" in e for e in S.number_errors(sl, CLAIMS))
    sl = slide(image={"what": "감자밭 사진", "source": "가상 섬 농업청 보도자료실"})
    assert S.number_errors(sl, CLAIMS) == []


# ── 어절 줄바꿈 ──────────────────────────────────────────────────────────
def _fake_measure(text, size, bold=False):
    return len(text) * size * (1.1 if bold else 1.0)


@pytest.mark.parametrize("width", [60, 100, 140, 300])
def test_wrap_never_splits_a_word(width):
    text = "바닷가 작은 마을의 감자밭은 해마다 조금씩 넓어졌다 그리고 올해는 기록적인 수확을 했다"
    lines = S.wrap(text, width, 10, measure_fn=_fake_measure)
    words = text.split()
    got = [text[a:b] for a, b in lines]
    assert " ".join(got) == text
    assert sum(len(g.split()) for g in got) == len(words)  # 어느 낱말도 두 줄로 쪼개지지 않았다
    for g in got:
        assert _fake_measure(g, 10) <= width or len(g.split()) == 1


def test_wrap_keeps_long_word_whole_and_layout_reports_overflow():
    lines = S.wrap("가나다라마바사아자차카타파하", 30, 10, measure_fn=_fake_measure)
    assert lines == [(0, 14)]
    sl = slide(body=["줄 하나에 들어갈 만큼만 쓴 문장"] * 12)
    assert any("줄 넘침" in e for e in B.layout_problems(sl))
    sl = slide(title="아주 긴 제목 " * 12)
    assert any("제목" in e for e in B.layout_problems(sl))


# ── 단계 순서 ────────────────────────────────────────────────────────────
def test_stage_order_follows_template():
    ok = ["여는 장", "배경", "반전", "전개", "근거 수치", "반전", "비교", "전개", "반전", "시사점", "닫는 장"]
    errs, _ = S.stage_errors(ok, TEMPLATE)
    assert errs == []
    bad = ["여는 장", "비교", "배경", "전개", "닫는 장"]  # 비교가 배경보다 앞
    errs, _ = S.stage_errors(bad, TEMPLATE)
    assert any("배경" in e and "비교" in e for e in errs)
    errs, _ = S.stage_errors(["배경", "전개", "닫는 장"], TEMPLATE)
    assert any("첫 단계" in e for e in errs)
    errs, _ = S.stage_errors(["여는 장", "전개", "닫는 장", "전개"], TEMPLATE)
    assert errs
    errs, _ = S.stage_errors(["여는 장", "없는 단계", "닫는 장"], TEMPLATE)
    assert any("어휘" in e for e in errs)


def test_check_whole_spec_fails_on_stage_and_table_shape():
    sp = spec_of([slide(stage="비교")])  # 배경 다음에 비교 → 뒤에 오는 근거 수치가 거꾸로
    rep = S.check(sp, CLAIMS, TEMPLATE)
    assert not rep.ok and any("거스른다" in e for e in rep.errors)
    sp = spec_of([{"stage": "배경", "kind": "compare_table", "title": "표", "seconds": 10,
                   "table": {"header": ["가", "나"], "rows": [["하나", "둘", "셋"]]}}])
    rep = S.check(sp, CLAIMS, TEMPLATE)
    assert any("칸 수" in e for e in rep.errors)
    sp = spec_of([slide(body=["수확량 1,234톤"], claim_ids=[CID])])
    assert S.check(sp, CLAIMS, TEMPLATE, layout_fn=B.layout_problems).ok


# ── 부록은 검증 기록에서 ─────────────────────────────────────────────────
def test_appendix_rows_come_from_claims_and_land_in_pptx(tmp_path):
    card = {"card_id": "2099-01-02-am-01", "sources": [{"name": "가상 일보", "url": "https://example.org/news", "tier": "T3"}]}
    sp = spec_of([slide(body=["수확량 1,234톤"], claim_ids=[CID], image={"what": "감자밭 지도", "source": "가상 섬 측량청", "map": True}),
                  slide(body=["보도로만 알려진 일"], refs=["가상 일보"])])
    rows = B.source_rows(sp, CLAIMS, card)
    assert rows[0][:5] == ["c1", "가상 섬 통계청", "표 3", "https://example.org/potato.pdf", "2098"]
    assert rows[0][5] == "3"  # 쓰인 쪽
    assert rows[1][1] == "가상 일보" and "검증 기록 없음" in rows[1][2]
    vis = B.visual_rows(sp)
    assert vis == [["3", "감자밭 지도", "가상 섬 측량청", "", "", ""]]  # 확인란은 빈칸 · 지도라 지도 표기 칸도 빈칸
    out = tmp_path / "d.pptx"
    info = B.build_pptx(sp, CLAIMS, card, out)
    from pptx import Presentation
    prs = Presentation(str(out))
    assert len(prs.slides) == info["total"] == len(sp["slides"]) + len(info["appendix"])
    texts = []
    for s in list(prs.slides)[info["main"]:]:
        for sh in s.shapes:
            if sh.has_table:
                texts += [c.text for r in sh.table.rows for c in r.cells]
    assert "https://example.org/potato.pdf" in texts and "가상 섬 측량청" in texts
    notes = prs.slides[2].notes_slide.notes_text_frame.text
    assert CID in notes  # 숫자가 든 슬라이드의 노트에 claim_id


def test_built_text_has_no_mid_word_break(tmp_path):
    body = ["바닷가 작은 마을의 감자밭은 해마다 조금씩 넓어졌고 올해는 아주 많이 거두었다"]
    sp = spec_of([slide(body=body, emphasis=["아주 많이"])])
    B.build_pptx(sp, CLAIMS, {}, tmp_path / "w.pptx")
    from pptx import Presentation
    s = Presentation(str(tmp_path / "w.pptx")).slides[2]
    box = next(sh for sh in s.shapes if sh.name == "본문")
    assert box.text_frame.word_wrap is False  # 파워포인트 자동 줄바꿈을 끄고 어절 줄바꿈만 쓴다
    lines = box.text_frame.text.replace("\v", "\n").split("\n")
    assert len(lines) > 1
    assert " ".join(x.strip() for x in lines) == body[0]


# ── 코드 검토 결함의 반례(숫자 판독 반례는 아래 NUMBER_TABLE 하나로 모았다) ──────
def _full(sl):
    return S.check(spec_of([sl]), CLAIMS_X, TEMPLATE, layout_fn=B.layout_problems)


CX = "2099-01-02-am-01-c3"
CLAIMS_X = dict(CLAIMS)


def _with_observed(obs):
    CLAIMS_X[CX] = claim(CX, text="가상의 섬 통계.", observed=obs)
    return CX


@pytest.mark.parametrize("sl", [
    {"stage": "근거 수치", "kind": "number", "title": "가상", "number": {"label": "수확량"}, "seconds": 10},
    {"stage": "배경", "kind": "quote_line", "title": "가상", "quote": {"by": "가상 통계청"}, "seconds": 10},
    {"stage": "배경", "kind": "compare_table", "title": "가상", "table": {"header": ["가"]}, "seconds": 10},
])
def test_defect8_nested_required_values_fail_check_not_build(sl):
    rep = _full(sl)
    assert not rep.ok
    assert any("배치 실패" in e or "있어야 한다" in e for e in rep.errors)


def test_spoken_and_transition_numbers_follow_the_same_rule():
    sl = slide(body=["숫자 없는 화면"], spoken="작년보다 40% 늘었습니다", claim_ids=[CID])
    assert any("말로 할 문장" in e and "40%" in e for e in S.number_errors(sl, CLAIMS))
    sl = slide(body=["숫자 없는 화면"], transition="다음은 7가지 이유입니다")
    assert any("claim_ids 가 없다" in e for e in S.number_errors(sl, CLAIMS))
    sl = slide(body=["숫자 없는 화면"], spoken="1,234톤, 12% 늘었습니다", claim_ids=[CID], notes="메모의 99% 는 보지 않는다")
    assert S.number_errors(sl, CLAIMS) == []


def test_draft_mode_allows_unverified_but_still_checks_numbers():
    claims = {CID: claim(hv=False)}
    sp = spec_of([slide(body=["수확량 1,234톤"], claim_ids=[CID])])
    assert not S.check(sp, claims, TEMPLATE).ok  # 엄격 모드는 그대로 실패
    rep = S.check(sp, claims, TEMPLATE, draft=True)
    assert rep.ok and rep.pending == {3: [CID]}
    sp = spec_of([slide(body=["수확량 9,999톤"], claim_ids=[CID])])
    assert not S.check(sp, claims, TEMPLATE, draft=True).ok  # 숫자 대조는 초안에서도
    sp = spec_of([slide(body=["숫자 없음"], claim_ids=["2099-01-02-am-01-c9"])])
    assert not S.check(sp, claims, TEMPLATE, draft=True).ok  # 기록은 실제로 있어야


def test_claims_dir_records_only_in_draft(tmp_path):
    import yaml
    cid = "2099-01-02-am-01-c7"
    d = tmp_path / "staging" / "2099-01-02-am-01"
    d.mkdir(parents=True)
    (d / f"{cid}.yaml").write_text(yaml.safe_dump(claim(cid), allow_unicode=True), encoding="utf-8")
    claims, staged = S.load_claims([cid], [tmp_path / "staging"])
    assert cid in claims and staged == {cid}
    sp = spec_of([slide(body=["수확량 1,234톤"], claim_ids=[cid])])
    rep = S.check(sp, claims, TEMPLATE, staged=staged)
    assert any("대기 폴더" in e for e in rep.errors)  # 사람 대조가 참이어도 엄격 모드에선 실패
    rep = S.check(sp, claims, TEMPLATE, draft=True, staged=staged)
    assert rep.ok and rep.pending == {3: [cid]}


def test_draft_pptx_marks_pending_slides_and_source_labels(tmp_path):
    sp = spec_of([slide(body=["수확량 1,234톤"], claim_ids=[CID])])
    sp["source_labels"] = {CID: "가상 통계 요약"}
    B.build_pptx(sp, {CID: claim(hv=False)}, {}, tmp_path / "p.pptx", pending={3: [CID]})
    from pptx import Presentation
    s3 = Presentation(str(tmp_path / "p.pptx")).slides[2]
    texts = [sh.text_frame.text for sh in s3.shapes if sh.has_text_frame]
    assert any(t.startswith("[검증 대기]") for t in texts)
    assert any("출처: 가상 통계 요약" in t for t in texts)
    assert "[검증 대기]" in s3.notes_slide.notes_text_frame.text


def test_defect3_card_id_cannot_escape_drafts_and_missing_card_stops_build(tmp_path):
    rep = S.check({**spec_of([]), "card_id": "/tmp/escape-deck"}, CLAIMS, TEMPLATE)
    assert any("형식" in e for e in rep.errors)
    with pytest.raises(SystemExit):
        B.resolve_card("/tmp/escape-deck")
    with pytest.raises(SystemExit):
        B.resolve_card("2099-12-31-am-99")  # 형식은 맞지만 카드가 없다 — 빈 카드로 대신하지 않는다
    with pytest.raises(SystemExit):
        B.out_paths("../../escape", "20990101_000000", False)
    d, pp = B.out_paths("2099-01-02-am-01", "20990101_000000", True)
    assert d.parent == B.DRAFTS.resolve() and pp.name.endswith("_draft.pptx")


def test_defect4_image_text_numbers_are_checked():
    sl = slide(image={"what": "매출 999억원 증가 그래프", "source": "가상 공식 통계"})
    assert any("999억" in e for e in S.number_errors(sl, CLAIMS))
    sl = slide(image={"what": "감자 그래프", "source": "가상 통계청 2098년 보고서 7쪽"})
    assert any("7" in e for e in S.number_errors(sl, CLAIMS))


def test_defect7_yaml_zero_is_checked():
    sl = {"stage": "근거 수치", "kind": "number", "title": "가상 지표", "number": {"value": 0, "label": "달러"}, "seconds": 10}
    assert "0" in "\n".join(S.visible_text(sl))
    assert not _full(sl).ok


def test_r2_3_symlinked_output_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "DRAFTS", tmp_path / "drafts")
    B.DRAFTS.mkdir()
    victim = tmp_path / "victim.pptx"
    victim.write_text("원래 내용")
    outdir, pptx = B.out_paths("2099-01-02-am-01", "20990101_000000", True)
    outdir.mkdir()
    pptx.symlink_to(victim)
    with pytest.raises(SystemExit):
        B.safe_new_file(outdir, pptx)
    assert victim.read_text() == "원래 내용"
    link_dir = B.DRAFTS / "2099-01-02-am-01_20990101_000001"
    link_dir.symlink_to(tmp_path)
    with pytest.raises(SystemExit):
        B.out_paths("2099-01-02-am-01", "20990101_000001", False)


def test_r2_4_canonical_symlink_to_staging_counts_as_staged(tmp_path, monkeypatch):
    import yaml
    from ozl.research import cards as Cmod
    canon = tmp_path / "claims"
    stage = tmp_path / "staging"
    (canon / "2099-01-02").mkdir(parents=True)
    stage.mkdir()
    cid = "2099-01-02-am-01-c5"
    real = stage / f"{cid}.yaml"
    real.write_text(yaml.safe_dump(claim(cid, observed="12%"), allow_unicode=True), encoding="utf-8")
    (canon / "2099-01-02" / f"{cid}.yaml").symlink_to(real)
    monkeypatch.setattr(Cmod, "CLAIMS", canon)
    claims, staged = S.load_claims([cid], [stage])
    assert cid in claims and cid in staged
    sp = spec_of([slide(body=["가상 12%"], claim_ids=[cid])])
    assert any("대기 폴더" in e for e in S.check(sp, claims, TEMPLATE, staged=staged).errors)


def test_r2_6_source_label_numbers_are_checked():
    cid = _with_observed("12%")
    sp = spec_of([slide(body=["가상 12%"], claim_ids=[cid])])
    sp["source_labels"] = {cid: "매출 999억 통계"}
    rep = S.check(sp, CLAIMS_X, TEMPLATE)
    assert any("999억" in e for e in rep.errors)
    sp["source_labels"] = {cid: "가상 통계 요약"}
    assert S.check(sp, CLAIMS_X, TEMPLATE).ok


def test_r2_7_visual_appendix_rows_carry_pending_mark(tmp_path):
    sp = spec_of([slide(body=["가상 12%"], claim_ids=[CX], image={"what": "매출 12% 증가 그래프", "source": "가상 통계청"})])
    claims = {CX: claim(CX, observed="12%", hv=False)}
    rep = S.check(sp, claims, TEMPLATE, draft=True)
    assert rep.ok and rep.pending == {3: [CX]}
    assert B.visual_rows(sp, rep.pending)[0][0].endswith("[검증 대기]")
    info = B.build_pptx(sp, claims, {}, tmp_path / "v.pptx", pending=rep.pending)
    from pptx import Presentation
    appx = list(Presentation(str(tmp_path / "v.pptx")).slides)[info["main"]:]
    for sl in appx:  # 출처 부록과 시각물 부록 모두 쪽 딱지와 행 표시가 있다
        texts = [sh.text_frame.text for sh in sl.shapes if sh.has_text_frame]
        cells = [c.text for sh in sl.shapes if sh.has_table for r in sh.table.rows for c in r.cells]
        assert any(t.startswith("[검증 대기]") for t in texts)
        assert any("[검증 대기]" in c.replace("\x0b", " ") for c in cells)


@pytest.mark.parametrize("widths", [[-1, 2], [0, 1], [float("inf"), 1], ["넓게", 1], [True, 1]])
def test_r2_8_table_widths_must_be_positive_finite(widths):
    sl = {"stage": "배경", "kind": "compare_table", "title": "가상 표", "seconds": 10,
          "table": {"header": ["항목", "설명"], "rows": [["가", "나"]], "widths": widths}}
    rep = _full(sl)
    assert any("양의 유한수" in e for e in rep.errors), rep.errors


# ── 부록 다듬기 · 명령줄 오류 ────────────────────────────────────────────
def test_appendix_locator_drops_urls_and_lists_cross_check():
    c = claim(CX, observed="12%")
    c["checks"]["primary_doc_locator"] = "표 3 https://example.org/a.pdf · 부록 2쪽 (https://example.org/b)"
    c["cross_check"] = [{"url": "https://example.org/other", "tier": "T3", "publisher": "가상 다른 일보"}]
    sp = spec_of([slide(body=["가상 12%"], claim_ids=[CX])])
    rows = B.source_rows(sp, {CX: c}, {}, {CX})
    assert "http" not in rows[0][2] and rows[0][2].startswith("표 3")
    assert rows[1][0].startswith("c3 교차") and "[검증 대기]" in rows[1][0]
    assert rows[1][1] == "가상 다른 일보" and rows[1][3] == "https://example.org/other" and rows[1][5] == "3"


def test_cli_missing_spec_is_one_line_error(tmp_path, capsys):
    from ozl.render import __main__ as M
    assert M.main(["check", str(tmp_path / "없는파일.yaml")]) == 1
    err = capsys.readouterr().err
    assert "사양 파일이 없다" in err and "Traceback" not in err
    bad = tmp_path / "bad.yaml"
    bad.write_text("slides: [\n", encoding="utf-8")
    assert M.main(["check", str(bad)]) == 1


def test_empty_table_cells_do_not_fall_back_to_18pt(tmp_path):
    """빈 칸의 문단 끝 표시가 기본 18pt 로 남으면 파워포인트가 행을 키워 부록 표가 쪽 아래로 넘친다(2026-11-10 시각물 부록에서 실측)."""
    sp = spec_of([slide(image={"what": "가상 지도", "source": "가상 측량청", "map": True})])
    info = B.build_pptx(sp, {}, {}, tmp_path / "e.pptx")
    from pptx import Presentation
    from pptx.oxml.ns import qn
    last = list(Presentation(str(tmp_path / "e.pptx")).slides)[-1]
    tbl = next(sh for sh in last.shapes if sh.has_table).table
    for row in tbl.rows:
        for cell in row.cells:
            for para in cell.text_frame.paragraphs:
                end = para._p.find(qn("a:endParaRPr"))
                assert end is not None and end.get("sz") == str(B.APPX_SIZE * 100)


# ── 숫자 판독 반례 표(1~3차 코드 검토의 반례 전부 · 지어낸 예시) ─────────────
# (본문, 기록 observed — None 이면 인용 없음, 환산 (shown, source) — None 이면 없음, 통과해야 하는가)
NUMBER_TABLE = [
    # 1차: 부호·소수점·%p·크기 단위
    ("가상 지표 -3%", "3%", None, False), ("가상 지표 -3%", "-3%", None, True),
    ("가상 지표 .5%", "5%", None, False), ("가상 지표 .5%", ".5%", None, True),
    ("가상 지표 3%p", "3%", None, False), ("가상 지표 3%p", "3%p", None, True),
    ("가상 지표 1 million 달러", "1 billion 달러", None, False), ("가상 지표 1 million 달러", "1 million 달러", None, True),
    ("가상 지표 3천만", "3천", None, False), ("가상 지표 3천만", "3천만", None, True),
    # 1차: 단위·분수는 식별자가 아니다
    ("농산물 12kg", None, None, False), ("매출 33million 달러", None, None, False),
    ("생산량 1/3 감소", None, None, False), ("표본 5천명", None, None, False),
    # 1차: 날짜와 기간
    ("9일간 파업", None, None, False), ("3월 9일간 파업", None, None, False), ("2000년 전 유적", None, None, False),
    ("16년 동안", None, None, False), ("1776년 독립", None, None, True), ("2100년 전망", None, None, True),
    ("2026.11.10 발표", None, None, True), ("11월 9일 발표", None, None, True),
    # 1차: 환산 원문은 완전한 수량
    ("가상 100만 개", "21 million", ("100만", "1 million"), False), ("가상 2,100만 개", "21 million", ("2,100만", "21 million"), True),
    # 2차: 한글에 붙은 부호 · 환산 원문의 끝 경계
    ("가상 수익률-3%", "3%", None, False), ("가상 수익률 -3%", "가상 수익률-3%", None, True),
    ("가상 3,000건", "3천만", ("3,000건", "3천"), False), ("가상 3.0%", "3%p", ("3.0%", "3%"), False),
    ("가상 3.0%", "-3%", ("3.0%", "3%"), False),
    # 2차: 조사와 붙은 기간 · 세 자리 연도
    ("1000년간의 변화", None, None, False), ("11월 9일간의 파업", None, None, False), ("2000년 전부터", None, None, False),
    ("10년 새", None, None, False), ("918년 고려 건국", None, None, False),  # 4차 원칙: 세 자리 연도는 달력으로 보지 않는다
    # 3차: 부호와 범위
    ("가상 -3%,-4%", "-3% 및 4%", None, False), ("가상 -80만", "70만-80만", None, False),
    ("가상 70만-80만", "70만 및 80만", None, True), ("가상 GDP-3%", "3%", None, False), ("가상 GDP-3%", "가상 GDP-3%", None, True),
    ("가상 3-4%", "3-4%", None, True), ("전년 대비 -3%", "-3%", None, True), ("가상 70만~80만", "70만~80만", None, True),
    # 3차: 복합 한글 수량의 조각 · 숫자 없는 환산 원문
    ("가상 300만", "3천3백만", ("300만", "3백만"), False), ("가상 3천", "3천3백만", None, False),
    ("가상 999억", "통계 확인", ("999억", "통계"), False),
    # 3차: 달력은 면제 · 기간은 대조
    ("2020~2022년", None, None, True), ("2004~2025년", None, None, True), ("1~9월", None, None, True), ("3분기", None, None, True),
    ("2026년 1분기", None, None, True), ("1998년→2013년", None, None, True),
    ("100년 만의 변화", None, None, False), ("1000년 만의 변화", None, None, False), ("반년 동안", None, None, False),
    ("23년 만에", None, None, False), ("6년 9개월", None, None, False), ("세계 1위", None, None, False),
    # 3차: 식별자
    # 4차 원칙: 식별자는 추측하지 않는다 — 사건 번호 꼴만 자동 면제, 나머지는 사양의 identifiers 목록(아래 IDENT_TABLE)
    ("허가 A-3", None, None, False), ("허가 52C 문서", None, None, False), ("사건 XYZ/01/02", None, None, True), ("(기록 c3 참고)", None, None, False),
    # 4차: 공백 있는 복합 수량 · 영문자 붙은 수량 · 좁은 달력 · 영문 크기 단위 · 한글 분수의 % · 낱말 조사 · 기간 범위
    ("가상 500", "70만 1천 5백 배럴", ("500", "5백"), False), ("가상 3천", "3천 3백만", None, False),
    ("가상 3천 3백만", "3천3백만", None, True), ("가상 3천3백만", "3천 3백만", None, True),
    ("매출 USD100 million", None, None, False), ("GDP3%", None, None, False),
    ("가격 2026.11달러", None, None, False), ("생산량 2004~2025만 배럴", None, None, False), ("1000~2000년 동안", None, None, False),
    ("가상 1 million달러", "1 billion달러", None, False), ("가상 1 million달러", "1 million달러", None, True),
    ("가상 2분의 1%", "1/2", None, False), ("가상 2분의 1%", "2분의 1%", None, True),
    ("갑절로 증가", None, None, False), ("갑절이 됐다", None, None, False),
    ("가상 49B", None, None, False), ("가상 10-K", None, None, False),
    ("가상 3일-4일", "3일 및 4일", None, True), ("가상 70만 1천 5백 배럴", "700,000 + 1,500", None, False),
    # 5차 1: 달력 뒤의 수량·기간 문맥(공백·조사·복합 기간) — 닫힌 조건이 아니면 달력이 아니다
    ("생산량 2004~2025 million 배럴", None, None, False), ("생산량 2004~2025 kg", None, None, False),
    ("생산량 2004~2025 배럴을", None, None, False), ("1000~2000 년 동안", None, None, False),
    ("가상 2000년 6개월 동안", "6개월", None, False),
    ("2026년 1분기 실적", None, None, True), ("2월 13일 원판", None, None, True), ("3월 18일입니다.", None, None, True),
    ("2001년 147만 배럴", "147만", None, True),
    # 5차 2: 연속 공백(정규화 뒤 판독) — 오통과와 오실패 양쪽
    ("가상 3천", "3천  3백만", None, False), ("가상 500", "70만 1천  5백 배럴", ("500", "5백"), False),
    ("가상 1  million달러", "1  billion달러", None, False), ("가상 2분의 1  %", "1/2", None, False),
    ("가상 3천  3백만", "3천3백만", None, True),
    # 5차 3: 복합 수량의 마지막 일의 자리
    ("가상 2천3백4십", "2천3백4십5", None, False), ("가상 2천3백4십5", "2천3백4십5", None, True),
    # 5차 4: 소수 분수 · 판독하지 못한 이음은 통째로
    ("가상 5%", "1/2.5%", None, False), ("가상 2분의 1.5%", "1/2.5%", None, False), ("가상 1/2.5%", "1/2.5%", None, True),
    ("가상 1.2.3 배럴", "1.2.3 배럴", None, True), ("가상 1.2 배럴", "1.2.3 배럴", None, False),
    # 5차 5: 자동 사건 번호 뒤의 % — 식별자로 면제하지 않는다
    ("사건 ARB/07/27%", None, None, False),
    # 5차 6: U+2212 는 부호
    ("가상 12% −3%", "12% 및 3%", None, False), ("가상 12% −3%", "12% 및 −3%", None, True),
    # 5차 9: 탭·개행 뒤 범위
    ("가상 3일\t-4일", "3일 및 4일", None, True), ("가상 3일\n-4일", "3일 및 4일", None, True),
    # 6차: '년' 없는 연도 범위는 수량 범위와 가를 수 없어 근거를 요구한다(기록에 있으면 통과)
    ("2020-2022", None, None, False), ("가상 2020-2022", "between 2020 and 2022", None, True),
    ("생산량 2004~2025 kg으로", None, None, False), ("생산량 2004~2025 kg을", None, None, False), ("생산량 2004~2025 million달러", None, None, False),
    # 6차: 복합 수량의 마지막 자리(크기 단위 없음) — 조각은 근거가 못 되고, 붙여 쓴 것과 띄어 쓴 것은 같다
    ("예산 1억", "1억 2,345원", None, False), ("예산 2,345원", "1억 2,345원", None, False),
    ("예산 1억 2,345원", "1억2345원", None, True), ("예산 1억2345원", "1억 2,345원", None, True),
    # 6차: 분모의 쉼표
    ("발생률 1/2", "1/2,000", None, False), ("발생률 1/2,000", "1/2000", None, True),
    # 6차: 판독하지 못한 이음은 뒤의 %·크기 단위까지 같은 표기여야 한다
    ("가상 1/2/3%", "1/2/3", None, False), ("가상 1/2/3", "1/2/3%", None, False), ("가상 1/2/3 million", "1/2/3 billion", None, False),
    ("가상 1/2/3%", "1/2/3%", None, True),
    # 6차: 달력 꼬리말 뒤의 조사
    ("3월말까지 발표", None, None, True), ("2026년판은 개정됐다", None, None, True),
    # 경계 그물: 판독부가 통째로 읽지 못한 표기는 조각으로 근거가 되지 않고, 같은 표기 전체로만 맞는다
    ("가상 1억", "1억 2,345.5원", None, False), ("가상 2,345.5원", "1억 2,345.5원", None, False),
    ("가상 1억 2,345.5원", "1억 2,345.5원", None, True),
    ("가상 1", "1,23", None, False), ("가상 23", "1,23", None, False), ("가상 1,23", "1,23", None, True), ("가상 1,23", "1,23,45", None, False),
    ("가상 5", "5 %", None, False), ("가상 100", "100 million", None, False),
    # 7차: 복합 분모(1만분의 1) · 숫자와 크기 단위 사이 공백 · 떨어진 부호 · 단위로 닫힌 수량의 나열
    ("발생 확률은 1이다", "발생 확률은 1만분의 1이다", None, False), ("발생 확률은 1만분의 1이다", "발생 확률은 1만분의 1이다", None, True),
    ("가상 1", "1만 5천분의 1", None, False), ("가상 1만 5천", "1만 5천분의 1", None, False), ("가상 1만 5천분의 1", "1만 5천분의 1", None, True),
    ("생산량 70 배럴", "생산량 70 만 배럴", None, False), ("생산량 70만 배럴", "생산량 70 만 배럴", None, True),
    ("수익률 3%", "수익률 − 3%", None, False), ("수익률 -3%", "수익률 − 3%", None, True),
    ("이익 변동 3.5 billion", "이익 변동 -$3.5 billion", None, False), ("이익 변동 -3.5 billion", "이익 변동 -$3.5 billion", None, True),
    ("지지율 10%,20%", "10% 및 20%", None, True), ("소요 기간 3일/4일", "3일 및 4일", None, True), ("소요 기간 6년9개월", "6년 9개월", None, True),
    ("가상 1/2/3", "1/2/3 만", None, False), ("가상 지표 - 3% 상승", "3%", None, True),
    # 영문 percent · percentage points
    ("가상 12%", "up 12 percent", None, True), ("가상 12", "up 12 percent", None, False),
    ("가상 3%p", "rose 3 percentage points", None, True), ("가상 3%", "rose 3 percentage points", None, False),
    # 숫자에 영문자가 바로 붙은 표기는 글자까지 한 토큰이다(52C 의 52 · 3.5B 의 3.5 는 근거가 못 된다)
    ("가상 52", "GENERAL LICENSE NO. 52C", None, False), ("가상 52C", "GENERAL LICENSE NO. 52C", None, True),
    ("가상 3.5", "worth $3.5B", None, False), ("가상 701", "about 701k barrels", None, False), ("가상 5 kg", "5kg", ("5 kg", "5kg"), True),
    ("3/4분기 실적", None, None, True),
    # 8차: 떨어진 부호 경로도 같은 뒤처리(붙은 영문자) · 통화 기호가 낀 범위는 부호가 아니다
    ("이익 변동 -3.5", "이익 변동 -$3.5B", None, False), ("이익 변동 -$3.5B", "이익 변동 -$3.5B", None, True),
    ("투자액 -4 billion", "투자액 범위 $3 billion–$4 billion", None, False), ("투자액 4 billion", "투자액 범위 $3 billion–$4 billion", None, True),
    ("유가 -80달러", "유가 예상 범위 $70 –$80", None, False), ("유가 80달러", "유가 예상 범위 $70 –$80", None, True),
    # 8차: 띄어 쓴 복합 크기 단위 · 측정 단위 뒤에 어미가 붙은 꼴
    ("예산 3 달러", "예산 3 백만 달러", None, False), ("예산 3백만 달러", "예산 3 백만 달러", None, True), ("예산 5 원", "예산 5 천만 원", None, False),
    ("생산량 70 배럴", "생산량 70 만 배럴가량", None, False), ("매출 70 달러", "매출 70 만 달러였다", None, False),
    ("발생 확률 1", "발생 확률 1 만분의 1", None, False), ("가상 1/2/3", "1/2/3 백만", None, False), ("생산량 1.2.3", "생산량 1.2.3B", None, False),
    ("수익률 3.5 billion", "수익률 − $ 3.5 billion", None, False),
    # 8차: 단위로 닫힌 수량 뒤의 영문 낱말·구분자는 다른 말이다 / 분모의 크기 단위와 분자 뒤 크기 단위는 다른 자리다
    ("성장률 3%YoY", "성장률 3% YoY", None, True), ("생산량 70만,80만", "70만 및 80만", None, True), ("찬성/반대 10%/20%", "찬성 10% 및 반대 20%", None, True),
    ("확률 2분의 1만", "확률 2만분의 1", None, False), ("확률 2만분의 1", "확률 2만분의 1", None, True),
    # 범위의 앞 수는 뒤 수의 단위를 같이 쓴다 — 단위를 뗀 앞 수는 근거가 못 된다
    ("가상 3 배럴", "3~5% 범위", None, False), ("가상 3%", "3~5% 범위", None, True), ("가상 3~5%", "3~5% 범위", None, True),
    ("가상 70 배럴", "70~80만 배럴", None, False), ("가상 70만 배럴", "70~80만 배럴", None, True), ("가상 3 billion", "$3–4 billion", None, True),
    ("가상 3 배럴", "3~5년 걸린다", None, False), ("가상 3년", "3~5년 걸린다", None, True), ("가상 2일", "2~3일 뒤", None, True),
    ("가상 70 배럴", "70~80만5천 배럴", None, False),                      # 단위를 나눠 줄 수 없는 범위의 앞 수는 근거가 못 된다
    ("가상 100", "매출 100 - 3% 감소", None, True),                        # 공백으로 둘러싼 '-' 는 줄표 — 앞 수에 % 를 붙이지 않는다
    ("가상 1위", "1~3위", None, True),                                     # 둘 다 단위 없는 수는 그대로
    # 9차: 금액 – 비율은 범위가 아니다 · 일반 낱말의 첫 글자는 크기 단위가 아니다 · 단위 낱말을 사이에 둔 범위는 부호가 아니다
    ("할인율 100%", "가격 $100 – 20% 할인", None, False), ("가격 100달러", "가격 $100 – 20% 할인", None, True),
    ("가상 100%", "할인 계산: $100 - 20% = $80", None, False),
    ("매출 3조 원", "표 3 조명시장 전망", None, False), ("매출 3조 원", "표 3 조원태 회장 발언", None, False),
    # 10차: 숫자 뒤에 띄어 쓴 '크기 단위 글자 + 한글' 은 크기 단위인지 낱말인지 가를 수 없다 — 추측하지 않고 그 숫자를 근거로 쓰지 않는다
    ("매출 3조 원", "표 3 조명 산업 현황", None, False), ("매출 3만 원", "표 3 만주 지역", None, False), ("표 3: 조명시장 전망", "표 3 조명시장 전망", None, False),
    ("예산 3원", "예산 3 백만원으로는 부족하다", None, False), ("예산 3백만 원", "예산 3 백만 원으로는 부족하다", None, True),
    # 11차: 슬래시 뒤의 설명하는 말(/YoY)은 단위가 아니다 · 부호부터 시작한 금액 – 비율 · 따로 선 '조' 는 성일 수 있다
    ("증감률 3%", "매출 100억/YoY-3%", None, False), ("증감률 -3%", "매출 100억/YoY-3%", None, True), ("증감률 3%", "100억/QoQ-3%", None, False),
    ("증감률 -100%", "손실 -$100 – 20% 개선", None, False), ("증감률 -100%", "손실 −$100 – 20%", None, False),
    ("예산 3조 원", "표 3 조 바이든 정부 정책", None, False), ("가상 70만", "70 만 수준", None, False), ("가상 3조 원", "예산 3 조 원", None, True),
    # 10차: 설명하는 말 뒤의 '-' 는 부호다 · 통화 기호와 숫자 사이 공백 · 여러 낱말 단위 뒤의 범위
    ("증감률 3%", "매출 100억 전년비-3%", None, False), ("증감률 -3%", "매출 100억 전년비-3%", None, True),
    ("증감률 3%", "매출 100억원 -3%", None, False), ("증감률 -3%", "매출 100억원 -3%", None, True),
    ("할인율 100%", "가격 $ 100 – 20% 할인", None, False), ("가격 100달러", "가격 $ 100 – 20% 할인", None, True),
    ("유가 -80달러", "유가 $70 per barrel–$ 80 per barrel", None, False), ("유가 80달러", "유가 $70 per barrel–$ 80 per barrel", None, True),
    ("유가 -80달러", "유가 전망 $70/bbl–$ 80/bbl", None, False), ("유가 80달러", "유가 전망 $70/bbl–$ 80/bbl", None, True),
    ("유가 -80달러", "$70/bbl–$80/bbl", None, False), ("하루 80만 배럴", "하루 70만 배럴-80만 배럴", None, True),
    ("가상 -3%", "매출 100억 원 -3% 감소", None, True),
    # 9차: 띄어 쓴 크기 단위 뒤의 측정 단위 낱말 · 처리하지 못한 범위의 앞 수 · 부호 붙은 기간 · 지수 표기
    ("개발 부지 3평", "개발 부지 3 만평", None, False), ("저장량 70리터", "저장량 70 만리터", None, False), ("예산 3불", "예산 3 백만불", None, False),
    ("개발 부지 3만 평", "개발 부지 3 만 평", None, True),
    ("투자 규모 3달러", "투자 규모 $3–5B", None, False), ("개발 기간 3", "개발 기간 3~5개월", None, False),
    ("투자 규모 70달러", "투자 규모 $70–$ 80 million", None, False),
    ("기간 변동 −1.5개월", "기간 변동 −1.5년", None, False), ("기간 변동 −1.5년", "기간 변동 −1.5년", None, True),
    ("생산량 1.2.3만", "생산량 1.2.3만B", None, False), ("가상 3%", "1.2e-3%", None, False), ("기간 .5년", "기간 0.5년", None, True),
    # 소수 기간
    ("가상 1.5 배럴", "1.5년 걸렸다", None, False), ("가상 1.5년", "1.5년 걸렸다", None, True),
    # 정상 환산(원문 표기를 그대로 source 에)
    ("가상 311만 9천 배럴", "3,119", ("311만 9천", "3,119"), True), ("가상 94만 배럴", "0.94", ("94만", "0.94"), True),
    ("가상 11만 배럴", "110", ("11만", "110"), True), ("가상 71.5%", "736,192 / 1,029,398", ("71.5%", "736,192"), True),
    # 숫자 없는 수량 낱말
    ("가상 지표가 세 배 늘었다", "300%", None, False), ("가상 지표가 세 배 늘었다", "300%", ("세 배", "300%"), True),
    ("가상 허가는 세 번 바뀌었다", "가상 허가는 세 번 바뀌었다", None, True),
]


@pytest.mark.parametrize("body,observed,conv,ok", NUMBER_TABLE)
def test_number_table(body, observed, conv, ok):
    sl = slide(body=[body])
    claims = {}
    if observed is not None:
        claims = {CX: claim(CX, text="가상의 섬 통계.", observed=observed)}
        sl["claim_ids"] = [CX]
    if conv:
        sl["conversions"] = [{"shown": conv[0], "source": conv[1], "claim_id": CX, "basis": "가상 환산"}]
    errs = S.number_errors(sl, claims)
    assert (errs == []) is ok, (body, observed, conv, errs)
    rep = S.check(spec_of([sl]), claims, TEMPLATE, layout_fn=B.layout_problems)  # 전체 검사(단계·배치 포함)도 같은 판정
    assert rep.ok is ok, rep.errors


def test_spoken_word_quantities_need_basis():
    sl = slide(body=["숫자 없는 화면"], spoken="반년 만에 절반이 됐습니다", claim_ids=[CID])
    assert any("반년" in e and "절반" in e for e in S.number_errors(sl, CLAIMS))


# ── 3차: 보도 행의 검증 대기 · 표의 어절 ───────────────────────────────────
def test_r3_7_ref_rows_carry_pending_mark():
    card = {"sources": [{"name": "가상 12% 보도", "url": "https://example.org/r", "tier": "T3"}]}
    sp = spec_of([slide(body=["가상 12%"], claim_ids=[CX], refs=["가상 12% 보도"])])
    claims = {CX: claim(CX, observed="12%", hv=False)}
    rep = S.check(sp, claims, TEMPLATE, card=card, draft=True)
    assert rep.ok, rep.errors
    rows = B.source_rows(sp, claims, card, rep.pending)
    ref_row = next(r for r in rows if r[1] == "가상 12% 보도")
    assert "[검증 대기]" in ref_row[0]


def test_r3_8_table_word_wider_than_cell_fails_and_autowrap_is_off(tmp_path):
    sl = {"stage": "배경", "kind": "compare_table", "title": "가상 표", "seconds": 10,
          "table": {"header": ["항목", "설명"], "rows": [["경제성장률", "생산 증가의 정도"]], "widths": [1, 7]}}
    assert any("칸 폭보다 길다" in e for e in _full(sl).errors)
    sl["table"]["widths"] = [2, 6]
    assert _full(sl).ok
    B.build_pptx(spec_of([sl]), {}, {}, tmp_path / "t.pptx")
    from pptx import Presentation
    s3 = Presentation(str(tmp_path / "t.pptx")).slides[2]
    tbl = next(sh for sh in s3.shapes if sh.has_table).table
    assert all(c.text_frame.word_wrap is False for r in tbl.rows for c in r.cells)


# 4차: 식별자는 사양의 identifiers 목록에 적은 것만 면제하고, check 가 면제 목록을 돌려준다
IDENT_TABLE = [
    ("가상 49B 허가", ["49B"], True), ("가상 10-K 보고서", ["10-K"], True), ("허가 A-3", ["A-3"], True),
    ("가상 49B 허가", ["52C"], False), ("가상 149B", ["49B"], False),  # 목록에 없거나 다른 낱말의 일부면 수량
    ("매출 USD100 million", ["USD100"], False),  # 목록의 표기가 붙은 수량 전체를 덮지 못하면 나머지는 수량
    # 5차 5·8: 식별자 뒤의 소수점·연속 공백 크기 단위는 수량 / 조사·일반 낱말은 식별자 유지
    ("매출 USD100  million", ["USD100"], False), ("매출 USD100.5 million", ["USD100"], False),
    ("허가 49B만으로", ["49B"], True), ("49B 조사", ["49B"], True),
    # 6차: 보조사 '만' 뒤에 낱말이 이어져도 식별자 / 쉼표로 이어진 숫자는 수량
    ("허가 49B만 남았다", ["49B"], True), ("매출 USD100,500 million", ["USD100"], False), ("매출 USD100만 달러", ["USD100"], False),
    ("허가 49B만 3월까지 유효하다", ["49B"], True),  # 7차: '만' 뒤가 달력이면 보조사
    ("지분 49 percent", ["49"], False),  # 8차: 식별자 뒤의 % 낱말도 수량의 이음
    ("생산량 49 백만 달러", ["49"], False),  # 9차: 식별자 뒤에 띄어 쓴 복합 크기 단위
    # 10차: 숫자만으로 된 표기는 식별자로 받지 않는다(49억 · 49개월 · 49 백만원이 같이 빠지지 않게)
    ("예산 49 백만원으로는", ["49"], False), ("자산 49억 3월 발표", ["49"], False), ("사업 기간 49개월", ["49"], False), ("허가 49호", ["49"], False),
    # 11차: 범위처럼 생긴 식별자(49-51) 뒤에 크기 단위·기간이 이어지면 수량이다
    ("예산 49-51억원으로는 부족하다", ["49-51"], False), ("자산 49-51억 3월 발표", ["49-51"], False), ("사업 기간 49-51개월", ["49-51"], False),
    ("허가 49-51 유효", ["49-51"], True),
]


@pytest.mark.parametrize("body,idents,ok", IDENT_TABLE)
def test_identifiers_only_from_spec_list(body, idents, ok):
    sp = spec_of([slide(body=[body])])
    sp["identifiers"] = idents
    rep = S.check(sp, {}, TEMPLATE)
    assert rep.ok is ok, rep.errors
    if ok:
        assert set(rep.exempt_idents) <= set(idents) and rep.exempt_idents


def test_r4_7_card_source_name_in_footnote_is_checked():
    cid = _with_observed("12%")
    card = {"card_id": "2099-01-02-am-01", "data": [{"claim_id": cid, "source_name": "인구 999억 돌파 보도"}]}
    sp = spec_of([slide(body=["가상 12%"], claim_ids=[cid])])
    rep = S.check(sp, CLAIMS_X, TEMPLATE, card=card)
    assert any("999억" in e for e in rep.errors), rep.errors
    assert S.footnote_text(sp["slides"][2], CLAIMS_X, card, {}) == B.footnote_text(sp["slides"][2], CLAIMS_X, card, {})
    card["data"][0]["source_name"] = "가상 통계청 발표"
    assert S.check(sp, CLAIMS_X, TEMPLATE, card=card).ok


def test_r4_10_appendix_long_word_fails():
    cid = _with_observed("12%")
    c = dict(CLAIMS_X[cid])
    c["source"] = {"url": "https://example.org/x", "publisher": "국제에너지기구공식통계발표기관", "tier": "T1"}
    sp = spec_of([slide(body=["가상 12%"], claim_ids=[cid])])
    errs = B.appendix_problems(sp, {cid: c}, {})
    assert any("칸 폭보다 길다" in e for e in errs)
    c["source"]["publisher"] = "가상 에너지 기구"
    assert B.appendix_problems(sp, {cid: c}, {}) == []
    rep = S.check(sp, {cid: c}, TEMPLATE, appendix_fn=B.appendix_problems)
    assert rep.ok, rep.errors


def test_press_sources_in_spec_only_in_draft():
    """카드 sources 에 아직 없는 보도를 사양 press_sources 에 적으면 초안 모드에서만 refs 로 쓸 수 있고, 그 쪽은 검증 대기로 표시된다."""
    sp = spec_of([slide(body=["가상 보도로만 알려진 일"], refs=["가상 통신 보도"])])
    sp["press_sources"] = [{"name": "가상 통신 보도", "tier": "T3", "url": "https://example.org/wire"}]
    card = {"card_id": "2099-01-02-am-01", "sources": []}
    rep = S.check(sp, {}, TEMPLATE, card=card)
    assert any("초안 모드" in e for e in rep.errors)
    rep = S.check(sp, {}, TEMPLATE, card=card, draft=True)
    assert rep.ok and rep.pending == {3: ["보도:가상 통신 보도"]}
    rows = B.source_rows(sp, {}, card, rep.pending)
    assert rows[0][1] == "가상 통신 보도" and rows[0][3] == "https://example.org/wire" and "[검증 대기]" in rows[0][0]
    card["sources"] = [{"name": "가상 통신 보도", "tier": "T3", "url": "https://example.org/wire"}]
    assert S.check(sp, {}, TEMPLATE, card=card).ok  # 카드에 반영된 뒤에는 엄격 모드도 통과
    sp["press_sources"] = [{"name": "가상 통신 보도", "tier": "T9", "url": "주소 아님"}]
    assert not S.check(sp, {}, TEMPLATE, card=card, draft=True).ok



# ── 5차: 식별자 경계(기록이 있어도) · 부록 일반 글의 숫자 · 시각물 주소 ─────────────
def test_r5_5_identifier_does_not_cover_longer_quantity_even_with_record():
    cid = _with_observed("5 million")
    sp = spec_of([slide(body=["가상 USD100.5 million"], claim_ids=[cid])])
    sp["identifiers"] = ["USD100"]
    rep = S.check(sp, CLAIMS_X, TEMPLATE)
    assert not rep.ok and "USD100" not in rep.exempt_idents


def test_r6_identifier_does_not_cover_comma_joined_quantity_even_with_record():
    cid = _with_observed("500 million")
    sp = spec_of([slide(body=["가상 USD100,500 million"], claim_ids=[cid])])
    sp["identifiers"] = ["USD100"]
    rep = S.check(sp, CLAIMS_X, TEMPLATE)
    assert not rep.ok and "USD100" not in rep.exempt_idents


def test_r6_fragment_tokens_never_enter_the_pool_or_match():
    """경계 그물 자체: 앞뒤에 숫자 이음이 남은 토큰은 기록 쪽에서는 근거 목록에 들지 않고, 화면 쪽에서는 따로 오류가 난다."""
    N = S.N
    assert N.pool("1억 2,345.5원") == {"raw:1억2,345.5"}          # 이어진 토큰은 통째로 하나
    assert N.pool("가상 12 .5") == {"12", "0.5"}                    # 공백으로 떨어진 것은 따로
    toks = N.scan("가상 x9,5")                                        # 쉼표로 이어진 둘은 하나의 raw 토큰이 된다
    assert [(t.canon, t.fragment) for t in toks] == [("raw:9,5", False)]
    frag = [t for t in N.scan("가상 3.5.") if t.fragment]            # 문장 끝 마침표는 이음이 아니다
    assert frag == []
    cid = _with_observed("7")
    sl = slide(body=["가상 7 billion"], claim_ids=[cid])              # 기록의 7 은 화면의 7 billion 을 받치지 못한다
    assert S.number_errors(sl, CLAIMS_X)
    cid = _with_observed("7 billion")
    sl = slide(body=["가상 7"], claim_ids=[cid])                      # 기록의 7 billion 은 화면의 7 을 받치지 못한다
    assert S.number_errors(sl, CLAIMS_X)


def test_r5_7_appendix_general_text_numbers_are_checked():
    cid = _with_observed("12%")
    c = dict(CLAIMS_X[cid])
    c["checks"] = dict(c["checks"], primary_doc_locator="본문 첫 문단")
    c["cross_check"] = [{"publisher": "인구 999억 돌파 보도", "url": "https://example.org/b", "tier": "T3"}]
    sp = spec_of([slide(body=["가상 12%"], claim_ids=[cid])])
    errs = B.appendix_number_errors(sp, {cid: c}, {})
    assert any("999억" in e and "교차 출처" in e for e in errs)
    assert not S.check(sp, {cid: c}, TEMPLATE, appendix_fn=B.appendix_problems).ok
    c["cross_check"] = [{"publisher": "가상 다른 일보", "url": "https://example.org/b", "tier": "T3"}]
    assert B.appendix_number_errors(sp, {cid: c}, {}) == []
    c["source"] = dict(c["source"], publisher="가상 통계청 777억 집계")  # 기관 이름도 대조 칸
    assert any("777억" in e and "기관" in e for e in B.appendix_number_errors(sp, {cid: c}, {}))


def test_r5_7b_doc_locator_is_structural():
    """문서 위치(primary_doc_locator)는 쪽·조·문단·표 번호를 가리키는 구조 칸이라 숫자가 있어도 통과한다."""
    cid = _with_observed("12%")
    c = dict(CLAIMS_X[cid])
    c["checks"] = dict(c["checks"], primary_doc_locator="판정문 ¶108~112(인쇄 45~47쪽) · 제23조 · Box 1.2 · 37쪽 표")
    sp = spec_of([slide(body=["가상 12%"], claim_ids=[cid])])
    assert B.appendix_number_errors(sp, {cid: c}, {}) == []
    assert "문서 위치" in B.APPX_STRUCTURAL and "문서 위치" not in B.APPX_CHECKED
    assert S.check(sp, {cid: c}, TEMPLATE, layout_fn=B.layout_problems, appendix_fn=B.appendix_problems).ok


def test_r5_10_visual_source_url_is_not_a_long_word(tmp_path):
    url = "https://example.org/press/official-publication/annual-report/official-photo.jpg"
    sp = spec_of([slide(image={"what": "가상 사진", "source": url})])
    assert B.appendix_problems(sp, {}, {}) == []
    assert S.check(sp, {}, TEMPLATE, layout_fn=B.layout_problems, appendix_fn=B.appendix_problems).ok
    info = B.build_pptx(sp, {}, {}, tmp_path / "u.pptx")
    from pptx import Presentation
    last = list(Presentation(str(tmp_path / "u.pptx")).slides)[-1]
    tbl = next(sh for sh in last.shapes if sh.has_table).table
    cell = next(c for r in tbl.rows for c in r.cells if url in c.text.replace("\x0b", ""))
    assert cell.text_frame.word_wrap is True  # 주소가 든 칸만 파워포인트가 접는다
    assert any(c.text_frame.word_wrap is False for r in tbl.rows for c in r.cells if c.text and "://" not in c.text)


def test_r5_normalize_collapses_all_whitespace():
    from ozl.render import numbers as N
    assert N.normalize("3천\t\n  3백만\u00a0배럴") == "3천 3백만 배럴"
    assert [t.canon for t in N.scan("3천\t3백만")] == ["3천3백만"]


# ── 무작위 시험: 수량 표현의 일부만 떼어 쓴 화면 글은 통과하지 못한다(지어낸 숫자 · 씨앗 고정) ─────────────
def _fz_digits(rnd, lo=1, hi=6, comma=None, dec=None):
    n = str(rnd.randint(1, 9)) + "".join(str(rnd.randint(0, 9)) for _ in range(rnd.randint(lo, hi) - 1))
    comma = rnd.random() < 0.5 if comma is None else comma
    if comma and len(n) > 3:
        n = f"{int(n):,}"
    dec = rnd.random() < 0.3 if dec is None else dec
    return n + ("." + "".join(str(rnd.randint(0, 9)) for _ in range(rnd.randint(1, 2))) if dec else "")


def _fz_expr(rnd):
    k = rnd.random()
    if k < 0.24:
        parts = [_fz_digits(rnd, 1, 4, dec=False) + u for u in "조억만천백십" if rnd.random() < 0.45] or [_fz_digits(rnd, 1, 4, dec=False) + "만"]
        if rnd.random() < 0.4:
            parts.append(_fz_digits(rnd, 1, 4, dec=rnd.random() < 0.2))   # 크기 단위 없는 마지막 자리
        e = (" " if rnd.random() < 0.6 else "").join(parts)
    elif k < 0.30:
        e = _fz_digits(rnd, 1, 3, dec=False) + rnd.choice(["만", "천", "백만", "만 5천", ""]) + rnd.choice(["분의 ", "분의"]) + _fz_digits(rnd, 1, 2, dec=False)
    elif k < 0.36:
        e = _fz_digits(rnd, 1, 4) + rnd.choice(["B", "k", "C", "kg", "Q", "bbl"])                 # 숫자에 붙은 영문자
    elif k < 0.50:
        e = _fz_digits(rnd) + "/" + _fz_digits(rnd, 1, 5)
    elif k < 0.70:
        e = _fz_digits(rnd, 1, 4) + rnd.choice([" million", " billion", "million", " trillion", " bn"])
    elif k < 0.80:
        e = ".".join(_fz_digits(rnd, 1, 2, False, False) for _ in range(rnd.randint(3, 4)))   # 판독하지 못하는 이음
    else:
        e = _fz_digits(rnd)
    if rnd.random() < 0.35 and not e[-1].isalpha():
        e += rnd.choice(["%", " %", "%p", "퍼센트", " percent", " percentage points"])
    if rnd.random() < 0.2:
        e = rnd.choice(["-", "−", "+", "− ", "-$", "−$"]) + e                                      # 붙은 부호 · 떨어진 부호 · 통화 기호 건너 부호
    return e


def _fz_spaced_mag(rnd):
    """숫자와 한글 크기 단위 사이에 공백이 있는 표기 — 뒤에 측정 단위가 올 때만 크기 단위로 읽는다."""
    return _fz_digits(rnd, 1, 4, dec=False) + " " + rnd.choice("만억천"), rnd.choice([" 원", " 달러", " 배럴", " 명", " 톤"])


def test_fuzz_fragments_of_a_quantity_never_pass():
    import random
    import re as _re
    N = S.N
    rnd = random.Random(20261111)

    def canon(t):
        return [(x.kind, x.canon) for x in N.scan(t) if x.needs_claim]

    def plain(t):  # 판독부와 독립인 비교: 공백과 쉼표만 지운 글자열(percentage point 의 단수·복수는 같은 말)
        return _re.sub(r"[\s,]", "", t.replace("percentage points", "percentage point"))

    tried = 0
    for _ in range(220):
        if rnd.random() < 0.1:
            e, unit = _fz_spaced_mag(rnd)
        else:
            e, unit = _fz_expr(rnd), rnd.choice(["원", "달러", " 배럴", "명", "", " t", "톤"])
        if e[-1].isalpha() and e[-1].isascii() and unit[:1].isascii() and unit[:1].isalpha():
            unit = " " + unit
        rec = f"가상 지표는 {e}{unit}이다" if unit.strip() and unit[-1] >= "가" else f"가상 지표는 {e}{unit} 수준"
        claims = {CX: claim(CX, text="가상의 섬 통계.", observed=rec)}
        whole = f"가상 {e}{unit} 값"
        assert S.number_errors(slide(body=[whole], claim_ids=[CX]), claims) == [], (e, unit)   # 같은 표기는 통과
        subs = {e[a:b].strip() for a in range(len(e)) for b in range(a + 1, len(e) + 1)}
        for sub in sorted(subs):
            if not sub or plain(sub) == plain(e) or not _re.search(r"\d", sub) or not (sub[0].isdigit() or sub[0] in "-−+"):
                continue
            for tail in (unit, ""):
                body = f"가상 {sub}{tail} 값"
                mine = canon(body)
                assert mine, ("숫자를 못 봄", e, sub + tail)
                tried += 1   # 진부분 문자열은 모두 조각이다 — 판독부가 원래 표현과 같은 수로 읽었더라도 통과하면 안 된다
                assert S.number_errors(slide(body=[body], claim_ids=[CX]), claims), ("조각이 통과", e, sub + tail, mine, canon(rec))
    assert tried > 8000


@pytest.mark.parametrize("shown,recorded", [
    ("70만 1천 5백 배럴", "70만1천5백 배럴"), ("1억 2,345원", "1억2345원"), ("3,300만 개", "3300만 개"), ("1.5 million", "1.5million"),
    ("12 %", "12%"), ("12퍼센트", "12%"), ("2분의 1", "1/2"), ("1/2,000", "1/2000"), ("−3%", "-3%"), ("1.2 bn", "1.2 billion"),
])
def test_same_quantity_in_different_spacing_passes_both_ways(shown, recorded):
    for a, b in ((shown, recorded), (recorded, shown)):
        claims = {CX: claim(CX, text="가상의 섬 통계.", observed=f"가상 지표 {b}")}
        assert S.number_errors(slide(body=[f"가상 {a}"], claim_ids=[CX]), claims) == [], (a, b)


def test_refs_label_follows_source_tier():
    """refs 의 꼬리표는 카드 sources 의 등급을 따른다 — T1·T2(기업·기관 문서)는 '자료', T3 이하는 '보도'(2026-11-13).
    각주와 부록 출처표가 같은 기준을 쓴다. 예시 이름은 지어낸 것이다."""
    sp = spec_of([slide(body=["가상 섬의 계획"], refs=["가상 섬 정부 발표 자료", "가상 일보"])])
    card = {"card_id": "2099-01-02-am-01", "sources": [
        {"name": "가상 섬 정부 발표 자료", "tier": "T1", "url": "https://example.org/gov"},
        {"name": "가상 일보", "tier": "T3", "url": "https://example.org/news"}]}
    assert S.check(sp, {}, TEMPLATE, card=card).ok
    ft = S.footnote_text(sp["slides"][2], {}, card, {})
    assert ft == "자료: 가상 섬 정부 발표 자료  ·  보도: 가상 일보", ft
    rows = B.source_rows(sp, {}, card, {})
    by = {r[1]: r for r in rows}
    assert by["가상 섬 정부 발표 자료"][0] == "자료(T1)" and "문서 인용" in by["가상 섬 정부 발표 자료"][2]
    assert by["가상 일보"][0] == "보도(T3)" and "보도 인용" in by["가상 일보"][2]
    card["sources"][0]["tier"] = "T3"                                 # 등급이 보도면 종전처럼 '보도'
    assert S.footnote_text(sp["slides"][2], {}, card, {}) == "보도: 가상 섬 정부 발표 자료 / 가상 일보"
