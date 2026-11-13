"""이슈 기록 검사기(설계 6절 '코드가 막는 것') 회귀 시험 — 틀린 예마다 그 검사가 없으면 통과해 버리는 최소 자료를 만들어 거부 문구까지 본다.
자료는 전부 지어낸 것이다(가상의 한빛시, 가상의 회사 누리전자). 네트워크를 쓰지 않는다(원문 받기는 가짜 응답을 넣는다)."""
from __future__ import annotations

import copy
import io
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.issues import check, ids, model, paths, rules, style  # noqa: E402
from ozl.issues import evidence as EV  # noqa: E402
from ozl.issues.__main__ import main  # noqa: E402
from ozl.research import capture as K  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "issues"
I1, I2 = "i20990101-01", "i20990101-02"
PAD = "이 문서는 시험용으로 지어낸 가상의 자료이며 실제 기관이나 회사와 관계가 없다. 문장과 수치는 모두 지어낸 것이다. " * 2


# ── 도우미 ────────────────────────────────────────────────────────────
class Resp:
    def __init__(self, body: bytes, url: str):
        self.status, self._b, self.headers, self._url = 200, io.BytesIO(body), {"Content-Type": "text/html; charset=utf-8"}, url

    def geturl(self):
        return self._url

    def read(self, n=-1):
        return self._b.read(n)

    def close(self):
        pass


def fetcher_of(body: bytes):
    return lambda url, dest: K.fetch(url, dest, opener=lambda req, timeout: Resp(body, url))


def make_desk(tmp_path, monkeypatch) -> pathlib.Path:
    """예시 두 건을 시험 루트에 복사하고 근거의 사본 경로를 시험 루트의 captures 로 고쳐 쓴다."""
    root = tmp_path / "desk"
    shutil.copytree(FIX, root / "issues")
    monkeypatch.setenv(paths.ENV, str(root))
    for iid in (I1, I2):
        for eid, ev in model.load_evidences(iid).items():
            model.save_evidence(EV.with_capture_dir(ev, paths.captures_dir(iid)))
    return root


@pytest.fixture
def desk(tmp_path, monkeypatch):
    return make_desk(tmp_path, monkeypatch)


def load(iid):
    return model.load_issue(iid), model.load_evidences(iid)


def errors(issue, evs, public=True):
    return check.check_issue(issue, evs, public=public)["errors"]


def has(errs, path, msg) -> bool:
    return any(f" {path}: " in e and msg in e for e in errs)


def add_official(iid, sentence, doc, kind="기관 자료", unit="n/a", as_of="2098년", base="2098", status="확정", revision="final"):
    """지어낸 html 한 쪽을 원문으로 받아(가짜 응답) 기계 대조까지 마친 근거 기록을 하나 더한다. 근거 번호는 대장에서 받는다."""
    eid = ids.next_evidence_ids(iid)[0]
    url = f"https://agency.example/doc/{eid}.html"
    ev = {"evidence_id": eid, "issue_id": iid, "kind": kind,
          "source": {"url": url, "publisher": doc["speaker"], "title": "시험 문서", "tier": EV.KIND_TIER[kind], "accessed": "2099-01-02 09:00"},
          "observed": sentence,
          "checks": {"unit_ok": True if unit != "n/a" else "n/a", "base_period": base, "real_vs_nominal": "n/a", "seasonally_adjusted": "n/a",
                     "methodology_match": "n/a", "revision_status": revision, "primary_doc_locator": "첫 문단", "recalculated": "n/a",
                     "translation_checked": "n/a"},
          "doc": doc, "revision": 1}
    model.save_evidence(ev)
    body = f"<!doctype html><html><body><h1>시험 문서</h1><p>{sentence}</p><p>{PAD}</p></body></html>".encode()
    assert EV.capture_evidence(iid, eid, fetcher=fetcher_of(body))["ok"]
    ev = model.load_yaml(paths.evidence_file(iid, eid))
    ev["verification"]["author"] = {"by": "agent-a", "located": ""}
    ev["verification"]["recheck"] = {"by": "agent-b", "located": sentence, "checks": {"unit": unit, "as_of": as_of, "status": status}, "at": "x"}
    model.save_evidence(ev)
    res = EV.machine_verify_evidence(iid, eid)
    assert res["ok"], res["reasons"]
    return eid


