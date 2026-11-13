"""새 장 종류(capture_full · photo_caption · image_pair) · 그림 검수 대장(pictures) · 판 상한(progress) · 발표 시간 어림 시험.
네트워크 없이 돈다(임시 폴더의 html 사본과 주입한 응답 · 임시 PNG). 예시 문장, 숫자, 이름은 전부 지어낸 것이다."""
from __future__ import annotations

import copy
import pathlib
import sys
from datetime import datetime, timedelta

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import test_deck_visuals as V  # noqa: E402
from test_deck_visuals import desk  # noqa: E402,F401  (pytest fixture)
from ozl.render import build as B  # noqa: E402
from ozl.render import pictures as PIC  # noqa: E402
from ozl.render import progress as P  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.render.__main__ import main as render_main  # noqa: E402
from ozl.research import cards as C  # noqa: E402

CID, CARD, TEMPLATE = V.CID, V.CARD, V.TEMPLATE


def check(sl, claims, draft=False, pictures=None, extra=()):
    sp = V.spec_of([sl, *extra])
    if pictures is not None:
        sp["pictures"] = pictures
    return S.check(sp, claims, TEMPLATE, draft=draft, layout_fn=B.layout_problems, appendix_fn=B.appendix_problems)


def full(**kw):
    base = {"stage": "근거 수치", "kind": "capture_full", "title": "감자 값 원문", "capture": CID, "claim_ids": [CID], "seconds": 15}
    base.update(kw)
    return base


def photo(**kw):
    base = {"stage": "배경", "kind": "photo_caption", "title": "감자밭", "picture": "p1", "caption": "가상의 섬 감자밭 풍경이다", "seconds": 10}
    base.update(kw)
    return base


def pair(left, right, **kw):
    base = {"stage": "전개", "kind": "image_pair", "title": "감자 두 그림", "claim_ids": [CID],
            "pair": [{**left}, {**right}], "seconds": 20}
    base.update(kw)
    return base


@pytest.fixture
def png(tmp_path):
    from PIL import Image
    p = tmp_path / "pic.png"
    Image.new("RGB", (800, 500), "white").save(p)
    return p


def entry(png, pid="p1", kind="CC BY", **kw):
    e = {"id": pid, "path": str(png), "kind": kind, "source_url": "https://commons.example.org/file/potato.png",
         "origin": "가상 사진가의 개인 누리집", "rights_holder": "가상 사진가", "license": "CC BY 4.0", "commercial_ok": True, "modify_ok": True,
         "attribution": "사진: 가상 사진가", "reverse_search": {"did": "가상 역검색 두 곳에 올렸다", "result": "더 이른 게시를 찾지 못했다"},
         "synthetic_check": "합성 흔적을 찾지 못했다", "content_check": "인물 없음 · 로고 없음 · 지도 아님",
         "checked_at": "2099-01-02T10:00:00+09:00", "as_is": True, "map": False,
         "sha256": PIC.file_sha256(png) if pathlib.Path(png).is_file() else "0" * 64}
    e.update(kw)
    return e


# ── capture_full ─────────────────────────────────────────────────────────
def test_capture_full_accepts_and_uses_the_big_slot(desk):
    c = V.machine_claim(desk, image=False)
    assert check(full(), {CID: c}).errors == []
    size_px, slot_in = S.capture_geom(full())
    assert abs(slot_in - (B.SW - 2 * B.ML)) < 1e-6 and size_px[0] > size_px[1]      # 쪽 폭을 다 쓰는 가로 자리


def test_capture_full_fit_uses_the_new_slot_size(desk):
    """왼쪽 그림 자리에 다 들어가지 않는 대목도 capture_full 의 큰 자리에는 들어간다. 그보다 길면 큰 자리에서도 실패한다."""
    for n, fits in ((60, True), (400, False)):
        long = "가상의 섬 감자 값은 " + "해마다 조금씩 다르게 집계되어 왔고 " * n + "18,250이다."
        body = f"<!doctype html><html><body><p>{long}</p><p>{V.PAD}</p></body></html>".encode("utf-8")
        c = V.machine_claim(desk, image=False, body=body, observed=long, recheck_located=long)
        assert any("다 들어가지 않는다" in e for e in V.errors(V.slide(capture=CID), {CID: c}))
        errs = check(full(), {CID: c}).errors
        assert (errs == []) is fits, errs
        if not fits:
            assert any("원문 캡처를 그릴 수 없다" in e and "다 들어가지 않는다" in e for e in errs), errs


def test_capture_full_required_fields_and_single_visual(desk):
    c = V.machine_claim(desk, image=False)
    sl = full()
    del sl["capture"]
    assert any("capture_full 에는 'capture' 가 있어야 한다" in e for e in check(sl, {CID: c}).errors)
    errs = check(full(image={"what": "감자", "source": "가상 섬 농업청"}), {CID: c}).errors
    assert any("그림 자리는 하나다" in e for e in errs), errs
    assert any("본문 글(body)을 두지 않는다" in e for e in check(full(body=["감자"]), {CID: c}).errors)


