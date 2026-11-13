"""숫자 세 가지 — 독자에게 보이는 글의 수량마다 그 종류(공식, 주장, 계산)를 적게 하고 종류별로 검사한다(설계 7절).

  공식  공식 원문의 값. 그 항목이 인용한 근거의 observed(공식 원문·기관 자료) 또는 raw.located(언론 공개 원자료)에
        같은 표기로 있어야 한다(render.numbers.complete_in). 보도 근거는 숫자의 근거가 되지 않는다.
  주장  떠도는 주장 속의 값. 주장 요지(claims.gist·parts.gist)와 퍼진 곳(spread.where)에만 쓴다. 그 밖의 칸은 그 문장(항목)이나
        숫자 항목에 refutes: c<n> 을 달 때만(반박하려고 값을 적는 경우).
  계산  우리가 계산하거나 센 값. inputs·formula(사칙연산과 괄호만)·rounding 으로 다시 계산해 value 의 수와 같아야 한다.
        입력은 하나하나 출처를 밝힌다 — {value, kind: 공식, evidence}(근거 원문에 같은 표기) 또는 {kind: 셈, of: [구절…], evidence}
        (센 것마다 근거 원문에 있는 구절을 적는다. 값은 구절 수). 맨 문자열 입력은 받지 않고, 식이 입력 이름 하나뿐이면(값을 그대로
        옮긴 것) 셈 입력일 때만 받는다.
글을 render.numbers.claim_tokens 로 훑은 토큰마다 같은 정규형·종류의 항목이 있어야 한다. 달력과 식별자는 대상이 아니다.
한글로 쓴 수량('이백억 원', '열두 명')은 토큰으로 잡히지 않으므로 오류로 내고 숫자로 고쳐 쓰게 한다.
언론 공개 원자료는 프로그램이 다시 대조하지 못하므로 공식 수치의 근거가 되지 않는다.
"""
from __future__ import annotations

import ast
import math
import operator
import re
from decimal import ROUND_HALF_UP, Decimal

from ozl.render import numbers as N

from . import model

CLAIM_FIELDS = re.compile(r"^claims\.[^.]+\.(gist|spread\.where|parts\.[^.]+\.gist)$")
ROUNDING = re.compile(r"^(반올림 소수 (\d)자리|내림|올림|그대로)$")
REFUTES = re.compile(r"^c[1-9]\d{0,2}$")
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_MAG = {"십": 10, "백": 100, "천": 1000, "만": 10**4, "억": 10**8, "조": 10**12, "경": 10**16}


def to_number(text) -> float | None:
    """표기에서 수 하나를 읽는다('1만 2천 개' → 12000 · '200억 원' → 2e10 · '3년' → 3 · '7.5%' → 7.5). 읽지 못하면 None."""
    s = str(text if text is not None else "").replace(",", "").replace(" ", "")
    m = re.search(r"-?\d+(?:\.\d+)?(?:[십백천만억조경]|\d|\.)*", s)
    if not m:
        return None
    t = m.group(0)
    if not re.search(r"[십백천만억조경]", t):
        try:
            return float(t)
        except ValueError:
            return None
    total, small = 0.0, 0.0
    for num, mag in re.findall(r"(\d+(?:\.\d+)?)?([십백천만억조경]?)", t):
        if not num and not mag:
            continue
        v = float(num) if num else 0.0
        if mag in ("만", "억", "조", "경"):        # 큰 단위: 앞에 모인 작은 단위 묶음(없으면 1)을 곱한다 — '3천3백만'
            total += ((small + v) or 1.0) * _MAG[mag]
            small = 0.0
        elif mag:                                   # 작은 단위: '2천' · '천'(= 1천)
            small += (v or 1.0) * _MAG[mag]
        else:
            small += v
    return total + small


def _eval(node, names: dict):
    if isinstance(node, ast.Expression):
        return _eval(node.body, names)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left, names), _eval(node.right, names))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand, names)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    raise ValueError("식에는 사칙연산, 괄호, 수, inputs 의 이름만 쓴다")


def _round(v: float, rule: str) -> float:
    m = ROUNDING.match(rule)
    if m.group(2) is not None:
        q = Decimal(1).scaleb(-int(m.group(2)))
        return float(Decimal(repr(v)).quantize(q, rounding=ROUND_HALF_UP))
    if rule == "내림":
        return float(math.floor(v))
    if rule == "올림":
        return float(math.ceil(v))
    return v


