"""조합표 — 문장의 종류(1단계), 근거 한 건이 받칠 수 있는 조건(가·나·다), 판정이 성립하는가(2단계), 게시 가부(3단계).

판정 규칙은 주장-근거 연결 칸(passage_role, period, refers_to_original, addresses_cause)을 믿고 판정한다. 코드는 이 칸이
원문과 맞는지 모르므로, 칸이 비면 통과시키지 않고 거부한다(빈 값을 '해당 없음'으로 읽지 않는다). 이 칸들이 원문과 맞는지는 검토가 본다.
원문 사본 재검사 결과(copy_errs: {근거 번호: 오류 목록})는 check 가 evidence.copy_errors 로 만들어 넘긴다. 목록에 없는 근거는
재검사하지 않은 것으로 보고 (가)(나)(다)로 세지 않는다.
"""
from __future__ import annotations

import re

from ozl.research import cards

from . import model

SENTENCE_KINDS = {
    "발표와 조치": {"where": "facts", "verdict": False},          # 발표가 있었는지가 다툼이면 claims 의 '발표 여부'
    "발표 여부":   {"where": "claims", "verdict": True},
    "사실":        {"where": "claims", "verdict": True},
    "수치":        {"where": "claims", "verdict": True},           # 기간·단위에 '해당 없음'을 받지 않는다(_judge)
    "인과":        {"where": "claims", "verdict": True},           # 원인 문서 검사(_cause_ok)
    "평가":        {"where": "stances", "verdict": False},
    "전망":        {"where": "stances", "verdict": False},
}
CLAIM_KINDS = ("발표 여부", "사실", "수치", "인과")
STANCE_KINDS = model.STANCE_KINDS
BASIS_REQ = {
    "가": {"speaker_role": {"제3기관"}, "authority": True, "doc_stage": {"확정된 판단"}, "transcribed": False,
           "passage_role": {"작성자의 판단"}, "court_final": True, "not_doc_kind": {"수사 절차"},
           "ev_kind": {"공식 원문", "기관 자료"}},
    "나": {"speaker_role": {"당사자"}, "admission_kind": "인정", "against_interest": True, "transcribed": False,
           "scope_equals_admission": True},
    # 언론 공개 원자료는 프로그램이 사본을 다시 대조하지 못하므로 판정의 근거로 세지 않는다(2026-11-14 검토 반영).
    "다": {"refers_to_original": True, "ev_kind": {"공식 원문", "기관 자료"}},
}
CAUSE_DOC_KINDS = {"판결", "조사 보고서", "원인 발표"}
VERDICTS = ("확인", "일부 맞음", "사실과 다름", "확인 못 함")
UNVERIFIED_REASONS = ("핵심 근거를 구하지 못함", "근거끼리 어긋남", "절차가 끝나지 않음", "확인할 방법이 없음")
PART_VERDICTS = ("확인", "사실과 다름", "확인 못 함")
VERDICT_NEEDS = {
    "확인":        {"counter_searched": True, "support": {"가", "나", "다"}, "no_counter": {"가", "다"}},
    "사실과 다름": {"counter_searched": True, "oppose": {"가", "다"}},
    "일부 맞음":   {"parts_min": 2, "core_needs_confirmed": True},
    "확인 못 함":  {"reasons_min": 1, "fields": ("searched", "would_decide")},
}
PUBLISH_STATES = model.PUBLISH_STATES
TARGET_KINDS = model.TARGET_KINDS
TARGET_MUST_EXCLUDE = {"공인의 사생활", "일반인"}   # 이 대상의 항목은 publish 가 '공개 제외' 여야 한다
OFFICIAL = ("공식 원문", "기관 자료")
DISCLOSURE_LABEL = "회사 공시 기준"

MSG_DENIAL_ONLY = "당사자의 부인만으로는 '사실과 다름'을 붙이지 않는다"
MSG_INVESTIGATION = "조사 중인 문서로는 판정하지 않는다 — '확인 못 함'(절차가 끝나지 않음)으로 둔다"
MSG_TRANSCRIBED = "옮겨 적힌 당사자 주장은 그 문서의 판단이 아니다"
MSG_UNFINAL = "확정되지 않은 판결로는 판정하지 않는다 — '확인 못 함'(절차가 끝나지 않음)으로 둔다"
MSG_UNVERIFIED = ("'확인 못 함'은 사유(" + ", ".join(UNVERIFIED_REASONS) + " 중 하나 이상)와 찾아본 범위, "
                  "무엇이 나오면 판정할 수 있는지를 적는다")
