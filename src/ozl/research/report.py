#!/usr/bin/env python3
"""일일 보고서 렌더 — 카드 YAML 에서 세 문서를 만든다.

- 전체본(비공개)  private/daily/YYYY/MM/<날짜>_<회차>.md        모든 카드 · 내부 메모 포함
- 검증 시트(비공개) private/daily/YYYY/MM/<날짜>_<회차>_검증시트.md  기록마다 원문 표기·위치·링크·등급(사람 대조 '확인' / 프로그램 대조 「원문 일치」)
- 발행본(공개)    daily/YYYY/MM/<날짜>_<회차>.md                공개 이력이 있는 회차만 — 승인된 카드는 전문, 나머지는 번호·상태만
공개 규칙의 정본은 docs/methodology.md §8 — 공개는 사용자가 승인한 카드만, 공개 이력이 없는 회차는 발행본을 쓰지 않는다(keeps_public_page).
"""
from __future__ import annotations

import json
import pathlib
import re
from collections import Counter
from datetime import datetime
from urllib.parse import quote

from . import cards as C

ROOT = C.ROOT
SITE ="https://johyunbin.github.io/ozl"
REPO = "https://github.com/johyunbin/ozl"  # 발행본은 저장소 화면과 사이트 양쪽에서 읽히므로 링크를 절대 주소로 쓴다
SLOT_KO = {"am": "아침", "pm": "저녁", "wk": "주간"}
DOW = "월화수목금토일"
_ANCHOR = re.compile(r'<a id="((?:am|pm|wk)-\d{2})"></a>')   # 발행본에 실린 카드 자리표


def paths(date: str, slot: str) -> dict[str, pathlib.Path]:
    y, m = date[:4], date[5:7]
    return {"private": ROOT / "private" / "daily" / y / m / f"{date}_{slot}.md",
            "sheet": ROOT / "private" / "daily" / y / m / f"{date}_{slot}_검증시트.md",
            "public": ROOT / "daily" / y / m / f"{date}_{slot}.md"}


def anchor(card_id: str) -> str:
    return card_id[11:]  # am-01


def page_url(card_id: str) -> str:
    return f"{SITE}/daily/{card_id[:10]}_{card_id[11:13]}/#{anchor(card_id)}"


def _stats(date: str, slot: str) -> dict | None:
    p = C.DESK / f"{date}_{slot}" / "candidates.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    red = sum(1 for c in d["clusters"] if c["sensitivity"]["level"] == "RED")
    on = [f for f in d["feeds"] if f.get("enabled") is not False]   # 출처 대장으로 끈 피드는 요청하지 않았다 — 응답 수의 분모·분자 어디에도 넣지 않는다
    ok = sum(1 for f in on if not f["error"])
    return {"feeds_ok": ok, "feeds": len(on), "feeds_off": len(d["feeds"]) - len(on), "items": d["n_items_window"], "clusters": d["n_clusters"], "red": red,
            "hours": d["window_hours"], "generated_at": d["generated_at"]}


def _off_note(st: dict) -> str:
    return f"(출처 대장으로 끈 {st['feeds_off']}곳 제외)" if st.get("feeds_off") else ""


def _claim_mark(c: dict) -> str:
    if c.get("status") == "verified":
        return C.grade_label(c)   # 사람 대조만 '확인', 기계 대조는 「원문 일치」
    if c.get("status") == "pending":
        return "검증 전"   # 「원문 일치」는 machine-verify 를 통과해야 붙는다(모델이 대조했다고 적은 것만으로는 아니다)
    return C.BADGE_KO.get(c.get("status"), "?")


def _cell(s) -> str:
    """표 칸 하나에 넣을 글. 역슬래시를 먼저 풀고 [ ] | 를 이스케이프해 링크·열이 깨지지 않게 한다. 줄바꿈은 빈칸으로 바꾼다."""
    s = re.sub(r"\s*[\r\n]+\s*", " ", "" if s is None else str(s)).strip()   # None 만 빈 글자다. 0·false 는 글자로 남긴다
    return s.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("|", "\\|")


