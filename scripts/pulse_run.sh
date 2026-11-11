#!/bin/zsh
# OZL Pulse 매시 실행 — launchd(com.hyunbin.ozl-pulse)가 매시 5분에 부른다. 모델 호출 없음(결정적 코드만).
# 로그: private/pulse/logs/run_YYYYMM.log · 새벽 4시대 실행에서 90일 지난 기록을 정리한다.
set -u
cd "${0:A:h}/.." || exit 1
mkdir -p private/pulse/logs
LOG="private/pulse/logs/run_$(date +%Y%m).log"
{
  echo "== $(date '+%Y-%m-%d %H:%M:%S %Z')"
  nice -n 10 .venv/bin/python -m ozl.pulse run
  echo "exit=$?"
  if [[ "$(date +%H)" == "04" ]]; then .venv/bin/python -m ozl.pulse prune; fi
} >>"$LOG" 2>&1
