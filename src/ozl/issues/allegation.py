"""의혹 주장과 제목·첫 화면 — 범죄 낱말 예외(확정 판단으로 '확인'된 주장)와 의혹 요지를 옮겨 쓴 곳 찾기. check 가 부른다."""
from __future__ import annotations

from . import model, rules, style


def _settled(c: dict, issue: dict, evidences: dict, copy_errs: dict) -> bool:
    """'확인'이고 판정이 성립하며, 수사기관·법원의 확정 문서(가 · 확정 판결, 처분)가 지지 근거로 받치는 주장인가."""
    if not isinstance(c, dict) or c.get("verdict") != "확인" or rules.verdict_errors(c, evidences, copy_errs, issue):
        return False
    infos, _ = rules.classify(c, evidences, copy_errs)
    return any(rules.allegation_basis(i) and i["link"].get("stance") == "지지" for i in infos)


def _crime_exempt(issue: dict, evidences: dict, copy_errs: dict) -> set[str]:
    """제목이 기대는 주장(titles.basis_claims)이 '확인'이고 확정 판단 근거로 받쳐지면 그 요지의 범죄 낱말은 첫 화면에 쓸 수 있다."""
    out: set[str] = set()
    basis = ((issue.get("titles") or {}).get("basis_claims") or []) if isinstance(issue.get("titles"), dict) else []
    for c in issue.get("claims") or []:
        if isinstance(c, dict) and c.get("id") in basis and rules.item_public(issue, c) and _settled(c, issue, evidences, copy_errs):
            out |= set(style.crime_words(str(c.get("gist") or "")))
    return out


ALLEGATION_RUN = 8   # 의혹 주장의 요지와 이만큼(정규화한 글자 수) 겹치면 그 요지를 옮긴 것으로 본다


def _allegation_errors(issue: dict, evidences: dict, copy_errs: dict) -> list[tuple[str, str]]:
    """의혹 주장(allegation: true)의 요지를 제목과 첫 화면(그림 설명 포함)에 옮기지 않는다. 확정 판단으로 '확인'된 주장만 예외."""
    out: list[tuple[str, str]] = []
    t = issue.get("titles") if isinstance(issue.get("titles"), dict) else {}
    basis = t.get("basis_claims") if isinstance(t.get("basis_claims"), list) else []
    firsts = [(p, style.norm(x)) for p, x, _n, _i in model.reader_items(issue) if style.FIRST_SCREEN.match(p)]
    for c in issue.get("claims") or []:
        if not isinstance(c, dict) or c.get("allegation") is not True or _settled(c, issue, evidences, copy_errs):
            continue
        if c.get("id") in basis:
            out.append(("titles.basis_claims", f"{style.MSG_CRIME} — 의혹 주장({c.get('id')})에 제목을 기대지 않는다"))
        g = style.norm(str(c.get("gist") or ""))
        wins = {g[i:i + ALLEGATION_RUN] for i in range(0, max(0, len(g) - ALLEGATION_RUN + 1))}
        for p, n in firsts:
            if any(w in n for w in wins):
                out.append((p, f"{style.MSG_CRIME} — 의혹 주장({c.get('id')})의 요지를 옮겼다"))
    return out
