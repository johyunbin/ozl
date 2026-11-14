"""이슈 글(article.yaml) — 글 형식 명세 3절의 검사(오류 일곱 가지와 경고), article-new, 내보내기의 article 묶음, 승인 지문.
자료는 전부 지어낸 것이다(가상의 한빛시, 가상의 한빛교통공사). 네트워크를 쓰지 않는다."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.issues import article as ART  # noqa: E402
from ozl.issues import check, digest, export, ids, model, paths, revisions  # noqa: E402
from ozl.issues.__main__ import main  # noqa: E402
from test_issues_check import I1, I2, desk, load  # noqa: E402,F401
from test_issues_revisions import approve, edit, ready, real  # noqa: E402,F401

SLUG1 = "hanbit-bus-fare-400"


def sample(iid: str = I1, slug: str = SLUG1) -> dict:
    """검사를 오류 없이 통과하는 지어낸 글."""
    return {
        "schema": 1, "issue_id": iid, "slug": slug, "category": "사회 · 교통", "state": "진행 중", "started": "2099-01-01",
        "as_of": "2099-01-03 09:00", "title": "한빛시 버스 요금 400원 인상안, 시의회 심사는 어디까지 왔나",
        "dek": "인상안은 아직 확정되지 않았다. 시가 낸 안과 시의회의 일정을 나눠 정리했다.",
        "summary": ["한빛시가 시내버스 기본요금을 400원 올리는 안을 시의회에 냈다.",
                    "한빛교통공사는 지난해 적자가 커졌다고 설명한다.",
                    "시의회 상임위원회는 다음 주에 안건을 다룬다. 결론은 아직 없다."],
        "numbers": [{"value": "400", "unit": "원", "label": "올리겠다는 기본요금 폭", "refs": [1]}],
        "what": [{"text": "발단은 한빛시의 요금 조정안이다. 시는 1월 1일 기본요금을 400원 올리는 안을 시의회에 보냈다.[^1]"},
                 {"text": "공사는 연료비가 오른 탓에 운영비가 늘었다고 설명한다.[^2] 시민단체는 인상 폭이 크다며 반대 서명을 받고 있다.[^3]"}],
        "why": {"lead": "요금은 4년째 그대로였다.", "points": [{"head": "적자가 늘었다.", "text": "공사의 지난해 적자는 전년보다 커졌다.[^2]"}]},
        "news": [{"date": "2099-01-03", "label": "1월 3일", "new": True, "items": ["시민단체가 시청 앞에서 반대 서명을 시작했다.[^3]"]},
                 {"date": "2099-01-01", "label": "1월 1일", "items": ["시가 조정안을 시의회에 냈다.[^1]"]}],
        "earlier": [],
        "status": {"confirmed": ["시가 낸 안의 인상 폭은 400원이다.[^1]"], "reported": ["시민단체의 반대 서명.[^3]"],
                   "alleged": [], "unknown": ["시의회가 언제 결론을 낼지."]},
        "views": [],
        "next": [{"head": "상임위원회 심사.", "text": "다음 주 회의에서 안건을 다룬다."},
                 {"head": "공청회.", "text": "시는 공청회를 열겠다고 했다. 날짜는 정하지 않았다.[^1]"}],
        "sources": [{"n": 1, "kind": "공식", "publisher": "한빛시", "title": "요금 조정안", "date": "2099-01-01",
                     "url": "https://example.org/hanbit/fare", "evidence": None},
                    {"n": 2, "kind": "공식", "publisher": "한빛교통공사", "title": "경영 공시", "date": "2099-01-02",
                     "url": "https://example.org/hanbit/report", "evidence": None},
                    {"n": 3, "kind": "보도", "publisher": "가상일보", "title": "", "date": "2099-01-03",
                     "url": "https://example.org/news/1", "evidence": None}],
        "figure": None, "related_syuka": [], "changes": [],
    }


def write(iid: str = I1, art: dict | None = None) -> dict:
    art = sample(iid, model.load_issue(iid)["slug"]) if art is None else art
    model.save_yaml(ART.article_file(iid), art)
    return art


def errs(art, evs=None, iid=I1):
    return ART.check_article(art, evs or {}, issue_id=iid)["errors"]


def warns(art, evs=None, iid=I1):
    return ART.check_article(art, evs or {}, issue_id=iid)["warnings"]


def has(rows, path, msg) -> bool:
    return any(p == path and msg in m for p, m in rows)


# ── 검사 ──────────────────────────────────────────────────────────────
def test_sample_passes():
    r = ART.check_article(sample(), {}, issue_id=I1)
    assert r["errors"] == [] and r["warnings"] == [("article", "본문 분량이 1,500 ~ 2,800자 밖이다(지금 " + f"{ART.body_length(sample()):,}자)")]


def test_1_required():
    a = sample()
    del a["title"]
    a["dek"], a["next"], a["sources"], a["as_of"], a["category"] = "", [], [], "", ""
    for k in ("title", "dek", "next", "sources", "as_of", "category"):
        assert has(errs(a), k, "이 없다"), k
    a = sample()
    a["summary"] = a["summary"][:2]
    assert has(errs(a), "summary", "정확히 3줄")
    a = sample()
    a["what"] = a["what"][:1]
    assert has(errs(a), "what", "2문단 이상")
    a = sample()
    a["status"] = {g: [] for g in ART.STATUS_GROUPS}
    assert has(errs(a), "status", "모두 비어 있다")
    a = sample()
    a["state"] = "끝"
    assert has(errs(a), "state", "허용 값")


def test_2_footnotes():
    a = sample()
    a["what"][0]["text"] += "[^9]"
    assert has(errs(a), "what.0.text", "[^9] 의 출처가 sources 에 없다")
    a = sample()
    a["sources"].append({"n": 4, "kind": "보도", "publisher": "가상일보", "title": "", "date": "2099-01-03", "url": "https://example.org/n/2", "evidence": None})
    assert has(errs(a), "sources", "출처 4 이 본문에서 한 번도 쓰이지 않았다")
    a = sample()
    a["sources"][2]["n"] = 5
    a["status"]["reported"][0] = "시민단체의 반대 서명.[^5]"
    a["what"][1]["text"] = a["what"][1]["text"].replace("[^3]", "[^5]")
    a["news"][0]["items"][0] = a["news"][0]["items"][0].replace("[^3]", "[^5]")
    assert has(errs(a), "sources", "1부터 차례로 이어지지 않는다")
    a = sample()
    a["numbers"][0]["refs"] = [7]
    assert has(errs(a), "numbers.0.refs", "[^7] 의 출처가 sources 에 없다")


def test_3_status_footnotes():
    a = sample()
    a["status"]["confirmed"][0] = "시가 낸 안의 인상 폭은 400원이다."
    a["status"]["reported"][0] = "시민단체의 반대 서명."
    e = errs(a)
    assert has(e, "status.confirmed.0", "각주가 없다") and has(e, "status.reported.0", "각주가 없다")
    a = sample()
    a["status"]["confirmed"][0] = "시민단체가 반대 서명을 받는다.[^3]"     # 보도 각주만 — 명세대로 경고
    assert not any(p.startswith("status.") for p, _ in errs(a)) and has(warns(a), "status.confirmed.0", "공식 출처 각주가 없다")


def test_4_lengths():
    a = sample()
    a["title"] = "버스 요금 인상"
    assert has(errs(a), "title", "15 ~ 45자")
    a = sample()
    a["summary"][0] = "가" * 121
    assert has(errs(a), "summary.0", "120자 이하")
    a = sample()
    a["what"][1]["text"] = "시민들이 정류장에서 의견을 냈다. " * 25 + "[^2][^3]"
    assert has(errs(a), "what.1.text", "400자 이하")
    a = sample()
    a["news"] = [{"date": f"2099-01-0{9 - i}", "label": f"1월 {9 - i}일", "items": [f"{i}번째 회의가 열렸다.[^1]"]} for i in range(6)]
    a["news"][0]["items"].append("시민단체가 모였다.[^3]")
    assert has(errs(a), "news", "5개까지")


def test_5_internal_terms():
    for term in ART.INTERNAL_TERMS:
        a = sample()
        a["next"][0]["text"] = f"다음 주에 {term} 결과를 본다."
        assert has(errs(a), "next.0.text", f"'{term}'"), term


def test_6_duplicate_sentence():
    a = sample()
    a["what"][1]["text"] += " 한빛시가 시내버스 기본요금을 400원 올리는 안을 시의회에 냈다.[^1]"
    assert has(errs(a), "what.1.text", "같은 문장이 summary.0 에도 있다")


def test_7_evidence_file(desk):
    a = sample()
    a["sources"][0]["evidence"] = f"{I1}-e1"
    assert errs(a, model.load_evidences(I1)) == []
    a["sources"][1]["evidence"] = f"{I1}-e9"
    assert has(errs(a, model.load_evidences(I1)), "sources.1.evidence", f"근거 기록 파일이 없다: {I1}-e9")


def test_warnings():
    a = sample()
    a["what"][1]["text"] += " 시는 그렇게 밝혔다. 공사도 밝혔다. 의원도 밝혔다. 단체도 밝혔다. 주민도 밝혔다.[^1]"
    assert has(warns(a), "article", "'밝혔다'가 5번")
    a = sample()
    a["what"][0]["text"] += " " + "시의회는 여러 차례 회의를 열어 요금과 노선과 배차 간격을 길게 따져 보았다고 " * 3 + "설명했다.[^1]"
    assert has(warns(a), "what.0.text", "110자를 넘는다")
    a = sample()
    a["status"]["alleged"] = ["요금 인상이 미리 정해져 있었다는 소문."]
    assert has(warns(a), "status.alleged", "당사자 입장이 없다")
    a["status"]["alleged"] = ["요금 인상이 미리 정해져 있었다는 소문. 시는 부인한다."]
    assert not has(warns(a), "status.alleged", "당사자 입장")
    a = sample()
    a["dek"] = "인상안은 아직 확정되지 않았다 — 시의회가 다룬다."
    a["why"]["lead"] = "요금·노선·배차·환승이 함께 바뀐다."
    a["next"][0]["text"] = "다음 주에 다룬다 \U0001F68C"
    w = warns(a)
    assert has(w, "dek", "줄표") and has(w, "why.lead", "가운뎃점") and has(w, "next.0.text", "이모지")


# ── 붙여 읽기와 지문 ──────────────────────────────────────────────────
def test_load_attaches_and_save_strips(desk):
    h0 = digest.content_hash(*load(I1))
    assert model.ARTICLE_KEY not in model.load_issue(I1)
    write(I1)
    issue = model.load_issue(I1)
    assert issue["article"]["title"] == sample()["title"]
    model.save_issue(issue)
    assert "article" not in model.load_yaml(paths.issue_file(I1))
    h1 = digest.content_hash(*load(I1))
    assert h1 != h0                                           # 글이 지문에 든다
    art = sample()
    art["dek"] = "인상안은 확정되지 않았다. 일정을 나눠 정리했다."
    write(I1, art)
    assert digest.content_hash(*load(I1)) not in (h0, h1)    # 글을 고치면 지문이 바뀐다
    ART.article_file(I1).unlink()
    assert digest.content_hash(*load(I1)) == h0              # 글이 없으면 예전 지문 그대로
    raw = model.load_yaml(paths.issue_file(I1))
    raw["article"] = sample()
    model.save_yaml(paths.issue_file(I1), raw)
    try:
        model.load_issue(I1)
        assert False, "issue.yaml 안의 article 을 받았다"
    except ValueError as e:
        assert "article.yaml" in str(e)


def test_article_errors_in_issue_check(desk):
    art = sample()
    art["title"] = "짧은 제목"
    write(I1, art)
    r = check.check_ids([I1])[I1]
    assert any("article.title" in x for x in r["errors"])


def test_approve_freezes_article(real, tmp_path):
    art = sample()
    art["sources"][0]["evidence"] = f"{I1}-e1"
    write(I1, art)
    ready(I1)
    assert approve(I1)["code"] == 0
    fi, fe, _ = revisions.load_fixed(I1, 1)
    assert fi["article"]["title"] == art["title"] and f"{I1}-e1" in fe
    assert revisions.revision_publishable(I1, 1)[0]
    assert [r["approval"] for r in revisions.status_rows([I1])] == ["승인됨"]
    art["dek"] = "시의회 일정을 나눠 정리했다. 결론은 아직 없다."
    write(I1, art)
    assert [r["approval"] for r in revisions.status_rows([I1])] == ["승인 뒤 고침"]


# ── 명령과 내보내기 ───────────────────────────────────────────────────
def test_article_new_and_article_only_issue(desk, tmp_path, capsys):
    assert main(["article-new", "hanbit-library-hours", "--category", "사회 · 문화", "--title", "한빛시 도서관 운영 시간 단축안 어디까지 왔나",
                 "--date", "2099-01-05"]) == 0
    iid = capsys.readouterr().out.strip()
    assert iid == "i20990105-01" and iid in ids.load_ledger()["issues"]
    art = ART.load_article(iid)
    assert art["slug"] == "hanbit-library-hours" and art["category"] == "사회 · 문화" and art["summary"] == []
    assert model.load_issue(iid)["claims"] == []
    assert main(["article-new", "hanbit-library-hours", "--category", "기타", "--title", "같은 이름의 다른 글을 하나 더 만든다"]) == 2
    assert main(["article-check", iid]) == 1
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last.startswith("오류 ") and ", 경고 " in last
    assert main(["status", iid]) == 0 and main(["check", iid]) in (0, 1)
    assert main(["export", "--preview", "--out", str(tmp_path / "pv")]) == 0
    b = json.loads((tmp_path / "pv" / "issues" / "hanbit-library-hours.json").read_text(encoding="utf-8"))
    assert b["article"]["title"] == art["title"]


def test_article_check_command(desk, capsys):
    assert main(["article-check", I1]) == 2                   # 글이 없다
    write(I1)
    capsys.readouterr()
    assert main(["article-check", I1]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "오류 0, 경고 1"


def test_export_article_and_index(real, tmp_path):
    art = sample()
    art["sources"][0]["evidence"] = f"{I1}-e1"
    write(I1, art)
    out = tmp_path / "pv"
    assert export.export("preview", out)["code"] == 0
    b = json.loads((out / "issues" / f"{SLUG1}.json").read_text(encoding="utf-8"))
    assert b["article"]["what"][0]["text"].endswith("[^1]")
    assert all("evidence" not in s for s in b["article"]["sources"]) and b["article"]["sources"][0]["publisher"] == "한빛시"
    assert f"{I1}-e1" not in json.dumps(b["article"], ensure_ascii=False)
    rows = json.loads((out / "index.json").read_text(encoding="utf-8"))["issues"]
    assert [r["id"] for r in rows] == [I1]                    # 글이 없는 I2 는 목록에 없다
    head = rows[0]["article"]
    assert head == {"title": art["title"], "dek": art["dek"], "category": art["category"], "state": "진행 중", "started": "2099-01-01",
                    "as_of": "2099-01-03 09:00", "news_new": {"date": "2099-01-03", "label": "1월 3일", "text": art["news"][0]["items"][0]}}
    b2 = json.loads((out / "issues" / "nuri-battery-recall.json").read_text(encoding="utf-8"))
    assert b2["article"] is None


def test_public_export_uses_frozen_article(real, tmp_path, monkeypatch):
    monkeypatch.setenv(export.CONTACT_ENV, "report@example.org")
    art = sample()
    write(I1, art)
    ready(I1)
    assert approve(I1)["code"] == 0
    later = copy.deepcopy(art)
    later["dek"] = "승인 뒤에 고친 한 줄 설명이다. 공개용에는 실리지 않는다."
    write(I1, later)
    out = tmp_path / "pub"
    assert export.export("public", out)["code"] == 0
    b = json.loads((out / "issues" / f"{SLUG1}.json").read_text(encoding="utf-8"))
    assert b["article"]["dek"] == art["dek"]
    assert json.loads((out / "index.json").read_text(encoding="utf-8"))["issues"][0]["article"]["dek"] == art["dek"]
