"""수집 상태와 비중 나누기의 재료(§5-3). 수집 DB 의 실행 기록(runs)과 지금의 feeds.yaml·대장으로 종류별 상태를 정한다.

피드 f 가 실행 r 에서 성공 = f 가 켜져 있고 대장 collect·score_use 가 허용이며 r 의 error 가 비었고 feeds_failed 에 f 가 없다.
종류 k 가 실행 r 에서 성공 = 그 종류의 대상 피드 가운데 절반 이상이 성공(대상 피드가 0개면 꺼짐).
날짜 d 의 상태(end = min(asof, d 다음날 0시)): 실패 = [d 0시, end] 에 성공한 실행이 하나도 없음,
오래됨 = 그날 성공은 있었으나 마지막 성공이 end−6시간보다 이름(반나절만 받고 멈춘 날도 받은 값은 관측값으로 쓴다),
성공 = 그 밖. 비중 나누기는 '실패'일 때만 한다. 피드 성공 기록이 따로 없어 "실패 목록에 없음"을 성공으로 본다(§10).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from ozl.signals import config, score, source

KIND_OF_FEED = {"news": score.NEWS, "trend": score.SEARCH, "official": score.OFFICIAL}
SUCCESS, STALE, FAILED, OFF = "성공", "오래됨", "실패", "꺼짐"


def targets(allowed=None) -> dict[str, list[str]]:
    """종류 → 대상 피드 id(켜져 있고 대장 collect·score_use 허용). 위키는 1판에 수집이 없어 빈 목록."""
    if allowed is None:
        from ozl.research import ledger
        allowed = ledger.allowed
    out = {k: [] for k in score.KINDS}
    for fid, m in sorted(source.feeds_meta().items()):
        k = KIND_OF_FEED.get(m["kind"])
        if k and m["enabled"] and allowed(fid, "collect") and allowed(fid, "score_use"):
            out[k].append(fid)
    return out


def parse_runs(rows: list[dict]) -> list[dict]:
    """source.runs_until 의 행 → feeds_failed 를 {id: 오류} 로 푼 꼴."""
    out = []
    for r in rows:
        ff = r.get("feeds_failed")
        if isinstance(ff, str):
            try:
                ff = json.loads(ff or "[]")
            except ValueError:
                ff = []
        out.append({"at_dt": r["at_dt"], "error": r.get("error"), "feeds_failed": ff or []})
    return out


def _failed(run: dict) -> dict[str, str]:
    out = {}
    for f in run.get("feeds_failed") or []:
        if isinstance(f, dict):
            out[str(f.get("id"))] = str(f.get("error") or "")
        else:
            out[str(f)] = ""
    return out


def kind_ok(run: dict, feeds: list[str]) -> bool:
    if not feeds or run.get("error"):
        return False
    bad = _failed(run)
    return sum(1 for f in feeds if f not in bad) * 2 >= len(feeds)


def day_end(day: str, asof: datetime) -> datetime:
    nxt = datetime.fromisoformat(config.day_add(day, 1)).replace(tzinfo=config.KST).astimezone(config.UTC)
    return min(asof.astimezone(config.UTC), nxt)


def day_start(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=config.KST).astimezone(config.UTC)


def day_status(runs: list[dict], tg: dict[str, list[str]], day: str, asof: datetime) -> dict[str, dict]:
    """종류 → {status, last_ok(datetime|None)}. runs 는 at ≤ asof 인 실행만 들어와야 한다."""
    end, start = day_end(day, asof), day_start(day)
    out = {}
    for k in score.KINDS:
        feeds = tg.get(k) or []
        if not feeds:
            out[k] = {"status": OFF, "last_ok": None}
            continue
        oks = [r["at_dt"] for r in runs if start <= r["at_dt"] <= end and kind_ok(r, feeds)]
        last = max(oks) if oks else None
        if last is None:
            st = FAILED
        elif end - last > timedelta(hours=config.STALE_HOURS):
            st = STALE
        else:
            st = SUCCESS
        out[k] = {"status": st, "last_ok": last}
    return out


def ok_kinds(st: dict[str, dict]) -> set[str]:
    return {k for k, s in st.items() if s["status"] in (SUCCESS, STALE)}


def missing_labels(st: dict[str, dict]) -> list[str]:
    out = []
    for k in score.KINDS:
        s = st.get(k)
        if not s:
            continue
        name = "공공" if k == score.OFFICIAL else k
        if s["status"] == FAILED:
            out.append(f"{name}(실패)")
        elif s["status"] == STALE:
            hm = s["last_ok"].astimezone(config.KST).strftime("%H:%M")
            out.append(f"{name}(오래됨, 마지막 성공 {hm})")
    return out


def feed_table(runs: list[dict], tg: dict[str, list[str]]) -> list[dict]:
    """피드마다 마지막 성공 시각, 지금 이어지는 실패가 시작된 시각, 마지막 오류. runs 는 시각순."""
    out = []
    for k in score.KINDS:
        for f in tg.get(k) or []:
            last_ok = since = None
            err = ""
            for r in runs:
                bad = _failed(r)
                failed = bool(r.get("error")) or f in bad
                if failed:
                    if since is None:
                        since = r["at_dt"]
                    err = bad.get(f) or str(r.get("error") or "")
                else:
                    last_ok, since, err = r["at_dt"], None, ""
            out.append({"kind": k, "feed": f, "last_ok": last_ok, "fail_since": since, "error": err})
    return out


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(config.KST).isoformat() if d else None


def sources_block(runs: list[dict], tg: dict[str, list[str]], st: dict[str, dict], wiki_reason: str) -> list[dict]:
    """board.json 의 sources: 종류별 상태와 피드별 마지막 성공 시각(출처별 표)."""
    table = feed_table(runs, tg)
    last_run = runs[-1] if runs else None
    out = []
    for k in score.KINDS:
        s = st[k]
        if s["status"] == OFF:
            reason = wiki_reason if k == score.WIKI else "대상 피드 없음(꺼짐 또는 대장 허용 아님)"
            out.append({"kind": k, "status": OFF, "reason": reason})
            continue
        feeds = tg[k]
        bad = _failed(last_run) if last_run else {}
        n_ok = 0 if (last_run is None or last_run.get("error")) else sum(1 for f in feeds if f not in bad)
        rows = [t for t in table if t["kind"] == k]
        out.append({"kind": k, "status": s["status"], "last_ok": _iso(s["last_ok"]), "feeds_ok": n_ok,
                    "feeds_total": len(feeds),
                    "failed": [{"feed": t["feed"], "error": t["error"], "since": _iso(t["fail_since"])}
                               for t in rows if t["fail_since"]],
                    "feeds": [{"feed": t["feed"], "last_ok": _iso(t["last_ok"]), "fail_since": _iso(t["fail_since"])}
                              for t in rows]})
    return out


def basis(st: dict[str, dict]) -> str:
    on = [("공공 원문" if k == score.OFFICIAL else k) for k in score.KINDS if st[k]["status"] != OFF]
    off = [k for k in score.KINDS if st[k]["status"] == OFF]
    tail = " · " + ", ".join(f"{k} 수집 없음" for k in off) if off else ""
    return f"출처 {len(on)}종 기준({', '.join(on)}{tail})"