def _parse_date(s) -> datetime | None:
    try:
        return datetime.strptime(str(s), "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _flow_table(videos: list[dict]) -> list[str]:
    """⑥ 에 relation 이 하나라도 붙은 카드만 쓰는 흐름 표. 날짜를 실제 날짜로 풀어 오름차순으로 놓고, 풀 수 없는 날짜는 맨 뒤에 적힌 그대로 둔다.
    관계가 없는 영상은 「-」로 둔다. 링크의 영상 ID 는 URL 인코딩해 칸이 쪼개지지 않게 한다."""
    L = ["", "| 때 | 영상 | 무엇을 다뤘나 | 관계 |", "|---|---|---|---|"]
    for v in sorted(videos, key=lambda v: (0, _parse_date(v.get("date"))) if _parse_date(v.get("date")) else (1, datetime.min)):
        d = _parse_date(v.get("date"))
        when = d.strftime("%Y-%m") if d else _cell(v.get("date"))
        vid = quote(str(v["video_id"]), safe="")
        L += [f"| {when} | [{_cell(v['title'])}](https://youtu.be/{vid}) | {_cell(v.get('gist'))} | {_cell(v.get('relation')) or '-'} |"]
    return L + [""]


def render_card(card: dict, claims: list[dict], n: int, public: bool) -> str:
    cid = card["card_id"]
    if public and not C.publishable(card, claims):
        raise PermissionError(f"{cid}: 발행 승인되지 않은 카드는 공개용으로 렌더하지 않는다")
    by_id = {c["claim_id"]: c for c in claims}
    sens = card["sensitivity"]
    # 제목을 "N. " 로 시작해 PDF 엔진의 자동 장 번호와 겹치지 않게 한다. 앵커는 사이트·저장소 화면 양쪽에서 통하는 HTML 로 둔다.
    L = [f'<a id="{anchor(cid)}"></a>', "", f"## {n}. {card['titles'][0]}", "",
         f"`{cid}` · {card.get('topic', '')} · 민감도 {sens['level']} · {C.badge_label(card)} · 상태 {card['state']} · r{card['revision']}", ""]
    L += ["**① 제목 후보**", ""] + [f"{i}. {t}" for i, t in enumerate(card["titles"], 1)] + [""]
    L += [f"**② 한 줄 훅** — {card['hook']}", ""]
    wt = card["why_today"]
    L += [f"**③ 왜 오늘인가** — {wt['text']} _(계기: {wt['trigger_type']} · {wt['trigger_date']})_", ""]
    L += ["**④ 핵심 데이터**", "", "| # | 내용 | 출처 | 등급 | 검증 |", "|---|---|---|---|---|"]
    for i, d in enumerate(card.get("data") or [], 1):
        cl = by_id.get(d.get("claim_id"))
        mark = _claim_mark(cl) if cl else "링크만(검증 전)"
        ref = f" `{d['claim_id'][-2:]}`" if cl else ""
        L += [f"| {i} | {d['text']}{ref} | [{d['source_name']}]({d['url']}) | {d.get('tier', '')} | {mark} |"]
    if not card.get("data"):
        L += ["| – | (핵심 수치는 채택 뒤 확보) | | | |"]
    L += [""]
    if card.get("sources"):
        L += ["1차 출처: " + " · ".join(f"[{s['name']}]({s['url']})({s['tier']})" for s in card["sources"]), ""]
    L += [f"**⑤ 검증 배지** — {C.badge_label(card)}" + (f" {card['badge_note']}" if card.get("badge_note") else ""), ""]
    cov = card["coverage"]
    L += [f"**⑥ 슈카월드 기존 커버리지** — {cov['summary']}"]
    vids = cov.get("videos") or []
    if any("relation" in v for v in vids):
        L += _flow_table(vids)
    else:
        for v in vids:
            L += [f"  - {v['date']} [{v['title']}](https://youtu.be/{v['video_id']})"]
    if not public:
        L += [f"  - _대조 낱말: {', '.join(cov.get('searched') or [])}_"]
    L += ["", f"**⑦ 민감도** — {sens['level']}" + (f" · {sens['reason']}" if sens.get("reason") else ""), ""]
    L += ["**⑧ 예상 구성**", ""] + [f"{i}. **{o['stage']}** — {o['note']}" for i, o in enumerate(card["outline"], 1)] + [""]
    ang = card["angles"]
    L += ["**⑨ 이면**", "", f"- 반전: {ang['twist']}"]
    if ang.get("parallel"):
        L += [f"- 평행 사례: {ang['parallel']}"]
    if ang.get("analogy"):
        L += [f"- 비유·위트: {ang['analogy']}"]
    L += [f"- 브릿지 멘트: {ang['bridge']}", ""]
    L += ["**⑩ 리스크**", ""] + [f"- {r}" for r in card["risks"]] + [""]
    counters = [c for c in claims if (c.get("counter") or {}).get("strongest_counter")]
    if counters:
        L += ["**반증 메모**", ""]
        for c in counters:
            ct = c["counter"]
            L += [f"- `{c['claim_id'][-2:]}` 가장 강한 반례: {ct['strongest_counter']} / 남는 불확실성: {ct.get('residual_uncertainty', '')}"]
        L += [""]
    if not public and card.get("discovery"):
        L += [f"_발굴 경로: {card['discovery']}_", ""]
    return "\n".join(L)


def _head(date: str, slot: str, title: str, front: bool = False) -> list[str]:
    dow = DOW[datetime.strptime(date, "%Y-%m-%d").weekday()]
    fm = ["---", "kicker: OZL Daily Desk", f"date: {date}", "theme: doc", "---", ""] if front else []   # 비공개 문서만 — PDF 머리말용
    return fm + [f"# {title} — {date} ({dow}) {SLOT_KO[slot]}", ""]


def summary_counts(cards: list[dict]) -> str:
    """카드 배지 집계. verified 는 기록으로 다시 갈라 센다 — 사람이 대조한 것만 `확인`, 기계 대조가 섞이면 「원문 일치」
    (원시 배지로 세면 「원문 일치」 카드가 `확인`으로 세어진다 — 2026-11-13 수정)."""
    n = Counter(C.badge_ko(c) for c in cards)
    return (f"{C.GRADE_HUMAN} {n[C.GRADE_HUMAN]} · {C.GRADE_MACHINE} {n[C.GRADE_MACHINE]} · 추정 {n['추정']} · 단독 {n['단독']} · "
            f"루머 {n['루머']} · 검증 대기 {n['pending']}")


def render_private(date: str, slot: str) -> str:
    cards = C.cards_for(date, slot)
    st = _stats(date, slot)
    L = _head(date, slot, "OZL 일일 데스크(전체본·비공개)", front=True)
    L += ["| 항목 | 값 |", "|---|---|", f"| 회차 | {slot} · 작성 {C.now_kst()[:16].replace('T', ' ')} KST |",
          f"| 소재 | {len(cards)}장 (정밀 {sum(c['depth'] == 'full' for c in cards)} · 간이 {sum(c['depth'] == 'light' for c in cards)}) |",
          f"| 검증 요약 | {summary_counts(cards)} |",
          f"| 공개 발행 | 승인 {sum(C.publishable(c, C.claims_for(c['card_id'])) for c in cards)}장 |"]
    if st:
        L += [f"| 수집 | 피드 {st['feeds_ok']}/{st['feeds']}곳{_off_note(st)} · 최근 {st['hours']:g}시간 {st['items']}건 → 묶음 {st['clusters']}개 → 민감 기준 제외 {st['red']}개 → 카드 {len(cards)}장 |"]
    L += ["", "**채택 대기**", ""]
    wait = [c for c in cards if c["state"] == "제안"]
    L += [f"- `{c['card_id']}` {c['titles'][0]} — {C.badge_label(c)}" for c in wait] or ["없음"]
    L += ["", "통과: `/ozl pick <card_id>` 또는 Notion 상태를 `채택`으로(그 뒤 완성 절차는 시스템이 한다). 공개는 사용자가 말했을 때만 `/ozl publish <card_id>`.", ""]
    for i, c in enumerate(cards, 1):
        L += ["---", "", render_card(c, C.claims_for(c["card_id"]), i, public=False)]
    return "\n".join(L) + "\n"


def render_sheet(date: str, slot: str) -> str:
    """기록마다 원문 표기·위치·링크·등급을 한 덩어리로(표는 PDF 에서 쪽이 갈려 목록으로 쓴다). 사용자에게 대조를 요청하는 문서가 아니다 —
    등급은 사람 대조('확인')와 프로그램 대조+독립 재대조(「원문 일치」)를 가른다."""
    L = _head(date, slot, "검증 시트(비공개)", front=True)
    L += ["기록마다 **원문 표기**와 **원문 위치**, 출처 링크, 등급을 적는다. 「원문 일치」는 프로그램이 받은 원문 사본에서 문구를 대조하고 다른 에이전트가 같은 자리를 독립으로 다시 찾은 것이고, `확인`은 사람이 눈으로 대조한 것이다.", ""]
    for c in C.cards_for(date, slot):
        cl = C.claims_for(c["card_id"])
        if not cl:
            continue
        L += [f"## {c['card_id'][11:]} · {c['titles'][0]}", ""]
        for x in cl:
            src = x["source"]
            done = (f"{C.GRADE_HUMAN} {x.get('human_verified_at', '')[:10]} · {x.get('human_verified_by', '')}" if x.get("human_verified")
                    else C.grade_label(x))
            L += [f"**`{x['claim_id'][11:]}`** {x['text']}", "",
                  f"- 원문 표기: `{x['observed']}`",
                  f"- 원문 위치: {(x.get('checks') or {}).get('primary_doc_locator', '')}",
                  f"- 출처: [{src['publisher']}]({src['url']}) · {src['tier']}",
                  f"- 등급: {done}", ""]
    return "\n".join(L) + "\n"


def render_public(date: str, slot: str) -> str:
    cards = C.cards_for(date, slot)
    status = {c["card_id"]: C.publish_status(c, C.claims_for(c["card_id"])) for c in cards}
    pub = [c for c in cards if status[c["card_id"]] == "발행"]
    gone = [c for c in cards if status[c["card_id"]] == "철회"]
    hold = [c for c in cards if status[c["card_id"]] == "미발행" and c["state"] != "반려"]
    st = _stats(date, slot)
    L = _head(date, slot, "OZL 일일 데스크")
    L += ["| 항목 | 값 |", "|---|---|", f"| 회차 | {SLOT_KO[slot]}({slot}) |",
          f"| 소재 카드 | {len(cards)}장 — 발행 {len(pub)} · 검증·승인 대기 {len(hold)}" + (f" · 철회 {len(gone)}" if gone else "") + " |",
          f"| 검증 요약 | {summary_counts(cards)} |"]
    if st:
        L += [f"| 수집 | 피드 {st['feeds_ok']}/{st['feeds']}곳{_off_note(st)} · 최근 {st['hours']:g}시간 기사·발표 {st['items']}건 → 사건 묶음 {st['clusters']}개 → 민감 기준 제외 {st['red']}개 → 카드 {len(cards)}장 |"]
    L += ["", f"공개를 승인한 카드만 전문을 싣습니다([검증 방법 8절]({SITE}/methodology/)). "
          "승인 전 카드는 번호와 상태만 남깁니다.", ""]
    if pub:
        for i, c in enumerate(pub, 1):
            claims = C.claims_for(c["card_id"])
            L += ["---", "", render_card(c, claims, i, public=True)]
            if claims:
                L += [f"클레임 레코드: " + " · ".join(f"[`{x['claim_id'][-2:]}`]({REPO}/blob/main/claims/{c['card_id'][:10]}/{x['claim_id']}.yaml)" for x in claims), ""]
    if gone:
        L += ["---", "", "## 철회", "", "| 카드 | 철회 시각 | 사유 |", "|---|---|---|"]
        for c in gone:
            L += [f"| `{c['card_id']}` | {c['publish']['withdrawn_at'][:16].replace('T', ' ')} | {c['publish'].get('reason', '')} |"]
        L += ["", f"정정·철회 기록: [corrections]({SITE}/corrections/)", ""]
    if hold:
        # 승인 전 카드는 소재를 드러내지 않는다 — 분야·계기 칸을 두지 않는다(2026-11-13)
        L += ["---", "", "## 승인 대기", "", "| 카드 | 상태 |", "|---|---|"]
        for c in hold:
            L += [f"| `{c['card_id']}` | {C.badge_label(c)} |"]
        L += [""]
    return "\n".join(L) + "\n"


def notion_content(card: dict, claims: list[dict]) -> str:
    """Notion 페이지 본문 — 표 없이 제목·글머리·링크만 쓴다(휴대폰에서 읽는 요약). 전문은 전체본에 있다."""
    by_id = {c["claim_id"]: c for c in claims}
    L = [f"**한 줄 훅** — {card['hook']}", "", f"**왜 오늘인가** — {card['why_today']['text']}", "", "### 제목 후보"]
    L += [f"- {t}" for t in card["titles"]]
    L += ["", "### 핵심 데이터"]
    for d in card.get("data") or []:
        cl = by_id.get(d.get("claim_id"))
        L += [f"- {d['text']} — [{d['source_name']}]({d['url']}) ({d.get('tier', '')} · {_claim_mark(cl) if cl else '링크만'})"]
    L += ["", "### 예상 구성"] + [f"{i}. **{o['stage']}** — {o['note']}" for i, o in enumerate(card["outline"], 1)]
    ang = card["angles"]
    L += ["", "### 이면", f"- 반전: {ang['twist']}"]
    L += [f"- 평행 사례: {ang['parallel']}"] if ang.get("parallel") else []
    L += [f"- 비유: {ang['analogy']}"] if ang.get("analogy") else []
    L += [f"- 브릿지 멘트: {ang['bridge']}", "", "### 리스크"] + [f"- {r}" for r in card["risks"]]
    L += ["", f"기존 커버리지: {card['coverage']['summary']}", "", f"`{card['card_id']}` · r{card['revision']} · 민감도 {card['sensitivity']['level']}"]
    return "\n".join(L)


def notion_rows(date: str, slot: str) -> list[dict]:
    """Notion DB 「OZL 소재 카드」 upsert 용 속성 묶음(키 = card_id). 실제 호출은 루틴이 MCP 커넥터로 한다."""
    rows = []
    for c in C.cards_for(date, slot):
        approved = C.publishable(c, C.claims_for(c["card_id"]))
        cov = c["coverage"]["summary"]
        n_src = len({d["url"] for d in (c.get("data") or [])} | {s["url"] for s in (c.get("sources") or [])})
        props = {
            "제목": c["titles"][0], "card_id": c["card_id"], "date:날짜:start": c["date"], "date:날짜:is_datetime": 0,
            "회차": c["slot"], "상태": c["state"], "주제": c["category"], "민감도": c["sensitivity"]["level"],
            "배지": C.badge_ko(c), "출처 수": n_src, "왜 오늘인가": c["why_today"]["text"][:1900],
            "반전 포인트": c["angles"]["twist"][:1900], "기존 커버리지": cov[:1900],
            "Pages 링크": page_url(c["card_id"]) if approved else None, "revision": c["revision"]}
        ev = C.event_times(c)
        props["발행"] = C.publish_status(c, C.claims_for(c["card_id"]))
        props["세부 주제"] = c.get("topic", "")
        if ev["picked_at"]:
            props["date:채택일:start"] = ev["picked_at"][:10]   # 날짜 값이 없으면 키를 넣지 않는다(빈 날짜로 덮어쓰지 않게)
        if ev["published_at"]:
            props["date:발행일:start"] = ev["published_at"][:10]
        rows.append({"card_id": c["card_id"], "content": notion_content(c, C.claims_for(c["card_id"])), "properties": props})
    return rows


def keeps_public_page(cards: list[dict]) -> bool:
    """회차 발행본(공개 쪽)을 둘지. 공개 이력(승인 또는 철회)이 한 번이라도 있는 카드가 있으면 둔다 — 한 번 공개한 쪽은
    조용히 사라지지 않는다(철회도 쪽에 남는다). 공개 이력이 없는 회차는 승인 전 후보만 있으므로 쓰지 않는다(2026-11-13 운영 변경:
    승인 전 후보를 날마다 사이트에 올리지 않는다)."""
    for c in cards:
        ev = C.event_times(c)
        if ev["published_at"] or ev["withdrawn_at"] or (c.get("publish") or {}).get("approved") is True:
            return True
    return False


def render_all(date: str, slot: str) -> dict:
    cards = C.cards_for(date, slot)
    if not cards:
        raise FileNotFoundError(f"{date} {slot} 카드가 없다 — private/desk/cards/")
    errs = []
    for c in cards:
        errs += C.validate_card(c, C.claims_for(c["card_id"]))
    if errs:
        raise ValueError("검증 오류 — 렌더 중단:\n" + "\n".join(f"  - {e}" for e in errs))
    from . import archive   # archive 가 이 모듈을 불러 쓰므로 여기서 늦게 부른다
    keep = keeps_public_page(cards)
    archive.build_index(include=[(date, slot)] if keep else [])   # 미리 실패만 걸러낸다 — 여기서 예외가 나면 파일을 하나도 쓰지 않는다
    P = paths(date, slot)
    for _ in range(3):
        written = ""
        for k, fn in (("private", render_private), ("sheet", render_sheet), ("public", render_public)):
            text = fn(date, slot)
            if k == "public":
                # 판정은 발행본을 만든 뒤에 다시 한다(그 사이 승인이 끼어들었으면 남긴다). 공개 이력이 없는 회차는 쓰지 않고, 남은 파일은 지운다
                keep = keeps_public_page(C.cards_for(date, slot))
                if not keep:
                    if P[k].exists():
                        P[k].unlink()   # 색인 저장보다 먼저 지운다 — 중간에 멈추면 사이트 검사가 크게 실패하고 다음 렌더가 바로잡는다
                    continue
            P[k].parent.mkdir(parents=True, exist_ok=True)
            P[k].write_text(text, encoding="utf-8")
            written = text if k == "public" else written
        try:
            index = archive.build_index(include=[(date, slot)] if keep else [])   # 보고서를 다 쓴 뒤 다시 계산한다 — 색인은 늘 보고서와 같거나 더 나중 상태
        except ValueError:
            if not keep and keeps_public_page(C.cards_for(date, slot)):
                continue   # 쓰지 않기로 판정한 뒤에 첫 승인이 끼어들었다 — 다시 판정해 발행본을 쓴다
            raise
        # 실제로 쓴 발행본의 자리표와 색인의 이 회차 발행 카드가 같아야 저장한다. 그 사이 승인·철회가 끼어들었으면 다시 쓴다
        in_report = {f"{date}-{a}" for a in _ANCHOR.findall(written)}
        in_index = {c["card_id"] for c in index["cards"] if (c["date"], c["slot"]) == (date, slot)}
        if in_report == in_index:
            break
    else:
        raise RuntimeError(f"{date} {slot}: 보고서를 3번 다시 써도 발행 카드가 색인과 맞지 않는다 — 색인은 저장하지 않았다")
    idx, _ = archive.save_index(index)
    out = {k: str(v) for k, v in P.items()}
    if not keep:
        out["public"] = None   # 발행본을 쓰지 않았다(공개 이력 없는 회차) — 부르는 쪽은 daily/ 를 폴더째 git add 한다
    out["index"] = str(idx)
    mine = next((r for r in index["reports"] if (r["date"], r["slot"]) == (date, slot)), None)
    return {"paths": out, "cards": len(cards), "summary": summary_counts(cards), "published": mine["published"] if mine else 0,
            "public_page": keep}
