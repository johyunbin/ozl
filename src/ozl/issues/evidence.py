"""근거 기록 — 모양 검사, 원문 받기(capture_evidence), 기계 대조(machine_verify_evidence), 옛 클레임 모양으로 바꾼 사본(as_claim_view).

원문 사본의 경로 규칙·재해시·종류 재판별·글 뽑기·observed 대조·통째 대목·쓴 쪽과 재대조 쪽 분리·맥락 칸 대조는
cards.copy_source / cards.machine_check 를 그대로 쓴다(근거 기록을 클레임 모양으로 바꿔 넘긴다). 오류 문구 앞의 식별자는 근거 번호다.
사본·해시·다시 대조는 공식 원문과 기관 자료에만 적용한다. 보도는 주소, 제목, 매체, 읽은 시각, 근거 종류만 두고,
언론 공개 원자료는 사본 없이 주소, 받은 시각, 해시와 두 에이전트의 대목만 둔다.
"""
from __future__ import annotations

import copy
import pathlib
import re

from ozl.briefs.deck import _host, _is_comm_host
from ozl.research import capture as K
from ozl.research import cards

from . import ids, model, paths

EV_KINDS = ("공식 원문", "기관 자료", "보도", "언론 공개 원자료")
OFFICIAL = ("공식 원문", "기관 자료")
KIND_TIER = {"공식 원문": "T1", "기관 자료": "T2", "보도": "T3", "언론 공개 원자료": "T3"}
COMMON = {"evidence_id", "issue_id", "kind", "revision", "source", "doc"}
KIND_FIELDS = {"공식 원문": {"observed", "checks", "verification"}, "기관 자료": {"observed", "checks", "verification"},
               "보도": {"report"}, "언론 공개 원자료": {"raw"}}
SPEAKER_ROLES = ("제3기관", "당사자", "보도 매체", "기타")
DOC_KINDS = ("판결", "처분", "공식 통계", "조사 보고서", "원인 발표", "수사 절차", "공시", "보도자료", "기사", "원자료", "기타")
DOC_STAGES = ("확정된 판단", "조사 중", "한쪽 주장을 옮긴 것", "작성자 자신의 발표")
COURT_LEVELS = ("1심", "2심", "대법원", "헌법재판소", "기타")
ADMISSION_KINDS = ("인정", "부인")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

MSG_REPORT_BODY = "보도 근거에는 기사 본문을 두지 않는다(주소, 제목, 매체, 읽은 시각, 근거 종류만)"
MSG_COMMUNITY = "커뮤니티 글은 근거와 링크로 쓰지 않는다"


def community_url(url) -> bool:
    return bool(url) and _is_comm_host(_host(str(url)))


def _blank(v) -> bool:
    return cards._blank(v)


def as_claim_view(ev: dict) -> dict:
    """근거 기록을 cards.copy_source·machine_check 가 받는 클레임 모양으로 바꾼 사본(원본은 고치지 않는다)."""
    v = ev.get("verification")
    done = isinstance(v, dict) and not _blank(v.get("verified_at"))
    return {"claim_id": ev.get("evidence_id", "?"), "observed": ev.get("observed") or "", "source": copy.deepcopy(ev.get("source") or {}),
            "checks": copy.deepcopy(ev.get("checks") or {}), "verification": copy.deepcopy(v) if isinstance(v, dict) else v,
            "status": "verified" if done else "pending", "human_verified": False}


def with_capture_dir(ev: dict, captures_root) -> dict:
    """사본 경로(path·text_path)만 captures_root/<근거 번호>/ 아래로 고쳐 쓴 사본. sha256 은 그대로 둔다(판 고정 사본·시험이 쓴다)."""
    out = copy.deepcopy(ev)
    cap = ((out.get("verification") or {}).get("capture")) if isinstance(out.get("verification"), dict) else None
    if isinstance(cap, dict):
        d = pathlib.Path(captures_root) / str(out.get("evidence_id"))
        for k in ("path", "text_path"):
            if not _blank(cap.get(k)):
                cap[k] = paths.rel_or_abs(d / pathlib.Path(str(cap[k])).name)
    return out