def test_capture_full_unaccepted_record_fails_strict_waits_in_draft(desk):
    c = V.pending_claim(desk)
    errs = check(full(), {CID: c}).errors
    assert any(e.startswith("3쪽: capture ") and "사람 대조 전" in e for e in errs), errs
    rep = check(full(), {CID: c}, draft=True)
    assert rep.ok, rep.errors
    assert rep.pending[3] == [CID, S.WAIT_IMAGE + CID]


def test_capture_full_build_pptx_running_sheet_and_appendix(desk):
    from pptx import Presentation
    c = V.machine_claim(desk, image=False)
    sp = V.spec_of([full(spoken="감자 값 원문을 그대로 본다", notes="지어낸 메모")])
    assert S.check(sp, {CID: c}, TEMPLATE, layout_fn=B.layout_problems, appendix_fn=B.appendix_problems).ok
    out = desk / "o" / "f.pptx"
    info = B.build_pptx(sp, {CID: c}, {"card_id": CARD}, out)
    s3 = list(Presentation(str(out)).slides)[2]
    pics = V._pictures(s3)
    assert len(pics) == 1 and pics[0].name == "원문 캡처" and pics[0].width > B.deck.IMG_W * 2
    texts = [sh.text_frame.text for sh in s3.shapes if sh.has_text_frame]
    assert "원문: stats.example.org" in texts and "감자 값 원문" in texts
    assert "그림: 원문 캡처" in s3.notes_slide.notes_text_frame.text
    assert info["appendix"][-1].startswith("부록 · 시각물 출처·검증표(차트·원문 캡처)")
    md = B.running_sheet(sp, {"card_id": CARD}, {CID: c}, "x")
    assert "| 원문 캡처(한 장) c1 |" in md


def test_capture_full_trims_blank_band_but_keeps_ink(desk):
    """큰 자리의 대목 그림은 글 아래가 비어 상자 안에 빈칸이 생긴다 — 글과 표기 줄 사이 흰 띠만 줄이고, 글자와 형광 픽셀 수는 그대로다."""
    from PIL import Image
    c = V.machine_claim(desk, image=False)
    sp = V.spec_of([full()])
    vis = B.render_visuals(sp, {CID: c}, desk / "vis_full")
    png, _, view = vis[(3, -1)]
    assert view == "text_passage"
    size_px, _ = S.capture_geom(full())
    with Image.open(png) as g:
        w, h = g.size
        dark = sum(g.convert("L").histogram()[:245])
    assert w == size_px[0] and h < size_px[1]                      # 폭은 그대로, 높이만 줄었다
    ref = desk / "vis_ref.png"
    B.capture_png(c, ref, size_px, None, B.capture_slot_in(B.plan_slide(full()).imgs[0]))
    with Image.open(ref) as g:
        assert sum(g.convert("L").histogram()[:245]) == dark   # 잉크 픽셀은 하나도 빠지지 않았다
    assert B.trim_passage_gap(png) is False                         # 두 번 줄이지 않는다
    # 왼쪽 그림 자리(image_text)의 대목 그림은 줄이지 않는다
    vis2 = B.render_visuals(V.spec_of([V.slide(capture=CID)]), {CID: c}, desk / "vis_left")
    with Image.open(vis2[(3, -1)][0]) as g:
        assert g.size == S.capture_geom(V.slide(capture=CID))[0]


# ── photo_caption ────────────────────────────────────────────────────────
def test_photo_caption_accepts_and_builds_with_credit(desk, png):
    from pptx import Presentation
    pics = [entry(png)]
    rep = check(photo(), {}, pictures=pics)
    assert rep.ok, rep.errors
    sp = V.spec_of([photo()])
    sp["pictures"] = pics
    out = desk / "o" / "p.pptx"
    info = B.build_pptx(sp, {}, {"card_id": CARD}, out)
    s3 = list(Presentation(str(out)).slides)[2]
    p = V._pictures(s3)
    assert len(p) == 1 and p[0].name == "그림 파일"
    texts = [sh.text_frame.text for sh in s3.shapes if sh.has_text_frame]
    assert "사진: 가상 사진가 · CC BY 4.0" in texts and "가상의 섬 감자밭 풍경이다" in texts
    assert "그림 파일 p1" in s3.notes_slide.notes_text_frame.text
    assert info["appendix"][-1] == "부록 · 시각물 출처·검증표(그림 파일)"
    rows = B.picture_rows(sp)
    assert rows == [["p1", "3", "CC BY", "가상 사진가", "CC BY 4.0", "https://commons.example.org/file/potato.png", "2099-01-02 10:00"]]
    md = B.running_sheet(sp, {"card_id": CARD}, {}, "x")
    assert "| 그림 파일 p1 |" in md


