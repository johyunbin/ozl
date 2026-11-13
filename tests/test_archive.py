"""카드 원장·발행 카드 색인·사이트 「기록」 쪽 회귀 테스트.
비공개 자료 없이 임시 폴더의 합성 카드만 쓴다. 예시 문장은 전부 지어낸 것이다."""
from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.research import archive  # noqa: E402
from ozl.research import cards as C  # noqa: E402
from ozl.research import report  # noqa: E402
from test_desk import make_card, make_claim  # noqa: E402

CID = "2026-11-10-am-01"
OLD_KEYS = {"제목", "card_id", "date:날짜:start", "date:날짜:is_datetime", "회차", "상태", "주제", "민감도", "배지", "출처 수",
            "왜 오늘인가", "반전 포인트", "기존 커버리지", "Pages 링크", "revision"}


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


def approve(cid=CID):
    C.human_verify([f"{cid}-c{i}" for i in (1, 2, 3)], "tester")
    C.approve_publish(cid, "tester")


def index_text(desk) -> str:
    return (desk / "daily" / "index.json").read_text(encoding="utf-8")


# ── 발행 카드 색인 ────────────────────────────────────────────────────
def test_index_follows_publishable(desk):
    r = report.render_all("2026-11-10", "am")
    assert r["paths"]["index"] == str(desk / "daily" / "index.json")
    idx = json.loads(index_text(desk))
    assert "지어낸 제목 하나" not in index_text(desk) and idx["cards"] == []          # 승인 전에는 제목이 없다
    assert idx["reports"] == [] and r["paths"]["public"] is None and r["published"] == 0   # 공개 이력이 없는 회차는 발행본을 쓰지 않는다
    assert not (desk / "daily" / "2026" / "11" / "2026-11-10_am.md").exists()
    approve()
    report.render_all("2026-11-10", "am")
    idx = json.loads(index_text(desk))
    assert [c["title"] for c in idx["cards"]] == ["지어낸 제목 하나"]
    assert idx["cards"][0] == {"card_id": CID, "date": "2026-11-10", "slot": "am", "title": "지어낸 제목 하나", "category": "기타",
                               "badge": "확인", "url": report.page_url(CID)}
    assert idx["reports"][0]["published"] == 1
    C.withdraw(CID, "tester", "지어낸 철회 사유")
    report.render_all("2026-11-10", "am")
    assert "지어낸 제목 하나" not in index_text(desk) and CID not in index_text(desk)   # 철회하면 다시 빠진다
    assert json.loads(index_text(desk))["reports"][0]["published"] == 0                   # 쪽은 남는다(철회 기록이 실린다)
    assert (desk / "daily" / "2026" / "11" / "2026-11-10_am.md").exists()


def test_index_keeps_published_card_even_if_rejected(desk):
    approve()
    C.set_state(CID, "반려")                                 # 상태는 지문 밖 — 승인은 그대로 유효
    report.render_all("2026-11-10", "am")
    assert [c["card_id"] for c in json.loads(index_text(desk))["cards"]] == [CID]


def test_index_is_unescaped_and_deterministic(desk):
    approve()
    report.render_all("2026-11-10", "am")
    first = index_text(desk)
    assert "\\u" not in first and "지어낸 제목 하나" in first and first.endswith("}\n")
    archive.write_index()
    assert index_text(desk) == first                        # 다시 써도 글자 하나 바뀌지 않는다


