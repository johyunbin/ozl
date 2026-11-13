"""1단계: 하루치 사건 묶음(그룹, §4-1). 단위 = 전재 묶음의 대표 기사와 공공 원문 항목. 같은 언어·같은 날끼리만."""
from __future__ import annotations

import hashlib
from collections import defaultdict

from ozl.signals import config, text
from ozl.signals.source import order_key


def prep_unit(u: dict) -> dict:
    """묶기에 쓰는 값을 붙인다(제자리). entities·terms 는 text.analyze 결과."""
    if "_tb" not in u:
        u["norm_title"] = u.get("norm_title") or text.norm_title(u["title"])
        u["_tb"] = text.bigrams(u["norm_title"])
    u["_ents"] = frozenset(u.get("entities") or ())
    return u


def pair_values(a: dict, b: dict) -> tuple[int, float, float]:
    """(E, S, T): 넓은 이름을 뺀 고유명사 겹친 수, 제목 Dice, 발행 시각 차(시간)."""
    prep_unit(a)
    prep_unit(b)
    E = len(a["_ents"] & b["_ents"])
    S = text.dice(a["_tb"], b["_tb"])
    T = abs((a["event_at"] - b["event_at"]).total_seconds()) / 3600
    return E, S, T


def linked(E: int, S: float, T: float) -> bool:
    """연결 조건: (E≥2 ∧ S≥0.30) ∨ (E≥1 ∧ S≥0.53) ∨ (S≥0.63 ∧ T≤24). 값은 config 가 정본."""
    return ((E >= 2 and S >= config.G_E2_S) or (E >= 1 and S >= config.G_E1_S)
            or (S >= config.G_E0_S and T <= config.G_E0_T))


def family_key(u: dict) -> str:
    """프로필에서 쓰는 출처 계열. 언론은 매체 계열, 공공 원문은 '공공:매체'."""
    return u["family"] if u["kind"] == "news" else "공공:" + u["outlet"]


def group_id(day: str, seed_key: str) -> str:
    return "g" + day.replace("-", "") + "-" + hashlib.sha1(seed_key.encode()).hexdigest()[:8]


def _adjacency(units: list[dict]) -> list[set[int]]:
    """앞선 단위 가운데 연결된 것의 번호(역색인으로 S ≥ 0.30 후보만 견준다. 모든 조건이 S ≥ 0.30 을 요구하므로 결과는 같다)."""
    idx: dict[str, list[int]] = defaultdict(list)
    adj: list[set[int]] = []
    for j, u in enumerate(units):
        shared: dict[int, int] = defaultdict(int)
        for g in u["_tb"]:
            for i in idx[g]:
                shared[i] += 1
        nb = set()
        nj = len(u["_tb"])
        for i, c in shared.items():
            ni = len(units[i]["_tb"])
            if 2 * c / (ni + nj) < config.G_E2_S:
                continue
            if linked(*pair_values(units[i], u)):
                nb.add(i)
        adj.append(nb)
        for g in u["_tb"]:
            idx[g].append(j)
    return adj


def group_day(units: list[dict], day: str) -> list[dict]:
    """하루치 단위를 그룹으로. 발행 시각순(같으면 키 순)으로 보며, 씨앗과 연결되거나 구성원 둘 이상과 연결된 그룹만 후보,
    후보 가운데 연결 수가 가장 많은 그룹(같으면 먼저 생긴 그룹)에 넣는다. 언어별로 따로 묶는다."""
    out: list[dict] = []
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        if u["day"] == day:
            by_lang[u["lang"]].append(prep_unit(u))
    for lang in sorted(by_lang):
        us = sorted(by_lang[lang], key=order_key)
        adj = _adjacency(us)
        groups: list[list[int]] = []
        where: dict[int, int] = {}
        for j in range(len(us)):
            best = None
            for gi, mem in enumerate(groups):
                cnt = sum(1 for m in mem if m in adj[j])
                if mem[0] in adj[j] or cnt >= 2:
                    k = (cnt, -gi)
                    if best is None or k > best[0]:
                        best = (k, gi)
            if best is None:
                groups.append([j])
                where[j] = len(groups) - 1
            else:
                groups[best[1]].append(j)
                where[j] = best[1]
        for mem in groups:
            out.append(summarize([us[m] for m in mem], day, lang))
    out.sort(key=lambda g: (g["first_at"], g["seed"]))
    return out


def summarize(members: list[dict], day: str, lang: str) -> dict:
    """그룹 값: 구성 단위, 씨앗 제목, 매체 계열, 낱말마다 나온 계열."""
    seed = members[0]
    ent_fam: dict[str, set] = defaultdict(set)
    term_fam: dict[str, set] = defaultdict(set)
    for u in members:
        fk = family_key(u)
        for e in u.get("entities") or ():
            ent_fam[e].add(fk)
        for t in u.get("terms") or ():
            term_fam[t].add(fk)
    return {
        "group_id": group_id(day, seed["key"]), "day": day, "lang": lang, "seed": seed["key"],
        "units": [u["key"] for u in members], "copies": [],
        "families": sorted({u["family"] for u in members if u["kind"] == "news"}),
        "sources": sorted({family_key(u) for u in members}),
        "has_official": any(u["kind"] == "official" for u in members),
        "ent_fam": {e: sorted(f) for e, f in sorted(ent_fam.items())},
        "term_fam": {t: sorted(f) for t, f in sorted(term_fam.items())},
        "title": text.strip_head(seed["title"]), "first_at": config.iso_utc(seed["event_at"]),
    }
