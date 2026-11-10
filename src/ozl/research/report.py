#!/usr/bin/env python3
"""일일 보고서 렌더 — 카드 YAML 에서 세 문서를 만든다.

- 전체본(비공개)  private/daily/YYYY/MM/<날짜>_<회차>.md        모든 카드 · 내부 메모 포함
- 검증 시트(비공개) private/daily/YYYY/MM/<날짜>_<회차>_검증시트.md  사람이 원문과 눈으로 대조할 표
- 발행본(공개)    daily/YYYY/MM/<날짜>_<회차>.md                발행 승인된 카드만 전문, 나머지는 번호·분야·상태만
공개 규칙의 정본은 docs/methodology.md §8 — 배지가 확인·추정이고 발행 승인된 카드만 싣는다.
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter
from datetime import datetime

from . import cards as C

ROOT = C.ROOT
TAGLINE = "**OZL — 오늘의 즐길거리.** 매일 이슈를 발굴·검증·브리핑합니다."
SITE = "https://johyunbin.github.io/ozl"
REPO = "https://github.com/johyunbin/ozl"  # 발행본은 저장소 화면과 사이트 양쪽에서 읽히므로 링크를 절대 주소로 쓴다
SLOT_KO = {"am": "아침", "pm": "저녁", "wk": "주간"}
DOW = "월화수목금토일"


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
    ok = sum(1 for f in d["feeds"] if not f["error"])
    return {"feeds_ok": ok, "feeds": len(d["feeds"]), "items": d["n_items_window"], "clusters": d["n_clusters"], "red": red,
            "hours": d["window_hours"], "generated_at": d["generated_at"]}


def _claim_mark(c: dict) -> str:
    if c.get("status") == "verified":
        return "확인"
    if c.get("status") == "pending":
        return "원문 대조함 · 사람 확인 대기" if (c.get("verifiers") or {}).get("claude") else "검증 전"
    return C.BADGE_KO.get(c.get("status"), "?")


def render_card(card: dict, claims: list[dict], n: int, public: bool) -> str:
    cid = card["card_id"]
    if public and not C.publishable(card, claims):
        raise PermissionError(f"{cid}: 발행 승인되지 않은 카드는 공개용으로 렌더하지 않는다")
    by_id = {c["claim_id"]: c for c in claims}
    sens = card["sensitivity"]
    # 제목을 "N. " 로 시작해 PDF 엔진의 자동 장 번호와 겹치지 않게 한다. 앵커는 사이트·저장소 화면 양쪽에서 통하는 HTML 로 둔다.
    L = [f'<a id="{anchor(cid)}"></a>', "", f"## {n}. {card['titles'][0]}", "",
         f"`{cid}` · {card.get('topic', '')} · 민감도 {sens['level']} · {C.BADGE_LABEL[card['badge']]} · 상태 {card['state']} · r{card['revision']}", ""]
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
    L += [f"**⑤ 검증 배지** — {C.BADGE_LABEL[card['badge']]}" + (f" {card['badge_note']}" if card.get("badge_note") else ""), ""]
    cov = card["coverage"]
    L += [f"**⑥ 슈카월드 기존 커버리지** — {cov['summary']}"]
    for v in cov.get("videos") or []:
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
    return fm + [f"# {title} — {date} ({dow}) {SLOT_KO[slot]}", "", f"> {TAGLINE}", ""]


def summary_counts(cards: list[dict]) -> str:
    n = Counter(c["badge"] for c in cards)
    return f"확인 {n['verified']} · 추정 {n['credible_estimate']} · 단독 {n['single_source']} · 루머 {n['unverified_rumor']} · 검증 대기 {n['pending']}"


def render_private(date: str, slot: str) -> str:
    cards = C.cards_for(date, slot)
    st = _stats(date, slot)
    L = _head(date, slot, "OZL 일일 데스크(전체본·비공개)", front=True)
    L += ["| 항목 | 값 |", "|---|---|", f"| 회차 | {slot} · 작성 {C.now_kst()[:16].replace('T', ' ')} KST |",
          f"| 소재 | {len(cards)}장 (정밀 {sum(c['depth'] == 'full' for c in cards)} · 간이 {sum(c['depth'] == 'light' for c in cards)}) |",
          f"| 검증 요약 | {summary_counts(cards)} |",
          f"| 공개 발행 | 승인 {sum(C.publishable(c, C.claims_for(c['card_id'])) for c in cards)}장 |"]
    if st:
        L += [f"| 수집 | 피드 {st['feeds_ok']}/{st['feeds']}곳 · 최근 {st['hours']:g}시간 {st['items']}건 → 묶음 {st['clusters']}개 → 민감 기준 제외 {st['red']}개 → 카드 {len(cards)}장 |"]
    L += ["", "**채택 대기**", ""]
    wait = [c for c in cards if c["state"] == "제안"]
    L += [f"- `{c['card_id']}` {c['titles'][0]} — {C.BADGE_LABEL[c['badge']]}" for c in wait] or ["없음"]
    L += ["", "채택: `/ozl pick <card_id>` 또는 Notion 상태를 `채택`으로. 공개 발행: 검증 시트로 원문을 대조한 뒤 `/ozl publish <card_id>`.", ""]
    for i, c in enumerate(cards, 1):
        L += ["---", "", render_card(c, C.claims_for(c["card_id"]), i, public=False)]
    return "\n".join(L) + "\n"


def render_sheet(date: str, slot: str) -> str:
    """사람 육안 대조용 — 클레임마다 원문 표기·위치·링크를 한 덩어리로(표는 PDF 에서 쪽이 갈려 목록으로 쓴다)."""
    L = _head(date, slot, "검증 시트(비공개)", front=True)
    L += ["원문을 열어 **원문 표기**의 값이 **원문 위치**에 그대로 있는지 눈으로 확인한다. 확인한 클레임 번호를 알려 주면 `human_verified` 로 올린다.", ""]
    for c in C.cards_for(date, slot):
        cl = C.claims_for(c["card_id"])
        if not cl:
            continue
        L += [f"## {c['card_id'][11:]} · {c['titles'][0]}", ""]
        for x in cl:
            src = x["source"]
            done = f"확인함 {x.get('human_verified_at', '')[:10]} · {x.get('human_verified_by', '')}" if x.get("human_verified") else "아직"
            L += [f"**`{x['claim_id'][11:]}`** {x['text']}", "",
                  f"- 원문 표기: `{x['observed']}`",
                  f"- 원문 위치: {(x.get('checks') or {}).get('primary_doc_locator', '')}",
                  f"- 출처: [{src['publisher']}]({src['url']}) · {src['tier']}",
                  f"- 사람 확인: {done}", ""]
    return "\n".join(L) + "\n"


def render_public(date: str, slot: str) -> str:
    cards = C.cards_for(date, slot)
    pub = [c for c in cards if C.publishable(c, C.claims_for(c["card_id"]))]
    gone = [c for c in cards if c not in pub and (c.get("publish") or {}).get("withdrawn_at")]
    hold = [c for c in cards if c not in pub and c not in gone and c["state"] != "반려"]
    st = _stats(date, slot)
    L = _head(date, slot, "OZL 일일 데스크")
    L += ["| 항목 | 값 |", "|---|---|", f"| 회차 | {SLOT_KO[slot]}({slot}) |",
          f"| 소재 카드 | {len(cards)}장 — 발행 {len(pub)} · 검증·승인 대기 {len(hold)}" + (f" · 철회 {len(gone)}" if gone else "") + " |",
          f"| 검증 요약 | {summary_counts(cards)} |"]
    if st:
        L += [f"| 수집 | 피드 {st['feeds_ok']}/{st['feeds']}곳 · 최근 {st['hours']:g}시간 기사·발표 {st['items']}건 → 사건 묶음 {st['clusters']}개 → 민감 기준 제외 {st['red']}개 → 카드 {len(cards)}장 |"]
    L += ["", f"이 데스크는 배지가 `확인`·`추정`이고 사람이 발행을 승인한 카드만 전문을 싣습니다([검증 방법론 §8]({SITE}/methodology/)). "
          "나머지는 번호·분야·상태만 남기고, 검증이 끝나면 같은 번호로 채워집니다.", ""]
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
        L += ["---", "", "## 검증·승인 대기", "", "| 카드 | 분야 | 계기 | 민감도 | 상태 |", "|---|---|---|---|---|"]
        for c in hold:
            L += [f"| `{c['card_id']}` | {c.get('topic', '')} | {c['why_today']['trigger_type']} | {c['sensitivity']['level']} | {C.BADGE_LABEL[c['badge']]} |"]
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
        rows.append({"card_id": c["card_id"], "content": notion_content(c, C.claims_for(c["card_id"])), "properties": {
            "제목": c["titles"][0], "card_id": c["card_id"], "date:날짜:start": c["date"], "date:날짜:is_datetime": 0,
            "회차": c["slot"], "상태": c["state"], "주제": c["category"], "민감도": c["sensitivity"]["level"],
            "배지": C.BADGE_KO[c["badge"]], "출처 수": n_src, "왜 오늘인가": c["why_today"]["text"][:1900],
            "반전 포인트": c["angles"]["twist"][:1900], "기존 커버리지": cov[:1900],
            "Pages 링크": page_url(c["card_id"]) if approved else None, "revision": c["revision"]}})
    return rows


def render_all(date: str, slot: str) -> dict:
    cards = C.cards_for(date, slot)
    if not cards:
        raise FileNotFoundError(f"{date} {slot} 카드가 없다 — private/desk/cards/")
    errs = []
    for c in cards:
        errs += C.validate_card(c, C.claims_for(c["card_id"]))
    if errs:
        raise ValueError("검증 오류 — 렌더 중단:\n" + "\n".join(f"  - {e}" for e in errs))
    P = paths(date, slot)
    for k, fn in (("private", render_private), ("sheet", render_sheet), ("public", render_public)):
        P[k].parent.mkdir(parents=True, exist_ok=True)
        P[k].write_text(fn(date, slot), encoding="utf-8")
    return {"paths": {k: str(v) for k, v in P.items()}, "cards": len(cards), "summary": summary_counts(cards),
            "published": sum(C.publishable(c, C.claims_for(c["card_id"])) for c in cards)}