MSG_PRIVATE = "대상이 일반인(공인의 사생활)인 항목은 '공개 제외'로 둔다"
MSG_SIDE_ONLY = "핵심이 틀린 주장에는 '일부 맞음'을 붙이지 않는다 — '사실과 다름'으로 두고 맞는 곁가지를 설명에 적는다"
MSG_CAUSE = "인과 주장은 원인과 결과를 직접 판단한 근거(조사 보고서, 원인 발표, 판결)가 있을 때만 판정한다"
MSG_REASON = "다루는 이유가 비어 있으면 게시할 수 없다"
MSG_EVENT = "사건이 1차 원문으로 확인되기 전에는 그 사건을 전제로 판정하지 않는다"
MSG_EVAL = "평가와 전망은 판정하지 않는다 — 입장 칸으로"
MSG_NO_SUPPORT = ("'확인'은 권한 있는 기관의 확정 판단, 당사자가 스스로에게 불리하게 인정한 것, 원자료 직접 대조 가운데 하나로 "
                  "받친 지지 근거가 있어야 한다 — 보도만으로는 판정하지 않는다")
MSG_NO_OPPOSE = "'사실과 다름'은 권한 있는 기관의 확정 판단이나 원자료 직접 대조로 받친 반대 근거가 있어야 한다"
MSG_COUNTER = "'확인'과 '사실과 다름'은 반대 자료를 찾아본 뒤에만 붙인다(counter_searched: true)"
MSG_DISCLOSURE = "회사 공시 수치로 '확인'하면 판정 옆 표시에 '회사 공시 기준'을 붙인다(basis_label)"
MSG_ALLEGATION = "범죄·비위 의혹은 수사기관이나 법원의 확정 문서 없이 판정하지 않는다 — '확인 못 함'으로 둔다"
MSG_SO_FAR = "'사실과 다름' 판정({})은 지금까지 3줄에 적는다"
MSG_PROCEDURE = "수사 절차 문서는 그 절차가 있었다는 것만 받친다(about_procedure) — 혐의 내용의 확정 판단이 아니다"
MSG_RAW = "언론 공개 원자료는 프로그램이 원문을 다시 대조하지 못하므로 판정의 근거로 세지 않는다"
MSG_PART_KIND = "작은 주장의 종류(kind)는 " + ", ".join(CLAIM_KINDS) + " 가운데 하나다"
MSG_PART_KIND_LOCK = "핵심 작은 주장과 인과 주장의 작은 주장은 주장의 종류를 바꾸지 않는다"
MSG_PREMISE = "사건이 1차 원문으로 확인되지 않았으면 판정한 주장마다 사건을 전제로 하는지(premise_event: 참·거짓)를 적는다"
MSG_NUM_NA = "수치 주장의 {}에는 '해당 없음'을 쓰지 않는다 — 기간과 단위를 맞춰 적는다"
MSG_REF_HIDDEN = "제목과 지금까지 3줄이 기대는 주장({})은 게시되는 주장이어야 한다"
LABEL = {"subject": "대상", "period": "기간", "scope": "범위", "unit": "단위"}


def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def _doc(ev) -> dict:
    d = ev.get("doc") if isinstance(ev, dict) else None
    return d if isinstance(d, dict) else {}


