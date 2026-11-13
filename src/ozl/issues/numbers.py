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
MINUS = str.maketrans({"\u2212": "-", "\uff0d": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\ufe63": "-"})


def to_number(text) -> float | None:
    """표기에서 수 하나를 읽는다('1만 2천 개' → 12000 · '200억 원' → 2e10 · '3년' → 3 · '7.5%' → 7.5). 읽지 못하면 None."""
    # 빼기 기호(U+2212 −, U+FF0D －, 줄표들)는 '-' 로 읽는다 — render.numbers.claim_tokens 가 같은 글을 음수로 읽으므로 맞춘다
    s = str(text if text is not None else "").translate(MINUS).replace(",", "").replace(" ", "")
    m = re.search(r"-?\d+(?:\.\d+)?(?:[십백천만억조경]|\d|\.)*", s)
    if not m:
        return None
    t = m.group(0)
    if not re.search(r"[십백천만억조경]", t):
        try:
            return float(t)
        except ValueError:
            return None
    sign = -1.0 if t.startswith("-") else 1.0      # 부호는 따로 둔다 — 아래 낱낱 읽기는 '-' 를 보지 않는다
    t = t.lstrip("-")
    total, small, small_seen = 0.0, 0.0, False
    for num, mag in re.findall(r"(\d+(?:\.\d+)?)?([십백천만억조경]?)", t):
        if not num and not mag:
            continue
        v = float(num) if num else None             # 적힌 0 과 생략(= 1)을 가른다 — '0억' 은 0, '억' 은 1억
        if mag in ("만", "억", "조", "경"):        # 큰 단위: 앞에 모인 작은 단위 묶음(없으면 1)을 곱한다 — '3천3백만'
            base = small + (v or 0.0) if (small_seen or v is not None) else 1.0
            total += base * _MAG[mag]
            small, small_seen = 0.0, False
        elif mag:                                   # 작은 단위: '2천' · '천'(= 1천) · '0천'(= 0)
            small += (1.0 if v is None else v) * _MAG[mag]
            small_seen = True
        else:
            small += v or 0.0
            small_seen = True
    return sign * (total + small)


def _names(node) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _const_error(node, counts_only: bool = False, unit: str = "") -> str:
    """식의 수 상수는 두 가지만 받는다 — 출처 없는 값을 식에 넣지 못하게.
      · 단위 바꾸기: 입력이 든 식에 곱하거나 나누는 10의 거듭제곱(10, 100, 1000 …). 셈 입력만 쓴 식(센 수)에는 단위가 없으니
        비율을 백분율로 바꾸는 '× 100'(나눗셈이 든 식, 단위 %)만 받는다 — 센 수 2 에 10^8 을 곱해 '2억 건'을 만들지 못하게.
      · 양끝을 넣어 세는 '± 1': 두 입력의 차('b - a')에 한 번만 더하거나 뺀다(2095~2098년 = 4년).
    상수끼리의 셈('1+1', '10*10'), 부호 뒤집기('-a'), 0 과 음수는 받지 않는다."""
    parents = {}
    for p in ast.walk(node):
        for ch in ast.iter_child_nodes(p):
            parents[ch] = p
    ones = 0
    has_div = any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) for n in ast.walk(node))
    for n in ast.walk(node):
        if isinstance(n, ast.UnaryOp):
            return "부호(+·-)를 붙인 식"            # 공식 수치의 부호를 뒤집어 다른 값을 만들지 못하게 — 차는 'b - a' 로 적는다
        if isinstance(n, ast.BinOp) and not _names(n):
            return "상수끼리의 셈"
        if not isinstance(n, ast.Constant):
            continue
        v = n.value
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            return f"식의 수 '{v}'"
        p = parents.get(n)
        if not isinstance(p, ast.BinOp):
            return f"식의 수 '{v}'"
        other = p.right if p.left is n else p.left
        if v == 1 and isinstance(p.op, (ast.Add, ast.Sub)):
            # 양끝을 넣어 세는 '+ 1' — 상대가 두 입력의 차('b - a')일 때만, 식 전체에 한 번만
            if not (isinstance(other, ast.BinOp) and isinstance(other.op, ast.Sub) and _names(other.left) and _names(other.right)):
                return f"식의 수 '{v}'"
            ones += 1
            if ones > 1:
                return f"식의 수 '{v}'(± 1 을 두 번 이상)"
            continue
        lg = math.log10(v)
        if abs(lg - round(lg)) > 1e-12 or round(lg) < 1 or not isinstance(p.op, (ast.Mult, ast.Div)):
            return f"식의 수 '{v}'"
        if counts_only and not (v == 100 and has_div and "%" in unit):
            return f"셈 입력에 곱하거나 나눈 수 '{v}'"
    return ""


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


