"""점수 산식(§5-1 · 계획 5-2 표). DB 를 모르는 순수 함수. 중간값은 반올림하지 않는다(저장 때 소수 여섯째 자리).

v = Σ_{ok_v} c·x / Σ_{ok_v} c  (c = 언론 0.60, 검색 0.25, 위키 0.15 · 수집이 실패한 종류는 빼고 나머지로 다시 나눈다)
H(d) = 0.7·H(d−1) + v(d)       (v 가 없음이면 H(d) = H(d−1))
B = |나타난 종류 ∩ ok_B| / |ok_B|
P = min(v ≥ 0.1 인 날 수, 7) / 7  (날 수는 최근 7일 [d−6, d] · config.P_WINDOW_DAYS)
D = min(1, (2f + e) / 10)       (최근 7일에 처음 생긴 f, e)
S_raw = 100·(0.40·min(1, H/2.5) + 0.25·B + 0.15·P + 0.20·D),  score = floor(round(S_raw, 6) + 0.5)
"""
from __future__ import annotations

import math

from ozl.signals import config

NEWS, SEARCH, WIKI, OFFICIAL = "언론", "검색", "위키백과", "공공 원문"
KINDS = (NEWS, SEARCH, WIKI, OFFICIAL)          # 화면과 기록에 쓰는 순서
V_KINDS = {NEWS: config.C_NEWS, SEARCH: config.C_SEARCH, WIKI: config.C_WIKI}


def L(A: int) -> float:
    return min(1.0, math.log(1 + A) / math.log(config.L_BASE))


def grade(raw) -> float:
    """급상승 검색량 표기 → 등급(§5-2). 못 읽으면 0.40(올랐다는 사실만)."""
    from ozl.pulse.signals import parse_traffic
    n = parse_traffic(str(raw)) if raw else None
    if n is None:
        return config.GRADE_UNKNOWN
    for bound, g in config.GRADE_STEPS:
        if n < bound:
            return g
    return config.GRADE_TOP


def ordered(kinds) -> list[str]:
    return [k for k in KINDS if k in kinds]


def v_value(A: int, g: float, w: float | None, ok) -> float | None:
    x = {NEWS: L(A), SEARCH: g, WIKI: w or 0.0}
    ks = [k for k in V_KINDS if k in ok]
    if not ks:
        return None
    return sum(V_KINDS[k] * x[k] for k in ks) / sum(V_KINDS[k] for k in ks)


def h_next(prev_h: float, v: float | None) -> float:
    return prev_h if v is None else config.H_DECAY * prev_h + v


def h_screen(H: float) -> float:
    return min(1.0, H / config.H_SCREEN)


def present_kinds(A: int, g: float, w: float | None, official: bool) -> list[str]:
    on = {NEWS: A >= 1, SEARCH: g > 0, WIKI: bool(w and w > 0), OFFICIAL: official}
    return [k for k in KINDS if on[k]]


def b_value(present, ok) -> float | None:
    ok = set(ok)
    if not ok:
        return None
    return len(set(present) & ok) / len(ok)


def p_days(v_hist: dict, day: str, first_day: str, window: int | None) -> list[str]:
    """P 에 세는 날(v ≥ 0.1, 없음인 날과 이슈가 있기 전 날은 빼고)."""
    lo = first_day if window is None else max(first_day, config.day_add(day, -(window - 1)))
    return sorted(d for d, v in v_hist.items() if lo <= d <= day and v is not None and v >= config.V_ACTIVE)


def p_value(n_days: int) -> float:
    return min(n_days, config.P_DAYS) / config.P_DAYS


def d_value(f: int, e: int) -> float:
    return min(1.0, (config.D_FOLLOWUP_W * f + e) / config.D_DIV)


def s_raw(H: float, B: float | None, P: float, D: float, v_missing: bool = False) -> float | None:
    if v_missing or B is None:
        return None
    return 100 * (config.W_H * h_screen(H) + config.W_B * B + config.W_P * P + config.W_D * D)


def display(s: float | None) -> int | None:
    """사사오입. 파이썬 round() 는 짝수 쪽으로 반올림해 44.5 → 44 가 된다."""
    return None if s is None else math.floor(round(s, 6) + 0.5)


