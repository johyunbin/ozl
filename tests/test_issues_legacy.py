"""옛 자료(카드 29장과 그 기록) 회귀 시험 — 실제 private/desk 를 읽기만 한다. 자료가 없는 기기에서는 건너뛴다.
발행 5장의 공개 판정 값은 private/out/night_20261114/baseline_publishable.json 과 대조한다(내용은 읽지 않고 번호·지문·참거짓만)."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.issues import gate, links  # noqa: E402
from ozl.research import cards  # noqa: E402

BASELINE = ROOT / "private" / "out" / "night_20261114" / "baseline_publishable.json"
PUBLISHED = {"2026-11-10-am-01", "2026-11-10-am-02", "2026-11-10-am-03", "2026-11-10-am-05", "2026-11-10-am-06"}

need_private = pytest.mark.skipif(not links.available(), reason="옛 자료(private/desk)가 이 기기에 없다")


@need_private
def test_counts_explained():
    c = links.counts()
    assert c["claims_files"] == c["claims_read"] + c["parked"]          # 운영으로 늘어도 이 관계는 남는다
    assert c["cards"] >= 29 and c["published_cards"] >= 5


@need_private
def test_published_cards_unchanged():
    if not BASELINE.is_file():
        pytest.skip("기준 파일이 없다")
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    for cid in PUBLISHED:
        card, claims = cards.load_card(cid), cards.claims_for(cid)
        assert cards.publishable(card, claims) is True
        assert base[cid]["publishable"] is True and cards.content_digest(card, claims) == base[cid]["digest"]
    for cid, row in base.items():
        if cards.card_path(cid).is_file():
            assert cards.publishable(cards.load_card(cid), cards.claims_for(cid)) == row["publishable"], cid


@need_private
def test_links_no_missing():
    r = links.check()
    assert not r["skipped"] and r["missing"] == [] and r["errors"] == []


@need_private
def test_gate_matches_cards():
    for card in cards.all_cards():
        cid = card["card_id"]
        assert gate.is_public("card", cid) == cards.publishable(card, cards.claims_for(cid))