# 키워드의 숫자 — 키워드는 숫자 종류 검사를 받을 수 없으니 수량은 쓰지 않는다(설계 C-7·C-8). 다만 숫자가 이름의 일부인 표기
# ('5G', 'G7', '가상병19', '2차전지', '3기 신도시', '4대강', '1인 가구', 'K2', 'VIRUS-19', '2099 시장 선거')는 수량이 아니다.
# 받는 것: 부호·소수점·쉼표·%·크기 단위가 없는 정수가 글자에 붙어 있고(앞이나 뒤), 붙은 한글이나 띄어 쓴 다음 낱말이 세는 단위가
# 아닐 때, 또는 홀로 선 네 자리 연도(1000~2999 — 뒤 낱말이 단위가 아닐 때). 그 밖은 모두 수량으로 본다(막는 쪽으로 틀린다).
# 못 잡는 것: 한글에 붙여 쓴 끝자리 수('요금400')는 '가상병19' 와 가를 수 없어 이름으로 본다.
_KW_UNIT_PREFIX = ("원", "명", "개", "건", "곳", "가구", "배", "달러", "톤", "채", "살", "퍼센트", "프로", "년", "개월", "시간", "위",
                   "번", "마리", "척", "만", "억", "조", "천", "백", "경", "%")
_KW_UNIT_EXACT = {"일", "주", "분", "초", "대", "회", "권", "세", "십", "장", "그루", "벌", "켤레", "포기", "병", "잔", "그릇"}
_KW_ASCII_UNIT = {"k", "m", "b", "bn", "mn", "kg", "km", "t", "g", "mg", "ml", "l", "cm", "mm", "kw", "kwh", "mw", "gw", "w",
                  "K", "M", "B", "BN", "MN", "KB", "MB", "GB", "TB", "KG", "KM"}
_KW_ASCII_WORD = {"million", "billion", "trillion", "thousand", "hundred", "percent", "won", "usd", "dollar", "dollars", "krw",
                  "kg", "km", "people", "times"}


def _kw_unit(word: str) -> bool:
    return bool(word) and (word in _KW_UNIT_EXACT or word.startswith(_KW_UNIT_PREFIX) or word.lower() in _KW_ASCII_WORD)


