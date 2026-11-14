"""이슈 글(읽는 층) — `<자료 루트>/issues/<이슈 번호>/article.yaml` 읽기, 빈 뼈대, 검사, 공개 자료로 옮기기.

형식과 검사 규칙의 정본은 글 형식 명세(private/plan/글형식_명세_20261114.md) 2절과 3절이다. 검증 기록(issue.yaml, evidence/)은
뒤쪽 층으로 그대로 두고, 글의 각주(본문의 `[^n]`)가 가리키는 출처(sources)는 가능하면 근거 기록 번호(evidence)로 이어진다.
글은 model.load_issue 가 issue["article"] 로 붙여 읽고(저장할 때는 떼어 낸다), 승인 지문(digest)과 고정 사본에 함께 든다.
"""
from __future__ import annotations

import copy
import re

from . import ids, model, paths
from . import style as S

FILE = "article.yaml"
STATES = ("진행 중", "일단락")
SOURCE_KINDS = ("공식", "보도")
STATUS_GROUPS = ("confirmed", "reported", "alleged", "unknown")
FIELDS = ("schema", "issue_id", "slug", "category", "state", "started", "as_of", "title", "dek", "summary", "numbers", "what", "why",
          "news", "earlier", "status", "views", "next", "sources", "figure", "related_syuka", "changes")
REQUIRED = ("title", "dek", "summary", "what", "status", "next", "sources", "as_of", "state", "category")
SOURCE_KEYS = ("n", "kind", "publisher", "title", "date", "url", "evidence")
NEWS_KEYS = ("date", "label", "items", "new", "planned")
NUMBER_KEYS = ("value", "unit", "label", "refs")
# 공개 자료에 싣지 않는 칸(출처의 근거 기록 번호는 내부 번호다)
PRIVATE_SOURCE_KEYS = ("evidence",)

INTERNAL_TERMS = ("판정", "1판", "근거 기록", "사본", "robots", "수집기", "로그인 벽", "찾아본 범위", "확인한 범위", "원문 대조",
                  "검증 대기", "에이전트", "모델")
REPEAT_WORDS = ("밝혔다", "적었다", "확인하지 못했다", "확인되지 않았다")
REPEAT_MAX = 4
TITLE_LEN = (15, 45)
SUMMARY_MAX = 120
PARA_MAX = 400
SENTENCE_MAX = 110
NEWS_MAX = 5
BODY_LEN = (1500, 2800)                     # 명세 4절 10번. 출처와 표시 글(날짜 표시, 주제, 입장 이름, 숫자 설명)을 뺀 본문,
                                            # 각주 표시를 뺀 글자 수(공백 포함). 명세가 센 방식은 적혀 있지 않다. 경고로만 본다
DUP_MIN = 8                                 # 같은 문장 검사에서 이보다 짧은 문장(정규화 뒤)은 보지 않는다('다만.' 같은 것)
TITLE_VERDICT = ("확인 못 함", "확인됨", "사실과 다름", "일부 맞음")
PARTY_WORDS = ("부인", "해명", "반박", "당사자", "입장")
DASH = re.compile(r"[—―–]")
FOOTNOTE = re.compile(r"\[\^(\d+)\]")
SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")
AS_OF = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── 읽기와 뼈대 ───────────────────────────────────────────────────────
def article_file(issue_id: str):
    return paths.issue_dir(issue_id) / FILE


def load_article(issue_id: str) -> dict | None:
    """article.yaml 을 읽는다. 없으면 None, 있는데 읽지 못하면 예외."""
    p = article_file(issue_id)
    return model.load_yaml(p) if p.is_file() else None


