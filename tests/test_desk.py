"""이슈 데스크(수집·민감 표시·커버리지·카드 검증·발행 게이트) 회귀 테스트.
네트워크·비공개 자료 없이 합성 입력만 쓴다. 예시 문장은 전부 지어낸 것이다."""
from __future__ import annotations

import copy
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.research import cards as C  # noqa: E402
from ozl.research import collect, coverage, report, sensitive  # noqa: E402

NOW = datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc)


# ── 민감 표시: 잡아야 할 것과 놓아야 할 것을 둘 다 본다 ─────────────────
@pytest.mark.parametrize("text,level", [
    ("국민의힘 원내대표, 예산안 처리 두고 야당과 충돌", "RED"),
    ("지방선거 앞두고 후보 지지율 여론조사 발표", "RED"),
    ("흉기 사건 피해자 유족, 엄벌 탄원", "RED"),
    ("전 대표 구속영장 청구… 1심 선고는 다음 달", "RED"),
    ("최저임금 인상률 놓고 노사 팽팽", "YELLOW"),
    ("물류창고 화재로 3명 숨져", "YELLOW"),
    ("미국 공화당 경선, 트럼프 지지율 다시 올라", "GREEN"),
    ("일본 자민당 총재 선거, 엔화 약세에 불붙이나", "GREEN"),
    ("반도체 수출 석 달 연속 증가", "GREEN"),
    ("국내 여당 지지율, 미국 관세 협상 뒤 급락", "RED"),        # 문장 뒤쪽의 '미국'이 국내 정치를 풀어 주면 안 된다
    ("미국 민주당 지지율 하락", "GREEN"),                       # 바로 앞에 붙은 해외 표지는 해외 정치
    ("Election results announced in South Korea", "RED"),      # 영문은 어순과 무관하게
    ("South Korea election results announced", "RED"),
    ("South Korea chip exports rise", "GREEN"),
])
def test_sensitive_levels(text, level):
    assert sensitive.classify(text)["level"] == level


def test_sensitive_worst_takes_highest_of_cluster():
    rs = [sensitive.classify("반도체 수출 석 달 연속 증가")] * 4 + [sensitive.classify("국민의힘 공천 논란")]
    assert sensitive.worst(rs)["level"] == "RED"            # 다섯 번째 기사에만 있어도 묶음은 RED
    assert sensitive.worst([])["level"] == "GREEN"


def test_sensitive_domestic_party_beats_foreign_marker():
    # 해외 낱말이 섞여 있어도 국내 정당 실명이 있으면 내려 주지 않는다
    assert sensitive.classify("민주당, 미국 관세 협상 결과 두고 정부 비판")["level"] == "RED"


# ── 커버리지 ─────────────────────────────────────────────────────────
CAT = [{"video_id": "aaa", "title": "관세 폭탄에 흔들리는 자동차 수출", "date": "2026-10-01", "duration_sec": 1500},
       {"video_id": "bbb", "title": "달 탐사 경쟁, 누가 먼저 기지를 짓나", "date": "2026-06-01", "duration_sec": 1500},
       {"video_id": "ccc", "title": "자동차 수출 사상 최대", "date": "2024-01-01", "duration_sec": 1500}]


def test_coverage_search_window_and_keywords():
    got = coverage.search(["자동차"], months=12, today="2026-11-10", catalog=CAT)
    assert [r["video_id"] for r in got] == ["aaa"]            # 24개월 밖(ccc)은 빠진다
    assert coverage.search(["없는낱말"], months=12, today="2026-11-10", catalog=CAT) == []
    assert coverage.search([" "], catalog=CAT) == []
    future = CAT + [{"video_id": "zzz", "title": "자동차 미래 영상", "date": "2027-01-01", "duration_sec": 1}]
    assert [r["video_id"] for r in coverage.search(["자동차"], months=12, today="2026-11-10", catalog=future)] == ["aaa"]   # 앞날 날짜는 창 밖
    assert [r["video_id"] for r in coverage.recent_overlap(coverage.tokens("자동차 미래 영상 관세 수출"), future, "2026-11-10")] == ["aaa"]


