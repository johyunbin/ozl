"""덱 번호 발급·검사·목록.

    python -m ozl.briefs ids --slot pm -n 3          # 새 번호(발급 대장에 적힌다 — 지운 번호도 다시 쓰지 않는다)
    python -m ozl.briefs check <덱.yaml>…            # 덱 검사(오류가 있으면 종료 코드 1)
    python -m ozl.briefs check --date 2026-11-11     # 그날 덱 전부
    python -m ozl.briefs list [--date …]             # 덱 목록(JSON) — 웹·앱 목록 화면이 쓴다

검사는 형식과 근거 연결만 본다. 판정이 옳은지, 문장이 출처를 넘지 않는지는 사람과 다른 에이전트가 원문을 열어 본다.
"""
from __future__ import annotations

import fcntl
import json
import os
import pathlib
import re
import unicodedata
from datetime import datetime
from urllib.parse import unquote, urlparse

import yaml

from ..pulse import store

BRIEFS = store.ROOT / "private" / "briefs"
LEDGER = BRIEFS / "issued_ids.json"
ID = re.compile(r"(\d{4}-\d{2}-\d{2})-(am|pm)-b(\d{2})")
TYPES = {"cover", "number", "claim", "bars", "cards", "text", "questions"}
VERDICTS = ["확인", "일부 맞음", "사실과 다름", "근거 없음", "확인 못 함"]
STATUSES = {"진행 중", "결론 남", "논란 중"}
# 커뮤니티·SNS 주소는 근거(sources)로 쓰지 못한다 — 단서(community_refs)에만
COMMUNITY_HOSTS = ("bobaedream.co.kr", "ppomppu.co.kr", "clien.net", "fmkorea.com", "ruliweb.com", "dcinside.com", "theqoo.net",
                   "instiz.net", "dogdrip.net", "pann.nate.com", "mlbpark.donga.com", "reddit.com", "x.com", "twitter.com",
                   "threads.net", "instagram.com", "facebook.com", "tiktok.com", "youtube.com", "youtu.be", "t.co", "nitter.net",
                   "namu.wiki", "signal.bz", "supple.kr", "cafe.naver.com", "blog.naver.com", "post.naver.com", "cafe.daum.net",
                   "tistory.com", "brunch.co.kr", "velog.io", "everytime.kr", "blind.com", "teamblind.com")
LIMITS = {"headline": 40, "summary": 70, "title": 60, "why": 180, "body": 220, "claim": 80}
SLIDES = (8, 14)


