"""원문 확보·문구 대조(src/ozl/research/capture.py)와 기계 대조 등급(cards.machine_verify) 회귀 테스트.
네트워크 없이 돈다(임시 폴더의 html·pdf·xlsx 파일과 주입한 응답). 예시 문장과 숫자는 전부 지어낸 것이다."""
from __future__ import annotations

import copy
import io
import pathlib
import shutil
import sys
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.render import spec as S  # noqa: E402
from ozl.research import cards as C  # noqa: E402
from ozl.research import capture as K  # noqa: E402
from ozl.research import report  # noqa: E402

CARD = "2099-01-02-am-01"
CID = f"{CARD}-c1"
URL = "https://example.org/potato.html"
PAD = "가상의 섬 통계청은 해마다 감자와 당근의 수확량을 집계해 알린다. 이 문서의 수치는 전부 지어낸 것이다. " * 3
HTML = ("<!doctype html><html><head><title>가상 섬 통계</title><script>var leak='4,321톤';</script><style>.x{}</style></head><body>"
        "<h1>가상의 섬 2098년 감자 통계</h1>"
        "<p>2098년 감자 수확량은 4,321톤으로 전년보다 7.5% 늘었다.</p>"
        "<p>같은 해 당근 수출은 -0.8% 줄었다.</p>"
        "<p>참고로 당근 창고 용량은&nbsp;4,321톤이다.</p>"
        f"<p>{PAD}</p></body></html>").encode("utf-8")


class Resp:
    def __init__(self, body: bytes, status=200, ctype="text/html; charset=utf-8", url=URL):
        self.status, self._b, self.headers, self._url = status, io.BytesIO(body), {"Content-Type": ctype}, url

    def geturl(self):
        return self._url

    def read(self, n=-1):
        return self._b.read(n)

    def close(self):
        pass


def opener_of(body, **kw):
    return lambda req, timeout: Resp(body, **kw)


def base_claim(observed="수확량은 4,321톤으로", tier="T1", url=URL):
    return {"claim_id": CID, "card_id": CARD, "text": "가상의 섬 2098년 감자 수확량은 4,321톤이다.", "observed": observed,
            "source": {"url": url, "tier": tier, "publisher": "가상 섬 통계청", "accessed": "2099-01-02", "archived": ""},
            "cross_check": [], "status": "pending",
            "checks": {"unit_ok": True, "base_period": "2098", "real_vs_nominal": "n/a", "seasonally_adjusted": "n/a", "methodology_match": "n/a",
                       "revision_status": "final", "primary_doc_locator": "본문 첫 문단", "recalculated": "n/a", "translation_checked": True},
            "counter": {"core_claim": "가상", "strongest_counter": "가상", "denominator_check": "가상", "residual_uncertainty": "가상"},
            "human_verified": False, "revision": 1}


def recheck(by="agent-b", located="2098년 감자 수확량은 4,321톤으로", **chk):
    checks = {"unit": "톤", "as_of": "2098년", "status": "확정", "population": "가상의 섬 전체", "speaker": "가상 섬 통계청"}
    checks.update(chk)
    return {"by": by, "located": located, "checks": checks, "at": "2099-01-02T10:00:00+09:00"}


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DESK", tmp_path / "desk")
    monkeypatch.setattr(C, "CARDS", tmp_path / "desk" / "cards")
    monkeypatch.setattr(C, "CLAIMS", tmp_path / "desk" / "claims")
    monkeypatch.setattr(C, "PUB_CLAIMS", tmp_path / "claims")
    return tmp_path


def prepare(tmp, claim, body=HTML, author="agent-a", author_located="", rc=None, **opener_kw):
    """capture_claim 으로 사본·대조를 채우고 재대조 기록을 붙여 정본 위치(임시)에 저장한다."""
    got = K.capture_claim(claim, tmp / "captures", C.ROOT, fetcher=lambda u, d: K.fetch(u, d, opener=opener_of(body, **opener_kw)), shot=False)
    claim["verification"] = {"method": "machine", **got, "author": {"by": author, "located": author_located},
                             "recheck": rc if rc is not None else recheck(), "verified_at": ""}
    C.save_yaml(C.claim_path(CID), claim)
    return claim


# ── 문구 대조 ──────────────────────────────────────────────────────────
def test_find_phrase_only_normalizes_whitespace():
    text = "감자 수확량은\n 4,321 톤으로\t늘었다. 또 4,321 톤."
    f = K.find_phrase(text, "수확량은 4,321 톤으로")
    assert f["found"] and f["count"] == 1 and "【수확량은 4,321 톤으로】" in K.context_of(f["matches"][0], "수확량은 4,321 톤으로")
    assert K.find_phrase(text, "4,321 톤")["count"] == 2              # 여러 번이면 전부
    assert not K.find_phrase(text, "4321 톤")["found"]                 # 쉼표를 무시하지 않는다
    assert not K.find_phrase(text, "4,321톤")["found"]                 # 띄어쓰기를 지우지 않는다(공백을 한 칸으로 줄일 뿐)
    assert not K.find_phrase(text, "4.321 톤")["found"]


def test_find_phrase_rejects_pieces_of_longer_numbers():
    text = "당근 수출은 -0.8% 줄었고 출하는 11,234상자, 무게는 12.34톤이었다."
    assert not K.find_phrase(text, "0.8%")["found"] and K.find_phrase(text, "0.8%")["cut"] == 1    # 부호를 뗀 값
    assert K.find_phrase(text, "-0.8%")["found"]
    assert not K.find_phrase(text, "1,234상자")["found"]
    assert not K.find_phrase(text, "12.3")["found"]


def test_pdf_page_offsets_follow_form_feed():
    text = "첫 쪽 글\f둘째 쪽에 감자 4,321톤\f셋째"
    m = K.find_phrase(text, "감자 4,321톤")["matches"][0]
    assert m["page"] == 2 and text[m["raw_offset"]:].startswith("감자")


