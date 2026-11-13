"""게시 승인 화면의 틀(설계 5절) — 스크립트 없음, 모든 값은 `html.escape`.

원문 대목은 근거 기록의 `observed` 를 그대로 싣는다. 공개 제외 주장도 보이되(운영자만 보는 화면) 그 사실을 표시한다.
"""
from __future__ import annotations

from html import escape as E

from . import approvals as A
from .candidates import TBD as TBD_TEXT
from .templates import form, login_link, page


def _ev(e: A.EvRow) -> str:
    if not e.found:
        return '<li class="ev"><p class="muted">근거 기록을 찾지 못했다.</p></li>'
    obs = (f'<blockquote class="obs">{E(e.observed)}</blockquote>' if e.observed
           else '<p class="muted">원문 대목이 없는 근거다(보도는 본문을 두지 않는다).</p>')
    src = ", ".join(x for x in (e.publisher, e.title) if x)
    meta = ", ".join(x for x in (e.host, f"받은 시각 {e.accessed}" if e.accessed else "") if x)
    stance = f'<span class="tag{" warn" if e.stance == "반대" else ""}">{E(e.stance or "입장 정리 전")}</span>'
    return f'<li class="ev">{stance}{obs}<p class="src">{E(src)}</p><p class="muted">{E(meta)}</p></li>'


def _claim(c: A.ClaimRow, part: bool = False) -> str:
    tags = [f'<span class="tag{" warn" if c.verdict == "사실과 다름" else ""}">{E(c.verdict or "판정 정리 전")}</span>']
    if not c.public:
        # 보류와 공개 제외를 가려 보인다. 둘 다 독자 화면에는 나가지 않는다.
        why = c.publish if c.publish in ("보류", "공개 제외") else "공개 제외"
        tags.append(f'<span class="tag">{E(why)}(운영 화면에만 보인다)</span>')
    left = [f'<p class="gist">{E(c.cid)} {E(c.gist)}</p><p>{"".join(tags)}</p>']
    if c.scope:
        left.append(f'<p>확인한 범위: {E(c.scope)}</p>')
    if c.searched:
        left.append(f'<p class="muted">찾아본 범위: {E(c.searched)}</p>')
    for u in c.uncertain:
        left.append(f'<p class="muted">{E(u)}</p>')
    if c.party:
        left.append(f'<p class="muted">당사자 입장: {E(c.party)}</p>')
    # 연결된 근거가 없는 것은 기록이 사라진 것과 다르다: 작은 주장에 달려 있거나, 확인하지 못해 연결할 근거가 없는 경우다.
    none = "근거는 아래 나눠 본 판정에 달려 있다." if c.parts else "연결한 근거가 없다."
    right = "".join(_ev(e) for e in c.evidence) or f'<li class="ev"><p class="muted">{none}</p></li>'
    sub = "".join(_claim(p, True) for p in c.parts)
    return (f'<div class="claim{" part" if part else ""}"><div class="cl">{"".join(left)}</div>'
            f'<ul class="evs">{right}</ul></div>{sub}')


def _lines(title: str, items: list[str], cls: str = "") -> str:
    if not items:
        return ""
    return f'<h3>{E(title)}</h3><ul class="plain {cls}">{"".join(f"<li>{E(x)}</li>" for x in items)}</ul>'


def _reviews(c: A.IssueCard) -> str:
    got = [f'{r["kind"]}, {r["model"]}, {r["result"]}, {r["at"]}' + ("" if r["notes_ok"] else " (검토 원문이 맞지 않아 세지 않는다)")
           for r in c.got]
    miss = [f"받지 못한 검토: {m}" for m in c.missing]
    return _lines("검토", miss + got) or '<h3>검토</h3><p class="muted">받은 검토가 없다.</p>'