# ── 연결 한 건 ────────────────────────────────────────────────────────
def link_field_errors(link, claim) -> list[str]:
    """연결 칸의 모양(필수와 허용 값). 빈 연결 칸은 거부한다."""
    if not isinstance(link, dict):
        return ["근거 연결은 사전이다"]
    e = []
    for k, allowed in (("stance", model.STANCES), ("basis", model.BASES), ("passage_role", model.PASSAGE_ROLES)):
        if link.get(k) not in allowed:
            e.append(f"연결의 {k} 값 '{link.get(k)}'은 허용 값({', '.join(allowed)})이 아니다")
    if link.get("basis") == "다" and not isinstance(link.get("refers_to_original"), bool):
        e.append("근거 조건 (다)는 refers_to_original(참·거짓)을 적는다")
    if claim.get("kind") == "인과" and not isinstance(link.get("addresses_cause"), bool):
        e.append("인과 주장의 근거 연결은 addresses_cause(참·거짓)를 적는다")
    return e


def link_mismatch(link, claim) -> list[str]:
    """연결의 대상·기간·범위(수치면 단위)가 주장과 같은가. 다르면 그 연결은 근거가 아니다(6-4)."""
    out = []
    keys = ("subject", "period", "scope") + (("unit",) if claim.get("kind") == "수치" else ())
    for k in keys:
        a, b = link.get(k), claim.get(k)
        if cards._blank(a):
            out.append(f"근거 연결의 {LABEL[k]} 칸이 비어 있다 — 비우지 않고 '{model.NA}'은 글자로 적는다")
        elif k == "period":
            if cards._period_key(a) != cards._period_key(b):
                out.append(f"근거의 기간({a})과 주장의 기간({b})이 다르다 — 일부 기간을 전체로 넓히지 않는다")
        elif norm(a) != norm(b):
            out.append(f"근거의 {LABEL[k]}({a})과 주장의 {LABEL[k]}({b})이 다르다 — 일부 {LABEL[k]}을 전체로 넓히지 않는다")
    return out


def basis_ok(link: dict, ev: dict | None, claim: dict, copy_errs: dict | None = None) -> tuple[bool, str]:
    """연결이 내세운 근거 조건(가·나·다)을 그 근거가 채우는가. (참, '') 또는 (거짓, 사유)."""
    b = link.get("basis")
    if b not in BASIS_REQ:
        return False, "근거 조건을 내세우지 않았다"
    if not isinstance(ev, dict):
        return False, "근거 기록이 없다"
    doc, kind = _doc(ev), ev.get("kind")
    if kind == "보도":
        return False, "보도는 판정의 근거로 세지 않는다"
    if doc.get("doc_stage") == "조사 중":
        return False, MSG_INVESTIGATION
    errs = (copy_errs or {}).get(ev.get("evidence_id"))
    if errs is None:
        return False, "원문 재검사를 하지 않은 근거다"
    if errs:
        return False, "원문 재검사를 통과하지 못했다 — " + errs[0]
    req = BASIS_REQ[b]
    # 문서 쪽 방어는 (가)(나)(다) 모두에 적용한다 — 조건 글자를 바꿔 피해 가지 못하게.
    if cards._blank(link.get("passage_role")):
        return False, "연결 칸 passage_role 이 비어 있다"
    if link.get("passage_role") == "당사자 주장을 옮긴 것" or doc.get("transcribed") is not False \
            or doc.get("doc_stage") == "한쪽 주장을 옮긴 것":
        return False, MSG_TRANSCRIBED
    if doc.get("doc_kind") == "판결" and (doc.get("court") or {}).get("final") is not True:
        return False, MSG_UNFINAL
    if doc.get("doc_kind") == "수사 절차" and claim.get("about_procedure") is not True:
        return False, MSG_PROCEDURE
    if kind == "언론 공개 원자료":
        return False, MSG_RAW
    adm = doc.get("admission") if isinstance(doc.get("admission"), dict) else {}
    if link.get("stance") == "반대" and adm.get("kind") == "부인":
        return False, "당사자의 부인은 반대 근거가 아니다 — " + MSG_DENIAL_ONLY
    if b == "가":
        if doc.get("speaker_role") not in req["speaker_role"] or doc.get("authority") is not True:
            return False, "권한 있는 제3기관의 문서가 아니다"
        if doc.get("doc_stage") not in req["doc_stage"]:
            return False, "확정된 판단이 아니다"
        if link.get("passage_role") not in req["passage_role"]:
            return False, "대조한 대목이 작성자의 판단이 아니다"
        if kind not in req["ev_kind"]:
            return False, "공식 원문이나 기관 자료가 아니다"
        return True, ""
    if b == "나":
        if doc.get("speaker_role") not in req["speaker_role"]:
            return False, "당사자의 문서가 아니다"
        if adm.get("kind") == "부인":
            return False, "당사자의 부인은 인정이 아니다 — " + MSG_DENIAL_ONLY
        if adm.get("kind") != req["admission_kind"] or adm.get("against_interest") is not True:
            return False, "당사자가 자기에게 불리한 사실을 인정한 문서가 아니다"
        if norm(link.get("scope")) != norm(adm.get("scope")):
            return False, f"당사자가 인정한 범위({adm.get('scope')})와 연결의 범위({link.get('scope')})가 다르다 — 인정한 범위까지만 근거로 센다"
        return True, ""
    if link.get("refers_to_original") is not True:
        return False, "주장이 바로 이 원자료를 가리키지 않는다(refers_to_original)"
    if kind not in req["ev_kind"]:
        return False, "원자료가 아니다"
    return True, ""


