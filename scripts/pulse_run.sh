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
  # 화제 엔진: 수집 뒤에 한 번. 실패해도 수집의 종료 코드와 로그는 그대로다. 300초를 넘기면 끊는다(엔진이 멈춰 수집 실행 전체를 붙잡지 않게).
  { echo "== $(date '+%Y-%m-%d %H:%M:%S %Z')"; nice -n 10 perl -e 'alarm 300; exec @ARGV' .venv/bin/python -m ozl.signals run; echo "exit=$?"; } >>"private/pulse/logs/engine_$(date +%Y%m).log" 2>&1
  if [[ "$(date +%H)" == "04" ]]; then .venv/bin/python -m ozl.pulse prune; fi
} >>"$LOG" 2>&1
