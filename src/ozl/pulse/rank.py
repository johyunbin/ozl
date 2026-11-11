"""종합 점수 — 신호 네 가지의 가중합에, 서로 다른 신호가 함께 뜰 때 보너스를 더한다.

가중치는 보도량 > 검색 > 기관 > 커뮤니티 순. 한 가지 신호만 강한 주제(검색어 하나, 커뮤니티 글 하나)는
여러 신호가 겹친 주제보다 아래에 오게 하는 것이 목적이다. 점수는 순위를 정하는 데만 쓴다 — 사실 여부와 무관하다.
"""
from __future__ import annotations

WEIGHTS = {"volume": 0.35, "search": 0.30, "official": 0.25, "community": 0.10}
ON = 0.3          # 이 값 이상이면 그 신호가 "켜졌다"고 센다
BONUS = 1.5       # 켜진 신호가 하나 늘 때마다(두 번째부터)
SINGLE_CAP = 1.5  # 매체 한 곳뿐인 묶음의 점수 상한(snapshot.score_clusters 가 적용)
LABELS = {"search": "검색", "volume": "보도", "community": "커뮤니티", "official": "기관"}


def combine(signals: dict[str, float]) -> tuple[float, list[str]]:
    """신호 → (점수, 켜진 신호 이름). 점수는 0~10 가중합 + 보너스."""
    base = 10 * sum(WEIGHTS[k] * signals.get(k, 0.0) for k in WEIGHTS)
    on = [k for k in WEIGHTS if signals.get(k, 0.0) >= ON]
    bonus = BONUS * (len(on) - 1) if len(on) >= 2 else 0.0
    return round(base + bonus, 2), on


def movement(rank: int, prev: int | None) -> str:
    """직전 실행 대비 순위 변동 표시."""
    if prev is None:
        return "신규"
    if prev == rank:
        return "-"
    return f"▲{prev - rank}" if prev > rank else f"▼{rank - prev}"