def test_grey_placeholder_fails_in_strict_passes_in_draft():
    """photo_caption · image_pair 의 회색 자리(image)는 그림이 주인공인 장이라 엄격 모드에서 실패('그림 자리' 글이 완성본에 찍히지 않게),
    초안 모드에서는 통과하고 말하지 않는다."""
    grey = {"what": "감자밭 사진 자리", "source": "미정"}
    sl = photo(image=grey)
    del sl["picture"]
    rep = check(sl, {})
    assert not rep.ok and any("회색 자리" in e for e in rep.errors), rep.errors
    draft = check(sl, {}, draft=True)
    assert draft.ok and not any("회색 자리" in w for w in draft.warnings + draft.errors)
    pr = pair({"image": grey, "caption": "왼쪽"}, {"image": grey, "caption": "오른쪽"}, claim_ids=[])
    assert sum("회색 자리" in e for e in check(pr, {}).errors) == 2
    assert check(pr, {}, draft=True).ok


def test_photo_caption_required_fields_and_single_visual(png):
    pics = [entry(png)]
    sl = photo()
    del sl["caption"]
    assert any("photo_caption 에는 'caption' 가 있어야 한다" in e for e in check(sl, {}, pictures=pics).errors)
    sl = photo()
    del sl["picture"]
    assert any("그림 자리에 image · picture 가운데 하나가 있어야 한다" in e for e in check(sl, {}, pictures=pics).errors)
    errs = check(photo(image={"what": "감자밭", "source": "가상 섬 농업청"}), {}, pictures=pics).errors
    assert any("그림 자리는 하나다" in e for e in errs), errs


def test_photo_caption_does_not_take_capture_or_chart(desk):
    c = V.pending_claim(desk)                                    # 엄격 모드에서 받지 않는 기록
    sl = photo(picture=None, capture=CID, claim_ids=[CID])
    errs = check(sl, {CID: c}).errors
    assert any("'capture' 는 photo_caption 의 그림 자리에 쓰지 않는다" in e for e in errs), errs
    assert any("사람 대조 전" in e for e in errs)                 # 인용한 기록 상태도 그대로 본다


def test_photo_caption_caption_follows_number_rule_and_fits(png):
    pics = [entry(png)]
    errs = check(photo(caption="감자 값이 3배 올랐다"), {}, pictures=pics).errors
    assert any("숫자·수량" in e and "claim_ids 가 없다" in e for e in errs), errs
    errs = check(photo(caption="감자밭이 끝없이 이어진다 " * 12), {}, pictures=pics).errors
    assert any("설명:" in e and "줄 넘침" in e for e in errs), errs


# ── image_pair ───────────────────────────────────────────────────────────
BAR = {"kind": "bar", "title": "가상의 섬 감자 값 비교", "unit": "원", "period": "2098년",
       "series": [{"name": "감자", "points": [["1월", "12.5"], ["12월", "18,250"]]}], "source": "가상 섬 통계청", "claims": [CID]}


def test_image_pair_two_charts_accept_and_build(desk):
    from pptx import Presentation
    c = V.machine_claim(desk, image=False)
    sl = pair({"chart": V.line_chart(highlight=[]), "caption": "선으로 본 감자 값"}, {"chart": copy.deepcopy(BAR), "caption": "막대로 본 감자 값"})
    assert check(sl, {CID: c}).errors == []
    sp = V.spec_of([sl])
    out = desk / "o" / "pair.pptx"
    B.build_pptx(sp, {CID: c}, {"card_id": CARD}, out)
    assert sorted(x.name for x in (out.parent / B.VISUALS_DIR).iterdir()) == ["03a_chart.png", "03b_chart.png"]
    s3 = list(Presentation(str(out)).slides)[2]
    charts = V._pictures(s3)
    assert [p.name for p in charts] == ["차트", "차트"] and charts[0].left < charts[1].left
    texts = [sh.text_frame.text for sh in s3.shapes if sh.has_text_frame]
    assert "선으로 본 감자 값" in texts and "막대로 본 감자 값" in texts
    md = B.running_sheet(sp, {"card_id": CARD}, {CID: c}, "x")
    assert "| 왼쪽 자리 차트(선) · 오른쪽 자리 차트(막대) |" in md and "- 3 오른쪽 차트(막대)" in md
    rows = B.visual_check_rows(sp, {CID: c})
    assert [r[0] for r in rows] == ["3 왼", "3 오른"]


def test_image_pair_chart_point_check_is_the_same(desk):
    c = V.machine_claim(desk, image=False)
    bad = copy.deepcopy(BAR)
    bad["series"][0]["points"][0] = ["1월", "12.6"]
    errs = check(pair({"chart": V.line_chart(highlight=[]), "caption": "선"}, {"chart": bad, "caption": "막대"}), {CID: c}).errors
    assert any(e.startswith("3쪽: 오른쪽 자리: chart 계열 '감자' 점 1월: 값 '12.6'") for e in errs), errs


