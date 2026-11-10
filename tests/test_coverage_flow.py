"""⑥ 기존 커버리지의 흐름 칸(relation·gist) 회귀 테스트.
비공개 자료 없이 임시 폴더의 합성 카드만 쓴다. 예시 문장은 전부 지어낸 것이다."""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.research import cards as C  # noqa: E402
from ozl.research import report  # noqa: E402
from test_desk import make_card, make_claim  # noqa: E402

CID = "2026-11-10-am-01"
HEAD = "| 때 | 영상 | 무엇을 다뤘나 | 관계 |"


def claims():
    return [make_claim(i) for i in (1, 2, 3)]


def vid(n, date, **kw):
    return {"video_id": f"vid{n:08d}", "title": f"지어낸 영상 {n}", "date": date, **kw}


def section6(md: str) -> str:
    return md.split("**⑥ ", 1)[1].split("**⑦ ", 1)[0]


def cols(row: str) -> int:
    """이스케이프된 \\| 는 칸 구분이 아니다."""
    return len(row.replace("\\\\", "").replace("\\|", "").strip().strip("|").split("|"))


# ── 검사 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,needle", [
    (vid(1, "2025-01-02", relation="원인"), "relation 오류"),
    (vid(1, "2025-01-02", relation="배경", gist="가" * 61), "gist"),
    (vid(1, "2025-01-02", gist="지어낸 요지\n둘째 줄"), "gist"),
    (vid(1, "2025-02-30", relation="후속"), "relation 을 붙인 영상"),
])
def test_flow_fields_are_checked(v, needle):
    card = make_card()
    card["coverage"]["videos"] = [v]
    errs = C.validate_card(card, claims())
    assert any(needle in e for e in errs), errs


def test_gist_at_limit_and_fields_absent_pass():
    card = make_card()
    card["coverage"]["videos"] = [vid(1, "2025-01-02", relation="배경", gist="가" * 60), vid(2, "2024-05-06")]
    assert C.validate_card(card, claims()) == []
    card["coverage"]["videos"] = [vid(1, "2025-01-02"), vid(2, "2024-05-06")]     # 둘 다 없어도 오류가 아니다
    assert C.validate_card(card, claims()) == []


def test_relation_capped_per_card():
    card = make_card()
    card["coverage"]["videos"] = [vid(i, f"2025-01-{i:02d}", relation="같은 주제") for i in range(1, 9)]
    assert C.validate_card(card, claims()) == []
    card["coverage"]["videos"].append(vid(9, "2025-01-09", relation="같은 주제"))
    assert any("9편" in e for e in C.validate_card(card, claims()))


# ── 렌더 ─────────────────────────────────────────────────────────────
def test_without_relation_keeps_old_list():
    card = make_card()
    card["coverage"]["videos"] = [vid(2, "2025-06-01", gist="지어낸 요지"), vid(1, "2024-01-01")]
    s6 = section6(report.render_card(card, claims(), 1, public=False))
    assert HEAD not in s6
    assert s6 == ("슈카월드 기존 커버리지** — 전용 영상 없음\n"
                  "  - 2025-06-01 [지어낸 영상 2](https://youtu.be/vid00000002)\n"
                  "  - 2024-01-01 [지어낸 영상 1](https://youtu.be/vid00000001)\n"
                  "  - _대조 낱말: 가상_\n\n")


def flow_card():
    card = make_card()
    card["coverage"]["videos"] = [vid(3, "2026-03-04", relation="후속", gist="지어낸 뒷이야기"),
                                  vid(1, "2024-01-15", relation="배경"),
                                  vid(2, "2025-07-20", title="지어낸 | 제목 [특집]", gist="가|나 ] 다")]
    return card


def table_rows(md: str) -> list[str]:
    return [ln for ln in section6(md).splitlines() if ln.startswith("|")]


