"""게시 승인 화면과 승인 요청(설계 5절, 11절) — 지어낸 이슈(tests/fixtures/issues)와 지어낸 화제 목록만 쓴다.

승인은 화면의 폼 값 그대로 보낸다. 시험 자료 루트라 승인한 쪽은 늘 '시험'이고, 실제 private/desk 의 발행 목록은 시험 앞뒤로 같다.
"""
from __future__ import annotations

import copy
import html
import json
import os
import re

import pytest

from test_ops_support import desk, ops, real_untouched  # noqa: F401

from ozl.issues import digest, model, paths, revisions, style, units
from ozl.ops import approvals, approve_view

pytestmark = pytest.mark.usefixtures("real_untouched")
I1, I2 = "i20990101-01", "i20990101-02"
DATE = "2099-01-02"


# ---------- 도우미(e2e 도 가져다 쓴다) ----------

def add_review(iid: str, kind: str, by_model: str, family: str, result: str = "통과") -> dict:
    d = revisions.notes_dir(iid)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"note_{len(list(d.iterdir())) + 1}.md"
    f.write_text(f"{kind} {by_model} {result} — 시험용으로 지어낸 검토 원문\n", encoding="utf-8")
    return revisions.add_review(iid, kind, by_model, family, result, notes_path=str(f))


def ready(iid: str, n_reviews: int = 2) -> str:
    issue = model.load_issue(iid)
    issue["work_state"] = "게시 대기"
    model.save_issue(issue)
    if n_reviews >= 1:
        add_review(iid, "문장 대조", "Claude Sonnet", "anthropic")
    if n_reviews >= 2:
        add_review(iid, "해석 점검", "가상 모델 G", "openai")
    return digest.content_hash(model.load_issue(iid), model.load_evidences(iid))


