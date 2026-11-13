"""묶기 평가(§9-2). 정답 쌍의 어긋남과 묶음 단위 오류를 센다. 엔진 계산에는 쓰지 않는다."""
from __future__ import annotations

from collections import defaultdict


def same_issue(a: str, b: str, issue_of: dict[str, str | None], aliases: dict[str, str] | None = None) -> bool:
    """두 기사가 같은 이슈인가(별칭을 풀어서). 어느 한쪽이 이슈가 없으면 거짓."""
    def res(i):
        seen = set()
        while aliases and i in aliases and i not in seen:
            seen.add(i)
            i = aliases[i]
        return i
    ia, ib = issue_of.get(a), issue_of.get(b)
    return ia is not None and ib is not None and res(ia) == res(ib)


def pair_errors(pairs: list[dict], issue_of: dict, aliases: dict | None = None) -> dict:
    """pairs: {'id', 'a_key', 'b_key', 'same_issue'}. 잘못 합침(따로여야 하는데 합침)과 지나치게 가름(같아야 하는데 갈림)."""
    merged, split = [], []
    for p in pairs:
        got = same_issue(p["a_key"], p["b_key"], issue_of, aliases)
        if got and not p["same_issue"]:
            merged.append(p["id"])
        elif not got and p["same_issue"]:
            split.append(p["id"])
    return {"false_merge": merged, "over_split": split}


def unit_errors(labels: dict[str, str], issue_of: dict, aliases: dict | None = None) -> dict:
    """묶음 단위 오류. labels: 기사 키 → 정답 사건 라벨.
    갈림 = 라벨마다 (그 기사들이 흩어진 이슈 수 − 1)의 합. 이슈가 없는 기사는 저마다 한 묶음으로 센다.
    섞임 = 이슈마다 (든 정답 라벨 수 − 1)의 합."""
    def res(i):
        seen = set()
        while aliases and i in aliases and i not in seen:
            seen.add(i)
            i = aliases[i]
        return i
    by_label: dict[str, set] = defaultdict(set)
    by_issue: dict[str, set] = defaultdict(set)
    for k, lab in labels.items():
        iid = issue_of.get(k)
        slot = res(iid) if iid else "없음:" + k
        by_label[lab].add(slot)
        if iid:
            by_issue[slot].add(lab)
    split = sum(len(s) - 1 for s in by_label.values())
    mixed = sum(len(s) - 1 for s in by_issue.values())
    return {"split": split, "mixed": mixed,
            "split_labels": sorted(l for l, s in by_label.items() if len(s) > 1),
            "mixed_issues": sorted(i for i, s in by_issue.items() if len(s) > 1)}
