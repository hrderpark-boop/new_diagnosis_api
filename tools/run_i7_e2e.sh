#!/bin/bash
# I-7: 신규 파이프라인(outer=3) end-to-end 1회 + 2회차 0콜. 방어 포함.
set -u
cd /Users/daniel/python_new/new_diagnosis_api
PY=/Users/daniel/python_new/.venv/bin/python
FIX=tests/fixtures/kimbautong_te.json
LOG=/tmp/i7.log
: > "$LOG"
log() { echo "$@" | tee -a "$LOG"; }
credit_hit() { grep -q "GEMINI_CREDIT_DEPLETED\|크레딧소진" "$1" 2>/dev/null; }

log "=== I-7 end-to-end: 신규 파이프라인 outer=3 (예상 ≈ \$1.71) ==="
log "--- preflight ---"
$PY tools/credit_probe.py > /tmp/i7_pf.log 2>&1; PF=$?
tail -1 /tmp/i7_pf.log | tee -a "$LOG"
if [ $PF -ne 0 ]; then log "🛑 ABORT: 크레딧 미가용(code=$PF)"; exit $PF; fi
log "✅ preflight OK"

rm -f .analysis_cache/*.json 2>/dev/null
log "--- run (cold, outer=3) ---"
$PY tools/fixture_reanalyze.py analyze "$FIX" > /tmp/i7_run.json 2>/tmp/i7_run.err
if credit_hit /tmp/i7_run.err; then
  log "🛑 ABORT: 크레딧소진 발생 → 무효."; exit 4
fi
grep -E "재분석 계측|analysis_degraded|🚨 분석 오염" /tmp/i7_run.err | tail -3 | tee -a "$LOG"

log "--- 2회차 0콜 검증 (캐시 재사용) ---"
$PY tools/fixture_reanalyze.py analyze "$FIX" > /tmp/i7_recache.json 2>/tmp/i7_recache.err
grep "재분석 계측" /tmp/i7_recache.err | tail -1 | tee -a "$LOG"
log "=== I-7 DONE ==="