# ── 글 뽑기 ───────────────────────────────────────────────────────────
def test_html_text_drops_script_and_style(tmp_path):
    p = tmp_path / "a.html"
    p.write_bytes(HTML)
    ex = K.extract_text(p, "html")
    assert ex["ok"] and "leak" not in ex["text"] and ".x{}" not in ex["text"]
    assert K.find_phrase(ex["text"], "4,321톤")["count"] == 2               # 스크립트 안의 값은 세지 않는다


def _xlsx(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   "<si><t>가상 섬 감자 수확량(톤)</t></si><si><t>4,321</t></si></sst>")
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                   '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1"><f>B1*2</f><v>8642</v></c></row>'
                   + "".join(f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>가상의 설명 줄 {i} 지어낸 값</t></is></c></row>' for i in range(2, 12))
                   + "</sheetData></worksheet>")


def test_xlsx_cells_read_without_running_formulas(tmp_path):
    p = tmp_path / "a.xlsx"
    _xlsx(p)
    ex = K.extract_text(p, "xlsx")
    assert ex["ok"] and "가상 섬 감자 수확량(톤)\t4,321\t8642" in ex["text"]


def _pdf(path, lines: list[str] | None):
    """글 한 쪽짜리 최소 PDF(ASCII). lines 가 None 이면 글이 없는 쪽(그림 PDF 처럼 뽑을 글이 없다)."""
    if lines:
        body = "BT /F1 11 Tf 40 800 Td 14 TL " + " ".join(f"({x}) Tj T*" for x in lines) + " ET"
    else:
        body = "0 0 1 rg 10 10 200 200 re f"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(body)} >>\nstream\n{body}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    pathlib.Path(path).write_bytes(out)
    return out


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext 없음")
def test_pdf_text_and_image_pdf_is_unmatchable(tmp_path):
    p = tmp_path / "a.pdf"
    _pdf(p, ["Imaginary Island potato harvest in 2098 was 4,321 tonnes.", "All figures here are invented for a test."] * 2)
    ex = K.extract_text(p, "pdf")
    assert ex["ok"] and K.find_phrase(ex["text"], "4,321 tonnes")["found"]
    q = tmp_path / "b.pdf"
    _pdf(q, None)
    ex = K.extract_text(q, "pdf")
    assert not ex["ok"] and ex["reason"].startswith("프로그램 대조 불가")


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm 없음")
def test_pdf_snapshot_and_failure_is_not_an_exception(tmp_path):
    p = tmp_path / "a.pdf"
    _pdf(p, ["Invented line 4,321 tonnes."])
    r = K.snapshot(CID, p, "pdf", tmp_path / f"{CID}.png", page=1)
    assert r["path"] and pathlib.Path(r["path"]).is_file()
    r = K.snapshot(CID, tmp_path / "없음.pdf", "pdf", tmp_path / "x.png")
    assert r["path"] == "" and r["reason"]
    assert K.snapshot(CID, p, "xlsx", tmp_path / "y.png")["path"] == ""


# ── 원문 확보 ─────────────────────────────────────────────────────────
def test_fetch_saves_copy_with_hash(tmp_path):
    r = K.fetch(URL, tmp_path / "c", opener=opener_of(HTML))
    assert r["ok"] and r["kind"] == "html" and r["bytes"] == len(HTML) and r["status"] == 200
    assert K.sha256_file(r["path"]) == r["sha256"] and r["fetched_at"].endswith("+09:00")


@pytest.mark.parametrize("code", [401, 403, 429])
def test_fetch_blocked_status_is_result_not_exception(tmp_path, code):
    import urllib.error

    def opener(req, timeout):
        raise urllib.error.HTTPError(URL, code, "blocked", {}, None)
    r = K.fetch(URL, tmp_path / "c", opener=opener)
    assert not r["ok"] and r["reason"].startswith("열지 못함") and r["status"] == code and not (tmp_path / "c").exists()


def test_fetch_bot_wall_and_size_cap(tmp_path):
    wall = b"<html><head><title>Just a moment...</title></head><body>Checking your browser. cf-challenge</body></html>"
    r = K.fetch(URL, tmp_path / "w", opener=opener_of(wall))
    assert not r["ok"] and "봇 차단" in r["reason"]
    r = K.fetch(URL, tmp_path / "s", opener=opener_of(b"x" * 2000, ctype="text/plain"), max_bytes=1000)
    assert not r["ok"] and "크기 상한" in r["reason"] and not (tmp_path / "s").exists()


# ── machine_verify 정상 경로 ──────────────────────────────────────────
def test_machine_verify_happy_path(desk):
    prepare(desk, base_claim())
    r = C.machine_verify(CID)
    assert r["ok"], r["reasons"]
    c = C.load_yaml(C.claim_path(CID))
    assert c["status"] == "verified" and c["human_verified"] is False and c["revision"] == 2
    assert C.grade_label(c) == "원문 일치" and C.grade_label(c) != "확인"
    assert C.validate_claim(c, deep=True) == []
    assert c["verification"]["match"]["found"] is True and c["verification"]["verified_at"]
    assert report._claim_mark(c) == "원문 일치"
    errs, pend = S.claim_state_errors([CID], {CID: c})                 # 엄격 모드 덱 검사가 받는다
    assert errs == [] and pend == []
    sl = {"stage": "근거 수치", "kind": "image_text", "title": "감자", "body": ["수확량은 4,321톤으로 늘었다"], "claim_ids": [CID]}
    assert S.number_errors(sl, {CID: c}) == []


def test_running_sheet_does_not_call_machine_match_human(desk):
    from ozl.render import build as B
    prepare(desk, base_claim())
    assert C.machine_verify(CID)["ok"]
    c = C.load_yaml(C.claim_path(CID))
    spec = {"card_id": CARD, "slides": [{"stage": "근거 수치", "title": "감자", "body": ["4,321톤"], "claim_ids": [CID], "seconds": 10}]}
    md = B.running_sheet(spec, {"card_id": CARD}, {CID: c}, "20990102_000000")
    assert "사람이 대조한" not in md and "「원문 일치」 1건" in md and "c1「원문 일치」" in md