def doc_of(speaker, role="제3기관", kind="조사 보고서", stage="확정된 판단", authority=True, transcribed=False, **kw):
    return {"speaker": speaker, "speaker_role": role, "doc_kind": kind, "doc_stage": stage, "authority": authority, "transcribed": transcribed, **kw}


def claim(issue, cid):
    return next(c for c in issue["claims"] if c["id"] == cid)


def new_claim(iid, issue, **kw):
    cid = ids.next_item_ids(iid, "c")[0]
    c = {"id": cid, "gist": "", "kind": "사실", "subject": "", "period": "2098년", "scope": "", "spread": {"where": "기사", "first_seen": "2099-01-02", "links": []},
         "verdict": "확인", "searched": "시험 범위", "counter_searched": True, "evidence": [], "party_position": {"none": True, "checked_at": "2099-01-02"},
         "allegation": False, "target_kind": "기관과 정책", "publish": "게시 가능", "numbers": []}
    c.update(kw)
    issue["claims"].append(c)
    return c


def link(eid, stance, basis, cl, **kw):
    d = {"id": eid, "stance": stance, "basis": basis, "subject": cl["subject"], "period": cl.get("period"), "scope": cl["scope"],
         "passage_role": "작성자의 판단"}
    if cl.get("kind") == "수치":
        d["unit"] = cl["unit"]
    d.update(kw)
    return d


# ── 시험 ──────────────────────────────────────────────────────────────
def test_examples_pass(desk):
    for iid in (I1, I2):
        r = check.check_issue(*load(iid), public=True)
        assert r == {"errors": [], "warnings": []}, r
    assert main(["check", "--all", "--public"]) == 0
    assert main(["check"]) == 2
    issue, _ = load(I1)
    assert issue["example"] is True and rules.hidden_claims(issue) == 0
    assert rules.hidden_claims(load(I2)[0]) == 2           # 공개 제외 1건 + 보류 1건 = "이 밖에 다루지 않은 주장"
    issue["reason"] = ""
    model.save_issue(issue)
    assert main(["check", I1]) == 1


def test_reject_denial_only_false(desk):
    issue, evs = load(I1)
    eid = add_official(I1, "한빛시는 버스 운송 적자가 200억 원이라는 말은 사실이 아니라고 밝혔다.",
                       doc_of("한빛시", role="당사자", kind="보도자료", stage="작성자 자신의 발표", authority=False,
                              admission={"kind": "부인", "scope": "시내버스 전체", "against_interest": False}),
                       kind="공식 원문", unit="원", as_of="2098년")
    evs = model.load_evidences(I1)
    c = claim(issue, "c1")
    for basis in ("나", "없음"):
        c["evidence"] = [link(eid, "반대", basis, c, passage_role="사실 기재")]
        errs = errors(issue, evs)
        assert has(errs, "claims.c1.verdict", rules.MSG_DENIAL_ONLY), errs


def test_allow_institution_denies_own_document(desk):
    issue, _ = load(I1)
    eid = add_official(I1, "한빛통계원은 요금 인상을 권고하는 자료를 낸 적이 없다.",
                       doc_of("한빛통계원", role="당사자", kind="보도자료", stage="작성자 자신의 발표", authority=False, denies_own_document=True),
                       kind="공식 원문", base="n/a", as_of="n/a", revision="n/a", status="확정")
    evs = model.load_evidences(I1)
    c = new_claim(I1, issue, kind="발표 여부", attributed_to="한빛통계원", gist="한빛통계원이 요금 인상을 권고하는 자료를 냈다.",
                  subject="한빛통계원의 요금 인상 권고 자료", period="해당 없음", scope="한빛통계원 발표", verdict="사실과 다름")
    c["evidence"] = [link(eid, "반대", "없음", c, passage_role="사실 기재")]
    issue["so_far_refs"].append(c["id"])
    assert errors(issue, evs) == []
    other = copy.deepcopy(issue)
    claim(other, c["id"])["attributed_to"] = "한빛시"
    assert has(errors(other, evs), f"claims.{c['id']}.verdict", rules.MSG_NO_OPPOSE)
    evs[eid]["doc"]["denies_own_document"] = False
    assert has(errors(issue, evs), f"claims.{c['id']}.verdict", rules.MSG_NO_OPPOSE)