def test_relation_renders_sorted_table():
    card = flow_card()
    assert C.validate_card(card, claims()) == []
    rows = table_rows(report.render_card(card, claims(), 1, public=False))
    assert rows[0] == HEAD and rows[1] == "|---|---|---|---|"
    body = rows[2:]
    assert [r.split(" | ")[0] for r in body] == ["| 2024-01", "| 2025-07", "| 2026-03"]     # 날짜 오름차순 · 때는 YYYY-MM
    assert body[0] == "| 2024-01 | [지어낸 영상 1](https://youtu.be/vid00000001) |  | 배경 |"   # gist 없으면 빈칸
    assert body[2] == "| 2026-03 | [지어낸 영상 3](https://youtu.be/vid00000003) | 지어낸 뒷이야기 | 후속 |"
    # 제목·요지가 잘리지 않고 이스케이프됐는지 행 전체로 본다 · relation 없으면 「-」
    assert body[1] == r"| 2025-07 | [지어낸 \| 제목 \[특집\]](https://youtu.be/vid00000002) | 가\|나 \] 다 | - |"
    assert all(cols(r) == 4 for r in rows)                                                # | 와 ] 가 있어도 4열


def test_table_dates_are_parsed_not_string_sorted():
    card = make_card()
    card["coverage"]["videos"] = [vid(1, "2025-10-05", relation="후속"), vid(2, "2025-2-01", relation="배경"),
                                  vid(3, "언젠가|쯤"), vid(4, "2025-3-9")]      # 한 자리 월·일도 실제 날짜로 푼다
    # 날짜 검사는 기존 규칙 그대로다 — 한 자리 월은 통과하고, 풀 수 없는 날짜만 기존 오류 하나로 걸린다
    assert C.validate_card(card, claims()) == [f"{CID}: ⑥ videos 항목의 video_id·title·date 오류"]
    rows = table_rows(report.render_card(card, claims(), 1, public=False))[2:]
    assert [r.split(" | ")[0] for r in rows] == ["| 2025-02", "| 2025-03", "| 2025-10", r"| 언젠가\|쯤"]   # 풀 수 없는 날짜는 맨 뒤 · 적힌 그대로
    assert all(cols(r) == 4 for r in rows)


def test_relation_needs_youtube_id_and_link_is_encoded():
    card = make_card()
    card["coverage"]["videos"] = [vid(1, "2025-01-02", relation="배경", video_id="abc|def")]
    assert any("video_id" in e and "11자" in e for e in C.validate_card(card, claims()))
    card["coverage"]["videos"] = [vid(1, "2025-01-02", relation="배경", video_id="Ab_-12345cD")]
    assert C.validate_card(card, claims()) == []
    card["coverage"]["videos"].append(vid(2, "2025-01-03", video_id="abc|def"))   # relation 없는 형제는 기존 검사 그대로
    assert C.validate_card(card, claims()) == []
    rows = table_rows(report.render_card(card, claims(), 1, public=False))[2:]
    assert rows[1] == "| 2025-01 | [지어낸 영상 2](https://youtu.be/abc%7Cdef) |  | - |"
    assert all(cols(r) == 4 for r in rows)


@pytest.mark.parametrize("title,shown", [(0, "0"), (False, "False"), (None, "")])
def test_cell_keeps_falsy_values(title, shown):
    assert report._cell(title) == shown
    card = make_card()
    card["coverage"]["videos"] = [vid(1, "2025-01-02", relation="배경", title=title)]
    assert table_rows(report.render_card(card, claims(), 1, public=False))[2] == \
        f"| 2025-01 | [{shown}](https://youtu.be/vid00000001) |  | 배경 |"


def test_public_render_has_same_table(desk):
    cid = CID
    card = flow_card()
    C.save_yaml(C.card_path(cid), card)
    C.human_verify([f"{cid}-c{i}" for i in (1, 2, 3)], "tester")
    C.approve_publish(cid, "tester")
    card, cl = C.load_card(cid), C.claims_for(cid)
    pub, prv = report.render_card(card, cl, 1, public=True), report.render_card(card, cl, 1, public=False)
    assert table_rows(pub) == table_rows(prv) and HEAD in pub
    assert "지어낸 뒷이야기" in pathlib.Path(report.render_all("2026-11-10", "am")["paths"]["public"]).read_text(encoding="utf-8")


@pytest.fixture()
def desk(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "DESK", tmp_path / "desk")
    monkeypatch.setattr(C, "CARDS", tmp_path / "desk" / "cards")
    monkeypatch.setattr(C, "CLAIMS", tmp_path / "desk" / "claims")
    monkeypatch.setattr(C, "PUB_CLAIMS", tmp_path / "claims")
    monkeypatch.setattr(report, "ROOT", tmp_path)
    for i in (1, 2, 3):
        c = make_claim(i)
        C.save_yaml(C.claim_path(c["claim_id"]), c)
    return tmp_path