def issue(slot: str, date: str, n: int, ledger: pathlib.Path | None = None, root: pathlib.Path | None = None) -> list[str]:
    """새 번호 n 개. 대장과 디스크의 기존 파일을 모두 보고 그다음 번호부터. 잠금 아래에서 읽고 쓴다(동시 실행 대비)."""
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"날짜는 YYYY-MM-DD: {date!r}") from None
    if len(date) != 10 or slot not in ("am", "pm") or n < 1:
        raise ValueError("날짜 YYYY-MM-DD · 회차 am|pm · n≥1")
    ledger = ledger or LEDGER
    root = root or BRIEFS
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger.with_suffix(".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        used = set(json.loads(ledger.read_text(encoding="utf-8"))) if ledger.exists() else set()
        used |= {p.stem for p in (root / date).glob(f"{date}-{slot}-b*.yaml")} if (root / date).exists() else set()
        nums = [int(m.group(3)) for u in used if (m := ID.fullmatch(u)) and m.group(1) == date and m.group(2) == slot]
        start = max(nums, default=0) + 1
        if start + n - 1 > 99:
            raise ValueError("한 회차 번호가 99를 넘는다")
        new = [f"{date}-{slot}-b{k:02d}" for k in range(start, start + n)]
        tmp = ledger.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(sorted(used | set(new)), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, ledger)
    return new


def _norm(url: str) -> str:
    """전각·이체 문자를 보통 글자로(ｘ→x, 。→.) — 눈에는 같은 주소가 검사를 빠져나가지 않게."""
    u = unicodedata.normalize("NFKC", str(url))
    for dot in ("\u3002", "\uff61", "\uff0e"):
        u = u.replace(dot, ".")
    return u


def _host(url: str) -> str:
    try:
        h = (urlparse(_norm(url)).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    try:
        return h.encode("idna").decode("ascii") if h and not h.isascii() else h
    except UnicodeError:
        return h


def _is_comm_host(h: str) -> bool:
    return any(h == c or h.endswith("." + c) for c in COMMUNITY_HOSTS)


def url_ok(url: str) -> bool:
    """근거 주소 꼴 — http(s) 와 호스트가 있어야 한다."""
    try:
        u = urlparse(str(url))
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.hostname)


def is_community(url: str) -> bool:
    """커뮤니티·SNS·블로그·위키 주소인가. 실제 호스트, 그리고 주소 안에 명시적으로 박힌 주소(리다이렉트 ?q=https://…,
    아카이브 /web/…/https://…)의 호스트만 본다. utm_source=facebook.com 같은 단순 문자열은 보지 않는다."""
    u = _norm(url)
    if _is_comm_host(_host(u)) or ("//" not in u and _is_comm_host(_host("//" + u))):
        return True
    for inner in re.findall(r"(?:https?:)?//([^/?#&\s]+)", unquote(unquote(u)), re.I):
        if _is_comm_host(_host("//" + inner)):
            return True
    return False


def _s(x) -> str:
    return x if isinstance(x, str) else ""


def check(d, path_stem: str | None = None) -> tuple[list[str], list[str]]:
    """덱 하나 → (오류, 경고). 오류가 있으면 발행 화면에 올리지 않는다. 깨진 입력에도 예외 대신 오류를 돌려준다."""
    if not isinstance(d, dict):
        return ["덱 최상위가 사전(mapping)이 아니다"], []
    try:
        return _check(d, path_stem)
    except Exception as e:  # noqa: BLE001 — 검사기가 죽지 않게
        return [f"검사 중 예외 {type(e).__name__} — 형식이 깨졌다"], []


def _check(d: dict, path_stem: str | None) -> tuple[list[str], list[str]]:
    err, warn = [], []
    bid = d.get("brief_id", "")
    if d.get("example") and path_stem and ID.fullmatch(path_stem):
        err.append("실제 덱에 example: true 가 남아 있다(형식 예시를 복사한 흔적)")
    if not d.get("example"):
        if not ID.fullmatch(str(bid)):
            err.append(f"brief_id 꼴이 아니다: {bid!r}")
        if path_stem and path_stem != bid:
            err.append(f"파일 이름({path_stem})과 brief_id 가 다르다")
    if d.get("format") != "deck":
        err.append("format 은 deck 이어야 한다")
    if d.get("status") not in STATUSES:
        err.append(f"status 는 {sorted(STATUSES)} 중 하나: {d.get('status')!r}")
    for k in ("headline", "updated_at", "category"):
        if not d.get(k):
            err.append(f"{k} 없음")
    if not d.get("example") and not isinstance(d.get("sensitivity"), dict):
        warn.append("sensitivity 없음 — 후보 파일의 민감 표시를 덱 최상위 sensitivity: {level, reasons} 로 옮긴다(skills/ozl-news 3단계)")
    if len(str(d.get("headline", ""))) > LIMITS["headline"]:
        warn.append(f"headline 이 {LIMITS['headline']}자를 넘는다")
    summ = d.get("summary") or []
    if not isinstance(summ, list) or len(summ) != 3 or not all(isinstance(x, str) and x for x in summ):
        err.append("summary 는 글 3줄(목록)")
        summ = []
    for s in summ:
        if len(s) > LIMITS["summary"]:
            warn.append(f"summary 한 줄이 {LIMITS['summary']}자를 넘는다: {s[:20]}…")

    sources = d.get("sources") or []
    if not isinstance(sources, list) or not all(isinstance(x, dict) for x in sources):
        return err + ["sources 는 항목(사전)의 목록"], warn
    ids = [s.get("id") for s in sources]
    if len(ids) != len(set(ids)):
        err.append("sources id 가 겹친다")
    for s in sources:
        for k in ("id", "outlet", "title", "url", "opened_at"):
            if not s.get(k):
                err.append(f"출처 {s.get('id', '?')}: {k} 없음")
        if s.get("url") and not url_ok(s["url"]):
            err.append(f"출처 {s.get('id')}: 주소는 http(s):// 로 시작해야 한다")
        if is_community(s.get("url", "")):
            err.append(f"출처 {s.get('id')}: 커뮤니티·SNS 주소는 근거로 못 쓴다(community_refs 로) — {_host(s['url'])}")
    known = set(ids)

    slides = d.get("slides") or []
    if not isinstance(slides, list) or not all(isinstance(x, dict) for x in slides):
        return err + ["slides 는 장(사전)의 목록"], warn
    if not slides or slides[0].get("type") != "cover":
        err.append("첫 장은 cover")
    if not d.get("example") and not (SLIDES[0] <= len(slides) <= SLIDES[1]):
        warn.append(f"장 수 {len(slides)} — {SLIDES[0]}~{SLIDES[1]}장(약 3분)을 권한다")
    if slides and slides[-1].get("type") != "questions":
        warn.append("마지막 장은 questions(요약 없이 남은 질문)를 권한다")
    claims = 0
    for n, s in enumerate(slides, 1):
        t = s.get("type")
        where = f"{n}장({t})"
        if t not in TYPES:
            err.append(f"{where}: 모르는 유형")
            continue
        if t != "cover":
            if not _s(s.get("title")):
                err.append(f"{where}: title 없음")
            elif len(s["title"]) > LIMITS["title"]:
                warn.append(f"{where}: 제목이 {LIMITS['title']}자를 넘는다")
        for sid in s.get("sources") or []:
            if sid not in known:
                err.append(f"{where}: 출처 {sid} 가 sources 에 없다")
        for it in s.get("items") or []:
            if isinstance(it, dict):
                for sid in it.get("sources") or []:
                    if sid not in known:
                        err.append(f"{where}: 출처 {sid} 가 sources 에 없다")
        if t == "claim":
            claims += 1
            if s.get("verdict") not in VERDICTS:
                err.append(f"{where}: verdict 는 {VERDICTS} 중 하나")
            for k in ("claim", "said_by", "why"):
                if not _s(s.get(k)):
                    err.append(f"{where}: {k} 없음")
            if len(_s(s.get("why"))) > LIMITS["why"]:
                warn.append(f"{where}: 판정 이유가 {LIMITS['why']}자를 넘는다")
            if s.get("verdict") in ("확인", "일부 맞음", "사실과 다름") and not s.get("sources"):
                err.append(f"{where}: '{s.get('verdict')}' 판정에는 근거(sources)가 있어야 한다")
        elif t == "number" and not s.get("big"):
            err.append(f"{where}: big 없음")
        elif t in ("bars", "cards", "questions") and not s.get("items"):
            err.append(f"{where}: items 없음")
        elif t == "text":
            if not _s(s.get("body")):
                err.append(f"{where}: body 없음")
            elif len(s["body"]) > LIMITS["body"]:
                warn.append(f"{where}: 글이 {LIMITS['body']}자를 넘는다 — 그림 장으로 나눌 것")
        if t in ("number", "bars") and not s.get("sources"):
            err.append(f"{where}: 숫자 장에는 장의 근거(sources)가 있어야 한다")
        if t == "cards":
            for it in s.get("items") or []:
                if not (isinstance(it, dict) and (it.get("sources") or s.get("sources"))):
                    err.append(f"{where}: 숫자 카드마다 근거가 있어야 한다(카드나 장의 sources)")
                    break
    if claims == 0:
        warn.append("판정 장(claim)이 하나도 없다")
    for c in d.get("community_refs") or []:
        if not isinstance(c, dict) or not c.get("url") or not c.get("site"):
            err.append("community_refs 항목에 site·url 이 있어야 한다")
    return err, warn


def load(path: pathlib.Path):
    """YAML 읽기. 문법이 깨졌으면 None(검사에서 오류로 보고)."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return None


def decks(date: str | None = None, root: pathlib.Path | None = None) -> list[pathlib.Path]:
    root = root or BRIEFS
    pat = f"{date}/*-b*.yaml" if date else "*/*-b*.yaml"
    return sorted(p for p in root.glob(pat) if ID.fullmatch(p.stem))


def listing(date: str | None = None, root: pathlib.Path | None = None) -> list[dict]:
    """목록 화면용 요약 — 검사 오류가 없는 덱만. 최신 회차·번호순."""
    out = []
    for p in decks(date, root):
        d = load(p)
        err, _ = check(d, p.stem)
        if err:
            continue
        verdicts = [s.get("verdict") for s in d.get("slides", []) if s.get("type") == "claim"]
        out.append({"brief_id": p.stem, "headline": d["headline"], "status": d["status"], "category": d["category"],
                    "updated_at": d["updated_at"], "summary": d.get("summary", []), "n_slides": len(d.get("slides", [])),
                    "sensitivity": d.get("sensitivity"),
                    "verdicts": {v: verdicts.count(v) for v in VERDICTS if v in verdicts}})
    out.sort(key=lambda x: (x["brief_id"][:13], -int(x["brief_id"][-2:])), reverse=True)
    return out
