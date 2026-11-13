"""글 속의 날짜 — 독자에게 보이는 글의 'M월 D일'('YYYY년 M월 D일', 'M.D.(요일)')이 그 글이 기댈 수 있는 날짜에 있는가.

기댈 수 있는 날짜(같은 월일이면 맞다):
  흐름  그 항목의 event_date·report_date, 인용한 근거의 대목과 문서 날짜
  입장  그 항목의 at, 인용한 근거의 대목과 문서 날짜
  주장  주장의 period, 작은 주장의 period, 인용한 근거(작은 주장·당사자 입장의 근거 포함)의 대목과 문서 날짜, 퍼진 곳은 first_seen 도
  사실·그림  인용한 근거의 대목과 문서 날짜, 같은 근거를 인용한 흐름의 event_date·report_date
  맨 위 글(제목, 무엇이 새로운가, 왜 중요한가, 지금까지 3줄, 다루는 까닭, 이번 판 한 줄)과 남은 질문
        흐름의 event_date·report_date, 게시되는 주장의 period, 이슈가 인용한 근거 전부의 대목과 문서 날짜
근거의 문서 날짜 = 출처 제목(source.title), 기준 시점(checks.base_period), 재대조가 적은 시점(recheck.checks.as_of)에 적힌 날짜.
영문 대목의 날짜(November 9, 2026 · Nov. 9 · 9 November)도 월일로 읽는다. '어제', '다음 날' 같은 말은 보지 않는다.
못 보는 것: 주장의 찾아본 범위·못 찾은 것·판정할 수 있는 조건(searched, not_found, would_decide — 찾은 문서의 날짜를 적는 칸이라
인용 근거에 없을 수 있다), 정정, 비슷한 사례, 판정 변경 이력.
"""
from __future__ import annotations

import re

from . import model

KO = re.compile(r"(?:(?<!\d)(\d{4})년\s?)?(?<!\d)(1[0-2]|0?[1-9])월\s?(3[01]|[12]\d|0?[1-9])일")
DOT_DAY = re.compile(r"(?<![\d.])(1[0-2]|0?[1-9])\.\s?(3[01]|[12]\d|0?[1-9])\.\s?\([월화수목금토일]\)")
ISO = re.compile(r"(?<!\d)(\d{4})\s?[-./]\s?(1[0-2]|0?[1-9])\s?[-./]\s?(3[01]|[12]\d|0?[1-9])(?!\d)")
_MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
_MON_RX = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
EN_MD = re.compile(_MON_RX + r"\s+(3[01]|[12]\d|0?[1-9])(?:st|nd|rd|th)?(?!\d)", re.I)
EN_DM = re.compile(r"(?<!\d)(3[01]|[12]\d|0?[1-9])(?:st|nd|rd|th)?\s+" + _MON_RX, re.I)

MSG_TOP = "날짜 '{}'이 흐름, 주장의 기간, 근거 대목 어디에도 없다"
MSG_ITEM = "날짜 '{}'이 이 항목의 날짜 칸과 인용한 근거의 대목 어디에도 없다"
TOP_PATHS = re.compile(r"^(titles\.(chosen|candidates\.\d+)|what_new|why_matters|reason|rev_line|so_far\.\d+)$")
CLAIM_SKIP = re.compile(r"^claims\.[^.]+\.(searched|not_found|would_decide|basis_label|verdict_history\..*|parts\.[^.]+\.would_decide)$")


def shown_dates(text) -> list[tuple[str, tuple[int, int]]]:
    """독자에게 보이는 글의 날짜 [(적힌 표기, (월, 일))]."""
    t = str(text or "")
    out = [(m.group(0), (int(m.group(2)), int(m.group(3)))) for m in KO.finditer(t)]
    out += [(m.group(0), (int(m.group(1)), int(m.group(2)))) for m in DOT_DAY.finditer(t)]
    return out


def month_days(text) -> set[tuple[int, int]]:
    """근거 쪽 글(대목, 날짜 칸)에서 읽은 월일 전부 — 한글, 점·빗금·줄표 날짜, 영문."""
    t = str(text or "")
    out = {d for _s, d in shown_dates(t)}
    out |= {(int(m.group(2)), int(m.group(3))) for m in ISO.finditer(t)}
    out |= {(_MON[m.group(1).lower()[:4] if m.group(1).lower().startswith("sept") else m.group(1).lower()[:3]], int(m.group(2)))
            for m in EN_MD.finditer(t)}
    out |= {(_MON[m.group(2).lower()[:4] if m.group(2).lower().startswith("sept") else m.group(2).lower()[:3]], int(m.group(1)))
            for m in EN_DM.finditer(t)}
    return out