def skeleton(issue_id: str, slug: str, category: str, title: str, now: str) -> dict:
    """article-new 가 쓰는 빈 뼈대. now 는 'YYYY-MM-DDTHH:MM…' 또는 'YYYY-MM-DD HH:MM'."""
    as_of = now[:16].replace("T", " ")
    return {"schema": 1, "issue_id": issue_id, "slug": slug, "category": category, "state": "진행 중", "started": now[:10],
            "as_of": as_of, "title": title, "dek": "", "summary": [], "numbers": [], "what": [], "why": None, "news": [],
            "earlier": [], "status": {g: [] for g in STATUS_GROUPS}, "views": [], "next": [], "sources": [], "figure": None,
            "related_syuka": [], "changes": []}


def evidence_ids(article) -> list[str]:
    """출처가 이어진 근거 기록 번호(승인 지문과 고정 사본이 함께 담는다)."""
    if not isinstance(article, dict):
        return []
    return list(dict.fromkeys(s["evidence"] for s in _list(article.get("sources"))
                              if isinstance(s, dict) and isinstance(s.get("evidence"), str) and s["evidence"].strip()))


# ── 글 칸 순회 ────────────────────────────────────────────────────────
def _list(v) -> list:
    return v if isinstance(v, list) else []


def _s(v) -> str:
    return v if isinstance(v, str) else ""


def _dated(rows, base: str):
    for i, d in enumerate(_list(rows)):
        if isinstance(d, dict):
            yield f"{base}.{i}.label", _s(d.get("label")), "label"
            for j, t in enumerate(_list(d.get("items"))):
                yield f"{base}.{i}.items.{j}", _s(t), "para"


def texts(article: dict):
    """(칸 경로, 글, 종류) — 독자에게 보이는 글 칸 전부(출처, 그림, 슈카 영상 칸은 뺀다). 종류: title, line(요약 한 줄),
    para(문단·항목 글), head(굵은 한 마디), label(날짜 표시, 주제, 입장 이름, 숫자 설명)."""
    yield "title", _s(article.get("title")), "title"
    yield "dek", _s(article.get("dek")), "para"
    for i, t in enumerate(_list(article.get("summary"))):
        yield f"summary.{i}", _s(t), "line"
    for i, n in enumerate(_list(article.get("numbers"))):
        if isinstance(n, dict):
            yield f"numbers.{i}.label", _s(n.get("label")), "label"
    for i, p in enumerate(_list(article.get("what"))):
        yield f"what.{i}.text", _s(p.get("text")) if isinstance(p, dict) else _s(p), "para"
    why = article.get("why") if isinstance(article.get("why"), dict) else {}
    yield "why.lead", _s(why.get("lead")), "para"
    for i, p in enumerate(_list(why.get("points"))):
        if isinstance(p, dict):
            yield f"why.points.{i}.head", _s(p.get("head")), "head"
            yield f"why.points.{i}.text", _s(p.get("text")), "para"
    yield from _dated(article.get("news"), "news")
    yield from _dated(article.get("earlier"), "earlier")
    st = article.get("status") if isinstance(article.get("status"), dict) else {}
    for g in STATUS_GROUPS:
        for i, t in enumerate(_list(st.get(g))):
            yield f"status.{g}.{i}", _s(t), "para"
    for i, v in enumerate(_list(article.get("views"))):
        if isinstance(v, dict):
            yield f"views.{i}.topic", _s(v.get("topic")), "label"
            for j, s in enumerate(_list(v.get("sides"))):
                if isinstance(s, dict):
                    yield f"views.{i}.sides.{j}.who", _s(s.get("who")), "label"
                    yield f"views.{i}.sides.{j}.text", _s(s.get("text")), "para"
    for i, n in enumerate(_list(article.get("next"))):
        if isinstance(n, dict):
            yield f"next.{i}.head", _s(n.get("head")), "head"
            yield f"next.{i}.text", _s(n.get("text")), "para"
    for i, c in enumerate(_list(article.get("changes"))):
        if isinstance(c, dict):
            yield f"changes.{i}.what", _s(c.get("what")), "para"


def plain(text: str) -> str:
    """각주 표시를 뺀 글."""
    return FOOTNOTE.sub("", text or "")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(plain(text)) if s.strip()]


