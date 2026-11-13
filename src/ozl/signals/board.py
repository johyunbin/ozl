"""board.json(§8-1): 후보 목록, 두 구역(§6-2), 출처 상태. 운영 화면과 웹 첫 화면이 읽는다. 원자적으로 쓴다(임시 파일 → os.replace).

두 구역(계획 4-2, 5-2):
- 오늘 새로 뜬 것(많아야 4줄): 1~2일째, v_new = max(v(D), v(D−1)) ≥ 0.1(1일째는 v(D)). v_new → 간접 포착 → S_raw → 번호 순.
- 며칠째 이어지는 것(많아야 6줄): 3일째 이상, v ≥ 0.1 인 날 2일 이상, v(D) 또는 v(D−1) ≥ 0.1, 휴면 아님. S_raw → 번호 순.
- 한국어, 종료 아님, 민감 RED 아님. 한 분야는 구역 최대 줄 수의 절반까지(넘으면 건너뛰고 capped 에 센다).
  '기타'(분야를 정하지 못한 이슈)는 분야가 아니므로 상한을 걸지 않는다.
"""
from __future__ import annotations

import json
import os
import pathlib
from collections import Counter

from ozl.signals import category, config

SCHEMA = "ozl.board/1"
NOTE = "검증 전 신호다. 화제 점수는 얼마나 화제인가만 잰다. 사실 여부와 중요성과 무관하다."
NO_NEW = "오늘 새로 잡힌 이슈가 없다"
NO_COND = "조건(v 0.1 이상)을 넘는 이슈가 없다"
FAILED = "수집 실패로 오늘 값을 내지 못했다"
FORMULA_NOTE = ["정상일의 식(위키백과 수집 없음): v = (0.6 L(A) + 0.25 g) / 0.85",
                "B 의 분모는 3(언론, 검색, 공공 원문)이다"]


def _num(x):
    return None if x is None else round(float(x), 6)


def full_row(r: dict, aliases: list[str]) -> dict:
    """issue_days 의 기준일 줄(+ detail.row) → 후보 한 줄."""
    base = dict(r["detail"]["row"])
    sens = r.get("sensitivity") or {}
    out = {"issue_id": base["issue_id"], "aliases": sorted(aliases), "lang": base["lang"], "title": base["title"],
           "score": r["score"], "score_raw": _num(r["score_raw"]), "state": r["state"], "day_n": base["day_n"],
           "first_day": base["first_day"], "status_line": base["status_line"], "new_thing": base["new_thing"],
           "parts": {"v": _num(r["v"]), "H": _num(r["H"]), "B": _num(r["B"]), "P": _num(r["P"]), "D": _num(r["D"]),
                     "A": r["A"], "g": _num(r["g"]), "w": _num(r["w"])},
           "outlets_n": base["outlets_n"], "articles_n": base["articles_n"], "copies_n": base["copies_n"],
           "kinds": list(r["kinds_present"]), "kinds_ok": list(r["kinds_ok"]), "missing": list(r["missing"]),
           "category": r["category"],
           "sensitivity": {"level": sens.get("level", "GREEN"), "reason": "; ".join(sens.get("reasons") or [])},
           "person": bool(r["person"]), "indirect": base["indirect"], "links": base["links"],
           "prev_day": base.get("prev_day"), "zone": None,
           "_z": base["_z"], "_raw": r["score_raw"]}
    return out


def _raw(c) -> float:
    """정렬에 쓰는 반올림 전 화제 점수(§5-1). 없음은 맨 뒤."""
    x = c.get("_raw", c["score_raw"])
    return -1.0 if x is None else float(x)


def _key_new(c):
    z = c["_z"]
    return (-_vnew(c), 0 if c["indirect"] else 1, -_raw(c), c["issue_id"])


def _vnew(c) -> float:
    z = c["_z"]
    xs = [z["v"]] if c["day_n"] == 1 else [z["v"], z["v_prev"]]
    xs = [x for x in xs if x is not None]
    return max(xs) if xs else -1.0


def _eligible(c) -> bool:
    return (c["lang"] == "ko" and not c["_z"].get("ended") and c["state"] != "종료"
            and (c.get("sensitivity") or {}).get("level") != "RED")


def _fill(cands: list[dict], limit: int) -> tuple[list[str], list[dict]]:
    cap = limit // 2
    used, skipped, rows = Counter(), Counter(), []
    for c in cands:
        if len(rows) >= limit:
            break
        cat = c["category"]
        if cat != category.OTHER and used[cat] >= cap:
            skipped[cat] += 1
            continue
        used[cat] += 1
        rows.append(c["issue_id"])
    return rows, [{"category": k, "skipped": v} for k, v in sorted(skipped.items())]


def zones(cands: list[dict], failed_both: bool) -> dict:
    pool = [c for c in cands if _eligible(c)]
    young = [c for c in pool if c["day_n"] in (1, 2)]
    new = sorted([c for c in young if _vnew(c) >= config.ZONE_V], key=_key_new)

    def ok_old(c):
        z = c["_z"]
        return (c["day_n"] >= 3 and z["vdays"] >= 2 and c["state"] != "휴면"
                and ((z["v"] or 0) >= config.ZONE_V or (z["v_prev"] or 0) >= config.ZONE_V))
    old = sorted([c for c in pool if ok_old(c)],
                 key=lambda c: (-_raw(c), c["issue_id"]))
    out = {}
    for name, lst, limit in (("new", new, config.ZONE_NEW_MAX), ("ongoing", old, config.ZONE_ONGOING_MAX)):
        rows, capped = _fill(lst, limit)
        reason = None
        if not rows:
            if failed_both:
                reason = FAILED
            elif not pool or (name == "new" and not young):
                reason = NO_NEW
            else:
                reason = NO_COND
        out[name] = {"rows": rows, "empty_reason": reason, "capped": capped}
    return out


def build(meta: dict, day_rows: list[dict], aliases: dict[str, list[str]]) -> dict:
    """meta: 계산 기록에 남긴 판의 머리(asof, 출처 상태 …). day_rows: 기준일의 issue_days 줄(detail 포함)."""
    cands = [full_row(r, aliases.get(r["issue_id"], [])) for r in day_rows
             if r.get("detail", {}).get("row") and r["detail"].get("active")]
    cands.sort(key=lambda c: (-_raw(c), c["issue_id"]))
    z = zones(cands, meta["failed_both"])
    where = {i: name for name, zz in z.items() for i in zz["rows"]}
    for c in cands:
        c["zone"] = where.get(c["issue_id"])
        c.pop("_z", None)
        c.pop("_raw", None)
    return {"schema": SCHEMA, "asof": meta["asof"], "base_day": meta["base_day"], "base_day_partial": meta["partial"],
            "decided_at": meta["decided_at"], "calc_id": meta["calc_id"], "mode": meta["mode"],
            "versions": meta["versions"], "basis": meta["basis"], "formula_note": FORMULA_NOTE,
            "sources": meta["sources"], "missing": meta["missing"], "zones": z, "candidates": cands,
            "searches_unmatched": [{k: s[k] for k in ("keyword", "grade", "day")} for s in meta["unmatched"]
                                   if s.get("lang", "ko") == "ko"],
            "merge_hints": meta["merge_hints"], "note": NOTE}


def write(b: dict, path: pathlib.Path | str) -> pathlib.Path:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return p