def test_human_verified_label_and_old_strict_behaviour_unchanged():
    old = {**base_claim(), "status": "verified", "human_verified": True, "human_verified_at": "x", "human_verified_by": "y"}
    assert C.grade_label(old) == "확인"
    assert S.accepted({"human_verified": True, "status": "single_source"})     # 종전처럼 human_verified 참이면 받는다
    no_bundle = {**base_claim(), "status": "verified"}
    assert any("human_verified 가 아님 — 사람 육안 대조 전에는 pending" in e for e in C.validate_claim(no_bundle))
    assert C.grade_label(no_bundle) == "검증 오류" and not S.accepted(no_bundle)


def test_forged_bundle_fails_structure():
    c = base_claim()
    c["status"] = "verified"
    c["verification"] = {"method": "machine", "capture": {"url": URL, "fetched_at": "t", "sha256": "0", "path": "p", "kind": "html"},
                         "match": {"found": True}, "author": {"by": "a"}, "recheck": recheck(by="A "), "verified_at": "t"}
    assert any("식별자가 같다" in e for e in C.validate_claim(c))
    assert C.grade_label(c) == "검증 오류"


def test_strict_mode_rechecks_evidence_every_time(desk):
    """기록 파일에 verified 라고 적혀 있다는 것만으로는 덱 엄격 모드가 받지 않는다 — 사본과 문구를 쓸 때마다 다시 본다."""
    # (1) 구조는 완전하지만 사본이 없는, 손으로 쓴 묶음
    forged = base_claim()
    forged["status"] = "verified"
    forged["verification"] = {"method": "machine",
                              "capture": {"url": URL, "fetched_at": "t", "sha256": "0" * 64, "path": "private/desk/captures/none/source.html", "kind": "html"},
                              "match": {"found": True}, "author": {"by": "agent-a"}, "recheck": recheck(), "verified_at": "t"}
    assert C.machine_struct_errors(forged) == [] and C.grade_label(forged) == "원문 일치"     # 구조만 보면 통과한다
    errs, _ = S.claim_state_errors([CID], {CID: forged})
    assert errs and "사본 파일이 없다" in errs[0] and not S.accepted(forged)
    # (2) 정상으로 올린 뒤 사본이 바뀐 경우
    prepare(desk, base_claim())
    assert C.machine_verify(CID)["ok"]
    c = C.load_yaml(C.claim_path(CID))
    assert S.accepted(c)
    copy = C._resolve(c["verification"]["capture"]["path"])
    copy.write_bytes(copy.read_bytes().replace("4,321".encode(), "4,399".encode()))
    C._TEXT_CACHE.clear()
    errs, _ = S.claim_state_errors([CID], {CID: c})
    assert errs and "sha256" in errs[0] and not S.accepted(c)
    # (3) 올린 뒤 observed 만 고쳐 쓴 경우
    prepare(desk, base_claim())
    assert C.machine_verify(CID)["ok"]
    c = C.load_yaml(C.claim_path(CID))
    c["observed"] = "수확량은 4,399톤으로"
    errs, _ = S.claim_state_errors([CID], {CID: c})
    assert errs and "observed 가 사본 글에 없다" in errs[0]


def test_card_badge_never_says_confirmed_for_machine_records(desk):
    prepare(desk, base_claim())
    assert C.machine_verify(CID)["ok"]
    c = C.load_yaml(C.claim_path(CID))
    card = {"card_id": CARD, "badge": "verified"}
    assert C.badge_ko(card, [c]) == "원문 일치" and C.badge_label(card, [c]) == "[원문 일치]"
    human = {**base_claim(), "status": "verified", "human_verified": True}
    assert C.badge_ko(card, [human]) == "확인" and C.badge_label(card, [human]) == "[공식 확인]"
    assert C.badge_ko(card, [human, c]) == "원문 일치"                      # 하나라도 섞이면 '확인'이라 하지 않는다
    assert C.badge_ko({"card_id": CARD, "badge": "pending"}, [c]) == "pending"


# ── 올리지 않는 반례 ───────────────────────────────────────────────────
def _refused(desk, claim, **kw):
    prepare(desk, claim, **kw)
    before = C.claim_path(CID).read_bytes()
    r = C.machine_verify(CID)
    assert not r["ok"] and r["reasons"]
    assert C.claim_path(CID).read_bytes() == before                # 아무것도 저장하지 않는다
    return " / ".join(r["reasons"])


def test_refuse_observed_not_in_copy(desk):
    assert "observed 가 사본 글에 없다" in _refused(desk, base_claim(observed="수확량은 5,000톤으로"))


@pytest.mark.parametrize("observed", ["수확량은 4,322톤으로", "2097년 감자 수확량은 4,321톤", "0.8% 줄었다", "+0.8% 줄었다", "4,321 톤으로"])
def test_refuse_altered_number_year_sign(desk, observed):
    assert "observed 가 사본 글에 없다" in _refused(desk, base_claim(observed=observed), rc=recheck(located="같은 해 당근 수출은 -0.8% 줄었다"))


def test_refuse_tampered_copy(desk):
    claim = prepare(desk, base_claim())
    p = pathlib.Path(claim["verification"]["capture"]["path"])
    p.write_bytes(p.read_bytes().replace("7.5%".encode(), "7.6%".encode()))
    r = C.machine_verify(CID)
    assert not r["ok"] and any("sha256" in x for x in r["reasons"])


def test_refuse_same_agent(desk):
    assert "식별자가 같다" in _refused(desk, base_claim(), author="Agent-B", rc=recheck(by="agent-b"))


