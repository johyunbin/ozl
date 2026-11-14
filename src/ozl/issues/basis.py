"""판정을 받치는 사실(basis_facts)과 확인한 범위(scope), 재대조한 쪽과 문장 대조 검토자의 연결 — check 가 부른다.

basis_facts 는 새 문장을 짓지 않고 이미 대조한 확인된 사실의 번호를 적는다. 그 사실은 게시 가능이어야 하고, 사실의 근거가 그 주장
(작은 주장)의 근거 연결이나 당사자 입장의 근거에 들어 있어야 한다. 본문(body.basis_texts)은 그 사실들의 문장을 basis 로 싣는다.
"""
from __future__ import annotations

from ozl.research import cards

from . import evidence as EV
from . import model, rules

MSG_BASIS_LIST = "basis_facts 는 확인된 사실 번호 목록이다(예: [f1, f2])"
MSG_BASIS_WARN = "판정을 받치는 사실(basis_facts)을 적지 않았다 — 화면의 '근거가 말하는 것'이 비어 나간다"
MSG_SCOPE_WARN = "확인한 범위(scope)가 비어 있다 — 요건이 붙은 조치면 판정 옆에 범위를 밝힌다"
MSG_SCOPE_WORD = ("확인한 범위(scope)에 낱말 하나만 있다 — '{}' 는 화면에 '확인한 범위: {}' 로 그대로 나간다"
                  "(무엇까지 확인했고 무엇은 확인하지 않았는지 적는다)")


def scope_is_one_word(v) -> bool:
    """범위 칸에 낱말 하나(대상 이름)만 있는가. 이 칸은 근거 연결의 scope 와 맞추는 맥락 칸이면서 화면의 '확인한 범위'로도
    실린다. 짧은 구('시내버스 전체')는 범위를 말하지만 이름 하나는 아무것도 말하지 않는다. 문장인지까지는 보지 않는다."""
    return len(str(v or "").split()) == 1


def _basis_links(claim: dict, part: dict | None) -> set:
    """판정을 받치는 사실이 기댈 수 있는 근거 — 그 주장(작은 주장)의 근거 연결과 당사자 입장의 근거."""
    pp = claim.get("party_position") if isinstance(claim.get("party_position"), dict) else {}
    own = model.item_evidence_ids(claim) if part is None else \
        [x.get("id") for x in part.get("evidence") or [] if isinstance(x, dict)]
    return set(own) | ({pp["evidence"]} if isinstance(pp.get("evidence"), str) else set())


def basis_errors(issue: dict) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(오류, 경고) — 주장·작은 주장의 basis_facts(판정을 받치는 확인된 사실)와 scope(확인한 범위)."""
    facts = {f.get("id"): f for f in issue.get("facts") or [] if isinstance(f, dict)}
    errs, warns = [], []
    for c in issue.get("claims") or []:
        if not isinstance(c, dict):
            continue
        base = f"claims.{c.get('id')}"
        units = [(base, c, None)] + [(f"{base}.parts.{p.get('id')}", p, p) for p in c.get("parts") or [] if isinstance(p, dict)]
        for path, x, part in units:
            bf = x.get("basis_facts")
            if bf is not None and (not isinstance(bf, list) or any(not isinstance(i, str) for i in bf)):
                errs.append((f"{path}.basis_facts", MSG_BASIS_LIST))
                bf = None
            links = _basis_links(c, part)
            for fid in bf or []:
                f = facts.get(fid)
                if f is None:
                    errs.append((f"{path}.basis_facts", f"없는 사실을 가리킨다: {fid}"))
                elif f.get("publish") != "게시 가능":
                    errs.append((f"{path}.basis_facts", f"판정을 받치는 사실({fid})이 게시 가능이 아니다"))
                elif not set(model.item_evidence_ids(f)) & links:
                    errs.append((f"{path}.basis_facts", f"판정을 받치는 사실({fid})의 근거가 이 주장의 근거 연결이나 "
                                                         "당사자 입장의 근거에 없다"))
            # 숨긴 주장(보류, 공개 제외)은 화면에 나가지 않는다 — 비어 나갈 줄이 없으니 알리지 않는다
            if c.get("publish") == "게시 가능" and x.get("verdict") in ("확인", "사실과 다름") and not bf:
                warns.append((f"{path}.basis_facts", MSG_BASIS_WARN))
        scope_blank = lambda v: cards._blank(v) or rules.norm(v) == rules.norm(model.NA)   # noqa: E731
        if c.get("verdict") in ("확인", "일부 맞음") and scope_blank(c.get("scope")):
            warns.append((f"{base}.scope", MSG_SCOPE_WARN))
        if c.get("publish") == "게시 가능":              # 숨긴 주장의 범위는 화면에 나가지 않는다
            for path, x, _part in units:
                if not scope_blank(x.get("scope")) and scope_is_one_word(x.get("scope")):
                    errs.append((f"{path}.scope", MSG_SCOPE_WORD.format(x.get("scope"), x.get("scope"))))
    return errs, warns


MSG_RECHECK_LINK = "재대조한 쪽({})이 문장 대조 검토자({}) 누구와도 이어지지 않는다 — 재대조는 검토 단계의 몫이다"


def recheck_warnings(issue: dict, evidences: dict) -> list[tuple[str, str]]:
    """인용한 공식 원문·기관 자료의 재대조한 쪽(verification.recheck.by)이 문장 대조 검토 줄의 검토자(쓴 모델과 다른 모델)와
    이어지는가 — 검토자 모델 이름의 낱말(판 번호 뺌)이 재대조 쪽 이름에 모두 들어 있어야 한다. 문장 대조 줄이 아직 없으면 보지 않는다."""
    from .reviews import _same, model_key
    drafted = (issue.get("production") or {}).get("drafted_by") if isinstance(issue.get("production"), dict) else None
    names = [r.get("by_model") for r in issue.get("reviews") or [] if isinstance(r, dict) and r.get("kind") == "문장 대조"
             and r.get("family") == "anthropic" and not _same(r.get("by_model"), drafted)]
    keys = [set(model_key(n).split()) for n in names if model_key(n)]
    if not keys:
        return []
    out = []
    for eid in model.cited_evidence_ids(issue):
        ev = evidences.get(eid)
        if not isinstance(ev, dict) or ev.get("kind") not in EV.OFFICIAL:
            continue
        v = ev.get("verification") if isinstance(ev.get("verification"), dict) else {}
        by = (v.get("recheck") or {}).get("by") if isinstance(v.get("recheck"), dict) else None
        if cards._blank(by):
            continue                                # 재대조가 비어 있으면 copy_errors 가 오류로 낸다
        mine = set(model_key(by).split())
        if not any(k <= mine for k in keys):
            out.append((f"evidence.{eid}.verification.recheck.by", MSG_RECHECK_LINK.format(by, ", ".join(dict.fromkeys(names)))))
    return out
