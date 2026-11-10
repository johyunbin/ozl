#!/usr/bin/env python3
"""슈카월드 영상 주제 태그 — "이 채널이 이 주제를 언제 어떻게 다뤘나"를 1분 안에 찾는다.

    python -m ozl.research.videos batch --since 2024-11-10 --prefix p1     # 태깅 묶음 입력 만들기(비공개 작업 폴더)
    python -m ozl.research.videos merge                                     # 묶음 결과 검사 → 태그 파일에 병합
    python -m ozl.research.videos check [--complete]                        # 태그 파일 검사(어휘·핵심어 수·요지 길이·전사 인용)
    python -m ozl.research.videos find --category 금융·증시 --keyword 연준 --since 2024 [--q 인하] [--desc]
    python -m ozl.research.videos keywords                                  # 핵심어 빈도·표기 흔들림 후보(사전 다듬기용)
    python -m ozl.research.videos rulecheck                                 # 제목 낱말 규칙(topic_of)과 어긋난 표
    python -m ozl.research.videos sample --n 60 --since … --name eval_…     # 분야·연도 층화 표본(앞선 태그를 빼고 묶음 입력)
    python -m ozl.research.videos compare --name eval_…                     # 독립 태그와 본 태그의 분야 어긋남 표
    python -m ozl.research.videos notion-csv                                # Notion 가져오기용 CSV(비공개)
    python -m ozl.research.videos aggregate                                 # 공개 집계 문서(분야×연도 편수만)

읽는 것(전부 비공개): private/meta/catalog_syukaworld.csv · private/transcripts/trading_export/syuka/<video_id>.json(앞부분만).
쓰는 것: private/meta/video_tags_syukaworld.csv(정본) · private/meta/video_tags_work/(묶음 입출력) ·
공개는 tracks/syuka/analysis/topics_syukaworld.md 하나(편수만 — 제목·video_id 를 넣지 않는다).
태그 칸: video_id,category,category2,keywords,gist,basis,tagged_at — 분야 1개 + 보조 0~1개(cards.CATEGORIES),
핵심어 최대 4개(`|` 구분, keywords.yaml 로 표기 통일), 요지 40자 이내(자기 말 · 전사 문장을 옮기지 않는다), basis = auto|human.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

import yaml

from . import coverage
from .cards import CATEGORIES, KST

ROOT = coverage.ROOT
META = ROOT / "private" / "meta"
CATALOG = coverage.CATALOG
TRANSCRIPTS = coverage.EXPORT / "syuka"
TAGS = META / "video_tags_syukaworld.csv"
WORK = META / "video_tags_work"
NOTION_CSV = META / "notion_videos_syukaworld.csv"
KEYWORDS = pathlib.Path(__file__).with_name("keywords.yaml")
PUBLIC_DOC = ROOT / "tracks" / "syuka" / "analysis" / "topics_syukaworld.md"

COLS = ["video_id", "category", "category2", "keywords", "gist", "basis", "tagged_at"]
BASIS = ("auto", "human")
MAX_KEYWORDS = 4
GIST_MAX = 40
HEAD_CHARS = 800          # 전사 앞부분 — 태깅 근거로만 쓰고 결과에 옮기지 않는다
QUOTE_WINDOW = 15         # 요지가 전사와 이만큼(정규화 문자) 연속으로 같으면 인용으로 본다
COMMON_TAG_MIN = 300      # 이 편수 이상에 붙은 유튜브 태그는 채널 공통(변별력 없음)으로 보고 뺀다
ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


# ── 입력 ────────────────────────────────────────────────────────────────
def catalog_rows(path: pathlib.Path | None = None) -> list[dict]:
    """태깅 대상 = 영상 목록에서 쇼츠를 뺀 행(coverage.load_catalog 와 같은 거르기). 최신순."""
    with (path or CATALOG).open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("kind") != "short"]
    return sorted(rows, key=lambda r: r["published_kst"], reverse=True)


def common_tags(rows: list[dict]) -> set[str]:
    c = Counter(t for r in rows for t in (r.get("tags") or "").split("|") if t)
    return {t for t, n in c.items() if n >= COMMON_TAG_MIN} | {"yt:cc=on"}


def transcript_status(video_id: str, root: pathlib.Path | None = None) -> tuple[str, str]:
    """(본문, 상태) — 상태는 ok | missing(파일 없음 — 전사 없는 영상) | broken(파일은 있는데 못 읽음)."""
    p = (root or TRANSCRIPTS) / f"{video_id}.json"
    if not p.exists():
        return "", "missing"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("text", "") or "", "ok"
    except Exception:  # noqa: BLE001 — 깨진 전사는 상태로 알린다(인용 검사가 조용히 통과하지 않게)
        return "", "broken"


def transcript_text(video_id: str, root: pathlib.Path | None = None) -> str:
    return transcript_status(video_id, root)[0]


def _need_dir(root: pathlib.Path | None) -> None:
    if root is not None and not root.is_dir():
        raise FileNotFoundError(f"전사 폴더 없음: {root} — 인용 검사를 건너뛴 채 통과시키지 않는다")


def transcript_head(video_id: str, n: int = HEAD_CHARS, root: pathlib.Path | None = None) -> str:
    return re.sub(r"\s+", " ", transcript_text(video_id, root)).strip()[:n]


# ── 핵심어 표기 통일 ──────────────────────────────────────────────────────
def _kkey(s: str) -> str:
    return re.sub(r"\s+", "", s or "").casefold()


def load_keywords(path: pathlib.Path | None = None) -> dict[str, str]:
    """별칭(공백·대소문자 무시) → 대표 표기. 대표 표기 자신도 넣는다."""
    p = path or KEYWORDS
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    amap: dict[str, str] = {}
    for canon, aliases in (data or {}).items():
        canon = str(canon).strip()
        for a in [canon, *(aliases or [])]:
            k = _kkey(str(a))
            if k in amap and amap[k] != canon:
                raise ValueError(f"keywords.yaml: 별칭 {a!r} 가 {amap[k]!r} 와 {canon!r} 두 곳에 있다")
            amap[k] = canon
    return amap


def normalize_keyword(k: str, amap: dict[str, str]) -> str:
    k = re.sub(r"\s+", " ", (k or "").strip())
    return amap.get(_kkey(k), k)


def split_keywords(s: str) -> list[str]:
    return [k for k in (x.strip() for x in (s or "").split("|")) if k]


# ── 검사 ────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"[^\w가-힣]+", "", s or "").lower()


def quotes_transcript(gist: str, text: str, n: int = QUOTE_WINDOW) -> str:
    """요지가 전사와 n 자(정규화) 이상 연속으로 같으면 그 조각을 돌려준다."""
    g, t = _norm(gist), _norm(text)
    if len(g) < n or not t:
        return ""
    for i in range(len(g) - n + 1):
        if g[i:i + n] in t:
            return g[i:i + n]
    return ""


def validate_record(r: dict) -> list[str]:
    """한 행(태그 파일 형식 — keywords 는 `|` 문자열)의 형식 검사."""
    r = {k: (v if isinstance(v, str) else "" if v is None else str(v)) for k, v in r.items()}
    vid = r.get("video_id") or ""
    e = []
    if not ID_RE.match(vid):
        e.append(f"{vid or '?'}: video_id 형식이 아니다")
    cat, cat2 = r.get("category") or "", r.get("category2") or ""
    if cat not in CATEGORIES:
        e.append(f"{vid}: category 는 {'|'.join(CATEGORIES)} 중 하나({cat!r})")
    if cat2 and cat2 not in CATEGORIES:
        e.append(f"{vid}: category2 는 비우거나 어휘 안에서({cat2!r})")
    if cat2 and cat2 == cat:
        e.append(f"{vid}: category2 가 category 와 같다")
    kws = split_keywords(r.get("keywords") or "")
    if len(kws) > MAX_KEYWORDS:
        e.append(f"{vid}: 핵심어 {len(kws)}개 — 최대 {MAX_KEYWORDS}개")
    if len({_kkey(k) for k in kws}) != len(kws):
        e.append(f"{vid}: 핵심어가 겹친다")
    if any("," in k for k in kws):
        e.append(f"{vid}: 핵심어에 쉼표가 있다(여러 개를 한 칸에 넣었나) — `|` 로 나눈다")
    gist = (r.get("gist") or "").strip()
    if not gist:
        e.append(f"{vid}: 요지가 비었다")
    elif len(gist) > GIST_MAX:
        e.append(f"{vid}: 요지 {len(gist)}자 — {GIST_MAX}자 이내")
    if (r.get("basis") or "") not in BASIS:
        e.append(f"{vid}: basis 는 auto|human({r.get('basis')!r})")
    try:
        datetime.fromisoformat(r.get("tagged_at") or "")
    except ValueError:
        e.append(f"{vid}: tagged_at 이 ISO 시각이 아니다({r.get('tagged_at')!r})")
    return e


def read_tags(path: pathlib.Path | None = None) -> list[dict]:
    p = path or TAGS
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        if rd.fieldnames != COLS:
            raise ValueError(f"{p}: 열이 {COLS} 가 아니다({rd.fieldnames})")
        return list(rd)


def write_tags(rows: list[dict], path: pathlib.Path | None = None, order: list[str] | None = None) -> pathlib.Path:
    p = path or TAGS
    pos = {v: i for i, v in enumerate(order or [])}
    rows = sorted(rows, key=lambda r: (pos.get(r["video_id"], len(pos)), r["video_id"]))
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLS})
    tmp.replace(p)
    return p


def check_tags(rows: list[dict], catalog_ids: list[str] | None = None, complete: bool = False,
               transcripts: pathlib.Path | None = None) -> list[str]:
    """태그 파일 전체 검사. catalog_ids 를 주면 목록 밖 ID·(complete 면) 빠진 ID 도 잡는다.
    transcripts 폴더를 주면 요지가 전사를 옮겼는지도 본다."""
    _need_dir(transcripts)
    e = []
    seen = Counter(r.get("video_id") for r in rows)
    e += [f"{v}: 같은 video_id 가 {n}번" for v, n in seen.items() if n > 1]
    for r in rows:
        e += validate_record(r)
        if transcripts is not None:
            text, st = transcript_status(r["video_id"], transcripts)
            if st == "broken":
                e.append(f"{r['video_id']}: 전사 파일을 읽지 못했다 — 인용 검사를 못 했다")
            q = quotes_transcript(r.get("gist") or "", text)
            if q:
                e.append(f"{r['video_id']}: 요지가 전사를 옮겼다({len(q)}자 연속 일치)")
    if catalog_ids is not None:
        ids = set(catalog_ids)
        e += [f"{v}: 영상 목록(쇼츠 제외)에 없는 ID" for v in seen if v not in ids]
        if complete:
            miss = [v for v in catalog_ids if v not in seen]
            if miss:
                e.append(f"태그 없는 영상 {len(miss)}편(예: {miss[:3]})")
    return e


# ── 묶음 입력·결과 병합 ───────────────────────────────────────────────────
def batch_block(i: int, r: dict, common: set[str], root: pathlib.Path | None = None) -> str:
    tags = [t for t in (r.get("tags") or "").split("|") if t and t not in common]
    head = transcript_head(r["video_id"], root=root)
    kind = "생방송" if r.get("kind") == "live" else "일반"
    mins = round(int(r.get("duration_sec") or 0) / 60)
    return "\n".join([
        f"### {i}. {r['video_id']}",
        f"- 게시: {r['published_kst'][:10]} · 길이 {mins}분 · 형식 {kind}",
        f"- 제목: {r['title']}",
        f"- 유튜브 태그(채널 공통 제외): {', '.join(tags[:15]) if tags else '(없음)'}",
        f"- 전사 앞부분: {head if head else '(전사 없음 — 제목·태그로만 판단하고 note 에 title_only 라고 적는다)'}",
        "",
    ])


def make_batches(rows: list[dict], prefix: str, size: int = 60, outdir: pathlib.Path | None = None,
                 common: set[str] | None = None, root: pathlib.Path | None = None) -> list[pathlib.Path]:
    """rows 를 size 편 안팎의 묶음으로 고르게 나눠 in/<prefix>_NNN.md 로 쓰고 manifest.json 에 ID 를 적는다."""
    out = (outdir or WORK)
    (out / "in").mkdir(parents=True, exist_ok=True)
    (out / "out").mkdir(parents=True, exist_ok=True)
    common = common_tags(rows) if common is None else common
    nb = max(1, -(-len(rows) // size))
    chunks = [rows[k::nb] for k in range(nb)]  # 번갈아 나눠 묶음마다 시기가 고르게 섞이게
    man_p = out / "manifest.json"
    manifest = json.loads(man_p.read_text(encoding="utf-8")) if man_p.exists() else {}
    paths = []
    for k, ch in enumerate(chunks, 1):
        name = f"{prefix}_{k:03d}"
        ch = sorted(ch, key=lambda r: r["published_kst"])
        body = [f"# 태깅 묶음 {name} — {len(ch)}편", ""] + [batch_block(i, r, common, root) for i, r in enumerate(ch, 1)]
        p = out / "in" / f"{name}.md"
        p.write_text("\n".join(body), encoding="utf-8")
        manifest[name] = [r["video_id"] for r in ch]
        paths.append(p)
    man_p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return paths


def read_out(p: pathlib.Path) -> list[dict]:
    recs = []
    for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError as ex:
            raise ValueError(f"{p.name}:{ln}: JSON 이 아니다 ({ex})") from ex
    return recs


def to_row(rec: dict, amap: dict[str, str], basis: str = "auto", tagged_at: str | None = None) -> dict:
    if not isinstance(rec, dict):
        raise ValueError(f"행이 객체가 아니다({type(rec).__name__})")
    for f in ("video_id", "category", "category2", "gist"):
        if rec.get(f) is not None and not isinstance(rec.get(f), str):
            raise ValueError(f"{rec.get('video_id')}: {f} 가 문자열이 아니다")
    kws = rec.get("keywords") or []
    if isinstance(kws, str):
        kws = split_keywords(kws)
    if not isinstance(kws, list) or not all(isinstance(k, str) for k in kws):
        raise ValueError(f"{rec.get('video_id')}: keywords 는 문자열 목록")
    norm, seen = [], set()
    for k in kws:
        k = normalize_keyword(str(k).replace("|", " "), amap)
        if k and _kkey(k) not in seen:
            seen.add(_kkey(k))
            norm.append(k)
    return {"video_id": (rec.get("video_id") or "").strip(), "category": (rec.get("category") or "").strip(),
            "category2": (rec.get("category2") or "").strip(), "keywords": "|".join(norm),
            "gist": re.sub(r"\s+", " ", rec.get("gist") or "").strip(), "basis": basis, "tagged_at": tagged_at or now_kst()}


def unify_spacing(rows: list[dict], amap: dict[str, str]) -> int:
    """공백·대소문자만 다른 핵심어 표기를 하나로 — 사전 대표 표기가 있으면 그것, 없으면 가장 많이 쓴 표기(같으면 사전순 앞)."""
    canon = set(amap.values())
    c = Counter(k for r in rows for k in split_keywords(r["keywords"]))
    groups = defaultdict(list)
    for k in c:
        groups[_kkey(k)].append(k)
    pick = {}
    for forms in groups.values():
        if len(forms) < 2:
            continue
        best = sorted(forms, key=lambda f: (f not in canon, -c[f], f))[0]
        pick.update({f: best for f in forms if f != best})
    changed = 0
    for r in rows:
        if r.get("basis") == "human":  # 사람이 확인한 행은 고치지 않는다(빈도 계산에는 넣는다)
            continue
        kws = split_keywords(r["keywords"])
        new = list(dict.fromkeys(pick.get(k, k) for k in kws))
        if new != kws:
            r["keywords"] = "|".join(new)
            changed += 1
    return changed


def merge(work: pathlib.Path | None = None, tags_path: pathlib.Path | None = None, catalog: list[dict] | None = None,
          amap: dict[str, str] | None = None, transcripts: pathlib.Path | None = None, names: list[str] | None = None,
          dry_run: bool = False) -> dict:
    """out/<묶음>.jsonl 을 검사해 태그 파일에 병합한다. 사람이 확인한 행(basis=human)은 덮어쓰지 않는다.
    묶음 하나라도 빠진 편·형식 오류가 있으면 그 묶음 전체를 넣지 않고 사유를 돌려준다(부분 병합으로 구멍이 조용히 남지 않게)."""
    work = work or WORK
    amap = load_keywords() if amap is None else amap
    catalog = catalog_rows() if catalog is None else catalog
    cat_ids = [r["video_id"] for r in catalog]
    _need_dir(transcripts)
    manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    current = read_tags(tags_path)
    dup = [v for v, n in Counter(r["video_id"] for r in current).items() if n > 1]
    if dup:
        raise ValueError(f"태그 파일에 같은 video_id 가 두 줄 이상: {dup[:5]} — 먼저 정리한다(사람 확인 행이 사라질 수 있다)")
    existing = {r["video_id"]: r for r in current}
    report = {"merged": [], "rejected": {}, "missing_out": [], "kept_human": 0,
              "unknown_names": [n for n in (names or []) if n not in manifest]}
    for name, ids in sorted(manifest.items()):
        if names and name not in names:
            continue
        p = work / "out" / f"{name}.jsonl"
        if not p.exists():
            report["missing_out"].append(name)
            continue
        try:
            recs = read_out(p)
        except ValueError as ex:
            report["rejected"][name] = [str(ex)]
            continue
        try:
            rows = [to_row(x, amap) for x in recs]
        except (ValueError, TypeError, AttributeError) as ex:
            report["rejected"][name] = [f"형식 오류: {ex}"]
            continue
        errs = []
        for r in rows:
            errs += validate_record(r)
            if r["video_id"] not in ids:
                errs.append(f"{r['video_id']}: 이 묶음의 영상이 아니다")
            if transcripts is not None:
                text, st = transcript_status(r["video_id"], transcripts)
                if st == "broken":
                    errs.append(f"{r['video_id']}: 전사 파일을 읽지 못했다 — 인용 검사를 못 했다")
                if quotes_transcript(r["gist"], text):
                    errs.append(f"{r['video_id']}: 요지가 전사를 옮겼다")
        got = Counter(r["video_id"] for r in rows)
        errs += [f"{v}: 두 번 나온다" for v, n in got.items() if n > 1]
        miss = [v for v in ids if v not in got]
        if miss:
            errs.append(f"빠진 편 {len(miss)}개(예: {miss[:3]})")
        if errs:
            report["rejected"][name] = errs
            continue
        for r in rows:
            if existing.get(r["video_id"], {}).get("basis") == "human":
                report["kept_human"] += 1
                continue
            existing[r["video_id"]] = r
        report["merged"].append(name)
    report["unified"] = unify_spacing(list(existing.values()), amap)
    if not dry_run:
        write_tags(list(existing.values()), tags_path, order=cat_ids)
    report["total"] = len(existing)
    return report


# ── 찾기 ────────────────────────────────────────────────────────────────
def _period(s: str | None, end: bool = False) -> str | None:
    if not s:
        return None
    s = s.strip()
    if re.fullmatch(r"\d{4}", s):
        return s + ("-12-31" if end else "-01-01")
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return s + ("-31" if end else "-01")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    raise ValueError(f"기간은 YYYY · YYYY-MM · YYYY-MM-DD ({s!r})")


def keyword_forms(k: str, amap: dict[str, str]) -> set[str]:
    """찾는 낱말의 모든 표기(대표 표기 + 별칭, 공백·대소문자 무시) — 제목·요지에 별칭으로 쓰인 영상도 잡으려고."""
    canon = normalize_keyword(k, amap)
    forms = {_kkey(canon), _kkey(k)} | {a for a, c in amap.items() if c == canon}
    return {f for f in forms if f}


def _match(forms: set[str], r: dict) -> tuple[int | None, int | None, bool, bool]:
    """(핵심어 정확 일치 자리, 핵심어 부분 일치 자리, 제목에 있음, 요지에 있음)."""
    kws = [_kkey(k) for k in split_keywords(r.get("keywords") or "")]
    exact = next((i for i, k in enumerate(kws) if k in forms), None)
    sub = next((i for i, k in enumerate(kws) if any(f in k for f in forms)), None)
    t, g = _kkey(r.get("title") or ""), _kkey(r.get("gist") or "")
    return exact, sub, any(f in t for f in forms), any(f in g for f in forms)


def keyword_score(forms: set[str], r: dict) -> int:
    """핵심어 하나의 맞음 점수 — 핵심어 정확 일치 3 · 핵심어 안에 포함 2 · 제목·요지에 포함 1 · 없음 0."""
    exact, sub, in_title, in_gist = _match(forms, r)
    return 3 if exact is not None else 2 if sub is not None else 1 if (in_title or in_gist) else 0


CORE_POS = 2  # 핵심어 앞 두 자리 — 태깅 지침이 핵심어를 중요도 순으로 적게 한다


def is_core(forms: set[str], r: dict, entity: bool = True) -> bool:
    """찾는 낱말이 이 영상의 '중심'인가.
    이름(태그에 실제로 쓰인 핵심어·사전 표기)이면 — 핵심어 앞 두 자리에 **정확히** 있고 요지나 제목에도 나온다.
      (부분 일치로 '인도'에 인도네시아가, 제목의 '환율이란'에 이란이 중심으로 걸리던 것을 막는다 · 2026-11-10 검토)
    개념 낱말(태그에 그 자체로는 없는 말, 예: '출산')이면 — 요지에 나오고, 핵심어 앞 두 자리(부분 일치)나 제목에도 나온다.
    1단계 평가(2026-11-10)에서 시간순만으로는 곁가지로 언급한 영상이 위로 올라와 넣은 기준이다."""
    exact, sub, in_title, in_gist = _match(forms, r)
    if entity:
        return exact is not None and exact < CORE_POS and (in_gist or in_title)
    return in_gist and ((sub is not None and sub < CORE_POS) or in_title)


def find(category: str | None = None, keywords: list[str] | None = None, q: list[str] | None = None,
         since: str | None = None, until: str | None = None, limit: int = 40, desc: bool = False,
         catalog: list[dict] | None = None, tags: list[dict] | None = None, amap: dict[str, str] | None = None) -> dict:
    """분야(주·보조 어느 쪽이든)·핵심어(전부 맞아야 함)·낱말(제목·요지, 전부)·기간으로 거른다.
    맞은 영상을 '중심'(핵심어면 is_core, 분야만 주면 주 분야)과 '곁가지'로 나눠 중심을 먼저, 각각 시간순으로 낸다.
    결과가 limit 보다 많으면 중심·맞음 점수가 높은 것(같으면 최근)을 남긴다."""
    if category and category not in CATEGORIES:
        raise ValueError(f"분야는 {'|'.join(CATEGORIES)} 중 하나({category!r})")
    amap = load_keywords() if amap is None else amap
    cat = coverage.load_catalog() if catalog is None else catalog
    tag = {r["video_id"]: r for r in (read_tags() if tags is None else tags)}
    known = {_kkey(k) for t in tag.values() for k in split_keywords(t["keywords"])} | set(amap)
    kws = [(keyword_forms(k, amap)) for k in (keywords or []) if k.strip()]
    entity = [bool(f & known) for f in kws]
    qs = [x for x in (q or []) if x.strip()]
    lo, hi = _period(since), _period(until, end=True)
    hits = []
    for c in cat:
        t = tag.get(c["video_id"])
        if t is None:
            continue
        if lo and c["date"] < lo or hi and c["date"] > hi:
            continue
        if category and category not in (t["category"], t["category2"]):
            continue
        r = {**c, **t}
        score = 2 if category and t["category"] == category else 1 if category else 0
        ok = True
        for k in kws:
            s = keyword_score(k, r)
            if not s:
                ok = False
                break
            score += s
        for x in qs:
            if _kkey(x) not in _kkey(r.get("title", "")) and _kkey(x) not in _kkey(r.get("gist", "")):
                ok = False
                break
            score += 1
        if ok:
            core = all(is_core(k, r, e) for k, e in zip(kws, entity)) if kws else (t["category"] == category if category else True)
            hits.append({**r, "score": score, "core": core})
    total = len(hits)
    if limit and total > limit:
        hits = sorted(hits, key=lambda r: (r["core"], r["score"], r["date"]), reverse=True)[:limit]
    hits.sort(key=lambda r: r["date"], reverse=desc)
    hits.sort(key=lambda r: not r["core"])  # 안정 정렬 — 중심 먼저, 그 안에서는 시간순 유지
    return {"total": total, "shown": len(hits), "core": sum(r["core"] for r in hits), "rows": hits}


def format_row(r: dict) -> str:
    cat = r["category"] + (f"+{r['category2']}" if r.get("category2") else "")
    kw = r.get("keywords", "").replace("|", ", ")
    return f"{r['date'][:7]}  {r['title']}  https://youtu.be/{r['video_id']}\n         [{cat}] {kw} — {r.get('gist', '')}"


# ── 점검·평가 ────────────────────────────────────────────────────────────
def keyword_report(rows: list[dict], amap: dict[str, str]) -> tuple[Counter, list[tuple[str, str]]]:
    """핵심어 빈도와 표기 흔들림 후보(공백·대소문자만 다르거나, 한쪽이 다른 쪽을 품는 쌍)."""
    c = Counter(k for r in rows for k in split_keywords(r["keywords"]))
    names = [k for k, n in c.most_common()]
    pairs = []
    byk = defaultdict(list)
    for k in names:
        byk[_kkey(k)].append(k)
    pairs += [(v[0], x) for v in byk.values() if len(v) > 1 for x in v[1:]]
    top = [k for k in names if c[k] >= 2][:400]
    for a in top:
        for b in top:
            if a != b and len(_kkey(a)) >= 2 and _kkey(a) in _kkey(b) and len(_kkey(b)) - len(_kkey(a)) <= 3:
                pairs.append((a, b))
    return c, pairs


def rule_confusion(rows: list[dict], catalog: list[dict]) -> Counter:
    """제목 낱말 규칙(analyze.catalog.topic_of)과 태그 분야의 짝 — 어긋남 점검용(규칙이 정답이라는 뜻이 아니다)."""
    from ozl.analyze.catalog import topic_of
    title = {r["video_id"]: r["title"] for r in catalog}
    return Counter((topic_of({"title": title.get(r["video_id"], "")}), r["category"]) for r in rows)


def stratified_sample(rows: list[dict], catalog: list[dict], n: int = 60, seed: int = 20261110,
                      since: str | None = None, until: str | None = None, exclude: set[str] | None = None) -> list[str]:
    """분야×연도 칸마다 고르게(칸 크기를 넘지 않게 라운드로빈) n 편. exclude 의 ID(앞선 표본 등)는 뺀다."""
    year = {r["video_id"]: r["published_kst"][:4] for r in catalog}
    date = {r["video_id"]: r["published_kst"][:10] for r in catalog}
    pool = [r for r in rows if (not since or date.get(r["video_id"], "") >= since) and (not until or date.get(r["video_id"], "") <= until)
            and r["video_id"] not in (exclude or set())]
    cells = defaultdict(list)
    for r in pool:
        cells[(r["category"], year.get(r["video_id"], "?"))].append(r["video_id"])
    rng = random.Random(seed)
    for v in cells.values():
        rng.shuffle(v)
    keys = sorted(cells)
    # 분야가 고르게 먼저 — 분야마다 연도를 돌며 하나씩
    by_cat = defaultdict(list)
    for k in keys:
        by_cat[k[0]].append(k)
    out: list[str] = []
    while len(out) < n and any(cells[k] for k in keys):
        for c in CATEGORIES:
            ks = [k for k in by_cat.get(c, []) if cells[k]]
            if not ks or len(out) >= n:
                continue
            ks.sort(key=lambda k: sum(1 for v in out if year.get(v) == k[1]))  # 덜 뽑힌 연도부터
            out.append(cells[ks[0]].pop())
    return out


def confusion_table(a: dict[str, dict], b: dict[str, dict]) -> dict:
    """a = 본 태그, b = 독립 태그(같은 ID). 주 분야 일치(엄격)와 주·보조 겹침(느슨)을 같이 센다."""
    ids = [v for v in b if v in a]
    strict = sum(a[v]["category"] == b[v]["category"] for v in ids)
    loose = sum(bool({a[v]["category"], a[v]["category2"]} - {""} & {b[v]["category"], b[v]["category2"]} - {""}) for v in ids)
    mat = Counter((a[v]["category"], b[v]["category"]) for v in ids)
    per = {}
    for c in CATEGORIES:
        rows = [v for v in ids if a[v]["category"] == c]
        per[c] = (sum(b[v]["category"] == c for v in rows), len(rows))
    kw_overlap = []
    for v in ids:
        ka = {_kkey(k) for k in split_keywords(a[v]["keywords"])}
        kb = {_kkey(k) for k in split_keywords(b[v]["keywords"])}
        if ka or kb:
            kw_overlap.append(len(ka & kb) / max(1, len(ka | kb)))
    return {"n": len(ids), "strict": strict, "loose": loose, "matrix": mat, "per": per,
            "kw_jaccard": sum(kw_overlap) / len(kw_overlap) if kw_overlap else 0.0,
            "diff": [v for v in ids if a[v]["category"] != b[v]["category"]]}


# ── 내보내기 ─────────────────────────────────────────────────────────────
NOTION_COLS = ["제목", "게시일", "연도", "분야", "보조 분야", "핵심어", "한 줄 요지", "길이(분)", "형식", "링크", "video_id"]


def notion_rows(catalog: list[dict], tags: list[dict]) -> list[dict]:
    """Notion 「슈카월드 영상」 행 — 조회수·좋아요처럼 변하는 숫자는 넣지 않는다."""
    tag = {r["video_id"]: r for r in tags}
    out = []
    for c in catalog:
        t = tag.get(c["video_id"])
        if not t:
            continue
        out.append({"제목": c["title"], "게시일": c["published_kst"][:10], "연도": c["published_kst"][:4],
                    "분야": t["category"], "보조 분야": t["category2"], "핵심어": ", ".join(split_keywords(t["keywords"])),
                    "한 줄 요지": t["gist"], "길이(분)": round(int(c.get("duration_sec") or 0) / 60),
                    "형식": "생방송" if c.get("kind") == "live" else "일반", "링크": f"https://youtu.be/{c['video_id']}",
                    "video_id": c["video_id"]})
    return out


def write_notion_csv(rows: list[dict], path: pathlib.Path | None = None) -> pathlib.Path:
    p = path or NOTION_CSV
    with p.open("w", encoding="utf-8-sig", newline="") as f:  # 엑셀·Notion 이 한글을 바로 읽게 BOM
        w = csv.DictWriter(f, fieldnames=NOTION_COLS)
        w.writeheader()
        w.writerows(rows)
    return p


def notion_pages(rows: list[dict]) -> list[dict]:
    """notion_rows → Notion 커넥터(create-pages) 속성 모양. 빈 보조 분야는 넣지 않는다."""
    out = []
    for r in rows:
        props = {"제목": r["제목"], "date:게시일:start": r["게시일"], "date:게시일:is_datetime": 0, "연도": r["연도"],
                 "분야": r["분야"], "핵심어": r["핵심어"], "한 줄 요지": r["한 줄 요지"], "길이(분)": r["길이(분)"],
                 "형식": r["형식"], "링크": r["링크"], "video_id": r["video_id"]}
        if r["보조 분야"]:
            props["보조 분야"] = r["보조 분야"]
        out.append({"properties": props})
    return out


def write_notion_chunks(rows: list[dict], outdir: pathlib.Path, size: int = 100) -> list[pathlib.Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    pages = notion_pages(rows)
    paths = []
    for k in range(0, len(pages), size):
        p = outdir / f"chunk_{k // size + 1:03d}.json"
        p.write_text(json.dumps(pages[k:k + size], ensure_ascii=False), encoding="utf-8")
        paths.append(p)
    return paths


def year_table(catalog: list[dict], tags: list[dict], secondary: bool = False) -> tuple[list[str], dict]:
    year = {r["video_id"]: r["published_kst"][:4] for r in catalog}
    t = defaultdict(Counter)
    for r in tags:
        y = year.get(r["video_id"])
        if not y:
            continue
        t[r["category"]][y] += 1
        if secondary and r.get("category2"):
            t[r["category2"]][y] += 1
    years = sorted({y for c in t.values() for y in c})
    return years, t


def render_public(catalog: list[dict], tags: list[dict], today: str | None = None, agreement: str | None = None) -> str:
    """공개 집계 — 분야×연도 편수만. 제목·video_id·핵심어·요지는 넣지 않는다."""
    years, t = year_table(catalog, tags)
    _, t2 = year_table(catalog, tags, secondary=True)
    basis = Counter(r["basis"] for r in tags)
    n_target = len(catalog)

    def table(tt: dict) -> list[str]:
        out = ["| 분야 | " + " | ".join(years) + " | 합계 |", "|---|" + "---|" * (len(years) + 1)]
        for c in CATEGORIES:
            row = [tt[c][y] for y in years]
            out.append(f"| {c} | " + " | ".join(f"{v:,}" for v in row) + f" | {sum(row):,} |")
        col = [sum(tt[c][y] for c in CATEGORIES) for y in years]
        out.append("| 합계 | " + " | ".join(f"{v:,}" for v in col) + f" | {sum(col):,} |")
        return out

    lines = [
        "# 슈카월드 영상 주제 분포 (집계)",
        "",
        f"- 기준: 채널 영상 목록(쇼츠 제외) {n_target:,}편 가운데 태그가 붙은 {len(tags):,}편 · 갱신 {today or datetime.now(KST).strftime('%Y-%m-%d')}",
        f"- 태그: 영상마다 분야 1개 + 보조 분야 0~1개(카드와 같은 6종) · 근거 자동 {basis.get('auto', 0):,}편 · 사람 확인 {basis.get('human', 0):,}편",
        "- 방법: 제목·유튜브 태그·전사 앞부분을 Claude 서브에이전트가 읽고 분야를 붙였다(자동). 층화 표본을 다른 에이전트가 따로 붙여 일치율을 쟀다"
        + (f" — {agreement}." if agreement else "."),
        "- 개별 영상(제목·식별자·핵심어·요지)과 전사는 비공개다. 여기에는 편수만 싣는다.",
        "",
        "## 분야×연도 (주 분야 기준 편수)",
        "",
        *table(t),
        "",
        "## 분야×연도 (보조 분야까지 센 편수 — 한 영상이 두 칸에 들 수 있다)",
        "",
        *table(t2),
        "",
    ]
    return "\n".join(lines)


def leaks(text: str, catalog: list[dict], tags: list[dict] | None = None, window: int = QUOTE_WINDOW, min_title: int = 10) -> list[str]:
    """공개 문서에 개별 영상 정보가 들어갔으면 그 항목을 돌려준다 — video_id, 제목(정규화 window 자 창 · 짧은 제목은 min_title 자 이상 통째),
    요지(window 자 창). 핵심어는 '미국' 같은 흔한 이름이라 낱개로는 보지 않는다."""
    out = []
    nt = _norm(text)
    wins = {nt[i:i + window] for i in range(max(0, len(nt) - window + 1))}

    def hit(s: str) -> bool:
        s = _norm(s)
        if len(s) >= window:
            return any(s[i:i + window] in wins for i in range(len(s) - window + 1))
        return len(s) >= min_title and s in nt

    for r in catalog:
        if r["video_id"] in text:
            out.append(f"video_id {r['video_id']}")
        if hit(r.get("title") or ""):
            out.append(f"제목 {r['video_id']}")
    for r in tags or []:
        if hit(r.get("gist") or ""):
            out.append(f"요지 {r['video_id']}")
    return out


# ── 명령줄 ───────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    ap = argparse.ArgumentParser(prog=f"ozl.research.videos {cmd}")
    if cmd == "batch":
        ap.add_argument("--since")
        ap.add_argument("--until")
        ap.add_argument("--prefix", required=True)
        ap.add_argument("--size", type=int, default=60)
        ap.add_argument("--untagged", action="store_true", help="태그 파일에 없는 편만")
        a = ap.parse_args(rest)
        cat = catalog_rows()
        common = common_tags(cat)
        done = {r["video_id"] for r in read_tags()} if a.untagged else set()
        rows = [r for r in cat if (not a.since or r["published_kst"][:10] >= a.since) and (not a.until or r["published_kst"][:10] <= a.until)
                and r["video_id"] not in done]
        paths = make_batches(rows, a.prefix, a.size, common=common)
        print(f"{len(rows)}편 → 묶음 {len(paths)}개 ({paths[0].name} … {paths[-1].name}) · {WORK}")
        return 0
    if cmd == "merge":
        ap.add_argument("--names", nargs="*")
        ap.add_argument("--dry-run", action="store_true", help="검사만 하고 태그 파일은 쓰지 않는다(묶음 작업자용)")
        a = ap.parse_args(rest)
        rep = merge(names=a.names, transcripts=TRANSCRIPTS, dry_run=a.dry_run)
        print(("[검사만] " if a.dry_run else "") + f"병합 {len(rep['merged'])}묶음 · 태그 파일 {rep['total']}행 · 사람 확인 유지 {rep['kept_human']}")
        if rep["missing_out"]:
            print(f"결과 없는 묶음: {', '.join(rep['missing_out'])}")
        if rep["unknown_names"]:
            print(f"⚠️ 목록에 없는 묶음 이름: {', '.join(rep['unknown_names'])}")
        for name, errs in rep["rejected"].items():
            print(f"⚠️ {name} 거부: " + " / ".join(errs[:6]) + (f" … 외 {len(errs) - 6}" if len(errs) > 6 else ""))
        return 1 if rep["rejected"] or rep["unknown_names"] or (a.names and rep["missing_out"]) else 0
    if cmd == "check":
        ap.add_argument("--complete", action="store_true")
        ap.add_argument("--no-quote", action="store_true", help="전사 인용 검사 생략")
        a = ap.parse_args(rest)
        cat = catalog_rows()
        rows = read_tags()
        errs = check_tags(rows, [r["video_id"] for r in cat], a.complete, None if a.no_quote else TRANSCRIPTS)
        print(f"태그 {len(rows)}행 / 대상 {len(cat)}편 · 오류 {len(errs)}")
        for x in errs[:40]:
            print(f"- {x}")
        return 1 if errs else 0
    if cmd == "find":
        ap.add_argument("--category", "--분야")
        ap.add_argument("--keyword", "--핵심어", action="append")
        ap.add_argument("--q", action="append", help="제목·요지에 든 낱말(여러 번 = 전부)")
        ap.add_argument("--since")
        ap.add_argument("--until")
        ap.add_argument("--limit", type=int, default=40)
        ap.add_argument("--desc", action="store_true", help="최신부터")
        a = ap.parse_args(rest)
        res = find(a.category, a.keyword, a.q, a.since, a.until, a.limit, a.desc)
        cond = " · ".join(x for x in [a.category and f"분야 {a.category}", a.keyword and f"핵심어 {a.keyword}", a.q and f"낱말 {a.q}",
                                       (a.since or a.until) and f"기간 {a.since or '…'}~{a.until or '…'}"] if x)
        print(f"{cond or '조건 없음'} → {res['total']}편 · 중심 {res['core']}편" + (f" (상위 {res['shown']}편만 표시)" if res["shown"] < res["total"] else ""))
        side = False
        for r in res["rows"]:
            if not r["core"] and not side:
                side = True
                print(f"── 곁가지(핵심어 뒷자리·보조 분야로만 맞음) {res['shown'] - res['core']}편 ──")
            print(format_row(r))
        return 0
    if cmd == "keywords":
        ap.add_argument("--top", type=int, default=80)
        a = ap.parse_args(rest)
        c, pairs = keyword_report(read_tags(), load_keywords())
        print(f"핵심어 {len(c)}종 · 상위 {a.top}: " + ", ".join(f"{k}({n})" for k, n in c.most_common(a.top)))
        print(f"표기 흔들림 후보 {len(pairs)}쌍:")
        for x, y in pairs[:200]:
            print(f"- {x}({c[x]}) ~ {y}({c[y]})")
        return 0
    if cmd == "rulecheck":
        mat = rule_confusion(read_tags(), catalog_rows())
        n = sum(mat.values())
        same = sum(v for (r, t), v in mat.items() if r == t)
        print(f"제목 규칙과 같은 분야 {same}/{n} ({same / max(1, n):.0%}) — 규칙은 낱말 세기라 '기타'가 많다. 어긋난 짝 상위:")
        for (r, t), v in mat.most_common():
            if r != t:
                print(f"- 규칙 {r} → 태그 {t}: {v}")
        return 0
    if cmd == "sample":
        ap.add_argument("--n", type=int, default=60)
        ap.add_argument("--since")
        ap.add_argument("--until")
        ap.add_argument("--name", required=True)
        ap.add_argument("--seed", type=int, default=20261110)
        ap.add_argument("--exclude", nargs="*", default=[], help="앞선 표본 이름(eval/<이름>/ids.json) — 그 편은 뺀다")
        a = ap.parse_args(rest)
        cat = catalog_rows()
        excl = {v for nm in a.exclude for v in json.loads((WORK / "eval" / nm / "ids.json").read_text(encoding="utf-8"))}
        ids = stratified_sample(read_tags(), cat, a.n, a.seed, a.since, a.until, excl)
        by = {r["video_id"]: r for r in cat}
        d = WORK / "eval" / a.name
        d.mkdir(parents=True, exist_ok=True)
        common = common_tags(cat)
        rows = sorted((by[v] for v in ids), key=lambda r: r["published_kst"])
        (d / "in.md").write_text("\n".join([f"# 독립 태깅 표본 {a.name} — {len(rows)}편", ""] +
                                           [batch_block(i, r, common) for i, r in enumerate(rows, 1)]), encoding="utf-8")
        (d / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
        print(f"표본 {len(ids)}편 → {d / 'in.md'}")
        return 0
    if cmd == "compare":
        ap.add_argument("--name", required=True)
        a = ap.parse_args(rest)
        d = WORK / "eval" / a.name
        amap = load_keywords()
        b = {r["video_id"]: r for r in (to_row(x, amap) for x in read_out(d / "out.jsonl"))}
        main_tags = {r["video_id"]: r for r in read_tags()}
        ids = json.loads((d / "ids.json").read_text(encoding="utf-8"))
        miss = [v for v in ids if v not in b]
        res = confusion_table(main_tags, {v: b[v] for v in ids if v in b})
        print(f"표본 {res['n']}편(빠짐 {len(miss)}) · 주 분야 일치 {res['strict']}/{res['n']} ({res['strict'] / max(1, res['n']):.1%})"
              f" · 주·보조 겹침 {res['loose']}/{res['n']} · 핵심어 자카드 평균 {res['kw_jaccard']:.2f}")
        for c, (ok, n) in res["per"].items():
            print(f"- {c}: {ok}/{n}")
        print("어긋난 짝(본 → 독립):")
        for (x, y), v in res["matrix"].most_common():
            if x != y:
                print(f"- {x} → {y}: {v}")
        (d / "compare.json").write_text(json.dumps({**res, "matrix": [[x, y, v] for (x, y), v in res["matrix"].items()],
                                                    "missing": miss}, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    if cmd == "notion-csv":
        ap.add_argument("--chunks", help="커넥터로 나눠 넣을 때 쓸 100행 JSON 묶음 폴더")
        ap.add_argument("--only", help="video_id 목록 파일(한 줄 1개) — 이 편만 내보낸다")
        a = ap.parse_args(rest)
        rows = notion_rows(catalog_rows(), read_tags())
        if a.only:
            keep = {x.strip() for x in pathlib.Path(a.only).read_text(encoding="utf-8").split() if x.strip()}
            rows = [r for r in rows if r["video_id"] in keep]
        p = write_notion_csv(rows)
        print(f"Notion CSV {len(rows)}행 → {p}")
        if a.chunks:
            paths = write_notion_chunks(rows, pathlib.Path(a.chunks))
            print(f"커넥터용 묶음 {len(paths)}개 → {a.chunks}")
        return 0
    if cmd == "aggregate":
        ap.add_argument("--out")
        ap.add_argument("--agreement", help="일치율 한 줄(예: 주 분야 일치 93.3%%)")
        a = ap.parse_args(rest)
        cat = catalog_rows()
        tags = read_tags()
        text = render_public(cat, tags, agreement=a.agreement)
        bad = leaks(text, cat, tags)
        if bad:
            print(f"⚠️ 공개 문서에 개별 영상 정보가 들어갔다: {bad[:5]}")
            return 1
        p = pathlib.Path(a.out) if a.out else PUBLIC_DOC
        p.write_text(text, encoding="utf-8")
        print(f"집계 → {p}")
        return 0
    print(f"모르는 명령: {cmd}\n{__doc__}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
