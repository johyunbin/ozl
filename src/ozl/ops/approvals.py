"""게시 승인 — 목록(정렬·접기), 주장과 원문 대목 짝짓기, 받지 못한 검토, 승인 요청 처리와 `approvals.jsonl`(설계 5절).

승인 규칙은 다시 짜지 않는다. 이슈는 `revisions.approve`, 그날의 화제와 복원판은 `units.approve_unit` 을 그대로 부르고,
그 함수의 거부(판·해시 불일치, 게시 대기가 아님, 검토 없음)를 HTTP 상태로 옮기기만 한다.
원문 대목은 근거 기록의 `observed` 만 쓴다. 원문 사본(captures/) 파일은 읽지 않는다.
잠금 순서는 "운영 잠금 → 이슈 잠금"이다(승인 함수가 안에서 이슈 잠금을 건다).
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime

from ozl.issues import digest, model, paths, revisions, rules, units
from ozl.issues import reviews as RV

from . import actions, auth, store

APPROVALS_FILE = "approvals.jsonl"
MSG = {12: "승인했다. 발행 목록에 한 줄을 더했다.", 13: "이미 승인된 판이다. 발행 목록은 그대로다."}
CODE_HTTP = {0: 303, 1: 422, 2: 400, 3: 409}
TARGET_RE = {"issue": r"i[0-9]{8}-[0-9]{2}", "day": r"[0-9]{4}-[0-9]{2}-[0-9]{2}", "restored": r"[0-9]{4}-[0-9]{2}-[0-9]{2}"}
REV_RE = r"[1-9][0-9]{0,3}"
HASH_RE = r"[0-9a-f]{32,64}"
SENS_WORD = {"정치": "정치", "선거": "선거", "형사": "형사", "연예": "연예", "건강": "건강"}
PRIVATE_KINDS = ("공인의 사생활", "일반인")
NEED_CMP = "다른 모델의 문장 대조(같은 계열, 쓴 모델과 다른 모델)"
NEED_ITP = "다른 계열의 해석 점검"
NEED_OBJ = "남은 지적이나 반려를 고친 뒤의 수정 확인"
UNIT_LABEL = {"day": "그날의 화제", "restored": "복원판"}


# ---------- 받지 못한 검토 (revisions 의 검토 조건과 같은 규칙을 읽기 전용으로) ----------

def _passing(reviews: list, h: str, drafted) -> tuple[bool, bool]:
    cmp = any(r.get("kind") == "문장 대조" and r.get("family") == "anthropic" and not RV._same(r.get("by_model"), drafted)
              and r.get("result") == "통과" and r.get("content_hash") == h for r in reviews)
    itp = any(r.get("kind") == "해석 점검" and r.get("family") not in (None, "anthropic") and r.get("result") == "통과"
              and r.get("content_hash") == h for r in reviews)
    return cmp, itp


def missing_reviews(issue: dict, evs: dict) -> list[str]:
    """지금 내용 해시로 받지 못한 검토의 이름. 빈 목록 ⇔ `revisions.review_state` 가 '검토 완료'.
    규칙은 이슈 패키지의 공개 함수(`ozl.issues.reviews.missing_reviews`) 하나를 쓴다."""
    return RV.missing_reviews(issue, evs)


def got_reviews(issue: dict) -> list[dict]:
    iid = issue.get("issue_id")
    return [{"kind": r.get("kind"), "model": r.get("by_model"), "result": r.get("result"), "at": r.get("at"),
             "notes_ok": RV._notes_ok(iid, r)} for r in issue.get("reviews") or [] if isinstance(r, dict)]


# ---------- 한 건의 표시 ----------

@dataclass
class EvRow:
    stance: str
    observed: str | None
    publisher: str
    title: str
    host: str
    accessed: str
    found: bool


@dataclass
class ClaimRow:
    cid: str
    gist: str
    verdict: str
    searched: str
    uncertain: list[str]
    evidence: list[EvRow]
    public: bool
    counter: bool
    disputed: bool
    parts: list["ClaimRow"] = field(default_factory=list)
    party: str | None = None
    scope: str = ""            # 확인한 범위(판정이 어디까지를 확인한 것인지 — 독자 화면에도 판정 아래에 나간다)
    publish: str = ""          # 게시 가부 값 그대로(게시 가능, 보류, 공개 제외). 작은 주장은 빈 글


@dataclass
class IssueCard:
    issue_id: str
    rev: int
    title: str
    work_state: str
    content_hash: str
    personal: bool
    false_verdict: bool
    flagged: bool
    disputed: bool
    counter: bool
    sensitive: list[str]
    changed: list[str]
    errors: list[str]
    warnings: list[str]
    missing: list[str]
    got: list[dict]
    claims: list[ClaimRow]
    hidden_claims: int

    @property
    def open(self) -> bool:
        return self.personal or self.false_verdict or self.flagged or self.disputed

    @property
    def sort_key(self) -> tuple:
        return (not self.personal, not self.false_verdict, not self.flagged, self.issue_id)

    def flag_words(self) -> list[str]:
        out = [w for w, on in (("개인 언급", self.personal), ("사실과 다름", self.false_verdict), ("점검에 걸림", self.flagged),
                               ("다툼", self.disputed), ("반대 근거", self.counter)) if on]
        if self.sensitive:
            out.append("민감: " + ", ".join(self.sensitive))
        if self.hidden_claims:
            out.append(f"공개 제외 주장 {self.hidden_claims}개")
        return out


def _host(url) -> str:
    try:
        return urllib.parse.urlsplit(str(url or "")).hostname or ""
    except ValueError:
        return ""


def _ev_rows(item: dict, evs: dict) -> list[EvRow]:
    out = []
    for e in item.get("evidence") or []:
        if not isinstance(e, dict):
            continue
        ev = evs.get(e.get("id")) or {}
        src = ev.get("source") if isinstance(ev.get("source"), dict) else {}
        obs = ev.get("observed")
        out.append(EvRow(stance=str(e.get("stance") or ""), observed=obs if isinstance(obs, str) and obs.strip() else None,
                         publisher=str(src.get("publisher") or ""), title=str(src.get("title") or ""), host=_host(src.get("url")),
                         accessed=str(src.get("accessed") or ""), found=bool(ev)))
    return out


def _uncertain(c: dict) -> list[str]:
    out = []
    ur = c.get("unverified_reasons")
    if isinstance(ur, list) and ur:
        out.append("확인하지 못한 까닭: " + ", ".join(map(str, ur)))
    for k, label in (("would_decide", "판정을 가를 자료"), ("not_found", "찾지 못한 것")):
        v = c.get(k)
        if isinstance(v, str) and v.strip():
            out.append(f"{label}: {v.strip()}")
    return out


def _party(c: dict, evs: dict) -> str | None:
    pp = c.get("party_position")
    if not isinstance(pp, dict):
        return None
    if pp.get("none"):
        return f"입장을 찾지 못했다({pp.get('checked_at') or '확인 시각 없음'})"
    text = str(pp.get("text") or "").strip()
    if not text:
        return None
    ev = evs.get(pp.get("evidence")) or {}
    src = ev.get("source") if isinstance(ev.get("source"), dict) else {}
    where = src.get("publisher") or ""
    return text + (f" (근거: {where})" if where else "")


def _claim_row(c: dict, evs: dict, issue: dict) -> ClaimRow:
    ev = _ev_rows(c, evs)
    stances = {e.stance for e in ev}
    parts = [_claim_row(p, evs, issue) for p in c.get("parts") or [] if isinstance(p, dict)]
    counter = "반대" in stances or any(p.counter for p in parts)
    disputed = ({"지지", "반대"} <= stances or c.get("verdict") == "일부 맞음"
                or any(p.disputed for p in parts))
    return ClaimRow(cid=str(c.get("id") or ""), gist=str(c.get("gist") or ""), verdict=str(c.get("verdict") or ""),
                    searched=str(c.get("searched") or ""), uncertain=_uncertain(c), evidence=ev,
                    public=rules.item_public(issue, c) if "publish" in c else True, counter=counter, disputed=disputed,
                    parts=parts, party=_party(c, evs), scope=str(c.get("scope") or ""),
                    publish=str(c.get("publish") or ""))


def _items(issue: dict):
    for lst in ("facts", "claims", "flow", "stances", "figures", "open_questions"):
        for it in issue.get(lst) or []:
            if isinstance(it, dict):
                yield it
                for p in it.get("parts") or [] if lst == "claims" else []:
                    if isinstance(p, dict):
                        yield p


def _changed(issue: dict, man: dict) -> list[str]:
    prev = [e for e in revisions.entries(man, "issue", issue.get("issue_id")) if int(e.get("rev") or 0) < int(issue.get("revision") or 0)]
    if not prev:
        return []
    try:
        before = model.load_yaml(revisions.rev_dir(issue["issue_id"], prev[-1]["rev"]) / "issue.yaml")
    except (OSError, ValueError):
        return []
    return digest.changed_fields(before, issue)


def issue_card(issue: dict, evs: dict, man: dict) -> IssueCard:
    claims = [c for c in issue.get("claims") or [] if isinstance(c, dict)]
    rows = [_claim_row(c, evs, issue) for c in claims]
    allc = rows + [p for r in rows for p in r.parts]
    r = revisions.check_with_manifest(issue, evs, public=True, man=man)
    review = revisions.review_state(issue, evs)
    pub_state = (issue.get("publish") or {}).get("state") if isinstance(issue.get("publish"), dict) else None
    sens = [SENS_WORD.get(str(s), str(s)) for s in issue.get("sensitive") or []]
    personal = any(it.get("target_kind") in PRIVATE_KINDS for it in _items(issue)) or any(c.get("allegation") is True for c in claims)
    t = issue.get("titles") if isinstance(issue.get("titles"), dict) else {}
    return IssueCard(
        issue_id=str(issue.get("issue_id")), rev=int(issue.get("revision") or 0), title=str(t.get("chosen") or "제목 정리 전"),
        work_state=str(issue.get("work_state") or ""), content_hash=digest.content_hash(issue, evs), personal=personal,
        false_verdict=any(x.verdict == "사실과 다름" for x in allc),
        flagged=bool(r["errors"] or r["warnings"]) or review == "검토 대기" or pub_state != "게시 가능",
        disputed=any(x.disputed for x in allc), counter=any(x.counter for x in allc), sensitive=sens,
        changed=_changed(issue, man), errors=list(r["errors"]), warnings=list(r["warnings"]), missing=missing_reviews(issue, evs),
        got=got_reviews(issue), claims=rows, hidden_claims=sum(1 for x in rows if not x.public))


# ---------- 목록 ----------

@dataclass
class UnitRow:
    unit: str
    date: str
    rev: object
    content_hash: str
    errors: list[str]
    warnings: list[str]
    n_items: int


@dataclass
class ApproveView:
    issues: list[IssueCard]
    not_ready: list[tuple[str, str, str]]       # (번호, 제목, 작업 상태)
    units: dict[str, list[UnitRow]]
    error: str | None = None

    @property
    def n_pending(self) -> int:
        return len(self.issues) + sum(len(v) for v in self.units.values())


def _n_items(unit: str, d: dict) -> int:
    if unit == "restored":
        return len(d.get("items") or [])
    return sum(len(d.get(k) or []) for k in ("new", "ongoing", "upcoming", "pre") if isinstance(d.get(k), list))


def build_view() -> ApproveView:
    try:
        man = revisions.load_manifest()
    except (OSError, ValueError) as e:
        return ApproveView([], [], {u: [] for u in units.UNITS}, error=type(e).__name__)
    cards, waiting = [], []
    for iid in model.all_issue_ids():
        try:
            issue, evs = model.load_issue(iid), model.load_evidences(iid)
        except (OSError, ValueError):
            waiting.append((iid, "읽지 못했다", "정리 전"))
            continue
        ws = str(issue.get("work_state") or "")
        title = str((issue.get("titles") or {}).get("chosen") or "제목 정리 전") if isinstance(issue.get("titles"), dict) else "제목 정리 전"
        if ws != "게시 대기":
            if ws in ("검토 대기", "작성 중"):
                waiting.append((iid, title, ws))
            continue
        h = digest.content_hash(issue, evs)
        if any(e.get("content_hash") == h and e.get("rev") == issue.get("revision") for e in revisions.entries(man, "issue", iid)):
            continue
        cards.append(issue_card(issue, evs, man))
    cards.sort(key=lambda c: c.sort_key)
    urows: dict[str, list[UnitRow]] = {}
    for unit in units.UNITS:
        urows[unit] = []
        for date in units.all_dates(unit):
            try:
                d = units.load_unit(unit, date)
            except (OSError, ValueError):
                continue
            h = units.unit_hash(unit, d)
            if any(e.get("content_hash") == h and e.get("rev") == d.get("revision") for e in revisions.entries(man, unit, date)):
                continue
            ck = units.check_unit(unit, d, date)
            urows[unit].append(UnitRow(unit, date, d.get("revision"), h, ck["errors"], ck["warnings"],
                                       _n_items(unit, d) if isinstance(d, dict) else 0))
    return ApproveView(cards, waiting, urows)


# ---------- 승인 요청 ----------

@dataclass
class Result:
    http: int
    m: int = 0
    lines: list[str] = field(default_factory=list)


def parse(form: dict) -> dict:
    if not auth.request_id_ok(form.get("request_id")):
        raise actions.BadForm("request_id")
    if set(form) - {"kind", "target", "rev", "hash", "request_id", "csrf"}:
        raise actions.BadForm("extra")
    kind = form.get("kind")
    if kind not in TARGET_RE:
        raise actions.BadForm("kind")
    f = {"action": "approve", "kind": kind, "target": form.get("target") or "", "rev": form.get("rev") or "",
         "hash": form.get("hash") or ""}
    for k, rx in (("target", TARGET_RE[kind]), ("rev", REV_RE), ("hash", HASH_RE)):
        if not re.fullmatch(rx, f[k]):
            raise actions.BadForm(k)
    return f


def _screen_lines(msg: str) -> list[str]:
    """승인 함수의 문구 가운데 화면에 보여도 되는 줄(경로처럼 보이는 줄은 뺀다)."""
    return [x.strip() for x in str(msg or "").splitlines() if x.strip() and "/" not in x and "\\" not in x][:20]


def _replay(rid: str, m: int) -> Result:
    if m in MSG:
        return Result(303, m)
    for r in store.read_jsonl(store.ops_file(APPROVALS_FILE)):
        if r.get("request_id") == rid:
            return Result(int(r.get("http") or 409), 0, _screen_lines(r.get("msg", "")))
    return Result(409)


def handle(form: dict, *, now: datetime, index: store.RequestIndex, approver: str) -> Result:
    f = parse(form)
    rid, fp = form["request_id"], store.fingerprint(f)
    store.require_safe_root()        # 실제 자료 루트를 다른 철자로 가리키면 시험 승인 이름으로 실제 목록에 쓰게 된다
    by = approver if paths.is_real_root() else revisions.TEST_BY     # 화면에서 받지 않는다
    with store.ops_lock():
        seen = index.lookup(rid)
        if seen is not None:
            if seen[0] != fp:
                raise actions.Conflict("same id, different content")
            return _replay(rid, seen[1])
        rev = int(f["rev"])
        if f["kind"] == "issue":
            out = revisions.approve(f["target"], rev, f["hash"], by, request_id=rid)
        else:
            out = units.approve_unit(f["kind"], f["target"], rev, f["hash"], by, request_id=rid)
        code = int(out.get("code", 2))
        http = CODE_HTTP.get(code, 400)
        m = (13 if "이미 승인됨" in str(out.get("msg")) else 12) if code == 0 else 0
        at = store.iso(now)
        store.append_jsonl(store.ops_file(APPROVALS_FILE), {
            "at": at, "request_id": rid, "kind": f["kind"], "target": f["target"], "rev": rev, "content_hash": f["hash"],
            "by": by, "code": code, "http": http, "msg": str(out.get("msg") or ""), "fp": fp, "m": m})
        store.append_jsonl(store.ops_file(actions.ACTIONS_FILE), {
            "at": at, "request_id": rid, "action": "approve", "key": f"{f['kind']}:{f['target']}", "title": None, "deck": False,
            "result": "처리" if code == 0 else f"거부({http})", "fp": fp, "m": m})
        index.remember(rid, fp, m)
    return Result(http, m, [] if code == 0 else _screen_lines(out.get("msg", "")))