def test_image_pair_required_fields_and_single_visual_per_slot(desk, png):
    c = V.machine_claim(desk, image=False)
    sl = pair({}, {})
    del sl["pair"]
    assert any("image_pair 에는 'pair' 가 있어야 한다" in e for e in check(sl, {CID: c}).errors)
    one = pair({"picture": "p1", "caption": "왼쪽"}, {"picture": "p1"})
    assert any("오른쪽 자리: 짧은 설명(caption)" in e for e in check(one, {CID: c}, pictures=[entry(png)]).errors)
    two = pair({"picture": "p1", "caption": "왼쪽"}, {"chart": V.line_chart(), "capture": CID, "caption": "오른쪽"})
    assert any("오른쪽 자리: 그림 자리는 하나다" in e for e in check(two, {CID: c}, pictures=[entry(png)]).errors)
    three = pair({"picture": "p1", "caption": "왼쪽"}, {"picture": "p1", "caption": "오른쪽"})
    three["pair"].append({"picture": "p1", "caption": "셋째"})
    assert any("그림 자리 두 개" in e for e in check(three, {CID: c}, pictures=[entry(png)]).errors)


def test_image_pair_unaccepted_capture_fails_strict_waits_in_draft(desk, png):
    c = V.pending_claim(desk)
    sl = pair({"capture": CID, "caption": "원문"}, {"picture": "p1", "caption": "사진"})
    errs = check(sl, {CID: c}, pictures=[entry(png)]).errors
    assert any(e.startswith("3쪽: 왼쪽 자리: capture ") and "사람 대조 전" in e for e in errs), errs
    rep = check(sl, {CID: c}, draft=True, pictures=[entry(png)])
    assert rep.ok, rep.errors
    assert rep.pending[3] == [CID, S.WAIT_IMAGE + CID]


# ── 그림 검수 대장 ───────────────────────────────────────────────────────
# 설계 5-7절 그림 종류 표 — 코드 상수를 읽지 않고 표를 그대로 다시 적어 견준다
DESIGN_TABLE = {
    "직접 그린 도표": "쓴다", "직접 그린 지도": "쓴다", "공공누리 1유형": "쓴다", "CC BY": "쓴다",
    "CC BY-SA": "원형 그대로만", "공공누리 3유형": "원형 그대로만", "기업 뉴스룸": "허락 기록이 있을 때만 원형으로",
    "무료 스톡 인물 사진": "쓴다", "로고": "원형 그대로만", "AI 개념도": "쓴다", "밈": "연습용 판에서만",
    "통신사·언론사 사진": "쓰지 않는다", "방송 화면 캡처": "쓰지 않는다", "공공누리 2유형": "쓰지 않는다", "공공누리 4유형": "쓰지 않는다",
    "실존 인물 AI 그림": "쓰지 않는다", "사실처럼 보이는 AI 장면": "쓰지 않는다",
}
LICENSE_FOR = {"공공누리 1유형": "공공누리 제1유형", "공공누리 2유형": "공공누리 제2유형", "공공누리 3유형": "공공누리 제3유형",
               "공공누리 4유형": "공공누리 제4유형", "CC BY-SA": "CC BY-SA 4.0"}
EXTRA_FOR = {"직접 그린 지도": {"map": True, "map_check": {"east_sea": True, "dokdo": True}}, "기업 뉴스룸": {"permission": "가상 뉴스룸 이용 조건 3항을 읽었다"},
             "밈": {"meme_origin": "가상 게시판의 오래된 글에서 시작했다"}}


@pytest.mark.parametrize("kind", list(DESIGN_TABLE))
def test_judge_matches_design_table(png, kind):
    e = entry(png, kind=kind, license=LICENSE_FOR.get(kind, "CC BY 4.0"), **EXTRA_FOR.get(kind, {}))
    assert set(PIC.KIND_RULES) == set(DESIGN_TABLE)
    verdict, why, warns = PIC.judge(e, draft=False)
    assert verdict == DESIGN_TABLE[kind]
    if verdict == "쓰지 않는다":
        assert why and PIC.judge(e, draft=True)[1]                 # 어느 모드에서도 쓰지 않는다
    elif verdict == "연습용 판에서만":
        assert why and not PIC.judge(e, draft=True)[1]             # 초안 모드에서만 쓴다
    else:
        assert not why, why
    assert bool(warns) == (kind == "무료 스톡 인물 사진")


def test_ai_concept_picture_carries_the_mark(desk, png):
    from pptx import Presentation
    e = entry(png, kind="AI 개념도", license="자체 생성", rights_holder="지어낸 제작팀", attribution="지어낸 제작팀 생성")
    assert PIC.credit_lines(e) == [PIC.AI_MARK, "지어낸 제작팀 생성 · 자체 생성"]
    sp = V.spec_of([photo()])
    sp["pictures"] = [e]
    assert S.check(sp, {}, TEMPLATE, layout_fn=B.layout_problems).ok
    out = desk / "o" / "ai.pptx"
    B.build_pptx(sp, {}, {"card_id": CARD}, out)
    texts = [sh.text_frame.text for sh in list(Presentation(str(out)).slides)[2].shapes if sh.has_text_frame]
    assert any(t.startswith(PIC.AI_MARK) for t in texts), texts