def test_reject_investigation_doc_confirmed(desk):
    issue, _ = load(I1)
    eid = add_official(I1, "한빛시 감사관실은 기본요금 인상 폭 400원의 산정 과정을 조사하고 있다.",
                       doc_of("한빛시 감사관실", stage="조사 중"), unit="원", as_of="2099년", base="2099")
    evs = model.load_evidences(I1)
    c = claim(issue, "c4")
    c["evidence"] = [link(eid, "지지", "가", c)]
    errs = errors(issue, evs)
    assert has(errs, "claims.c4.verdict", rules.MSG_INVESTIGATION), errs


def _ruling_claim(issue, evs, final=True, role="작성자의 판단", addresses=True):
    c = claim(issue, "c3")
    c.update(verdict="확인", counter_searched=True)
    c["evidence"][0].update(basis="가", passage_role=role, addresses_cause=addresses)
    evs["i20990101-02-e3"]["doc"]["court"]["final"] = final
    return c


def test_reject_transcribed_as_judgment(desk):
    issue, evs = load(I2)
    _ruling_claim(issue, evs, final=True, role="작성자의 판단")
    assert errors(issue, evs) == []                                   # 확정 판결의 판단 대목이면 받친다
    issue, evs = load(I2)
    _ruling_claim(issue, evs, final=True, role="당사자 주장을 옮긴 것")
    assert has(errors(issue, evs), "claims.c3.evidence.i20990101-02-e3", rules.MSG_TRANSCRIBED)
    issue, evs = load(I2)
    _ruling_claim(issue, evs, final=True)
    evs["i20990101-02-e3"]["doc"]["transcribed"] = True
    assert has(errors(issue, evs), "claims.c3.evidence.i20990101-02-e3", rules.MSG_TRANSCRIBED)


def test_reject_unfinal_ruling(desk):
    issue, evs = load(I2)
    _ruling_claim(issue, evs, final=False)
    errs = errors(issue, evs)
    assert has(errs, "claims.c3.evidence.i20990101-02-e3", rules.MSG_UNFINAL) and has(errs, "claims.c3.verdict", rules.MSG_NO_SUPPORT)


def test_reject_partial_period(desk):
    issue, evs = load(I1)
    claim(issue, "c1")["evidence"][0]["period"] = "2098년 2분기"
    assert has(errors(issue, evs), "claims.c1.verdict", "근거의 기간(2098년 2분기)과 주장의 기간(2098년)이 다르다 — 일부 기간을 전체로 넓히지 않는다")


@pytest.mark.parametrize("field,value,label", [("subject", "한빛시 마을버스 운송 적자", "대상"), ("scope", "간선버스", "범위"), ("unit", "달러", "단위")])
def test_reject_subject_scope_unit_mismatch(desk, field, value, label):
    issue, evs = load(I1)
    claim(issue, "c1")["evidence"][0][field] = value
    errs = errors(issue, evs)
    assert has(errs, "claims.c1.verdict", rules.MSG_NO_OPPOSE) and has(errs, "claims.c1.verdict", f"근거의 {label}({value})"), errs
    claim(issue, "c1")["evidence"][0][field] = ""
    assert has(errors(issue, evs), "claims.c1.verdict", f"근거 연결의 {label} 칸이 비어 있다")


@pytest.mark.parametrize("change", [{"unverified_reasons": []}, {"unverified_reasons": ["그냥"]}, {"would_decide": ""}, {"searched": ""}])
def test_reject_unverified_without_reason(desk, change):
    issue, evs = load(I1)
    claim(issue, "c3").update(change)
    assert has(errors(issue, evs), "claims.c3.verdict", rules.MSG_UNVERIFIED)


