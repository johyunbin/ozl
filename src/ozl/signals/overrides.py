"""사람의 합치기·가르기 판단(§4-4). 파일 private/pulse/engine_overrides.yaml 을 읽기만 한다. at ≤ asof 인 항목만 쓴다."""
from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from datetime import datetime

import yaml

from ozl.signals import config

ACTIONS = ("merge", "split", "not_same", "end", "reopen")


@dataclass
class Overrides:
    sha: str = "없음"
    merges: list = field(default_factory=list)      # {keep, absorb: [..], at, day, reason}
    splits: list = field(default_factory=list)      # {issue, groups: set, items: set, at, day, sig, reason}
    not_same: set = field(default_factory=set)      # frozenset({a, b})
    ended: set = field(default_factory=set)         # 종료로 고정된 번호
    entries: list = field(default_factory=list)

    def resolve(self, iid: str, day: str) -> str:
        """합치기 판단을 따라간 번호. 판단 시각이 속한 날부터 absorb → keep."""
        seen = set()
        cur = iid
        while cur not in seen:
            seen.add(cur)
            nxt = None
            for m in self.merges:
                if m["day"] <= day and cur in m["absorb"]:
                    nxt = m["keep"]
            if nxt is None:
                return cur
            cur = nxt
        return cur

    def blocked_with(self, iid: str) -> set[str]:
        out = set()
        for pair in self.not_same:
            if iid in pair:
                out |= set(pair) - {iid}
        return out


def _at(v) -> datetime | None:
    if isinstance(v, datetime):
        d = v if v.tzinfo else v.replace(tzinfo=config.KST)
        return d.astimezone(config.UTC)
    d = config.parse_ts(str(v)) if v else None
    if d is not None and "+" not in str(v) and not str(v).endswith("Z"):
        d = datetime.fromisoformat(str(v)).replace(tzinfo=config.KST).astimezone(config.UTC)   # 시각은 KST 로 적는다
    return d


def load(path: pathlib.Path | str | None, asof: datetime) -> Overrides:
    """at ≤ asof 인 판단만 담은 Overrides. 파일이 없으면 빈 것."""
    p = pathlib.Path(path) if path else None
    if p is None or not p.exists():
        return Overrides()
    raw = p.read_bytes()
    doc = yaml.safe_load(raw.decode("utf-8")) or []
    ov = Overrides(sha=hashlib.sha256(raw).hexdigest()[:12])
    cut = asof.astimezone(config.UTC)
    items = []
    for e in doc:
        if not isinstance(e, dict) or e.get("action") not in ACTIONS:
            continue
        at = _at(e.get("at"))
        if at is None or at > cut:
            continue
        items.append((at, e))
    items.sort(key=lambda x: x[0])
    for at, e in items:
        day = config.kst_day(at)
        at_iso = config.iso_utc(at)
        a = e["action"]
        ov.entries.append({**e, "at": at_iso})
        if a == "merge":
            ov.merges.append({"keep": str(e["keep"]), "absorb": [str(x) for x in e.get("absorb") or []],
                              "at": at_iso, "day": day, "reason": e.get("reason", "")})
        elif a == "split":
            sig = hashlib.sha1(json.dumps({"at": at_iso, "issue": e.get("issue"), "groups": e.get("groups") or [],
                                           "items": e.get("items") or []}, sort_keys=True, ensure_ascii=False)
                               .encode()).hexdigest()
            ov.splits.append({"issue": str(e["issue"]), "groups": {str(x) for x in e.get("groups") or []},
                              "items": {str(x) for x in e.get("items") or []}, "at": at_iso, "day": day, "sig": sig,
                              "reason": e.get("reason", "")})
        elif a == "not_same":
            ids = [str(x) for x in e.get("issues") or []]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    ov.not_same.add(frozenset((ids[i], ids[j])))
        elif a == "end":
            ov.ended.add(str(e["issue"]))
        elif a == "reopen":
            ov.ended.discard(str(e["issue"]))
    return ov