def test_refuse_recheck_passage_not_in_copy(desk):
    assert "재대조한 쪽 대목(recheck.located) 가 사본 글에 없다" in _refused(desk, base_claim(), rc=recheck(located="감자 수확량은 4,321톤으로 줄었다"))


def test_refuse_recheck_points_to_other_place(desk):
    # 같은 값이 다른 문맥(당근 창고)에도 나오는 문서 — 쓴 쪽은 감자 문장을, 재대조는 창고 문장을 가리켰다
    why = _refused(desk, base_claim(observed="4,321톤"), author_located="감자 수확량은 4,321톤으로 전년보다",
                   rc=recheck(located="당근 창고 용량은 4,321톤이다"))
    assert "통째로 담지 않는다" in why
    # 쓴 쪽이 자리를 가리키지 않으면 여러 번 나오는 값은 올리지 않는다
    assert "author.located" in _refused(desk, base_claim(observed="4,321톤"), rc=recheck(located="감자 수확량은 4,321톤으로"))


def test_same_value_twice_passes_when_both_point_to_same_place(desk):
    prepare(desk, base_claim(observed="4,321톤"), author_located="감자 수확량은 4,321톤으로 전년보다", rc=recheck(located="2098년 감자 수확량은 4,321톤"))
    assert C.machine_verify(CID)["ok"]


@pytest.mark.parametrize("tier", ["T3", "T4", "T5"])
def test_refuse_low_tier(desk, tier):
    assert "기계 대조는 T1/T2" in _refused(desk, base_claim(tier=tier))


@pytest.mark.parametrize("chk,msg", [({"unit": ""}, "unit 비어 있음"), ({"as_of": ""}, "as_of 비어 있음"), ({"status": ""}, "status 비어 있음"),
                                     ({"as_of": "2097년"}, "기준 시점 불일치"), ({"status": "잠정"}, "확정·잠정 불일치"),
                                     ({"status": "전망"}, "확정·잠정 불일치"), ({"status": "모름"}, "status 값 오류")])
def test_refuse_context_blank_or_mismatch(desk, chk, msg):
    assert msg in _refused(desk, base_claim(), rc=recheck(**chk))


def test_refuse_author_unit_not_checked(desk):
    c = base_claim()
    c["checks"]["unit_ok"] = False
    assert "unit_ok" in _refused(desk, c)


def test_refuse_unreadable_document(desk):
    tiny = b"<html><body><img src='chart.png'><p>4,321</p></body></html>" + b" " * 70000   # 표지 검사 밖의 크기 · 뽑힐 글은 거의 없다
    assert "프로그램 대조 불가" in _refused(desk, base_claim(observed="4,321"), body=tiny)


def test_refuse_copy_from_other_url(desk):
    claim = prepare(desk, base_claim())
    claim["verification"]["capture"]["url"] = "https://example.org/other.html"
    C.save_yaml(C.claim_path(CID), claim)
    r = C.machine_verify(CID)
    assert not r["ok"] and any("source.url 과 다르다" in x for x in r["reasons"])


def test_refuse_blocked_fetch(desk):
    import urllib.error

    def blocked(u, d):
        return K.fetch(u, d, opener=lambda req, t: (_ for _ in ()).throw(urllib.error.HTTPError(u, 403, "no", {}, None)))
    claim = base_claim()
    got = K.capture_claim(claim, desk / "captures", C.ROOT, fetcher=blocked, shot=False)
    assert got["capture"]["ok"] is False and got["match"]["found"] is False and got["image"]["reason"]
    claim["verification"] = {"method": "machine", **got, "author": {"by": "a"}, "recheck": recheck(), "verified_at": ""}
    C.save_yaml(C.claim_path(CID), claim)
    assert not C.machine_verify(CID)["ok"]


def test_capture_reuses_one_fetch_per_url(desk):
    calls = []

    def fetcher(u, d):
        calls.append(u)
        return K.fetch(u, d, opener=opener_of(HTML))
    cache: dict = {}
    a = K.capture_claim(base_claim(), desk / "cap", C.ROOT, cache=cache, fetcher=fetcher, shot=False)
    b2 = {**base_claim(), "claim_id": f"{CARD}-c2"}
    b = K.capture_claim(b2, desk / "cap", C.ROOT, cache=cache, fetcher=fetcher, shot=False)
    assert calls == [URL] and a["capture"]["sha256"] == b["capture"]["sha256"] and a["capture"]["path"] != b["capture"]["path"]


def test_machine_verify_cli_with_claims_dir(desk, capsys):
    from ozl.research import __main__ as M
    claim = prepare(desk, base_claim())
    d = desk / "trial"
    d.mkdir()
    shutil.copy2(C.claim_path(CID), d / f"{CID}.yaml")
    C.claim_path(CID).unlink()
    assert M.main(["machine-verify", "--claims-dir", str(d)]) == 0
    assert C.load_yaml(d / f"{CID}.yaml")["status"] == "verified" and not C.CARDS.exists()
    assert claim["status"] == "pending"


def test_old_records_judged_as_before():
    """verification 칸이 없는 옛 기록은 validate_claim 결과와 지문이 이 변경과 무관하다."""
    old = {**base_claim(), "status": "verified", "human_verified": True, "human_verified_at": "x", "human_verified_by": "y"}
    snap = copy.deepcopy(old)
    assert C.validate_claim(old) == [] and C.grade_label(old) == "확인" and old == snap
    card = {"card_id": CARD}
    assert C.content_digest(card, [old]) == C.content_digest(card, [snap])


# ════ 반박 검토(H·M) · Codex 검토(C) 반례 ═══════════════════════════════
import http.client  # noqa: E402
import urllib.error  # noqa: E402

REAL_FETCH = K.fetch


def doc(*sentences: str) -> bytes:
    return ("<!doctype html><html><body>" + "".join(f"<p>{x}</p>" for x in sentences) + f"<p>{PAD}</p></body></html>").encode("utf-8")


