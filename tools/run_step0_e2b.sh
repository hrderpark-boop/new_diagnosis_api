#!/bin/bash
# Step 0 (최우선): E-2b×3 안전 재실행 — R-3 완결.
# 방어: ①선행 크레딧 프리플라이트 ②실행 중 크레딧소진 1건 → 전체 즉시 중단·무효
#       ③(a) 2회차 0콜 검증 통합(별도 실행 없음). 비용 큰 arm(E-2b)만 실행.
set -u
cd /Users/daniel/python_new/new_diagnosis_api
PY=/Users/daniel/python_new/.venv/bin/python
FIX=tests/fixtures/kimbautong_te.json
LOG=/tmp/step0.log
: > "$LOG"

log() { echo "$@" | tee -a "$LOG"; }
credit_hit() { grep -q "GEMINI_CREDIT_DEPLETED\|크레딧소진" "$1" 2>/dev/null; }

log "=== Step 0: E-2b×3 (tie-break, ANALYSIS_SAMPLES=3, cold) ==="
log "예상 비용 ≈ \$1.32 × 3 ≈ \$4 (프리플라이트 통과 시에만 시작)"

# ── ① 프리플라이트 ──────────────────────────────────────────
log "--- preflight: 크레딧 프로브 ---"
$PY tools/credit_probe.py > /tmp/step0_preflight.log 2>&1
PF=$?
tail -1 /tmp/step0_preflight.log | tee -a "$LOG"
if [ $PF -ne 0 ]; then
  log "🛑 ABORT: 크레딧 미가용(code=$PF) — E-2b×3 시작하지 않음. 무효 실행 방지."
  exit $PF
fi
log "✅ preflight OK — 크레딧 사용 가능, 배치 시작"

# ── E-2b×3 (cold, 크레딧소진 시 즉시 전체 중단) ──────────────
for i in 1 2 3; do
  rm -f .analysis_cache/*.json 2>/dev/null
  log "--- run $i (cold) ---"
  ANALYSIS_SAMPLES=3 $PY tools/fixture_reanalyze.py analyze "$FIX" \
    > /tmp/step0_e2b_$i.json 2>/tmp/step0_e2b_$i.err
  if credit_hit /tmp/step0_e2b_$i.err; then
    echo "INVALID: 크레딧소진 발생" > /tmp/step0_e2b_$i.invalid
    log "🛑 ABORT at run $i: GEMINI_CREDIT_DEPLETED 발생 → 전체 중단."
    log "   run $i 이후 표본 무효 표기(.invalid). 부분 데이터로 판정 금지."
    exit 4
  fi
  grep "재분석 계측" /tmp/step0_e2b_$i.err | tail -1 | tee -a "$LOG"
  log "DONE run $i"
done

# ── (a) 통합: 2회차 0콜 검증 (run3 캐시 재사용, cold 아님) ────
log "--- (a) 2회차 0콜 검증 (run3 캐시 재사용) ---"
ANALYSIS_SAMPLES=3 $PY tools/fixture_reanalyze.py analyze "$FIX" \
  > /tmp/step0_recache.json 2>/tmp/step0_recache.err
grep "재분석 계측" /tmp/step0_recache.err | tail -1 | tee -a "$LOG"
log "(참고: run1 계측 = §8 baseline, 위 재계측 = 2회차 0콜 여부)"

log "=== ALL STEP0 DONE ==="