def test_empty_field_fails_strict_and_waits_in_draft(desk, png):
    e = entry(png, origin="", reverse_search={"did": "가상 역검색", "result": ""})
    errs = check(photo(), {}, pictures=[e]).errors
    assert any("원출처(origin) 칸이 비었다" in x for x in errs) and any("역검색(reverse_search)" in x for x in errs), errs
    rep = check(photo(), {}, draft=True, pictures=[e])
    assert rep.ok, rep.errors
    assert rep.pending[3] == [S.WAIT_IMAGE + "p1"] and any("그림 대기" in w and "origin" in w for w in rep.warnings)
    from pptx import Presentation
    sp = V.spec_of([photo()])
    sp["pictures"] = [e]
    out = desk / "o" / "wait.pptx"
    B.build_pptx(sp, {}, {"card_id": CARD}, out, pending=rep.pending)
    s3 = list(Presentation(str(out)).slides)[2]
    texts = [sh.text_frame.text for sh in s3.shapes if sh.has_text_frame]
    assert "[그림 대기] p1" in texts and not V._pictures(s3)
    assert B.picture_rows(sp, rep.pending)[0][0] == "p1\n[그림 대기]"
    assert "| 그림 파일 p1 [그림 대기] |" in B.running_sheet(sp, {"card_id": CARD}, {}, "x", rep.pending)


def test_missing_file_and_unknown_id(png, tmp_path):
    errs = check(photo(), {}, pictures=[entry(tmp_path / "없는 그림.png")]).errors
    assert any("그림 파일이 없다" in x for x in errs), errs
    errs = check(photo(picture="p9"), {}, pictures=[entry(png)]).errors
    assert any("p9 가 그림 검수 대장(pictures)에 없다" in x for x in errs), errs
    rep = check(photo(), {}, pictures=[entry(png), entry(png, pid="p2")])
    assert rep.ok and any("쓰지 않은 그림: p2" in w for w in rep.warnings)
    assert any("겹친다" in x for x in check(photo(), {}, pictures=[entry(png), entry(png)]).errors)


def test_as_is_only_license_with_edits_fails(png):
    e = entry(png, kind="CC BY-SA", license="CC BY-SA 4.0", as_is=False, edits="가장자리를 잘랐다")
    errs = check(photo(), {}, pictures=[e]).errors
    assert any("원형 그대로만 쓴다" in x for x in errs), errs
    e = entry(png, kind="공공누리 3유형", license="공공누리 제3유형", as_is=False, edits="글자를 덧칠했다", modify_ok=False)
    errs = check(photo(), {}, pictures=[e]).errors
    assert any("원형 그대로만 쓴다" in x for x in errs) and any("변경이 안 되는 그림" in x for x in errs), errs
    e = entry(png, as_is=False)                                   # 고쳐 썼으면 무엇을 고쳤는지 적는다
    assert any("자르기·덧칠 내용(edits)" in x for x in check(photo(), {}, pictures=[e]).errors)
    assert check(photo(), {}, pictures=[entry(png, as_is=False, edits="가장자리를 잘랐다")]).ok   # CC BY 는 고쳐 써도 된다


def test_blocked_logo_and_other_rules(png, monkeypatch):
    monkeypatch.setattr(PIC, "LOGO_BLOCKED", PIC.LOGO_BLOCKED + ("지어낸 과일 회사",))
    e = entry(png, kind="로고", rights_holder="지어낸 과일 회사", attribution="지어낸 과일 회사 로고", license="상표")
    verdict, why, _ = PIC.judge(e)
    assert verdict == "쓰지 않는다" and any("따로 허락을 요구하는 회사" in x for x in why)
    ok = entry(png, kind="로고", rights_holder="지어낸 채소 회사", attribution="지어낸 채소 회사 로고", license="상표")
    assert not PIC.judge(ok)[1] and PIC.credit_lines(ok) == ["지어낸 채소 회사 로고 · 상표 · " + PIC.TRADEMARK_NOTE]
    assert PIC.judge(entry(png, commercial_ok=False))[0] == "쓰지 않는다"                # 상업적 이용이 안 되면 종류와 상관없이
    assert any("저작자" in x for x in PIC.judge(entry(png, attribution="지어낸 누리집"))[1])  # CC BY 는 저작자 표기
    assert any("NC" in x for x in PIC.judge(entry(png, license="CC BY-NC 4.0"))[1])
    assert any("뉴스룸" in x for x in PIC.judge(entry(png, kind="기업 뉴스룸"))[1])
    assert any("동해와 독도" in x for x in PIC.judge(entry(png, kind="직접 그린 지도", map_check={"east_sea": True}))[1])
    assert any("종류 표에 없다" in x for x in PIC.judge(entry(png, kind="무료 스톡 풍경 사진"))[1])


def test_stock_person_photo_warns(png):
    rep = check(photo(), {}, pictures=[entry(png, kind="무료 스톡 인물 사진")])
    assert rep.ok and any("부정적인 소재" in w for w in rep.warnings), rep.warnings


# ── 밈 ──────────────────────────────────────────────────────────────────
def meme(png, pid="p2"):
    return entry(png, pid=pid, kind="밈", meme_origin="가상 게시판의 오래된 글에서 시작했다", license="CC BY 4.0")