def test_reject_official_number_not_in_evidence(desk):
    issue, evs = load(I1)
    f = issue["facts"][0]
    f["text"] = f["text"].replace("400원", "500원")
    f["numbers"] = [{"value": "500원", "kind": "공식", "evidence": I1 + "-e1"}]
    assert has(errors(issue, evs), "facts.f1.text", f"공식 수치 '500원'이 인용한 근거({I1}-e1) 원문에 같은 표기로 없다")
    f["numbers"] = [{"value": "500원", "kind": "공식", "evidence": I1 + "-e2"}]     # 인용하지 않은 근거로 받칠 수 없다
    assert has(errors(issue, evs), "facts.f1.text", "이 글이 인용한 근거가 아니다")


def test_reject_unlabeled_number(desk):
    issue, evs = load(I1)
    issue["facts"][0]["numbers"] = []
    assert has(errors(issue, evs), "facts.f1.text", "의 종류(공식, 주장, 계산)를 적지 않았다")
    issue, evs = load(I1)
    issue["numbers"]["what_new"][0]["kind"] = "추정"
    assert has(errors(issue, evs), "what_new", "허용 값(공식, 주장, 계산)이 아니다")


def test_claimed_number_only_in_claim_fields(desk):
    issue, evs = load(I1)
    assert errors(issue, evs) == []                                    # 주장 요지와 refutes 를 단 지금까지 3줄은 통과
    claim(issue, "c1")["searched"] = "적자 200억 원이라는 글, 시 결산서"
    assert has(errors(issue, evs), "claims.c1.searched", "주장 속 값 '200억 원'은 주장 요지와 퍼진 곳에만 쓴다")
    issue, evs = load(I1)
    del issue["numbers"]["so_far.2"][0]["refutes"]
    assert has(errors(issue, evs), "so_far.2", "주장 속 값 '200억 원'")


@pytest.mark.parametrize("change,msg", [({"formula": "결산연도 - 근거연도 + 1"}, "다시 계산한 값(4)과 다르다"),
                                         ({"rounding": "적당히"}, "rounding 은"),
                                         ({"formula": "abs(결산연도 - 근거연도)"}, "식을 계산하지 못했다"),
                                         ({"inputs": {"결산 연도": "2098"}, "formula": "2098 - 2095"}, "수로 읽지 못했다")])
def test_computed_number_recomputed(desk, change, msg):
    issue, evs = load(I1)
    issue["numbers"]["so_far.1"][0].update(change)
    assert has(errors(issue, evs), "so_far.1", msg)


def test_reject_private_person_items(desk):
    issue, evs = load(I2)
    claim(issue, "c5")["publish"] = "게시 가능"
    assert has(errors(issue, evs), "claims.c5.publish", rules.MSG_PRIVATE)
    issue, evs = load(I2)
    issue["titles"]["target_kind"] = "일반인"
    assert has(errors(issue, evs), "titles.target_kind", rules.MSG_PRIVATE)
    issue, evs = load(I2)
    gid = ids.next_item_ids(I2, "g")[0]
    issue["figures"].append({"id": gid, "kind": "직접 그린 도표", "caption": "회수 절차", "alt": "회수 절차를 그린 도표",
                             "target_kind": "공인의 사생활", "publish": "게시 가능"})
    assert has(errors(issue, evs), f"figures.{gid}.publish", rules.MSG_PRIVATE)
    issue["figures"][0]["publish"] = "공개 제외"
    assert errors(issue, evs) == []


