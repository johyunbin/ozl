"""이슈 후보 — 커뮤니티 인기글·실시간 검색어·검색 급상승어를 서로 묶어 "지금 사람들이 이야기하는 것"을 고른다.

    python -m ozl.briefs candidates --slot pm [--hours 14] [--n 30]

Pulse 의 기사 묶음(`snapshot`)은 경제·국제 기사 위주라 커뮤니티 화제와 잘 이어지지 않는다(B2 실측 0건).
그래서 여기서는 화제 신호(시그널·구글 트렌드 KR·커뮤니티 글)를 먼저 묶어 이슈를 만들고, 기사는 이슈마다 나중에 붙인다.
민감 소재는 거르지 않는다(표시만). 커뮤니티 글은 단서일 뿐 근거가 아니다.

산출(비공개): private/briefs/<날짜>/<회차>/candidates.json · candidates.md
"""
from __future__ import annotations

import json
import math
import pathlib
from datetime import datetime, timezone

from ..pulse import signals as psig
from ..pulse import community as pcommunity
from ..pulse import store
from ..research import collect, ledger, sensitive

BRIEFS = store.ROOT / "private" / "briefs"
NEWS_KINDS = ("news", "official")
# 기사 붙이기에서 식별어로 치지 않는 흔한 낱말 — 이것만 겹쳐서는 같은 사건이라 볼 수 없다
GENERIC = set("속보 단독 종합 오늘 어제 내일 올해 정부 한국 미국 중국 일본 국내 해외 시장 발표 공개 논란 의혹 사과 입장 "
              "실적 매출 영업이익 순이익 증가 감소 상승 하락 급등 급락 전년 대비 분기 1분기 2분기 3분기 4분기 상반기 하반기 "
              "최대 최고 최저 역대 사상 기록 가능 전망 예상 우려 확대 축소 추진 검토".split())


def toks(title: str) -> set[str]:
    return collect.toks(title, "ko")


def seeds_from(items: list[dict]) -> list[dict]:
    """창 안 항목 → 화제 씨앗. 시그널·구글 트렌드 KR 키워드와 커뮤니티 글(HN 제외)."""
    out = []
    for i in items:
        src = i.get("source") or ""
        if i["kind"] == "trend" and (src == "signal" or i["feed"] == "trends_kr"):
            kind = "signal" if src == "signal" else "trend"
        elif i["kind"] == "community" and i["lang"] == "ko" and src in ("bobaedream", "ppomppu", "clien"):
            kind = "post"
        else:
            continue
        t = toks(i["title"])   # 묶기에는 제목 낱말만 — 급상승어에 딸린 기사 제목의 흔한 낱말로 무관한 글이 묶인다
        if not t:
            continue
        out.append({**i, "seed_kind": kind, "tok": t, "kw": t})
    return out


def priority(s: dict) -> tuple:
    """묶기의 기준(anchor)이 될 순서 — 시그널 순위 → 트렌드 검색량 → 반응이 큰 글."""
    if s["seed_kind"] == "signal":
        return (0, s.get("rank") or 99)
    if s["seed_kind"] == "trend":
        return (1, -(psig.parse_traffic(s.get("traffic", "")) or 0))
    return (2, -post_heat(s))


def linked(a: dict, b: dict) -> bool:
    """두 씨앗을 같은 이슈로 볼까. 낱말 2개 이상 겹치거나, 낱말 2개 이상짜리 키워드가 상대 제목에 통째로 들어 있을 때.
    낱말 하나짜리 키워드("임신")는 무관한 글에도 흔해 그것만으로 잇지 않는다."""
    if len(a["tok"] & b["tok"]) >= 2:
        return True
    for x, y in ((a, b), (b, a)):
        if x["seed_kind"] in ("signal", "trend") and len(x["kw"]) >= 2 and x["kw"] <= y["tok"]:
            return True
    return False


def group(seeds: list[dict]) -> list[list[dict]]:
    """기준 씨앗 방식 + 과반 연결 — 씨앗은 기준(묶음의 첫 씨앗)과 이어지고, 이미 든 구성원의 과반과도 이어질 때만 그 묶음에 든다.
    두 화제를 다 언급한 글이 기준이 되면 양쪽 화제가 모두 기준과 이어지므로, 과반 조건이 다리 역할을 막는다."""
    groups: list[list[dict]] = []
    for s in sorted(seeds, key=priority):
        for g in groups:
            if linked(g[0], s) and sum(linked(m, s) for m in g) * 2 > len(g):
                g.append(s)
                break
        else:
            groups.append([s])
    return groups