def test_meme_is_dropped_in_strict_and_kept_in_draft(desk, png):
    pics = [entry(png), meme(png)]
    sp = V.spec_of([photo(picture="p2", title="감자 밈"), V.slide(claim_ids=[], picture="p2", body=["감자 이야기"]),
                    pair({"picture": "p1", "caption": "사진"}, {"picture": "p2", "caption": "밈"}, claim_ids=[])])
    sp["pictures"] = pics
    strict_raw = S.check(sp, {}, TEMPLATE, layout_fn=B.layout_problems)
    assert any("밈이다" in e for e in strict_raw.errors)                 # 밈을 빼지 않은 사양을 엄격 검사에 넣으면 실패(안전망)
    dropped_sp, notes = PIC.drop_memes(sp)
    assert len(dropped_sp["slides"]) == len(sp["slides"]) - 1 and len(notes) == 3
    assert notes[0].startswith("3쪽(photo_caption): 밈 p2 을 뺐다 — 쪽을 뺐다")
    rep = S.check(dropped_sp, {}, TEMPLATE, layout_fn=B.layout_problems, appendix_fn=B.appendix_problems)
    assert rep.ok, rep.errors
    md = B.running_sheet(dropped_sp, {"card_id": CARD}, {}, "x", dropped=notes)
    assert "밈 3장을 뺐다" in md and "오른쪽 자리 밈을 뺐다" in md
    assert [r[0] for r in B.picture_rows(dropped_sp)] == ["p1"]
    out = desk / "o" / "m.pptx"
    B.build_pptx(dropped_sp, {}, {"card_id": CARD}, out)
    draft = S.check(sp, {}, TEMPLATE, draft=True, layout_fn=B.layout_problems)
    assert draft.ok and not draft.pending, (draft.errors, draft.pending)   # 초안 모드는 밈을 그대로 둔다
    assert sp["slides"][2]["picture"] == "p2"                              # 원래 사양은 고치지 않는다


def test_check_command_reports_dropped_meme(desk, png, tmp_path, capsys):
    C.save_yaml(C.card_path(CARD), {"card_id": CARD, "date": "2099-01-02", "slot": "am", "titles": ["지어낸 감자 이야기"], "history": []})
    sp = V.spec_of([photo(picture="p2", title="감자 밈")])
    sp["pictures"] = [meme(png)]
    f = tmp_path / "s.yaml"
    f.write_text(yaml.safe_dump(sp, allow_unicode=True), encoding="utf-8")
    assert render_main(["check", str(f)]) == 0
    out = capsys.readouterr().out
    assert "[밈 제외] 3쪽(photo_caption): 밈 p2 을 뺐다" in out and "본편 10장" in out
    assert render_main(["check", str(f), "--draft"]) == 0
    assert "[밈 제외]" not in capsys.readouterr().out


# ── 발표 시간 어림 · 인용 기록 수 ─────────────────────────────────────────
def test_running_sheet_states_speech_estimate_and_record_count(desk):
    c = V.machine_claim(desk, image=False)
    sp = V.spec_of([V.slide(spoken="가" * 450, transition="나 " * 75)])
    n, minutes = B.speech_estimate(sp["slides"])
    assert n == 525 and abs(minutes - 525 / B.SPEAK_CHARS_PER_MIN) < 1e-9
    md = B.running_sheet(sp, {"card_id": CARD}, {CID: c}, "x")
    assert f"발표 시간 어림 {525 / B.SPEAK_CHARS_PER_MIN:.1f}분(말로 할 문장 525자 · 기준 분당 {B.SPEAK_CHARS_PER_MIN}자, 공백 제외)" in md
    assert "인용한 검증 기록 1건" in md


# ── 판 상한 ─────────────────────────────────────────────────────────────
def _card():
    return {"card_id": CARD, "date": "2099-01-02", "slot": "am", "titles": ["지어낸 감자 이야기"], "state": "채택", "history": []}


def _spec_file(tmp_path, k):
    f = tmp_path / f"spec_{k}.yaml"
    f.write_text(f"card_id: {CARD}\nslides: []\n# 판 {k}\n", encoding="utf-8")
    return str(f)


