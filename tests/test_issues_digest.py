"""승인 지문, 근거 해시, 본문 해시 시험(설계 8절). 지어낸 예시만 쓴다."""
from __future__ import annotations

import json
import pathlib
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import body as B  # noqa: E402
from ozl.issues import digest, model, revisions  # noqa: E402
from test_issues_check import I1, I2, desk, load  # noqa: E402,F401
from test_issues_revisions import approve, claim, edit, ready, real  # noqa: E402,F401


def test_digest_fields_classified():
    inside, outside = set(digest.DIGEST_FIELDS), set(digest.DIGEST_SKIP)
    assert not inside & outside
    assert inside | outside == set(model.ISSUE_FIELDS)
    assert len(digest.DIGEST_FIELDS) == len(inside) and len(digest.DIGEST_SKIP) == len(outside)
    assert "numbers" in inside and "production" in inside and "reviews" in outside


def test_score_change_keeps_approval(real):
    ready(I1)
    assert approve(I1)["code"] == 0
    h = digest.content_hash(*load(I1))
    edit(I1, lambda i: i.update(trend={"score": 88, "bars7": [1, 1, 1, 1, 1, 1, 1], "asof": "2099-01-03 07:40", "formula_version": 2},
                                topic_state="정점", work_state="보류"))
    assert digest.content_hash(*load(I1)) == h
    score = revisions.rev_dir(I1, 1) / "score.json"
    score.write_text(json.dumps({"score": 3, "bars7": [0] * 7, "asof": "x", "formula_version": 9}), encoding="utf-8")
    assert revisions.revision_publishable(I1, 1) == (True, "")
    assert not revisions.manifest_errors(*load(I1), revisions.load_manifest())


def test_content_change_voids(real):
    ready(I1)
    assert approve(I1)["code"] == 0
    base = digest.content_hash(*load(I1))
    for fn in (lambda i: claim(i, "c1").update(gist="한빛시 버스 운송 적자가 한 해 300억 원이다."),
               lambda i: claim(i, "c3").update(verdict="사실과 다름"),
               lambda i: i.update(sensitive=["정치"])):
        issue = model.load_issue(I1)
        fn(issue)
        assert digest.content_hash(issue, model.load_evidences(I1)) != base
    fixed = revisions.rev_dir(I1, 1) / "issue.yaml"
    d = model.load_yaml(fixed)
    d["what_new"] = "시가 1월 3일 요금 400원 인상안을 발표했다."
    model.save_yaml(fixed, d)
    ok, why = revisions.revision_publishable(I1, 1)
    assert not ok and "내용 해시" in why


def test_capture_change_voids(real):
    ready(I2)
    assert approve(I2)["code"] == 0
    src = revisions.rev_dir(I2, 1) / "captures" / f"{I2}-e1" / "source.html"
    b = bytearray(src.read_bytes())
    b[-2] = (b[-2] + 1) % 256
    src.write_bytes(bytes(b))
    ok, why = revisions.revision_publishable(I2, 1)
    assert not ok and "근거 사본이 바뀌면 무효" in why


def test_body_hash_tool_independent(desk):
    issue, evs = load(I1)
    b = B.issue_body(issue, evs, rev_at="2099-01-02T12:00:00+09:00")
    h = digest.body_hash(b)
    shuffled = json.loads(json.dumps(dict(reversed(list(b.items()))), ensure_ascii=False))
    assert digest.body_hash(shuffled) == h
    nfd = json.loads(unicodedata.normalize("NFD", json.dumps(b, ensure_ascii=False)))
    assert digest.body_hash(nfd) == h
    assert digest.body_hash(dict(b, header={"site": "다른 이름"}, footer={"x": 1}, trend={"score": 1}, trend_now=None,
                                 internal={"a": 1})) == h
    assert digest.body_hash(dict(b, title=b["title"] + "  ")) == h          # 양끝 공백
    assert digest.body_hash(dict(b, title="버스 요금 인상, 근거 수치의 해")) != h
