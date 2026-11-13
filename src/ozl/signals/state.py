"""상태 판정(§6-1 · 계획 5-2의 상태 정의). 아래 순서로 보고 처음 맞는 것을 쓴다(돌려주는 규칙 번호도 이 번호).

1 종료(사람 판단) · 2 휴면(7일째 이상, 최근 7일 v 모두 0.1 미만) · 3 다시 오름 · 4 새로 뜸(첫날, v ≥ 0.3)
5 커지는 중(v 이틀 연속 오름) · 6 정점(최댓값의 0.9 이상이고 더 오르지 않음) · 7 식는 중(최댓값의 0.7 미만이고 이틀 연속 내림)
8 직전 상태 그대로(첫날 v < 0.3 이면 빈 칸). 직전 상태가 다시 오름이면 빈 칸(다시 오름은 그날 하루만)

다시 오름은 계획 문장("이틀 넘게 최댓값의 0.3 미만이다가 0.5 이상으로 오르거나 새 후속 사건이 생김")을 따른다:
d 바로 전 사흘(이슈가 있던 날)이 모두 v < 0.3×peak(d−1) 이고, v(d) ≥ 0.5×peak(d−1) 이거나 그날 후속 사건이 1건 이상.
없는 날의 v 는 0 으로 본다. v(d) 가 없음이면 직전 상태. 진행 중인 오늘은 v(D) ≥ v(D−1) 일 때만 새로 판정하고
휴면·식는 중은 진행 중인 날로 새로 판정하지 않는다.
"""
from __future__ import annotations

from ozl.signals import config

NAMES = {1: "종료", 2: "휴면", 3: "다시 오름", 4: "새로 뜸", 5: "커지는 중", 6: "정점", 7: "식는 중", 8: "직전 상태 유지"}


def _v(hist: dict, d: str, first_day: str) -> float:
    if d < first_day:
        return 0.0
    x = hist.get(d)
    return 0.0 if x is None else x


def _rules(d: str, first_day: str, hist: dict, f_new: int) -> tuple[str, int] | None:
    age = config.day_diff(d, first_day) + 1
    vd = _v(hist, d, first_day)
    p1 = max([_v(hist, config.day_add(first_day, i), first_day) for i in range(age - 1)] or [0.0])
    peak = max(p1, vd)
    if age >= config.DORMANT_DAYS and all(_v(hist, config.day_add(d, -i), first_day) < config.V_ACTIVE
                                          for i in range(config.DORMANT_DAYS)):
        return "휴면", 2
    low_days = [config.day_add(d, -i) for i in range(1, config.RISE_LOW_DAYS + 1)]
    if p1 > 0 and all(x >= first_day for x in low_days) and \
            all(_v(hist, x, first_day) < config.RISE_LOW * p1 for x in low_days) and \
            (vd >= config.RISE_HIGH * p1 or f_new >= 1):
        return "다시 오름", 3
    if age == 1 and vd >= config.STATE_NEW_V:
        return "새로 뜸", 4
    v1, v2 = _v(hist, config.day_add(d, -1), first_day), _v(hist, config.day_add(d, -2), first_day)
    if vd > v1 > v2:
        return "커지는 중", 5
    if peak > 0 and vd >= config.STATE_PEAK * peak and vd <= v1:
        return "정점", 6
    if vd < config.STATE_COOL * peak and vd < v1 < v2:
        return "식는 중", 7
    return None


def state_of(d: str, first_day: str, hist: dict, prev_state: str | None, f_new: int = 0, ended: bool = False,
             partial: bool = False) -> tuple[str | None, int | None]:
    """(상태, 규칙 번호). hist = {날: v} (d 포함, 없음은 None)."""
    if ended:
        return "종료", 1
    # 다시 오름은 그날 하루만 붙는다: 다음 날은 규칙으로 다시 보고, 맞는 것이 없으면 상태 없음.
    keep = (prev_state, 8) if prev_state and prev_state != "다시 오름" else (None, None)
    if hist.get(d) is None:
        return keep
    if partial and _v(hist, d, first_day) < _v(hist, config.day_add(d, -1), first_day):
        return keep
    got = _rules(d, first_day, hist, f_new)
    if got is None:
        return keep
    if partial and got[0] in ("휴면", "식는 중"):
        return keep
    return got
