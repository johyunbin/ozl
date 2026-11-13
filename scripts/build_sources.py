#!/usr/bin/env python3
"""docs/sources.md 를 설정과 기록에서 뽑아 쓴다.

    python scripts/build_sources.py

매일 읽는 피드(feeds.yaml), 발표 일정 출처(calendar.yaml), 공개한 검증 기록이 인용한 기관(claims/)을 읽는다.
손으로 적지 않으므로, 이 쪽에 없는 곳은 쓰지 않는 곳이다. 피드나 일정을 고치면 다시 돌린다.
"""
from __future__ import annotations

import collections
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "src" / "ozl" / "research"
sys.path.insert(0, str(ROOT / "src"))
from ozl.research import ledger  # noqa: E402 — 출처 대장(수집이 허용인 피드만 "읽는 피드"로 적는다)
KIND = {"official": "기관 원문", "news": "언론·통신", "paper": "연구 보고서", "trend": "검색 급상승어", "community": "커뮤니티"}
ORDER = {k: i for i, k in enumerate(KIND)}


def build() -> str:
    feeds = yaml.safe_load((RES / "feeds.yaml").read_text(encoding="utf-8"))["feeds"]
    events = yaml.safe_load((RES / "calendar.yaml").read_text(encoding="utf-8"))["events"]
    live = [f for f in feeds if f.get("enabled", True)]
    on = [f for f in live if ledger.allowed(f["id"], "collect")]
    blocked = [f for f in live if not ledger.allowed(f["id"], "collect")]   # 켜져 있지만 출처 대장이 막아 받지 않는 곳
    off = [f for f in feeds if not f.get("enabled", True)]

    L = ["# 쓰는 소스", "",
         "이 쪽은 손으로 적지 않고 설정 파일과 검증 기록에서 뽑아 만듭니다(`scripts/build_sources.py`). 여기 없는 곳은 쓰지 않는 곳입니다.", ""]

    L += ["## 매일 읽는 피드", "",
          f"피드 {len(on)}개, 매체와 기관 {len({f['outlet'] for f in on})}곳입니다. 등급은 [검증 방법](methodology.md)의 출처 등급입니다.", "",
          "| 매체·기관 | 종류 | 등급 | 읽는 면 |", "|---|---|---|---|"]
    groups: dict[tuple, list] = collections.OrderedDict()
    for f in on:
        groups.setdefault((f["outlet"], f["kind"], f["tier"]), []).append(f.get("section") or "")
    for (outlet, kind, tier), secs in sorted(groups.items(), key=lambda x: (ORDER.get(x[0][1], 9), x[0][0])):
        secs = [s for s in dict.fromkeys(secs) if s]
        L.append(f"| {outlet} | {KIND.get(kind, kind)} | {tier} | {', '.join(secs) or '전체'} |")
    L += ["", "검색 급상승어와 커뮤니티 피드는 무엇이 화제인지 알아보는 단서로만 씁니다. 거기서 본 내용은 인용하지 않고 위 등급의 출처에서 다시 확인합니다.", ""]

    if off or blocked:
        L += ["### 지금 받지 않는 피드", "",
              "주소가 응답하지 않거나, 이용 조건을 확인한 결과 받지 않기로 한 곳입니다. 조건은 출처 대장(`src/ozl/research/sources_ledger.yaml`)에 적습니다.", ""]
        seen: dict[str, str] = collections.OrderedDict()
        for f in off:
            seen.setdefault(f["outlet"], f.get("note") or "응답 없음")
        for f in blocked:
            why = "이용 조건이 수집을 막아 받지 않습니다" if ledger.verdict(f["id"], "collect") == "금지" else "이용 조건을 확인하지 못해 받지 않습니다"
            seen.setdefault(f["outlet"], why)
        L += [f"- {o}: {why}" for o, why in seen.items()] + [""]

    L += ["## 발표 일정을 확인하는 곳", "",
          "물가, 고용, 금리 결정처럼 날짜가 정해진 발표는 기관의 일정 페이지를 직접 열어 확인한 날짜만 일정표에 적습니다.", ""]
    orgs: dict[str, str] = collections.OrderedDict()
    for e in events:
        orgs.setdefault(e["org"], e["schedule_url"])
    L += [f"- [{org}]({url})" for org, url in orgs.items()] + [""]

    cited: collections.Counter = collections.Counter()
    for p in sorted((ROOT / "claims").rglob("*.yaml")):
        src = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("source") or {}
        if src.get("publisher"):
            cited[(src["publisher"], src.get("tier", ""))] += 1
    L += ["## 공개한 카드가 인용한 곳", "",
          f"공개한 검증 기록 {sum(cited.values())}건의 출처입니다. 기록 파일에 적힌 이름 그대로 옮겼습니다.", "",
          "| 기관 | 등급 | 건수 |", "|---|---|---|"]
    L += [f"| {name} | {tier} | {n} |" for (name, tier), n in sorted(cited.items(), key=lambda x: (-x[1], x[0][0]))]
    L += ["", "예전에 이 자리에 있던 소스 조사 문서는 항목을 하나씩 확인하기 전의 초안이어서 내렸습니다.", ""]
    return "\n".join(L)


def main() -> None:
    out = ROOT / "docs" / "sources.md"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