def classify(claim: dict, evidences: dict, copy_errs: dict | None) -> tuple[list[dict], list[tuple[str, str]]]:
    """연결마다 {link, ev, counted(가·나·다 | None), mismatch} 와, 내세운 조건을 못 채운 연결의 오류 [(칸, 문구)]."""
    infos, errs = [], []
    for link in claim.get("evidence") or []:
        if not isinstance(link, dict):
            errs.append(("evidence", "근거 연결은 사전이다"))
            continue
        lid = link.get("id")
        ev = evidences.get(lid)
        where = f"evidence.{lid}"
        errs += [(where, m) for m in link_field_errors(link, claim)]
        if ev is None:
            errs.append((where, "근거 기록이 없다"))
        mis = link_mismatch(link, claim)
        counted = None
        if link.get("basis") in BASIS_REQ and ev is not None:
            ok, why = basis_ok(link, ev, claim, copy_errs)
            if not ok:
                errs.append((where, why))
            elif not mis:
                counted = link["basis"]
        infos.append({"link": link, "ev": ev, "counted": counted, "mismatch": mis})
    return infos, errs


# ── 판정 ──────────────────────────────────────────────────────────────
def _cause_ok(infos) -> bool:
    """원인을 직접 판단한 문서인가. 권한 있는 제3기관의 확정 판단(판결이면 확정)이거나, (나)로 센 당사자의 불리한 인정만 받는다
    — 당사자가 스스로 낸 '원인 발표'를 (다)로 올려 인과를 확인하지 못하게."""
    for i in infos:
        d = _doc(i["ev"])
        if d.get("doc_kind") not in CAUSE_DOC_KINDS or i["link"].get("addresses_cause") is not True:
            continue
        third = d.get("speaker_role") == "제3기관" and d.get("authority") is True and d.get("doc_stage") == "확정된 판단" \
            and (d.get("doc_kind") != "판결" or (d.get("court") or {}).get("final") is True)
        if third or i["counted"] == "나":
            return True
    return False


