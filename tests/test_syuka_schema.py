"""슈카 추출 양식 검사 · 두 모델 일치율 — 지어낸 자료만."""
from __future__ import annotations

import copy

import pytest

from ozl.syuka import agree, schema

TRANSCRIPT = "오늘은 가상의 섬나라에서 벌어진 화폐 개혁 이야기를 해 보겠습니다. 새 돈이 나오자 가게마다 값을 올려 받았다고 합니다."


def good() -> dict:
    return {
        "topic_line": "가상 섬나라 화폐 개혁과 물가",
        "question": "화폐 단위를 바꾸면 물가가 왜 오르는가?",
        "field": "해외 경제",
        "intro_style": "최근 뉴스에서 출발",
        "stages": ["개혁 발표", "가격 반올림", "정부 대응"],
        "claims": [{"point": "생필품 값 상승을 소개", "value": "12", "unit": "%"},
                   {"point": "가게들의 값 인상 설명", "value": None, "unit": None},
                   {"point": "금리 인상 대응", "value": "1.5", "unit": "%p"}],
        "people": ["가상 총재"], "orgs": ["가상 중앙은행"], "countries": ["가상국"],
        "korea_link": {"level": "없음", "line": ""},
        "event_period": {"start": "2025-03", "end": "2025-06"},
        "sensitive": [],
        "notes": "",
    }


def test_good_passes():
    assert schema.validate(good(), TRANSCRIPT) == []
    assert schema.check_file({"video_id": "V", "schema_version": schema.SCHEMA_VERSION, "seconds": 10, "record": good()}) == []


def test_missing_and_extra_keys():
    r = good()
    del r["question"]
    r["views"] = 1
    errs = schema.validate(r)
    assert "question: 칸 없음" in errs and "views: 양식에 없는 칸" in errs


@pytest.mark.parametrize("key,val", [
    ("field", "경제"), ("intro_style", "뉴스"), ("field", "증시·투자"), ("field", "기업·산업"),
    ("intro_style", "개인 경험이나 잡담으로 출발"), ("people", [f"가상{i}" for i in range(7)]), ("orgs", [f"가상{i}" for i in range(7)]), ("sensitive", ["정치"]), ("sensitive", ["젠더", "젠더"]),
    ("korea_link", {"level": "조금", "line": "x"}), ("event_period", "2025"), ("event_period", {"start": "2025-13", "end": "2025-12"}),
    ("event_period", {"start": "2025-06", "end": "2025-03"}), ("stages", ["하나", "둘"]), ("stages", ["x"] * 8),
    ("claims", good()["claims"][:2]), ("claims", [{"point": "p", "value": None, "unit": "%"}] * 3),
])
def test_out_of_list_or_shape(key, val):
    r = good()
    r[key] = val
    assert schema.validate(r), (key, val)


def test_lengths():
    r = good()
    r["topic_line"] = "가" * 61
    r["stages"] = ["가" * 81, "b", "c"]
    errs = schema.validate(r)
    assert any(e.startswith("topic_line: 60자 초과") for e in errs) and any(e.startswith("stages[0]") for e in errs)
    r = good()
    r["topic_line"] = "가" * 60
    assert schema.validate(r) == []


def test_period_variants():
    for p in ("특정 시기 없음", {"start": "2024", "end": "2024"}, {"start": "-490", "end": "-480"}):
        r = good()
        r["event_period"] = p
        assert schema.validate(r) == [], p


def test_copy_detection_boundary():
    # 전사 정규화: "오늘은가상의섬나라에서벌어진화폐개혁..." — 공백·부호를 빼고 15자는 통과, 16자는 걸린다
    tn = schema.norm(TRANSCRIPT)
    assert schema.copied("오늘은 가상의 섬나라에서 벌어진화", tn) == ""          # 15자
    assert schema.copied("오늘은, 가상의 섬나라에서 벌어진화폐", tn) != ""       # 16자(부호·공백 무시)
    r = good()
    r["stages"] = ["개혁 발표", "새 돈이 나오자 가게마다 값을 올려 받았다", "정부 대응"]
    errs = schema.validate(r, TRANSCRIPT)
    assert errs == ["stages[1]: 전사와 연속 15자 넘게 같다(옮김) — 요약해 다시 쓴다"]
    r = good()
    r["claims"][0]["point"] = "나오자 가게마다 값을 올려 받았다고 합니다"
    assert any(e.startswith("claims[0].point") for e in schema.validate(r, TRANSCRIPT))
    assert schema.validate(r) == []  # 전사를 안 주면 옮김 검사는 하지 않는다


def test_file_envelope():
    errs = schema.check_file({"video_id": "V", "schema_version": 1, "seconds": 0, "record": good()})
    assert any("schema_version" in e for e in errs) and any("seconds" in e for e in errs)


# ── 일치율


def _recs(pairs):
    out = []
    for i, (a, b) in enumerate(pairs):
        out += [{"video_id": f"v{i}", "model": "opus", "record": a, "seconds": 100},
                {"video_id": f"v{i}", "model": "sonnet", "record": b, "seconds": 60}]
    return out


def test_same_values():
    a, b = good(), good()
    b["intro_style"] = "질문으로 출발"
    b["sensitive"] = ["젠더"]
    res = agree.compare(_recs([(a, copy.deepcopy(a)), (a, b)]), "opus", "sonnet")
    f = res["fields"]
    assert f["field"]["rate"] == 1.0 and f["intro_style"]["rate"] == 0.5 and f["sensitive"]["rate"] == 0.5
    assert not res["all_pass"] and res["seconds_median"] == {"opus": 100, "sonnet": 60}
    assert {d["field"] for d in res["disagreements"]} == {"intro_style", "sensitive"}