# H1 경로 탈출
@pytest.mark.parametrize("bad", ["../escaped_rel", "/tmp/ozl_escape_abs", "2099-01-02-am-01-c1/../../x", "x"])
def test_capture_claim_refuses_bad_claim_id(tmp_path, bad):
    called = []
    with pytest.raises(ValueError):
        K.capture_claim({**base_claim(), "claim_id": bad}, tmp_path / "captures", C.ROOT, fetcher=lambda u, d: called.append(d))
    assert not called and not (tmp_path / "escaped_rel").exists() and not pathlib.Path("/tmp/ozl_escape_abs").exists()


def test_cli_refuses_file_name_claim_id_mismatch(desk, capsys):
    from ozl.research import __main__ as M
    d = desk / "trial"
    d.mkdir()
    C.save_yaml(d / f"{CARD}-c2.yaml", base_claim())          # 파일은 c2, 안의 claim_id 는 c1
    before = (d / f"{CARD}-c2.yaml").read_bytes()
    assert M.main(["capture", "--claims-dir", str(d), "--no-image", "--captures-dir", str(desk / "captures")]) == 1
    assert "파일 이름과 기록의 claim_id 가 다르다" in capsys.readouterr().out
    assert (d / f"{CARD}-c2.yaml").read_bytes() == before and not (desk / "captures").exists()


# H2 + C1 수의 조각 · C2 표 칸
@pytest.mark.parametrize("text,obs,want", [
    ("성장률은 − 0.8%다.", "0.8%", False), ("성장률은 12.8%다.", ".8%", False), ("격차는 5%p다.", "5%", False),
    ("전망치는 3~5%다.", "5%", False), ("예산은 1억2만원이다.", "2만원", False), ("두 수익률은 3%,5%다.", "5%", True),
    ("성장률은 -0.8%다.", "0.8%", False), ("성장률은 -0.8%다.", "-0.8%", True), ("출하는 11,234상자", "1,234상자", False),
    ("△0.8% 감소", "0.8%", False), ("▲0.8% 증가", "0.8%", False), ("▽0.8 하락", "0.8", False), ("▼0.8 하락", "0.8", False),
    ("값 －0.8%", "0.8%", False), ("값 ‐0.8%", "0.8%", False), ("값 ‑0.8%", "0.8%", False), ("값 ﹣0.8%", "0.8%", False),
    ("값 —0.8%", "0.8%", False), ("손실 (0.8) 기록", "0.8", False), ("값 - 0.8%", "0.8%", False), ("값 − 0.8%", "0.8%", False),
    ("값 △ 0.8%", "0.8%", False), ("값 1‍0.8%", "0.8%", False), ("값 1­0.8%", "0.8%", False), ("값 1⁠0.8%", "0.8%", False),
    ("값 １0.8%", "0.8%", False), ("값 10.8%", ".8%", False), ("값 1,234.5 원", "1,234.", False), ("값 △0.8% 감소", "△0.8%", True),
    ("표 2025 64.54 다음", "64.54", True), ("증가율(0.8%) 기록", "0.8%", True), ("인구는 12 345명이다.", "345명", True),   # 마지막은 알려진 한계
    ("A수량\tB수량\n1\t234", "1 234", False), ("감자 수확량은\n4,321톤", "수확량은 4,321톤", True),
])
def test_find_phrase_number_pieces(text, obs, want):
    assert K.find_phrase(text, obs)["found"] is want


# H3 차단·벽·넘김·예외
def test_fetch_http_exceptions_are_results(tmp_path):
    def raising(exc):
        def op(req, t):
            raise exc
        return op
    for exc in (http.client.IncompleteRead(b""), http.client.BadStatusLine("x"), http.client.LineTooLong("header")):
        r = K.fetch(URL, tmp_path / "e", opener=raising(exc))
        assert not r["ok"] and r["reason"].startswith("열지 못함")

    class Broken(Resp):
        def read(self, n=-1):
            raise http.client.IncompleteRead(b"part")
    r = K.fetch(URL, tmp_path / "e2", opener=lambda req, t: Broken(b""))
    assert not r["ok"] and "IncompleteRead" in r["reason"]


@pytest.mark.parametrize("body,ctype", [
    ("<html><head><meta charset='euc-kr'></head><body>서비스 이용을 위해 로그인이 필요합니다</body></html>".encode("cp949"), "text/html"),
    ("﻿<html><body>Just a moment... checking</body></html>".encode("utf-16"), "text/html"),
    (("<html><body><script>" + "x" * 80000 + "</script><p>Access Denied</p></body></html>").encode(), "text/html; charset=utf-8"),
    (b"Access denied. Your request was blocked.", "text/plain"),
    (b'{"error": "captcha required"}', "application/json"),
])
def test_fetch_walls_in_other_encodings_sizes_and_kinds(tmp_path, body, ctype):
    r = K.fetch(URL, tmp_path / "w", opener=opener_of(body, ctype=ctype))
    assert not r["ok"] and "봇 차단·로그인 벽" in r["reason"] and not (tmp_path / "w").exists()


def test_long_real_document_mentioning_access_denied_is_not_a_wall(tmp_path):
    body = doc("이 보고서는 'access denied' 오류가 늘어난 가상의 사례를 다룬다.", "가상의 본문 문장이 이어진다. " * 200)
    r = K.fetch(URL, tmp_path / "ok", opener=opener_of(body))
    assert r["ok"]


def test_fetch_redirect_to_other_host(tmp_path):
    r = K.fetch(URL, tmp_path / "r", opener=opener_of(HTML, url="https://login.example.net/auth"))
    assert not r["ok"] and "다른 호스트로 넘겨짐" in r["reason"]
    r = K.fetch(URL, tmp_path / "r2", opener=opener_of(HTML, url="https://www.example.org/potato.html"))
    assert r["ok"]


