"""슈카 3판 양식(영상 → 토막) 검사, 이름 맞추기, DB 넣기와 찾기, 시험 30편 고르기 — 지어낸 자료만."""
from __future__ import annotations

import copy
import json
import pathlib
import re

import pytest

from ozl.syuka import __main__ as cli
from ozl.syuka import db, db_v3, names, pilot, schema_v3

TRANSCRIPT = ("안녕하세요 여러분. 오늘은 가상의 섬나라 몽돌국이 화폐 단위를 바꾼 이야기를 해 보겠습니다. "
              "새 돈이 나오자 가게마다 값을 올려 받았다고 합니다. 한 달 사이 생필품 값이 12% 올랐습니다. "
              "다음은 가상 회사 별빛전자의 실적 이야기입니다. 영업이익이 3조 원이라고 합니다. 오늘 방송은 여기까지입니다.")
UPLOAD = "2025-06-10 19:00"


def seg(n=1, **kw) -> dict:
    s = {
        "seg": n,
        "span": {"start_char": 0, "end_char": 100},
        "topic_line": "몽돌국 화폐 개혁과 물가",
        "question": "화폐 단위를 바꾸면 물가가 왜 오르는가?",
        "field": "해외 경제", "field2": None,
        "intro_style": "최근 뉴스에서 출발",
        "main_person": "가상 총재", "main_org": "몽돌국 중앙은행",
        "people": ["가상 총재"], "orgs": ["몽돌국 중앙은행", "몽돌국 재무부"], "countries": ["몽돌국"],
        "korea_link": {"level": "없음", "line": ""},
        "period": {"core_start": "2025-03", "core_end": "2025-06", "background_years": [1998]},
        "claims": [{"point": "생필품 값 상승", "value": "12", "unit": "%", "as_of": "2025-05"},
                   {"point": "가게들이 값을 올려 받음", "value": None, "unit": None, "as_of": None},
                   {"point": "금리 인상으로 대응", "value": "1.5", "unit": "%p", "as_of": "2025-04"}],
        "stages": [{"role": "hook", "line": "개혁 발표"}, {"role": "explainer", "line": "가격 반올림"},
                   {"role": "implication", "line": "정부 대응과 전망"}],
        "story_devices": ["역사 사례"], "source_types": ["외신"], "sensitive": [],
        "sponsored": {"level": "아니오", "line": ""}, "evergreen": "시사",
        "followups": [{"metric": "몽돌국 물가 상승률", "value_then": "12%", "date_then": "2025-05", "why": "개혁 효과 확인"}],
        "keywords": ["화폐 개혁", "물가"], "notes": "",
    }
    s.update(kw)
    return s


def doc(**kw) -> dict:
    d = {"video_id": "fakeVID0001", "schema_version": 3, "model": "opus", "seconds": 300, "read_to_end": True,
         "transcript_chars": len(TRANSCRIPT), "summary": "몽돌국 화폐 개혁과 별빛전자 실적", "ad_disclosure": "아니오",
         "n_segments": 2, "notes": "앞뒤 인사는 토막에서 뺐다",
         "segments": [seg(1), seg(2, span={"start_char": 100, "end_char": 160}, topic_line="별빛전자 실적", question="별빛전자는 얼마를 벌었나?",
                              field="기업·증시", main_person=None, people=[], main_org="별빛전자", orgs=["별빛전자"],
                              keywords=["별빛전자"], followups=[])]}
    d.update(kw)
    return d


def test_good_file_passes():
    assert schema_v3.validate_file(doc(), TRANSCRIPT, UPLOAD) == []
    assert schema_v3.validate_file(doc()) == []


def test_missing_extra_and_envelope():
    d = doc()
    del d["summary"]
    d["views"] = 3
    d["read_to_end"] = False
    d["schema_version"] = 2
    errs = schema_v3.validate_file(d)
    for want in ("summary: 칸 없음", "views: 양식에 없는 칸", "read_to_end", "schema_version"):
        assert any(e.startswith(want) for e in errs), want


