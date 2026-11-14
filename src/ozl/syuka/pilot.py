"""3판 시험 30편 — 표본 60편(sample_60.json)과 겹치지 않게.

- 본편 24편: 전사 3,000자 이상. 연도마다 고르게, 연도 안에서는 기존 분야 태그(video_tags_syukaworld.csv)를
  연도를 넘어 돌아가며 뽑는다('기타'와 태그 없는 영상은 뺀다 — sample.py 와 같은 규칙).
- 생방송 전체 6편: 서로 다른 연도에서 한 편씩(전사 3,000자 이상). 표본을 빼고 남은 연도가 6개보다 적으면
  (2026-11-14 기준 5개 — 2023년 생방송 2편은 모두 표본에 들었다) 남은 편이 가장 많은 해에서 한 편 더 뽑는다.
- 광고 영상: 제목에 유료 광고 포함, 협찬, '○○ x 슈카월드' 표시가 있는 본편이 있으면 2편을 본편 몫 안에서 넣는다
  (서로 다른 해에서, 그 해의 다른 본편 한 편과 바꾼다). 없으면 넣지 않는다.
- 씨앗이 같으면 결과가 같다.
"""
from __future__ import annotations

import json
import pathlib
import random
import re
from collections import defaultdict

from .catalog import ROOT
from .sample import MIN_CHARS, SKIP_CATS, UNTAGGED, quotas

SEED = 20261115
N_MAIN, N_LIVE, N_AD = 24, 6, 2
OUT = ROOT / "private" / "syuka" / "pilot30_v3.json"
AD_TITLE = re.compile(r"유료\s*광고\s*포함|협찬|[xX×]\s*슈카월드|슈카월드\s*[xX×]")
COLS = ("video_id", "kind", "upload_at", "transcript_path", "chars", "title", "stratum", "ad_title")


def is_ad_title(title: str) -> bool:
    return bool(AD_TITLE.search(title or ""))


def pick(rows: list[dict], tags: dict[str, str], exclude: set[str], seed: int = SEED,
         n_main: int = N_MAIN, n_live: int = N_LIVE, n_ad: int = N_AD) -> list[dict]:
    rng = random.Random(seed)
    pool = sorted((r for r in rows if r["has_transcript"] and r["chars"] >= MIN_CHARS and r["video_id"] not in exclude
                   and r["kind"] in ("본편", "생방송 전체")), key=lambda r: r["video_id"])
    out: list[dict] = []

    lives = defaultdict(list)
    for r in pool:
        if r["kind"] == "생방송 전체":
            lives[r["upload_at"][:4]].append(r)
    years = sorted(lives)
    for y in sorted(rng.sample(years, min(n_live, len(years)))):
        r = rng.choice(lives[y])
        lives[y].remove(r)
        out.append(r | {"stratum": f"생방송 전체/{y}"})
    # 표본을 빼고 남은 연도가 n_live 보다 적으면 남은 편이 많은 해에서 더 뽑는다(같은 해 둘째 편)
    for y in sorted(years, key=lambda y: (-len(lives[y]), y))[:max(0, n_live - len(years))]:
        if lives[y]:
            out.append(rng.choice(lives[y]) | {"stratum": f"생방송 전체/{y}/같은 해 둘째"})

    mains = defaultdict(lambda: defaultdict(list))
    for r in pool:
        c = tags.get(r["video_id"], UNTAGGED)
        if r["kind"] == "본편" and c not in SKIP_CATS and not is_ad_title(r["title"]):
            mains[r["upload_at"][:4]][c].append(r)
    for cell in (c for y in mains.values() for c in y.values()):
        rng.shuffle(cell)
    years = sorted(mains)
    cats = sorted({c for y in mains.values() for c in y})
    rng.shuffle(cats)
    q = quotas(sorted(years, key=lambda _: rng.random()), n_main,
               {y: sum(map(len, mains[y].values())) for y in years})
    picked_main = []
    cursor = 0
    for y in years:
        got = 0
        while got < q[y]:
            c = cats[cursor % len(cats)]
            cursor += 1
            if mains[y].get(c):
                picked_main.append(mains[y][c].pop() | {"stratum": f"본편/{y}/{c}"})
                got += 1

    ads = [r for r in pool if r["kind"] == "본편" and is_ad_title(r["title"])]
    by_year = defaultdict(list)
    for r in ads:
        by_year[r["upload_at"][:4]].append(r)
    ad_years = sorted(rng.sample(sorted(by_year), min(n_ad, len(by_year))))
    for y in ad_years:
        ad = rng.choice(by_year[y])
        same_year = [i for i, r in enumerate(picked_main) if r["upload_at"][:4] == y and not r.get("ad_title")]
        idx = same_year[-1] if same_year else next(i for i, r in enumerate(picked_main) if not r.get("ad_title"))
        picked_main[idx] = ad | {"stratum": f"본편/{y}/{tags.get(ad['video_id'], UNTAGGED)}/광고 표시", "ad_title": True}
    out += picked_main
    for r in out:
        r.setdefault("ad_title", False)
    return sorted(out, key=lambda r: (r["kind"], r["upload_at"]))


def write(picks: list[dict], out: pathlib.Path = OUT, seed: int = SEED) -> pathlib.Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {"seed": seed, "n": len(picks), "schema_version": 3, "rule": __doc__.strip(),
           "videos": [{k: r[k] for k in COLS} for r in picks]}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out