# ── 모양 검사 ─────────────────────────────────────────────────────────
def _doc_errors(doc) -> list[tuple[str, str]]:
    if not isinstance(doc, dict):
        return [("doc", "doc 이 없다")]
    e: list[tuple[str, str]] = []
    if _blank(doc.get("speaker")):
        e.append(("doc.speaker", "doc.speaker 가 없다"))
    for k, allowed in (("speaker_role", SPEAKER_ROLES), ("doc_kind", DOC_KINDS), ("doc_stage", DOC_STAGES)):
        if doc.get(k) not in allowed:
            e.append((f"doc.{k}", f"doc.{k} 값 '{doc.get(k)}'은 허용 값({', '.join(allowed)})이 아니다"))
    for k in ("authority", "transcribed"):
        if not isinstance(doc.get(k), bool):
            e.append((f"doc.{k}", f"doc.{k} 는 참·거짓으로 적는다"))
    if "denies_own_document" in doc and not isinstance(doc["denies_own_document"], bool):
        e.append(("doc.denies_own_document", "doc.denies_own_document 는 참·거짓으로 적는다"))
    if doc.get("doc_kind") == "판결":
        ct = doc.get("court")
        if not isinstance(ct, dict) or ct.get("level") not in COURT_LEVELS or not isinstance(ct.get("final"), bool):
            e.append(("doc.court", f"판결 근거는 doc.court 에 심급({', '.join(COURT_LEVELS)})과 확정 여부(final)를 적는다"))
    adm = doc.get("admission")
    if adm is not None:
        if not isinstance(adm, dict) or adm.get("kind") not in ADMISSION_KINDS or _blank(adm.get("scope")) \
                or not isinstance(adm.get("against_interest"), bool):
            e.append(("doc.admission", "doc.admission 은 {kind: 인정|부인, scope, against_interest: 참·거짓} 꼴이다"))
    return e


def structure_errors(ev: dict, issue_id: str, file_id: str | None = None) -> list[tuple[str, str]]:
    """근거 기록 한 건의 모양 오류 [(칸 경로, 문구)] — 칸 경로는 근거 번호 아래(예: source.url)."""
    e: list[tuple[str, str]] = []
    eid = ev.get("evidence_id")
    if not ids.evidence_id_ok(eid, issue_id):
        e.append(("evidence_id", f"근거 번호 '{eid}'가 이 이슈의 근거 번호 꼴이 아니다"))
    if file_id is not None and eid != file_id:
        e.append(("evidence_id", f"파일 이름({file_id})과 근거 번호가 다르다"))
    if ev.get("issue_id") != issue_id:
        e.append(("issue_id", f"issue_id 가 {issue_id} 가 아니다"))
    kind = ev.get("kind")
    if kind not in EV_KINDS:
        return e + [("kind", f"kind 값 '{kind}'은 허용 값({', '.join(EV_KINDS)})이 아니다")]
    extra = set(ev) - COMMON - KIND_FIELDS[kind]
    if extra:
        msg = MSG_REPORT_BODY if kind == "보도" else f"{kind} 근거에 둘 수 없는 칸이 있다"
        e.append((",".join(sorted(extra)), msg))
    src = ev.get("source")
    if not isinstance(src, dict):
        return e + [("source", "source 가 없다")]
    url = str(src.get("url") or "")
    if not re.match(r"^https?://[^/\s]+", url):
        e.append(("source.url", "source.url 이 http(s) 주소가 아니다"))
    if community_url(url):
        e.append(("source.url", MSG_COMMUNITY))
    for k in ("publisher", "accessed"):
        if _blank(src.get(k)):
            e.append((f"source.{k}", f"source.{k} 가 없다"))
    if src.get("tier") != KIND_TIER[kind]:
        e.append(("source.tier", f"{kind} 근거의 출처 등급은 {KIND_TIER[kind]} 로 고정이다(지금 {src.get('tier')})"))
    e += _doc_errors(ev.get("doc"))
    if kind in OFFICIAL:
        if _blank(ev.get("observed")):
            e.append(("observed", "observed 가 없다 — 원문에서 대조할 통째 대목을 적는다"))
        v = ev.get("verification")
        if not isinstance(v, dict) or v.get("method") != "machine":
            e.append(("verification", "verification(method: machine) 이 없다 — capture 명령을 먼저 돌린다"))
        else:
            cap = v.get("capture") if isinstance(v.get("capture"), dict) else {}
            for k in ("path", "text_path"):
                if not _blank(cap.get(k)) and not cards._inside_captures(cap.get(k)):
                    e.append((f"verification.capture.{k}", f"원문 사본이 captures 폴더 밖에 있다: {cap.get(k)}"))
            if not HEX64.match(str(cap.get("sha256") or "")):
                e.append(("verification.capture.sha256", "사본 해시는 64자 16진수로 적는다"))
    elif kind == "보도":
        r = ev.get("report")
        if not isinstance(r, dict):
            e.append(("report", "보도 근거는 report(매체, 제목, 읽은 시각, 근거 종류)를 적는다"))
        else:
            if set(r) - {"outlet", "title", "read_at", "basis_kinds", "first_report"}:
                e.append(("report", MSG_REPORT_BODY))
            for k in ("outlet", "title", "read_at"):
                if _blank(r.get(k)):
                    e.append((f"report.{k}", f"report.{k} 가 없다"))
            if len(str(r.get("title") or "")) > model.LIMITS["report.title"]:
                e.append(("report.title", f"report.title 이 {model.LIMITS['report.title']}자를 넘는다"))
            if not isinstance(r.get("basis_kinds"), list):
                e.append(("report.basis_kinds", "report.basis_kinds 는 목록이다(기사가 밝힌 근거의 종류)"))
    else:
        r = ev.get("raw")
        if not isinstance(r, dict):
            e.append(("raw", "언론 공개 원자료는 raw(주소, 받은 시각, 해시, 두 에이전트의 대목)를 적는다"))
        elif not HEX64.match(str(r.get("sha256") or "")):
            e.append(("raw.sha256", "원자료 해시는 64자 16진수로 적는다"))
    return e