def body_length(article: dict) -> int:
    """출처와 표시 글을 뺀 본문의 글자 수(각주 표시를 빼고 공백은 센다)."""
    return sum(len(plain(t).strip()) for _p, t, k in texts(article) if t.strip() and k != "label")


# ── 검사 ──────────────────────────────────────────────────────────────
def check_article(article, evidences: dict | None = None, issue_id: str | None = None) -> dict:
    """{errors: [(칸 경로, 문구)], warnings: [(칸 경로, 문구)]} — 명세 3절. evidences = {근거 번호: 근거 기록}(파일이 있는 것)."""
    e: list[tuple[str, str]] = []
    w: list[tuple[str, str]] = []
    if not isinstance(article, dict):
        return {"errors": [("article", "article.yaml 맨 위가 사전이 아니다")], "warnings": []}
    evidences = evidences or {}

    # 모양(명세 2절)
    for k in sorted(set(article) - set(FIELDS), key=str):
        e.append((str(k), "정해지지 않은 칸이다"))
    if article.get("schema") != 1:
        e.append(("schema", "schema 는 1 이다"))
    if issue_id is not None and article.get("issue_id") != issue_id:
        e.append(("issue_id", f"폴더의 이슈 번호({issue_id})와 다르다({article.get('issue_id')})"))
    if ids.slug_error(article.get("slug")):
        e.append(("slug", ids.slug_error(article.get("slug"))))

    # 1. 필수 칸
    for k in REQUIRED:
        v = article.get(k)
        if v is None or (isinstance(v, (str, list, dict)) and not (v.strip() if isinstance(v, str) else v)):
            e.append((k, f"{k} 이 없다"))
    summ = article.get("summary")
    if isinstance(summ, list) and summ and (len(summ) != 3 or any(not _s(x).strip() for x in summ)):
        e.append(("summary", f"summary 는 정확히 3줄이다(지금 {len(summ)}줄)"))
    elif summ is not None and not isinstance(summ, list):
        e.append(("summary", "summary 는 목록이다"))
    what = [p for p in _list(article.get("what")) if (_s(p.get("text")) if isinstance(p, dict) else _s(p)).strip()]
    if article.get("what") and len(what) < 2:
        e.append(("what", f"what 은 2문단 이상이다(지금 {len(what)}문단)"))
    elif len(what) > 4:
        w.append(("what", f"what 은 2 ~ 4문단으로 쓴다(지금 {len(what)}문단)"))
    for i, p in enumerate(_list(article.get("what"))):
        if not isinstance(p, dict) or set(p) - {"text"}:
            e.append((f"what.{i}", "문단은 {text: …} 꼴이다"))
    st = article.get("status")
    if st is not None and not isinstance(st, dict):
        e.append(("status", "status 는 confirmed, reported, alleged, unknown 묶음의 사전이다"))
        st = {}
    st = st or {}
    for g in sorted(set(st) - set(STATUS_GROUPS), key=str):
        e.append((f"status.{g}", "정해지지 않은 묶음이다"))
    if st and not any(_list(st.get(g)) for g in STATUS_GROUPS):
        e.append(("status", "status 의 묶음이 모두 비어 있다"))
    for g in STATUS_GROUPS:
        rows = st.get(g)
        if rows is not None and not isinstance(rows, list):
            e.append((f"status.{g}", "묶음은 줄의 목록이다"))
        elif len(_list(rows)) > 4:
            w.append((f"status.{g}", f"묶음마다 1 ~ 4줄로 쓴다(지금 {len(rows)}줄)"))
    if article.get("state") is not None and article.get("state") not in STATES:
        e.append(("state", f"state 값 '{article.get('state')}'은 허용 값({', '.join(STATES)})이 아니다"))
    if _s(article.get("as_of")).strip() and not AS_OF.match(_s(article.get("as_of")).strip()):
        e.append(("as_of", "as_of 는 'YYYY-MM-DD HH:MM' 꼴이다"))
    if article.get("started") not in (None, "") and not DAY.match(_s(article.get("started"))):
        e.append(("started", "started 는 'YYYY-MM-DD' 꼴이다"))
    nx = _list(article.get("next"))
    if nx and not 2 <= len(nx) <= 4:
        w.append(("next", f"next 는 2 ~ 4개로 쓴다(지금 {len(nx)}개)"))
    if len(_list(article.get("numbers"))) > 4:
        w.append(("numbers", f"numbers 는 4개까지다(지금 {len(article['numbers'])}개)"))
    if len(_list(article.get("views"))) > 3:
        w.append(("views", f"views 는 3개까지다(지금 {len(article['views'])}개)"))
    for i, n in enumerate(_list(article.get("numbers"))):
        if not isinstance(n, dict) or set(n) - set(NUMBER_KEYS):
            e.append((f"numbers.{i}", f"숫자 항목은 {{{', '.join(NUMBER_KEYS)}}} 칸만 둔다"))
    for base in ("news", "earlier"):
        rows = _list(article.get(base))
        for i, d in enumerate(rows):
            if not isinstance(d, dict) or set(d) - set(NEWS_KEYS):
                e.append((f"{base}.{i}", f"날짜 묶음은 {{{', '.join(NEWS_KEYS)}}} 칸만 둔다"))
                continue
            if not DAY.match(_s(d.get("date"))):
                e.append((f"{base}.{i}.date", "date 는 'YYYY-MM-DD' 꼴이다"))
            if not [t for t in _list(d.get("items")) if _s(t).strip()]:
                e.append((f"{base}.{i}.items", "날짜 묶음에 항목이 없다"))
        dates = [_s(d.get("date")) for d in rows if isinstance(d, dict)]
        if dates != sorted(dates, reverse=True):
            w.append((base, "최신이 위에 오게 쓴다"))
    if sum(1 for d in _list(article.get("news")) if isinstance(d, dict) and d.get("new")) > 1:
        w.append(("news", "new: true 는 한 묶음에만 둔다"))

    # 출처
    srcs = _list(article.get("sources"))
    by_n: dict[int, dict] = {}
    order: list = []
    for i, s in enumerate(srcs):
        if not isinstance(s, dict):
            e.append((f"sources.{i}", "출처는 사전이다"))
            continue
        if set(s) - set(SOURCE_KEYS):
            e.append((f"sources.{i}", f"정해지지 않은 칸 {', '.join(sorted(map(str, set(s) - set(SOURCE_KEYS))))}"))
        n = s.get("n")
        order.append(n)
        if not (isinstance(n, int) and not isinstance(n, bool)):
            e.append((f"sources.{i}.n", "n 은 정수다"))
            continue
        if n in by_n:
            e.append((f"sources.{i}.n", f"같은 번호의 출처가 둘이다: {n}"))
        by_n[n] = s
        if s.get("kind") not in SOURCE_KINDS:
            e.append((f"sources.{i}.kind", f"kind 값 '{s.get('kind')}'은 허용 값({', '.join(SOURCE_KINDS)})이 아니다"))
        if not _s(s.get("publisher")).strip():
            e.append((f"sources.{i}.publisher", "publisher 가 없다"))
        if not re.match(r"^https?://[^/\s]+", _s(s.get("url"))):
            e.append((f"sources.{i}.url", "url 은 그 문서의 직접 주소(http, https)다"))
        # 7. 근거 기록 연결
        ev = s.get("evidence")
        if ev is not None:
            if not ids.evidence_id_ok(ev, issue_id or article.get("issue_id")):
                e.append((f"sources.{i}.evidence", f"근거 번호 꼴이 아니다: {ev}"))
            elif ev not in evidences:
                e.append((f"sources.{i}.evidence", f"근거 기록 파일이 없다: {ev}"))
    # 2. 번호가 1부터 이어지는가(적힌 순서 그대로)
    if order and order != list(range(1, len(order) + 1)):
        e.append(("sources", f"출처 번호가 1부터 차례로 이어지지 않는다({', '.join(map(str, order))})"))

    # 각주 쓰임
    used: dict[int, list[str]] = {}
    tx = list(texts(article))
    for p, t, _k in tx:
        for m in FOOTNOTE.finditer(t):
            used.setdefault(int(m.group(1)), []).append(p)
    for i, n in enumerate(_list(article.get("numbers"))):
        for r in _list(n.get("refs")) if isinstance(n, dict) else []:
            if isinstance(r, int) and not isinstance(r, bool):
                used.setdefault(r, []).append(f"numbers.{i}.refs")
            else:
                e.append((f"numbers.{i}.refs", f"refs 는 출처 번호(정수)의 목록이다: {r}"))
    for n, where in sorted(used.items()):
        if n not in by_n:
            e.append((where[0], f"각주 [^{n}] 의 출처가 sources 에 없다"))
    for n in sorted(by_n):
        if n not in used:
            e.append(("sources", f"출처 {n} 이 본문에서 한 번도 쓰이지 않았다"))

    # 3. 확인된 것, 보도로 전해진 것
    for g in ("confirmed", "reported"):
        for i, t in enumerate(_list(st.get(g))):
            ns = [int(x) for x in FOOTNOTE.findall(_s(t))]
            if not ns:
                e.append((f"status.{g}.{i}", "각주가 없다"))
            elif g == "confirmed" and not any((by_n.get(n) or {}).get("kind") == "공식" for n in ns):
                w.append((f"status.{g}.{i}", "공식 출처 각주가 없다(당사자가 인정한 사실이면 그대로 둔다)"))

    # 4. 길이
    title = plain(_s(article.get("title"))).strip()
    if title and not TITLE_LEN[0] <= len(title) <= TITLE_LEN[1]:
        e.append(("title", f"제목은 {TITLE_LEN[0]} ~ {TITLE_LEN[1]}자다(지금 {len(title)}자)"))
    for p, t, k in tx:
        n = len(plain(t).strip())
        if k == "line" and n > SUMMARY_MAX:
            e.append((p, f"요약 한 줄은 {SUMMARY_MAX}자 이하다(지금 {n}자)"))
        elif k == "para" and n > PARA_MAX:
            e.append((p, f"문단은 {PARA_MAX}자 이하다(지금 {n}자)"))
    news = _list(article.get("news"))
    if len(news) > NEWS_MAX:
        e.append(("news", f"보이는 날짜는 {NEWS_MAX}개까지다(지금 {len(news)}개) — 오래된 것은 earlier 로 내린다"))

    # 5. 내부 용어
    for p, t, _k in tx:
        for term in INTERNAL_TERMS:
            if term in t:
                e.append((p, f"내부 용어 '{term}'를 독자 글에 쓰지 않는다"))

    # 6. 같은 문장
    seen: dict[str, str] = {}
    for p, t, k in tx:
        if k == "label":
            continue
        for s in sentences(t):
            key = S.norm(s)
            if len(key) < DUP_MIN:
                continue
            if key in seen and seen[key] != p:
                e.append((p, f"같은 문장이 {seen[key]} 에도 있다: {s[:40]}"))
            elif key in seen:
                e.append((p, f"같은 문장이 한 칸에 두 번 있다: {s[:40]}"))
            else:
                seen[key] = p

    # 경고
    whole = "\n".join(plain(t) for _p, t, _k in tx)
    for word in REPEAT_WORDS:
        c = whole.count(word)
        if c > REPEAT_MAX:
            w.append(("article", f"'{word}'가 {c}번 나온다({REPEAT_MAX}번 이하로)"))
    for p, t, k in tx:
        if k == "label":
            continue
        for s in sentences(t):
            if len(s) > SENTENCE_MAX:
                w.append((p, f"한 문장이 {SENTENCE_MAX}자를 넘는다({len(s)}자): {s[:30]}…"))
    if _list(st.get("alleged")):
        party = [t for p, t, _k in tx if p.startswith(("what.", "views.", "status.alleged", "why."))]
        if not _list(article.get("views")) and not any(word in t for t in party for word in PARTY_WORDS):
            w.append(("status.alleged", "의혹이 있는데 views 나 본문에 당사자 입장이 없다"))
    for p, t, _k in tx:
        if DASH.search(t):
            w.append((p, "줄표(—)를 쓰지 않는다"))
        if S.middot_run(t):
            w.append((p, "가운뎃점으로 명사를 길게 잇지 않는다"))
        if S.EMOJI.search(t):
            w.append((p, "이모지를 쓰지 않는다"))
    if any(v in title for v in TITLE_VERDICT):
        w.append(("title", "제목에 확인 정도의 낱말을 넣지 않는다"))
    n = body_length(article)
    if n and not BODY_LEN[0] <= n <= BODY_LEN[1]:
        w.append(("article", f"본문 분량이 {BODY_LEN[0]:,} ~ {BODY_LEN[1]:,}자 밖이다(지금 {n:,}자)"))
    return {"errors": list(dict.fromkeys(e)), "warnings": list(dict.fromkeys(w))}