def _issue(c: A.IssueCard, csrf: str | None) -> str:
    head = (f'<p class="meta"><span>{E(c.issue_id)}</span><span>{c.rev}판</span><span>{E(c.work_state)}</span></p>'
            f'<p class="flags">{"".join(f"<span class=tag>{E(w)}</span>" for w in c.flag_words()) or "<span class=muted>걸린 것 없음</span>"}</p>')
    if c.changed:
        head += f'<p class="muted">이전 승인판에서 바뀐 칸: {E(", ".join(c.changed))}</p>'
    check = _lines("점검", c.errors + c.warnings, "warnlist") or '<h3>점검</h3><p class="muted">오류와 경고가 없다.</p>'
    body = "".join(_claim(x) for x in c.claims) or f'<p class="muted">주장 {TBD_TEXT}</p>'
    act = (form("/approve", f"{c.rev}판 게시 승인", csrf, {"kind": "issue", "target": c.issue_id, "rev": str(c.rev),
                                                          "hash": c.content_hash}, "primary")
           if csrf else login_link("/approve"))
    inner = f'{head}{check}{_reviews(c)}<h3>주장과 원문 대목</h3><div class="claims">{body}</div><div class="btns">{act}</div>'
    title = f'<h2 class="ititle">{E(c.title)}</h2>'
    if c.open:
        return f'<article class="issue open">{title}{inner}</article>'
    counters = [x for x in c.claims if x.counter]
    shown = "".join(_claim(x) for x in counters)
    shown = f'<div class="claims">{shown}</div>' if shown else ""
    return (f'<article class="issue">{title}{shown}<details class="fold"><summary>펼쳐 보기({E(c.issue_id)})</summary>'
            f'{inner}</details></article>')


def _unit(u: A.UnitRow, csrf: str | None) -> str:
    msgs = [f"오류: {x}" for x in u.errors] + [f"경고: {x}" for x in u.warnings]
    lines = "".join(f"<li>{E(x)}</li>" for x in msgs) or '<li class="muted">오류와 경고가 없다.</li>'
    act = (form("/approve", f"{u.rev}판 게시 승인", csrf, {"kind": u.unit, "target": u.date, "rev": str(u.rev),
                                                          "hash": u.content_hash}, "primary")
           if csrf and isinstance(u.rev, int) else "")
    return (f'<li class="row"><p class="title">{E(u.date)} <span class="muted">{E(str(u.rev))}판, 항목 {u.n_items}개</span></p>'
            f'<ul class="plain">{lines}</ul><div class="btns">{act}</div></li>')


def approve_page(v: A.ApproveView, csrf: str | None, note: str | None = None) -> str:
    out = []
    if v.error:
        out.append("<p>발행 목록을 읽지 못했다. 저장소에서 이슈 기록 검사를 먼저 돌린다.</p>")
    if csrf is None:
        out.append(login_link("/approve"))
    out.append(f'<p class="muted">게시 대기 {len(v.issues)}건. 개인 언급, 사실과 다름, 점검에 걸린 건이 위에 온다.</p>')
    out.append("".join(_issue(c, csrf) for c in v.issues) or '<p class="muted">승인할 이슈가 없다.</p>')
    for unit, label in A.UNIT_LABEL.items():
        rows = v.units.get(unit) or []
        out.append(f"<h2>{E(label)}</h2>")
        out.append(f'<ol class="rows">{"".join(_unit(u, csrf) for u in rows)}</ol>' if rows else '<p class="muted">승인할 판이 없다.</p>')
    if v.not_ready:
        li = "".join(f"<li>{E(i)} {E(t)} <span class=\"tag\">{E(s)}</span></li>" for i, t, s in v.not_ready)
        out.append(f'<details class="fold"><summary>아직 게시 대기가 아닌 것 {len(v.not_ready)}건</summary><ul class="plain">{li}</ul></details>')
    return page("게시 승인", "".join(out), logged_in=csrf is not None, note=note)


def refused_page(code: int, lines: list[str]) -> str:
    head = {409: "판 번호나 내용이 화면을 그린 뒤 바뀌었거나, 같은 판이 다른 내용으로 이미 승인됐다. 화면을 새로 열고 다시 본다.",
            422: "검사나 검토 조건을 채우지 못해 승인하지 않았다.",
            400: "승인 요청을 받을 수 없다."}.get(code, "승인하지 않았다.")
    body = f"<p>{E(head)}</p>" + (f'<ul class="plain">{"".join(f"<li>{E(x)}</li>" for x in lines)}</ul>' if lines else "")
    return page("승인하지 않았다", body + '<p><a href="/approve">돌아가기</a></p>', note=f"상태 {code}")
