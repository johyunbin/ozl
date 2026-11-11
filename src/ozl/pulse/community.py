"""국내 커뮤니티 인기글 목록과 실시간 검색어 — 회차(하루 2회)에만 받는다. 매시 실행에는 넣지 않는다.

    python -m ozl.pulse run --community   # 피드 수집에 더해 아래 소스를 한 번씩 받는다

받는 것은 목록의 제목·링크·추천/조회/댓글 수·게시 시각뿐이다. 글 본문·댓글·이미지는 받지 않는다
(뽐뿌 RSS 는 본문 앞부분을 실어 보내지만 버린다). 소스당 회차마다 요청 1회, 다시 시도하지 않는다.
실패는 상태 표에 남기고 다음 소스로 넘어간다. 커뮤니티 글은 T5 단서다 — 사실 근거로 쓰지 않는다.

약관·robots 확인(2026-11-11, 사이트를 직접 열어 읽음)은 SOURCES 의 terms 칸과 README 「커뮤니티 수집」 표에 있다.
금지로 읽힌 소스는 enabled=False 로 두고 파서도 두지 않는다.

민감 소재(정치 게시판 포함)는 거르지 않는다. 정치 게시판 글에는 politics=True 를 달아 표시만 한다.
"""
from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

import requests

from ..research import collect

KST = collect.KST

SOURCES: list[dict] = [
    {"id": "signal_realtime", "source": "signal", "outlet": "시그널 실시간검색어", "url": "https://api.signal.bz/news/realtime",
     "parser": "signal", "section": "실시간 검색어", "enabled": True,
     "terms": "불명 — 이용약관에 자동 수집 조항 없음. 제13조(회원의 의무)가 서비스의 영리 목적 무단 이용을 막는다. robots.txt 전체 허용. "
              "공개 문서화된 API 는 아니다(사이트 화면이 부르는 주소). 비영리·비공개 신호로만 쓴다."},
    {"id": "clien_park", "source": "clien", "outlet": "클리앙 모두의공원", "url": "https://www.clien.net/service/board/park?&od=T31",
     "parser": None, "section": "모두의공원 추천순", "enabled": False,
     "terms": "금지 — 이용약관 제13조③이 서비스로 얻은 정보를 권리자 동의 없이 수집·복제·배포하는 것을 막는다. "
              "robots.txt 가 ClaudeBot·anthropic-ai 를 막고, 모든 수집기에 쿼리 주소(/*?*)와 /service/recommend 를 막는다."},
    {"id": "bobae_best", "source": "bobaedream", "outlet": "보배드림 베스트", "url": "https://www.bobaedream.co.kr/list?code=best",
     "parser": "bobae", "section": "베스트글", "enabled": True,
     "terms": "불명 — 이용약관에 자동 수집 조항 없음. 제11조③(회원의 의무)이 서비스로 얻은 정보를 회사 사전 승낙 없이 복제·사용·제공하는 "
              "것을 막는다(영리 여부 구분 없음). robots.txt 전체 허용(Amazonbot 만 차단). 제목은 비공개 신호 계산에만 쓰고 밖으로 내보내지 않는다."},
    {"id": "ppomppu_free", "source": "ppomppu", "outlet": "뽐뿌 자유게시판", "url": "https://www.ppomppu.co.kr/rss.php?id=freeboard",
     "parser": "ppomppu", "section": "자유게시판", "enabled": True,
     "terms": "허용(공식 RSS) — 사이트가 RSS 를 내놓고 있다. 이용약관에 자동 수집 조항 없음. 제13조②가 사전 승낙 없는 영리 목적 이용과 "
              "제3자 제공을 막는다. robots.txt 는 /rss.php 를 막지 않는다."},
    {"id": "ppomppu_issue", "source": "ppomppu", "outlet": "뽐뿌 정치자유게시판", "url": "https://www.ppomppu.co.kr/rss.php?id=issue",
     "parser": "ppomppu", "section": "정치자유게시판", "politics": True, "enabled": True,
     "terms": "ppomppu_free 와 같음. 게시판 이름은 issue 지만 실제로는 정치 게시판이다(표시만 하고 거르지 않는다)."},
]