def test_coverage_fulltext_reports_unreadable(monkeypatch, tmp_path):
    src = tmp_path / "syuka"
    src.mkdir()
    (src / "aaa.json").write_text("{ 깨진 json", encoding="utf-8")
    monkeypatch.setattr(coverage, "EXPORT", tmp_path)
    with pytest.raises(OSError):        # 하나도 못 읽었으면 '0편'이 아니라 오류
        coverage.search(["자동차"], months=12, fulltext=True, today="2026-11-10", catalog=CAT)
    (src / "bbb.json").write_text('{"text": "달 달 달 기지"}', encoding="utf-8")
    st: dict = {}
    coverage.search(["달"], months=12, fulltext=True, today="2026-11-10", catalog=CAT, stats=st)
    assert st == {"scanned": 2, "unreadable": 1}


def test_coverage_recent_overlap_needs_two_tokens():
    t = coverage.tokens("자동차 수출이 관세로 꺾였다")
    assert [r["video_id"] for r in coverage.recent_overlap(t, CAT, "2026-11-10")] == ["aaa"]
    assert coverage.recent_overlap(coverage.tokens("자동차 리콜 급증"), CAT, "2026-11-10") == []


def test_coverage_missing_catalog_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(coverage, "CATALOG", tmp_path / "nope.csv")
    with pytest.raises(FileNotFoundError):   # 못 읽은 것을 '다룬 적 없음'으로 돌려주지 않는다
        coverage.load_catalog()


# ── 수집: 묶음·점수·요약 ───────────────────────────────────────────────
def item(title, outlet, kind="news", tier="T3", lang="ko", hours_ago=1.0, undated=False):
    return {"title": title, "url": f"https://example.com/{abs(hash(title)) % 9999}", "summary": "", "published": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "undated": undated, "feed": outlet, "outlet": outlet, "tier": tier, "lang": lang, "kind": kind, "section": ""}


def test_cluster_groups_same_event_only():
    items = [item("해운 운임 지수 석 달 만에 반등", "가"), item("해운 운임 지수 반등… 석 달 만에 상승", "나"),
             item("커피 원두 가격 사상 최고", "다"), item("Shipping rates index rebounds after three months", "D", lang="en")]
    cl = collect.cluster(items)
    sizes = sorted(len(c["items"]) for c in cl)
    assert sizes == [1, 1, 2]                      # 같은 사건 2건만 묶이고, 언어가 다르면 묶지 않는다


def test_cluster_does_not_chain_unrelated_items():
    a, b, c = "solar battery factory expands exports demand", "solar battery factory shuts coal power", "coal power demand falls across Europe"
    cl = collect.cluster([item(a, "A", lang="en"), item(b, "B", lang="en"), item(c, "C", lang="en")])
    assert sorted(len(x["items"]) for x in cl) == [1, 2]     # C 는 첫 기사와 1개만 겹친다 — 합집합에 기대 묶이지 않는다


def test_score_counts_distinct_outlets_and_ignores_undated_recency():
    a = collect.cluster([item("해운 운임 지수 석 달 만에 반등", "가"), item("해운 운임 지수 반등 석 달 만에", "나")])[0]
    b = collect.cluster([item("해운 운임 지수 석 달 만에 반등", "가"), item("해운 운임 지수 반등 석 달 만에", "가")])[0]
    assert collect.score(a, set(), NOW) > collect.score(b, set(), NOW)   # 같은 매체 두 건은 한 곳으로 센다
    dated = collect.cluster([item("새 논문 공개", "X", kind="paper", tier="T4")])[0]
    undated = collect.cluster([item("새 논문 공개", "X", kind="paper", tier="T4", undated=True)])[0]
    assert collect.score(dated, set(), NOW) > collect.score(undated, set(), NOW)