def test_round_cap_marks_incomplete_after_three_rounds_with_major(desk, tmp_path, monkeypatch):
    C.save_yaml(C.card_path(CARD), _card())
    monkeypatch.setattr(P, "spec_major", lambda path: ["검사: 3쪽: 화면의 숫자·수량 ['7'] 가 인용한 클레임에 없다"] if "spec_3" not in path else [])
    t0 = datetime(2099, 1, 2, 9, 0, tzinfo=P.KST)
    P.start(CARD, "세션-가", at=t0)
    for k in (1, 2):
        st = P.mark(CARD, "검토", spec=_spec_file(tmp_path, k), at=t0 + timedelta(minutes=k), by="세션-가")
        assert st["status"] == P.IN_PROGRESS and P.rounds(st) == k and len(P.major_left(st)) == 1
    st = P.mark(CARD, "검토", spec=_spec_file(tmp_path, 3), major=["근거 없는 사실 문장: 4쪽 '감자가 가장 많이 팔렸다'"],
                at=t0 + timedelta(minutes=3), by="세션-가")
    assert st["status"] == P.INCOMPLETE and st["steps"][-1]["step"] == P.INCOMPLETE and st["lease_until"] == ""
    assert "검토 3판/3판 · 남은 큰 오류 1건" in P.summary(P.load(CARD), CARD)
    with pytest.raises(ValueError, match="진행 중이 아니다"):
        P.mark(CARD, "빌드", at=t0 + timedelta(minutes=4), by="세션-가")
    with pytest.raises(ValueError, match="미완성"):
        P.start(CARD, "세션-가", at=t0 + timedelta(minutes=5))
    assert P.start(CARD, "세션-가", force=True, at=t0 + timedelta(minutes=6))["status"] == P.IN_PROGRESS


def test_round_cap_clean_third_round_stays_in_progress_and_done_needs_no_major(desk, tmp_path, monkeypatch):
    C.save_yaml(C.card_path(CARD), _card())
    monkeypatch.setattr(P, "spec_major", lambda path: [])
    t0 = datetime(2099, 1, 2, 9, 0, tzinfo=P.KST)
    P.start(CARD, "세션-가", at=t0)
    P.mark(CARD, "검토", spec=_spec_file(tmp_path, 1), major=["넘침: 5쪽 본문"], at=t0 + timedelta(minutes=1), by="세션-가")
    final = tmp_path / "final"
    final.mkdir()
    for k, s in enumerate(P.STEPS[:-1], 2):
        if s != "검토":
            P.mark(CARD, s, at=t0 + timedelta(minutes=k), by="세션-가")
    with pytest.raises(ValueError, match="큰 오류 1건이 남았다"):
        P.done(CARD, str(final), at=t0 + timedelta(minutes=30), by="세션-가")
    st = P.mark(CARD, "검토", spec=_spec_file(tmp_path, 2), at=t0 + timedelta(minutes=31), by="세션-가")
    assert st["status"] == P.IN_PROGRESS and P.major_left(st) == []
    assert P.done(CARD, str(final), at=t0 + timedelta(minutes=32), by="세션-가")["status"] == P.DONE


def test_old_state_file_without_major_still_works(desk, tmp_path):
    C.save_yaml(C.card_path(CARD), _card())
    t0 = datetime(2099, 1, 2, 9, 0, tzinfo=P.KST)
    old = {"card_id": CARD, "status": P.IN_PROGRESS, "by": "세션-가", "started_at": t0.isoformat(),
           "steps": [{"step": s, "at": t0.isoformat(), "note": "", "digest": ""} for s in P.STEPS[:-1]],
           "updated_at": t0.isoformat(), "lease_until": (t0 + timedelta(hours=6)).isoformat(), "final": ""}
    P.save(CARD, old)
    st = P.load(CARD)
    assert P.rounds(st) == 1 and P.major_left(st) == []
    final = tmp_path / "final"
    final.mkdir()
    assert P.done(CARD, str(final), at=t0 + timedelta(hours=1), by="세션-가")["status"] == P.DONE


# ── 검토 지적 반례(2026-11-14) ──────────────────────────────────────────
@pytest.mark.parametrize("holder", ["Apple Inc", "Apple Korea", "Ａpple", " apple ", "APPLE INC.", "애플코리아", "주식회사 애플"])
def test_blocked_logo_matches_on_word_boundary(png, holder):
    e = entry(png, kind="로고", rights_holder=holder, attribution=f"{holder} 로고", license="상표")
    verdict, why, _ = PIC.judge(e)
    assert verdict == "쓰지 않는다" and any("LOGO_BLOCKED" in x for x in why), (holder, why)


@pytest.mark.parametrize("holder", ["Pineapple Co", "Applebee Farm", "지어낸 채소 회사"])
def test_logo_block_does_not_hit_other_words(png, holder):
    e = entry(png, kind="로고", rights_holder=holder, attribution=f"{holder} 로고", license="상표")
    assert not any("LOGO_BLOCKED" in x for x in PIC.judge(e)[1]), holder


def test_map_check_for_any_kind_that_looks_like_a_map(png):
    e = entry(png, content_check="가상의 반도 지도, 동해 독도 표기 확인 안 함")
    why = PIC.judge(e)[1]
    assert any("동해와 독도" in x for x in why) and any("지도인가(map) 칸이 거짓" in x for x in why), why
    e = entry(png, map=True)                                   # 지도라고 답했으면 확인 기록이 있어야 한다
    assert any("동해와 독도" in x for x in PIC.judge(e)[1])
    ok = entry(png, map=True, content_check="가상의 반도 지도", map_check={"east_sea": True, "dokdo": True})
    assert not PIC.judge(ok)[1]
    assert not PIC.judge(entry(png))[1]                         # '지도 아님' 은 지도가 아니다
    assert any("지도인가(map)" in x for x in PIC.judge(entry(png, map=None))[1])   # 모든 종류가 답해야 하는 칸


