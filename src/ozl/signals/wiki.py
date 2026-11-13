"""위키백과(한국어) 일별 조회 상위 수집기 자리(§1-1 · 계획 5-1). 1판은 **꺼져 있다**.

켜지는 조건(둘 다): 출처 대장의 `wikipedia_pageviews_ko` collect 가 허용이고, 설정에 연락처가 있다
(위키미디어 API 는 요청의 User-Agent 에 연락처를 적으라고 한다). 연락처는 환경 변수 OZL_WIKI_CONTACT 로 준다.
켜지지 않으면 요청 함수를 부르지 않는다. 이 모듈은 점수에 아직 쓰이지 않는다(w = 없음).
"""
from __future__ import annotations

import os

SOURCE_ID = "wikipedia_pageviews_ko"
CONTACT = os.environ.get("OZL_WIKI_CONTACT", "").strip()
API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/ko.wikipedia/all-access/{y}/{m}/{d}"


def _ledger_ok() -> bool:
    from ozl.research import ledger
    return ledger.allowed(SOURCE_ID, "collect")


def enabled() -> bool:
    return bool(CONTACT) and _ledger_ok()


def off_reason() -> str:
    from ozl.research import ledger
    parts = [] if _ledger_ok() else [f"대장 {ledger.verdict(SOURCE_ID, 'collect')}"]
    if not CONTACT:
        parts.append("연락처 미정")
    return "수집 없음(" + " · ".join(parts) + ")" if parts else "수집 없음(1판은 점수에 쓰지 않음)"


def top_articles(day: str, http_get=None) -> list[dict] | None:
    """그날 상위 문서 [{article, rank}]. 꺼져 있으면 요청하지 않고 None. http_get(url, headers) -> dict 는 시험에서 바꿔 끼운다."""
    if not enabled():
        return None
    from ozl.research import ledger
    ledger.require(SOURCE_ID, "collect")
    if http_get is None:
        raise RuntimeError("1판에는 실제 요청 함수를 두지 않는다 — 켜는 작업에서 붙인다")
    y, m, d = day.split("-")
    data = http_get(API.format(y=y, m=m, d=d), {"User-Agent": f"OZL-engine/1 ({CONTACT})"})
    arts = ((data or {}).get("items") or [{}])[0].get("articles") or []
    return [{"article": a["article"], "rank": int(a["rank"])} for a in arts if ":" not in str(a.get("article", ""))]