OFFICIAL = ("공식 원문", "기관 자료")
_NATIVE = "(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)?\\s?(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)|열|스무|스물|서른|마흔|쉰"
KOREAN_QTY = re.compile(
    r"(?<![가-힣0-9.,])(?<![0-9] )"
    r"(?:(?:수|몇|[일이삼사오육칠팔구])?[십백천만억조경](?:\s?[일이삼사오육칠팔구십백천만억조경])*\s?"
    r"(?:원|명|개|건|곳|가구|배|퍼센트|프로|달러|톤|채|살)"
    r"|(?:" + _NATIVE + r")\s?(?:명|개|건|곳|가구|배|채|살|척|마리)"
    r"|(?:[일이삼사오육칠팔구]|이십|삼십|사십|오십|육십|칠십|팔십|구십)\s?퍼센트)")


def korean_qty(text: str) -> list[str]:
    """한글로 쓴 수량 표기들('이백억 원', '수천억 원', '열두 명', '삼십 퍼센트')."""
    return [m.group(0) for m in KOREAN_QTY.finditer(text or "")]


def _official_error(value, eid, cited, evidences, need_digits=False) -> str:
    if eid not in cited:
        return f"공식 수치 '{value}'의 근거({eid})가 이 글이 인용한 근거가 아니다"
    ev = evidences.get(eid) or {}
    hay = [str(ev.get("observed") or "")] if ev.get("kind") in OFFICIAL else []
    if not any(N.complete_in(str(value), h, need_digits=need_digits) for h in hay if h.strip()):
        return f"공식 수치 '{value}'이 인용한 근거({eid}) 원문에 같은 표기로 없다(공식 원문과 기관 자료만 받친다)"
    return ""


def _count_error(k, raw: dict, cited, evidences) -> tuple[str, float]:
    """셈 입력 {kind: 셈, of: [구절…], evidence} — 구절마다 근거 원문에 있어야 하고 값은 구절 수."""
    of, eid = raw.get("of"), raw.get("evidence")
    if not isinstance(of, list) or not of or any(not isinstance(x, str) or not x.strip() for x in of) or len(set(of)) != len(of):
        return f"셈 입력 '{k}'은 센 것마다 근거 원문의 구절을 서로 다르게 적는다(of)", 0.0
    if eid not in cited:
        return f"셈 입력 '{k}'의 근거({eid})가 이 글이 인용한 근거가 아니다", 0.0
    ev = evidences.get(eid) or {}
    hay = " ".join(str(ev.get("observed") or "").split()) if ev.get("kind") in OFFICIAL else ""
    miss = [x for x in of if " ".join(x.split()) not in hay]
    if miss:
        return f"셈 입력 '{k}'의 구절 '{miss[0]}'이 근거({eid}) 원문에 없다", 0.0
    return "", float(len(of))


def computed_error(n: dict, cited, evidences) -> str:
    inputs, formula, rule = n.get("inputs"), n.get("formula"), str(n.get("rounding") or "")
    if not isinstance(inputs, dict) or not inputs or not isinstance(formula, str) or not formula.strip():
        return f"계산 값 '{n.get('value')}'은 inputs 와 formula 를 적는다"
    if not ROUNDING.match(rule):
        return f"계산 값 '{n.get('value')}'의 rounding 은 '반올림 소수 n자리', '내림', '올림', '그대로' 가운데 하나다"
    if model._s(n.get("unit")).strip() == "":
        return f"계산 값 '{n.get('value')}'의 unit 을 적는다"
    names, counts = {}, set()
    for k, raw in inputs.items():
        if not str(k).isidentifier():
            return f"계산 입력 '{k}'을 수로 읽지 못했다(이름은 띄어 쓰지 않는다)"
        if not isinstance(raw, dict) or raw.get("kind") not in ("공식", "셈"):
            return (f"계산 입력 '{k}'은 출처를 밝힌다 — {{value, kind: 공식, evidence}} 또는 {{kind: 셈, of, evidence}}"
                    " (맨 값은 받지 않는다)")
        if raw["kind"] == "셈":
            why, v = _count_error(k, raw, cited, evidences)
            if why:
                return why
            counts.add(str(k))
        else:
            why = _official_error(raw.get("value"), raw.get("evidence"), cited, evidences, need_digits=True)
            if why:
                return why
            v = to_number(raw.get("value"))
            if v is None:
                return f"계산 입력 '{k}: {raw.get('value')}'을 수로 읽지 못했다(이름은 띄어 쓰지 않는다)"
        names[str(k)] = v
    if formula.strip() in names and formula.strip() not in counts:
        return f"계산 값 '{n.get('value')}'의 식이 입력 하나를 그대로 옮긴 것이다 — 공식 수치로 적는다"
    try:
        got = _eval(ast.parse(formula, mode="eval"), names)
    except (SyntaxError, ValueError, ZeroDivisionError) as e:
        return f"계산 값 '{n.get('value')}'의 식을 계산하지 못했다: {e}"
    want = to_number(n.get("value"))
    if want is None or not math.isclose(_round(got, rule), want, rel_tol=0, abs_tol=1e-9):
        return f"계산 값 '{n.get('value')}'이 식({formula})을 다시 계산한 값({_round(got, rule):g})과 다르다"
    return ""