def test_sensitive_is_set():
    a, b = good(), good()
    a["sensitive"], b["sensitive"] = ["젠더", "종교"], ["종교", "젠더"]
    assert agree.same("sensitive", a, b)


def test_jaccard_boundary():
    a, b = good(), good()
    a["people"] = ["트럼프 대통령", "제롬 파월 의장", "가", "나", "다"]
    b["people"] = ["트럼프", "제롬파월", "가", "라"]          # 겹침 3 / 합 6 = 0.5
    assert not agree.same("people", a, b)
    b["people"] = ["트럼프", "제롬파월", "가", "나"]          # 4 / 5 = 0.8
    assert agree.same("people", a, b)
    a["orgs"], b["orgs"] = ["가", "나", "다"], ["가", "나", "다", "라", "마"]  # 3/5 = 0.6 → 일치
    assert agree.same("orgs", a, b)
    b["orgs"] = ["가", "나", "다", "라", "마", "바"]          # 3/6 = 0.5
    assert not agree.same("orgs", a, b)
    a["orgs"], b["orgs"] = ["삼성전자(주)"], ["삼성전자"]
    assert agree.same("orgs", a, b)
    a["people"] = b["people"] = []
    assert agree.same("people", a, b)


def test_period_year_month():
    a, b = good(), good()
    b["event_period"] = {"start": "2025-03", "end": "2025-07"}
    assert not agree.same("event_period", a, b)
    a["event_period"] = b["event_period"] = schema.NO_PERIOD
    assert agree.same("event_period", a, b)
    b["event_period"] = {"start": "2025-03", "end": "2025-03"}
    assert not agree.same("event_period", a, b)


def test_only_pairs_counted():
    recs = _recs([(good(), good())]) + [{"video_id": "solo", "model": "opus", "record": good(), "seconds": 5}]
    res = agree.compare(recs, "opus", "sonnet")
    assert res["n_videos"] == 1 and res["only_one_model"] == ["solo"] and res["all_pass"]


# ── 2판: 시기 정밀도 · 표기 정규화 · 1판 값 옮기기


@pytest.mark.parametrize("period,ok", [
    ({"start": "2023-04", "end": "2024-05"}, True),     # 올린 해(2024)와 앞 해는 연-월
    ({"start": "2023", "end": "2024"}, True),           # 월을 모르면 연도 된다
    ({"start": "2022-04", "end": "2024-05"}, False),    # 앞 해보다 이른 시점에 월
    ({"start": "1973", "end": "2024-05"}, True),
    ({"start": "-490", "end": "-480"}, True),
    ({"start": "2024-05", "end": "2024-06"}, False),    # 올린 달 뒤(예정·전망)
    ({"start": "2024", "end": "2025"}, False),
])
def test_period_vs_upload(period, ok):
    r = good()
    r["event_period"] = period
    assert (schema.validate(r, upload_at="2024-05-20 10:00") == []) is ok, period
    assert schema.validate(r) == [] or not ok  # 올린 날을 주지 않으면 이 검사는 하지 않는다


@pytest.mark.parametrize("a,b", [
    (["트럼프"], ["도널드 트럼프"]), (["에마뉘엘 마크롱"], ["마크롱"]), (["샘 알트먼"], ["샘 올트먼"]),
    (["로버트 F. 케네디 주니어"], ["로버트 케네디 주니어"]), (["월튼 워커"], ["월턴 워커"]),
])
def test_person_same_target(a, b):
    assert agree.list_jaccard(a, b, "people") == 1.0


@pytest.mark.parametrize("a,b", [
    (["도널드 트럼프"], ["이방카 트럼프"]),       # 성만 같은 다른 사람(둘 다 전체 이름)
    (["가상 헌트"], ["헌트 형제"]),
    (["드마커스 커즌스"], ["드마커스 커즈"]),      # 표기 차이 목록에 없는 것은 같게 보지 않는다
])
def test_person_different_target(a, b):
    assert agree.list_jaccard(a, b, "people") == 0.0


def test_surname_pairs_once():
    # 한쪽에 '트럼프'와 '이방카 트럼프', 다른 쪽에 '도널드 트럼프' → 짝은 하나
    assert agree.match_count(["트럼프", "이방카 트럼프"], ["도널드 트럼프"], "people") == (2, 1, 1)


@pytest.mark.parametrize("a,b", [
    (["미국 재무부"], ["미 재무부"]), (["미국 연방거래위원회"], ["연방거래위원회"]), (["NATO"], ["나토"]),
    (["EU"], ["유럽연합"]), (["인도 공과대학(IIT)"], ["IIT"]), (["독일 사민당"], ["독일 사회민주당"]),
    (["UN 안보리"], ["유엔 안전보장이사회"]), (["주베네수엘라 대한민국 대사관"], ["주베네수엘라 한국대사관"]),
    (["삼성전자(주)"], ["삼성전자"]),
])
def test_org_same_target(a, b):
    assert agree.list_jaccard(a, b, "orgs") == 1.0


@pytest.mark.parametrize("a,b", [
    (["미국 정부"], ["중국 정부"]), (["네이버웹툰"], ["네이버"]), (["소니뮤직"], ["소니"]),
])
def test_org_different_target(a, b):
    assert agree.list_jaccard(a, b, "orgs") == 0.0


def test_v1_values_mapped():
    a, b = good(), good()
    a["field"], b["field"] = "증시·투자", "기업·산업"
    a["intro_style"], b["intro_style"] = "개인 경험이나 잡담으로 출발", "개인 경험으로 출발"
    assert agree.same("field", a, b) and agree.same("intro_style", a, b)
    assert set(schema.V1_TO_V2["field"].values()) <= set(schema.FIELDS)
    assert set(schema.V1_TO_V2["intro_style"].values()) <= set(schema.INTRO_STYLES)