def _judge(cl: dict, issue: dict | None, copy_errs, evidences) -> list[tuple[str, str]]:
    infos, errs = classify(cl, evidences, copy_errs)
    kind, v = cl.get("kind"), cl.get("verdict")
    if kind in ("평가", "전망"):
        return errs + [("kind", MSG_EVAL)]
    if v == "확인 못 함":
        rs = cl.get("unverified_reasons")
        if not isinstance(rs, list) or not rs or any(r not in UNVERIFIED_REASONS for r in rs) \
                or cards._blank(cl.get("searched")) or cards._blank(cl.get("would_decide")):
            errs.append(("verdict", MSG_UNVERIFIED))
        return errs
    if v not in ("확인", "사실과 다름"):
        return errs
    if kind == "수치":
        for k, name in (("period", "기간"), ("unit", "단위")):
            if norm(cl.get(k)) == norm(model.NA):
                errs.append((k, MSG_NUM_NA.format(name)))
    if ((issue or {}).get("event_check") or {}).get("confirmed") is not True and not isinstance(cl.get("premise_event"), bool):
        errs.append(("premise_event", MSG_PREMISE))
    stance = "지지" if v == "확인" else "반대"
    mine = [i for i in infos if i["link"].get("stance") == stance]
    good = [i for i in mine if i["counted"] in (VERDICT_NEEDS[v].get("support") or VERDICT_NEEDS[v].get("oppose"))]
    if cl.get("counter_searched") is not True:
        errs.append(("counter_searched", MSG_COUNTER))
    if cards._blank(cl.get("searched")):
        errs.append(("searched", "찾아본 범위(searched)를 적는다"))
    if cl.get("premise_event") is True and ((issue or {}).get("event_check") or {}).get("confirmed") is not True:
        errs.append(("verdict", MSG_EVENT))
    if cl.get("allegation") is True and not any(i["counted"] == "가" for i in infos):
        errs.append(("verdict", MSG_ALLEGATION))
    if v == "사실과 다름" and not good and kind == "발표 여부":
        good = [i for i in mine if i["ev"] and _doc(i["ev"]).get("denies_own_document") is True and i["ev"].get("kind") in OFFICIAL
                and norm(_doc(i["ev"]).get("speaker")) == norm(cl.get("attributed_to")) and not cards._blank(cl.get("attributed_to"))
                and not i["mismatch"] and (copy_errs or {}).get(i["ev"].get("evidence_id")) == []]
    if not good:
        if v == "사실과 다름" and any((_doc(i["ev"]).get("admission") or {}).get("kind") == "부인" for i in mine if i["ev"]):
            errs.append(("verdict", MSG_DENIAL_ONLY))
        elif any(_doc(i["ev"]).get("doc_stage") == "조사 중" for i in mine if i["ev"]):
            errs.append(("verdict", MSG_INVESTIGATION))
        else:
            errs.append(("verdict", MSG_NO_SUPPORT if v == "확인" else MSG_NO_OPPOSE))
        errs += [("verdict", m) for i in mine for m in i["mismatch"]]
        return errs
    if kind == "인과" and not _cause_ok(good):
        errs.append(("verdict", MSG_CAUSE))
    if v == "확인":
        if any(i["counted"] in VERDICT_NEEDS["확인"]["no_counter"] for i in infos if i["link"].get("stance") == "반대"):
            errs.append(("verdict", "확정 판단이나 원자료 대조로 받친 반대 근거가 있으면 '확인'을 붙이지 않는다 — 근거끼리 어긋나면 '확인 못 함'"))
        if kind == "수치" and any(_doc(i["ev"]).get("speaker_role") == "당사자" and _doc(i["ev"]).get("doc_kind") == "공시" for i in good) \
                and cl.get("basis_label") != DISCLOSURE_LABEL:
            errs.append(("basis_label", MSG_DISCLOSURE))
    return errs


PART_OVERRIDE = ("kind", "subject", "period", "scope", "unit")


def part_view(claim: dict, part: dict) -> dict:
    """작은 주장을 판정하려고 만든 주장 모양. 대상·기간·범위·단위·종류는 작은 주장에 있으면 그것, 없으면 주장의 것."""
    v = {k: claim.get(k) for k in ("kind", "subject", "period", "scope", "unit", "counter_searched", "searched", "basis_label",
                                   "allegation", "premise_event", "attributed_to", "about_procedure")}
    v.update({k: part[k] for k in PART_OVERRIDE if k in part})
    v.update(verdict=part.get("verdict"), evidence=part.get("evidence") or [], unverified_reasons=part.get("unverified_reasons"),
             would_decide=part.get("would_decide"))
    return v