def test_index_refuses_when_report_has_no_cards(desk):
    approve()                                               # 발행본이 생기는 회차로 시작한다(승인 전 회차는 발행본이 없다)
    report.render_all("2026-11-10", "am")
    before = index_text(desk)
    orphan = desk / "daily" / "2026" / "11" / "2026-11-09_pm.md"
    orphan.write_text("# 지어낸 발행본\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="2026-11-09 pm"):
        archive.write_index()
    assert index_text(desk) == before                       # 색인은 건드리지 않는다
    orphan.unlink()
    (desk / "daily" / "index.json").unlink()
    for p in C.CARDS.glob("*.yaml"):
        p.unlink()
    with pytest.raises(FileNotFoundError):                  # 카드 폴더도 기존 색인도 없는 기기에서 돌린 경우
        archive.write_index()


def make_other_slot(desk, title="지어낸 저녁 제목"):
    """다른 회차(11-09 저녁)를 발행·렌더해 색인에 올린 뒤, 그 회차의 비공개 카드만 지운다 — 카드가 없는 기기를 흉내 낸다."""
    other = make_card()
    oid = "2026-11-09-pm-01"
    other.update(card_id=oid, date="2026-11-09", slot="pm", titles=[title, "지어낸 저녁 후보"])
    for d in other["data"]:
        d["claim_id"] = d["claim_id"].replace("2026-11-10-am-01", oid)
    C.save_yaml(C.card_path(oid), other)
    for i in (1, 2, 3):
        cl = make_claim(i)
        cl.update(claim_id=f"{oid}-c{i}", card_id=oid)
        C.save_yaml(C.claim_path(cl["claim_id"]), cl)
    approve(oid)
    report.render_all("2026-11-09", "pm")
    C.card_path(oid).unlink()
    return oid


def test_render_refuses_before_writing_anything(desk):
    # 1(가): 색인을 먼저 만든다 — 카드도 기존 색인 항목도 없는 회차가 있으면 보고서도 색인도 쓰지 않는다
    approve()
    report.render_all("2026-11-10", "am")
    pub = desk / "daily" / "2026" / "11" / "2026-11-10_am.md"
    before_pub, before_idx = pub.read_text(encoding="utf-8"), index_text(desk)
    orphan = desk / "daily" / "2026" / "11" / "2026-11-08_pm.md"
    orphan.write_text("# 지어낸 발행본\n", encoding="utf-8")
    C.withdraw(CID, "tester", "지어낸 철회 사유")
    with pytest.raises(FileNotFoundError, match="2026-11-08 pm"):
        report.render_all("2026-11-10", "am")
    assert pub.read_text(encoding="utf-8") == before_pub and index_text(desk) == before_idx


def test_render_carries_over_cardless_slot_and_reflects_withdrawal(desk, capsys):
    # 1(나): 카드가 없는 회차는 기존 색인 항목을 넘겨 쓰고, 지금 렌더하는 회차의 철회는 반드시 반영한다
    approve()
    report.render_all("2026-11-10", "am")
    oid = make_other_slot(desk)
    old = json.loads(index_text(desk))
    old_report = [r for r in old["reports"] if r["slot"] == "pm"]
    C.withdraw(CID, "tester", "지어낸 철회 사유")
    capsys.readouterr()
    report.render_all("2026-11-10", "am")
    idx = json.loads(index_text(desk))
    assert "지어낸 제목 하나" not in index_text(desk) and CID not in [c["card_id"] for c in idx["cards"]]
    assert [c["card_id"] for c in idx["cards"]] == [oid] and "지어낸 저녁 제목" in index_text(desk)
    assert [r for r in idx["reports"] if r["slot"] == "pm"] == old_report
    assert [r for r in idx["reports"] if r["slot"] == "am"][0]["published"] == 0
    assert "2026-11-09 pm" in capsys.readouterr().err


# ── 카드 원장 ─────────────────────────────────────────────────────────
def read_ledger(path: pathlib.Path) -> list[dict]:
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")                  # 엑셀에서 한글이 깨지지 않게 BOM
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_ledger_times_match_history(desk):
    other = make_card()
    other.update(card_id="2026-11-10-am-02", rank=2, titles=["지어낸 둘째 제목", "지어낸 둘째 후보"])
    C.save_yaml(C.card_path(other["card_id"]), other)        # 클레임이 없는 카드도 한 줄 차지한다
    C.set_state(CID, "채택")
    approve()
    C.set_state(CID, "보류")
    C.set_state(CID, "채택")                                 # 다시 채택하면 가장 최근 것
    path, n = archive.write_ledger()
    assert path == desk / "desk" / "ledger.csv" and n == 2
    rows = read_ledger(path)
    assert list(rows[0]) == archive.LEDGER_COLUMNS and [r["card_id"] for r in rows] == [CID, "2026-11-10-am-02"]
    hist = C.load_card(CID)["history"]
    picks = [h["at"] for h in hist if h["event"] == "state → 채택"]
    pubs = [h["at"] for h in hist if h["event"] == "공개 발행 승인"]
    r = rows[0]
    assert r["picked_at"] == picks[-1] and r["published_at"] == pubs[0] and r["republished_at"] == ""
    assert (r["publish"], r["badge"], r["claims"], r["human_verified"], r["videos"]) == ("발행", "확인", "3", "3", "0")
    assert r["title"] == "지어낸 제목 하나" and r["topic"] == "가상 분야" and r["withdrawn_at"] == ""
    assert rows[1]["publish"] == "미발행" and rows[1]["picked_at"] == rows[1]["published_at"] == "" and rows[1]["claims"] == "0"


def test_ledger_records_republish_and_withdraw(desk):
    card = C.load_card(CID)
    card["history"] = [{"at": "2026-11-10T09:00:00+09:00", "event": "state → 채택"},
                       {"at": "2026-11-10T10:00:00+09:00", "event": "공개 발행 승인"},
                       {"at": "2026-11-10T11:00:00+09:00", "event": "state → 반려 — 지어낸 사유"},
                       {"at": "2026-11-10T12:00:00+09:00", "event": "공개 발행 승인"}]
    C.save_yaml(C.card_path(CID), card)
    assert C.event_times(card) == {"picked_at": "2026-11-10T09:00:00+09:00", "published_at": "2026-11-10T10:00:00+09:00",
                                   "republished_at": "2026-11-10T12:00:00+09:00", "withdrawn_at": ""}
    approve()                                                  # 실제 재승인 한 번 더
    C.withdraw(CID, "tester", "지어낸 철회 사유")
    r = read_ledger(archive.write_ledger()[0])[0]
    after = C.load_card(CID)
    pubs = [h["at"] for h in after["history"] if h["event"] == "공개 발행 승인"]
    assert r["published_at"] == "2026-11-10T10:00:00+09:00" and r["republished_at"] == pubs[-1] != pubs[0]
    assert r["withdrawn_at"] == after["publish"]["withdrawn_at"] and r["publish"] == "철회"


def test_publish_status_three_ways(desk):
    assert C.publish_status(C.load_card(CID), C.claims_for(CID)) == "미발행"
    approve()
    assert C.publish_status(C.load_card(CID), C.claims_for(CID)) == "발행"
    C.withdraw(CID, "tester", "지어낸 철회 사유")
    assert C.publish_status(C.load_card(CID), C.claims_for(CID)) == "철회"


# ── Notion 속성 ──────────────────────────────────────────────────────
def test_notion_rows_add_fields_and_keep_old_ones(desk):
    p0 = report.notion_rows("2026-11-10", "am")[0]["properties"]
    assert set(p0) == OLD_KEYS | {"발행", "세부 주제"}               # 날짜가 없으면 날짜 키를 넣지 않는다
    assert p0["발행"] == "미발행" and p0["세부 주제"] == "가상 분야"
    assert (p0["제목"], p0["주제"], p0["배지"], p0["Pages 링크"], p0["date:날짜:is_datetime"]) == ("지어낸 제목 하나", "기타", "pending", None, 0)
    C.set_state(CID, "채택")
    approve()
    p1 = report.notion_rows("2026-11-10", "am")[0]["properties"]
    ev = C.event_times(C.load_card(CID))
    assert set(p1) == OLD_KEYS | {"발행", "세부 주제", "date:채택일:start", "date:발행일:start"}
    assert p1["date:채택일:start"] == ev["picked_at"][:10] and p1["date:발행일:start"] == ev["published_at"][:10]
    assert p1["발행"] == "발행" and p1["Pages 링크"] == report.page_url(CID) and p1["상태"] == "채택"


# ── 사이트 「기록」 쪽 ─────────────────────────────────────────────────
def load_build_site():
    spec = importlib.util.spec_from_file_location("build_site_under_test", ROOT / "scripts" / "build_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_site(tmp_path, index: dict | None, reports: dict[str, str]) -> pathlib.Path:
    for name, body in reports.items():
        p = tmp_path / "daily" / name[:4] / name[5:7] / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (tmp_path / "daily").mkdir(exist_ok=True)
    if index is not None:
        (tmp_path / "daily" / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return tmp_path


INDEX = {"schema": 1,
         "reports": [{"date": "2026-10-31", "slot": "pm", "file": "daily/2026/10/2026-10-31_pm.md", "cards": 4, "published": 1},
                     {"date": "2026-11-10", "slot": "am", "file": "daily/2026/11/2026-11-10_am.md", "cards": 6, "published": 2}],
         "cards": [{"card_id": "2026-10-31-pm-03", "date": "2026-10-31", "slot": "pm", "title": "지어낸 시월 제목", "category": "기타", "badge": "추정", "url": "u"},
                   {"card_id": "2026-11-10-am-01", "date": "2026-11-10", "slot": "am", "title": "지어낸 | 막대 제목", "category": "기타", "badge": "확인", "url": "u"},
                   {"card_id": "2026-11-10-am-02", "date": "2026-11-10", "slot": "am", "title": "지어낸 둘째", "category": "기타", "badge": "확인", "url": "u"}]}
REPORTS = {"2026-10-31_pm.md": '# 지어낸 시월\n\n<a id="pm-03"></a>\n',
           "2026-11-10_am.md": '# 지어낸 십일월\n\n<a id="am-01"></a>\n\n<a id="am-02"></a>\n'}


def test_build_site_import_does_nothing():
    target = ROOT / "docs" / "daily" / "index.md"
    before = target.stat().st_mtime_ns if target.exists() else None
    mod = load_build_site()
    assert callable(mod.main)
    assert (target.stat().st_mtime_ns if target.exists() else None) == before


def test_build_site_groups_by_month(tmp_path):
    root = make_site(tmp_path, INDEX, REPORTS)
    assert load_build_site().main(root) == 0
    assert sorted(p.name for p in (root / "docs" / "daily").iterdir()) == ["2026-10-31_pm.md", "2026-11-10_am.md", "index.md"]
    md = (root / "docs" / "daily" / "index.md").read_text(encoding="utf-8")
    assert md.startswith("# 기록\n")
    assert "## 2026년 11월\n\n- [2026-11-10 아침](2026-11-10_am.md) · 카드 6장, 발행 2장" in md
    assert "- [2026-10-31 저녁](2026-10-31_pm.md) · 카드 4장, 발행 1장" in md
    assert md.index("## 2026년 11월\n") < md.index("## 2026년 10월\n") < md.index("## 2026년 11월 발행 카드") < md.index("## 2026년 10월 발행 카드")
    assert "| 날짜 | 제목 | 분야 | 배지 |" in md
    assert "| 2026-11-10 아침 | [지어낸 \\| 막대 제목](2026-11-10_am.md#am-01) | 기타 | 확인 |" in md
    assert "[지어낸 시월 제목](2026-10-31_pm.md#pm-03)" in md
    assert md.index("#am-01)") < md.index("#am-02)")               # 한 회차 안에서는 카드 번호 순


def test_build_site_without_index_lists_files_and_warns(tmp_path, capsys):
    root = make_site(tmp_path, None, REPORTS)
    assert load_build_site().main(root) == 0
    md = (root / "docs" / "daily" / "index.md").read_text(encoding="utf-8")
    assert "- [2026-11-10 아침](2026-11-10_am.md)\n" in md and "발행 카드" not in md and "카드 6장" not in md
    assert "index.json" in capsys.readouterr().err


def test_build_site_fails_on_missing_anchor_or_report(tmp_path):
    root = make_site(tmp_path, INDEX, {**REPORTS, "2026-11-10_am.md": '<a id="am-01"></a>\n'})
    assert load_build_site().main(root) == 1                 # am-02 자리표가 없다
    other = tmp_path / "second"
    other.mkdir()
    root2 = make_site(other, INDEX, {"2026-11-10_am.md": REPORTS["2026-11-10_am.md"]})
    assert load_build_site().main(root2) == 1                # 시월 보고서 파일이 없다


def test_build_site_without_reports(tmp_path):
    root = make_site(tmp_path, None, {})
    assert load_build_site().main(root) == 0
    assert "아직 발행된 보고서가 없습니다." in (root / "docs" / "daily" / "index.md").read_text(encoding="utf-8")


# ── 검토 반례(2026-11-10 Codex 검토 2~7) ─────────────────────────────
def test_withdrawn_at_survives_reapproval(desk):
    # 2: 승인 → 철회 → 재승인하면 publish 칸이 바뀌어도 철회 시각은 history 에서 남는다
    approve()
    C.withdraw(CID, "tester", "지어낸 철회 사유")
    approve()
    card = C.load_card(CID)
    assert "withdrawn_at" not in card["publish"]
    last = [h["at"] for h in card["history"] if h["event"].startswith("발행 철회")][-1]
    assert C.event_times(card)["withdrawn_at"] == last != ""
    assert C.publish_status(card, C.claims_for(CID)) == "발행"


def test_event_times_takes_latest_pick():
    # 7: 서로 다른 시각을 직접 넣어 '첫 채택을 돌려주는 오류'를 잡는다
    card = {"history": [{"at": "2026-11-10T09:00:00+09:00", "event": "state → 채택"},
                        {"at": "2026-11-10T10:00:00+09:00", "event": "state → 보류"},
                        {"at": "2026-11-10T11:00:00+09:00", "event": "state → 채택"},
                        {"at": "2026-11-10T12:00:00+09:00", "event": "발행 철회 — 지어낸 사유"},
                        {"at": "2026-11-10T13:00:00+09:00", "event": "발행 철회 — 지어낸 둘째 사유"}],
            "publish": {"approved": False, "withdrawn_at": "2026-11-10T13:00:00+09:00"}}
    ev = C.event_times(card)
    assert ev["picked_at"] == "2026-11-10T11:00:00+09:00" and ev["withdrawn_at"] == "2026-11-10T13:00:00+09:00"
    assert C.event_times({"publish": {"withdrawn_at": "2026-11-10T08:00:00+09:00"}})["withdrawn_at"] == "2026-11-10T08:00:00+09:00"


def test_build_site_fails_when_indexed_report_missing(tmp_path, capsys):
    # 3: 카드가 비어 있어도 색인의 reports 가 가리키는 파일이 없으면 실패
    idx = {**INDEX, "cards": [], "reports": [{**r, "published": 0} for r in INDEX["reports"]]}
    root = make_site(tmp_path, idx, {"2026-11-10_am.md": REPORTS["2026-11-10_am.md"]})
    assert load_build_site().main(root) == 1
    assert "2026-10-31_pm.md" in capsys.readouterr().err


def test_build_site_lists_unindexed_report_with_warning(tmp_path, capsys):
    # 3: 파일은 있는데 색인에 없는 보고서는 목록에 넣고 경고만
    root = make_site(tmp_path, INDEX, {**REPORTS, "2026-11-11_pm.md": "# 지어낸 새 회차\n"})
    assert load_build_site().main(root) == 0
    md = (root / "docs" / "daily" / "index.md").read_text(encoding="utf-8")
    assert "- [2026-11-11 저녁](2026-11-11_pm.md)\n" in md
    assert "2026-11-11_pm.md" in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["null", "{}", "[]", '{"schema": 2, "reports": [], "cards": []}',
                                 '{"schema": 1, "reports": {}, "cards": []}', '{"schema": 1, "reports": [], "cards": [{"card_id": "x"}]}',
                                 '{"schema": 1, "reports": [{"date": "2026-11-10", "slot": "am", "file": "daily/2026/11/2026-11-10_am.md", "cards": "6", "published": 1}], "cards": []}',
                                 "{ 깨진"])
def test_build_site_rejects_malformed_index(tmp_path, raw):
    # 4: 있는데 모양이 틀린 색인은 '없는 색인'으로 넘기지 않는다
    root = make_site(tmp_path, None, REPORTS)
    (root / "daily" / "index.json").write_text(raw, encoding="utf-8")
    assert load_build_site().main(root) == 1


@pytest.mark.parametrize("patch", [
    lambda i: i["cards"][1].update(date="../2026-11-10"),
    lambda i: i["cards"][1].update(slot="am/../x"),
    lambda i: i["cards"][1].update(card_id="2026-11-10-am-01/../../x"),
    lambda i: i["cards"][1].update(card_id="2026-11-10-pm-01"),                 # 날짜·회차와 다른 card_id
    lambda i: i["reports"][1].update(date="2026-11-10\n"),
    lambda i: i["reports"][1].update(file="daily/../../etc/2026-11-10_am.md"),
])
def test_build_site_rejects_bad_ids_and_paths(tmp_path, patch):
    # 5: 경로를 만드는 값은 형식을 정확히 맞춰야 한다
    idx = json.loads(json.dumps(INDEX))
    patch(idx)
    root = make_site(tmp_path, idx, REPORTS)
    assert load_build_site().main(root) == 1


def _split_cells(row: str) -> list[str]:
    """역슬래시로 이스케이프되지 않은 | 로만 칸을 나눈다."""
    cells, cur, i = [], "", 0
    while i < len(row):
        ch = row[i]
        if ch == "\\" and i + 1 < len(row):
            cur += row[i:i + 2]
            i += 2
            continue
        if ch == "|":
            cells.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    return cells + [cur]


def test_build_site_escapes_table_cells(tmp_path):
    # 6: 역슬래시·대괄호·막대가 섞인 제목도 칸 수와 링크 모양이 그대로다
    import re
    idx = json.loads(json.dumps(INDEX))
    idx["cards"][1]["title"] = "지어낸 \\| [괄호] 제목 \\"
    idx["cards"][1]["category"] = "기타|분야"
    root = make_site(tmp_path, idx, REPORTS)
    assert load_build_site().main(root) == 0
    md = (root / "docs" / "daily" / "index.md").read_text(encoding="utf-8")
    row = next(l for l in md.splitlines() if "#am-01)" in l)
    cells = _split_cells(row)
    assert len(cells) == 6 and cells[0] == "" and cells[-1] == ""        # 앞뒤 빈칸 + 4열
    assert re.fullmatch(r" \[(?:\\.|[^\\\[\]])*\]\(2026-11-10_am\.md#am-01\) ", cells[2]), cells[2]
    assert cells[2] == " [지어낸 \\\\\\| \\[괄호\\] 제목 \\\\](2026-11-10_am.md#am-01) "
    assert cells[3] == " 기타\\|분야 "


# ── 재검토 반례(2026-11-10 Codex 재검토 1~4) ────────────────────────
def test_carry_over_rejects_mismatched_prior_entry(desk):
    # 1: 카드가 없는 회차의 옛 항목에 다른 회차의 card_id 가 들어 있으면 넘겨 쓰지 않고 예외
    approve()
    report.render_all("2026-11-10", "am")
    make_other_slot(desk)
    bad = json.loads(index_text(desk))
    for c in bad["cards"]:
        if c["slot"] == "pm":
            c.update(card_id=CID, title="지어낸 옛 제목")
    (desk / "daily" / "index.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    pub = desk / "daily" / "2026" / "11" / "2026-11-10_am.md"
    before = pub.read_text(encoding="utf-8")
    C.withdraw(CID, "tester", "지어낸 철회 사유")
    with pytest.raises(ValueError, match="card_id"):
        report.render_all("2026-11-10", "am")
    assert pub.read_text(encoding="utf-8") == before        # 미리 거르기에서 멈춰 아무것도 쓰지 않았다
    assert archive.index_errors(bad) and "card_id" in " ".join(archive.index_errors(bad))


def test_carry_over_skips_ids_that_exist_privately(desk, monkeypatch):
    # 1: 비공개 카드가 있는 card_id 는 옛 항목을 쓰지 않고 현재 판정만 — 중복도 옛 제목도 남지 않는다
    approve()
    report.render_all("2026-11-10", "am")
    oid = make_other_slot(desk)
    real = C.all_cards
    ghost = {**make_card(), "card_id": oid, "date": "2026-11-09", "slot": "pm", "publish": {"approved": False}}
    monkeypatch.setattr(C, "all_cards", lambda: sorted(real() + [ghost], key=lambda c: c["card_id"]))
    with pytest.raises(ValueError, match="발행 1장과 색인 카드 0장"):   # 옛 카드는 빠지고, 옛 발행 수와 어긋나 저장하지 않는다
        archive.build_index()
    assert C.card_path(oid).exists() is False


def test_index_rejects_duplicates_and_bad_counts():
    # 1·4: 병합 결과나 저장 직전 색인에 중복·건수 모순이 있으면 통과시키지 않는다
    good = json.loads(json.dumps(INDEX))
    assert archive.index_errors(good) == []
    dup_card = json.loads(json.dumps(INDEX))
    dup_card["cards"].append(dict(dup_card["cards"][1]))
    dup_card["reports"][1]["published"] = 3
    dup_card["reports"][1]["cards"] = 6
    assert any("둘 이상" in e for e in archive.index_errors(dup_card))
    dup_report = json.loads(json.dumps(INDEX))
    dup_report["reports"].append(dict(dup_report["reports"][1]))
    assert any("둘 이상" in e for e in archive.index_errors(dup_report))
    over = json.loads(json.dumps(INDEX))
    over["reports"][0]["published"] = 5
    assert any("건수 모순" in e for e in archive.index_errors(over))
    short = json.loads(json.dumps(INDEX))
    short["reports"][1]["published"] = 1
    assert any("다르다" in e for e in archive.index_errors(short))
    orphan = json.loads(json.dumps(INDEX))
    orphan["reports"].pop(0)
    assert any("보고서가 색인에 없다" in e for e in archive.index_errors(orphan))
    with pytest.raises(ValueError):
        archive.save_index(short, pathlib.Path("/nonexistent/never-written.json"))


def test_render_saves_index_computed_after_reports(desk, monkeypatch):
    # 2: 미리 거른 뒤 보고서를 쓰는 사이에 철회되면, 색인은 나중 상태(철회 반영)를 저장한다
    approve()
    report.render_all("2026-11-10", "am")
    real_public = report.render_public

    def public_then_withdraw(date, slot):
        text = real_public(date, slot)
        C.withdraw(CID, "tester", "지어낸 동시 철회")         # 다른 프로세스가 끼어든 것처럼
        return text
    monkeypatch.setattr(report, "render_public", public_then_withdraw)
    r = report.render_all("2026-11-10", "am")
    assert "지어낸 제목 하나" not in index_text(desk) and json.loads(index_text(desk))["cards"] == []
    assert r["published"] == 0                              # 반환값도 색인과 같은 시점


def test_build_site_checks_report_file_path(tmp_path, capsys):
    # 3: 색인의 file 경로를 그대로 대조한다 — 같은 이름이 다른 폴더에만 있으면 실패
    idx = json.loads(json.dumps(INDEX))
    idx["reports"][1]["file"] = "daily/missing/2026-11-10_am.md"
    root = make_site(tmp_path, idx, REPORTS)
    assert load_build_site().main(root) == 1
    assert "daily/missing/2026-11-10_am.md" in capsys.readouterr().err


def test_build_site_refuses_flat_name_collision(tmp_path, capsys):
    # 3: 평평하게 복사하면 덮어쓰게 되는 같은 이름은 실패
    root = make_site(tmp_path, INDEX, REPORTS)
    extra = root / "daily" / "2026" / "spare" / "2026-11-10_am.md"
    extra.parent.mkdir(parents=True)
    extra.write_text("# 지어낸 겹침\n", encoding="utf-8")
    assert load_build_site().main(root) == 1
    assert "2026-11-10_am.md" in capsys.readouterr().err
    assert not (root / "docs" / "daily").exists()             # 쓰기 전에 멈춘다


@pytest.mark.parametrize("patch", [
    lambda i: i["reports"][0].update(published=2),                                   # 발행 > 카드 수(4 중 2 인데 색인 카드 1)
    lambda i: i["reports"][0].update(published=5),                                   # 발행 > 카드
    lambda i: i["reports"][0].update(published=-1),
    lambda i: i["cards"].append(dict(i["cards"][1])) or i["reports"][1].update(published=3),   # card_id 중복
    lambda i: i["reports"].append(dict(i["reports"][1])),                            # 회차 보고서 중복
    lambda i: i["reports"].pop(0),                                                   # 카드는 있는데 회차 보고서 없음
])
def test_build_site_rejects_count_mismatch_and_duplicates(tmp_path, patch):
    # 4: 건수 모순과 중복
    idx = json.loads(json.dumps(INDEX))
    patch(idx)
    root = make_site(tmp_path, idx, REPORTS)
    assert load_build_site().main(root) == 1


# ── 세 번째 검토 반례: 렌더 도중 승인 ─────────────────────────────────
def test_render_rewrites_report_when_approved_midway(desk, monkeypatch):
    # 본문을 쓴 직후 다른 프로세스가 승인하면 보고서부터 다시 써서 자리표와 색인을 맞춘다
    C.human_verify([f"{CID}-c{i}" for i in (1, 2, 3)], "tester")
    report.render_all("2026-11-10", "am")
    real_public, calls = report.render_public, []

    def public_then_approve(date, slot):
        text = real_public(date, slot)
        if not calls:
            C.approve_publish(CID, "tester")                # 다른 프로세스가 끼어든 것처럼(한 번만)
        calls.append(1)
        return text
    monkeypatch.setattr(report, "render_public", public_then_approve)
    r = report.render_all("2026-11-10", "am")
    pub = (desk / "daily" / "2026" / "11" / "2026-11-10_am.md").read_text(encoding="utf-8")
    assert len(calls) == 2 and '<a id="am-01"></a>' in pub and "지어낸 제목 하나" in pub
    assert [c["card_id"] for c in json.loads(index_text(desk))["cards"]] == [CID] and r["published"] == 1
    assert load_build_site().main(desk) == 0                 # 임시 폴더의 사이트 검사도 통과


def test_render_gives_up_after_three_mismatches(desk, monkeypatch):
    # 렌더할 때마다 승인·철회가 뒤집히면 3번 뒤 예외 — 색인은 저장하지 않는다
    C.human_verify([f"{CID}-c{i}" for i in (1, 2, 3)], "tester")
    report.render_all("2026-11-10", "am")
    before = index_text(desk)
    real_public = report.render_public

    def flip(date, slot):
        text = real_public(date, slot)
        if C.publishable(C.load_card(CID), C.claims_for(CID)):
            C.withdraw(CID, "tester", "지어낸 뒤집기")
        else:
            C.approve_publish(CID, "tester")
        return text
    monkeypatch.setattr(report, "render_public", flip)
    with pytest.raises(RuntimeError, match="3번"):
        report.render_all("2026-11-10", "am")
    assert index_text(desk) == before


# ── 승인 전 회차의 발행본(2026-11-13 운영 변경) ─────────────────────────────
def test_unapproved_slot_page_is_removed_and_site_builds(desk):
    """예전에 올라간 승인 전 회차 쪽은 다음 렌더 때 지워지고 색인에서도 빠진다 — 사이트 생성 검사도 통과한다."""
    legacy = desk / "daily" / "2026" / "11" / "2026-11-10_am.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("# 지어낸 예전 발행본\n\n| `2026-11-10-am-01` | 지어낸 분야 |\n", encoding="utf-8")
    r = report.render_all("2026-11-10", "am")
    assert not legacy.exists() and r["public_page"] is False
    assert json.loads(index_text(desk))["reports"] == []
    assert pathlib.Path(r["paths"]["private"]).exists() and pathlib.Path(r["paths"]["sheet"]).exists()   # 비공개 문서는 그대로 쓴다
    assert load_build_site().main(desk) == 0


def test_withdrawn_only_slot_keeps_page(desk):
    approve()
    C.withdraw(CID, "tester", "지어낸 철회 사유")
    r = report.render_all("2026-11-10", "am")
    page = pathlib.Path(r["paths"]["public"])
    assert r["public_page"] is True and page.exists() and "## 철회" in page.read_text(encoding="utf-8")
    assert report.keeps_public_page(C.cards_for("2026-11-10", "am"))


def test_changed_after_approval_stops_without_removing_page(desk):
    """승인 뒤 내용이 바뀐 회차는 렌더가 검사에서 멈추고 발행본을 지우지 않는다."""
    approve()
    page = pathlib.Path(report.render_all("2026-11-10", "am")["paths"]["public"])
    before = page.read_text(encoding="utf-8")
    card = C.load_card(CID)
    card["titles"] = ["승인 뒤에 바꾼 지어낸 제목"]
    C.save_yaml(C.card_path(CID), card)
    with pytest.raises(ValueError):
        report.render_all("2026-11-10", "am")
    assert page.exists() and page.read_text(encoding="utf-8") == before


def test_public_page_hides_topic_of_unapproved_cards(desk):
    pub = report.render_public("2026-11-10", "am")               # 함수는 늘 글을 돌려준다(쓸지는 render_all 이 정한다)
    card = C.load_card(CID)
    assert CID in pub and "승인 대기" in pub
    assert "지어낸 제목 하나" not in pub and card.get("topic", "없는 분야") not in pub and card["why_today"]["trigger_type"] not in pub
