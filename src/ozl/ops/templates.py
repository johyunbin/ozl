"""운영 화면의 틀 — 서버가 그리는 HTML 문자열. 모든 값은 `html.escape`. 스크립트 없음(접기는 <details>, 단추는 폼).

화면 글은 사람이 읽는 말로 쓴다. 내부 표기(등급 기호, 영문 상태값)를 내지 않는다.
"""
from __future__ import annotations

import secrets
from datetime import datetime
from html import escape as E

from . import candidates as C
from . import queue as Q
from . import store


def rid() -> str:
    return secrets.token_hex(16)


def when(s: str | None) -> str:
    if not s:
        return C.TBD
    try:
        d = store.now_kst(datetime.fromisoformat(s))
    except ValueError:
        return C.TBD
    return f"{d.month}월 {d.day}일 {d:%H:%M}"


def page(title: str, body: str, *, logged_in: bool = False, note: str | None = None) -> str:
    nav = ('<nav class="nav"><a href="/ops">운영</a><a href="/pick">고르기</a><a href="/approve">게시 승인</a>'
           '<a href="/preview/">미리보기</a>'
           + ("" if logged_in else '<a href="/login">로그인</a>') + "</nav>")
    banner = f'<p class="note" role="status">{E(note)}</p>' if note else ""
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"referrer\" content=\"same-origin\">"
            f"<title>{E(title)} | OZL</title><link rel=\"stylesheet\" href=\"/ops/static/ops.css\"></head>"
            f"<body><header class=\"top\"><p class=\"brand\">OZL 운영</p>{nav}</header>"
            f"<main>{banner}<h1>{E(title)}</h1>{body}</main></body></html>")


def hidden(name: str, value: str) -> str:
    return f'<input type="hidden" name="{E(name)}" value="{E(value)}">'


def form(action: str, label: str, csrf: str, fields: dict[str, str], cls: str = "") -> str:
    inner = "".join(hidden(k, v) for k, v in fields.items())
    return (f'<form method="post" action="{E(action)}" class="inline">{inner}{hidden("request_id", rid())}'
            f'{hidden("csrf", csrf)}<button type="submit" class="{E(cls)}">{E(label)}</button></form>')


def login_link(next_path: str) -> str:
    return f'<p class="muted"><a href="/login?next={E(next_path)}">로그인</a>하면 단추가 보인다.</p>'


# ---------- /login ----------

def login_page(pre: str, next_path: str, note: str | None = None) -> str:
    body = ('<form method="post" action="/login" class="login">'
            '<label for="tok">접속 토큰</label>'
            '<input id="tok" name="token" type="password" autocomplete="current-password" required maxlength="200">'
            f'{hidden("pre", pre)}{hidden("next", next_path)}<button type="submit">로그인</button></form>'
            '<p class="muted">토큰은 이 기기에서 <code>python -m ozl.ops token --show</code> 로 한 번 본다.</p>')
    return page("로그인", body, note=note)


# ---------- 오류 ----------

def error_page(code: int, msg: str, back: str = "/ops") -> str:
    body = f'<p>{E(msg)}</p><p><a href="{E(back)}">돌아가기</a></p>'
    return page("요청을 처리하지 못했다", body, note=f"상태 {code}")


def preview_missing(cmd: str) -> str:
    body = ("<p>미리보기가 아직 없다. 저장소에서 아래 명령으로 만든다.</p>"
            f"<pre class=\"cmd\">{E(cmd)}</pre><p><a href=\"/ops\">돌아가기</a></p>")
    return page("미리보기", body)


# ---------- /ops ----------

def ops_page(*, logged_in: bool, n_cand: int | None, n_pending: int | None, n_queue: int, has_preview: bool,
             csrf: str | None, note: str | None = None) -> str:
    def n(v):
        return C.TBD if v is None else f"{v}건"
    rows = [("로그인", "됨" if logged_in else "안 됨"), ("고를 후보", n(n_cand)), ("게시 대기", n(n_pending)),
            ("만들기 대기열", n(n_queue)), ("미리보기", "있음" if has_preview else "없음")]
    dl = "".join(f"<div><dt>{E(k)}</dt><dd>{E(v)}</dd></div>" for k, v in rows)
    links = ('<ul class="links"><li><a href="/pick">후보 고르기</a></li><li><a href="/approve">게시 승인</a></li>'
             '<li><a href="/preview/">미리보기</a></li><li><a href="/">수집 대시보드</a></li></ul>')
    tail = form("/logout", "로그아웃", csrf, {}, "quiet") if logged_in and csrf else login_link("/ops")
    return page("운영", f'<dl class="facts-grid">{dl}</dl>{links}{tail}', logged_in=logged_in, note=note)


# ---------- /pick ----------

