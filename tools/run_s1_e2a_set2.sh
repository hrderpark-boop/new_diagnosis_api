#!/bin/bash
# S-1: 교집합 재현성 검증용 Set 2 — E-2a(ANALYSIS_SAMPLES=1) 3회 cold.
# 방어(S-2): ①프리플라이트 ②각 run total_calls>0 ③크레딧소진 즉시 중단·무효.
set -u
cd /Users/daniel/python_new/new_diagnosis_api
PY=/Users/daniel/python_new/.venv/bin/python
FIX=tests/fixtures/kimbautong_te.json
LOG=/tmp/s1.log
: > "$LOG"
log() { echo "$@" | tee -a "$LOG"; }
credit_hit() { grep -q "GEMINI_CREDIT_DEPLETED\|크레딧소진" "$1" 2>/dev/null; }

log "=== S-1 Set 2: E-2a(n=1) × 3 cold (예상 ≈ \$1.71) ==="
log "--- preflight ---"
$PY tools/credit_probe.py > /tmp/s1_pf.log 2>&1; PF=$?
tail -1 /tmp/s1_pf.log | tee -a "$LOG"
if [ $PF -ne 0 ]; then log "🛑 ABORT: 크레딧 미가용(code=$PF)"; exit $PF; fi
log "✅ preflight OK"

for i in 1 2 3; do
  rm -f .analysis_cache/*.json 2>/dev/null
  rm -f /tmp/s1_e2a_$i.invalid 2>/dev/null
  log "--- set2 run $i (cold) ---"
  ANALYSIS_SAMPLES=1 $PY tools/fixture_reanalyze.py analyze "$FIX" \
    > /tmp/s1_e2a_$i.json 2>/tmp/s1_e2a_$i.err
  if credit_hit /tmp/s1_e2a_$i.err; then
    echo "INVALID: 크레딧소진" > /tmp/s1_e2a_$i.invalid
    log "🛑 ABORT at run $i: 크레딧소진 → 전체 중단, run $i 무효."
    exit 4
  fi
  METER=$(grep "재분석 계측" /tmp/s1_e2a_$i.err | tail -1)
  CALLS=$(echo "$METER" | grep -oE "총 [0-9]+콜" | grep -oE "[0-9]+")
  log "  $METER"
  if [ -z "$CALLS" ] || [ "$CALLS" -eq 0 ]; then
    echo "INVALID: 0콜(캐시)" > /tmp/s1_e2a_$i.invalid
    log "🛑 run $i total_calls=0 — cold 아님(캐시). 재현성 무효 → 중단."; exit 5
  fi
  log "  ✅ run $i cold 확인 (calls=$CALLS)"
done
log "=== S-1 SET2 DONE ==="