def post_heat(p: dict) -> float:
    """커뮤니티 글 하나의 반응 — 조회(로그) + 추천 + 댓글. 상한을 두지 않는다(상한에 붙으면 인기글끼리 구분이 안 된다).
    조회 1만·추천 100·댓글 30 이 대략 1.0."""
    v, r, c = p.get("views") or 0, p.get("votes") or 0, p.get("comments") or 0
    return round(0.4 * math.log10(1 + v) / 4 + r / 300 + c / 300 + 0.16, 3)


def score(g: list[dict]) -> tuple[float, dict]:
    sig = [s for s in g if s["seed_kind"] == "signal"]
    tr = [s for s in g if s["seed_kind"] == "trend"]
    posts = [s for s in g if s["seed_kind"] == "post"]
    best_rank = min((s.get("rank") or 11 for s in sig), default=None)
    traffic = max((psig.parse_traffic(s.get("traffic", "")) or 0 for s in tr), default=0)
    sites = {p.get("source") for p in posts}
    parts = {
        "signal": round(max(0, 11 - best_rank) / 10 * 3, 2) if best_rank else 0.0,   # 11위 밖은 0(음수 금지)
        "trend": round(psig.traffic_value(traffic) * 2, 2) if tr else 0.0,
        "community": round(sum(post_heat(p) for p in posts) + 0.8 * max(0, len(sites) - 1), 2),
        "kinds": len({s["seed_kind"] for s in g}),
    }
    total = parts["signal"] + parts["trend"] + parts["community"] + 1.0 * (parts["kinds"] - 1)
    return round(total, 2), {**parts, "signal_rank": best_rank, "traffic": traffic or None, "sites": sorted(x for x in sites if x)}


def label(g: list[dict]) -> str:
    """이슈 이름 — 시그널 키워드 > 트렌드 키워드 > 반응이 가장 큰 글 제목."""
    for kind in ("signal", "trend"):
        ks = sorted((s for s in g if s["seed_kind"] == kind), key=lambda s: s.get("rank") or 99)
        if ks:
            return ks[0]["title"]
    return max(g, key=post_heat)["title"]


def issue_sensitivity(g: list[dict], hits: list[dict]) -> dict:
    """씨앗 제목과 붙은 기사 제목을 모두 보고, 정치 게시판 글이 있으면 그 사실도 이유에 넣는다(거르지 않고 표시만)."""
    res = sensitive.worst([sensitive.classify(s["title"]) for s in g] + [sensitive.classify(h["title"]) for h in hits])
    if any(s.get("politics") or s["feed"] == "ppomppu_issue" for s in g if s["seed_kind"] == "post"):
        res = {"level": "RED" if res["level"] == "RED" else "YELLOW", "reasons": res["reasons"] + ["정치 게시판 글 포함"]}
    return res


def news_match(nt: set[str], keywords: list[set[str]], post_toks: list[set[str]]) -> int:
    """기사 제목 낱말 nt 가 이슈와 이어지는 정도(0 = 무관).
    키워드(낱말 2개 이상)가 통째로 들어 있거나, 3글자 이상 한 낱말 키워드가 들어 있거나, 커뮤니티 글 제목과 3개 이상 겹칠 때.
    급상승어에 딸린 기사 제목의 낱말은 쓰지 않는다 — '3분기'·'영업이익' 같은 흔한 낱말로 무관한 기사가 붙는다."""
    best = 0
    for kw in keywords:
        if len(kw) >= 2 and kw <= nt and (kw - GENERIC):
            best = max(best, len(kw) + 1)
        elif len(kw) == 1 and len(next(iter(kw))) >= 3 and kw <= nt:
            best = max(best, 2)
    for pt in post_toks:
        common = pt & nt
        if len(common) >= 3 and len(common - GENERIC) >= 2:   # 흔한 표현만 겹쳐서는 붙이지 않는다
            best = max(best, len(common))
    return best


def news_for(g: list[dict], news: list[dict], limit: int = 8) -> list[dict]:
    """이슈와 이어지는 최근 기사 — 취재의 출발점. 같은 매체는 한 번만."""
    keywords = [s["kw"] for s in g if s["seed_kind"] in ("signal", "trend") and s["kw"]]
    post_toks = [s["tok"] for s in g if s["seed_kind"] == "post"]
    hits, seen = [], set()
    for n in sorted(news, key=lambda n: n["ts"], reverse=True):
        ov = news_match(toks(n["title"]), keywords, post_toks)
        if ov and n["outlet"] not in seen:
            seen.add(n["outlet"])
            hits.append({"title": n["title"], "url": n["url"], "outlet": n["outlet"], "tier": n["tier"], "ts": n["ts"], "overlap": ov})
    hits.sort(key=lambda h: (h["overlap"], h["ts"]), reverse=True)
    return hits[:limit]


