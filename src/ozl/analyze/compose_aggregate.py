#!/usr/bin/env python3
"""구성 라벨(private/compose/*.json) + 슬라이드 타임라인 → 구성 템플릿 v0 집계 (Phase 2A-2).

입력: private/compose/<video_id>.json(서브에이전트 라벨 — SCHEMA.md v2) · private/slides_label/<video_id>.json
출력: tracks/syuka/analysis/composition_syukaworld.md(집계만 · 공개) · tracks/syuka/style/composition_template_v0.json(공개 스타일 자산)
슬라이드 문구·전사는 싣지 않는다(제목 첫 어절·어미 같은 형태 통계만).

    python -m ozl.analyze.compose_aggregate            # 도출 표본(홀드아웃 제외) 집계
    python -m ozl.analyze.compose_aggregate holdout    # + 홀드아웃 두 라벨러 일치도·템플릿 규칙 적중률
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "private" / "compose"
SLIDES = ROOT / "private" / "slides_label_r2"  # 라벨링에 쓴 슬라이드 목록의 고정본(1..N) — 번호가 라벨과 맞아야 하므로 재생성본(slides_label)이 아니라 고정본을 읽는다
OUT_MD = ROOT / "tracks" / "syuka" / "analysis" / "composition_syukaworld.md"
OUT_JSON = ROOT / "tracks" / "syuka" / "style" / "composition_template_v0.json"
HOLDOUT = ["xymdBYW2WUo", "WtYWltGjho4", "t-IIGGFe80U", "tIQFRHoKqdw", "gdfRFs0yMco"]

CONNECTIVES = {"그런데", "그러나", "하지만", "물론", "결국", "그러자", "그래서", "게다가", "그리고", "더구나", "반면", "다만", "만약", "한편", "그럼", "사실", "특히",
               "심지어", "덕분에", "그렇다보니", "이처럼", "또한", "즉", "따라서", "그러면", "그렇다면", "오히려", "문제는", "아니", "그래도", "이제는", "여기에", "더욱이"}
CHAIN_END = re.compile(r"(는데|지만|면서|으며|하며|하자|이자|이고|하고|해서|라서|니까|인데|은데|던데|다가|려고|도록|자마자|뿐만 아니라)[\.\!…]*$")


def base(x: str) -> str:
    return (x or "").split(":")[0].strip().lower()


def load(folder: pathlib.Path, vids: list[str] | None = None) -> list[dict]:
    out = []
    for p in sorted(folder.glob("*.json")):
        if vids is not None and p.stem not in vids:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[{p.name}] JSON 오류: {e}", file=sys.stderr)
            continue
        sl = json.loads((SLIDES / f"{p.stem}.json").read_text(encoding="utf-8"))
        nos = [s["no"] for s in sl["slides"]]
        roles = {r["no"]: r for r in d.get("slide_roles", [])}
        st = sorted(d.get("stages", []), key=lambda s: s["slide_from"])
        ok = (set(roles) == set(nos) and bool(st) and st[0]["slide_from"] == min(nos) and st[-1]["slide_to"] == max(nos)
              and all(x["slide_from"] <= x["slide_to"] for x in st) and all(a["slide_to"] + 1 == b["slide_from"] for a, b in zip(st, st[1:])))
        if not ok:
            print(f"[{p.stem}] 스키마 위반: roles {len(roles)}/{len(nos)} · stages 연속성 {'OK' if st else '없음'}", file=sys.stderr)
        d["_slides"], d["_stages"], d["_roles"], d["_valid"] = sl["slides"], st, roles, ok
        d["_real"] = [no for no, r in roles.items() if base(r.get("role")) != "non_slide"]  # 오프닝·엔딩 화면 등을 뺀 실제 슬라이드 번호
        out.append(d)
    return out


def med(xs, nd=2):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), nd) if xs else None


def rel(no: int, n: int) -> float:
    return (no - 1) / max(1, n - 1)


def boundaries(d: dict) -> list[int]:
    """단계 경계 = 두 번째 단계부터의 시작 슬라이드 번호."""
    return [s["slide_from"] for s in d["_stages"][1:]]


def title_stats(docs: list[dict]) -> dict:
    n = conn = ques = chain = 0
    first = Counter()
    for d in docs:
        for s in d["_slides"]:
            t = (s.get("title") or "").strip()
            if not t:
                continue
            n += 1
            w = re.split(r"[\s,]", t)[0]
            if w in CONNECTIVES:
                conn += 1
                first[w] += 1
            ques += int("?" in t[-4:])
            chain += int(bool(CHAIN_END.search(t)))
    return {"n": n, "connective_start": conn / max(1, n), "question": ques / max(1, n), "chain_ending": chain / max(1, n), "top_connectives": first.most_common(12)}


def aggregate(docs: list[dict]) -> dict:
    V = len(docs)
    stage_seq = [[base(s["stage"]) for s in d["_stages"]] for d in docs]
    stage_n = [len(x) for x in stage_seq]
    first, last = Counter(x[0] for x in stage_seq), Counter(x[-1] for x in stage_seq)
    st = {}
    for d in docs:
        n = len(d["_slides"])
        tot = Counter()
        for s in d["_stages"]:
            k = base(s["stage"])
            e = st.setdefault(k, {"videos": 0, "share": [], "center": [], "len": [], "count": 0})
            e["count"] += 1
            tot[k] += s["slide_to"] - s["slide_from"] + 1
            e["center"].append((rel(s["slide_from"], n) + rel(s["slide_to"], n)) / 2)
            e["len"].append(s["slide_to"] - s["slide_from"] + 1)
        for k, v in tot.items():  # 비중은 그 편에서 이 단계가 차지한 슬라이드 전부(여러 번 나오면 합산)
            st[k]["videos"] += 1
            st[k]["share"].append(v / n)
    roles, src = Counter(), Counter()
    role_third = [Counter(), Counter(), Counter()]
    non_slide = 0
    for d in docs:
        n = len(d["_slides"])
        for no, r in d["_roles"].items():
            if base(r.get("role")) == "non_slide":  # 오프닝·엔딩 화면·영상 재생 — 슬라이드 통계에서 뺀다
                non_slide += 1
                continue
            roles[base(r.get("role"))] += 1
            src[base(r.get("source_type"))] += 1
            role_third[min(2, int(rel(no, n) * 3))][base(r.get("role"))] += 1
    rev_n = [len(d.get("reversals") or []) for d in docs]
    rev_pos = [rel(r["slide_no"], len(d["_slides"])) for d in docs for r in (d.get("reversals") or []) if r.get("slide_no")]
    first_rev = [min(rel(r["slide_no"], len(d["_slides"])) for r in d["reversals"] if r.get("slide_no")) for d in docs if d.get("reversals")]
    kl = [d.get("korea_link") or {} for d in docs]
    kl_pos = [rel(k["slide_no"], len(d["_slides"])) for d, k in zip(docs, kl) if k.get("present") and k.get("slide_no") and k.get("mode") != "topic"]
    kl_mode = Counter((k.get("mode") or "slide") if k.get("present") else "none" for k in kl)
    verbal = [len(d.get("verbal_only_points") or []) for d in docs]
    multi = sum(1 for d in docs if (d.get("multi_topic") or {}).get("present"))
    hum_n = [len(d.get("humor_slides") or []) for d in docs]
    hum_pos = [rel(x, len(d["_slides"])) for d in docs for x in (d.get("humor_slides") or [])]
    bigram = Counter((a, b) for seq in stage_seq for a, b in zip(seq, seq[1:]))
    return {"V": V, "stage_n": stage_n, "first": first, "last": last, "st": st, "roles": roles, "src": src, "role_third": role_third, "rev_n": rev_n, "rev_pos": rev_pos,
            "first_rev": first_rev, "kl_present": sum(1 for k in kl if k.get("present")), "kl_pos": kl_pos, "hum_n": hum_n, "hum_pos": hum_pos, "bigram": bigram,
            "n_slides": [len(d["_real"]) for d in docs], "titles": title_stats(docs), "stage_seq": stage_seq,
            "non_slide": non_slide, "kl_mode": kl_mode, "verbal": verbal, "multi": multi}


# 규칙의 임계값은 도출 표본 25편의 분포만 보고 정했다(홀드아웃 라벨을 보기 전 · 2026-11-10). 홀드아웃에서 깨질 수 있는 진짜 검증이다.
def _first_rev(d):
    xs = [rel(r["slide_no"], len(d["_slides"])) for r in (d.get("reversals") or []) if r.get("slide_no")]
    return min(xs) if xs else None


RULES = [
    ("첫 단계가 hook(또는 lead_in)이다", lambda d: base(d["_stages"][0]["stage"]) in ("hook", "lead_in")),
    ("첫 단계는 전체 슬라이드의 15% 이하다", lambda d: (d["_stages"][0]["slide_to"] - d["_stages"][0]["slide_from"] + 1) / len(d["_slides"]) <= 0.15),
    ("두 번째 단계가 background·development·lead_in 중 하나다", lambda d: len(d["_stages"]) > 1 and base(d["_stages"][1]["stage"]) in ("background", "development", "lead_in")),
    ("단계 수가 9~17개다", lambda d: 9 <= len(d["_stages"]) <= 17),
    ("development 단계가 2번 이상 나온다", lambda d: sum(1 for s in d["_stages"] if base(s["stage"]) == "development") >= 2),
    ("반전 지점이 3~6곳이다", lambda d: 3 <= len(d.get("reversals") or []) <= 6),
    ("첫 반전이 앞 35% 안에 있다", lambda d: _first_rev(d) is not None and _first_rev(d) <= 0.35),
    ("유머 슬라이드가 2장 이상 있다", lambda d: len(d.get("humor_slides") or []) >= 2),
    ("한국 연결이 있다(슬라이드·말·주제 자체)", lambda d: bool((d.get("korea_link") or {}).get("present"))),
    ("마지막 단계가 closing 또는 implication 이다", lambda d: base(d["_stages"][-1]["stage"]) in ("closing", "implication")),
    ("외신(foreign_press)에 기댄 슬라이드가 30% 이상이다", lambda d: sum(1 for r in d["_roles"].values() if base(r.get("role")) != "non_slide" and base(r.get("source_type")) == "foreign_press") / max(1, len(d["_real"])) >= 0.3),
    ("가장 많은 역할이 quote(원문 인용)다", lambda d: Counter(base(r.get("role")) for r in d["_roles"].values() if base(r.get("role")) != "non_slide").most_common(1)[0][0] == "quote"),
]


def rule_hits(docs: list[dict]) -> list[tuple[str, int, int]]:
    out = []
    for name, fn in RULES:
        hit = 0
        for d in docs:
            try:
                hit += int(bool(fn(d)))
            except Exception:  # noqa: BLE001
                pass
        out.append((name, hit, len(docs)))
    return out


def agreement(a: dict, b: dict, tol: int = 1) -> tuple[int, int, int]:
    """두 라벨러의 단계 경계 일치(±tol 장). 반환 (일치 수, A 경계 수, B 경계 수)."""
    ba, bb = sorted(boundaries(a)), sorted(boundaries(b))
    i = j = m = 0
    while i < len(ba) and j < len(bb):  # 정렬된 두 열을 앞에서부터 짝짓는다 — 허용 오차가 같으면 이것이 최대 매칭
        if abs(ba[i] - bb[j]) <= tol:
            m, i, j = m + 1, i + 1, j + 1
        elif ba[i] < bb[j]:
            i += 1
        else:
            j += 1
    return m, len(ba), len(bb)


def pct_table(c: Counter, total: int, top: int = 12) -> list[str]:
    return [f"| {k} | {v} | {v / max(1, total):.0%} |" for k, v in c.most_common(top)]


def main(argv: list[str]) -> int:
    all_docs = [d for d in load(COMPOSE) if d["_valid"]]
    docs = [d for d in all_docs if d["video_id"] not in HOLDOUT]
    if not docs:
        print("유효한 구성 라벨 없음", file=sys.stderr)
        return 1
    A = aggregate(docs)
    V, T = A["V"], A["titles"]
    tot_slides = sum(A["roles"].values())
    L = ["# 슈카월드 한 주제의 구성 (대표 표본 · 구성 템플릿 v0 근거 집계)", "",
         f"대표 30편 중 **{V}편**(홀드아웃 {len(HOLDOUT)}편 제외)의 슬라이드 {tot_slides}장(오프닝·엔딩 화면 등 {A['non_slide']}장 제외)에 역할을 붙이고 이야기 단계로 묶은 결과다.",
         "라벨은 슬라이드 문구(문자 인식)와 전사를 함께 읽은 모델 라벨이며 사람 검수 전이다. 슬라이드 문구·전사는 싣지 않는다. 방법 = `src/ozl/analyze/compose_aggregate.py`.",
         "라벨에 쓴 슬라이드 목록은 묶음 로직을 고치기 전 판이라 `slide_structure_syukaworld.md` 의 최종 장수와 편당 0~2장(전체 1.5%) 다르다. 단계·역할 비율에는 영향이 없는 크기다.", "",
         "## 1. 뼈대", "",
         f"- 편당 슬라이드 중앙값 {med(A['n_slides'], 1)}장 · 단계 수 중앙값 **{med(A['stage_n'], 1)}개**(범위 {min(A['stage_n'])}~{max(A['stage_n'])})",
         f"- 첫 단계: " + " · ".join(f"{k} {v}/{V}" for k, v in A["first"].most_common(4)) + " — 마지막 단계: " + " · ".join(f"{k} {v}/{V}" for k, v in A["last"].most_common(4)), "",
         "| 단계 | 나온 편 | 편당 등장 | 슬라이드 비중(중앙값) | 한 번의 길이(장) | 위치(0=처음 · 1=끝) |", "|---|---|---|---|---|---|"]
    for k, e in sorted(A["st"].items(), key=lambda kv: med(kv[1]["center"])):
        L.append(f"| {k} | {e['videos']}/{V} | {e['count'] / max(1, e['videos']):.1f} | {med(e['share']):.0%} | {med(e['len'], 1)} | {med(e['center'])} |")
    L += ["", "- 가장 흔한 단계 이음: " + " · ".join(f"{a}→{b} {n}" for (a, b), n in A["bigram"].most_common(8)), "",
          "## 2. 슬라이드 한 장의 역할", "", "| 역할 | 장수 | 비율 |", "|---|---|---|", *pct_table(A["roles"], tot_slides), "",
          "| 역할 | 앞 1/3 | 가운데 | 뒤 1/3 |", "|---|---|---|---|"]
    for k, _ in A["roles"].most_common(8):
        L.append(f"| {k} | " + " | ".join(f"{A['role_third'][i][k] / max(1, sum(A['role_third'][i].values())):.0%}" for i in range(3)) + " |")
    L += ["", "## 3. 기대는 자료", "", "| 자료 유형 | 장수 | 비율 |", "|---|---|---|", *pct_table(A["src"], tot_slides), "",
          "## 4. 반전 · 한국 연결 · 유머", "",
          f"- 반전 지점: 편당 중앙값 **{med(A['rev_n'], 1)}곳** · 있는 편 {sum(1 for x in A['rev_n'] if x)}/{V} · 첫 반전 위치 중앙값 {med(A['first_rev'])} · 전체 반전 위치 중앙값 {med(A['rev_pos'])}",
          f"- 한국 연결: {A['kl_present']}/{V}편 (" + " · ".join(f"{k} {v}" for k, v in A["kl_mode"].most_common()) + f") · 주제 자체가 한국인 편을 뺀 위치 중앙값 {med(A['kl_pos'])}",
          f"- 슬라이드에 없이 말로만 한 핵심 주장: 편당 중앙값 {med(A['verbal'], 1)}곳 · 본 주제 뒤에 다른 주제·단신이 붙은 편 {A['multi']}/{V}",
          f"- 유머 슬라이드: 편당 중앙값 **{med(A['hum_n'], 1)}장** · 있는 편 {sum(1 for x in A['hum_n'] if x)}/{V} · 위치 중앙값 {med(A['hum_pos'])}", "",
          "## 5. 제목 문장의 형태 (문자 인식 결과에서 기계로 센 값)", "",
          f"- 제목 {T['n']}개 중 **접속어로 시작 {T['connective_start']:.0%}** · 물음표로 끝남 {T['question']:.0%} · 다음 장으로 이어지는 연결 어미로 끝남 {T['chain_ending']:.0%}",
          "- 자주 쓰는 접속어: " + " · ".join(f"{w} {c}" for w, c in T["top_connectives"]), "",
          "## 6. 구조 규칙 적중률", "", "| 규칙 | 도출 표본 |" + (" 홀드아웃 A | 홀드아웃 B |" if argv[:1] == ["holdout"] else ""), "|---|---|" + ("---|---|" if argv[:1] == ["holdout"] else "")]
    hits = rule_hits(docs)
    hold = None
    if argv[:1] == ["holdout"]:
        ha = [d for d in load(ROOT / "private" / "compose_holdout_a", HOLDOUT) if d["_valid"]]
        hb = [d for d in load(ROOT / "private" / "compose_holdout_b", HOLDOUT) if d["_valid"]]
        ra, rb = rule_hits(ha), rule_hits(hb)
        for (name, h, n), (_, h1, n1), (_, h2, n2) in zip(hits, ra, rb):
            L.append(f"| {name} | {h}/{n} ({h / max(1, n):.0%}) | {h1}/{n1} | {h2}/{n2} |")
        pairs = [(a, next((b for b in hb if b["video_id"] == a["video_id"]), None)) for a in ha]
        rows, M, NA, NB = [], 0, 0, 0
        for a, b in pairs:
            if b is None:
                continue
            m, na, nb = agreement(a, b)
            M, NA, NB = M + m, NA + na, NB + nb
            rows.append(f"| {a['video_id']} | {len(a['_slides'])} | {na} | {nb} | {m} | {2 * m / max(1, na + nb):.0%} |")
        f1 = 2 * M / max(1, NA + NB)
        strong = [(name, h, n) for name, h, n in hits if h / max(1, n) >= 0.8]
        hold_hits = sum(h1 for (name, h, n), (_, h1, _) in zip(hits, ra) if h / max(1, n) >= 0.8) + sum(h2 for (name, h, n), (_, h2, _) in zip(hits, rb) if h / max(1, n) >= 0.8)
        hold_tot = sum(n1 for (name, h, n), (_, _, n1) in zip(hits, ra) if h / max(1, n) >= 0.8) + sum(n2 for (name, h, n), (_, _, n2) in zip(hits, rb) if h / max(1, n) >= 0.8)
        L += ["", "## 7. 홀드아웃 5편 역적용", "",
              "도출에 쓰지 않은 5편을 서로 독립된 두 라벨러가 같은 어휘로 따로 라벨했다.", "",
              "| 영상 | 슬라이드 | A 경계 | B 경계 | 일치(±1장) | 일치율(F1) |", "|---|---|---|---|---|---|", *rows, "",
              f"- 단계 경계 일치율(±1장 · F1) **{f1:.0%}** ({M}/{NA}·{NB})",
              f"- 도출 표본에서 80% 이상 성립한 규칙 {len(strong)}개의 홀드아웃 적중 **{hold_hits}/{hold_tot} = {hold_hits / max(1, hold_tot):.0%}**"]
        hold = {"boundary_f1": round(f1, 3), "rule_hit_rate": round(hold_hits / max(1, hold_tot), 3), "labelers": 2, "videos": len(rows)}
    else:
        for name, h, n in hits:
            L.append(f"| {name} | {h}/{n} ({h / max(1, n):.0%}) |")
    L += ["", "※ 단계·역할 라벨은 해석이 들어간 값이다. 비율은 경향으로만 읽고, 개별 판정은 사람 검수 뒤 확정한다."]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    n_med = med(A["n_slides"], 1)
    n_all_med = med([len(d["_slides"]) for d in docs], 1)  # 단계 비중은 오프닝·엔딩 화면을 포함한 전체 번호 기준 → 장수 환산도 같은 기준
    tpl = {"version": "v0", "basis": {"videos": V, "slides": tot_slides, "holdout": hold},
           "deck": {"slides_median": n_med, "slides_p10_p90": [sorted(A["n_slides"])[int(V * 0.1)], sorted(A["n_slides"])[min(V - 1, int(V * 0.9))]], "stages_median": med(A["stage_n"], 1)},
           "stages": [{"stage": k, "videos_share": round(e["videos"] / V, 2), "slide_share_median": med(e["share"]), "run_length_median": med(e["len"], 1), "position_median": med(e["center"]),
                       "slides_in_deck": round(med(e["share"]) * n_all_med)} for k, e in sorted(A["st"].items(), key=lambda kv: med(kv[1]["center"])) if e["videos"] / V >= 0.2],
           "slide_roles": {k: round(v / tot_slides, 3) for k, v in A["roles"].most_common(12)},
           "source_mix": {k: round(v / tot_slides, 3) for k, v in A["src"].most_common(10)},
           "reversal": {"per_deck_median": med(A["rev_n"], 1), "first_position_median": med(A["first_rev"])},
           "korea_link": {"share": round(A["kl_present"] / V, 2), "position_median": med(A["kl_pos"])},
           "humor": {"per_deck_median": med(A["hum_n"], 1), "position_median": med(A["hum_pos"])},
           "title": {"connective_start": round(T["connective_start"], 3), "question": round(T["question"], 3), "chain_ending": round(T["chain_ending"], 3), "top_connectives": [w for w, _ in T["top_connectives"]]},
           "rules": [{"rule": name, "support": round(h / max(1, n), 2)} for name, h, n in hits]}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(tpl, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