@pytest.mark.parametrize("url", ["http://localhost/a", "http://127.0.0.1/a", "http://10.0.0.5/a", "http://192.168.1.2/a",
                                 "http://169.254.169.254/latest", "http://[::1]/a", "ftp://example.org/a", "file:///etc/hosts"])
def test_fetch_refuses_internal_and_non_http(tmp_path, url):
    called = []
    r = K.fetch(url, tmp_path / "i", opener=lambda req, t: called.append(1))
    assert not r["ok"] and not called


def test_fetch_overall_deadline(tmp_path):
    r = K.fetch(URL, tmp_path / "d", opener=opener_of(HTML), deadline=-1)
    assert not r["ok"] and "전체 제한 시간" in r["reason"]


# M1 숨긴 요소
def test_html_hidden_elements_are_not_text():
    raw = ("<html><body><p>보이는 감자 문장 4,321톤.</p>"
           "<div hidden>숨김A 9,991톤</div><span aria-hidden='true'>숨김B 9,992톤</span>"
           "<p style='display: none'>숨김C 9,993톤</p><p style='visibility:hidden'>숨김D 9,994톤</p><p style='font-size:0px'>숨김E 9,995톤</p>"
           "<textarea>숨김F 9,996톤</textarea><select><option>숨김G 9,997톤</option></select>"
           "<script/>숨김H 9,998톤</script><p style='font-size:0.9em'>보이는 작은 글 1,111톤</p></body></html>").encode()
    t = K.html_text(raw)
    assert "4,321톤" in t and "1,111톤" in t
    assert not any(f"9,99{i}" in t for i in range(1, 9))


# M2 xlsx 압축 폭탄 · pdftotext 상한
def test_xlsx_bomb_is_unmatchable(tmp_path):
    p = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b" " * (K.MAX_XLSX_MEMBER + 1))
    assert p.stat().st_size < 1_000_000                          # 작은 압축, 큰 file_size
    ex = K.extract_text(p, "xlsx")
    assert not ex["ok"] and ex["reason"].startswith("프로그램 대조 불가") and "크기 상한" in ex["reason"]


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext 없음")
def test_pdftotext_output_cap(tmp_path):
    p = tmp_path / "a.pdf"
    _pdf(p, ["Invented line about 4,321 tonnes of potatoes on an imaginary island."] * 4)
    with pytest.raises(K._TooBig):
        K._pdftotext(shutil.which("pdftotext"), p, limit=10)


# M4 capture CLI 건너뛰기 · 실제 CLI 호출
def _trial_dir(desk, claim):
    d = desk / "trial"
    d.mkdir(exist_ok=True)
    C.save_yaml(d / f"{claim['claim_id']}.yaml", claim)
    return d


@pytest.mark.parametrize("change,msg", [({"status": "verified"}, "pending 이고"), ({"human_verified": True}, "pending 이고"), (None, "발행 승인된 카드")])
def test_capture_cli_skips(desk, monkeypatch, capsys, change, msg):
    from ozl.research import __main__ as M
    monkeypatch.setattr(K, "fetch", lambda *a, **k: pytest.fail("받으면 안 된다"))
    claim = base_claim()
    if change:
        claim.update(change)
    else:
        C.save_yaml(C.card_path(CARD), {"card_id": CARD, "publish": {"approved": True}})
    d = _trial_dir(desk, claim)
    before = (d / f"{CID}.yaml").read_bytes()
    M.main(["capture", "--claims-dir", str(d), "--no-image", "--captures-dir", str(desk / "captures")])
    assert msg in capsys.readouterr().out and (d / f"{CID}.yaml").read_bytes() == before


def test_capture_cli_writes_bundle(desk, monkeypatch, capsys):
    from ozl.research import __main__ as M
    monkeypatch.setattr(K, "fetch", lambda u, d, **kw: REAL_FETCH(u, d, opener=opener_of(HTML)))
    d = _trial_dir(desk, base_claim())
    assert M.main(["capture", "--claims-dir", str(d), "--no-image", "--author", "agent-a", "--captures-dir", str(desk / "captures")]) == 0
    v = C.load_yaml(d / f"{CID}.yaml")["verification"]
    assert v["capture"]["ok"] and v["match"]["found"] and v["author"]["by"] == "agent-a" and "찾음" in capsys.readouterr().out


# M5 사본 경로
def test_copy_outside_captures_is_refused(desk):
    claim = prepare(desk, base_claim())
    src = pathlib.Path(claim["verification"]["capture"]["path"])
    outside = desk / "elsewhere" / "source.html"
    outside.parent.mkdir()
    shutil.copy2(src, outside)
    for bad in (str(outside), str(desk / "captures" / ".." / "elsewhere" / "source.html")):
        claim["verification"]["capture"]["path"] = bad
        C.save_yaml(C.claim_path(CID), claim)
        r = C.machine_verify(CID)
        assert not r["ok"] and any("captures) 밖" in x for x in r["reasons"])


# M7 그림용 사본
def test_render_copy_blocks_network_and_refresh():
    out = K.render_copy(b'<html><head><meta http-equiv="refresh" content="0;url=https://example.org/x"></head><body>t</body></html>')
    assert b"default-src 'none'" in out and b"refresh" not in out.lower().replace(b"content-security-policy", b"")


# refetch_check
def test_refetch_check(desk):
    claim = prepare(desk, base_claim())
    path = pathlib.Path(claim["verification"]["capture"]["path"])
    before = (path.read_bytes(), C.claim_path(CID).read_bytes())
    calls = []

    def same(u, d):
        calls.append(u)
        return K.fetch(u, d, opener=opener_of(HTML))
    cache: dict = {}
    r = K.refetch_check(claim, fetcher=same, cache=cache)
    assert r["ok"] and r["found"] and r["same_sha"] and r["claim_id"] == CID
    K.refetch_check(claim, fetcher=same, cache=cache)
    assert calls == [URL]                                          # 같은 주소는 한 번만
    changed = K.refetch_check(claim, fetcher=lambda u, d: K.fetch(u, d, opener=opener_of(HTML.replace("4,321톤으로".encode(), "4,000톤으로".encode()))))
    assert changed["ok"] and not changed["found"] and not changed["same_sha"]
    blocked = K.refetch_check(claim, fetcher=lambda u, d: K.fetch(u, d, opener=lambda req, t: (_ for _ in ()).throw(urllib.error.HTTPError(u, 403, "no", {}, None))))
    assert not blocked["ok"] and blocked["reason"]
    assert (path.read_bytes(), C.claim_path(CID).read_bytes()) == before