def _buttons(r: C.Row, csrf: str | None) -> str:
    if csrf is None:
        return ""
    c = r.cand
    b = []
    if r.queued:
        b.append(f'<span class="tag">대기열에 있음({E(when(r.queued.get("pressed_at")))})</span>')
    else:
        b.append(form("/pick/make", "만들기", csrf, {"key": c.key}, "primary"))
        b.append(form("/pick/make", "슈카 덱도 만들기", csrf, {"key": c.key, "deck": "1"}))
    b.append(form("/pick/later", "내일 다시 보기", csrf, {"key": c.key}))
    b.append(form("/pick/discard", "버리기", csrf, {"key": c.key}, "quiet"))
    return f'<div class="btns">{"".join(b)}</div>'


def _board_row(r: C.Row, csrf: str | None) -> str:
    """화제 엔진 재료의 한 줄: 점수(사사오입), 상태, 매체 계열 수, 분야, 민감, 간접 포착, 대표 기사."""
    c = r.cand
    title = E(c.title) + (' <span class="tag">어제 본 값</span>' if r.stale else "")
    if c.kind == "search":
        return (f'<li class="row"><p class="meta">이슈와 묶이지 않은 급상승 검색어</p><p class="title">{title}</p>'
                f'{_buttons(r, csrf)}</li>')
    if c.sens_level in ("RED", "YELLOW"):
        title += ' <span class="tag">민감</span>'
    head = (f'<p class="meta"><span class="score">점수 {E(c.score)}</span> <span>상태 {E(c.state)}</span> '
            f'<span>{E(c.days)}</span></p>')
    facts = [c.outlets, f"분야 {c.category or C.TBD}", c.kinds]
    if c.sens_level in ("RED", "YELLOW"):
        facts.append(f"민감 {C.SENS_WORD[c.sens_level]}" + (f": {c.sens_reason}" if c.sens_reason else ""))
    if c.indirect:
        facts.append(f"간접 포착: {c.indirect}")
    if c.new_line:
        facts.append(c.new_line)
    fl = "".join(f"<li>{E(f)}</li>" for f in facts if f and f != C.TBD)
    links = ""
    if c.links:
        li = "".join(f'<li><a href="{E(x["url"])}" rel="noopener noreferrer" target="_blank">{E(x["title"])}</a>'
                     + (f' <span class="muted">{E(x["outlet"])}</span>' if x.get("outlet") else "") + "</li>"
                     for x in c.links)
        links = f'<ul class="plain">{li}</ul>'
    return (f'<li class="row">{head}<p class="title">{title}</p><ul class="facts">{fl}</ul>{links}'
            f'{_buttons(r, csrf)}</li>')


def _row(r: C.Row, csrf: str | None) -> str:
    c = r.cand
    if c.source == "board":
        return _board_row(r, csrf)
    title = E(c.title) + (' <span class="tag">어제 본 값</span>' if r.stale else "")
    head = (f'<p class="meta"><span class="score">점수 {E(c.score)}</span> <span>흐름 {E(c.state)}</span> '
            f'<span>며칠째 {E(c.days)}</span></p>')
    facts = [c.new_line, ", ".join(x for x in (c.outlets, c.kinds) if x != C.TBD) or f"매체 {C.TBD}",
             f"주장 {c.claims}", f"민감: {c.sensitive}", f"슈카 {c.syuka}"]
    if c.search_words:
        facts.append("검색 급상승: " + ", ".join(c.search_words))
    fl = "".join(f"<li>{E(f)}</li>" for f in facts)
    return f'<li class="row">{head}<p class="title">{title}</p><ul class="facts">{fl}</ul>{_buttons(r, csrf)}</li>'


def _rows(rows: list[C.Row], csrf: str | None) -> str:
    out, cur = [], None
    for r in rows:
        if r.section != cur:
            if cur is not None:
                out.append("</ol>")
            out.append(f'<h2>{E(r.section)}</h2><ol class="rows">')
            cur = r.section
        out.append(_row(r, csrf))
    if cur is not None:
        out.append("</ol>")
    return "".join(out)


def _queue(items: list[dict], csrf: str | None) -> str:
    if not items:
        return '<p class="muted">비어 있다.</p>'
    li = []
    for j in items:
        extra = " 슈카 덱도" if j.get("deck") else ""
        line = f'{E(j.get("title") or "")}{E(extra)} <span class="tag">{E(j.get("state") or "")}</span> {E(when(j.get("pressed_at")))}'
        if j.get("note"):
            line += f' <span class="muted">{E(j["note"])}</span>'
        if csrf and j.get("state") == Q.WAITING:
            line += form("/pick/cancel", "취소", csrf, {"job_id": j["job_id"]}, "quiet")
        li.append(f"<li>{line}</li>")
    return f'<ul class="plain">{"".join(li)}</ul>'