def _item(src: dict, title: str, url: str, published: datetime | None, now: datetime, **counts) -> dict:
    """collect.fetch_feed 항목과 같은 꼴 + source·수치 칸."""
    it = {"title": collect.clean(title, 200), "url": url, "summary": "",
          "published": (published or now).isoformat(), "undated": published is None,
          "feed": src["id"], "outlet": src["outlet"], "tier": "T5", "lang": "ko", "kind": "community",
          "section": src.get("section", ""), "source": src["source"]}
    if src.get("politics"):
        it["politics"] = True
    it.update({k: v for k, v in counts.items() if v is not None})
    return it


def _int(s: str | None) -> int | None:
    if s is None:
        return None
    d = re.sub(r"[^\d]", "", s)
    return int(d) if d else None


# ── 시그널: 실시간 검색어 top10 ─────────────────────────────────────────
def parse_signal(raw: bytes, src: dict, now: datetime) -> list[dict]:
    """top10 키워드만 받는다 → 검색 신호용(kind=trend). 'articles'(포털 인기 기사)는 키워드와 짝이 아니라서 받지 않는다."""
    d = json.loads(raw)
    out = []
    for k in d.get("top10") or []:
        kw = collect.clean(str(k.get("keyword", "")), 100)
        if not kw:
            continue
        it = _item(src, kw, "", None, now, rank=_int(str(k.get("rank", ""))))
        it["kind"] = "trend"   # 급상승어처럼 묶지 않고 검색 신호에만 쓴다(snapshot 이 kind=trend 를 묶음에서 뺀다)
        it["undated"] = False  # 받은 시각이 곧 그 순위의 시각이다
        out.append(it)
    return out


