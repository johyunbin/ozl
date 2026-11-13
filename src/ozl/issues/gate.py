"""공개 판정 한 진입점 — 옛 카드는 cards.publishable 을 그대로 부르고(발행 5장의 값 불변), 이슈의 판·화제 목록·복원판은 새 판정으로 묶는다."""
from __future__ import annotations

from ozl.research import cards

from . import revisions, units


def is_public(unit: str, ref) -> bool:
    """unit 'card': ref = 카드 번호 · 'issue': ref = (이슈 번호, 판 | None) 또는 이슈 번호 · 'day' | 'restored': ref = 날짜."""
    if unit == "card":
        if not cards.card_path(ref).is_file():
            return False
        return cards.publishable(cards.load_card(ref), cards.claims_for(ref))
    if unit == "issue":
        iid, rev = (ref, None) if isinstance(ref, str) else tuple(ref)
        if rev is None:
            return revisions.latest_public(iid) is not None
        return revisions.revision_publishable(iid, rev)[0]
    if unit in ("day", "restored"):
        return units.unit_publishable(unit, ref)[0]
    raise ValueError(f"알 수 없는 단위다: {unit}")