def test_refetch_check_cli_exit(desk, monkeypatch, capsys):
    from ozl.research import __main__ as M
    prepare(desk, base_claim())
    assert C.machine_verify(CID)["ok"]
    d = desk / "trial"
    d.mkdir()
    shutil.copy2(C.claim_path(CID), d / f"{CID}.yaml")
    monkeypatch.setattr(K, "fetch", lambda u, dd, **kw: REAL_FETCH(u, dd, opener=opener_of(HTML)))
    assert M.main(["capture", "--refetch-check", "--claims-dir", str(d)]) == 0
    monkeypatch.setattr(K, "fetch", lambda u, dd, **kw: REAL_FETCH(u, dd, opener=opener_of(HTML.replace("4,321톤으로".encode(), "4,000톤으로".encode()))))
    assert M.main(["capture", "--refetch-check", "--claims-dir", str(d)]) == 1
    assert "못 찾음" in capsys.readouterr().out


# C3 기준 시점의 종류
@pytest.mark.parametrize("a,b,same", [
    ("2026년 1월", "2026년 1분기", False), ("2026-01", "2026년 1월", True), ("2026-Q1", "2026년 1분기", True), ("2026", "2026년", True),
    ("2026-01-15", "2026년 1월 15일", True), ("2026", "2026-01", False), ("1Q26", "2026-Q1", False), ("2025~2026", "2025년~2026년", True),
    ("2025~2026", "2025~2026-06", False), ("FY2026", "fy2026", True), ("FY2026", "2026", False),
])
def test_period_key_keeps_kind(a, b, same):
    assert (C._period_key(a) == C._period_key(b)) is same


# C4 자리 판정
def test_recheck_must_contain_whole_target(desk):
    why = _refused(desk, base_claim(observed="100억 원"), body=doc("국내 매출은 100억 원이다."), rc=recheck(located="원이다."))
    assert "통째로 담지 않는다" in why


def test_author_location_must_be_one_place(desk):
    body = doc("A사 매출 10억 원. B사 매출 10억 원.")
    why = _refused(desk, base_claim(observed="10억 원"), body=body, author_located="A사 매출 10억 원. B사 매출 10억 원.",
                   rc=recheck(located="B사 매출 10억 원."))
    assert "정해지지 않는다" in why
    prepare(desk, base_claim(observed="10억 원"), body=body, author_located="B사 매출 10억 원.", rc=recheck(located="B사 매출 10억 원."))
    assert C.machine_verify(CID)["ok"]


# C7 발행 판정이 증거를 다시 본다
def _pub_card(claims):
    card = {"card_id": CARD, "badge": "verified", "depth": "light", "data": [{"claim_id": CID}], "publish": {"approved": True}}
    card["publish"]["digest"] = C.content_digest(card, claims)
    return card


def test_publishable_rechecks_machine_evidence(desk):
    forged = base_claim()
    forged["status"] = "verified"
    forged["verification"] = {"method": "machine", "capture": {"url": URL, "fetched_at": "t", "sha256": "0" * 64, "path": "/does/not/exist", "kind": "html"},
                              "match": {"found": True}, "author": {"by": "agent-a"}, "recheck": recheck(), "verified_at": "t"}
    assert C.validate_claim(forged, deep=False) == []
    assert C.publishable(_pub_card([forged]), [forged]) is False
    prepare(desk, base_claim())
    assert C.machine_verify(CID)["ok"]
    good = C.load_yaml(C.claim_path(CID))
    assert C.publishable(_pub_card([good]), [good]) is True
    human = {**base_claim(), "status": "verified", "human_verified": True, "human_verified_at": "t", "human_verified_by": "u"}
    assert C.publishable(_pub_card([human]), [human]) is True


# C8 캐시 키
def test_text_cache_key_includes_kind_and_charset(desk):
    prepare(desk, base_claim())
    assert C.machine_verify(CID)["ok"]
    c = C.load_yaml(C.claim_path(CID))
    C._TEXT_CACHE.clear()
    C.machine_check(c, fresh=False)
    c2 = copy.deepcopy(c)
    c2["verification"]["capture"]["charset"] = "cp949"
    C.machine_check(c2, fresh=False)
    assert len(C._TEXT_CACHE) == 2 and {k[3] for k in C._TEXT_CACHE} == {"utf-8", "cp949"}


# C10 낡은 배지
def test_stale_verified_badge_is_rejudged_from_claims():
    card = {"card_id": CARD, "badge": "verified"}
    pending = base_claim()
    assert C.badge_ko(card, [pending]) == "pending" and C.badge_label(card, [pending]) == "[검증 대기]"
    assert C.badge_ko(card, []) == "pending"
    single = {**base_claim(), "status": "single_source"}
    human = {**base_claim(), "status": "verified", "human_verified": True}
    assert C.badge_ko(card, [human, single]) == "단독"


# ════ Codex 2차 검토 반례 ═══════════════════════════════════════════════
import random  # noqa: E402

import _fuzz_capture as FZ  # noqa: E402