def issue_findings(issue: dict, evidences: dict) -> tuple[list, list]:
    """check_issue 가 부른다 — issue 에 붙은 글의 ([(칸 경로, 문구)] 오류, 경고). 글이 없으면 둘 다 빈 목록."""
    if model.ARTICLE_KEY not in issue:
        return [], []
    r = check_article(issue[model.ARTICLE_KEY], evidences, issue_id=issue.get("issue_id"))
    return [(f"article.{p}", m) for p, m in r["errors"]], [(f"article.{p}", m) for p, m in r["warnings"]]


def check_issue_article(issue_id: str) -> dict:
    """article-check 명령의 본체 — {errors: [문구], warnings: [문구], missing: bool}."""
    art = load_article(issue_id)
    if art is None:
        return {"errors": [], "warnings": [], "missing": True}
    r = check_article(art, model.load_evidences(issue_id), issue_id=issue_id)
    return {"errors": [f"{issue_id} article.{p}: {m}" for p, m in r["errors"]],
            "warnings": [f"경고 {issue_id} article.{p}: {m}" for p, m in r["warnings"]], "missing": False}


# ── 공개 자료 ─────────────────────────────────────────────────────────
def public_view(article) -> dict | None:
    """사이트 자료에 싣는 글 — 정해진 칸만, 출처의 근거 기록 번호는 뺀다. 본문의 [^n] 은 그대로 둔다."""
    if not isinstance(article, dict):
        return None
    out = {k: copy.deepcopy(article.get(k)) for k in FIELDS if k in article}
    out["sources"] = [{k: v for k, v in s.items() if k in SOURCE_KEYS and k not in PRIVATE_SOURCE_KEYS}
                      for s in _list(article.get("sources")) if isinstance(s, dict)]
    return out


def index_view(article) -> dict | None:
    """이슈 목록 자료(첫 화면)에 싣는 글의 머리 — 제목, 한 줄 설명, 분야, 상태, 시작일, 기준 시각, 새 소식 첫 줄."""
    if not isinstance(article, dict):
        return None
    new = next((d for d in _list(article.get("news")) if isinstance(d, dict) and d.get("new")), None)
    first = next((t for t in _list((new or {}).get("items")) if _s(t).strip()), None)
    return {"title": article.get("title"), "dek": article.get("dek"), "category": article.get("category"), "state": article.get("state"),
            "started": article.get("started"), "as_of": article.get("as_of"),
            "news_new": {"date": new.get("date"), "label": new.get("label"), "text": first} if new and first else None}