def day_values(*, A: int, g: float, w: float | None, official: bool, ok, prev_H: float, v_hist: dict, fe_hist: dict,
               f: int, e: int, day: str, first_day: str, p_window: int | None = None) -> dict:
    """한 이슈의 날짜 d 값. v_hist·fe_hist 는 d 전날까지의 {날: v}, {날: (f, e)}."""
    win = config.P_WINDOW_DAYS if p_window is None else p_window
    v = v_value(A, g, w, ok)
    H = h_next(prev_H, v)
    present = present_kinds(A, g, w, official)
    B = b_value(present, ok)
    hist = dict(v_hist)
    hist[day] = v
    pd = p_days(hist, day, first_day, win)
    P = p_value(len(pd))
    lo = config.day_add(day, -(config.D_WINDOW_DAYS - 1))
    fs = f + sum(x[0] for d, x in fe_hist.items() if lo <= d < day)
    es = e + sum(x[1] for d, x in fe_hist.items() if lo <= d < day)
    Dv = d_value(fs, es)
    s = s_raw(H, B, P, Dv, v is None)
    return {"v": v, "H": H, "B": B, "P": P, "D": Dv, "score_raw": s, "score": display(s), "present": present,
            "p_days": pd, "f_sum": fs, "e_sum": es, "prev_H": prev_H}


# ── explain 의 식 한 줄씩
def _n(x: float) -> str:
    return "0" if x == 0 else f"{x:.6f}"


def _g(x) -> str:
    return "0" if not x else f"{x:g}"


def formula_lines(r: dict, ok) -> list[str]:
    """r = day_values 결과 + A, g. 사람이 손으로 대조할 수 있게 숫자를 넣은 식."""
    out = []
    ks = [k for k in V_KINDS if k in ok]
    if not ks:
        out.append("v = 없음(언론·검색 수집이 모두 실패) → H 는 전날 값 그대로")
    else:
        parts = []
        for k in ks:
            if k == NEWS:
                parts.append(f"{V_KINDS[k]:.2f}×L({r['A']})={_n(V_KINDS[k] * L(r['A']))}")
            elif k == SEARCH:
                parts.append(f"{V_KINDS[k]:.2f}×{_g(r['g'])}={_n(V_KINDS[k] * r['g'])}")
            else:
                parts.append(f"{V_KINDS[k]:.2f}×{_g(r.get('w'))}={_n(V_KINDS[k] * (r.get('w') or 0))}")
        den = sum(V_KINDS[k] for k in ks)
        out.append(f"v = ({' + '.join(parts)}) / {den:.2f} = {_n(r['v'])}")
    hv = "없음" if r["v"] is None else _n(r["v"])
    if r["v"] is None:
        out.append(f"H = {_n(r['prev_H'])} (v 없음) → 화면용 {_n(h_screen(r['H']))}")
    else:
        out.append(f"H = 0.7×{_n(r['prev_H'])} + {hv} = {_n(r['H'])} → 화면용 {h_screen(r['H']):.6f}")
    okl = ordered(ok)
    pr = [k for k in ordered(r["present"]) if k in ok]
    if okl:
        out.append(f"B = |{{{', '.join(pr)}}}| / |{{{', '.join(okl)}}}| = {len(pr)}/{len(okl)}")
    else:
        out.append("B = 없음(수집에 성공한 종류가 없음)")
    days = ", ".join(d[5:] for d in r["p_days"])
    out.append(f"P = v≥0.1 인 날 {{{days}}} {len(r['p_days'])}일 / 7 = {_n(r['P'])}")
    out.append(f"D = min(1, (2×{r['f_sum']} + {r['e_sum']})/10) = {_n(r['D'])}")
    if r["score_raw"] is None:
        out.append("S_raw = 없음(v 또는 B 가 없음)")
    else:
        out.append(f"S_raw = 100×(0.40×{h_screen(r['H']):.6f} + 0.25×{r['B']:.6f} + 0.15×{r['P']:.6f} + "
                   f"0.20×{_n(r['D'])}) = {r['score_raw']:.6f} → {r['score']}")
    return out