def verdict_errors(claim: dict, evidences: dict, copy_errs: dict | None = None, issue: dict | None = None) -> list[tuple[str, str]]:
    """주장 하나의 판정이 성립하는가. [(주장 안의 칸 경로, 문구)] — check 가 'claims.<id>.' 를 앞에 붙인다."""
    v = claim.get("verdict")
    if claim.get("kind") in ("평가", "전망"):
        return [("kind", MSG_EVAL)]
    if v not in VERDICTS:
        return [("verdict", f"verdict 값 '{v}'은 허용 값({', '.join(VERDICTS)})이 아니다")]
    if v != "일부 맞음":
        return _judge(claim, issue, copy_errs, evidences)
    errs: list[tuple[str, str]] = []
    errs += [(p, m) for p, m in classify(claim, evidences, copy_errs)[1]]
    parts = [p for p in claim.get("parts") or [] if isinstance(p, dict)]
    if len(parts) < VERDICT_NEEDS["일부 맞음"]["parts_min"]:
        return errs + [("parts", "'일부 맞음'은 작은 주장을 둘 이상으로 나눈다")]
    for p in parts:
        pid = p.get("id")
        if not (isinstance(pid, str) and re.match(r"^p[1-9]\d{0,2}$", pid)):
            errs.append(("parts", f"작은 주장 번호 '{pid}'가 p1 꼴이 아니다"))
        if p.get("verdict") not in PART_VERDICTS:
            errs.append((f"parts.{pid}.verdict", f"작은 주장의 판정은 {', '.join(PART_VERDICTS)} 가운데 하나다"))
            continue
        if not isinstance(p.get("core"), bool):
            errs.append((f"parts.{pid}.core", "작은 주장마다 핵심인지(core: 참·거짓)를 적는다"))
        pv = part_view(claim, p)
        if "kind" in p:
            if p["kind"] not in CLAIM_KINDS:
                errs.append((f"parts.{pid}.kind", MSG_PART_KIND))
                continue
            if p["kind"] != claim.get("kind") and (p.get("core") is True or claim.get("kind") == "인과"):
                errs.append((f"parts.{pid}.kind", MSG_PART_KIND_LOCK))
                continue
        errs += [(f"parts.{pid}.{k}", m) for k, m in _judge(pv, issue, copy_errs, evidences)]
    vs = [p.get("verdict") for p in parts]
    if "확인" not in vs or all(x == "확인" for x in vs):
        errs.append(("parts", "'일부 맞음'은 '확인'인 작은 주장과 '확인'이 아닌 작은 주장이 하나 이상씩 있어야 한다"))
    cores = [p for p in parts if p.get("core") is True]
    if not cores:
        errs.append(("parts", "핵심 작은 주장(core: true)을 하나 이상 정한다"))
    elif not any(p.get("verdict") == "확인" for p in cores):
        errs.append(("verdict", MSG_SIDE_ONLY))
    return errs


def evidence_label(claim: dict, evidences: dict, copy_errs: dict | None = None) -> str:
    """판정 옆 근거 종류 표시: 공식 원문 · 당사자 발표 · 원자료 대조 · 보도 n곳(맨 처음 매체, 근거: 종류) + basis_label."""
    views = [claim] + [part_view(claim, p) for p in claim.get("parts") or [] if isinstance(p, dict)]
    labels: list[str] = []
    reports: dict[str, dict] = {}
    for cl in views:
        for i in classify(cl, evidences, copy_errs)[0]:
            ev = i["ev"] or {}
            if ev.get("kind") == "보도":
                reports[ev.get("evidence_id")] = ev
            elif i["counted"] == "나":
                labels.append("당사자 발표")
            elif i["counted"] == "다" and ev.get("kind") == "언론 공개 원자료":
                labels.append("원자료 대조")
            elif i["counted"]:
                labels.append("공식 원문")
    if reports:
        evs = sorted(reports.values(), key=lambda e: (not (e.get("report") or {}).get("first_report"), str((e.get("report") or {}).get("read_at"))))
        first = evs[0].get("report") or {}
        kinds = list(dict.fromkeys(k for e in evs for k in (e.get("report") or {}).get("basis_kinds") or []))
        tail = f", 근거: {', '.join(kinds)}" if kinds else ""
        labels.append(f"보도 {len(evs)}곳(맨 처음 {first.get('outlet')}{tail})")
    out = ", ".join(dict.fromkeys(labels))
    if not cards._blank(claim.get("basis_label")):
        out = f"{out}, {claim['basis_label']}" if out else claim["basis_label"]
    return out


# 게시 가부(item_public, hidden_claims, publish_errors)는 publish 모듈에 있고 여기서 다시 내보낸다.
from .publish import hidden_claims, item_public, publish_errors  # noqa: E402,F401