def test_digest_surfaces_failures_and_red_counts():
    base = {"date": "2026-11-10", "slot": "am", "generated_at": "2026-11-10T13:00:00+09:00", "window_hours": 24.0, "n_items_raw": 3, "n_items_window": 3,
            "n_clusters": 2, "calendar": [], "calendar_gap": True, "trends": [], "uploads": [],
            "feeds": [{"id": "x", "outlet": "가", "http": 200, "entries": 3, "error": None}, {"id": "y", "outlet": "나", "http": 503, "entries": 0, "error": "HTTP 503"}],
            "coverage_error": "FileNotFoundError: catalog",
            "clusters": [{"title": "지어낸 경제 제목", "lang": "ko", "score": 2.0, "outlets": ["가"], "n_items": 1, "top_tier": "T3", "official": False, "t5_only": False,
                          "paper_only": False, "sensitivity": {"level": "GREEN", "reasons": []}, "coverage_recent": [], "items": [{"url": "https://example.com/1"}]},
                         {"title": "지어낸 정치 제목", "lang": "ko", "score": 5.0, "outlets": ["가"], "n_items": 1, "top_tier": "T3", "official": False, "t5_only": False,
                          "paper_only": False, "sensitivity": {"level": "RED", "reasons": ["국내 정당·선거·정치 공방(여당)"]}, "coverage_recent": [], "items": [{"url": "https://example.com/2"}]}]}
    md = collect.digest(base)
    assert "나(HTTP 503)" in md and "커버리지 대조 실패" in md and "일정표" in md
    assert "지어낸 경제 제목" in md and "지어낸 정치 제목" not in md       # RED 는 목록에서 빼되
    assert "RED 1개" in md and "국내 정당·선거·정치 공방: 1개" in md      # 뺀 사실과 사유는 남긴다


def test_recollect_keeps_first_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(collect, "DESK", tmp_path)
    monkeypatch.setattr(collect, "load_config", lambda: {"feeds": [{"id": "x", "outlet": "가", "url": "u", "tier": "T3", "lang": "ko", "kind": "news"}], "channels": []})
    monkeypatch.setattr(collect, "fetch_feed", lambda f, now: ([item("해운 운임 지수 석 달 만에 반등", "가")], {"id": "x", "outlet": "가", "http": 200, "entries": 1, "error": None}))
    monkeypatch.setattr(collect.coverage, "load_catalog", lambda: CAT)
    first = collect.collect("am", "2026-11-10", now=NOW)
    again = collect.collect("am", "2026-11-10", now=NOW)
    assert first.name == "candidates.md" and again.name.startswith("recheck_") and first.exists() and again.exists()


def test_calendar_window_marks_stale(monkeypatch, tmp_path):
    (tmp_path / "calendar.yaml").write_text(
        'events:\n  - {date: "2026-11-10", kst: "2026-11-10 22:30", org: A, title: t, schedule_url: "https://example.com", basis: official, checked: "2026-09-01"}\n'
        '  - {date: "2026-12-30", kst: "2026-12-30", org: B, title: t, schedule_url: "https://example.com", basis: official, checked: "2026-11-10"}\n', encoding="utf-8")
    monkeypatch.setattr(collect, "HERE", tmp_path)
    w = collect.calendar_window("2026-11-10")
    assert len(w) == 1 and w[0]["stale"] is True
    assert collect.calendar_gap("2026-11-11") is True and collect.calendar_gap("2026-11-10") is False


# ── 카드·클레임 검증 ──────────────────────────────────────────────────
def make_claim(n=1, status="pending", hv=False, tier="T1"):
    return {"claim_id": f"2026-11-10-am-01-c{n}", "card_id": "2026-11-10-am-01", "text": f"지어낸 주장 {n}", "observed": "12.3%",
            "source": {"url": "https://example.org/stat", "tier": tier, "publisher": "가상 통계청", "accessed": "2026-11-10", "archived": ""},
            "cross_check": [], "status": status,
            "checks": {"unit_ok": True, "base_period": "2026-10", "real_vs_nominal": "nominal", "seasonally_adjusted": "n/a", "methodology_match": True,
                       "revision_status": "preliminary", "primary_doc_locator": "표 1", "recalculated": True, "translation_checked": True},
            **({"human_verified_by": "tester"} if hv else {}),
            "counter": {"core_claim": "가", "strongest_counter": "나", "denominator_check": "다", "residual_uncertainty": "라"},
            "verifiers": {"claude": "원문 대조"}, "human_verified": hv, **({"human_verified_at": "2026-11-10T15:00:00+09:00"} if hv else {}),
            "links": {}, "revision": 1}


