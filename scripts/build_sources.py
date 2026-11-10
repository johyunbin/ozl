#!/usr/bin/env python3
"""docs/sources.md 를 설정과 기록에서 뽑아 쓴다.

    python scripts/build_sources.py

매일 읽는 피드(feeds.yaml), 발표 일정 출처(calendar.yaml), 공개한 검증 기록이 인용한 기관(claims/)을 읽는다.
손으로 적지 않으므로, 이 쪽에 없는 곳은 쓰지 않는 곳이다. 피드나 일정을 고치면 다시 돌린다.
"""
from __future__ import annotations

import collections
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "src" / "ozl" / "research"
KIND = {"official": "기관 원문", "news": "언론·통신", "paper": "연구 보고서", "trend": "검색 급상승어", "community": "커뮤니티"}
ORDER = {k: i for i, k in enumerate(KIND)}


def build() -> str:
    feeds = yaml.safe_load((RES / "feeds.yaml").read_text(encoding="utf-8"))["feeds"]
    events = yaml.safe_load((RES / "calendar.yaml").read_text(encoding="utf-8"))["events"]
    on = [f for f in feeds if f.get("enabled", True)]
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

    if off:
        L += ["### 지금 꺼 둔 피드", "", "주소가 응답하지 않거나 내용이 비어 있어 꺼 둔 곳입니다. 다시 열리면 켭니다.", ""]
        L += [f"- {f['outlet']}: {f.get('note') or '응답 없음'}" for f in off] + [""]

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