def copy_errors(ev: dict) -> list[str]:
    """원문 재검사. 공식 원문·기관 자료는 저장한 사본으로 cards.machine_check(fresh=False) 를 다시 돌리고 기계 대조를 마쳤는지
    (verified_at) 본다. 언론 공개 원자료는 해시, 대목, 쓴 쪽과 재대조 쪽(서로 다름)이 적혔는지만 본다(프로그램은 다시 대조하지 못한다).
    보도는 재검사 대상이 아니다(빈 목록 — 판정의 근거로 세지 않는 것은 rules 가 정한다)."""
    kind = ev.get("kind")
    eid = ev.get("evidence_id", "?")
    if kind in OFFICIAL:
        errs, _ = cards.machine_check(as_claim_view(ev), fresh=False)
        v = ev.get("verification")
        if isinstance(v, dict) and _blank(v.get("verified_at")):
            errs.append(f"{eid}: 기계 대조를 마치지 않았다(verified_at 없음) — machine-verify 를 돌린다")
        return errs
    if kind == "언론 공개 원자료":
        r = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
        errs = [f"{eid}: raw.{k} 가 없다" for k in ("url", "fetched_at", "sha256", "located", "author_by", "recheck_by") if _blank(r.get(k))]
        if not errs and cards._same_agent(r.get("author_by"), r.get("recheck_by")):
            errs.append(f"{eid}: 쓴 쪽과 재대조한 쪽의 식별자가 같다")
        if not errs and not HEX64.match(str(r.get("sha256"))):
            errs.append(f"{eid}: 원자료 해시가 64자 16진수가 아니다")
        return errs
    return []


# ── 원문 받기와 기계 대조 ─────────────────────────────────────────────
def _evidence_path(issue_id, evidence_id) -> pathlib.Path:
    """근거 파일 경로 — 번호 꼴을 먼저 보고, 풀어 낸 경로가 지금 자료 루트의 issues 폴더 안인지 본다(절대 경로 인자로 루트 밖에 쓰지 않게)."""
    if not ids.issue_id_ok(issue_id) or not ids.evidence_id_ok(evidence_id, issue_id):
        raise ValueError(f"이슈 번호나 근거 번호 꼴이 아니다: {issue_id} {evidence_id}")
    p = paths.evidence_file(issue_id, evidence_id)
    if paths.issues_dir().resolve() not in p.resolve().parents:
        raise ValueError(f"근거 파일이 자료 루트 밖이다: {p}")
    return p


