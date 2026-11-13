"""이슈 하나의 점수 내역(§8-3). engine.db 에 남은 날짜별 줄(확정 행 + asof 까지 마지막 단계의 잠정 행)을 읽어 식에 숫자를 넣어 보인다."""
from __future__ import annotations

import json
import pathlib
import sqlite3

from ozl.signals import config, score, state, store


def _resolve(con, iid: str) -> str:
    seen = set()
    while iid not in seen:
        seen.add(iid)
        r = con.execute("SELECT new_id FROM issue_aliases WHERE old_id=?", (iid,)).fetchone()
        if not r:
            break
        iid = r[0]
    return iid


def _urls(pulse_db, keys: list[str]) -> dict[str, str]:
    """수집 DB(읽기 전용)에서 기사 원래 주소. 수집 DB 가 없으면 빈 사전."""
    if not pulse_db or not keys or not pathlib.Path(pulse_db).exists():
        return {}
    out = {}
    con = sqlite3.connect(f"file:{pulse_db}?mode=ro", uri=True)
    try:
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            q = ",".join("?" * len(chunk))
            for k, u in con.execute(f"SELECT key, url FROM items WHERE key IN ({q})", chunk):
                out[k] = u or ""
    finally:
        con.close()
    return out


def _groups(con, iid: str, cid: int | None, asof_iso: str | None, pulse_db) -> dict[str, list[dict]]:
    """날마다 이 이슈에 붙은 그룹(확정된 날은 확정 그룹, 아니면 asof 까지 마지막 단계의 그룹)과 그 기사."""
    fin = {r[0] for r in con.execute("SELECT day FROM final_days f JOIN calc_runs c USING(calc_id) WHERE c.asof<=?",
                                     (asof_iso or "9999",))}
    rows = con.execute("SELECT * FROM groups WHERE issue_id=? AND (final=1 OR calc_id=?) ORDER BY day, first_at, seed_key",
                       (iid, cid if cid is not None else -1)).fetchall()
    gs = [store._row_group(r) for r in rows if (r["final"] == 1) == (r["day"] in fin)]
    keys = sorted({k for g in gs for k in [*g["units"], *g["copies"]]})
    arts = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in con.execute(f"SELECT item_key, outlet, family, kind, title, canon_url, event_at FROM articles"
                             f" WHERE item_key IN ({q})", chunk):
            arts[r["item_key"]] = dict(r)
    urls = _urls(pulse_db, keys)
    out: dict[str, list[dict]] = {}
    for g in gs:
        items = []
        for k in [*g["units"], *g["copies"]]:
            a = arts.get(k) or {}
            items.append({"key": k, "outlet": a.get("outlet"), "kind": a.get("kind"), "title": a.get("title"),
                          "url": urls.get(k) or a.get("canon_url") or "", "at": a.get("event_at"),
                          "copy": k in g["copies"], "seed": k == g["seed"]})
        out.setdefault(g["day"], []).append({"group_id": g["group_id"], "title": g["title"], "families": g["families"],
                                             "link": g["link"], "articles": items})
    return out


def explain(con, issue_id: str, asof=None, pulse_db=None) -> dict:
    """이슈 하나의 내역. pulse_db 를 주면 기사의 원래 주소를 수집 DB(읽기 전용)에서 읽는다."""
    asof_iso = config.iso_utc(asof) if asof else None
    iid = _resolve(con, issue_id)
    rec = con.execute("SELECT * FROM issues WHERE issue_id=?", (iid,)).fetchone()
    cid = store.last_calc_upto(con, asof_iso)
    calc = store.calc_row(con, cid) if cid else None
    out = {"issue_id": iid, "asked": issue_id, "found": rec is not None,
           "aliases": store.aliases_upto(con, asof_iso or "9999").get(iid, []),
           "first_day": rec["first_day"] if rec else None, "title": rec["title"] if rec else None,
           "history": store.history(con, iid, asof_iso),
           "calc": {"calc_id": cid, "asof": calc["asof"] if calc else None, "rules": calc["rules_ver"] if calc else None,
                    "formula": calc["formula_ver"] if calc else None, "dict": calc["dict_ver"] if calc else None},
           "title_now": None, "rep_group": None, "days": []}
    gdays = _groups(con, iid, cid, asof_iso, pulse_db) if rec is not None else {}
    for r in store.issue_day_rows(con, iid, asof_iso):
        det = r.get("detail") or {}
        ok = r["kinds_ok"]
        calc_v = {**det.get("calc", {}), "A": r["A"], "g": r["g"], "w": r["w"], "v": r["v"], "H": r["H"], "B": r["B"],
                  "P": r["P"], "D": r["D"], "score_raw": r["score_raw"], "score": r["score"],
                  "present": r["kinds_present"]}
        out["days"].append({
            "day": r["day"], "final": r["final"], "state": r["state"], "state_rule": det.get("rule"),
            "state_rule_name": state.NAMES.get(det.get("rule")) if det.get("rule") else None,
            "families": det.get("families", []), "copies": det.get("copies", []), "trends": det.get("trends", []),
            "wiki": "위키백과 수집 없음", "status": det.get("status", {}), "missing": r["missing"],
            "followups": det.get("followups", []), "entities": det.get("entities", []),
            "category": r["category"], "category_points": det.get("category_points", {}),
            "indirect": det.get("indirect", []), "sensitivity": r["sensitivity"],
            "groups": gdays.get(r["day"], []),
            "lines": score.formula_lines(calc_v, ok)})
        row = det.get("row")
        if row:                               # board 의 후보 한 줄(기준일 줄에만 있다)
            out["title_now"], out["rep_group"] = row.get("title"), row.get("rep_group")
    return out