def make_card(depth="full", badge="pending"):
    return {"card_id": "2026-11-10-am-01", "date": "2026-11-10", "slot": "am", "rank": 1, "revision": 1, "state": "제안", "depth": depth, "category": "기타", "topic": "가상 분야",
            "titles": ["지어낸 제목 하나", "지어낸 제목 둘"], "hook": "지어낸 훅",
            "why_today": {"text": "가상 기관이 오늘 수치를 냈다", "trigger_date": "2026-11-10", "trigger_type": "공식 발표"},
            "data": [{"text": f"지어낸 수치 {i}", "source_name": "가상 통계청", "url": "https://example.org/stat", "tier": "T1", "claim_id": f"2026-11-10-am-01-c{i}"} for i in (1, 2, 3)],
            "sources": [{"name": "가상 통계청", "url": "https://example.org/stat", "tier": "T1"}], "badge": badge,
            "coverage": {"summary": "전용 영상 없음", "searched": ["가상"], "videos": []}, "sensitivity": {"level": "GREEN", "reason": ""},
            "outline": [{"stage": s, "note": "메모"} for s in ("여는 장", "배경", "전개", "반전", "근거 수치", "시사점", "닫는 장")],
            "angles": {"twist": "지어낸 반전", "parallel": "지어낸 평행", "analogy": "", "bridge": "지어낸 멘트"}, "risks": ["지어낸 리스크"],
            "publish": {"approved": False}}


def test_valid_card_passes():
    assert C.validate_card(make_card(), [make_claim(i) for i in (1, 2, 3)]) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda c, cl: c["angles"].update(twist=""), "twist"),
    (lambda c, cl: c["sensitivity"].update(level="RED"), "RED"),
    (lambda c, cl: c["data"][0].update(tier="T3"), "T1/T2"),
    (lambda c, cl: c.update(badge="verified"), "배지"),
    (lambda c, cl: c["coverage"].update(searched=[]), "searched"),
    (lambda c, cl: c.update(outline=[o for o in c["outline"] if o["stage"] != "반전"]), "반전"),
    (lambda c, cl: cl[0].update(status="verified"), "human_verified"),
    (lambda c, cl: cl[1]["counter"].update(strongest_counter=""), "strongest_counter"),
    (lambda c, cl: cl[2].update(observed=""), "observed"),
    (lambda c, cl: cl.pop(), "클레임 레코드 없음"),
    (lambda c, cl: c["publish"].update(approved=True), "발행 승인"),
    (lambda c, cl: c.update(category="없는 분류"), "category"),
    (lambda c, cl: c["publish"].update(approved="false"), "true/false"),                 # 문자열을 승인으로 치지 않는다
    (lambda c, cl: c["data"][0].update(url="https://example.org/other"), "연결된 클레임"),   # 카드에 적은 출처가 클레임과 다르면
    (lambda c, cl: c["sources"][0].pop("name"), "sources"),
    (lambda c, cl: (c.update(card_id="2026-99-99-am-01", date="2026-99-99"),), "card_id 형식"),
    (lambda c, cl: cl[0].update(cross_check=[{}]), "cross_check"),
    (lambda c, cl: cl[0]["source"].update(tier="T5", url="https://example.org/stat") or c["data"][0].update(tier="T5") or cl[0].update(status="credible_estimate"), "T5"),
])
def test_invalid_card_is_caught(mutate, needle):
    card, claims = make_card(), [make_claim(i) for i in (1, 2, 3)]
    mutate(card, claims)
    errs = C.validate_card(card, claims)
    assert any(needle in e for e in errs), errs


def test_verified_needs_passing_checks_and_real_cross_check():
    ok = make_claim(1, "verified", True)
    assert C.validate_claim(ok) == []
    bad = make_claim(1, "verified", True)
    bad["checks"]["unit_ok"] = False
    assert any("unit_ok" in e for e in C.validate_claim(bad))
    t3 = make_claim(1, "verified", True, tier="T3")
    t3["cross_check"] = [{}]
    assert any("교차 출처" in e or "cross_check" in e for e in C.validate_claim(t3))
    t3["cross_check"] = [{"url": "https://example.net/a", "tier": "T3", "publisher": "가상 통신", "same_origin_as_source": False}]
    assert C.validate_claim(t3) == []
    t3["cross_check"][0]["same_origin_as_source"] = True        # 같은 원출처 받아쓰기는 교차로 세지 않는다
    assert C.validate_claim(t3) != []