@pytest.mark.parametrize("lic", ["CC BY NonCommercial 4.0", "CC BY-NoDerivatives 4.0", "CC BY ShareAlike 4.0", "CC BY 4.0 비영리"])
def test_license_condition_words_are_caught(png, lic):
    why = PIC.judge(entry(png, license=lic))[1]
    assert any("조건이 붙어 있다" in x for x in why), (lic, why)


def test_license_and_flags_must_agree(png):
    e = entry(png, kind="공공누리 1유형", license="공공누리 제1유형 CC BY-NC")
    assert any("commercial_ok) 칸이 참이다" in x for x in PIC.judge(e)[1])
    e = entry(png, kind="공공누리 1유형", license="공공누리 제1유형 CC BY-ND")
    assert any("modify_ok) 칸이 참이다" in x for x in PIC.judge(e)[1])


def test_tiny_picture_and_changed_file_fail(png, tmp_path):
    from PIL import Image
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (40, 30), "white").save(tiny)
    errs = check(photo(), {}, pictures=[entry(tiny)]).errors
    assert any("너무 작다" in x for x in errs), errs
    e = entry(png)
    Image.new("RGB", (800, 500), "black").save(png)             # 검수 뒤 파일이 바뀌었다
    errs = check(photo(), {}, pictures=[e]).errors
    assert any("sha256 이 대장과 다르다" in x for x in errs), errs
    assert any("파일 해시(sha256) 칸이 비었다" in x for x in PIC.judge(entry(png, sha256=""))[1])


def test_credit_numbers_are_limited(png):
    assert any("수 '2087'" in x for x in PIC.judge(entry(png, attribution="사진: 가상 사진가 2087"))[1])
    assert any("수 '1,234'" in x for x in PIC.judge(entry(png, attribution="사진: 가상 사진가 외 1,234명"))[1])
    assert not PIC.judge(entry(png, attribution="사진: 가상 사진가 2099"))[1]   # 확인 시각의 연도는 된다
    assert any("다른 수" in x for x in PIC.judge(entry(png, license="CC BY 4.0 (사진 12장)"))[1])
    assert not PIC.judge(entry(png, kind="공공누리 1유형", license="공공누리 제1유형"))[1]


def test_image_pair_with_two_memes_drops_the_slide(desk, png):
    sp = V.spec_of([pair({"picture": "p2", "caption": "밈 하나"}, {"picture": "p3", "caption": "밈 둘"}, claim_ids=[])])
    sp["pictures"] = [meme(png), meme(png, pid="p3")]
    dropped, notes = PIC.drop_memes(sp)
    assert len(dropped["slides"]) == len(sp["slides"]) - 1 and notes == ["3쪽(image_pair): 두 자리가 다 밈(p2 · p3)이다 — 쪽을 뺐다"]
    both = pair({PIC.DROPPED: "밈"}, {PIC.DROPPED: "밈"}, claim_ids=[])  # 비운 자리 둘이 검사에 오면(안전망) 실패
    assert any("두 자리가 다 비었다" in x for x in check(both, {}).errors)


def test_image_pair_three_slots_is_one_shape_error(desk, png):
    three = pair({"picture": "p1", "caption": "왼쪽"}, {"picture": "p1", "caption": "오른쪽"})
    three["pair"].append({"picture": "p1", "caption": "셋째"})
    errs = check(three, {CID: V.machine_claim(desk, image=False)}, pictures=[entry(png)]).errors
    assert len(errs) == 1 and "그림 자리 두 개" in errs[0] and not any("KeyError" in x for x in errs), errs


def test_capture_context_with_numbers_is_dropped(desk):
    """대목 앞뒤 회색 문맥 문장에 수가 있으면 그 문맥을 빼고 그린다(인용 기록 밖의 수량이 화면에 비치지 않게)."""
    from ozl.research import capture as K
    seen = []
    orig = K._passage_plan

    def spy(before, phrase, after, *a, **kw):
        seen.append((K._ctx_before(before), K._ctx_after(after)))
        return orig(before, phrase, after, *a, **kw)

    body = ("<!doctype html><html><body><p>가상의 섬 배추 값은 12% 올랐다. 가상의 섬 감자 값은 18,250이다. "
            "가상의 섬 무 값은 7.5% 내렸다.</p><p>" + V.PAD + "</p></body></html>").encode("utf-8")
    c = V.machine_claim(desk, image=False, body=body, observed="가상의 섬 감자 값은 18,250이다.", recheck_located="가상의 섬 감자 값은 18,250이다.")
    K._passage_plan = spy
    try:
        B.render_visuals(V.spec_of([full()]), {CID: c}, desk / "vis_ctx")
    finally:
        K._passage_plan = orig
    assert seen and all(b == "" and a == "" for b, a in seen), seen
    assert K._ctx_before("배추 값은 12% 올랐다.") != ""         # 빌드 밖에서는 원래 함수 그대로