def render(x: dict) -> str:
    if not x["found"]:
        return f"{x['asked']}: 번호 대장에 없다"
    L = [f"이슈 {x['issue_id']}" + (f" (물은 번호 {x['asked']})" if x["asked"] != x["issue_id"] else ""),
         f"첫날 {x['first_day']} · 별칭 {', '.join(x['aliases']) or '없음'}"]
    if x.get("title_now"):
        L.append(f"대표 제목 {x['title_now']}" + (f" (그룹 {x['rep_group']})" if x.get("rep_group") else ""))
    for h in x["history"]:
        L.append(f"  이력 {h['at'][:16]} {h['kind']} {json.dumps(h['detail'], ensure_ascii=False)}")
    for d in x["days"]:
        L.append("")
        L.append(f"[{d['day']}] {'확정' if d['final'] else '잠정'} · 상태 {d['state'] or '-'}"
                 + (f" (규칙 {d['state_rule']}: {d['state_rule_name']})" if d["state_rule"] else ""))
        if d["families"]:
            L.append(f"  매체 계열 {len(d['families'])}곳: {', '.join(d['families'])}")
        for c in d["copies"]:
            L.append(f"  전재로 뺀 기사: {c['key']} → 대표 {c.get('rep', '?')} (규칙 {c.get('rule', '확정 대표')})")
        for t in d["trends"]:
            L.append(f"  급상승 검색어: {t['keyword']} (표기 {t['traffic_raw'] or '없음'} → 등급 {t['grade']})")
        L.append(f"  {d['wiki']}")
        if d["status"]:
            L.append("  종류 상태: " + ", ".join(f"{k} {v['status']}" for k, v in d["status"].items()))
        L += ["  " + ln for ln in d["lines"]]
        for g in d.get("groups") or []:
            lk = g.get("link") or {}
            why = lk.get("rule") or (f"Ee {lk.get('Ee')} {lk.get('ents', [])}, Et {lk.get('Et')} {lk.get('terms', [])}, "
                                     f"S* {lk.get('S')}, 간격 {lk.get('gap')}" if lk else "")
            L.append(f"  그룹 {g['group_id']} · 계열 {len(g['families'])}곳 · {g['title']}" + (f" · 잇기: {why}" if why else ""))
            for a in g["articles"]:
                L.append(f"    {'전재 ' if a['copy'] else ''}{a['outlet']} · {a['title']} · {a['url']}")
        for f in d["followups"]:
            L.append(f"  후속 사건: {f['title']} · 계열 {', '.join(f['families'])} · 새 낱말 {', '.join(f['new_terms'])}")
        for e in d["entities"]:
            L.append(f"  새 인물·기관: {e['entity']} · 계열 {', '.join(e['families'])}")
        if d["category_points"]:
            L.append(f"  분야 {d['category']}: " + ", ".join(f"{k} {v}" for k, v in sorted(d["category_points"].items())))
        if d["indirect"]:
            L.append(f"  간접 포착 기사: {', '.join(d['indirect'])}")
        sens = d["sensitivity"] or {}
        if sens.get("level") and sens["level"] != "GREEN":
            L.append(f"  민감 {sens['level']}: {'; '.join(sens.get('reasons') or [])}")
    c = x["calc"]
    L += ["", f"계산 번호 {c['calc_id']} · asof {c['asof']} · 판 {c['rules']}/{c['formula']}/{c['dict']}"]
    return "\n".join(L)
