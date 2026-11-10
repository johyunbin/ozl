"""슈카월드 영상 태그(ozl.research.videos) 회귀 테스트.
비공개 자료 없이 합성 입력만 쓴다. 영상 ID·제목·요지·전사 문장은 전부 지어낸 것이다."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.research import videos as V  # noqa: E402

AT = "2026-11-10T12:00:00+09:00"


def tag(vid, cat="금융·증시", cat2="", kws="", gist="지어낸 요지 설명", basis="auto"):
    return {"video_id": vid, "category": cat, "category2": cat2, "keywords": kws, "gist": gist, "basis": basis, "tagged_at": AT}


CATALOG = [  # coverage.load_catalog() 모양(최신순)
    {"video_id": "fakeVid0005", "title": "가상의 달 기지 건설 경쟁 이야기", "date": "2026-03-02", "duration_sec": 1500},
    {"video_id": "fakeVid0004", "title": "상상 속 나라의 금리 이야기 둘", "date": "2025-09-18", "duration_sec": 1600},
    {"video_id": "fakeVid0003", "title": "상상 속 나라의 금리 이야기 하나", "date": "2024-09-19", "duration_sec": 1700},
    {"video_id": "fakeVid0002", "title": "어느 섬나라 관세 다툼 정리", "date": "2024-04-01", "duration_sec": 1300},
    {"video_id": "fakeVid0001", "title": "옛날 왕국의 화폐 개혁 이야기", "date": "2019-05-05", "duration_sec": 1200},
]
TAGS = [
    tag("fakeVid0005", "역사·과학·기술", "국제·지정학", "가상우주청", "달 기지를 둘러싼 나라 사이 경쟁 정리"),
    tag("fakeVid0004", "금융·증시", "", "연준|기준금리", "두 번째 금리 인하의 배경 설명"),
    tag("fakeVid0003", "금융·증시", "국제·지정학", "연준|기준금리|파월", "첫 금리 인하와 시장 반응 설명"),
    tag("fakeVid0002", "국제·지정학", "금융·증시", "섬나라", "관세를 둘러싼 두 나라 힘겨루기 해설"),
    tag("fakeVid0001", "역사·과학·기술", "", "옛 왕국", "화폐 개혁이 실패한 과정 해설"),
]
AMAP = {"연준": "연준", "fed": "연준", "미연준": "연준", "기준금리": "기준금리", "정책금리": "기준금리"}


# ── 태그 파일 검사 ──────────────────────────────────────────────────────
def test_valid_record_passes():
    assert V.validate_record(tag("fakeVid0001", "사회·문화", "기타", "가|나|다|라")) == []


def test_reject_category_outside_vocabulary():
    errs = V.validate_record(tag("fakeVid0001", "연예"))
    assert any("category" in e for e in errs)
    errs = V.validate_record(tag("fakeVid0001", "금융·증시", "스포츠"))
    assert any("category2" in e for e in errs)


def test_reject_same_secondary_category():
    assert any("같다" in e for e in V.validate_record(tag("fakeVid0001", "금융·증시", "금융·증시")))


def test_reject_five_keywords():
    errs = V.validate_record(tag("fakeVid0001", kws="가|나|다|라|마"))
    assert any("핵심어 5개" in e for e in errs)
    assert V.validate_record(tag("fakeVid0001", kws="가|나|다|라")) == []


def test_reject_long_or_empty_gist_and_bad_basis():
    assert any("요지" in e for e in V.validate_record(tag("fakeVid0001", gist="")))
    assert any("40자" in e for e in V.validate_record(tag("fakeVid0001", gist="가" * 41)))
    assert any("basis" in e for e in V.validate_record(tag("fakeVid0001", basis="model")))


def test_check_tags_duplicates_unknown_and_missing():
    rows = [tag("fakeVid0001"), tag("fakeVid0001"), tag("fakeVid0009")]
    errs = V.check_tags(rows, ["fakeVid0001", "fakeVid0002"], complete=True)
    assert any("2번" in e for e in errs)
    assert any("fakeVid0009" in e and "없는 ID" in e for e in errs)
    assert any("태그 없는 영상 1편" in e for e in errs)


def test_gist_copied_from_transcript_is_caught(tmp_path):
    body = "오늘은 가상의 섬나라가 이웃 나라와 벌인 관세 다툼의 속사정을 차근차근 짚어 보겠습니다"
    (tmp_path / "fakeVid0002.json").write_text(json.dumps({"text": body}, ensure_ascii=False), encoding="utf-8")
    copied = tag("fakeVid0002", gist="섬나라가 이웃 나라와 벌인 관세 다툼의 속사정")
    own = tag("fakeVid0002", gist="관세를 둘러싼 두 나라 힘겨루기 해설")
    assert any("전사를 옮겼다" in e for e in V.check_tags([copied], transcripts=tmp_path))
    assert V.check_tags([own], transcripts=tmp_path) == []


def test_keyword_alias_normalization_and_collision(tmp_path):
    p = tmp_path / "kw.yaml"
    p.write_text("연준: [Fed, 미 연준]\n기준금리: [정책금리]\n", encoding="utf-8")
    amap = V.load_keywords(p)
    assert V.normalize_keyword("FED", amap) == "연준"
    assert V.normalize_keyword("미연준", amap) == "연준"   # 띄어쓰기 무시
    assert V.normalize_keyword("새 이름", amap) == "새 이름"
    p.write_text("연준: [Fed]\n중앙은행: [fed]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        V.load_keywords(p)


# ── 묶음 병합 ───────────────────────────────────────────────────────────
def _work(tmp_path, recs, ids):
    (tmp_path / "out").mkdir()
    (tmp_path / "manifest.json").write_text(json.dumps({"b_001": ids}), encoding="utf-8")
    (tmp_path / "out" / "b_001.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")


def test_merge_rejects_batch_with_missing_item(tmp_path):
    _work(tmp_path, [{"video_id": "fakeVid0001", "category": "기타", "keywords": [], "gist": "지어낸 잡담 정리"}],
          ["fakeVid0001", "fakeVid0002"])
    rep = V.merge(tmp_path, tmp_path / "tags.csv", catalog=[{"video_id": "fakeVid0001"}, {"video_id": "fakeVid0002"}], amap={})
    assert rep["rejected"] and not rep["merged"]
    assert V.read_tags(tmp_path / "tags.csv") == []


def test_merge_rejects_malformed_batch_without_crashing(tmp_path):
    _work(tmp_path, [{"video_id": "fakeVid0001", "category": "기타", "keywords": 5, "gist": 7}], ["fakeVid0001"])
    rep = V.merge(tmp_path, tmp_path / "tags.csv", catalog=[{"video_id": "fakeVid0001"}], amap={}, names=["b_001", "b_999"])
    assert "b_001" in rep["rejected"] and rep["unknown_names"] == ["b_999"]


def test_merge_normalizes_keywords_and_keeps_human_rows(tmp_path):
    V.write_tags([tag("fakeVid0002", "국제·지정학", basis="human", gist="사람이 고친 요지")], tmp_path / "tags.csv")
    _work(tmp_path, [
        {"video_id": "fakeVid0001", "category": "금융·증시", "category2": "", "keywords": ["Fed", "정책금리"], "gist": "지어낸 금리 이야기 설명"},
        {"video_id": "fakeVid0002", "category": "기타", "category2": "", "keywords": [], "gist": "자동이 다시 붙인 요지"},
    ], ["fakeVid0001", "fakeVid0002"])
    rep = V.merge(tmp_path, tmp_path / "tags.csv", catalog=[{"video_id": "fakeVid0001"}, {"video_id": "fakeVid0002"}], amap=AMAP)
    assert rep["merged"] == ["b_001"] and rep["kept_human"] == 1
    rows = {r["video_id"]: r for r in V.read_tags(tmp_path / "tags.csv")}
    assert rows["fakeVid0001"]["keywords"] == "연준|기준금리"
    assert rows["fakeVid0002"]["gist"] == "사람이 고친 요지"


def test_unify_spacing_variants_prefers_dictionary_then_frequency():
    rows = [tag("fakeVid0001", kws="버크셔 해서웨이|가상 우주청"), tag("fakeVid0002", kws="버크셔해서웨이"),
            tag("fakeVid0003", kws="버크셔 해서웨이"), tag("fakeVid0004", kws="가상우주청"),
            tag("fakeVid0005", kws="버크셔해서웨이", basis="human")]
    n = V.unify_spacing(rows, {"가상우주청": "가상우주청"})
    assert [r["keywords"] for r in rows] == ["버크셔 해서웨이|가상우주청", "버크셔 해서웨이", "버크셔 해서웨이", "가상우주청",
                                             "버크셔해서웨이"] and n == 2   # 사람 확인 행은 그대로


def test_reject_comma_joined_keywords():
    assert any("쉼표" in e for e in V.validate_record(tag("fakeVid0001", kws="가, 나, 다, 라, 마")))


def test_transcript_folder_missing_or_broken_is_not_silent(tmp_path):
    with pytest.raises(FileNotFoundError):
        V.check_tags([tag("fakeVid0001")], transcripts=tmp_path / "없는폴더")
    (tmp_path / "fakeVid0001.json").write_text("{깨진", encoding="utf-8")
    assert any("읽지 못했다" in e for e in V.check_tags([tag("fakeVid0001")], transcripts=tmp_path))
    assert V.check_tags([tag("fakeVid0002")], transcripts=tmp_path) == []   # 파일이 없는 영상(전사 없음)은 정상


# ── find ────────────────────────────────────────────────────────────────
def ids(res):
    return [r["video_id"] for r in res["rows"]]


def test_find_by_category_includes_secondary_and_is_chronological():
    res = V.find(category="국제·지정학", catalog=CATALOG, tags=TAGS, amap=AMAP)
    assert ids(res) == ["fakeVid0002", "fakeVid0003", "fakeVid0005"]   # 주 분야(중심) 먼저, 보조 분야는 그 뒤 시간순
    assert [r["core"] for r in res["rows"]] == [True, False, False]
    assert ids(V.find(category="국제·지정학", desc=True, catalog=CATALOG, tags=TAGS, amap=AMAP)) == ["fakeVid0002", "fakeVid0005", "fakeVid0003"]


def test_find_by_keyword_alias_and_period():
    res = V.find(keywords=["Fed"], since="2025", catalog=CATALOG, tags=TAGS, amap=AMAP)
    assert ids(res) == ["fakeVid0004"]
    res = V.find(keywords=["fed", "파월"], catalog=CATALOG, tags=TAGS, amap=AMAP)   # 여러 핵심어는 전부 맞아야
    assert ids(res) == ["fakeVid0003"]
    assert V.find(keywords=["연준"], until="2024-08", catalog=CATALOG, tags=TAGS, amap=AMAP)["total"] == 0


def test_find_word_in_title_or_gist_and_unknown_category():
    assert ids(V.find(q=["인하"], catalog=CATALOG, tags=TAGS, amap=AMAP)) == ["fakeVid0003", "fakeVid0004"]
    with pytest.raises(ValueError):
        V.find(category="연예", catalog=CATALOG, tags=TAGS, amap=AMAP)


def test_find_limit_keeps_best_matches():
    res = V.find(category="금융·증시", limit=2, catalog=CATALOG, tags=TAGS, amap=AMAP)
    assert res["total"] == 3 and res["shown"] == 2
    assert "fakeVid0002" not in ids(res)  # 보조 분야로만 맞은 편이 먼저 빠진다


def test_find_core_before_side_mentions():
    """요지에 나오고 핵심어 앞자리(또는 제목)에도 나오면 중심, 핵심어 뒷자리로만 맞으면 곁가지 — 곁가지가 더 이르더라도 뒤로."""
    tags = [tag("fakeVid0001", "국제·지정학", "", "섬나라|이웃나라|무역|연준", "관세 다툼 속 무역 흐름 정리"),
            tag("fakeVid0003", "금융·증시", "", "연준|기준금리", "연준의 첫 금리 인하와 시장 반응 설명"),
            tag("fakeVid0004", "금융·증시", "", "파월|연준", "연준 두 번째 인하의 배경 설명")]
    res = V.find(keywords=["연준"], catalog=CATALOG, tags=tags, amap=AMAP)
    assert ids(res) == ["fakeVid0003", "fakeVid0004", "fakeVid0001"] and res["core"] == 2


def test_find_alias_in_title_counts_and_prefix_entity_is_side():
    amap = {"석유수출국기구": "석유수출국기구", "opec": "석유수출국기구", "인도": "인도", "인도네시아": "인도네시아"}
    cat = [{"video_id": "fakeVid0001", "title": "가상의 OPEC 감산 이야기", "date": "2025-01-01", "duration_sec": 900},
           {"video_id": "fakeVid0002", "title": "지어낸 인도네시아 섬 이야기", "date": "2024-01-01", "duration_sec": 900},
           {"video_id": "fakeVid0003", "title": "지어낸 인도 선거 이야기", "date": "2025-02-01", "duration_sec": 900}]
    tags = [tag("fakeVid0001", "금융·증시", "", "석유수출국기구|유가", "OPEC 감산 결정과 유가 반응 정리"),
            tag("fakeVid0002", "국제·지정학", "", "인도네시아", "인도네시아 수도 이전 해설"),
            tag("fakeVid0003", "국제·지정학", "", "인도|선거", "인도 총선 결과 해설")]
    res = V.find(keywords=["OPEC"], catalog=cat, tags=tags, amap=amap)
    assert ids(res) == ["fakeVid0001"] and res["rows"][0]["core"]       # 대표 표기로 바뀌어도 제목·요지의 별칭으로 중심
    res = V.find(keywords=["인도"], catalog=cat, tags=tags, amap=amap)
    assert [(r["video_id"], r["core"]) for r in res["rows"]] == [("fakeVid0003", True), ("fakeVid0002", False)]


def test_find_skips_untagged_videos():
    assert V.find(catalog=CATALOG, tags=TAGS[:2], amap=AMAP)["total"] == 2


# ── 공개 집계 ───────────────────────────────────────────────────────────
PUB_CATALOG = [{"video_id": c["video_id"], "title": c["title"], "published_kst": c["date"] + " 19:00"} for c in CATALOG]


def test_public_aggregate_has_counts_only():
    text = V.render_public(PUB_CATALOG, TAGS, today="2026-11-10")
    assert V.leaks(text, PUB_CATALOG) == []
    for c in CATALOG:
        assert c["video_id"] not in text and c["title"] not in text
    for t in TAGS:
        assert t["gist"] not in text
        for k in V.split_keywords(t["keywords"]):
            assert f"| {k} |" not in text
    assert "| 금융·증시 |" in text and "| 2019 | 2024 | 2025 | 2026 |" in text


def test_leak_detector_fires_on_title_and_id():
    bad = "| 분야 | 편수 |\n어느 섬나라 관세 다툼 정리 — fakeVid0001"
    found = V.leaks(bad, PUB_CATALOG)
    assert any("제목 fakeVid0002" in x for x in found) and any("video_id fakeVid0001" in x for x in found)


def test_leak_detector_fires_on_gist_and_partial_title():
    cat = PUB_CATALOG + [{"video_id": "fakeVid0009", "title": "지어낸 아주 긴 제목 가운데 일부만 옮겨도 잡히는지 보는 영상", "published_kst": "2020-01-01 19:00"}]
    assert any("요지 fakeVid0005" in x for x in V.leaks("메모: 달 기지를 둘러싼 나라 사이 경쟁 정리", cat, TAGS))
    assert any("제목 fakeVid0009" in x for x in V.leaks("메모: 가운데 일부만 옮겨도 잡히는지 보는", cat, TAGS))
    assert V.leaks(V.render_public(cat, TAGS, today="2026-11-10"), cat, TAGS) == []


def test_notion_rows_have_no_volatile_numbers():
    cat = [{**c, "published_kst": c["date"] + " 19:00", "kind": "video", "view_count": "123", "like_count": "4"} for c in CATALOG]
    rows = V.notion_rows(cat, TAGS)
    assert len(rows) == len(TAGS)
    assert set(rows[0]) == set(V.NOTION_COLS)
    assert rows[0]["링크"].startswith("https://youtu.be/") and rows[0]["연도"] == rows[0]["게시일"][:4]


def test_stratified_sample_spreads_categories():
    cat = [{"video_id": t["video_id"], "published_kst": c["date"] + " 19:00"} for t, c in zip(TAGS, CATALOG)]
    got = V.stratified_sample(TAGS, cat, n=3)
    assert len(got) == 3 and len({next(t["category"] for t in TAGS if t["video_id"] == v) for v in got}) == 3