def test_reject_crime_word_title(desk):
    issue, _ = load(I1)
    eid = add_official(I1, "한빛지방법원은 시 회계 담당자의 공금 횡령을 유죄로 확정했다.",
                       doc_of("한빛지방법원", kind="판결", court={"level": "대법원", "final": True}))
    evs = model.load_evidences(I1)
    c = new_claim(I1, issue, gist="시 회계 담당자의 공금 횡령이 확정됐다.", subject="한빛시 회계 담당자의 공금 횡령", scope="한빛시 회계",
                  allegation=True, target_kind="공인의 공적 활동")
    c["evidence"] = [link(eid, "지지", "가", c)]
    t = "버스 400원 인상, 시 회계 횡령 확정 판결도"
    issue["titles"]["candidates"][0]["text"] = issue["titles"]["chosen"] = t
    issue["titles"]["basis_claims"] = []
    assert has(errors(issue, evs), "titles.chosen", style.MSG_CRIME)
    issue["titles"]["basis_claims"] = [c["id"]]
    assert errors(issue, evs) == []
    evs[eid]["doc"]["court"]["final"] = False                       # 확정되지 않은 판결이면 예외도 풀린다
    assert has(errors(issue, evs), "titles.chosen", style.MSG_CRIME)


def test_reject_side_only_partial(desk):
    issue, evs = load(I1)
    p1, p2 = claim(issue, "c5")["parts"]
    p1["core"], p2["core"] = False, True
    assert has(errors(issue, evs), "claims.c5.verdict", rules.MSG_SIDE_ONLY)


def test_reject_causal_without_cause_doc(desk):
    issue, evs = load(I2)
    _ruling_claim(issue, evs, final=True, addresses=False)
    assert has(errors(issue, evs), "claims.c3.verdict", rules.MSG_CAUSE)
    issue, evs = load(I2)
    _ruling_claim(issue, evs, final=True, addresses=True)
    evs["i20990101-02-e3"]["doc"].update(doc_kind="처분")
    del evs["i20990101-02-e3"]["doc"]["court"]
    assert has(errors(issue, evs), "claims.c3.verdict", rules.MSG_CAUSE)
    issue, evs = load(I2)
    _ruling_claim(issue, evs, final=True, addresses=True)
    assert errors(issue, evs) == []


def test_reject_admission_beyond_scope(desk):
    issue, evs = load(I2)
    c = claim(issue, "c2")
    c["scope"] = c["evidence"][0]["scope"] = "회수 대상 제품의 교환 비용 전체"
    errs = errors(issue, evs)
    assert has(errs, "claims.c2.evidence.i20990101-02-e2", "인정한 범위까지만 근거로 센다") and has(errs, "claims.c2.verdict", rules.MSG_NO_SUPPORT)


def test_company_disclosure_needs_label(desk):
    issue, evs = load(I2)
    del claim(issue, "c2")["basis_label"]
    assert has(errors(issue, evs), "claims.c2.basis_label", rules.MSG_DISCLOSURE)


def test_reject_report_only_confirmed(desk):
    issue, evs = load(I2)
    c = claim(issue, "c4")
    c.update(verdict="확인", counter_searched=True, allegation=False)
    assert has(errors(issue, evs), "claims.c4.verdict", rules.MSG_NO_SUPPORT)
    c["evidence"][0].update(basis="다", refers_to_original=True)
    assert has(errors(issue, evs), "claims.c4.evidence.i20990101-02-e4", "보도는 판정의 근거로 세지 않는다")


@pytest.mark.parametrize("kind", ["평가", "전망"])
def test_reject_evaluation_as_claim(desk, kind):
    issue, evs = load(I1)
    claim(issue, "c3")["kind"] = kind
    assert has(errors(issue, evs), "claims.c3.kind", rules.MSG_EVAL)


def test_reject_blank_reason_publishable(desk):
    issue, evs = load(I1)
    issue["reason"] = ""
    assert has(errors(issue, evs, public=False), "reason", rules.MSG_REASON)
    issue["publish"] = {"state": "보류", "why": "검토 중"}
    assert not any(" reason: " in e for e in errors(issue, evs, public=False))


