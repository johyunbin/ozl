"""묶기 단계 한 번(A 덩어리): 수집 DB 읽기 → 같은 주소 합치기 → 낱말 분석 → 전재 묶기 → 하루치 그룹 → 이슈 잇기 → 저장.

점수(score·state·board)는 이 결과를 받아 계산한다(engine.py). 날짜 확정(§7-2), 번호 발급 단계(§7-3)를 여기서 지킨다.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta

from ozl.signals import FORMULA_VER, RULES_VER, cluster, config, dedup, overrides, source, store, text
from ozl.signals.link import Linker


def versions(dict_ver: str, ov_sha: str) -> dict:
    from ozl.research import collect, ledger
    led = getattr(ledger, "LEDGER", None) or getattr(ledger, "PATH", None)
    return {"rules": RULES_VER, "formula": FORMULA_VER, "dict": dict_ver,
            "ledger": config.file_hash(pathlib.Path(led)) if led else "모름",
            "feeds": config.file_hash(collect.HERE / "feeds.yaml"), "overrides": ov_sha}


def analyze_all(con, arts: list[dict], dict_ver: str) -> list[dict]:
    """저장된 분석(같은 사전 판·같은 제목)을 다시 쓰고, 없으면 분석해 붙인다. 새로 분석한 기사 목록을 돌려준다."""
    cached = store.get_analysis(con, [a["key"] for a in arts], dict_ver)
    fresh = []
    for a in arts:
        c = cached.get(a["key"])
        if c is None or c["title"] != a["title"]:
            c = text.analyze(a["title"], a["lang"])
            fresh.append(a)
        a.update({"entities": c["entities"], "terms": c["terms"], "person": c["person"], "indirect": c["indirect"]})
        a["norm_title"] = text.norm_title(a["title"])
        a["norm_summary"] = text.norm_summary(a.get("summary", ""))
    return fresh


def _prev_members(con, registry) -> dict[str, set]:
    cid = store.last_step_calc(con)
    out: dict[str, set] = {}
    if cid is None:
        return out
    for g in store.calc_groups(con, cid):
        iid = g["issue_id"]
        if iid and iid in registry and registry[iid].first_day == g["day"]:
            out.setdefault(iid, set()).update(g["units"], g["copies"])
    return out


def step(con, pulse_db: pathlib.Path | str, asof: datetime, mode: str = "step",
         overrides_path: pathlib.Path | str | None = None, trend_hit=None, decided_at: datetime | None = None,
         trend_rule=None) -> dict:
    """기준 시각 asof 의 묶기 한 번. mode='step' 은 번호를 발급하고 저장한다. 'view' 는 저장하지 않는다(임시 번호).
    trend_rule(group, 검색어 목록, 기사 사전) -> bool 을 주면 이번에 읽은 검색어로 '계열 1곳 + 급상승' 새 이슈 조건을 본다."""
    asof = asof.astimezone(config.UTC)
    asof_iso = config.iso_utc(asof)
    ov = overrides.load(overrides_path, asof)
    dv = config.dict_version()
    vers = versions(dv, ov.sha)
    calc_id = store.new_calc(con, asof_iso, config.iso_utc(decided_at or datetime.now(config.UTC)), mode, vers)

    items, excluded = source.load_items(pulse_db, asof)
    arts = dedup.merge_same_url(items)
    fresh = analyze_all(con, arts, dv)

    fdays = store.final_days(con)
    lo = config.day_add(config.kst_day(asof), -(config.DORMANT_KEEP_DAYS + config.LINK_WINDOW_DAYS))
    frozen = store.final_groups(con, since_day=lo)
    frozen_units = {k: g for g in frozen for k in g["units"]}
    frozen_keys = set(frozen_units) | {k for g in frozen for k in g["copies"]}
    finalize = sorted(d for d in {a["day"] for a in arts} - fdays if config.t_final(d) <= asof)
    work, late = [], 0
    for a in arts:
        d = a["day"]
        counted = a["kind"] in ("news", "official")
        if d in fdays:
            late += int(counted and a["key"] not in frozen_keys)
            continue
        if d in finalize and a["received_at"] > config.t_final(d):
            late += int(counted)
            continue
        work.append(a)

    start = min([a["day"] for a in work] or [config.kst_day(asof)])
    prior = [a for a in arts if a["key"] in frozen_units and a["kind"] == "news"
             and a["event_at"] >= config.t_final(config.day_add(start, -3)) - timedelta(hours=36)]
    copies = dedup.copy_groups([a for a in work if a["kind"] == "news"], prior)
    late_copies = {k: {**v, "issue_id": frozen_units[v["rep"]]["issue_id"]}
                   for k, v in copies.items() if v["rep"] in frozen_units}
    units = [a for a in work if a["kind"] in ("news", "official") and a["key"] not in copies]

    if trend_hit is None and trend_rule is not None:
        tr = [a for a in work if a["kind"] == "trend"]
        amap = {a["key"]: a for a in arts}
        trend_hit = (lambda g: trend_rule(g, tr, amap)) if tr else None
    registry = store.load_registry(con, asof_iso)
    linker = Linker(registry, ov, asof_iso, mode, calc_id, _prev_members(con, registry), trend_hit)
    for g in frozen:
        if g["issue_id"]:
            linker.add_group(g["issue_id"], g)

    by_day: dict[str, list[dict]] = {}
    for u in units:
        by_day.setdefault(u["day"], []).append(u)
    rep_of = {k: v["rep"] for k, v in copies.items()}
    groups = []
    for d in sorted(by_day):
        gs = cluster.group_day(by_day[d], d)
        where = {k: g for g in gs for k in g["units"]}
        for ck, rk in sorted(rep_of.items()):
            if rk in where:
                where[rk]["copies"].append(ck)
        linker.run_day(d, gs)
        groups += gs
    linker.finish(set(by_day))

    if mode == "step":
        have = store.aliases(con)
        for m in ov.merges:
            for old in m["absorb"]:
                if have.get(old) != m["keep"]:
                    linker.aliases.append({"old_id": old, "new_id": m["keep"], "at": m["at"], "reason": m["reason"] or "사람 판단(합침)"})
                    linker.history.append({"issue_id": m["keep"], "at": m["at"], "kind": "합침", "detail": {"absorb": old}})
                    linker.history.append({"issue_id": old, "at": m["at"], "kind": "합침", "detail": {"into": m["keep"]}})
        store.put_articles(con, fresh, dv)
        store.save_copies(con, copies)
        store.save_registry(con, linker.registry)
        store.add_history(con, linker.history)
        store.add_aliases(con, linker.aliases)
        fin = set(finalize)
        store.save_groups(con, calc_id, [g for g in groups if g["day"] not in fin], final=False)
        store.save_groups(con, calc_id, [g for g in groups if g["day"] in fin], final=True)
        for d in finalize:
            store.mark_final(con, d, calc_id, asof_iso)
    store.finish_calc(con, calc_id, excluded, late, len(items))
    con.commit()
    return {"calc_id": calc_id, "asof": asof_iso, "mode": mode, "groups": groups, "frozen": frozen,
            "copies": copies, "late_copies": late_copies, "articles": {a["key"]: a for a in arts},
            "trends": [a for a in work if a["kind"] == "trend"], "registry": linker.registry,
            "merge_hints": linker.merge_hints, "excluded": excluded, "late": late, "finalized": finalize,
            "overrides": ov, "versions": vers}


def run_times(pulse_db, frm: str | None = None, to: str | None = None, until: datetime | None = None) -> list[datetime]:
    """실행 기록의 수집 시각(단계). frm·to 는 KST 날짜(to 포함)."""
    runs = source.runs_until(pulse_db, until or datetime.now(config.UTC))
    out = []
    for r in runs:
        d = config.kst_day(r["at_dt"])
        if (frm is None or d >= frm) and (to is None or d <= to):
            out.append(r["at_dt"])
    return out


def issue_of(result: dict) -> dict[str, str | None]:
    """기사 키 → 이슈 번호(확정 그룹·이번 그룹·확정 대표를 따르는 사본 포함)."""
    out: dict[str, str | None] = {}
    for g in [*result["frozen"], *result["groups"]]:
        for k in [*g["units"], *g["copies"]]:
            out[k] = g["issue_id"]
    for k, v in result["late_copies"].items():
        out[k] = v["issue_id"]
    return out
