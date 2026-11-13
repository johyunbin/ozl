"""날짜별 값 계산(§5, §6): 묶기 결과(pipeline.step)를 받아 이슈마다 날짜 d 의 A, g, w, v, H, B, P, D, 화제 점수, 상태, 분야,
민감, 간접 포착, 후보 한 줄을 만든다. DB 를 모른다(engine.py 가 읽고 쓴다).

계산하는 이슈: 날짜 d 에 쓰이는 번호(합치기 판단을 따라간 번호)이고, d 까지 그룹이 있고 마지막 그룹이 14일 안인 것.
14일 넘게 조용한 이슈는 줄을 쓰지 않고, 다시 붙으면 마지막 줄의 H 를 빈 날마다 0.7 로 줄여 이어 받는다(그 사이 v=0).
다만 그 사이 언론과 검색이 모두 실패한 날(v=없음)은 줄이지 않는다.
"""
from __future__ import annotations

import functools
from collections import defaultdict

from ozl.signals import category, config, followup, health, score, state, text, trends


@functools.lru_cache(maxsize=65536)
def _sens(title: str, summary: str, context: str) -> tuple:
    from ozl.research import sensitive
    r = sensitive.classify_item(title, summary, context)
    return r["level"], tuple(r["reasons"])


def sensitivity(arts: list[dict]) -> dict:
    from ozl.research import sensitive
    ctx = " / ".join(a["title"] for a in arts)[:2000]
    res = [{"level": lv, "reasons": list(rs)} for lv, rs in (_sens(a["title"], a.get("summary") or "", ctx) for a in arts)]
    return sensitive.worst(res)