@pytest.mark.parametrize("key,val", [
    ("field", "경제"), ("field2", "해외 경제"), ("intro_style", "뉴스"), ("evergreen", "늘"),
    ("story_devices", ["비유", "비유"]), ("story_devices", ["농담"]), ("source_types", []),
    ("source_types", ["외신", "알 수 없음"]), ("sensitive", ["정치"]),
    ("sponsored", {"level": "예", "line": ""}), ("sponsored", {"level": "아마", "line": "x"}),
    ("korea_link", {"level": "직접", "line": ""}), ("keywords", []), ("keywords", list("가나다라마바사")),
    ("people", [f"사람{i}" for i in range(9)]), ("topic_line", "가" * 41), ("question", "질문\n둘"),
    ("main_person", "없는 사람"), ("main_org", "몽돌국 재무부"),
])
def test_segment_closed_values_and_shapes(key, val):
    d = doc()
    d["segments"][0][key] = val
    assert schema_v3.validate_file(d), (key, val)


def test_stage_roles_and_counts():
    d = doc()
    d["segments"][0]["stages"][0]["role"] = "intro"
    assert any("stages[0].role" in e for e in schema_v3.validate_file(d))
    d = doc()
    d["segments"][0]["stages"] = d["segments"][0]["stages"][:2]
    assert any("stages: 3~7" in e for e in schema_v3.validate_file(d))


def test_twist_needs_turn_stage():
    d = doc()
    d["segments"][0]["story_devices"] = ["반전"]
    assert any("turn" in e for e in schema_v3.validate_file(d))
    d["segments"][0]["stages"][1]["role"] = "turn"
    assert schema_v3.validate_file(d) == []


GUIDE = pathlib.Path(__file__).resolve().parents[1] / "private" / "syuka" / "extract_guide_v3.md"


@pytest.mark.skipif(not GUIDE.exists(), reason="비공개 지침 파일이 없는 환경")
def test_guide_example_passes():
    text = GUIDE.read_text(encoding="utf-8")
    m = re.search(r"```json\n(.*?)\n```", text, re.S)
    assert m, "지침에 본보기 JSON 이 없다"
    assert schema_v3.validate_file(json.loads(m.group(1)), upload_at="2025-06-10 19:00") == []


def test_claims_rules():
    d = doc()
    d["segments"][0]["claims"][1]["as_of"] = "2025"
    assert any("수치 없이" in e for e in schema_v3.validate_file(d))
    d = doc()
    d["segments"][0]["claims"][0]["as_of"] = "2025-13"
    assert any("as_of" in e for e in schema_v3.validate_file(d))
    d = doc()
    d["segments"][0]["claims"][0]["value"] = "많이"
    assert any("수치가 아니다" in e for e in schema_v3.validate_file(d))
    d = doc()
    d["segments"][0]["claims"][0]["value"] = "약 3조"
    assert schema_v3.validate_file(d) == []


@pytest.mark.parametrize("period,ok", [
    ({"core_start": "2025-03", "core_end": "2025-06", "background_years": [1998, 2008]}, True),
    ({"core_start": None, "core_end": None, "background_years": []}, True),       # 특정 시기 없음
    ({"core_start": "2025-03", "core_end": None, "background_years": []}, False),
    ({"core_start": "2025-07", "core_end": "2025-07", "background_years": []}, False),  # 올린 달 뒤
    ({"core_start": "2020-03", "core_end": "2025-06", "background_years": []}, False),  # 이른 해는 연만
    ({"core_start": "2020", "core_end": "2025-06", "background_years": []}, True),
    ({"core_start": "2025-03", "core_end": "2025-06", "background_years": [2025]}, False),  # 중심 사건 안의 해
    ({"core_start": "2025-03", "core_end": "2025-06", "background_years": [2008, 1998]}, False),  # 순서
    ({"core_start": "-490", "core_end": "-479", "background_years": [-500]}, True),
])
def test_period(period, ok):
    d = doc()
    d["segments"][0]["period"] = period
    assert (schema_v3.validate_file(d, upload_at=UPLOAD) == []) is ok, period


def test_followups():
    d = doc()
    d["segments"][0]["followups"] = d["segments"][0]["followups"] * 4
    assert any("followups: 0~3" in e for e in schema_v3.validate_file(d))
    d = doc()
    d["segments"][0]["followups"][0]["date_then"] = "2025-09"
    assert any("date_then" in e for e in schema_v3.validate_file(d, upload_at=UPLOAD))