def _discarded(items: list[dict], csrf: str | None) -> str:
    if not items:
        return '<p class="muted">비어 있다.</p>'
    li = []
    for i in items:
        line = f'{E(i.get("title") or "")} <span class="muted">{E(when(i.get("at")))}</span>'
        if csrf:
            line += form("/pick/restore", "되살리기", csrf, {"key": i.get("key", "")})
        li.append(f"<li>{line}</li>")
    return f'<ul class="plain">{"".join(li)}</ul>'


def _board_head(s: C.SourceResult) -> str:
    """목록 위 한 줄: 기준 시각, 날짜가 확정 전인지, 출처 누락."""
    parts = [f"기준 시각 {when(s.asof)}"]
    if s.base_day:
        try:
            d = datetime.fromisoformat(s.base_day)
            day = f"{d.month}월 {d.day}일"
        except ValueError:
            day = s.base_day
        parts.append(f"{day} 값은 아직 확정 전(진행 중인 날)" if s.base_day_partial else f"{day} 값은 확정")
    parts.append("출처 누락: " + ", ".join(s.missing) if s.missing else "출처 누락 없음")
    return f'<p class="muted">{E(" · ".join(parts))}</p>'


def _zones(v: C.PickView, csrf: str | None) -> str:
    out = []
    for name, rows, info in v.zones:
        out.append(f"<h2>{E(name)}</h2>")
        if rows:
            out.append(f'<ol class="rows">{"".join(_row(r, csrf) for r in rows)}</ol>')
        else:
            why = info.get("empty_reason") or "지금 보일 줄이 없다"
            out.append(f'<p class="muted">{E(str(why))}</p>')
        capped = [x for x in info.get("capped") or [] if x.get("category")]
        if capped:
            txt = ", ".join(f'{x["category"]} {x.get("skipped", 0)}건' for x in capped)
            out.append(f'<p class="muted">분야 상한으로 아래 목록으로 내린 것: {E(txt)}</p>')
    return "".join(out)


def pick_page(v: C.PickView, csrf: str | None, note: str | None = None) -> str:
    s = v.src
    head = []
    if s.fallback:
        head.append(f'<p class="muted">{E(s.fallback)}</p>')
    if s.error:
        head.append("<p>수집 결과가 아직 없다.</p>")
    elif s.kind == "board":
        head.append(_board_head(s))
        if s.note:
            head.append(f'<p class="muted">{E(s.note)}</p>')
        if s.skipped:
            head.append(f'<p class="muted">이슈 번호가 없는 후보 {s.skipped}건은 목록에서 뺐다.</p>')
    else:
        head.append(f'<p class="muted">재료를 만든 시각 {E(when(s.generated_at))}</p>')
        if s.note:
            head.append(f'<p class="muted">{E(s.note)}</p>')
        if s.feeds_failed:
            head.append(f'<p class="muted">받지 못한 피드 {s.feeds_failed}곳</p>')
    body = ["".join(head)]
    if csrf is None:
        body.append(login_link("/pick"))
    if v.zones:
        body.append(_zones(v, csrf))
    body.append(_rows(v.open_rows, csrf) or '<p class="muted">지금 보일 후보가 없다.</p>')
    if v.folded:
        body.append(f'<details class="fold"><summary>나머지 {len(v.folded)}건</summary>{_rows(v.folded, csrf)}</details>')
    if v.english:
        inner = f'<ol class="rows">{"".join(_row(r, csrf) for r in v.english)}</ol>'
        body.append(f'<details class="fold"><summary>영문 이슈 {len(v.english)}건</summary>{inner}</details>')
    if csrf:
        body.append('<h2>이것도 봐 줘</h2><form method="post" action="/pick/keyword" class="kw">'
                    '<label for="kw">키워드(80자까지)</label>'
                    '<input id="kw" name="text" type="text" required maxlength="80" autocomplete="off">'
                    f'{hidden("request_id", rid())}{hidden("csrf", csrf)}<button type="submit">넣기</button></form>')
    body.append(f'<details class="fold"><summary>만들기 대기열 {len(v.queue_items)}건</summary>{_queue(v.queue_items, csrf)}</details>')
    body.append(f'<details class="fold"><summary>버린 목록 {len(v.discarded)}건</summary>{_discarded(v.discarded, csrf)}</details>')
    if v.unlinked:
        inner = f'<ol class="rows">{"".join(_row(r, csrf) for r in v.unlinked)}</ol>'
        body.append(f'<details class="fold"><summary>주제로 묶이지 않은 검색어 {len(v.unlinked)}건</summary>{inner}</details>')
    return page("후보 고르기", "".join(body), logged_in=csrf is not None, note=note)