def test_badge_is_weakest_claim():
    assert C.badge_of([]) == "pending"
    assert C.badge_of([make_claim(1, "verified", True), make_claim(2)]) == "pending"
    assert C.badge_of([make_claim(1, "verified", True), make_claim(2, "credible_estimate")]) == "credible_estimate"
    assert C.badge_of([make_claim(1, "verified", True), make_claim(2, "verified", True)]) == "verified"


@pytest.fixture()
def desk(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "DESK", tmp_path / "desk")
    monkeypatch.setattr(C, "CARDS", tmp_path / "desk" / "cards")
    monkeypatch.setattr(C, "CLAIMS", tmp_path / "desk" / "claims")
    monkeypatch.setattr(C, "PUB_CLAIMS", tmp_path / "claims")
    monkeypatch.setattr(report, "ROOT", tmp_path)
    card = make_card()
    C.save_yaml(C.card_path(card["card_id"]), card)
    for i in (1, 2, 3):
        cl = make_claim(i)
        C.save_yaml(C.claim_path(cl["claim_id"]), cl)
    return tmp_path


def test_publish_gate_refuses_pending_then_allows_after_human_check(desk):
    cid = "2026-11-10-am-01"
    with pytest.raises(PermissionError):
        C.approve_publish(cid, "tester")                      # 사람 대조 전에는 공개 불가
    assert not (desk / "claims").exists()
    C.human_verify([f"{cid}-c1", f"{cid}-c2"], "tester")
    assert C.load_card(cid)["badge"] == "pending"             # 하나라도 남으면 여전히 대기
    with pytest.raises(PermissionError):
        C.approve_publish(cid, "tester")
    C.human_verify([f"{cid}-c3"], "tester")
    assert C.load_card(cid)["badge"] == "verified"
    card = C.approve_publish(cid, "tester")
    assert card["publish"]["approved"] is True
    assert sorted(p.name for p in (desk / "claims" / "2026-11-10").glob("*.yaml")) == [f"{cid}-c{i}.yaml" for i in (1, 2, 3)]


def test_human_verify_refuses_failed_checks_and_t5(desk):
    cid = "2026-11-10-am-01"
    x = C.load_yaml(C.claim_path(f"{cid}-c1"))
    x["checks"]["unit_ok"] = False
    C.save_yaml(C.claim_path(x["claim_id"]), x)
    with pytest.raises(ValueError):
        C.human_verify([f"{cid}-c1", f"{cid}-c2"], "tester")
    assert C.load_yaml(C.claim_path(f"{cid}-c2"))["human_verified"] is False     # 하나라도 막히면 아무것도 저장하지 않는다
    with pytest.raises(ValueError):
        C.human_verify([f"{cid}-c2"], "")


def test_approval_is_bound_to_content_and_can_be_withdrawn(desk):
    cid = "2026-11-10-am-01"
    C.human_verify([f"{cid}-c{i}" for i in (1, 2, 3)], "tester")
    C.approve_publish(cid, "tester")
    assert C.publishable(C.load_card(cid), C.claims_for(cid))
    assert "지어낸 제목 하나" in report.render_public("2026-11-10", "am")
    card = C.load_card(cid)
    card["titles"][0] = "승인 뒤에 바꾼 제목"                     # 승인 뒤 내용 변경 → 승인 무효
    C.save_yaml(C.card_path(cid), card)
    assert not C.publishable(card, C.claims_for(cid))
    assert "승인 뒤에 바꾼 제목" not in report.render_public("2026-11-10", "am")
    with pytest.raises(PermissionError):
        report.render_card(card, C.claims_for(cid), 1, public=True)
    assert any("다시 승인" in e for e in C.validate_card(card, C.claims_for(cid)))
    assert report.notion_rows("2026-11-10", "am")[0]["properties"]["Pages 링크"] is None
    C.withdraw(cid, "tester", "수치 재확인 필요")
    assert not list((desk / "claims").rglob("*.yaml"))            # 공개 클레임 사본도 치운다
    pub = pathlib.Path(report.render_all("2026-11-10", "am")["paths"]["public"]).read_text(encoding="utf-8")
    assert "## 철회" in pub and "수치 재확인 필요" in pub and "승인 뒤에 바꾼 제목" not in pub


