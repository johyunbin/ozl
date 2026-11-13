#!/usr/bin/env python3
"""소재 후보 수집 — 피드를 받아 같은 사건끼리 묶고, 민감 표시·기존 커버리지·발표 일정을 붙여 요약본을 만든다.

    python -m ozl.research collect --slot am            # 최근 24시간
    python -m ozl.research collect --slot pm --hours 14

산출(비공개): private/desk/<날짜>_<회차>/candidates.json(전체) · candidates.md(사람·모델이 읽는 요약) ·
private/desk/latest_uploads.json(슈카월드 최신 업로드 — 커버리지 대조에 합쳐 쓴다).
피드가 죽어도 나머지는 계속 받고, 실패는 요약본 맨 위 표에 남긴다(조용히 빠지지 않게).
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import json
import pathlib
import re
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import yaml

from . import coverage, ledger, sensitive

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
DESK = ROOT / "private" / "desk"
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (compatible; feed-reader/1.0)",
      "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"}
TIMEOUT = 15
TIER_W = {"T1": 3.0, "T2": 2.5, "T3": 1.0, "T4": 0.5, "T5": 0.0}
EN_STOP = set("the and for with from that this has have was were will after over into amid says said new its his her their than more as at by in of on to a an is are be "
              "what why how who when where could would should may might about against between under during not but out off up down per vs via".split())


def load_config() -> dict:
    return yaml.safe_load((HERE / "feeds.yaml").read_text(encoding="utf-8"))


def clean(s: str, limit: int = 300) -> str:
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:limit]


def entry_time(e) -> datetime | None:
    t = e.get("published_parsed") or e.get("updated_parsed")
    return datetime(*t[:6], tzinfo=timezone.utc) if t else None


def fetch_feed(feed: dict, now: datetime) -> tuple[list[dict], dict]:
    """피드 하나 → (항목들, 상태). 예외는 삼키되 상태에 남긴다.
    출처 대장(ledger)의 collect 칸이 '허용'이 아니면(대장에 없으면 불명) 요청하지 않고 꺼짐으로 적는다 — 실패로 세지 않는다."""
    status = {"id": feed["id"], "outlet": feed["outlet"], "http": None, "entries": 0, "error": None}
    if not ledger.allowed(feed["id"], "collect"):
        return [], {**status, "error": ledger.off_reason(feed["id"], "collect"), "enabled": False}
    try:
        r = requests.get(feed["url"], headers=UA, timeout=TIMEOUT)
        status["http"] = r.status_code
        if r.status_code != 200:
            status["error"] = f"HTTP {r.status_code}"
            return [], status
        d = feedparser.parse(r.content)
    except Exception as e:  # noqa: BLE001
        status["error"] = type(e).__name__
        return [], status
    items = []
    for e in d.entries:
        title = clean(e.get("title", ""), 200)
        if not title:
            continue
        outlet = feed["outlet"]
        if feed["id"].startswith("gnews_"):  # "제목 - 매체" 꼴에서 매체 꼬리를 뗀다
            title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)
        ts = entry_time(e)
        if ts and ts > now + timedelta(minutes=10):
            ts = None   # 앞날 시각이 찍힌 항목은 시각을 믿지 않는다(발행 시각 없음으로 취급)
        items.append({"title": title, "url": e.get("link", ""), "summary": clean(e.get("summary", "")),
                      "published": (ts or now).isoformat(), "undated": ts is None,
                      "feed": feed["id"], "outlet": outlet, "tier": feed["tier"], "lang": feed["lang"],
                      "kind": feed["kind"], "section": feed.get("section", "")})
        if feed["kind"] == "trend":   # 구글 트렌드 피드의 대략 검색량("500+")과 딸린 기사 제목 하나(feedparser 는 마지막 것만 남긴다)
            items[-1]["traffic"] = clean(e.get("ht_approx_traffic", ""), 20)
            items[-1]["trend_news"] = clean(e.get("ht_news_item_title", ""), 200)
    status["entries"] = len(items)
    if not items:
        status["error"] = "항목 0개"
    return items, status


def toks(title: str, lang: str) -> set[str]:
    if lang == "ko":
        return coverage.tokens(title)
    return {w for w in re.findall(r"[a-z][a-z0-9'&.\-]{2,}", title.lower()) if w not in EN_STOP}


def cluster(items: list[dict]) -> list[dict]:
    """제목 낱말이 겹치는 항목을 한 사건으로 묶는다(같은 언어끼리만 · 탐욕). 기준: 겹침 3개 이상이고 짧은 쪽의 절반 이상."""
    clusters: list[dict] = []
    for it in sorted(items, key=lambda x: (TIER_W.get(x["tier"], 0), x["published"]), reverse=True):
        t = toks(it["title"], it["lang"])
        it["_tok"] = t
        best, best_ov = None, 0
        if len(t) >= 3:
            for c in clusters:
                if c["lang"] != it["lang"]:
                    continue
                ov = len(t & c["seed_tok"])   # 분자·분모 모두 첫 항목(seed) 기준 — 누적 합집합과 견주면 서로 무관한 기사가 사슬처럼 엮인다
                if ov >= 3 and ov / min(len(t), len(c["seed_tok"])) >= 0.5 and ov > best_ov:
                    best, best_ov = c, ov
        if best is None:
            clusters.append({"lang": it["lang"], "seed_tok": t, "tok": set(t), "items": [it]})
        else:
            best["items"].append(it)
            best["tok"] |= t
    return clusters


def score(c: dict, trend_tokens: set[str], now: datetime) -> float:
    """묶음 점수 — 서로 다른 매체 수가 뼈대, 기관 원문·급상승어 겹침·최신성이 가점. 커뮤니티·급상승만 있는 묶음은 0 근처."""
    outlets = {i["outlet"] for i in c["items"] if i["kind"] in ("news", "official")}
    s = float(len(outlets))
    s += max((TIER_W.get(i["tier"], 0) for i in c["items"]), default=0) * (1.0 if any(i["kind"] == "official" for i in c["items"]) else 0.3)
    if c["tok"] & trend_tokens:
        s += 1.0
    dated = [datetime.fromisoformat(i["published"]) for i in c["items"] if not i["undated"]]
    if dated:  # 발행 시각이 없는 피드는 수집 시각이 들어가 있어 최신성 가점을 주지 않는다
        age_h = (now - max(dated)).total_seconds() / 3600
        s += 1.0 if age_h <= 6 else 0.5 if age_h <= 12 else 0.0
    return round(s, 2)


def calendar_window(today: str, back: int = 1, ahead: int = 7) -> list[dict]:
    """발표 일정표에서 [오늘−back, 오늘+ahead] 구간. 확인한 지 35일 넘은 항목은 stale 표시."""
    cal = yaml.safe_load((HERE / "calendar.yaml").read_text(encoding="utf-8")).get("events", [])
    d0 = datetime.strptime(today, "%Y-%m-%d")
    lo, hi = (d0 - timedelta(days=back)).strftime("%Y-%m-%d"), (d0 + timedelta(days=ahead)).strftime("%Y-%m-%d")
    out = []
    for e in cal:
        if lo <= e["date"] <= hi:
            stale = (d0 - datetime.strptime(e["checked"], "%Y-%m-%d")).days > 35
            out.append({**e, "stale": stale})
    return sorted(out, key=lambda e: e["kst"])


def calendar_gap(today: str, ahead: int = 14) -> bool:
    """앞으로 ahead 일 안에 일정이 하나도 없으면 True — 일정표가 비어 가는 것을 '조용한 주'로 읽지 않게."""
    cal = yaml.safe_load((HERE / "calendar.yaml").read_text(encoding="utf-8")).get("events", [])
    hi = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=ahead)).strftime("%Y-%m-%d")
    return not any(today <= e["date"] <= hi for e in cal)


def fetch_uploads(cfg: dict, now: datetime) -> tuple[list[dict], list[dict]]:
    """채널 공개 피드로 최신 업로드(약 15편)를 받는다."""
    vids, stats = [], []
    for ch in cfg.get("channels", []):
        st = {"id": f"channel_{ch['id']}", "outlet": ch["name"], "http": None, "entries": 0, "error": None}
        if not ledger.allowed(ch["id"], "collect"):   # 대장의 id 는 채널 id 그대로(syukaworld)
            stats.append({**st, "error": ledger.off_reason(ch["id"], "collect"), "enabled": False})
            continue
        try:
            r = requests.get(ch["url"], headers=UA, timeout=TIMEOUT)
            st["http"] = r.status_code
            d = feedparser.parse(r.content) if r.status_code == 200 else None
            for e in (d.entries if d else []):
                ts = entry_time(e) or now
                vid = e.get("yt_videoid") or e.get("link", "").split("v=")[-1]
                vids.append({"video_id": vid, "title": clean(e.get("title", ""), 200), "date": ts.astimezone(KST).strftime("%Y-%m-%d"), "channel": ch["id"]})
            st["entries"] = len(vids)
            if not vids:
                st["error"] = f"HTTP {r.status_code}" if r.status_code != 200 else "항목 0개"
        except Exception as e:  # noqa: BLE001
            st["error"] = type(e).__name__
        stats.append(st)
    return vids, stats


def collect(slot: str, date: str | None = None, hours: float = 24.0, now: datetime | None = None) -> pathlib.Path:
    """수집해 요약본 경로를 돌려준다. 그 회차의 첫 수집이면 candidates.md, 재수집이면 recheck_HHMM.md."""
    now = now or datetime.now(timezone.utc)
    date = date or now.astimezone(KST).strftime("%Y-%m-%d")
    cfg = load_config()
    feeds = [f for f in cfg["feeds"] if f.get("enabled", True)]
    items, statuses = [], []
    with cf.ThreadPoolExecutor(8) as ex:
        for got, st in ex.map(lambda f: fetch_feed(f, now), feeds):
            items += got
            statuses.append(st)
    uploads, up_stats = fetch_uploads(cfg, now)
    statuses += up_stats
    DESK.mkdir(parents=True, exist_ok=True)
    if uploads:  # 실패한 날에 빈 목록으로 덮어쓰지 않는다
        (DESK / "latest_uploads.json").write_text(json.dumps({"fetched_at": now.isoformat(), "videos": uploads}, ensure_ascii=False, indent=1), encoding="utf-8")

    since = now - timedelta(hours=hours)
    usable = ledger.scorable()   # 대장의 score_use 가 '허용'이 아닌 출처에서 받은 항목은 점수와 요약본에 쓰지 않는다
    seen, fresh, unscored = set(), [], 0
    for it in items:
        if datetime.fromisoformat(it["published"]) < since:
            continue
        if not usable(it):
            unscored += 1
            continue
        key = (re.sub(r"\W+", "", it["title"].lower()), it["outlet"])   # 같은 매체의 같은 제목만 중복 — 다른 매체가 같은 제목을 달았으면 둘 다 남긴다
        if key in seen:
            continue
        seen.add(key)
        fresh.append(it)

    trends = [it for it in fresh if it["kind"] == "trend"]
    trend_tokens = set()
    for t in trends:
        trend_tokens |= toks(t["title"], t["lang"])
    body = [it for it in fresh if it["kind"] != "trend"]
    try:
        catalog = coverage.load_catalog()
        cov_error = None
    except Exception as e:  # noqa: BLE001 — 커버리지를 못 읽으면 '겹침 없음'이 아니라 '대조 실패'로 적는다
        catalog, cov_error = [], f"{type(e).__name__}: {e}"

    clusters = []
    for c in cluster(body):
        lead = c["items"][0]
        ctx = " ".join(i["title"] for i in c["items"])   # 해외·국내 표지는 묶음 전체에서 찾는다(다른 기사 제목에만 있는 경우)
        sens = sensitive.worst([sensitive.classify_item(i["title"], i["summary"], ctx) for i in c["items"]])   # 묶음의 모든 항목을 본다
        outlets = sorted({i["outlet"] for i in c["items"]})
        cov = coverage.recent_overlap(c["tok"], catalog, date) if (catalog and c["lang"] == "ko") else []
        clusters.append({
            "title": lead["title"], "lang": c["lang"], "score": score(c, trend_tokens, now),
            "outlets": outlets, "n_items": len(c["items"]), "top_tier": min(i["tier"] for i in c["items"]),
            "official": any(i["kind"] == "official" for i in c["items"]),
            "t5_only": all(i["kind"] == "community" for i in c["items"]),
            "paper_only": all(i["kind"] == "paper" for i in c["items"]),
            "sensitivity": sens, "coverage_recent": cov,
            "items": [{k: v for k, v in i.items() if not k.startswith("_")} for i in c["items"][:8]],
        })
    clusters.sort(key=lambda c: c["score"], reverse=True)

    out_dir = DESK / f"{date}_{slot}"
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {"generated_at": now.astimezone(KST).isoformat(), "date": date, "slot": slot, "window_hours": hours,
            "feeds": statuses, "n_items_raw": len(items), "n_items_window": len(fresh), "n_items_unscored": unscored, "n_clusters": len(clusters),
            "coverage_error": cov_error, "calendar": calendar_window(date), "calendar_gap": calendar_gap(date),
            "trends": [{"title": t["title"], "outlet": t["outlet"]} for t in trends],
            "uploads": uploads[:15], "clusters": clusters}
    # 같은 회차를 다시 수집하면 첫 수집본(보고서의 수집 통계가 가리키는 것)을 덮지 않고 재점검본으로 따로 둔다
    stem = "candidates" if not (out_dir / "candidates.json").exists() else f"recheck_{now.astimezone(KST).strftime('%H%M')}"
    (out_dir / f"{stem}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(digest(data), encoding="utf-8")
    return out_dir / f"{stem}.md"


def digest(d: dict, top: int = 70) -> str:
    """모델·사람이 읽는 요약본. 제외한 것(RED)도 건수와 사유를 남긴다."""
    L = [f"# 소재 후보 요약 — {d['date']} {d['slot']} (생성 {d['generated_at'][:16]})", ""]
    off = [f for f in d["feeds"] if f.get("enabled") is False]   # 대장이 막아 요청하지 않은 것 — 실패로 세지 않는다
    on = [f for f in d["feeds"] if f.get("enabled") is not False]
    ok = [f for f in on if not f["error"]]
    bad = [f for f in on if f["error"]]
    L += [f"- 피드 {len(ok)}/{len(on)}곳 응답 · 원시 항목 {d['n_items_raw']}건 → 최근 {d['window_hours']:g}시간 {d['n_items_window']}건 → 묶음 {d['n_clusters']}개"]
    if bad:
        L += ["- **받지 못한 피드**: " + ", ".join(f"{f['outlet']}({f['error']})" for f in bad)]
    if d.get("n_items_unscored"):
        L += [f"- 출처 대장에서 점수 사용(score_use)이 허용이 아닌 출처의 항목 {d['n_items_unscored']}건은 점수와 이 요약에서 뺐다"]
    if off:
        L += [f"- 출처 대장으로 끈 피드 {len(off)}곳: " + ", ".join(f"{f['outlet']}({f['error']})" for f in off)]
    if d.get("coverage_error"):
        L += [f"- **커버리지 대조 실패**: {d['coverage_error']} — 아래 '기존 영상' 칸이 비어 있어도 '다룬 적 없음'이 아니다"]
    L += ["", "## 발표 일정 (어제 ~ 7일 뒤)", ""]
    if d["calendar"]:
        L += ["| KST | 기관 | 발표 | 대상 | 근거 |", "|---|---|---|---|---|"]
        for e in d["calendar"]:
            flag = " ⚠️재확인 필요" if e["stale"] else ""
            L += [f"| {e['kst']} | {e['org']} | {e['title']} | {e.get('period', '')} | [{e['basis']}]({e['schedule_url']}){flag} |"]
    else:
        L += ["이 구간에 등록된 일정이 없다."]
    if d.get("calendar_gap"):
        L += ["", "⚠️ 앞으로 14일 안에 등록된 일정이 없다 — 조용한 주가 아니라 일정표(`calendar.yaml`)를 채울 때다."]

    clusters = d["clusters"]
    red = [c for c in clusters if c["sensitivity"]["level"] == "RED"]
    rest = [c for c in clusters if c["sensitivity"]["level"] != "RED"]

    def line(c: dict) -> str:
        cov = f" · 기존 영상: {c['coverage_recent'][0]['date']} 「{c['coverage_recent'][0]['title']}」" if c["coverage_recent"] else ""
        sens = "" if c["sensitivity"]["level"] == "GREEN" else f" · [YELLOW] {'; '.join(c['sensitivity']['reasons'][:1])}"
        url = c["items"][0]["url"]
        return f"- [{c['score']:.1f}] {c['title']} — {', '.join(c['outlets'][:5])}({c['n_items']}건 · {c['top_tier']}){sens}{cov} · <{url}>"

    L += ["", "## 기관 원문 (T1·T2 — 통계·정책 발표)", ""]
    off = [c for c in rest if c["official"]]
    L += [line(c) for c in off[:30]] or ["없음"]
    L += ["", f"## 언론 묶음 상위 {top} (서로 다른 매체 수 순)", ""]
    news = [c for c in rest if not c["official"] and not c["t5_only"] and not c.get("paper_only")]
    L += [line(c) for c in news[:top]] or ["없음"]
    L += ["", "## 워킹페이퍼 (T4 — 동료심사 전, 주장으로만)", ""]
    L += [line(c) for c in rest if c.get("paper_only")][:10] or ["없음"]
    L += ["", "## 급상승 검색어 (단서 전용 — 인용 금지)", ""]
    L += [", ".join(f"{t['title']}({t['outlet'][-2:]})" for t in d["trends"]) or "없음"]
    L += ["", "## 커뮤니티 단서 (T5 — 반드시 T1~T3 로 역추적)", ""]
    L += [line(c) for c in rest if c["t5_only"]][:15] or ["없음"]
    L += ["", "## 슈카월드 최근 업로드", ""]
    L += [f"- {v['date']} {v['title']}" for v in d["uploads"]] or ["받지 못함"]
    L += ["", f"## 민감 기준으로 뺀 묶음 (RED {len(red)}개)", ""]
    reasons: dict[str, int] = {}
    for c in red:
        for r in c["sensitivity"]["reasons"][:1]:
            k = r.split("(")[0]
            reasons[k] = reasons.get(k, 0) + 1
    L += [f"- {k}: {n}개" for k, n in sorted(reasons.items(), key=lambda x: -x[1])] or ["없음"]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="ozl.research collect")
    ap.add_argument("--slot", required=True, choices=["am", "pm", "wk"])
    ap.add_argument("--date")
    ap.add_argument("--hours", type=float, default=24.0)
    a = ap.parse_args(argv)
    t0 = time.time()
    out = collect(a.slot, a.date, a.hours)
    d = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    on = [f for f in d["feeds"] if f.get("enabled") is not False]
    bad = [f["outlet"] for f in on if f["error"]]
    print(f"{out} — 피드 {len(on) - len(bad)}/{len(on)}(대장으로 끈 {len(d['feeds']) - len(on)}곳 제외) · 묶음 {d['n_clusters']}개 · {time.time() - t0:.0f}초" + (f" · 실패: {', '.join(bad)}" if bad else ""))
    return 0
