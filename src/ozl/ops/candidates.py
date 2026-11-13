"""후보 목록 — 재료 읽기(`load_source` 한 함수), 한 줄 모양, 화면 목록 섞기(설계 4절).

재료는 화제 엔진의 `private/pulse/out/board.json`(schema ozl.board/1)이다. 두 구역(새로 뜬 것, 이어지는 것)은
엔진이 정한 줄 그대로 맨 위에 두고, 나머지 후보는 한국어 이슈를 점수순으로, 영문 이슈는 접어서 맨 아래에 둔다.
board.json 이 없거나 꼴이 맞지 않으면 옛 수집기의 `now.json` 으로 돌아가고, 그 사실을 화면에 한 줄로 적는다.
값이 재료에 없는 칸은 숫자를 지어내지 않고 "정리 전"으로 둔다.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

from ozl.pulse import serve as pulse_serve

from . import queue, store

TBD = "정리 전"
OPEN_ROWS = 12
KINDS_TOTAL = 4
SENS_WORD = {"GREEN": "없음", "YELLOW": "주의", "RED": "높음"}
BOARD_FILE = "board.json"
BOARD_SCHEMA = "ozl.board/1"
ENGINE_ID = re.compile(r"t[0-9]{8}-[0-9]{3,4}")        # 화제 엔진의 이슈 번호(t20261114-003)
ZONES = (("new", "새로 뜬 것"), ("ongoing", "이어지는 것"))
LINKS_SHOWN = 2
# 점수가 사실 여부와 무관하다는 문장(옛 재료의 문장을 그대로 쓴다).
FACT_NOTE = "검증 전 신호다. 점수는 순위용이고 사실 여부와 무관하다."


@dataclass
class Candidate:
    key: str
    kind: str                     # topic | search | keyword
    title: str
    score: str = TBD
    state: str = TBD
    days: str = TBD
    new_line: str = TBD
    outlets: str = TBD
    kinds: str = TBD
    claims: str = TBD
    sensitive: str = TBD
    syuka: str = TBD
    first_seen: str | None = None
    raw_ref: dict = field(default_factory=dict)   # topic_id 나 keyword — 대기열에 넣을 대상
    search_words: list[str] = field(default_factory=list)
    # 아래는 화제 엔진 재료(board.json)에서만 채운다. 옛 재료와 옛 snapshot 에서는 기본값이다.
    source: str = "now"                           # now | board
    lang: str = ""
    category: str = ""
    sens_level: str = ""                          # GREEN | YELLOW | RED | ""
    sens_reason: str = ""
    indirect: str = ""                            # 간접 포착 표시 문구
    links: list[dict] = field(default_factory=list)
    zone: str | None = None                       # new | ongoing | None
    score_raw: float | None = None


@dataclass
class SourceResult:
    generated_at: str | None
    note: str | None
    candidates: list[Candidate]
    error: str | None = None
    unlinked: list[Candidate] = field(default_factory=list)   # 주제로 묶이지 않은 검색어
    feeds_failed: int = 0
    kind: str = "now"                             # now | board
    fallback: str | None = None                   # board.json 을 못 써 now.json 으로 돌아온 까닭(화면 한 줄)
    asof: str | None = None
    base_day: str | None = None
    base_day_partial: bool = False
    missing: list[str] = field(default_factory=list)
    zones: dict = field(default_factory=dict)     # {"new": {"rows": [...], "empty_reason": …, "capped": [...]}, …}
    skipped: int = 0                              # 번호 꼴이 아니어서 뺀 후보 수(보기 전용 계산의 임시 번호 등)


def norm_title(s: str) -> str:
    return re.sub(r"[^\w가-힣]+", "", s or "").lower()


def search_key(lang: str, title: str) -> str:
    return "q:" + hashlib.sha256(((lang or "") + (title or "")).encode("utf-8")).hexdigest()[:12]


def keyword_key(text: str) -> str:
    return "k:" + hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:8]


def sens_text(s: dict | None) -> str:
    if not isinstance(s, dict) or s.get("level") not in SENS_WORD:
        return TBD
    word = SENS_WORD[s["level"]]
    reasons = ", ".join(str(r) for r in (s.get("reasons") or []) if r)
    return f"{word}: {reasons}" if reasons and s["level"] != "GREEN" else word


def _latest_item(items: list) -> str:
    items = [i for i in items or [] if isinstance(i, dict) and i.get("title")]
    if not items:
        return TBD
    it = max(items, key=lambda i: str(i.get("ts") or ""))
    outlet = it.get("outlet")
    return f"가장 최근 보도: {it['title']}" + (f", {outlet}" if outlet else "")


def _topic(t: dict) -> Candidate:
    score = t.get("score")
    on = t.get("on") or []
    n_out = t.get("n_outlets")
    return Candidate(
        key=f"t:{int(t['topic_id'])}", kind="topic", title=str(t.get("title") or ""),
        score=f"{float(score):.2f}" if isinstance(score, (int, float)) else TBD,
        new_line=_latest_item(t.get("items")),
        outlets=f"매체 {n_out}곳" if isinstance(n_out, int) else TBD,
        kinds=f"종류 {len(on)}/{KINDS_TOTAL}",
        sensitive=sens_text(t.get("sensitivity")),
        first_seen=t.get("first_seen"),
        raw_ref={"topic_id": int(t["topic_id"]), "keyword": None})


def _search(s: dict) -> Candidate:
    title = str(s.get("title") or "")
    return Candidate(key=search_key(s.get("lang", ""), title), kind="search", title=title,
                     sensitive=sens_text(s.get("sensitivity")), new_line=TBD,
                     raw_ref={"topic_id": None, "keyword": title})


def _board_sens(s) -> tuple[str, str, str]:
    """(level, 까닭, 화면 글). 모르는 꼴은 정리 전."""
    if not isinstance(s, dict) or s.get("level") not in SENS_WORD:
        return "", "", TBD
    lv = s["level"]
    reason = str(s.get("reason") or "").strip()
    word = SENS_WORD[lv]
    return lv, reason, (f"{word}: {reason}" if reason and lv != "GREEN" else word)


def _safe_links(links) -> list[dict]:
    out = []
    for x in links or []:
        if not isinstance(x, dict):
            continue
        url = str(x.get("url") or "")
        if not re.match(r"https?://", url):                  # 화면에 거는 주소는 http(s) 만
            continue
        out.append({"title": str(x.get("title") or url), "url": url, "outlet": str(x.get("outlet") or "")})
    return out


def _day_word(day) -> str:
    try:
        d = datetime.fromisoformat(str(day))
        return f"{d.month}월 {d.day}일"
    except ValueError:
        return str(day or "")


def _day_counts(c: dict, partial: bool, base_day) -> tuple[str, str]:
    """(매체 계열 글, 출처 종류 글). 진행 중인 날(오늘)이면 어제 확정 전 값을 함께 보인다: '오늘 0곳, 어제 5곳'."""
    n_out = c.get("outlets_n")
    kinds, kinds_ok = c.get("kinds") or [], c.get("kinds_ok") or []
    prev = c.get("prev_day") if isinstance(c.get("prev_day"), dict) else None
    if not isinstance(n_out, int):
        outlets = TBD
    elif partial:
        outlets = f"매체 계열 오늘 {n_out}곳"
        if prev and isinstance(prev.get("outlets_n"), int):
            outlets += f", 어제 {prev['outlets_n']}곳"
    else:
        outlets = f"{_day_word(base_day)} 매체 계열 {n_out}곳"
    if not kinds_ok:
        kinds_t = TBD
    elif partial:
        kinds_t = f"출처 종류 오늘 {len(kinds)}/{len(kinds_ok)}"
        if prev and prev.get("kinds_ok"):
            kinds_t += f", 어제 {len(prev.get('kinds') or [])}/{len(prev['kinds_ok'])}"
    else:
        kinds_t = f"{_day_word(base_day)} 출처 종류 {len(kinds)}/{len(kinds_ok)}"
    return outlets, kinds_t


def _board_cand(c: dict, partial: bool = False, base_day=None) -> Candidate:
    iid = c["issue_id"]
    score = c.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float, type(None))):
        raise TypeError("score")
    raw = c.get("score_raw")
    lv, reason, stext = _board_sens(c.get("sensitivity"))
    ind = c.get("indirect")
    ind_text = str(ind.get("label") or "간접 포착") if isinstance(ind, dict) else ""
    outlets, kinds = _day_counts(c, partial, base_day)
    return Candidate(
        key=f"t:{iid}", kind="topic", title=str(c.get("title") or ""),
        score=str(int(score)) if isinstance(score, (int, float)) else "없음",   # 엔진이 사사오입한 값
        state=str(c.get("state") or "없음"),
        days=str(c.get("status_line") or TBD),
        new_line=str(c.get("new_thing") or ""),
        outlets=outlets, kinds=kinds,
        sensitive=stext, first_seen=c.get("first_day"),
        raw_ref={"topic_id": iid, "keyword": None},
        source="board", lang=str(c.get("lang") or ""), category=str(c.get("category") or ""),
        sens_level=lv, sens_reason=reason, indirect=ind_text, links=_safe_links(c.get("links"))[:LINKS_SHOWN],
        zone=c.get("zone") if c.get("zone") in ("new", "ongoing") else None,
        score_raw=float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None)


def load_board(out_dir: pathlib.Path) -> SourceResult:
    """board.json 을 읽는다. 없거나 꼴이 틀리면 error 에 까닭(화면 한 줄)을 담아 돌려준다."""
    p = out_dir / BOARD_FILE
    if not p.exists():
        return SourceResult(None, None, [], error="화제 엔진 결과(board.json)가 없다")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return SourceResult(None, None, [], error="화제 엔진 결과(board.json)를 읽지 못했다")
    try:
        if not isinstance(d, dict) or d.get("schema") != BOARD_SCHEMA:
            raise ValueError("schema")
        raw = d["candidates"]
        zones = d["zones"]
        if not isinstance(raw, list) or not isinstance(zones, dict):
            raise TypeError("candidates")
        cands, skipped = [], 0
        for c in raw:
            if not isinstance(c, dict) or not ENGINE_ID.fullmatch(str(c.get("issue_id") or "")):
                skipped += 1
                continue
            cands.append(_board_cand(c, bool(d.get("base_day_partial")), d.get("base_day")))
        zs = {}
        for z, _ in ZONES:
            zd = zones.get(z) or {}
            rows = zd.get("rows") or []
            if not isinstance(zd, dict) or not isinstance(rows, list):
                raise TypeError("zones")
            zs[z] = {"rows": [str(r) for r in rows], "empty_reason": zd.get("empty_reason"),
                     "capped": [x for x in zd.get("capped") or [] if isinstance(x, dict)]}
        unlinked = []
        for s in d.get("searches_unmatched") or []:
            if isinstance(s, dict) and s.get("keyword"):
                kw = str(s["keyword"])
                unlinked.append(Candidate(key=search_key("ko", kw), kind="search", title=kw, new_line="",
                                          raw_ref={"topic_id": None, "keyword": kw}, source="board"))
        missing = [str(m) for m in d.get("missing") or []]
    except (KeyError, TypeError, ValueError, AttributeError):
        return SourceResult(None, None, [], error="화제 엔진 결과(board.json)의 꼴이 맞지 않는다")
    return SourceResult(d.get("asof"), FACT_NOTE, cands, None, unlinked, 0, kind="board", asof=d.get("asof"),
                        base_day=d.get("base_day"), base_day_partial=bool(d.get("base_day_partial")),
                        missing=missing, zones=zs, skipped=skipped)


def load_now(out_dir: pathlib.Path) -> SourceResult:
    """옛 수집기의 now.json."""
    try:
        d = pulse_serve.read_now(out_dir)
    except (OSError, ValueError) as e:
        return SourceResult(None, None, [], error=type(e).__name__)
    if d is None:
        return SourceResult(None, None, [], error="없음")
    try:
        cands = [_topic(t) for t in d.get("topics") or [] if isinstance(t, dict) and "topic_id" in t]
        by_id = {c.raw_ref["topic_id"]: c for c in cands}
        unlinked = []
        for s in d.get("searches") or []:
            if not isinstance(s, dict) or not s.get("title"):
                continue
            if s.get("topic_id") in by_id:
                by_id[s["topic_id"]].search_words.append(str(s["title"]))
            else:
                unlinked.append(_search(s))
    except (KeyError, TypeError, ValueError) as e:
        return SourceResult(None, None, [], error=type(e).__name__)
    ff = d.get("feeds_failed")
    nff = len(ff) if isinstance(ff, list) else (ff if isinstance(ff, int) else 0)
    cands.sort(key=lambda c: -float(c.score) if c.score != TBD else 0.0)
    return SourceResult(d.get("generated_at"), d.get("note"), cands, None, unlinked, nff)


def load_source(now: datetime, out_dir: pathlib.Path) -> SourceResult:
    """재료를 읽는 유일한 함수. board.json 이 먼저, 못 쓰면 now.json(그 까닭을 fallback 에)."""
    b = load_board(out_dir)
    if b.error is None:
        return b
    old = load_now(out_dir)
    old.fallback = f"{b.error}. 옛 수집 목록(now.json)을 보인다."
    return old


# ---------- 운영 상태 파일 ----------

EMPTY = {"schema": 1, "items": []}


def load_state() -> dict[str, dict]:
    return {n: store.read_json(store.ops_file(f"{n}.json"), EMPTY) for n in ("discarded", "later", "keywords")}


def today(now: datetime) -> str:
    return store.now_kst(now).date().isoformat()


def tomorrow(now: datetime) -> str:
    return (store.now_kst(now).date() + timedelta(days=1)).isoformat()


def snapshot_of(c: Candidate) -> dict:
    return asdict(c)


def from_snapshot(d: dict) -> Candidate:
    known = {k: d[k] for k in Candidate.__dataclass_fields__ if k in d}
    return Candidate(**known)


def keyword_candidate(item: dict) -> Candidate:
    return Candidate(key=item["key"], kind="keyword", title=item["text"], new_line="직접 넣은 것",
                     raw_ref={"topic_id": None, "keyword": item["text"]})


def find(key: str, now: datetime, out_dir: pathlib.Path, src: SourceResult | None = None,
         state: dict | None = None) -> Candidate | None:
    """key 로 후보를 다시 찾는다: 지금 재료 → 내일 볼 것의 snapshot → 직접 넣은 키워드."""
    src = src or load_source(now, out_dir)
    for c in [*src.candidates, *src.unlinked]:
        if c.key == key:
            return c
    state = state or load_state()
    for it in state["later"]["items"]:
        if it.get("key") == key and isinstance(it.get("snapshot"), dict):
            return from_snapshot(it["snapshot"])
    for it in state["keywords"]["items"]:
        if it.get("key") == key:
            return keyword_candidate(it)
    return None


@dataclass
class Row:
    section: str          # 오늘 다시 볼 것 | 직접 넣은 것 | 수집 후보
    cand: Candidate
    stale: bool = False   # 재료에서 사라져 어제 본 값
    queued: dict | None = None


@dataclass
class PickView:
    src: SourceResult
    open_rows: list[Row]
    folded: list[Row]
    unlinked: list[Row]
    discarded: list[dict]
    queue_items: list[dict]
    zones: list[tuple[str, list[Row], dict]] = field(default_factory=list)   # (구역 이름, 줄, 구역 정보)
    english: list[Row] = field(default_factory=list)                         # 영문 이슈(접어 둔다)

    def n_candidates(self) -> int:
        return (sum(len(r) for _, r, _ in self.zones) + len(self.open_rows) + len(self.folded) + len(self.english)
                + len(self.unlinked))


def _rest_order(c: Candidate) -> tuple:
    """나머지 후보: 점수(반올림 전 값) 높은 순, 같으면 번호순. 점수 없음은 뒤로."""
    return (c.score_raw is None, -(c.score_raw or 0.0), c.key)


def build_view(now: datetime, out_dir: pathlib.Path) -> PickView:
    src = load_source(now, out_dir)
    st = load_state()
    q = queue.load()
    day = today(now)
    gone_keys = {i.get("key") for i in st["discarded"]["items"]}
    gone_titles = {i.get("norm_title") for i in st["discarded"]["items"] if i.get("norm_title")}

    def dropped(c: Candidate) -> bool:
        return c.key in gone_keys or (norm_title(c.title) and norm_title(c.title) in gone_titles)

    def queued(c: Candidate) -> dict | None:
        return queue.active_for_key(q, c.key)

    live = {c.key: c for c in [*src.candidates, *src.unlinked]}
    rows: list[Row] = []
    later_keys = set()
    for it in st["later"]["items"]:
        later_keys.add(it.get("key"))
        if str(it.get("show_from", "")) > day:
            continue
        c = live.get(it["key"])
        stale = c is None
        c = c or from_snapshot(it.get("snapshot") or {"key": it["key"], "kind": "topic", "title": it.get("title", "")})
        if not dropped(c):
            rows.append(Row("오늘 다시 볼 것", c, stale, queued(c)))
    for it in st["keywords"]["items"]:
        c = keyword_candidate(it)
        if not dropped(c) and c.key not in later_keys:
            rows.append(Row("직접 넣은 것", c, False, queued(c)))

    def shown(c: Candidate) -> bool:
        return c.key not in later_keys and not dropped(c)

    zones: list[tuple[str, list[Row], dict]] = []
    english: list[Row] = []
    if src.kind == "board":
        by_id = {c.raw_ref["topic_id"]: c for c in src.candidates}
        in_zone = set()
        for z, name in ZONES:
            info = src.zones.get(z) or {"rows": [], "empty_reason": None, "capped": []}
            zr = []
            for iid in info["rows"]:                 # 엔진이 정한 줄과 차례 그대로
                c = by_id.get(iid)
                if c is None:
                    continue
                in_zone.add(c.key)
                if shown(c):
                    zr.append(Row(name, c, False, queued(c)))
            zones.append((name, zr, info))
        rest = sorted((c for c in src.candidates if c.key not in in_zone and shown(c)), key=_rest_order)
        rows += [Row("그 밖의 후보", c, False, queued(c)) for c in rest if c.lang != "en"]
        english = [Row("영문 이슈", c, False, queued(c)) for c in rest if c.lang == "en"]
    else:
        rows += [Row("수집 후보", c, False, queued(c)) for c in src.candidates if shown(c)]
    unl = [Row("검색어", c, False, queued(c)) for c in src.unlinked if shown(c)]
    items = sorted(q["items"], key=lambda j: j.get("pressed_at") or "", reverse=True)
    return PickView(src, rows[:OPEN_ROWS], rows[OPEN_ROWS:], unl, list(st["discarded"]["items"]), items,
                    zones, english)