def keyword_qty(text: str) -> bool:
    """키워드(또는 화제 목록의 키워드)에 수량이 있는가. 달력은 수량이 아니고, 숫자가 이름의 일부인 표기도 수량이 아니다."""
    text = str(text or "")
    if korean_qty(text):
        return True
    for t in N.claim_tokens(text):
        if t.kind == "cal":
            continue
        core, left = text[t.start:t.end], t.start > 0 and text[t.start - 1].isalpha()
        if core[:1] == "-" and t.start > 0 and text[t.start - 1].isascii() and text[t.start - 1].isalpha():
            core, left = core[1:], True             # 'VIRUS-19' 의 '-' 는 이음표다(부호가 아니다). '−'(U+2212)는 언제나 부호
        m = re.fullmatch(r"([A-Za-z]*)(\d+)([A-Za-z]*)", core)
        if t.fragment or not m:
            return True                             # 부호, 소수점, 쉼표, %, 크기 단위, 분수, 기간·수량 낱말
        if m.group(3) in _KW_ASCII_UNIT:
            return True                             # '5kg', '3B', '701k'
        after = text[t.end:]
        run = re.match(r"[가-힣]+", after)
        word = run.group(0) if run else (re.match(r"\s+([가-힣A-Za-z%]+)", after) or [None, ""])[1]
        if _kw_unit(word or ""):
            return True                             # '400원', '12명', '1위', '400 원', '3 million'
        glued = left or bool(m.group(1)) or bool(m.group(3)) or bool(run) or (after[:1].isascii() and after[:1].isalpha())
        if glued:
            continue
        if len(m.group(2)) == 4 and 1000 <= int(m.group(2)) <= 2999:
            continue                                # 홀로 선 연도('2099 시장 선거')
        return True                                 # 홀로 선 수('요금 400', '400')
    return False


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
        if set(map(str, raw)) - set(model.INPUT_KEYS):
            return f"계산 입력 '{k}'에 둘 수 없는 칸이 있다({', '.join(sorted(set(map(str, raw)) - set(model.INPUT_KEYS)))})"
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
    try:
        tree = ast.parse(formula, mode="eval")
        got = _eval(tree, names)
    except (SyntaxError, ValueError, ZeroDivisionError) as e:
        return f"계산 값 '{n.get('value')}'의 식을 계산하지 못했다: {e}"
    unused = sorted(set(names) - _names(tree))
    if unused:
        return f"계산 값 '{n.get('value')}'의 식이 입력({', '.join(unused)})을 쓰지 않는다 — 쓰지 않는 입력은 적지 않는다"
    bad = _const_error(tree, counts_only=bool(counts) and counts == set(names), unit=model._s(n.get("unit")))
    if bad:
        return (f"계산 값 '{n.get('value')}'의 {bad}은 출처가 없다 — 식의 수는 단위를 바꾸려고 곱하거나 나누는 10의 거듭제곱만 쓴다. "
                "다른 값은 입력으로 적는다")
    for k in names:                                 # 입력마다 결과를 움직여야 한다('a - a + …', 'a * 0 + …' 는 입력을 쓴 것이 아니다)
        moved = dict(names, **{k: names[k] * 1.37 + 0.731})
        try:
            if math.isclose(_eval(tree, moved), got, rel_tol=1e-12, abs_tol=1e-12):
                return f"계산 값 '{n.get('value')}'의 식에서 입력 '{k}'이 결과를 바꾸지 않는다 — 식이 입력을 쓰지 않는 것이다"
        except ZeroDivisionError:
            pass
    official = [names[k] for k in names if k not in counts]
    if not counts and any(math.isclose(got, v, rel_tol=0, abs_tol=1e-9) for v in official):
        return f"계산 값 '{n.get('value')}'의 식이 입력 하나를 그대로 옮긴 것이다 — 공식 수치로 적는다"
    want = to_number(n.get("value"))
    if want is None or not math.isclose(_round(got, rule), want, rel_tol=0, abs_tol=1e-9):
        return f"계산 값 '{n.get('value')}'이 식({formula})을 다시 계산한 값({_round(got, rule):g})과 다르다"
    return ""


def number_errors(issue: dict, evidences: dict) -> list[tuple[str, str]]:
    """[(칸 경로, 문구)]. 글의 수량 토큰마다 종류를 적었는가, 적은 종류의 검사를 통과하는가."""
    errs: list[tuple[str, str]] = []
    seen: dict[int, tuple[str, dict]] = {}
    matched: set[int] = set()
    for path, text, nums, item in model.reader_items(issue):
        cited = set(model.item_evidence_ids(item)) if item is not None else set(evidences)
        for n in nums:
            if not isinstance(n, dict):
                errs.append((path, "숫자 항목은 사전이다"))
            elif id(n) not in seen:
                seen[id(n)] = (path, n)
                extra = sorted(set(map(str, n)) - set(model.NUMBER_KEYS))
                if extra:
                    errs.append((path, f"숫자 항목에 둘 수 없는 칸이 있다({', '.join(extra)})"))
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
            matched.add(id(n))
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
    for k, (path, n) in seen.items():
        if k not in matched and n.get("kind") in model.NUMBER_KINDS:
            errs.append((path, f"숫자 '{n.get('value')}'이 그 숫자를 적은 칸의 글에 없다 — 글에 없는 숫자 항목은 지운다(검사받지 않고 실린다)"))
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
