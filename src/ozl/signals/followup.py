"""후속 사건(f)과 새 인물·기관(e) — D 의 입력(§5-4). DB 를 모른다.

후속 사건: 날짜 d(첫날 다음부터)에 이슈에 붙은 그룹 G 가 (어제까지 이슈의 그룹 제목 전부와 Dice < 0.50) 그리고
(G 의 낱말 가운데 어제까지 이슈에 없었고 G 안에서 계열 2곳 이상에 나온 것이 1개 이상)이면 새 하위 사건.
같은 날의 새 하위 사건 그룹은 새 낱말이 겹치거나 1단계 연결 조건을 넘으면 한 단위로 합치고, 단위의 매체 계열이 3곳 이상이면 1건.
새 인물·기관: d 의 그룹 고유명사 가운데 어제까지 이슈에 없었고 그날 서로 다른 언론 계열 2곳 이상에 나온 것(공공 원문은 세지 않는다).
"""
from __future__ import annotations

from ozl.signals import cluster, config, text


def _tb(g: dict) -> frozenset:
    return text.bigrams(text.norm_title(g["title"]))


def _linked(a: dict, b: dict, arts: dict | None) -> bool:
    if not arts:
        return False
    for ka in a["units"]:
        for kb in b["units"]:
            if ka in arts and kb in arts and cluster.linked(*cluster.pair_values(arts[ka], arts[kb])):
                return True
    return False


def followups(day: str, first_day: str, groups_d: list[dict], hist: list[dict], arts: dict | None = None) -> list[dict]:
    """그날 새로 생긴 후속 사건 단위(계열 3곳 이상인 것만). hist = 어제까지 이 이슈의 그룹."""
    if day <= first_day:
        return []
    old_terms = {t for g in hist for t in g["term_fam"]}
    old_tbs = [_tb(g) for g in hist]
    cand = []
    for g in sorted(groups_d, key=lambda x: (x["first_at"], x["seed"])):
        tb = _tb(g)
        if old_tbs and max(text.dice(tb, o) for o in old_tbs) >= config.FOLLOWUP_DICE:
            continue
        new = sorted(t for t, f in g["term_fam"].items() if t not in old_terms and len(f) >= config.NEW_TERM_FAMILIES)
        if new:
            cand.append((g, set(new)))
    parent = list(range(len(cand)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            if cand[i][1] & cand[j][1] or _linked(cand[i][0], cand[j][0], arts):
                parent[find(j)] = find(i)
    units: dict[int, list] = {}
    for i in range(len(cand)):
        units.setdefault(find(i), []).append(cand[i])
    out = []
    for _, mem in sorted(units.items()):
        fams = sorted({f for g, _ in mem for f in g["families"]})
        if len(fams) >= config.FOLLOWUP_FAMILIES:
            seed = mem[0][0]
            out.append({"unit_id": seed["group_id"], "seed": seed["seed"], "title": seed["title"], "families": fams,
                        "new_terms": sorted(set().union(*(n for _, n in mem))),
                        "groups": [g["group_id"] for g, _ in mem]})
    return out


def new_entities(day: str, first_day: str, groups_d: list[dict], hist: list[dict]) -> list[dict]:
    if day <= first_day:
        return []
    old = {e for g in hist for e in g["ent_fam"]}
    fams: dict[str, set] = {}
    for g in groups_d:
        for e, f in g["ent_fam"].items():
            # 언론 계열만 센다(공공 원문은 '공공:매체'로 들어 있다 · §5-4 "대표 기사 제목")
            fams.setdefault(e, set()).update(x for x in f if not x.startswith("공공:"))
    return [{"entity": e, "families": sorted(f)} for e, f in sorted(fams.items())
            if e not in old and len(f) >= config.NEW_ENTITY_FAMILIES]
