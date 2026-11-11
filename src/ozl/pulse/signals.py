"""주제 하나에 대한 신호 네 가지 — 각 0~1, 그리고 사람이 읽을 근거 문장.

    search     검색 급상승(구글 트렌드 KR/US 급상승어가 주제 낱말에 들어 있나, 대략 검색량)
    volume     보도량(서로 다른 매체 수 + 지난 1시간 기사 수를 그 전 5시간 평균과 견준 속도)
    community  유튜브 인기 급상승·커뮤니티(HN) — 유튜브는 API 키가 있을 때만 켠다(youtube_key)
    official   기관 원문(중앙은행·통계 기관 피드)이 묶음에 있거나, 오늘 발표 일정과 낱말이 겹치나

판단은 전부 결정적 규칙이다(모델 호출 없음). 숫자 기준을 바꾸면 tests/test_pulse.py 도 같이 고친다.
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime, timedelta

import requests
import yaml

from ..research import collect

NEWS_KINDS = ("news", "official")
YT_URL = "https://www.googleapis.com/youtube/v3/videos"


def parse_traffic(s: str) -> int | None:
    """구글 트렌드 'approx_traffic' 표기 → 정수. '500+', '2,000+', '1만+', '20K+', '1M+'. 읽지 못하면 None."""
    if not s:
        return None
    t = s.replace(",", "").replace("+", "").strip().upper()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(만|천|K|M)?", t)
    if not m:
        return None
    mult = {"만": 10_000, "천": 1_000, "K": 1_000, "M": 1_000_000}.get(m.group(2) or "", 1)
    return int(float(m.group(1)) * mult)


def traffic_value(n: int | None) -> float:
    """100 → 0.4, 1천 → 0.55, 1만 → 0.7, 10만 → 0.85, 100만 이상 → 1. 검색량을 모르면 0.4."""
    if not n:
        return 0.4
    return round(max(0.4, min(1.0, 0.4 + 0.15 * math.log10(n / 100))), 2)


def trend_matches(tok: set[str], lang: str, trends: list[dict]) -> list[dict]:
    """같은 주제로 보는 조건 — 급상승어 낱말이 주제 낱말에 통째로 들어 있어야 하고(항상), 딸린 기사 제목이 있으면
    급상승어 자신을 뺀 나머지 낱말이 주제와 겹쳐야 한다(낱말 두 개 이상 급상승어는 1개, 낱말 하나짜리는 2개).
    딸린 기사가 없으면 낱말 두 개 이상 급상승어만 붙인다 — 한 낱말("의약품")은 무관한 기사에도 흔히 들어 있다."""
    out = []
    for t in trends:
        if t["lang"] != lang:
            continue
        kw = collect.toks(t["title"], lang)
        if not kw or not kw <= tok:
            continue
        rest = collect.toks(t.get("trend_news", ""), lang) - kw
        need = 1 if len(kw) >= 2 else 2
        if (rest and len(rest & tok) >= need) or (not rest and len(kw) >= 2):
            out.append(t)
    return out


def search_signal(tok: set[str], lang: str, trends: list[dict]) -> tuple[float, list[str], list[dict]]:
    hits = trend_matches(tok, lang, trends)
    if not hits:
        return 0.0, [], []
    best = max(hits, key=lambda t: parse_traffic(t.get("traffic", "")) or 0)
    v = traffic_value(parse_traffic(best.get("traffic", "")))
    region = "KR" if lang == "ko" else "US"
    return v, [f"검색 급상승 {region} '{best['title']}'" + (f" {best['traffic']}" if best.get("traffic") else "")], hits


def volume_signal(items: list[dict], now: datetime) -> tuple[float, list[str], dict]:
    """items 는 한 묶음의 항목(ts = 발행 시각, 없으면 처음 본 시각). 속도는 기사 수가 아니라 매체 수로 잰다 —
    한 매체가 1보·2보·종합을 연달아 내도 한 곳이다."""
    news = [i for i in items if i["kind"] in NEWS_KINDS]
    outlets = {i["outlet"] for i in news}
    h1 = (now - timedelta(hours=1)).isoformat()
    recent = {i["outlet"] for i in news if i["ts"] >= h1}
    earlier = {i["outlet"] for i in news if i["ts"] < h1}
    base = len(earlier) / 5.0   # 창이 6시간이므로 앞 5시간의 시간당 매체 수
    if not outlets:
        return 0.0, [], {"n_outlets": 0, "recent_1h": 0, "base_per_h": 0.0}
    # 매체 한 곳뿐이면 속도 몫은 주지 않는다 — 기사 한 건이 "급증"으로 켜지지 않게(매체 몫 1/8×0.5 만 남아 ON 미만)
    accel = min(1.0, len(recent) / max(3.0, 3 * base)) if len(outlets) >= 2 else 0.0   # 바닥 3: 새 매체 한 곳으로는 켜지지 않는다
    v = 0.5 * min(1.0, len(outlets) / 8) + 0.5 * accel
    reasons = [f"매체 {len(outlets)}곳"]
    if recent:
        reasons.append(f"지난 1시간 매체 {len(recent)}곳(그 전 시간당 {base:.1f}곳)")
    return round(v, 2), reasons, {"n_outlets": len(outlets), "recent_1h": len(recent), "base_per_h": round(base, 2)}


def youtube_key() -> str:
    """환경 변수 OZL_YOUTUBE_API_KEY → YOUTUBE_API_KEY → 저장소 루트 .env(gitignore)의 YOUTUBE_API_KEY 순. 값은 어디에도 적지 않는다."""
    for name in ("OZL_YOUTUBE_API_KEY", "YOUTUBE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    env = collect.ROOT / ".env"
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "YOUTUBE_API_KEY":
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def fetch_youtube(now: datetime) -> tuple[list[dict], dict]:
    """유튜브 인기 동영상(KR) 제목. 키가 없으면 꺼짐 상태만 돌려준다(0점이 아니라 '측정 안 함')."""
    key = youtube_key()
    st = {"id": "youtube_popular_kr", "outlet": "YouTube 인기(KR)", "http": None, "entries": 0, "error": None, "enabled": bool(key)}
    if not key:
        st["error"] = "꺼짐(유튜브 API 키 없음)"
        return [], st
    try:
        r = requests.get(YT_URL, params={"part": "snippet", "chart": "mostPopular", "regionCode": "KR", "maxResults": 50, "key": key},
                         timeout=collect.TIMEOUT)
        st["http"] = r.status_code
        if r.status_code != 200:
            st["error"] = f"HTTP {r.status_code}"
            return [], st
        vids = [{"title": collect.clean(v["snippet"]["title"], 200), "channel": v["snippet"].get("channelTitle", ""),
                 "url": f"https://www.youtube.com/watch?v={v['id']}", "lang": "ko"} for v in r.json().get("items", [])]
    except Exception as e:  # noqa: BLE001 — 키가 오류 메시지에 섞이지 않게 예외 이름만 남긴다
        st["error"] = type(e).__name__
        return [], st
    st["entries"] = len(vids)
    return vids, st


def community_signal(items: list[dict], tok: set[str], lang: str, youtube: list[dict]) -> tuple[float, list[str]]:
    v, reasons = 0.0, []
    comm = [i for i in items if i["kind"] == "community"]
    if comm:
        v = 0.6
        reasons.append(f"커뮤니티 {comm[0]['outlet']}")
    yt = [y for y in youtube if y["lang"] == lang and len(collect.toks(y["title"], lang) & tok) >= 2]
    if yt:
        v = 1.0
        reasons.append(f"유튜브 인기 {len(yt)}편")
    return v, reasons


def load_calendar() -> list[dict]:
    return yaml.safe_load((collect.HERE / "calendar.yaml").read_text(encoding="utf-8")).get("events", [])


CAL_GENERIC = {"미국", "한국", "중국", "일본", "유럽", "영국", "독일", "us", "u.s.", "결정", "발표", "회의", "결과", "추정", "지수",
               "동향", "올해", "마지막", "동반", "경제전망", "통화정책", "금리", "2차", "the", "of"}


def calendar_hits(tok: set[str], lang: str, events: list[dict], now: datetime) -> list[dict]:
    """오늘(KST) 발표 일정 가운데 제목 낱말이 주제와 겹치는 것. 시각이 적힌 일정은 발표 2시간 전부터 6시간 뒤까지만."""
    kst_now = now.astimezone(collect.KST)
    today = kst_now.strftime("%Y-%m-%d")
    out = []
    for e in events:
        when = str(e.get("kst", ""))
        if len(when) > 10:
            t = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=collect.KST)
            if not (t - timedelta(hours=2) <= kst_now <= t + timedelta(hours=6)):
                continue
        elif e.get("date") != today:
            continue
        ident = (collect.toks(e["title"], "ko") | collect.toks(e["title"], "en")) - CAL_GENERIC
        if ident & tok:   # 나라 이름·"발표" 같은 일반어 하나로는 잇지 않는다 — 지표 이름이 겹쳐야 한다
            out.append(e)
    return out


def official_signal(items: list[dict], tok: set[str], lang: str, events: list[dict], now: datetime) -> tuple[float, list[str]]:
    off = [i for i in items if i["kind"] == "official"]
    if off:   # 보도자료만 있고 언론이 받지 않았으면 아직 "뜨는 것"은 아니다 — ON 미만으로 두고, 따로 "기관 발표" 목록에 싣는다
        covered = any(i["kind"] == "news" for i in items)
        return (1.0 if covered else 0.2), [f"기관 원문 {off[0]['outlet']}" + ("" if covered else "(보도 없음)")]
    cal = calendar_hits(tok, lang, events, now)
    if cal:
        return 0.6, [f"발표 일정 {cal[0]['org']} {cal[0]['title']}"]
    return 0.0, []
