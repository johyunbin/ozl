"""시험 공통 — 출처 대장(src/ozl/research/sources_ledger.yaml)을 기본으로 '모두 허용'으로 바꿔 끼운다.

기존 시험은 지어낸 피드·소스 id 로 수집과 점수를 돌린다. 실제 대장은 그 id 를 모르므로(→ 불명 → 막힘)
대장 판정과 무관한 시험이 실제 대장 내용에 기대어 깨지지 않게 한다.
대장 자체를 시험하는 모듈은 pytestmark = pytest.mark.real_ledger 를 두고, 지어낸 대장 파일을 ledger.PATH 에 끼워 쓴다.
표지는 등록해 두므로 --strict-markers 에서 오타가 나면 시험이 멈춘다(모듈 속성처럼 조용히 '모두 허용'으로 굴러가지 않는다).
"""
from __future__ import annotations

import pytest

from ozl.research import ledger


class _AllowAll(dict):
    def get(self, key, default=None):  # noqa: ARG002
        return {"collect": "허용", "score_use": "허용"}


def pytest_configure(config):
    config.addinivalue_line("markers", "real_ledger: 출처 대장을 '모두 허용'으로 바꿔 끼우지 않는다")


@pytest.fixture(autouse=True)
def _permissive_ledger(request, monkeypatch):
    if request.node.get_closest_marker("real_ledger"):
        return
    if hasattr(request.module, "REAL_LEDGER"):   # 옛 방식 — 표지로 바꾸라고 멈춘다
        raise RuntimeError(f"{request.module.__name__}: REAL_LEDGER 대신 pytestmark = pytest.mark.real_ledger 를 쓴다")
    monkeypatch.setattr(ledger, "load", lambda path=None: _AllowAll())