def number_errors(issue: dict, evidences: dict) -> list[tuple[str, str]]:
    """[(칸 경로, 문구)]. 글의 수량 토큰마다 종류를 적었는가, 적은 종류의 검사를 통과하는가."""
    errs: list[tuple[str, str]] = []
    for path, text, nums, item in model.reader_items(issue):
        cited = set(model.item_evidence_ids(item)) if item is not None else set(evidences)
        entries = [n for n in nums if isinstance(n, dict)]
        canon = []
        for n in entries:
            toks = [t for t in N.claim_tokens(str(n.get("value") or "")) if not t.fragment]
            canon.append({(t.canon, t.kind) for t in toks})
        for shown in korean_qty(text):
            errs.append((path, f"한글로 쓴 수량 '{shown}'은 숫자로 고쳐 쓴다 — 그래야 종류(공식, 주장, 계산)를 적고 검사할 수 있다"))
        for t in N.claim_tokens(text):
            shown = text[t.start:t.end]
            if t.fragment:
                errs.append((path, f"숫자 '{shown}'을 온전한 수량으로 읽지 못했다 — 표기를 고친다"))
            elif not any((t.canon, t.kind) in c for c in canon):
                errs.append((path, f"숫자 '{shown}'의 종류(공식, 주장, 계산)를 적지 않았다"))
        for n, c in zip(entries, canon):
            value, kind = n.get("value"), n.get("kind")
            if kind not in model.NUMBER_KINDS:
                errs.append((path, f"숫자 '{value}'의 종류 '{kind}'은 허용 값({', '.join(model.NUMBER_KINDS)})이 아니다"))
                continue
            if not c or not N.complete_in(str(value), text, need_digits=False):
                continue   # 이 글에 없는 값(같은 항목의 다른 글 칸에 쓰인 것)은 그 칸에서 본다
            if kind == "공식":
                why = _official_error(value, n.get("evidence"), cited, evidences)
            elif kind == "주장":
                refutes = n.get("refutes") or (item or {}).get("refutes")
                ok = CLAIM_FIELDS.match(path) or (isinstance(refutes, str) and REFUTES.match(refutes)
                                                  and _refutes_ok(issue, refutes, c))
                why = "" if ok else (f"주장 속 값 '{value}'은 주장 요지와 퍼진 곳에만 쓴다 — 반박하려고 적는 문장이면 refutes 로 "
                                     "그 값을 담은 '사실과 다름'·'일부 맞음' 주장을 가리킨다")
                if ok and not CLAIM_FIELDS.match(path) and path.startswith("facts."):
                    why = f"주장 속 값 '{value}'은 확인된 사실 칸에 쓰지 않는다"
            else:
                why = computed_error(n, cited, evidences)
            if why:
                errs.append((path, why))
    return errs


def _refutes_ok(issue: dict, cid: str, canon: set) -> bool:
    """refutes 가 가리킨 주장이 '사실과 다름'·'일부 맞음'이고, 그 요지·작은 주장 요지·숫자에 같은 값이 있는가."""
    c = next((x for x in issue.get("claims") or [] if isinstance(x, dict) and x.get("id") == cid), None)
    if c is None or c.get("verdict") not in ("사실과 다름", "일부 맞음"):
        return False
    texts = [str(c.get("gist") or "")] + [str(p.get("gist") or "") for p in c.get("parts") or [] if isinstance(p, dict)]
    texts += [str(x.get("value") or "") for x in c.get("numbers") or [] if isinstance(x, dict)]
    have = {(t.canon, t.kind) for x in texts for t in N.claim_tokens(x) if not t.fragment}
    return bool(canon) and canon <= have
