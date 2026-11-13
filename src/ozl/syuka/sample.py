"""표본 60편 — 전사가 있는 슈카월드 영상에서 연도와 분야가 고르게.

- 대상: 본편·생방송 전체, 전사 3,000자 이상(쇼츠·짧은 클립·그 밖 제외)
- 생방송 전체 12편: 전사가 있는 연도마다 고르게
- 본편 48편: 연도마다 고르게, 연도 안에서는 기존 분야 태그(private/meta/video_tags_syukaworld.csv 의 category —
  제목·태그·전사 앞부분으로 붙인 6분류)를 연도를 넘어 돌아가며 뽑아 분야 수도 고르게 한다.
  '기타'(주로 2018년 게임·잡담 방송, 채널의 3%)와 태그 없는 영상은 본편 층에서 뺀다 — 고르게 뽑으면 실제보다 몇 배 많이 든다.
- 씨앗이 같으면 결과가 같다.
"""
from __future__ import annotations

import csv
import json
import pathlib
import random
from collections import defaultdict

from .catalog import META, ROOT

SEED = 20261114
N_TOTAL, N_LIVE = 60, 12
MIN_CHARS = 3000
TAGS = META / "video_tags_syukaworld.csv"
OUT = ROOT / "private" / "syuka" / "sample_60.json"
UNTAGGED = "미분류"
SKIP_CATS = {"기타", UNTAGGED}


def load_tags(path: pathlib.Path = TAGS) -> dict[str, str]:
    if not path.exists():
        return {}
    return {r["video_id"]: r["category"] for r in csv.DictReader(path.open(encoding="utf-8"))}


def quotas(keys: list[str], n: int, avail: dict[str, int]) -> dict[str, int]:
    """n 을 keys 에 고르게 나눈다. 모자란 칸의 몫은 남는 칸에 돌린다."""
    q = {k: 0 for k in keys}
    left = min(n, sum(avail.values()))
    while left:
        open_ = [k for k in keys if q[k] < avail[k]]
        for k in open_[:left] if len(open_) > left else open_:
            q[k] += 1
            left -= 1
    return q


def pick(rows: list[dict], tags: dict[str, str], seed: int = SEED, n_total: int = N_TOTAL, n_live: int = N_LIVE) -> list[dict]:
    rng = random.Random(seed)
    pool = sorted((r for r in rows if r["has_transcript"] and r["chars"] >= MIN_CHARS
                   and r["kind"] in ("본편", "생방송 전체")), key=lambda r: r["video_id"])
    out = []

    lives = defaultdict(list)
    for r in pool:
        if r["kind"] == "생방송 전체":
            lives[r["upload_at"][:4]].append(r)
    years = sorted(lives)
    rng.shuffle(years)  # 나머지 몫이 늘 같은 해로 가지 않게
    for y, k in quotas(years, n_live, {y: len(lives[y]) for y in years}).items():
        out += [r | {"stratum": f"생방송 전체/{y}"} for r in rng.sample(lives[y], k)]

    mains = defaultdict(lambda: defaultdict(list))
    for r in pool:
        c = tags.get(r["video_id"], UNTAGGED)
        if r["kind"] == "본편" and c not in SKIP_CATS:
            mains[r["upload_at"][:4]][c].append(r)
    for cell in (c for y in mains.values() for c in y.values()):
        rng.shuffle(cell)
    years = sorted(mains)
    cats = sorted({c for y in mains.values() for c in y})
    rng.shuffle(cats)
    q = quotas(sorted(years, key=lambda _: rng.random()), n_total - len(out),
               {y: sum(map(len, mains[y].values())) for y in years})
    cursor = 0
    for y in years:
        got = 0
        while got < q[y]:
            c = cats[cursor % len(cats)]
            cursor += 1
            if mains[y].get(c):
                out.append(mains[y][c].pop() | {"stratum": f"본편/{y}/{c}"})
                got += 1
    return sorted(out, key=lambda r: (r["kind"], r["upload_at"]))


SAMPLE_COLS = ("video_id", "title", "upload_at", "kind", "duration_sec", "chars", "transcript_path", "stratum")


def write(picks: list[dict], out: pathlib.Path = OUT, seed: int = SEED) -> pathlib.Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {"seed": seed, "n": len(picks), "rule": __doc__.strip(), "videos": [{k: r[k] for k in SAMPLE_COLS} for r in picks]}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out
