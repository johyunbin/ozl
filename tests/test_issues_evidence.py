"""근거 기록 — 원문 받기(가짜 응답)·기계 대조·옛 클레임 모양 사본 시험. 문장은 지어낸 것이다."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import evidence as EV  # noqa: E402
from ozl.issues import ids, model, paths  # noqa: E402
from ozl.research import cards  # noqa: E402
from test_issues_check import I1, PAD, add_official, desk, doc_of, fetcher_of, load  # noqa: E402,F401


def test_capture_and_machine_verify(desk):
    s = "2098년 한빛시 마을버스 운송 적자는 21억 원이었다."
    eid = add_official(I1, s, doc_of("한빛도 재정감사위원회"), unit="원")
    ev = model.load_yaml(paths.evidence_file(I1, eid))
    cap = ev["verification"]["capture"]
    assert cards._inside_captures(cap["path"]) and pathlib.Path(cap["path"]).parent.name == eid
    assert pathlib.Path(cap["text_path"]).read_text(encoding="utf-8").count(s) == 1
    assert ev["verification"]["match"]["found"] and ev["verification"]["verified_at"] and EV.copy_errors(ev) == []
    assert EV.machine_verify_evidence(I1, eid)["ok"] is False                    # 이미 마친 기록은 다시 올리지 않는다
    src = pathlib.Path(cap["path"])
    b = bytearray(src.read_bytes())
    b[-10] ^= 1
    src.write_bytes(bytes(b))
    errs = EV.copy_errors(ev)
    assert errs and "sha256" in errs[0]


def test_capture_rejects_unmatched_and_wrong_kind(desk):
    eid = ids.next_evidence_ids(I1)[0]
    ev = {"evidence_id": eid, "issue_id": I1, "kind": "기관 자료",
          "source": {"url": "https://agency.example/x.html", "publisher": "가상 기관", "tier": "T2", "accessed": "2099-01-02"},
          "observed": "이 문장은 원문에 없다.", "checks": {}, "doc": doc_of("가상 기관"), "revision": 1}
    model.save_evidence(ev)
    body = f"<!doctype html><html><body><p>다른 문장이다.</p><p>{PAD}</p></body></html>".encode()
    r = EV.capture_evidence(I1, eid, fetcher=fetcher_of(body))
    assert not r["ok"] and "observed" in r["reason"]
    assert not EV.machine_verify_evidence(I1, eid)["ok"]
    rep = model.load_evidences(I2 := "i20990101-02")["i20990101-02-e4"]
    assert rep["kind"] == "보도" and not EV.capture_evidence(I2, "i20990101-02-e4", fetcher=fetcher_of(body))["ok"]


def test_as_claim_view_reuses_cards(desk):
    _, evs = load(I1)
    ev = evs[I1 + "-e2"]
    before = repr(ev)
    view = EV.as_claim_view(ev)
    assert view["claim_id"] == ev["evidence_id"] and view["status"] == "verified"
    got = cards.copy_source(view)
    assert got["ok"] and ev["observed"] in got["text"]
    errs, match = cards.machine_check(view, fresh=False)
    assert errs == [] and match["found"] and match["target"]
    view["verification"]["recheck"]["by"] = "agent-a"                         # 사본을 고쳐도 원본은 그대로
    assert repr(ev) == before
    assert any("쓴 쪽과 재대조한 쪽" in e for e in cards.machine_check(view, fresh=False)[0])


def test_raw_material_needs_two_agents(desk):
    ev = {"evidence_id": I1 + "-e9", "kind": "언론 공개 원자료",
          "raw": {"url": "https://news.example/data.csv", "fetched_at": "x", "sha256": "a" * 64, "located": "행 3", "author_by": "agent-a", "recheck_by": "agent-a"}}
    assert any("같다" in e for e in EV.copy_errors(ev))
    ev["raw"]["recheck_by"] = "agent-b"
    assert EV.copy_errors(ev) == []