class DayCalc:
    def __init__(self, res: dict, final_rows: list[dict], statuses: dict[str, dict], asof, days: list[str],
                 final_now: set[str], status_of=None):
        # 날짜는 안에서 정렬한다(H·P·상태가 전날 값을 이어 받으므로 순서가 결과를 바꾼다).
        self.res, self.asof, self.days, self.final_now = res, asof, sorted(days), final_now
        self.status_of = status_of                      # 날 → 종류별 상태. 계산하지 않은 날(건너뛴 날)의 수집 실패를 볼 때 쓴다
        self.ov, self.reg, self.arts = res["overrides"], res["registry"], res["articles"]
        self.statuses = statuses                       # 날 → 종류 → {status, last_ok}
        self.base = config.kst_day(asof)
        self.partial = asof < health.day_end(self.base, config.t_final(self.base))
        self.groups = sorted([*res["frozen"], *res["groups"]], key=lambda g: (g["day"], g["first_at"], g["seed"]))
        self.rows: dict[str, dict[str, dict]] = defaultdict(dict)     # 번호 → 날 → 줄(확정 행 + 이번 계산)
        for r in final_rows:
            self.rows[r["issue_id"]][r["day"]] = r
        self.late = defaultdict(list)                                 # (원래 번호, 날) → 확정 대표를 따르는 사본
        for k, v in res["late_copies"].items():
            a = self.arts.get(k)
            if a and v.get("issue_id"):
                self.late[(v["issue_id"], a["day"])].append(k)
        self.out_rows, self.trend_rows, self.fu_rows, self.ent_rows, self.hist = [], [], [], [], []
        self.unmatched: dict[str, list] = {}

    # ── 번호
    def owner_map(self, d: str) -> dict[str, str]:
        return {g["issue_id"]: self.ov.resolve(g["issue_id"], d) for g in self.groups if g["issue_id"]}

    def _valid(self, iid: str, d: str) -> bool:
        if iid.startswith("임시-"):
            return True
        rec = self.reg.get(iid)
        return bool(rec and rec.status == "active" and rec.first_day <= d and self.ov.resolve(iid, d) == iid)

    def first_day(self, iid: str, srcs: list[str], gs: list[dict]) -> str:
        fds = [self.reg[j].first_day for j in srcs if j in self.reg]
        return min(fds) if fds else min(g["day"] for g in gs)

    # ── 이전 날
    def prev(self, srcs: list[str], iid: str, d: str):
        y = config.day_add(d, -1)
        prev_H, v_hist, fe_hist = 0.0, {}, defaultdict(lambda: [0, 0])
        for j in srcs:
            rows = {x: r for x, r in self.rows.get(j, {}).items() if x < d}
            if rows:
                last = max(rows)
                prev_H = max(prev_H, self._carry_H(rows[last]["H"], last, y))
            for x, r in rows.items():
                v = r["v"]
                if x not in v_hist or (v is not None and (v_hist[x] is None or v > v_hist[x])):
                    v_hist[x] = v
                fe_hist[x][0] += r.get("f_new") or 0
                fe_hist[x][1] += r.get("e_new") or 0
        own = {x: r for x, r in self.rows.get(iid, {}).items() if x < d}
        prev_state = own[max(own)]["state"] if own else None
        return prev_H, v_hist, {x: tuple(v) for x, v in fe_hist.items()}, prev_state

    def _v_missing(self, d: str) -> bool:
        """그날 언론과 검색이 모두 실패해 v 가 없음인가(그날은 H 를 줄이지 않는다 · §5-1). 상태를 모르면 거짓."""
        st = self.statuses.get(d)
        if st is None and self.status_of is not None:
            st = self.status_of(d)
        if st is None:
            return False
        return score.v_value(0, 0.0, None, health.ok_kinds(st)) is None

    def _carry_H(self, H: float, last: str, y: str) -> float:
        """마지막 줄(last)의 H 를 y 까지 이어 받는다. 줄을 쓰지 않은 날은 v=0 으로 보고 0.7 을 곱하되,
        언론과 검색이 모두 실패한 날(v=없음)은 곱하지 않는다."""
        x = config.day_add(last, 1)
        while x <= y:
            if not self._v_missing(x):
                H *= config.H_DECAY
            x = config.day_add(x, 1)
        return H

    # ── 하루
    def run(self) -> None:
        for d in self.days:
            self.run_day(d)

    def _arts_of(self, gs: list[dict], late: list[str] = ()) -> tuple[list[dict], list[dict]]:
        units = [self.arts[k] for g in gs for k in g["units"] if k in self.arts]
        copies = [self.arts[k] for g in gs for k in g.get("copies") or [] if k in self.arts]
        copies += [self.arts[k] for k in late if k in self.arts]
        return units, copies

    def run_day(self, d: str) -> None:
        own = self.owner_map(d)
        srcs: dict[str, list[str]] = defaultdict(list)
        for orig, o in sorted(own.items()):
            srcs[o].append(orig)
        by_day: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        last_day: dict[str, str] = {}
        for g in self.groups:
            if g["issue_id"] and g["day"] <= d:
                o = own[g["issue_id"]]
                by_day[o][g["day"]].append(g)
                last_day[o] = g["day"]
        lo = config.day_add(d, -config.QUIET_STOP_DAYS)
        ids = sorted(i for i, ld in last_day.items() if ld >= lo and self._valid(i, d))
        y = config.day_add(d, -1)
        cut = config.t_final(d) if d in self.final_now else self.asof
        sides = {}
        for iid in ids:
            gs = by_day[iid].get(y, []) + by_day[iid].get(d, [])
            late = [k for j in srcs[iid] for x in (y, d) for k in self.late.get((j, x), [])]
            u, c = self._arts_of(gs, late)
            sides[iid] = (gs[0]["lang"] if gs else self._lang(iid), trends.side_of(u + c))
        tr_d = [a for a in self.arts.values() if a["kind"] == "trend" and a["day"] == d and a["received_at"] <= cut]
        got, un = trends.assign(tr_d, {i: s for i, s in sides.items() if s[1][0]})
        self.unmatched[d] = [{"keyword": t["title"], "grade": score.grade(trends.traffic(t)), "day": d, "lang": t["lang"]}
                             for t in un]
        by_issue_tr = defaultdict(list)
        for t in got.values():
            by_issue_tr[t["issue_id"]].append(t)
        for iid in ids:
            self.issue_day(iid, d, sorted(set(srcs[iid]) | {iid}), by_day[iid], by_issue_tr.get(iid, []))

    def _lang(self, iid: str) -> str:
        rec = self.reg.get(iid)
        return rec.lang if rec else "ko"

    def issue_day(self, iid: str, d: str, srcs: list[str], gdays: dict, trs: list[dict]) -> None:
        gs = gdays.get(d, [])
        allg = [g for x in sorted(gdays) for g in gdays[x]]
        first = self.first_day(iid, srcs, allg)
        hist = [g for x in sorted(gdays) if x < d for g in gdays[x]]
        late = [k for j in srcs for k in self.late.get((j, d), [])]
        units, copies = self._arts_of(gs, late)
        fams = sorted({f for g in gs for f in g["families"]})
        official = any(g["has_official"] for g in gs)
        g_val = max([t["grade"] for t in trs] or [0.0])
        fus = followup.followups(d, first, gs, hist, self.arts)
        ents = followup.new_entities(d, first, gs, hist)
        st = self.statuses[d]
        ok = health.ok_kinds(st)
        prev_H, v_hist, fe_hist, prev_state = self.prev(srcs, iid, d)
        r = score.day_values(A=len(fams), g=g_val, w=None, official=official, ok=ok, prev_H=prev_H, v_hist=v_hist,
                             fe_hist=fe_hist, f=len(fus), e=len(ents), day=d, first_day=first)
        vh = dict(v_hist)
        vh[d] = r["v"]
        final = d in self.final_now
        stt, rule = state.state_of(d, first, vh, prev_state, len(fus), ended=iid in self.ov.ended,
                                   partial=(d == self.base and self.partial))
        near = [g for x in (config.day_add(d, -2), config.day_add(d, -1), d) for g in gdays.get(x, [])]
        n_units, _ = self._arts_of(near)
        cat, cat_pts = category.category_of(n_units)
        yd = gdays.get(config.day_add(d, -1), [])
        y_units, y_copies = self._arts_of(yd)
        # 민감은 그날 기사로만 본다(§6-4). 그날 기사가 없는 날(어제만 있는 2일째 등)은 어제 기사로 본다.
        sens = sensitivity(units + copies) if units or copies else sensitivity(y_units + y_copies)
        ind = sorted({a["family"] for a in units if a["kind"] == "news" and a.get("indirect")})
        active = bool(gs or yd or trs)
        row = {"issue_id": iid, "day": d, "final": final, "A": len(fams), "g": g_val, "w": None, "v": r["v"], "H": r["H"],
               "B": r["B"], "P": r["P"], "D": r["D"], "f_new": len(fus), "e_new": len(ents), "score_raw": r["score_raw"],
               "score": r["score"], "state": stt, "kinds_present": r["present"], "kinds_ok": score.ordered(ok),
               "missing": health.missing_labels(st), "category": cat, "sensitivity": sens,
               "person": any(a.get("person") for a in units + y_units), "indirect_n": len(ind),
               "articles_n": len(units) + len(copies), "copies_n": len(copies), "first_day": first, "_active": active}
        row["detail"] = {"calc": {k: r[k] for k in ("prev_H", "p_days", "f_sum", "e_sum")}, "rule": rule,
                         "first_day": first, "active": active}
        if active:
            row["detail"].update({
                "families": fams, "units": [a["key"] for a in units],
                "copies": [{"key": a["key"], **({k: v for k, v in self.res["copies"].get(a["key"], {}).items()
                                                  if k in ("rep", "rule", "dice")})} for a in copies],
                "trends": [{k: t[k] for k in ("trend_key", "keyword", "traffic_raw", "grade", "matched_article")} for t in trs],
                "status": {k: {"status": v["status"], "last_ok": config.iso_utc(v["last_ok"]) if v["last_ok"] else None}
                           for k, v in st.items()},
                "followups": fus, "entities": ents, "category_points": cat_pts,
                "indirect": [a["key"] for a in units if a.get("indirect")], "groups": [g["group_id"] for g in gs]})
        if d == self.base:
            row["detail"]["row"] = self.candidate(iid, d, row, gdays, fus, ents, units, ind)
            row["detail"]["row"]["_z"] = {"v": r["v"], "v_prev": vh.get(config.day_add(d, -1)),
                                          "vdays": sum(1 for x, v in vh.items() if x >= first and v is not None
                                                       and v >= config.V_ACTIVE),
                                          "ended": iid in self.ov.ended}
        self.rows[iid][d] = row
        self.out_rows.append(row)
        for t in trs:
            self.trend_rows.append({**t, "issue_id": iid, "day": d})
        if final:
            self.fu_rows += [{**u, "issue_id": iid, "day": d} for u in fus]
            self.ent_rows += [{**e, "issue_id": iid, "day": d} for e in ents]
            if stt != prev_state:
                kind = {"휴면": "휴면", "종료": "종료"}.get(stt) or {"휴면": "깨어남", "종료": "재개"}.get(prev_state)
                if kind:
                    self.hist.append({"issue_id": iid, "at": config.iso_utc(self.asof), "kind": kind,
                                      "detail": {"day": d, "state": stt, "before": prev_state}})

    # ── 후보 한 줄(§8-1)
    def _gsens(self, g: dict) -> str:
        u, c = self._arts_of([g])
        return sensitivity(u + c)["level"] if u or c else "GREEN"

    def rep_group(self, iid: str, allg: list[dict]) -> dict | None:
        """대표 그룹(§8-1): 지금까지 매체 계열이 가장 많은 그룹(같으면 이른 것)과 이슈를 처음 만든 씨앗 그룹 가운데,
        많은 계열 쪽을 먼저 쓴다. 그 그룹의 민감 표시가 높음(RED)이면 씨앗 그룹을, 둘 다 높음이면
        민감 표시가 낮은 그룹 가운데 계열이 많은 것을 쓴다."""
        if not allg:
            return None
        rank = {"GREEN": 0, "YELLOW": 1, "RED": 2}
        order = sorted(allg, key=lambda g: (-len(g["families"]), g["day"], g["first_at"], g["seed"]))
        rec = self.reg.get(iid)
        seed = next((g for g in allg if rec and g["seed"] == rec.seed_key), None) or \
            min(allg, key=lambda g: (g["day"], g["first_at"], g["seed"]))
        for g in (order[0], seed):
            if self._gsens(g) != "RED":
                return g
        return min(order, key=lambda g: (rank.get(self._gsens(g), 2), order.index(g)))

    def candidate(self, iid, d, row, gdays, fus, ents, units, ind) -> dict:
        rec = self.reg.get(iid)
        allg = [g for x in sorted(gdays) for g in gdays[x]]
        rep = self.rep_group(iid, allg)
        title = rep["title"] if rep else (rec.title if rec else "")
        n = config.day_diff(d, row["first_day"]) + 1
        if fus:
            best = max(fus, key=lambda u: (len(u["families"]), -fus.index(u)))
            new_thing = best["title"]
        elif ents:
            new_thing = "새로 나온 이름: " + ", ".join(e["entity"] for e in ents[:3])
        else:
            new_thing = ""
        ys = gdays.get(config.day_add(d, -1), []) + gdays.get(d, [])
        yrow = self.rows.get(iid, {}).get(config.day_add(d, -1))
        prev_day = None
        if yrow is not None:
            prev_day = {"day": config.day_add(d, -1), "outlets_n": yrow["A"], "articles_n": yrow["articles_n"],
                        "kinds": list(yrow["kinds_present"]), "kinds_ok": list(yrow["kinds_ok"]),
                        "score": yrow["score"], "state": yrow["state"]}
        return {"issue_id": iid, "lang": rec.lang if rec else (allg[0]["lang"] if allg else "ko"), "title": title,
                "day_n": n, "first_day": row["first_day"],
                "status_line": f"{n}일째" + (f" · {row['state']}" if row["state"] else ""), "new_thing": new_thing,
                "outlets_n": row["A"], "articles_n": row["articles_n"], "copies_n": row["copies_n"],
                "indirect": {"n": len(ind), "label": f"커뮤니티에서 화제라는 보도 {len(ind)}곳"} if ind else None,
                "rep_group": rep["group_id"] if rep else None, "prev_day": prev_day,
                "links": self.links(ys, rep)}

    def links(self, gs: list[dict], rep: dict | None = None) -> list[dict]:
        """최대 3개: 대표 그룹의 기사(씨앗부터, 서로 다른 계열) 둘, 공공 원문 하나, 나머지는 어제·오늘 그룹의 서로 다른 계열."""
        out, seen = [], set()

        def news_of(g):
            mem = [self.arts[k] for k in g["units"] if k in self.arts and self.arts[k]["kind"] == "news"]
            mem.sort(key=lambda a: (a["key"] != g["seed"], a["event_at"], a["key"]))
            return mem
        if rep is not None:
            for a in news_of(rep):
                if len(out) >= 2:
                    break
                if a["family"] not in seen:
                    seen.add(a["family"])
                    out.append(self._link(a))
        offs = sorted((self.arts[k] for g in gs for k in g["units"] if k in self.arts and self.arts[k]["kind"] == "official"),
                      key=lambda a: (a["event_at"], a["key"]), reverse=True)
        if offs and len(out) < 3:
            out.append(self._link(offs[0]))
        for g in sorted(gs, key=lambda g: (-len(g["families"]), g["first_at"], g["seed"])):
            for a in news_of(g):
                if len(out) >= 3:
                    return out
                if a["family"] in seen:
                    continue
                seen.add(a["family"])
                out.append(self._link(a))
        return out

    @staticmethod
    def _link(a: dict) -> dict:
        return {"title": text.strip_head(a["title"]), "url": a.get("url") or "", "outlet": a["outlet"],
                "at": a["event_at"].astimezone(config.KST).isoformat(), "kind": a["kind"]}