def build(items: list[dict], top: int = 30) -> list[dict]:
    """창 안 항목(Pulse DB) → 점수순 이슈 후보. DB 와 무관한 순수 계산이라 테스트가 직접 부른다."""
    seeds = seeds_from(items)
    news = [i for i in items if i["kind"] in NEWS_KINDS and i["lang"] == "ko"]
    out = []
    for g in group(seeds):
        if len(g) == 1 and g[0]["seed_kind"] == "post" and post_heat(g[0]) < 0.6:
            continue   # 반응이 작은 글 하나짜리는 후보로 올리지 않는다(이슈가 아니라 잡담일 가능성이 크다)
        sc, parts = score(g)
        tok = set().union(*(s["tok"] for s in g))
        posts = sorted((s for s in g if s["seed_kind"] == "post"), key=post_heat, reverse=True)
        out.append({
            "label": label(g), "score": sc, "parts": parts,
            "keywords": [{"kind": s["seed_kind"], "title": s["title"], "rank": s.get("rank"), "traffic": s.get("traffic")}
                         for s in g if s["seed_kind"] != "post"],
            "posts": [{"site": p.get("source"), "outlet": p["outlet"], "title": p["title"], "url": p["url"],
                       "views": p.get("views"), "votes": p.get("votes"), "comments": p.get("comments"),
                       "politics": bool(p.get("politics")) or p["feed"] == "ppomppu_issue"} for p in posts[:8]],
            "news": news_for(g, news),
            "sensitivity": issue_sensitivity(g, news_for(g, news)),
            "tokens": sorted(tok)[:20],
        })
    out.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(out[:top], 1):
        c["rank"] = i
    return out[:top]


def digest(d: dict) -> str:
    lines = [f"# 이슈 후보 {d['date']} {d['slot']} — 생성 {d['generated_at']}", "",
             f"창 {d['window_hours']}시간 · 씨앗 {d['n_seeds']}개 → 후보 {len(d['candidates'])}개. 민감 소재는 거르지 않았다(표시만). 커뮤니티 글은 단서일 뿐 근거가 아니다.", ""]
    for c in d["candidates"]:
        p = c["parts"]
        bits = []
        if p["signal_rank"]:
            bits.append(f"시그널 {p['signal_rank']}위")
        if p["traffic"]:
            bits.append(f"검색 {p['traffic']:,}+")
        if c["posts"]:
            bits.append(f"커뮤니티 {len(c['posts'])}건({', '.join(p['sites']) or '-'})")
        bits.append(f"기사 {len(c['news'])}곳")
        sens = "" if c["sensitivity"]["level"] == "GREEN" else f" [{c['sensitivity']['level']}: {', '.join(c['sensitivity']['reasons'])}]"
        lines.append(f"## {c['rank']}. {c['label']} — {c['score']}{sens}")
        lines.append("- " + " · ".join(bits))
        for k in c["keywords"][:4]:
            lines.append(f"  - 키워드({k['kind']}) {k['title']}" + (f" {k['rank']}위" if k.get("rank") else "") + (f" {k['traffic']}" if k.get("traffic") else ""))
        for po in c["posts"][:4]:
            cnt = " · ".join(f"{n} {v:,}" for n, v in (("조회", po["views"]), ("추천", po["votes"]), ("댓글", po["comments"])) if v)
            lines.append(f"  - 글 [{po['outlet']}] {po['title']} ({cnt}){' · 정치게시판' if po['politics'] else ''} <{po['url']}>")
        for n in c["news"][:5]:
            lines.append(f"  - 기사 [{n['outlet']}] {n['title']} <{n['url']}>")
        lines.append("")
    return "\n".join(lines)


def run(slot: str, date: str | None = None, hours: float = 24.0, top: int = 30, now: datetime | None = None,
        db: pathlib.Path | None = None, out_root: pathlib.Path | None = None) -> pathlib.Path:
    now = now or datetime.now(timezone.utc)
    date = date or now.astimezone(collect.KST).strftime("%Y-%m-%d")
    con = store.connect(db)
    # 꺼 둔 소스, 그리고 출처 대장의 score_use 가 '허용'이 아닌 출처(대장에 없으면 불명)에서 전에 받아 둔 항목은 쓰지 않는다
    usable = ledger.scorable(pcommunity.off_feeds())
    items = [i for i in store.window_items(con, now, hours) if usable(i)]
    cands = build(items, top)
    out_dir = (out_root or BRIEFS) / date / slot
    out_dir.mkdir(parents=True, exist_ok=True)
    d = {"generated_at": now.astimezone(collect.KST).isoformat(), "date": date, "slot": slot, "window_hours": hours,
         "n_seeds": len(seeds_from(items)), "candidates": cands}
    (out_dir / "candidates.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "candidates.md").write_text(digest(d), encoding="utf-8")
    return out_dir / "candidates.md"