def test_spans_order_and_length():
    d = doc()
    d["segments"][1]["span"] = {"start_char": 50, "end_char": 160}
    assert any("겹치거나" in e for e in schema_v3.validate_file(d))
    d = doc()
    d["segments"][1]["span"] = {"start_char": 100, "end_char": 10_000}
    assert any("전사 길이" in e for e in schema_v3.validate_file(d, TRANSCRIPT))
    d = doc()
    d["segments"][0]["span"] = {"start_sec": 0, "end_sec": 95.5}
    d["segments"][1]["span"] = {"start_sec": 95.5, "end_sec": 300}
    assert schema_v3.validate_file(d) == []
    d["segments"][1]["span"] = {"start_sec": 95.5}
    assert any("함께" in e for e in schema_v3.validate_file(d))


def test_segment_numbers_and_count():
    d = doc(n_segments=3)
    assert any(e.startswith("n_segments") for e in schema_v3.validate_file(d))
    d = doc()
    d["segments"][1]["seg"] = 5
    assert any("1부터 차례로" in e for e in schema_v3.validate_file(d))


def test_transcript_chars_and_copy():
    assert any(e.startswith("transcript_chars") for e in schema_v3.validate_file(doc(transcript_chars=5), TRANSCRIPT))
    d = doc()
    d["segments"][0]["notes"] = "새 돈이 나오자 가게마다 값을 올려 받았다"
    errs = schema_v3.validate_file(d, TRANSCRIPT)
    assert any("옮김" in e for e in errs)
    assert not any("가게마다" in e for e in errs)  # 겹친 조각은 찍지 않는다


def test_ad_disclosure_values():
    assert any(e.startswith("ad_disclosure") for e in schema_v3.validate_file(doc(ad_disclosure="몰라")))
    d = doc(ad_disclosure="예")  # 생방송 중간의 광고 읽기는 토막이 아니므로 sponsored 토막 없이도 된다
    assert schema_v3.validate_file(d) == []


@pytest.mark.parametrize("a,b", [
    ("트럼프", "도널드 트럼프"), ("샘 알트만", "샘 올트먼"), ("파월 의장", "제롬 파월"), ("Jerome H. Powell", "Jerome Powell"),
])
def test_person_same(a, b):
    assert names.person(a)[0] == names.person(b)[0]


def test_person_different_and_display():
    assert names.person("이방카 트럼프")[0] != names.person("도널드 트럼프")[0]
    assert names.person("트럼프 대통령")[1] == "도널드 트럼프"
    assert names.person("가상 인물")[1] == "가상 인물"  # 사전에 없으면 그대로


@pytest.mark.parametrize("a,b", [
    ("NATO", "나토"), ("연준", "미국 연방준비제도"), ("미 연준", "미국 연방준비제도"), ("Fed", "연방준비제도"),
    ("UN 안보리", "유엔 안전보장이사회"), ("가상전자(주)", "가상전자"),
])
def test_org_same(a, b):
    assert names.org(a)[0] == names.org(b)[0]


def test_org_different():
    assert names.org("한국은행")[0] != names.org("일본은행")[0]
    assert names.org("영국 보수당")[0] != names.org("보수당")[0]  # 나라가 있고 없음은 사전 밖에서 맞추지 않는다
    assert names.country("대한민국")[1] == names.country("한국")[1] == "한국"


def _con(tmp_path):
    con = db.connect(tmp_path / "t.db")
    t = tmp_path / "fakeVID0001.json"
    t.write_text(json.dumps({"text": TRANSCRIPT, "segments": []}, ensure_ascii=False), encoding="utf-8")
    db.put_videos(con, [{"video_id": "fakeVID0001", "title": "지어낸 제목", "upload_at": UPLOAD, "duration_sec": 900,
                         "kind": "본편", "has_transcript": 1, "transcript_source": "daglo", "transcript_path": str(t),
                         "chars": len(TRANSCRIPT), "in_uploads": 1, "in_transcripts": 1}])
    return con