def approve_forms(text: str) -> list[dict]:
    out = []
    for block in re.findall(r'<form method="post" action="/approve"[^>]*>(.*?)</form>', text, re.S):
        out.append({html.unescape(k): html.unescape(v) for k, v in
                    re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', block)})
    return out


def form_for(text: str, target: str) -> dict:
    f = [x for x in approve_forms(text) if x.get("target") == target]
    assert len(f) == 1, target
    return f[0]


def manifest() -> dict:
    p = paths.manifest_file()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"entries": [], "withdrawn": []}


def visible_chunks(text: str) -> list[str]:
    """보이는 글 조각. 이슈 번호는 운영자가 대기열·승인 기록과 맞춰 보는 식별자라 설계 5절대로 보이고, 검사에서는 뺀다."""
    text = re.sub(r"i\d{8}-\d{2}", "", re.sub(r"<[^>]+>", "\n", text))
    return [c.strip() for c in text.split("\n") if c.strip()]


# ---------- 시험 ----------

def test_approve_from_screen(ops):
    c = ops.client
    h = ready(I1)
    st, _, text = c.get("/approve")
    assert st == 200 and "로그인" in text and not approve_forms(text)     # 로그인 전에는 폼이 없다
    c.login()
    st, _, text = c.get("/approve")
    f = form_for(text, I1)
    assert f["kind"] == "issue" and f["rev"] == "1" and f["hash"] == h
    st, r, _ = c.post("/approve", f)
    assert st == 303 and r.getheader("Location") == "/approve?m=12"
    ents = manifest()["entries"]
    assert len(ents) == 1 and ents[0]["id"] == I1 and ents[0]["approved_by"] == revisions.TEST_BY
    ap = ops.lines("approvals.jsonl")
    assert len(ap) == 1 and ap[0]["code"] == 0 and ap[0]["by"] == revisions.TEST_BY and ap[0]["target"] == I1
    assert [x["action"] for x in ops.lines()] == ["approve"]
    for row in ap + ops.lines():
        assert not {"csrf", "token", "pre"} & set(row)
    st, _, text = c.get("/approve?m=12")
    assert "승인했다" in text and not [x for x in approve_forms(text) if x.get("target") == I1]   # 승인한 판은 목록에서 빠진다
    st, _, text = c.get("/ops")
    assert "게시 대기" in text


def test_wrong_hash_or_rev_is_409(ops):
    c = ops.client
    ready(I1)
    c.login()
    f = form_for(c.get("/approve")[2], I1)
    bad = dict(f, hash=("0" if f["hash"][0] != "0" else "1") + f["hash"][1:])
    st, _, text = c.post("/approve", bad)
    assert st == 409 and "화면을 새로 열고" in text
    st, _, _ = c.post("/approve", dict(f, rev="2", request_id=os.urandom(16).hex()))
    assert st == 409
    assert manifest()["entries"] == []
    assert [x["http"] for x in ops.lines("approvals.jsonl")] == [409, 409]


def test_same_request_twice_and_second_request(ops):
    c = ops.client
    ready(I1)
    c.login()
    f = form_for(c.get("/approve")[2], I1)
    assert c.post("/approve", f)[0] == 303
    snap = (manifest(), ops.lines("approvals.jsonl"), ops.lines())
    st, r, _ = c.post("/approve", f)                                    # 같은 요청 번호, 같은 내용
    assert st == 303 and r.getheader("Location") == "/approve?m=12"
    assert (manifest(), ops.lines("approvals.jsonl"), ops.lines()) == snap
    st, _, _ = c.post("/approve", dict(f, target=I2))                   # 같은 번호에 다른 내용
    assert st == 409 and (manifest(), ops.lines("approvals.jsonl")) == snap[:2]
    st, r, _ = c.post("/approve", dict(f, request_id="ab" * 16))        # 번호가 다른 두 번째 승인
    assert st == 303 and r.getheader("Location") == "/approve?m=13"
    assert manifest() == snap[0]
    ap = ops.lines("approvals.jsonl")
    assert len(ap) == 2 and "이미 승인됨" in ap[-1]["msg"]


def test_without_reviews_is_422(ops):
    c = ops.client
    ready(I1, n_reviews=0)
    c.login()
    st, _, text = c.get("/approve")
    assert "받지 못한 검토" in text and approvals.NEED_CMP in html.unescape(text)
    st, _, text = c.post("/approve", form_for(text, I1))
    assert st == 422 and "검토 조건을 채우지 못했다" in html.unescape(text)
    assert manifest()["entries"] == [] and ops.lines("approvals.jsonl")[0]["http"] == 422
    assert "/" not in "".join(re.findall(r"<li>(.*?)</li>", text))     # 거부 이유에 내부 경로가 없다


def test_bad_shape_is_400(ops):
    c = ops.client
    ready(I1)
    c.login()
    f = form_for(c.get("/approve")[2], I1)
    for bad in (dict(f, kind="card"), dict(f, target="../x"), dict(f, rev="0"), dict(f, hash="xyz"), dict(f, extra="1")):
        assert c.post("/approve", bad)[0] == 400
    assert manifest()["entries"] == [] and ops.lines("approvals.jsonl") == []


def test_missing_reviews_agree_with_review_state(desk):
    for iid in (I1, I2):
        for n in (0, 1, 2):
            if n:
                add_review(iid, ("문장 대조", "해석 점검")[n - 1], ("Claude Sonnet", "가상 모델 G")[n - 1],
                           ("anthropic", "openai")[n - 1])
            issue, evs = model.load_issue(iid), model.load_evidences(iid)
            miss = approvals.missing_reviews(issue, evs)
            assert (miss == []) == (revisions.review_state(issue, evs) == "검토 완료")
            assert miss == [[approvals.NEED_CMP, approvals.NEED_ITP], [approvals.NEED_ITP], []][n]


def _clean(issue: dict) -> dict:
    x = copy.deepcopy(issue)
    x["claims"] = [c for c in x["claims"] if c["id"] == "c4"]          # 확인 판정, 지지 근거 하나
    return x


def test_order_and_folding(desk, monkeypatch):
    monkeypatch.setattr(revisions, "check_with_manifest", lambda *a, **k: {"errors": [], "warnings": []})
    monkeypatch.setattr(revisions, "review_state", lambda *a, **k: "검토 완료")
    man = revisions.load_manifest()
    i1, e1 = model.load_issue(I1), model.load_evidences(I1)
    i2, e2 = model.load_issue(I2), model.load_evidences(I2)
    clean = approvals.issue_card(_clean(i1), e1, man)
    countered = _clean(i1)
    c1 = copy.deepcopy(next(c for c in i1["claims"] if c["id"] == "c1"))
    c1["verdict"] = "확인"                                               # 판정은 확인인데 반대 근거가 붙은 주장
    countered["claims"].append(c1)
    counter_card = approvals.issue_card(countered, e1, man)
    false_card = approvals.issue_card(i1, e1, man)
    personal = approvals.issue_card(i2, e2, man)
    assert personal.personal and false_card.false_verdict and not clean.open and not counter_card.open
    assert counter_card.counter and not counter_card.disputed
    order = sorted([clean, counter_card, false_card, personal], key=lambda c: c.sort_key)
    assert order[0] is personal and order[1] is false_card
    v = approvals.ApproveView(order, [], {"day": [], "restored": []})
    text = approve_view.approve_page(v, csrf="c" * 64)
    blocks = text.split('<article class="issue')[1:]
    assert len(blocks) == 4 and " open" in blocks[0][:6] and " open" in blocks[1][:6]
    assert "<details" in blocks[2] and "<details" in blocks[3]
    # 접힌 건에서도 반대 근거가 있는 주장은 접힘 밖에 보인다
    cb = next(b for b in blocks if c1["gist"] in b and "<details" in b)
    assert cb.index(c1["gist"]) < cb.index("<details")
    obs = e1["i20990101-01-e2"]["observed"]
    assert html.escape(obs) in cb.split("<details")[0]                   # 주장 옆에 근거의 observed 가 그대로
    # 공개 제외 주장도 운영 화면에는 보이고, 그 사실을 표시한다
    assert personal.hidden_claims >= 1 and "공개 제외(운영 화면에만 보인다)" in blocks[0]


def test_flags_without_patch(desk):
    i1, e1 = model.load_issue(I1), model.load_evidences(I1)
    card = approvals.issue_card(i1, e1, revisions.load_manifest())
    assert card.flagged and card.false_verdict and card.disputed and card.counter     # 검토가 없어 점검에 걸림
    assert approvals.NEED_CMP in card.missing


def _day() -> dict:
    return {"date": DATE, "revision": 1, "made_at": f"{DATE} 07:00",
            "line": {"updated_at": f"{DATE} 07:00", "source_kinds_ok": ["공식 발표"], "source_kinds_failed": []},
            "new": [{"keyword": "가상 소재", "state": "정리 전"}], "ongoing": [],
            "upcoming": [{"date": "2099-01-20", "what": "가상 시의회 본회의", "url": "https://council.example/plan"}],
            "pre": [], "empty_note": {"new": "", "ongoing": "오늘 이어지는 기록은 없다."}}


def _restored() -> dict:
    return {"date": DATE, "revision": 1, "made_at": f"{DATE} 07:00", "label": units.RESTORED_LABEL,
            "source_url": "https://wiki.example/pageviews", "items": [{"rank": 1, "article": "가상 도시", "views": 1200}]}


def test_day_and_restored_units(ops):
    model.save_yaml(units.unit_file("day", DATE), _day())
    model.save_yaml(units.unit_file("restored", DATE), _restored())
    c = ops.client
    c.login()
    text = c.get("/approve")[2]
    assert "그날의 화제" in text and "복원판" in text and DATE in text
    forms = [f for f in approve_forms(text) if f.get("target") == DATE]
    assert {f["kind"] for f in forms} == {"day", "restored"}
    day = next(f for f in forms if f["kind"] == "day")
    bad = dict(day, hash=("0" if day["hash"][0] != "0" else "1") + day["hash"][1:])
    assert c.post("/approve", bad)[0] == 409 and manifest()["entries"] == []
    assert c.post("/approve", dict(day, request_id=os.urandom(16).hex()))[0] == 303
    ents = manifest()["entries"]
    assert len(ents) == 1 and ents[0]["unit"] == "day" and ents[0]["id"] == DATE and ents[0]["approved_by"] == revisions.TEST_BY
    rest = next(f for f in forms if f["kind"] == "restored")
    assert c.post("/approve", rest)[0] == 303 and len(manifest()["entries"]) == 2
    text = c.get("/approve")[2]
    assert not [f for f in approve_forms(text) if f.get("target") == DATE]


def test_approve_screen_text(ops):
    ready(I1)
    c = ops.client
    pages = [c.get("/approve")[2]]
    c.login()
    pages.append(c.get("/approve")[2])
    for text in pages:
        for chunk in visible_chunks(text):
            assert not style.text_errors("ops", chunk), chunk