# A1 양끝에 단위가 있는 범위의 한쪽 · A3 공백 없는 긴 문맥 · A2 단위가 낀 표 칸
@pytest.mark.parametrize("text,obs,want", [
    ("전망치는 3%~5%다.", "5%", False), ("전망치는 3%~5%다.", "3%", False), ("전망치는 3%~5%다.", "3%~5%", True),
    ("금액은 3억~5억원이다.", "5억원", False), ("금액은 3억~5억원이다.", "3억~5억원", True), ("금액은 3억원이다.", "3억", True),
    ("격차는 5%p" + "가" * 61, "5%", False), ("예산은 1억2만원" + "가" * 61, "1억", False), ("가" * 61 + "1억2만원", "2만원", False),
    ("가" * 500 + " 값은 3%다", "3%", True),
    ("70\t만 배럴", "70 만 배럴", False), ("…감소한\n4,513억 원", "감소한 4,513억 원", True),
    ("값은 3명\n5명이다", "3명 5명", False), ("값은 3%\n−5%다", "3% −5%", False),
])
def test_find_phrase_ranges_cells_and_long_context(text, obs, want):
    assert K.find_phrase(text, obs)["found"] is want


def test_html_table_cells_are_tab_separated():
    t = K.html_text("<table><tr><td>1억</td><td>2천만원</td></tr><tr><td>가</td><td>나</td></tr></table>".encode())
    assert "1억\t" in t and "\t2천만원" in t
    assert not K.find_phrase(t, "1억 2천만원")["found"]


def test_window_without_space_up_to_limit_is_rejected():
    assert not K.find_phrase("가" * 450 + "3%" + "가" * 450, "3%")["found"]


# A4 무작위 시험 — 문법으로 만든 글과 문구, 만든 방법이 곧 정답(tests/_fuzz_capture.py)
def test_fuzz_quantity_pieces_never_found_and_wholes_found():
    r = random.Random(20261113)
    bad = []
    n = 0
    for _ in range(300):
        text, items = FZ.document(r)
        for q, why in FZ.queries(r, items):
            n += 1
            want = FZ.expected(text, items, q, why)
            if K.find_phrase(text, q)["found"] is not want:
                bad.append((why, want, q, text))
    assert n > 3000 and not bad, bad[:5]


# B1 종류를 바꿔 숨긴 글을 꺼낸다
def test_kind_swap_cannot_reveal_hidden_text(desk):
    body = ("<!doctype html><html><head><script>var v='9876';</script></head><body>"
            f"<p>{PAD}</p></body></html>").encode("utf-8")
    claim = prepare(desk, base_claim(observed="9876"), body=body, rc=recheck(located="9876"))
    claim["verification"]["capture"]["kind"] = "text"
    C.save_yaml(C.claim_path(CID), claim)
    r = C.machine_verify(CID)
    assert not r["ok"] and any("종류를 바꿔 읽지 않는다" in x for x in r["reasons"])


@pytest.mark.parametrize("head,kind,ok", [(b"%PDF-1.4", "html", False), (b"PK\x03\x04", "text", False), (b"<html><body>", "json", False),
                                          (b'{"a": 1}', "json", True), (b"plain words", "text", True), (b"plain words", "pdf", False)])
def test_byte_kind_rule(desk, head, kind, ok):
    p = desk / "captures" / CID / "source.bin"
    p.parent.mkdir(parents=True)
    p.write_bytes(head + b" " * 10)
    c = {"verification": {"capture": {"path": str(p), "kind": kind, "sha256": K.sha256_file(p)}}}
    r = C.copy_source(c)
    assert ("종류를 바꿔 읽지 않는다" in r["reason"]) is (not ok)


# B2 사본 글은 한 곳에서만
def test_spec_copy_text_is_cards_copy_text(desk):
    import inspect
    claim = prepare(desk, base_claim())
    assert S.copy_text(claim) == C.copy_text(claim)
    src = inspect.getsource(S)
    assert "C._" not in src and "_TEXT_CACHE" not in src


# D 대조한 자리 — match.target · 문맥
def test_match_target_is_the_place_rechecked(desk):
    body = doc("A사 매출 10억 원.", "B사 매출 10억 원.")
    prepare(desk, base_claim(observed="10억 원"), body=body, author_located="B사 매출 10억 원.", rc=recheck(located="B사 매출 10억 원."))
    assert C.machine_verify(CID)["ok"]
    m = C.load_yaml(C.claim_path(CID))["verification"]["match"]
    assert m["target"]["nth"] == 1 and "B사 매출 【10억 원】" in m["context"]


@pytest.mark.skipif(not (shutil.which("pdftoppm") and shutil.which("pdftotext")), reason="poppler 없음")
def test_evidence_image_pdf_band_and_passage(tmp_path):
    p = tmp_path / "a.pdf"
    _pdf(p, ["Imaginary Island potato harvest was 4,321 tonnes in 2098.", "Carrot harvest was 4,321 tonnes as well."] + ["Filler line."] * 20)
    text = K.extract_text(p, "pdf")["text"]
    ms = K.find_phrase(text, "4,321 tonnes")["matches"]
    assert len(ms) == 2
    r = K.evidence_image(CID, p, "pdf", text, "4,321 tonnes", ms[1]["offset"], {}, tmp_path / "e.png")
    assert r["path"] and r["view"] == "pdf_band" and r["offset"] == ms[1]["offset"]
    from PIL import Image
    with Image.open(r["path"]) as g:
        assert g.width < 200 / 72 * 595        # 쪽 전체가 아니라 띠로 잘랐다
    h = K.html_text(HTML)
    m = K.find_phrase(h, "수확량은 4,321톤으로")["matches"][0]
    r = K.evidence_image(CID, tmp_path / "x.html", "html", h, "수확량은 4,321톤으로", m["offset"], {"url": URL}, tmp_path / "t.png", size_px=(600, 590))
    assert r["path"] and r["view"] == "text_passage"
    assert K.evidence_image(CID, p, "pdf", text, "4,321 tonnes", 3, {}, tmp_path / "z.png")["path"] == ""   # 대조한 자리가 아니면 그리지 않는다