def test_db_put_idempotent_and_find(tmp_path):
    con = _con(tmp_path)
    d = doc()
    db_v3.put(con, d)
    first = db_v3.counts(con)
    db_v3.put(con, copy.deepcopy(d))
    assert db_v3.counts(con) == first
    assert first["v3_videos"] == 1 and first["v3_segments"] == 2 and first["v3_claims"] == 6
    d2 = doc()
    d2["segments"] = d2["segments"][:1]
    d2["n_segments"] = 1
    db_v3.put(con, d2)  # 토막이 줄면 남은 행이 없어야 한다
    assert db_v3.counts(con)["v3_segments"] == 1
    db_v3.put(con, d)
    rows = db_v3.find(con, "별빛전자")
    assert [(r["video_id"], r["seg"]) for r in rows] == [("fakeVID0001", 2)]
    assert "기관" in rows[0]["matched"] and rows[0]["upload_at"] == UPLOAD
    assert [r["seg"] for r in db_v3.find(con, "물가")] == [1]
    assert db_v3.find(con, "없는낱말") == []
    # 맞춘 표기로도 찾는다
    d["segments"][0]["people"] = ["트럼프"]
    d["segments"][0]["main_person"] = "트럼프"
    db_v3.put(con, d)
    assert [r["seg"] for r in db_v3.find(con, "도널드 트럼프")] == [1]


def test_old_tables_untouched(tmp_path):
    con = _con(tmp_path)
    db.put_record(con, "fakeVID0001", "opus", 2, {"x": 1}, 10)
    db_v3.put(con, doc())
    assert con.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1


def test_cli_validate_and_load(tmp_path, monkeypatch, capsys):
    _con(tmp_path).close()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    folder = tmp_path / "extract_v3"
    folder.mkdir()
    good = folder / "fakeVID0001.json"
    good.write_text(json.dumps(doc(), ensure_ascii=False), encoding="utf-8")
    assert cli.main(["validate-v3", str(good)]) == 0
    bad = folder / "wrongName.json"
    bad.write_text(json.dumps(doc(ad_disclosure="몰라"), ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["validate-v3", str(bad)]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert any(l.startswith("파일 이름") for l in out) and any(l.startswith("ad_disclosure") for l in out)
    assert cli.main(["load-v3", str(folder)]) == 1      # 하나는 걸린다
    assert cli.main(["load-v3", str(folder)]) == 1
    con = db.connect(tmp_path / "t.db")
    assert db_v3.counts(con)["v3_videos"] == 1 and db_v3.counts(con)["v3_segments"] == 2
    con.close()
    capsys.readouterr()
    assert cli.main(["find-v3", "몽돌국"]) == 0
    assert "fakeVID0001 #1" in capsys.readouterr().out


def _row(vid, year, kind="본편", title="지어낸 제목", chars=5000):
    return {"video_id": vid, "title": title, "upload_at": f"{year}-05-01 19:00", "kind": kind, "has_transcript": 1,
            "chars": chars, "transcript_path": f"x/{vid}.json"}


def test_pilot_pick():
    rows = [_row(f"m{y}{i}", y) for y in range(2018, 2027) for i in range(6)]
    rows += [_row(f"l{y}{i}", y, kind="생방송 전체") for y in (2018, 2019, 2022, 2024, 2026) for i in range(3)]
    rows += [_row("ad1", 2021, title="지어낸 회사 소개 [유료광고포함]"), _row("ad2", 2022, title="[가상부 x 슈카월드] 지어낸 제목"),
             _row("short", 2020, chars=100), _row("ex1", 2020)]
    tags = {r["video_id"]: ("금융·증시" if i % 2 else "사회·문화") for i, r in enumerate(rows)}
    picks = pilot.pick(rows, tags, exclude={"ex1"})
    ids = [r["video_id"] for r in picks]
    assert len(picks) == 30 and len(set(ids)) == 30
    assert "ex1" not in ids and "short" not in ids
    assert {"ad1", "ad2"} <= set(ids) and sum(r["ad_title"] for r in picks) == 2
    lives = [r for r in picks if r["kind"] == "생방송 전체"]
    assert len(lives) == 6 and len({r["upload_at"][:4] for r in lives}) == 5  # 다른 해가 5개뿐이면 한 해에서 둘
    assert pilot.pick(rows, tags, exclude={"ex1"}) == picks  # 씨앗이 같으면 같다
    assert pilot.is_ad_title("지어낸 영상 (유료 광고 포함)") and not pilot.is_ad_title("광고 시장 이야기")