def test_election_fields_and_mask(desk):
    issue, evs = load(I1)
    issue["sensitive"] = ["선거"]
    errs = errors(issue, evs)
    assert has(errs, "election", check.MSG_ELECTION) and has(errs, "claims.c1.election_mask", "election_mask")
    for lst in ("facts", "claims", "flow", "stances", "open_questions"):
        for it in issue[lst]:
            it["election_mask"] = False
    issue["election"] = {"kind": "시장 선거", "date": "2099-03-01", "poll_close": "18:00", "restrict_from": "2099-02-23",
                         "schedule_url": "https://election.example/2099"}
    assert errors(issue, evs) == []
    issue["election"]["restrict_from"] = "2099-02-20"
    assert has(errors(issue, evs), "election", check.MSG_ELECTION)
    issue["election"]["restrict_from"] = "2099-02-23"
    issue["stances"][0]["summary"] = "시장 후보 지지율에도 영향이 있다고 봤다."
    assert has(errors(issue, evs), "stances.s1.election_mask", style.MSG_POLL)
    issue["stances"][0]["election_mask"] = True
    assert errors(issue, evs) == []


def test_unconfirmed_event(desk):
    issue, evs = load(I1)
    issue["event_check"] = {"confirmed": False, "evidence": None, "at": None}
    assert has(errors(issue, evs), "facts.f1.kind", rules.MSG_EVENT)
    issue["facts"][0]["kind"] = "사실"
    errs = errors(issue, evs)
    assert has(errs, "claims.c4.premise_event", rules.MSG_PREMISE)         # 빈 칸을 '전제 아님'으로 읽지 않는다
    assert has(errs, "claims.c5.parts.p1.premise_event", rules.MSG_PREMISE)
    for c in issue["claims"]:
        c["premise_event"] = False
    assert errors(issue, evs) == []
    claim(issue, "c1")["premise_event"] = True
    assert has(errors(issue, evs), "claims.c1.verdict", rules.MSG_EVENT)


@pytest.mark.parametrize("change", [lambda e: e.update(observed="기사 본문 한 대목"), lambda e: e["report"].update(body="기사 본문")])
def test_report_evidence_no_body(desk, change):
    issue, evs = load(I2)
    change(evs["i20990101-02-e4"])
    assert any("evidence.i20990101-02-e4" in x and EV.MSG_REPORT_BODY in x for x in errors(issue, evs))


def test_community_link_rejected(desk):
    issue, evs = load(I2)
    claim(issue, "c4")["spread"]["links"] = [{"outlet": "게시판", "url": "https://gall.dcinside.com/board/1"}]
    assert has(errors(issue, evs), "claims.c4.spread.links.0.url", EV.MSG_COMMUNITY)
    issue, evs = load(I2)
    evs["i20990101-02-e4"]["source"]["url"] = "https://www.clien.net/service/board/1"
    assert has(errors(issue, evs), "evidence.i20990101-02-e4.source.url", EV.MSG_COMMUNITY)


def test_announcement_needs_official(desk):
    issue, evs = load(I2)
    issue["facts"][1]["evidence"] = ["i20990101-02-e4"]
    assert has(errors(issue, evs), "facts.f2.evidence", check.MSG_ANNOUNCE)


def test_false_claim_in_so_far(desk):
    issue, evs = load(I1)
    issue["so_far_refs"] = ["c2"]
    assert has(errors(issue, evs), "so_far_refs", rules.MSG_SO_FAR.format("c1"))
    claim(issue, "c1")["publish"] = "보류"                                 # 게시되지 않는 주장이면 묻지 않는다
    assert not has(errors(issue, evs), "so_far_refs", rules.MSG_SO_FAR.format("c1"))


def test_capture_outside_captures(desk, tmp_path):
    issue, evs = load(I1)
    ev = evs[I1 + "-e2"]
    cap = ev["verification"]["capture"]
    out = tmp_path / "elsewhere" / "source.html"
    out.parent.mkdir()
    shutil.copy2(cards_resolve(cap["path"]), out)                         # 해시는 그대로인 같은 파일
    cap["path"] = str(out)
    errs = errors(issue, evs)
    assert has(errs, f"evidence.{I1}-e2.verification.capture.path", "원문 사본이 captures 폴더 밖에 있다")
    assert has(errs, "claims.c1.evidence." + I1 + "-e2", "원문 재검사를 통과하지 못했다")


def cards_resolve(p):
    from ozl.research import cards
    return cards._resolve(p)