def evidence_days(ev) -> set[tuple[int, int]]:
    if not isinstance(ev, dict):
        return set()
    src = ev.get("source") if isinstance(ev.get("source"), dict) else {}
    ch = ev.get("checks") if isinstance(ev.get("checks"), dict) else {}
    v = ev.get("verification") if isinstance(ev.get("verification"), dict) else {}
    rc = v.get("recheck") if isinstance(v.get("recheck"), dict) else {}
    rch = rc.get("checks") if isinstance(rc.get("checks"), dict) else {}
    out = set()
    for t in (ev.get("observed"), src.get("title"), ch.get("base_period"), rch.get("as_of")):
        out |= month_days(t)
    return out


def _ev_days(eids, evidences) -> set[tuple[int, int]]:
    out = set()
    for e in eids:
        out |= evidence_days(evidences.get(e))
    return out


def date_errors(issue: dict, evidences: dict) -> list[tuple[str, str]]:
    """[(칸 경로, 문구)] — 기댈 날짜가 없는 글 속 날짜."""
    flows = [w for w in issue.get("flow") or [] if isinstance(w, dict)]

    def flow_days(ws) -> set:
        return {d for w in ws for k in ("event_date", "report_date") for d in month_days(w.get(k))}

    claims = [c for c in issue.get("claims") or [] if isinstance(c, dict)]
    pub_claims = [c for c in claims if c.get("publish") == "게시 가능"]
    top = flow_days(flows) | {d for c in pub_claims for d in month_days(c.get("period"))} \
        | _ev_days(model.cited_evidence_ids(issue), evidences)
    errs: list[tuple[str, str]] = []
    for path, text, _n, item in model.reader_items(issue):
        found = shown_dates(text)
        if not found:
            continue
        if item is None or path.startswith("open_questions."):
            pool, msg = top, MSG_TOP
        elif path.startswith("claims."):
            if CLAIM_SKIP.match(path):
                continue
            pool = month_days(item.get("period")) | _ev_days(model.item_evidence_ids(item), evidences)
            pool |= {d for p in item.get("parts") or [] if isinstance(p, dict) for d in month_days(p.get("period"))}
            if path.endswith(".spread.where"):
                pool |= month_days((item.get("spread") or {}).get("first_seen") if isinstance(item.get("spread"), dict) else "")
            msg = MSG_ITEM
        else:
            eids = model.item_evidence_ids(item)
            pool = _ev_days(eids, evidences)
            if path.startswith("flow."):
                pool |= flow_days([item])
            elif path.startswith("stances."):
                pool |= month_days(item.get("at"))
            else:                                  # 사실·그림 — 같은 근거를 인용한 흐름의 날짜도 받는다
                pool |= flow_days([w for w in flows if set(model.item_evidence_ids(w)) & set(eids)])
            msg = MSG_ITEM
        for shown, md in found:
            if md not in pool:
                errs.append((path, msg.format(shown)))
    return errs


MSG_PAST_PLAN = "'예정'인데 event_date({})가 기록을 쓴 날({})보다 앞선다 — 이미 지났으면 '시행'이나 다른 종류로 적는다"


def written_on(issue: dict) -> str:
    """기록을 쓴 날 — 이슈 번호의 날짜와 작업 기록(history)의 날짜 가운데 가장 늦은 날(YYYY-MM-DD). 읽지 못하면 빈 글."""
    days = []
    m = re.match(r"^i(\d{4})(\d{2})(\d{2})-\d{2}$", str(issue.get("issue_id") or ""))
    if m:
        days.append("-".join(m.groups()))
    for h in issue.get("history") or []:
        if isinstance(h, dict):
            d = re.match(r"^\d{4}-\d{2}-\d{2}", str(h.get("at") or ""))
            if d:
                days.append(d.group(0))
    return max(days, default="")


def flow_warnings(issue: dict) -> list[tuple[str, str]]:
    """[(칸 경로, 문구)] — 날짜가 이미 지난 '예정' 흐름(경고)."""
    ref = written_on(issue)
    out = []
    for w in issue.get("flow") or []:
        if isinstance(w, dict) and w.get("kind") == "예정" and ref:
            ed = str(w.get("event_date") or "")[:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", ed) and ed < ref:
                out.append((f"flow.{w.get('id')}.kind", MSG_PAST_PLAN.format(ed, ref)))
    return out
