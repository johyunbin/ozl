"""검사기 본체 — 빠진 칸, 허용 값, 번호, 근거 기록, 판정(rules), 숫자(numbers), 문체(style)를 모아 오류와 경고 목록을 만든다.

오류는 "<이슈 번호> <칸 경로>: <문구>" 꼴, 경고는 앞에 '경고'. public=True(명령의 --public)이거나 게시 가부가 '게시 가능'이면
게시 필수 칸까지 본다. 발행 목록과 견주는 검사(승인 뒤 판 번호, 게시한 주소 이름, 게시 대기의 검토 조건)는 revisions 가 더한다.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from ozl.research import cards

from . import article as ART, evidence as EV
from . import basis, dates, fields, idents, ids, model, numbers, rules, style
from .allegation import _allegation_errors, _crime_exempt

MSG_ELECTION = "선거 관련 이슈는 선거 종류, 선거일, 제한 기간(선거일 엿새 전부터)을 적는다"
MSG_ANNOUNCE = "발표와 조치는 발표문이나 기관 자료로 확인한다"
MSG_NA = f"없으면 '{model.NA}'을 글자로 적는다"
VH_KEYS = {"rev", "at", "from", "to", "why"}
CORRECTION_KEYS = {"rev", "at", "kind", "before", "after", "why"}
MSG_KW_POLL = "선거 관련 이슈의 키워드에는 판세 낱말을 쓰지 않는다(키워드는 가림 표시가 없다)"
MSG_KW_QTY = "키워드에는 수량을 쓰지 않는다 — 키워드는 숫자 종류 검사를 받을 수 없다"


class _Acc:
    def __init__(self):
        self.e: list[tuple[str, str]] = []

    def add(self, path, msg):
        self.e.append((path, msg))

    def need(self, d: dict, k: str, path: str) -> bool:
        if cards._blank(d.get(k)):
            self.add(path, f"{k}이 없다")
            return False
        return True

    def enum(self, v, allowed, path, name=None) -> bool:
        if v not in allowed:
            self.add(path, f"{name or path.rsplit('.', 1)[-1]} 값 '{v}'은 허용 값({', '.join(map(str, allowed))})이 아니다")
            return False
        return True

    def length(self, v, n, path):
        if isinstance(v, str) and len(v) > n:
            self.add(path, f"{n}자 이하로 쓴다(지금 {len(v)}자)")


def _http(u) -> bool:
    return isinstance(u, str) and bool(re.match(r"^https?://[^/\s]+", u))


def _real_date(s) -> bool:
    return isinstance(s, str) and cards._real_date(s)


def _items(a: _Acc, issue: dict, lst: str, kind: str):
    seen = set()
    for i, it in enumerate(issue.get(lst) or []):
        if not isinstance(it, dict):
            a.add(f"{lst}.{i}", "항목은 사전이다")
            continue
        iid = it.get("id")
        if not ids.item_id_ok(iid, kind):
            a.add(f"{lst}.{i}.id", f"항목 번호 '{iid}'가 {kind}1 꼴이 아니다")
        if iid in seen:
            a.add(f"{lst}.{iid}.id", "같은 번호의 항목이 둘이다")
        seen.add(iid)
        yield f"{lst}.{iid}", it


def _common_item(a: _Acc, p: str, it: dict, issue: dict, nums=True):
    a.enum(it.get("target_kind"), model.TARGET_KINDS, f"{p}.target_kind")
    a.enum(it.get("publish"), model.PUBLISH_STATES, f"{p}.publish")
    if nums and not isinstance(it.get("numbers", []), list):
        a.add(f"{p}.numbers", "numbers 는 목록이다")
    if "선거" in (issue.get("sensitive") or []):
        if not isinstance(it.get("election_mask"), bool):
            a.add(f"{p}.election_mask", "선거 관련 이슈의 항목마다 가림 대상인지(election_mask)를 적는다")
        elif it["election_mask"] is False and any(style.poll_words(t) for t in _item_strings(it)):
            a.add(f"{p}.election_mask", style.MSG_POLL)


def _item_strings(it: dict) -> list[str]:
    """항목 안의 글 전부(작은 주장의 요지·판정 이유, 당사자 입장, 판정 변경 이력까지) — 판세 낱말 검사가 본다."""
    out = [v for v in it.values() if isinstance(v, str)]
    for pt in it.get("parts") or []:
        if isinstance(pt, dict):
            out += [v for v in pt.values() if isinstance(v, str)]
    pp = it.get("party_position")
    if isinstance(pp, dict) and isinstance(pp.get("text"), str):
        out.append(pp["text"])
    for h in it.get("verdict_history") or []:
        if isinstance(h, dict):
            out += [v for v in h.values() if isinstance(v, str)]
    return out


def _cited(a: _Acc, p: str, eids, evidences, need=1):
    eids = [eids] if isinstance(eids, str) else eids
    if not isinstance(eids, list) or len(eids) < need:
        a.add(f"{p}.evidence", "근거 번호를 적는다")
        return []
    for e in eids:
        if e not in evidences:
            a.add(f"{p}.evidence", f"근거 기록이 없다: {e}")
    return [evidences[e] for e in eids if e in evidences]


def _top(a: _Acc, issue: dict, evidences: dict, post: bool):
    for k in sorted(set(issue) - set(model.ISSUE_FIELDS)):
        a.add(k, "알 수 없는 칸이다")
    for k in model.REQUIRED:
        if k not in issue or (cards._blank(issue[k]) and not isinstance(issue[k], bool) and k != "sensitive"):
            a.add(k, f"{k}이 없다")
    pub = issue.get("publish") if isinstance(issue.get("publish"), dict) else {}
    if post:
        for k in model.POST_REQUIRED:
            if k == "reason" and pub.get("state") == "게시 가능":
                continue   # rules.publish_errors 가 6-16 문구로 잡는다
            if cards._blank(issue.get(k)):
                a.add(k, f"{k}이 없다")
    if not ids.issue_id_ok(issue.get("issue_id")):
        a.add("issue_id", f"이슈 번호 '{issue.get('issue_id')}'가 i20261114-01 꼴(실제 날짜)이 아니다")
    if ids.slug_error(issue.get("slug")):
        a.add("slug", ids.slug_error(issue.get("slug")))
    al = issue.get("aliases")
    if al is not None and not isinstance(al, list):
        a.add("aliases", "별칭은 주소 이름 목록이다")
    for s in al if isinstance(al, list) else []:
        if ids.slug_error(s):
            a.add("aliases", f"별칭 '{s}': {ids.slug_error(s)}")
        elif s == issue.get("slug"):
            a.add("aliases", f"별칭 '{s}'이 주소 이름과 같다")
    if isinstance(al, list) and len(set(map(str, al))) != len(al):
        a.add("aliases", "같은 별칭이 둘이다")
    rev = issue.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        a.add("revision", "판 번호는 1 이상 정수다")
    for k in ("split_from", "merged_into"):
        if issue.get(k) is not None and not ids.issue_id_ok(issue.get(k)):
            a.add(k, f"{k} 는 이슈 번호다")
    a.enum(issue.get("category"), model.CATEGORIES, "category")
    kw = issue.get("keywords")
    if not isinstance(kw, list) or not 1 <= len(kw) <= 12 or any(cards._blank(x) or not isinstance(x, str) for x in kw):
        a.add("keywords", "키워드는 1~12개 문자열이다")
    if not isinstance(issue.get("example"), bool):
        a.add("example", "example 은 참·거짓으로 적는다")
    reason = issue.get("reason")
    if isinstance(reason, str) and reason.strip():
        if not model.REASON_LEN[0] <= len(reason) <= model.REASON_LEN[1]:
            a.add("reason", f"다루는 이유는 {model.REASON_LEN[0]}~{model.REASON_LEN[1]}자다(지금 {len(reason)}자)")
        if len(re.findall(r"[.!?。](?:\s|$)", reason.strip())) > 1:
            a.add("reason", "다루는 이유는 문장 하나로 쓴다")
    if a.enum(pub.get("state"), model.PUBLISH_STATES, "publish.state", "publish.state") and pub["state"] != "게시 가능" \
            and cards._blank(pub.get("why")):
        a.add("publish.why", "게시 가능이 아니면 까닭(why)을 적는다")
    sens = issue.get("sensitive")
    if not isinstance(sens, list) or any(s not in model.SENSITIVE for s in sens):
        a.add("sensitive", f"민감 표시는 {', '.join(model.SENSITIVE)} 의 부분집합이다")
        sens = []
    if "선거" in sens:
        el = issue.get("election") if isinstance(issue.get("election"), dict) else {}
        ok = not cards._blank(el.get("kind")) and _real_date(el.get("date")) and _real_date(el.get("restrict_from")) \
            and bool(re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(el.get("poll_close") or ""))) and _http(el.get("schedule_url"))
        if not ok or date.fromisoformat(el["restrict_from"]) != date.fromisoformat(el["date"]) - timedelta(days=6):
            a.add("election", MSG_ELECTION)
        for path, text, _n, item in model.reader_items(issue):
            if item is None and style.poll_words(text):
                a.add(path, style.MSG_POLL + " — 항목 밖의 글(제목, 첫 화면, 비슷한 사례)은 가림 표시가 없으니 판세를 쓰지 않는다")
            elif path.startswith("corrections.") and style.poll_words(text):
                a.add(path, style.MSG_POLL + " — 정정 문장은 가림 표시가 없으니 판세를 쓰지 않는다")
    a.enum(issue.get("syuka_deck"), model.SYUKA_DECK, "syuka_deck")
    ec = issue.get("event_check") if isinstance(issue.get("event_check"), dict) else {}
    if not isinstance(ec.get("confirmed"), bool):
        a.add("event_check.confirmed", "사건 확인 여부(confirmed)를 참·거짓으로 적는다")
    elif ec["confirmed"]:
        ev = evidences.get(ec.get("evidence"))
        if not ev or ev.get("kind") == "보도" or cards._blank(ec.get("at")):
            a.add("event_check.evidence", "사건 확인은 1차 원문 근거 번호와 확인 시각을 적는다(보도는 안 된다)")
    else:
        for f in issue.get("facts") or []:
            if isinstance(f, dict) and f.get("kind") == "발표와 조치":
                a.add(f"facts.{f.get('id')}.kind", rules.MSG_EVENT)
    t = issue.get("titles") if isinstance(issue.get("titles"), dict) else {}
    cands = [c for c in t.get("candidates") or [] if isinstance(c, dict)]
    if post or cands:
        if len(cands) < 3 or len({c.get("angle") for c in cands if c.get("angle") in model.ANGLES}) < 3:
            a.add("titles.candidates", f"제목 후보는 서로 다른 각도({', '.join(model.ANGLES)}) 3개 이상이다")
        for i, c in enumerate(cands):
            a.enum(c.get("angle"), model.ANGLES, f"titles.candidates.{i}.angle", "angle")
            a.need(c, "text", f"titles.candidates.{i}.text")
            a.length(c.get("text"), model.LIMITS["titles.chosen"], f"titles.candidates.{i}.text")
        a.need(t, "chosen", "titles.chosen")
        if t.get("chosen") not in [c.get("text") for c in cands]:
            a.add("titles.chosen", "고른 제목은 후보 가운데 하나다")
    a.length(t.get("chosen"), model.LIMITS["titles.chosen"], "titles.chosen")
    a.enum(t.get("target_kind"), model.TARGET_KINDS, "titles.target_kind", "titles.target_kind")
    cids = {c.get("id") for c in issue.get("claims") or [] if isinstance(c, dict)}
    for k in ("titles.basis_claims", "so_far_refs"):
        refs = (t if k.startswith("titles") else issue).get(k.split(".")[-1]) or []
        for r in refs if isinstance(refs, list) else [refs]:
            if r not in cids:
                a.add(k, f"없는 주장을 가리킨다: {r}")
    if isinstance(rev, int) and rev >= 2 and cards._blank(issue.get("rev_line")):
        a.add("rev_line", "2판부터는 이번 판 한 줄(rev_line)을 적는다")
    for k in ("rev_line", "what_new", "why_matters"):
        a.length(issue.get(k), model.LIMITS[k], k)
    sf = issue.get("so_far")
    if post or sf:
        if not isinstance(sf, list) or len(sf) != 3 or any(not isinstance(x, str) or not x.strip() for x in sf):
            a.add("so_far", "지금까지 3줄은 문자열 정확히 3개다")
        for i, x in enumerate(sf if isinstance(sf, list) else []):
            a.length(x, model.LIMITS["so_far"], f"so_far.{i}")
    nm = issue.get("numbers", {})
    if not isinstance(nm, dict) or any(not isinstance(v, list) for v in nm.values()):
        a.add("numbers", "numbers 는 {칸 경로: [숫자 항목]} 꼴이다")
    elif nm:
        ok_paths = model.top_number_paths(issue)
        for k in sorted(map(str, nm)):
            if k not in ok_paths:
                a.add(f"numbers.{k}", "최상위 numbers 의 칸 경로가 독자에게 보이는 글 칸이 아니다(빈 글 칸, 주장, numbers 칸이 있는 항목은 "
                                      "최상위 지도를 쓰지 않는다)")
    prod = issue.get("production") if isinstance(issue.get("production"), dict) else {}
    if not isinstance(prod.get("researched_by"), list) or cards._blank(prod.get("chosen_by")) or (post and cards._blank(prod.get("drafted_by"))):
        a.add("production", "만든 쪽(researched_by 목록, chosen_by, 게시할 때는 drafted_by 까지)을 적는다")
    if issue.get("topic_state") is not None:
        a.enum(issue.get("topic_state"), model.TOPIC_STATES, "topic_state")
    tr_err = model.trend_error(issue.get("trend"))
    if tr_err:
        a.add("trend", f"{tr_err} — trend 는 {{score: 0~100 정수, bars7: 수 7개, asof, formula_version}} 꼴이다")
    a.enum(issue.get("work_state"), model.WORK_STATES, "work_state")
    for i, r in enumerate(issue.get("reviews") or []):
        if not (isinstance(r, dict) and r.get("kind") in model.REVIEW_KINDS and r.get("family") in model.REVIEW_FAMILIES
                and r.get("result") in model.REVIEW_RESULTS):
            a.add(f"reviews.{i}", "검토 줄의 kind·family·result 가 허용 값이 아니다")
    corr = issue.get("corrections")
    if corr is not None and not isinstance(corr, list):
        a.add("corrections", "corrections 는 목록이다")
    for i, c in enumerate(corr if isinstance(corr, list) else []):
        a.enum((c or {}).get("kind") if isinstance(c, dict) else None, model.CORRECTION_KINDS, f"corrections.{i}.kind", "kind")
        need = ("at", "why", "after") + (("before",) if isinstance(c, dict) and c.get("kind") in ("정정", "판정 변경") else ())
        if not isinstance(c, dict) or set(c) - CORRECTION_KEYS or not isinstance(c.get("rev"), int) or isinstance(c.get("rev"), bool) \
                or not 1 <= c["rev"] <= (rev if isinstance(rev, int) and not isinstance(rev, bool) else 1) \
                or any(cards._blank(c.get(k)) or not isinstance(c.get(k), str) for k in need):
            a.add(f"corrections.{i}", "정정 줄은 {rev(이 판 이하 정수), at, kind, before, after, why} 꼴이다(정정과 판정 변경은 before 까지)")
    sp = issue.get("spillover") if isinstance(issue.get("spillover"), dict) else {}
    for i, c in enumerate(sp.get("similar_cases") or []):
        if not isinstance(c, dict) or set(c) - {"text", "url"} or cards._blank(c.get("text")) or not _http(c.get("url")):
            a.add(f"spillover.similar_cases.{i}", "비슷한 사례는 {text, url} 꼴이다")
            continue
        a.length(c.get("text"), model.LIMITS["similar_cases.text"], f"spillover.similar_cases.{i}.text")
        if EV.community_url(c.get("url")):
            a.add(f"spillover.similar_cases.{i}.url", EV.MSG_COMMUNITY)
    for i, k in enumerate(kw if isinstance(kw, list) else []):
        if isinstance(k, str):
            a.e += [(f"keywords.{i}", m) for m in style.text_errors("keywords", k)]
            if style.crime_words(k):
                a.add(f"keywords.{i}", style.MSG_CRIME)
            if "선거" in sens and style.poll_words(k):
                a.add(f"keywords.{i}", MSG_KW_POLL)
            if numbers.keyword_qty(k, numbers.identifiers(issue)):   # 숫자가 이름의 일부인 키워드(5G, 4대강)와 식별자는 받는다
                a.add(f"keywords.{i}", MSG_KW_QTY)
    a.e += idents.identifier_list_errors(issue)


def _lists(a: _Acc, issue: dict, evidences: dict):
    for p, f in _items(a, issue, "facts", "f"):
        a.need(f, "text", f"{p}.text")
        a.length(f.get("text"), model.LIMITS["facts.text"], f"{p}.text")
        a.enum(f.get("type"), model.FACT_TYPES, f"{p}.type")
        a.enum(f.get("kind"), model.FACT_KINDS, f"{p}.kind")
        evs = _cited(a, p, f.get("evidence"), evidences)
        if f.get("kind") == "발표와 조치" and not any(e.get("kind") != "보도" for e in evs):
            a.add(f"{p}.evidence", MSG_ANNOUNCE)
        _common_item(a, p, f, issue)
    for p, c in _items(a, issue, "claims", "c"):
        kind = c.get("kind")
        if kind not in ("평가", "전망"):
            a.enum(kind, rules.CLAIM_KINDS, f"{p}.kind")
        a.need(c, "gist", f"{p}.gist")
        a.length(c.get("gist"), model.LIMITS["claims.gist"], f"{p}.gist")
        for pt in c.get("parts") or []:
            if isinstance(pt, dict):
                a.need(pt, "gist", f"{p}.parts.{pt.get('id')}.gist")
                a.length(pt.get("gist"), model.LIMITS["parts.gist"], f"{p}.parts.{pt.get('id')}.gist")
                if "kind" in pt:
                    a.enum(pt.get("kind"), rules.CLAIM_KINDS, f"{p}.parts.{pt.get('id')}.kind", "kind")
        vh = c.get("verdict_history", [])
        if not isinstance(vh, list) or any(not isinstance(h, dict) or set(h) - VH_KEYS or not isinstance(h.get("rev"), int)
                                           or h.get("from") not in rules.VERDICTS or h.get("to") not in rules.VERDICTS
                                           or len(str(h.get("why") or "")) > model.LIMITS["verdict_history.why"] for h in vh):
            a.add(f"{p}.verdict_history", f"판정 변경 이력은 [{{rev, at, from, to, why}}] 꼴이다(why {model.LIMITS['verdict_history.why']}자 이하)")
        if not cards._blank(c.get("basis_label")) and c.get("basis_label") != rules.DISCLOSURE_LABEL:
            a.add(f"{p}.basis_label", f"basis_label 은 '{rules.DISCLOSURE_LABEL}' 만 쓴다")
        if kind == "발표 여부":
            a.need(c, "attributed_to", f"{p}.attributed_to")
        for k in ("subject", "scope", "searched"):
            a.need(c, k, f"{p}.{k}")
        if kind in ("사실", "수치", "인과") and cards._blank(c.get("period")):
            a.add(f"{p}.period", f"period 가 없다 — {MSG_NA}")
        if kind == "수치":
            a.need(c, "unit", f"{p}.unit")
        sp = c.get("spread") if isinstance(c.get("spread"), dict) else {}
        if cards._blank(sp.get("where")) or cards._blank(sp.get("first_seen")) or not isinstance(sp.get("links", []), list):
            a.add(f"{p}.spread", "어디서 퍼졌나(spread: where, first_seen, links)를 적는다")
        for i, ln in enumerate(sp.get("links") or []):
            url = ln.get("url") if isinstance(ln, dict) else ln
            if EV.community_url(url):
                a.add(f"{p}.spread.links.{i}.url", EV.MSG_COMMUNITY)
        pp = c.get("party_position")
        if not (isinstance(pp, dict) and not cards._blank(pp.get("checked_at"))
                and (pp.get("none") is True or (not cards._blank(pp.get("text")) and pp.get("evidence") in evidences))):
            a.add(f"{p}.party_position", "당사자 입장은 {text, evidence, checked_at} 또는 {none: true, checked_at} 이다")
        if not isinstance(c.get("allegation"), bool):
            a.add(f"{p}.allegation", "allegation 은 참·거짓으로 적는다")
        for k in ("about_procedure", "premise_event"):
            if k in c and not isinstance(c[k], bool):
                a.add(f"{p}.{k}", f"{k} 는 참·거짓으로 적는다")
        _common_item(a, p, c, issue)
    for p, w in _items(a, issue, "flow", "w"):
        a.need(w, "what", f"{p}.what")
        a.enum(w.get("kind"), model.FLOW_KINDS, f"{p}.kind")
        ed = w.get("event_date")        # 일어난 날을 확인하지 못했으면 비운다(화면은 보도된 날만 적고 그 사실을 밝힌다)
        if cards._blank(ed) and not _real_date(w.get("report_date")):
            a.add(f"{p}.event_date", "일어난 날(event_date)을 비우려면 보도된 날(report_date)이 YYYY-MM-DD 로 있어야 한다")
        elif not cards._blank(ed) and not _real_date(ed):
            a.add(f"{p}.event_date", "event_date 는 YYYY-MM-DD 다")
        _cited(a, p, w.get("evidence"), evidences)
        _common_item(a, p, w, issue)
    for p, s in _items(a, issue, "stances", "s"):
        for k in ("who", "summary", "at"):
            a.need(s, k, f"{p}.{k}")
        a.enum(s.get("kind"), model.STANCE_KINDS, f"{p}.kind")
        _cited(a, p, s.get("evidence"), evidences)
        _common_item(a, p, s, issue)
    for p, q in _items(a, issue, "open_questions", "q"):
        a.need(q, "text", f"{p}.text")
        _common_item(a, p, q, issue, nums=False)
    for p, g in _items(a, issue, "figures", "g"):
        for k in ("caption", "alt"):
            a.need(g, k, f"{p}.{k}")
        ge = g.get("evidence")
        if ge is not None or g.get("kind") == "공식 문서 캡처":
            if not isinstance(ge, str) or cards._blank(ge):
                a.add(f"{p}.evidence", "그림의 근거 번호는 하나(문자열)로 적는다")
            elif ge not in evidences:
                a.add(f"{p}.evidence", f"근거 기록이 없다: {ge}")
        _common_item(a, p, g, issue, nums=False)


def check_issue(issue: dict, evidences: dict, public: bool = False, articles=(), ledger: dict | None = None) -> dict:
    """{errors: [문구], warnings: [문구]}. evidences = {근거 번호(파일 이름): 근거 기록}."""
    iid = issue.get("issue_id") or "?"
    a = _Acc()
    pub = issue.get("publish") if isinstance(issue.get("publish"), dict) else {}
    post = public or pub.get("state") == "게시 가능"
    _top(a, issue, evidences, post)
    _lists(a, issue, evidences)
    copy_errs: dict[str, list[str]] = {}
    a.e += fields.issue_field_errors(issue) + fields.sentence_errors(issue) + dates.date_errors(issue, evidences)
    (b_errs, b_warns), (art_e, art_w) = basis.basis_errors(issue), ART.issue_findings(issue, evidences)   # art = 붙은 글(명세 3절)
    a.e += b_errs + art_e
    for eid, ev in evidences.items():
        a.e += [(f"evidence.{eid}.{k}", m) for k, m in EV.structure_errors(ev, iid, eid)]
        a.e += [(f"evidence.{eid}.{k}", m) for k, m in fields.evidence_field_errors(ev)]
        copy_errs[eid] = EV.copy_errors(ev)
        a.e += [(f"evidence.{eid}", m) for m in copy_errs[eid]]
    for c in issue.get("claims") or []:
        if isinstance(c, dict):
            a.e += [(f"claims.{c.get('id')}.{k}", m) for k, m in rules.verdict_errors(c, evidences, copy_errs, issue)]
    a.e += rules.publish_errors(issue, evidences)
    a.e += numbers.number_errors(issue, evidences)
    a.e += style.style_errors(issue, _crime_exempt(issue, evidences, copy_errs))
    a.e += _allegation_errors(issue, evidences, copy_errs)
    try:
        a.e += ids.ledger_errors(issue, list(evidences), ids.load_ledger() if ledger is None else ledger)
    except (ValueError, json.JSONDecodeError, OSError) as e:
        a.add("issue_id", f"발급 대장을 읽지 못했다: {e}")
    warns = art_w + style.copy20_warnings(issue, evidences, articles) + style.cause_warnings(issue) + dates.flow_warnings(issue) + b_warns \
        + basis.recheck_warnings(issue, evidences)
    errors = list(dict.fromkeys(f"{iid} {p}: {m}" for p, m in a.e))
    return {"errors": errors, "warnings": [f"경고 {iid} {p}: {m}" for p, m in warns]}


def check_ids(issue_ids: list[str], public: bool = False, articles=()) -> dict[str, dict]:
    out = {}
    for iid in issue_ids:
        try:
            issue = model.load_issue(iid)
        except (OSError, ValueError) as e:
            out[iid] = {"errors": [f"{iid} issue.yaml: 읽지 못했다 — {e}"], "warnings": []}
            continue
        if issue.get("issue_id") != iid:
            out[iid] = {"errors": [f"{iid} issue_id: 폴더 이름과 issue_id 가 다르다({issue.get('issue_id')})"], "warnings": []}
            continue
        out[iid] = check_issue(issue, model.load_evidences(iid), public=public, articles=articles)
    return out