def capture_evidence(issue_id: str, evidence_id: str, fetcher=None, save: bool = True) -> dict:
    """원문을 받아 captures/<근거 번호>/ 에 사본과 text.txt 를 두고 verification 의 capture·match 를 채운다.
    capture.capture_claim 과 같은 순서(받기 → 글 뽑기 → text.txt → 대조)이고 그림은 만들지 않는다.
    fetcher(url, dest_dir) 는 시험에서 망 없이 응답을 넣을 때 쓴다. {ok, reason, evidence}."""
    p = _evidence_path(issue_id, evidence_id)
    ev = model.load_yaml(p)
    if ev.get("kind") not in OFFICIAL:
        return {"ok": False, "reason": f"{evidence_id}: 원문 사본은 공식 원문과 기관 자료만 받는다", "evidence": ev}
    croot = paths.captures_dir(issue_id)
    d = croot / evidence_id
    if croot.resolve() not in d.resolve().parents:
        raise ValueError(f"사본 폴더 밖에 쓰려 한다: {d}")
    url = (ev.get("source") or {}).get("url", "")
    res = (fetcher or K.fetch)(url, d)
    cap = {k: res.get(k) for k in ("ok", "reason", "url", "final_url", "fetched_at", "status", "content_type", "charset", "bytes", "sha256", "kind")}
    cap["path"] = paths.rel_or_abs(res["path"]) if res.get("path") else ""
    cap["text_path"] = ""
    match = {"found": False, "count": 0, "offsets": [], "context": "", "reason": ""}
    if res.get("ok"):
        ex = K.extract_text(res["path"], res["kind"], res.get("charset") or "")
        tp = d / "text.txt"
        tp.write_text(ex["text"], encoding="utf-8")
        cap["text_path"] = paths.rel_or_abs(tp)
        if not ex["ok"]:
            match["reason"] = ex["reason"]
        else:
            f = K.find_phrase(ex["text"], ev.get("observed") or "")
            match.update(found=f["found"], count=f["count"], offsets=[m["offset"] for m in f["matches"]],
                         context=K.context_of(f["matches"][0], ev["observed"]) if f["found"] else "")
            if not f["found"]:
                match["reason"] = "observed 가 사본 글에 없다(공백만 정리해 비교)"
    else:
        match["reason"] = res.get("reason", "열지 못함")
    old = ev.get("verification") if isinstance(ev.get("verification"), dict) else {}
    ev["verification"] = {"method": "machine", "capture": cap, "match": match, "author": old.get("author") or {},
                          "recheck": old.get("recheck") or {}, "verified_at": ""}
    if save:
        model.save_yaml(p, ev)
    ok = bool(res.get("ok")) and match["found"]
    return {"ok": ok, "reason": "" if ok else match["reason"], "evidence": ev}


def machine_verify_evidence(issue_id: str, evidence_id: str, save: bool = True) -> dict:
    """cards.machine_check(fresh=True) 를 통과하면 match 와 verified_at 을 적는다. 못 채우면 아무것도 저장하지 않는다. {ok, reasons, evidence}."""
    try:
        p = _evidence_path(issue_id, evidence_id)
    except ValueError as e:
        return {"ok": False, "reasons": [str(e)], "evidence": None}
    if not p.is_file():
        return {"ok": False, "reasons": [f"{evidence_id}: 근거 기록 파일이 없다({p})"], "evidence": None}
    ev = model.load_yaml(p)
    reasons = [f"{evidence_id} {k}: {m}" for k, m in structure_errors(ev, issue_id, evidence_id) if k != "verification"]
    if ev.get("kind") not in OFFICIAL:
        reasons.append(f"{evidence_id}: 기계 대조는 공식 원문과 기관 자료만 한다")
    if not reasons:
        reasons, match = cards.machine_check(as_claim_view(ev), fresh=True)   # 이미 마친 기록(verified_at 있음)은 다시 올리지 않는다
        if not reasons:
            ev["verification"]["match"] = match
            ev["verification"]["verified_at"] = cards.now_kst()
            ev["revision"] = int(ev.get("revision") or 1) + 1
    if reasons:
        return {"ok": False, "reasons": reasons, "evidence": None}
    if save:
        model.save_yaml(p, ev)
    return {"ok": True, "reasons": [], "evidence": ev}
