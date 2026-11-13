"""화제 엔진(1판). 수집 DB 를 읽기 전용으로 읽어 전재를 묶고, 하루치 사건 그룹을 만들고, 여러 날의 이슈로 잇는다.

설계 정본: private/plan/engine_spec_20261114.md
"""

RULES_VER = "r1"     # 묶기·중복 규칙의 판
FORMULA_VER = "s1"   # 점수 산식의 판