# ── 보배드림 베스트: HTML 목록 ─────────────────────────────────────────
ROW = re.compile(r'<tr\s+itemscope[^>]*>(.*?)</tr>', re.S)
SUBJ = re.compile(r'<a[^>]*class="bsubject"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)


def _td(row: str, cls: str) -> str | None:
    m = re.search(rf'<td[^>]*class="{cls}"[^>]*>(.*?)</td>', row, re.S)
    return re.sub(r"<[^>]+>", " ", m.group(1)).strip() if m else None


def bobae_time(s: str | None, now: datetime) -> datetime | None:
    """'21:57'(오늘) · '11/10'·'26.11.10'(그날 0시) → UTC. 앞날이 되면 하루 앞으로 돌린다. 읽지 못하면 None."""
    if not s:
        return None
    s = s.strip()
    kst = now.astimezone(KST)
    if m := re.fullmatch(r"(\d{1,2}):(\d{2})", s):
        try:
            t = kst.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
        except ValueError:   # '24:10' 같은 값 — 행 하나 때문에 목록 전체를 잃지 않게
            return None
        if t > kst + timedelta(minutes=10):
            t -= timedelta(days=1)
        return t.astimezone(timezone.utc)
    if m := re.fullmatch(r"(?:(\d{2,4})[./-])?(\d{1,2})[./-](\d{1,2})", s):
        y = int(m[1]) if m[1] else kst.year
        y = y + 2000 if y < 100 else y
        try:
            t = datetime(y, int(m[2]), int(m[3]), tzinfo=KST)
            if t > kst:
                t = t.replace(year=t.year - 1)   # 2월 29일이면 ValueError → None
        except ValueError:
            return None
        return t.astimezone(timezone.utc)
    return None


def parse_bobae(raw: bytes, src: dict, now: datetime) -> list[dict]:
    text = raw.decode("utf-8", "replace")
    out = []
    for row in ROW.findall(text):
        m = SUBJ.search(row)
        if not m:
            continue
        title = re.sub(r"<[^>]+>", "", m.group(2))   # 문자 참조는 collect.clean 이 한 번만 푼다
        href = html.unescape(m.group(1))
        url = href if href.startswith("http") else "https://www.bobaedream.co.kr" + href
        c = re.search(r'class="totreply"[^>]*>\s*([\d,]+)', row)
        out.append(_item(src, title, url, bobae_time(_td(row, "date"), now), now,
                         votes=_int(_td(row, "recomm")), views=_int(_td(row, "count")),
                         comments=_int(c.group(1)) if c else None))
    return [i for i in out if i["title"]]


# ── 뽐뿌: 공식 RSS ─────────────────────────────────────────────────────
HITS = re.compile(r"\[\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\]")


def parse_ppomppu(raw: bytes, src: dict, now: datetime) -> list[dict]:
    """<hits> [댓글|조회|추천|비추천] — 칸 순서는 화면 목록과 견준 추정이다. description(본문 앞부분)은 읽지 않는다."""
    head = raw[:200].decode("ascii", "replace")
    if (enc := re.search(r'encoding=["\']([\w-]+)', head)) and enc[1].lower().replace("_", "-") not in ("utf-8", "utf8"):
        # ElementTree 는 EUC-KR 같은 멀티바이트 선언을 읽지 못한다 — 직접 풀고 선언을 뗀다
        raw = re.sub(r"^\s*<\?xml[^>]*\?>", "", raw.decode(enc[1], "replace")).encode("utf-8")
    root = ET.fromstring(raw)
    out = []
    for e in root.iter("item"):
        title = (e.findtext("title") or "").strip()
        if not title:
            continue
        ts = None
        try:
            ts = parsedate_to_datetime(e.findtext("pubDate") or "")
            ts = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            ts = None
        if ts and ts > now + timedelta(minutes=10):
            ts = None
        h = HITS.search(e.findtext("hits") or "")
        out.append(_item(src, title, (e.findtext("link") or "").strip().replace("http://", "https://", 1), ts, now,
                         comments=int(h[1]) if h else None, views=int(h[2]) if h else None, votes=int(h[3]) if h else None))
    return out


PARSERS: dict[str, Callable[[bytes, dict, datetime], list[dict]]] = {
    "signal": parse_signal, "bobae": parse_bobae, "ppomppu": parse_ppomppu}


def fetch_source(src: dict, now: datetime, get: Callable = requests.get) -> tuple[list[dict], dict]:
    """소스 하나 → (항목, 상태). 요청은 정확히 한 번(꺼진 소스는 0번). 예외는 상태에 남기고 삼킨다."""
    st = {"id": src["id"], "outlet": src["outlet"], "http": None, "entries": 0, "error": None,
          "enabled": src.get("enabled", True), "kind": "community"}
    if not st["enabled"]:
        st["error"] = "꺼짐(약관)"
        return [], st
    try:
        r = get(src["url"], headers={"User-Agent": collect.UA["User-Agent"], "Accept": "*/*"}, timeout=collect.TIMEOUT)
        st["http"] = r.status_code
        if r.status_code != 200:
            st["error"] = f"HTTP {r.status_code}"
            return [], st
        items = PARSERS[src["parser"]](r.content, src, now)
    except Exception as e:  # noqa: BLE001 — 한 소스가 깨져도 회차는 계속한다
        st["error"] = type(e).__name__
        return [], st
    st["entries"] = len(items)
    if not items:
        st["error"] = "항목 0개(목록 구조가 바뀌었을 수 있음)"
    return items, st


def fetch_all(now: datetime, get: Callable = requests.get, sources: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """차례대로(동시 요청 없음) 한 번씩."""
    items, statuses = [], []
    for src in sources or SOURCES:
        got, st = fetch_source(src, now, get)
        items += got
        statuses.append(st)
    return items, statuses