def test_claim_added_after_approval_blocks_publication(desk):
    cid = "2026-11-10-am-01"
    C.human_verify([f"{cid}-c{i}" for i in (1, 2, 3)], "tester")
    C.approve_publish(cid, "tester")
    extra = make_claim(4)                                          # 승인 뒤 pending 클레임이 붙으면 배지가 내려간다
    C.save_yaml(C.claim_path(extra["claim_id"]), extra)
    assert not C.publishable(C.load_card(cid), C.claims_for(cid))
    assert "지어낸 제목 하나" not in report.render_public("2026-11-10", "am")


def test_public_report_hides_unapproved_card_text(desk):
    cid = "2026-11-10-am-01"
    r = report.render_all("2026-11-10", "am")
    pub = pathlib.Path(r["paths"]["public"]).read_text(encoding="utf-8")
    prv = pathlib.Path(r["paths"]["private"]).read_text(encoding="utf-8")
    assert "지어낸 제목 하나" in prv and "지어낸 수치 1" in prv
    assert "지어낸 제목 하나" not in pub and "지어낸 훅" not in pub and "지어낸 수치 1" not in pub   # 공개본에는 번호·분야·상태만
    assert cid in pub and "검증·승인 대기" in pub
    assert report.notion_rows("2026-11-10", "am")[0]["properties"]["Pages 링크"] is None
    C.human_verify([f"{cid}-c{i}" for i in (1, 2, 3)], "tester")
    C.approve_publish(cid, "tester")
    pub2 = pathlib.Path(report.render_all("2026-11-10", "am")["paths"]["public"]).read_text(encoding="utf-8")
    assert "지어낸 제목 하나" in pub2 and "지어낸 수치 1" in pub2
    assert report.notion_rows("2026-11-10", "am")[0]["properties"]["Pages 링크"].endswith("/daily/2026-11-10_am/#am-01")


def test_render_refuses_invalid_cards(desk):
    card = C.load_card("2026-11-10-am-01")
    card["risks"] = []
    C.save_yaml(C.card_path(card["card_id"]), card)
    with pytest.raises(ValueError):
        report.render_all("2026-11-10", "am")


def test_next_ids_never_reuse(desk):
    assert C.next_ids("2026-11-10", "am", 2) == ["2026-11-10-am-02", "2026-11-10-am-03"]
    assert C.next_ids("2026-11-10", "am", 1) == ["2026-11-10-am-04"]      # 저장 전에 다시 불러도 겹치지 않는다
    C.card_path("2026-11-10-am-01").unlink()                               # 파일을 지워도 그 번호는 돌아오지 않는다
    assert C.next_ids("2026-11-10", "am", 1) == ["2026-11-10-am-05"]
    assert C.next_ids("2026-11-10", "pm", 1) == ["2026-11-10-pm-01"]
    with pytest.raises(ValueError):
        C.next_ids("2026-11-10", "wk", 100)
    with pytest.raises(ValueError):
        C.next_ids("2026-99-99", "am", 1)


def test_light_card_needs_only_links():
    card = make_card(depth="light")
    card["data"] = []
    assert C.validate_card(card, []) == []
    card3 = copy.deepcopy(card)
    card3["data"] = [{"text": "지어낸 수치", "source_name": "가상", "url": "https://example.org/x", "tier": "T3", "claim_id": "not_a_claim"}]
    assert any("클레임 레코드 없음" in e for e in C.validate_card(card3, []))   # 간이 카드도 없는 클레임을 가리키면 걸린다
    card2 = copy.deepcopy(card)
    card2["sources"] = []
    assert any("1차 출처" in e for e in C.validate_card(card2, []))
