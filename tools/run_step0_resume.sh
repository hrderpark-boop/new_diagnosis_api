#!/bin/bash
# Step 0 재개: run 1(유효) 보존, run 2·3만 cold 확보 → R-3 완결.
# 방어: ①프리플라이트 ②각 run total_calls>0(cold 확인) ③크레딧소진 즉시 중단·무효.
set -u
cd /Users/daniel/python_new/new_diagnosis_api
PY=/Users/daniel/python_new/.venv/bin/python
FIX=tests/fixtures/kimbautong_te.json
LOG=/tmp/step0_resume.log
: > "$LOG"
log() { echo "$@" | tee -a "$LOG"; }
credit_hit() { grep -q "GEMINI_CREDIT_DEPLETED\|크레딧소진" "$1" 2>/dev/null; }

log "=== Step 0 재개: run 2·3 (run 1 보존) ==="
if [ ! -s /tmp/step0_e2b_1.json ]; then
  log "🛑 run 1 결과 없음 — 재개 불가"; exit 2
fi
log "run 1 보존 확인: $(wc -c < /tmp/step0_e2b_1.json) bytes"

log "--- preflight: 크레딧 프로브 ---"
$PY tools/credit_probe.py > /tmp/step0_pf2.log 2>&1; PF=$?
tail -1 /tmp/step0_pf2.log | tee -a "$LOG"
if [ $PF -ne 0 ]; then log "🛑 ABORT: 크레딧 미가용(code=$PF)"; exit $PF; fi
log "✅ preflight OK"

for i in 2 3; do
  rm -f .analysis_cache/*.json 2>/dev/null
  rm -f /tmp/step0_e2b_$i.invalid 2>/dev/null
  log "--- run $i (cold) ---"
  ANALYSIS_SAMPLES=3 $PY tools/fixture_reanalyze.py analyze "$FIX" \
    > /tmp/step0_e2b_$i.json 2>/tmp/step0_e2b_$i.err
  if credit_hit /tmp/step0_e2b_$i.err; then
    echo "INVALID: 크레딧소진" > /tmp/step0_e2b_$i.invalid
    log "🛑 ABORT at run $i: 크레딧소진 → 전체 중단, run $i 무효."
    exit 4
  fi
  METER=$(grep "재분석 계측" /tmp/step0_e2b_$i.err | tail -1)
  CALLS=$(echo "$METER" | grep -oE "총 [0-9]+콜" | grep -oE "[0-9]+")
  log "  $METER"
  if [ -z "$CALLS" ] || [ "$CALLS" -eq 0 ]; then
    log "🛑 run $i total_calls=0 — cold 아님(캐시 반환). 재현성 무효 → 중단."
    echo "INVALID: 0콜(캐시)" > /tmp/step0_e2b_$i.invalid
    exit 5
  fi
  log "  ✅ run $i cold 확인 (calls=$CALLS)"
done

# (a) 2회차 0콜 검증 (run3 캐시 재사용)
log "--- (a) 2회차 0콜 검증 (run3 캐시 재사용) ---"
ANALYSIS_SAMPLES=3 $PY tools/fixture_reanalyze.py analyze "$FIX" \
  > /tmp/step0_recache.json 2>/tmp/step0_recache.err
RMETER=$(grep "재분석 계측" /tmp/step0_recache.err | tail -1)
log "  $RMETER"
RCALLS=$(echo "$RMETER" | grep -oE "총 [0-9]+콜" | grep -oE "[0-9]+")
if [ "${RCALLS:-1}" -eq 0 ]; then log "  ✅ (a) 2회차 0콜 확인(캐시 적중)"; \
  else log "  ⚠️ (a) 2회차 ${RCALLS}콜 — 0 아님(캐시 키 점검 필요)"; fi

log "=== STEP0 RESUME DONE ==="
