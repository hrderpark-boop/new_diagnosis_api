# BEI형 대화 구조 설계안 — 2026-11 (0단계, 코드 없음)

작성 2026-11-04. 검토자 승인 전까지 코드를 바꾸지 않는다.

**바꾸는 것 한 줄**: "하위역량 26개 × 앵커 1 + 후속 1~2"(설문형) → "챕터당 사례 2~3개 심층 + 미충족 하위역량 보완"(BEI형).
10/23~11/4 의 가드·고정 문장은 안전망으로 남기되, 문장은 LLM 이 쓰고 백엔드는 감독(슬롯 추적·커버리지·종료 판단)만 한다.

줄 번호는 현재 main(5a80d20) 기준. 약칭: D = `diag_project/routes/diagnoses.py`, I = `services/instruction_decider.py`,
T = `services/traversal.py`, E = `services/event_tracker.py`, L1/L2/L3 = `prompts/phase3a/layer{1,2,3}_*.py`, S = `diag_project/llm_service.py`.

---

## 0. 현재 구조에서 확인한 사실 (설계의 전제)

| 사실 | 위치 | 설계에 미치는 영향 |
|---|---|---|
| 원장은 전부 `DiagnosisSession.self_assessment_data` JSON 한 컬럼. 순회 원장 4키(`asked_subs`·`current_target`·`turns_on_target`·`result_probed`) + 탐침 이력 + 문체 카운터 + guard_log | T:116, D:3263~3410 | 스키마 변경 없이 키만 바꾼다 |
| 챕터 종료는 "그 챕터 하위역량 **전부** asked" 가 필수(`_unexplored_remaining`). 서킷브레이커(16/13/22/13/13턴)도 그 전엔 안 닫힘 | I:765~773 | 사람관리는 사실상 9×3=27턴. 새 구조는 예산을 절대값으로 건다 |
| 사건(Event)은 LLM 자기보고가 아니라 코치 질문 정규식으로 리더 답 원문을 S/T/A/R 칸에 통째로 넣는 휴리스틱. T 칸은 거의 안 참 | E:73~105, D:3472~3537 | 슬롯 판정을 Haiku 로 바꾸고 Event 행은 사례 1개=1행으로 다시 쓴다 |
| 분석의 판정 단위는 전부 하위역량. 같은 발화를 여러 하위역량 근거로 쓰는 것을 막는 코드 없음(`_audit_multi_mapping` 은 경고만, dedup 없음) | S:1506, S:2274~2311 | 사례 1개 → 하위역량 여러 개 배정이 이미 가능. 분석 코드 수정 최소 |
| measured = `asked ∧ evidence≥1 ∧ 게이트 통과`(`scoring.is_measured`, `_finalize_ledger`). 그 외는 전부 '사례 미확인' 1.0 | `scoring.py:36`, S:1878~1940, `report_ledger.py:139` | asked 의 뜻을 "사례로 증명됐거나 SWEEP 에서 물은 것" 으로 재정의하면 `is_measured` 는 그대로 |
| 분석에 들어가는 Event 는 챕터 전문 뒤 `[수집된 핵심 사건]` 텍스트 블록 한 군데 | `routes/reports.py:56~94` | 사례 행을 거기 쓰면 분석 입력이 구조를 얻는다 |
| 턴당 LLM 호출: 본 호출 1 + 조건부 재생성(13곳 각 1회) + 사다리 판정 최대 3 | D:1073~1150, 8-x 단계 | 새 구조는 본 1 + 슬롯 판정 1 + 재생성 ≤2 로 고정 |
| `FM_LLM_STUB=1` 은 코치 본 호출·재생성만 스텁. 판정 호출은 None(폴백) | S:1413~1421, `llm_judge.py:17` | 슬롯 판정·매핑 호출도 스텁 분기를 넣어야 1단계 스모크가 완주한다 |
| Haiku 5.5 요율 in 0.10 / out 0.50 USD/1M. 10/29 실측 대화 비용 ≈ $0.087/세션 | S:295, 메모리 | 아래 비용 추정의 근거 |

---

## 1. 챕터 상태기계

```
DIAGNOSIS_CONFIRM ─정의 답 실질─▶ ALIGN ─1턴─▶ EPISODE(1) ─종료─▶ [매핑] ─▶ EPISODE(2) ─▶ [매핑] ─┬─▶ EPISODE(3) ─▶ [매핑] ─▶ SWEEP ─▶ CLOSE
                                                                                           └─(예산·커버리지 조건)──────────▶ SWEEP ─▶ CLOSE
```

상태는 원장 `chapter_state[chapter] ∈ {confirm, align, episode, sweep, close}` 에 명시적으로 둔다(지금은 메시지 표식에서 매 턴 역산, I:947~1016).
리더 턴 수 `bei_turns[chapter]` 는 ALIGN 앵커에 대한 첫 답부터 센다(정의 답은 별도 1턴).

| 상태 | 진입 | 이 상태에서 나가는 코치 턴 | 종료(다음 상태로) |
|---|---|---|---|
| **DIAGNOSIS_CONFIRM** | 챕터 시작(첫 챕터는 INTRO 동의 뒤, 이후 챕터는 전환 팝업 동의 뒤) | 고정 정의 질문 1문장(`definition_question`, 8-k 유지) | 정의 답 실질(10자 이상, `def_reask` 1회 유지) → ALIGN |
| **ALIGN** | 정의 답 수신 | [LLM 되받기 2~3문장] + [고정 정의] + [목록] + [고정 안내] + **"먼저 하나를 깊게 들어볼게요."(신규 고정, 페르소나 6종)** + [사례 1 여는 앵커] | 즉시(1턴) → EPISODE(1). 답이 '네/넵' 이면 앵커 재질문 1회(`reask_anchor` 유지) |
| **EPISODE(n)** | 여는 앵커 발화됨 | 매 턴: [되받기 1~3] + [미충족 슬롯을 향한 질문 1] (LLM 전체 작성) | 아래 §2 종료 조건 → 매핑 호출 → 다음 상태 결정(§1-1) |
| **SWEEP** | 사례 단계 끝 | 커버리지 없는 하위역량마다 [되받기] + 앵커 1 → (사례가 나오면) 후속 ≤1 | 미커버 0 또는 예산 소진 → CLOSE |
| **CLOSE** | SWEEP 끝 | 8-d 템플릿(요약 2문장 + `chapter_end_bridge`, 유지) → 전환 팝업. 마지막 챕터는 DIAGNOSIS_COMPLETE | 다음 챕터 DIAGNOSIS_CONFIRM |

### 1-1. 사례 수와 예산 (챕터 리더 턴 16~20)

| 챕터 | 하위역량 | 예산 B(리더 턴) | 비고 |
|---|---|---|---|
| 조직관리 | 4 | 16 | 2사례 × ≤8 이면 SWEEP 0턴. 매핑이 3/4 이상 덮으면 통과 기준 충족 |
| 성과관리 | 5 | 18 | |
| 사람관리 | 9 | 20 | 3사례가 5~6개를 덮고 SWEEP 이 3~4개 |
| 일관리 | 5 | 18 | |
| 자기관리 | 3 | 16 | |

- 사례 종료 뒤 결정: `남은 턴 = B − bei_turns`, `미커버 = 챕터 하위역량 − covered(strong)`, `예비 = min(미커버, 3)`.
  - 사례 수 < 2 → EPISODE(n+1).
  - 사례 수 = 2 → `미커버 ≥ 2 and 남은 턴 − 예비 ≥ 5` 이면 EPISODE(3), 아니면 SWEEP.
  - 사례 수 = 3 → SWEEP.
- EPISODE 안에서 `bei_turns ≥ B − 1` 이면 사례를 강제 종료(매핑은 그대로 호출).
- 리더가 종료 의사(명시)면 현 상태와 무관하게 CLOSE(기존 0.7 블록 I:547~574 유지, `CHAPTER_ONE_MORE_ASK` 는 삭제 — 사례 중간이면 "지금 사례만 마무리할게요" 1턴 뒤 CLOSE).
- 지금의 `MAX_TURNS`(40/50) 안전망은 남긴다(I:242). `MIN_EVENTS`·`MIN_TURNS_BEFORE_END`·`MIN_EXPLORED`·`chapter_turn_cap` 은 삭제.

---

## 2. EPISODE 슬롯 6개

| # | 슬롯 키 | 뜻 | 충족 기준(판정 프롬프트에 그대로 씀) |
|---|---|---|---|
| 1 | `context` 상황·시점 | 언제, 누구와, 무엇이 걸려 있었나 | 시점(연·분기·"지난달" 등 상대 표현 포함)과 상대 또는 대상이 둘 다 있음 |
| 2 | `action` 리더 행동 | 리더가 **직접** 한 말·결정·행동 | 1인칭 행동 서술("제가 …했다"). 팀이 한 일·방침 설명만이면 partial |
| 3 | `reaction` 상대 반응 | 팀원·상대가 어떻게 받았나 | 상대의 말·행동·태도 변화가 하나라도 있음 |
| 4 | `result` 결과 | 그 뒤 무엇이 달라졌나(정성 허용) | 변화 서술 1개. "잘 됐다" 만이면 partial |
| 5 | `criterion` 판단 기준 | 왜 그렇게 했나, 버린 선택지 | 이유 또는 트레이드오프 1개 |
| 6 | `reflection` 다시 한다면·배운 것 | 돌아보며 바꿀 점 또는 배운 점 | 1개 |

### 2-1. 판정 — Haiku 1콜/턴

- 호출 시점: 리더 답 수신 직후, 코치 본 호출 **전**(결과가 이번 턴 프롬프트에 들어간다).
- 입력: 이 사례의 전문(코치 질문 + 리더 답, 여는 앵커부터) + 직전 슬롯 상태. 출력(JSON 스키마, `llm_schemas` 에 추가):
  `{"slots": {key: {"status": "filled|partial|empty", "quote": "리더 원문 그대로"}}, "no_case": bool, "switched_case": bool}`
- 결정론 병합: `filled` 는 되돌리지 않는다(sticky). `quote` 는 `filter_verbatim`(`level_gate.py:514`)로 원문 검증, 없으면 status 를 partial 로 강등.
- `no_case`(그런 일이 없다·기억 안 남) → §2-3. `switched_case`(다른 사례로 넘어감) → 사례 카드에 "직전 사례로 돌아가는 질문" 지시 1회, 다음 턴에도 참이면 현 사례 종료 후 새 사례로 등록(여는 앵커 없이, opener_sub = 매핑 결과).
- 실패·타임아웃 → 직전 상태 유지, guard_log `slot_judge=error`. 스텁(`FM_LLM_STUB`) → 턴 번호로 순서대로 한 슬롯씩 filled(1단계 스모크용).
- 비용: 입력 ≈ 1.5k·출력 ≈ 0.15k 토큰 → ≈ $0.0002/턴. 세션 100턴 ≈ $0.02.

### 2-2. 종료 조건

- `6/6 filled` **또는** 사례 리더 턴 = 8 **또는** 챕터 예산 도달(§1-1).
- 6/6 이 리더 턴 4 이전에 오면(장황형 리더) 그대로 종료한다. "사례당 5~8턴" 은 2단계 통과 기준(시뮬 지표)이지 강제 규칙이 아니다.
- 질문 순서는 LLM 이 정하되 사례 카드에 우선순위를 준다: context → action → reaction → result → criterion → reflection. `reflection` 은 `result` 가 filled 이후에만 지시한다.

### 2-3. 사례가 없을 때 (옛 ANCHOR_REASK 2·3회·ABSENCE_PROBE 의 재정의)

| 상황 | 처리 | 원장 |
|---|---|---|
| 여는 앵커 뒤 '네/넵/??' 단답 | `reask_anchor`("그럼 여쭤볼게요.") + 같은 앵커 1회(입력 이상 `ack_reask` 유지) | `anomaly_counts` |
| 여는 앵커 뒤 `no_case` 또는 2번째 단답 | LLM 에 "더 작은 단위로 1회 재질문"(EPISODE_RETRY) — 리더 턴 1 소모 | — |
| 재질문 뒤에도 `no_case` | 사례 폐기(leader_turns ≤ 2), opener_sub 를 `no_case_subs` 에 기록, 다른 하위역량 앵커로 새 사례 | `episodes[].status = "no_case"` |
| SWEEP 앵커 뒤 `no_case` 또는 단답 2회 | 그 하위역량을 `unconfirmed[chapter]` 에 기록(기존 키 D:958), 다음 앵커 | `unconfirmed` |

`reask_anchor_2`·`skip_item` 문장(`PERSONA_LINES`)은 삭제한다.

---

## 3. 사례 → 하위역량 매핑과 커버리지 원장

### 3-1. 매핑 — 사례 종료 시 Haiku 다중 라벨 1콜

- 입력: 사례 전문 + 이 챕터 하위역량 목록(이름 + `COMPETENCY_FRAMEWORK[..]["indicators"][k]["description"]` 1줄 + `SUBCOMPETENCY_MUST_ASK` 의 '행동:' 항목).
- 출력: `{"labels": [{"sub_key", "strength": "strong|weak", "quote"}]}`. `strong` = 그 하위역량의 **리더 행동**이 원문에 있음(태도·방침 설명만이면 weak). `quote` 는 verbatim 검증.
- 결정론 후처리: strong 상한 3개(넘으면 quote 가 긴 순), opener_sub 는 strong 이 아니어도 `weak` 로 최소 기록.
- SWEEP 후속 답에도 같은 호출을 쓴다(사례 전문 = 앵커 + 답 1~2턴).
- 비용 ≈ $0.0005/회, 세션 15회 ≈ $0.01.

### 3-2. 커버리지 원장 (신규 키, 모두 `self_assessment_data` 안)

```
episodes[chapter] = [{idx, opener_sub, opened_at_turn, leader_turns, slots{...}, status: done|no_case|budget|switched, labels[...]}]
covered[chapter]  = {sub_key: [{"episode": idx, "strength", "quote"}]}      # "사례 N 에서 증명"
sweep_asked[chapter] = [sub_key]                                             # SWEEP 앵커가 나간 것
unconfirmed[chapter] = [sub_key]                                             # 기존 키, 뜻만 §2-3 로
chapter_state[chapter], bei_turns[chapter], episode_slot_used[chapter] = [idx]   # 페르소나 슬롯 사례당 1회
```

### 3-3. 기존 asked / anchored 원장과의 관계

| 기존 키 | 처분 | 이유 |
|---|---|---|
| `asked_subs` | **유지, 파생값으로** — 사례 종료·SWEEP 앵커 때 `covered(strong) ∪ sweep_asked` 를 써넣는다 | `reports.py:30 _build_asked_subcompetencies`, self_eval, admin, report_prewarm 이 읽는다. 쓰는 쪽만 바꾸면 읽는 쪽 무수정 |
| `anchored_subs` | **유지** — 여는 앵커·SWEEP 앵커가 실제로 나간 하위역량 | `report_ledger.anchor_delivered` 와 누설 사전이 앵커 사전을 참조. 분석에서는 미사용이므로 부담 없음 |
| `current_target`·`turns_on_target`·`result_probed`·`probes_on_sub`·`action_probed`·`generalize_probed`·`generalize_pending`·`generalized`·`generalized_text`·`ladder_*`·`quantify_used`·`direct_q_count`·`emotion_q_count`·`contrast_q_count`·`persona_slot_used`·`michael_q_pending`·`bridge_idx`·`attitude_*`·`anchor_variant`(유지)·`ladder_avoid`(삭제) | **삭제**(anchor_variant 제외) | §6 삭제 목록의 기계가 쓰는 값. LLM 실패 롤백(`snapshot_ledger`)은 새 키 묶음으로 교체 |
| Event 테이블 | **유지, 사례 1개 = 1행** — 사례 종료 시 `situation=context quote, action, result`, `mapped_subcompetency = strong 라벨 ','.join`, `summary`, `is_complete = 6/6`, `tags = [weak 라벨]` | 분석 입력 `[수집된 핵심 사건]` 블록(`reports.py:77~94`)과 `conversation_compressor` 의 사건 요약이 그대로 동작 |

---

## 4. SWEEP

- 대상: `챕터 하위역량 − covered(strong)`, 순서는 `order_by_priority`(정의 순서 첫 항목 고정 + ALIGN 키워드 우선, T:40 유지).
- 턴 구성: 코치 턴 = [LLM 되받기 1~2] + **앵커 1(사전 52문, 페르소나 어미, 백엔드 삽입)**. LLM 의 자체 질문은 지운다(8-b ALIGN 과 같은 방식 `strip_trailing_question`).
- 후속 ≤1: 슬롯 판정에서 `action` 이 filled|partial 이고 `남은 턴 > 남은 미커버 수` 일 때만 LLM 질문 1턴(가장 비어 있는 슬롯 중 `action`→`result` 우선). 그 뒤 매핑 호출 → covered 에 `{"episode": "sweep", ...}`.
- `no_case`·단답 2회 → `unconfirmed`. 예산이 먼저 끝나면 남은 하위역량은 **미탐색**(asked 아님)으로 남긴다.
- SWEEP 안에서 리더가 긴 사례를 꺼내도 사례로 승격하지 않는다(후속 1턴까지). 예산 보호.

---

## 5. 분석 파이프라인 영향

| 질문 | 답 | 할 일 |
|---|---|---|
| `evidence_reselect` 가 사례 1개를 하위역량 여러 개에 배정할 수 있는가 | **이미 가능**. 재선택은 하위역량별·챕터 전문 기준이고(`level_gate.py:544`), 심층 분석도 "각 하위 지표를 독립 판정"(S:1658). 중복 금지 코드 없음 | 없음. `_audit_multi_mapping`(S:2274) 임계 "3개 이상 + 레벨 차 2" 는 BEI 에서 정상 상황이므로 경고 문구만 "검토 권고" 로 낮춘다 |
| 심층 분석이 사례를 알게 할 방법 | 지금은 `asked_subs` 로 "탐색 집중 대상" 블록(S:1537~1550)만 받는다 | 블록을 `covered` 로 확장: "하위역량 X — 사례 N(인용 '…')에서 증명". 심층이 그 인용 주변을 먼저 본다. 토큰 +300 이내 |
| `is_measured(asked, evidence)` | asked 의 뜻만 바뀜(§3-3) | 코드 무수정 |
| "사례 미확인" 재정의 | 현재: measured 아니면 전부 1.0 + `unconfirmed_kind ∈ {generalized, no_answer}`, `probe_deficit = not(generalize_probed ∧ probes≥3)` (`report_ledger.py:139~200`) | 아래 표로 교체. `generalize_probed` 삭제에 따른 `probe_deficit` 식 교체 필수(안 바꾸면 전부 True) |

**사례 미확인의 세 갈래 (리포트 라벨)**

| 갈래 | 조건(원장) | 라벨 | 점수 | 배지 |
|---|---|---|---|---|
| `no_case` | `sub ∈ unconfirmed[chapter]` (SWEEP 또는 여는 앵커에서 1회 물었고 없음) | 사례 미확인 | 1.0 | 기존 "근거 제한적" |
| `not_explored` | covered 도 sweep_asked 도 아님(예산 소진) | 미탐색 | 없음(공란, 기존 `mark_not_explored` 경로) | "이번 진단에서 다루지 못함" |
| `gate_dropped` | covered 인데 게이트 탈락(`evidence_missing/failed`) | 사례 미확인 | 1.0 | "사례는 있었으나 행동 근거 부족" (신규 문구 1줄) |

`probe_deficit` 는 `not_explored` 에만 True. `tools/analysis_lint.py` 의 집계 열도 세 갈래로. 자가진단 경고("탐색 ≥2 인데 측정 0", `pilot_report.py`)는 `sweep_asked ∪ opener` 기준으로.

---

## 6. 삭제 목록 (죽은 코드 남기지 않음)

영향 범위는 조사 결과 기준. "함께" 열은 먼저 끊어야 하는 의존.

| # | 삭제 대상 | 코드 | 테스트(삭제·수정) | 함께 |
|---|---|---|---|---|
| a | 하위역량 단위 앵커 루프 | T: `MAX_TURNS_PER_SUB`·`CHAPTER_TURN_SLACK`·`STALL_WATCHDOG_TURNS`(죽은 코드)·`select_next_target`·`should_advance_target`·`advanced_to_new_target`·`breadth_satisfied`·`chapter_over_budget`·`progress_stalled`·`apply_probe_turn`·`bump_turns_only`·`pick_result_probe`(죽은 코드). I: `MIN_EXPLORED`·`MIN_EVENTS`·`MIN_TURNS_BEFORE_END`·`_chapter_can_close`·넓이 게이트 746~799·#12 STAR 분기 787~810. D: 프로브 스텝 1029~1297 전체, `_anchor_fallback` 2160, `ANCHOR_TRANSITIONS`, 8-m 2906~2919. instruction `STAR_INCOMPLETE`·`STAR_COMPLETE_NEW_EVENT`·`CONTINUE_NORMAL`·`CHAPTER_ONE_MORE_ASK`·`FIRST_TURN_AVOIDANCE`·`AVOIDANCE_DETECTED`·`ABSTRACT_AVOIDANCE`·`ABSENCE_PROBE`·`DUPLICATE_SUSPECTED`·`CROSS_CHAPTER_OPPORTUNITY`·`COMPETENCY_INTRO`·`ONBOARDING_LAUNCH`·`CHAPTER_CONTINUE_CONFIRMED`(죽은 값) | 삭제: test_traversal, test_target_advance_anchor, test_last_target_followup, test_fuzzy_asked, test_no_yield_no_close, test_guard_ordering(cap<MAX 단언). 수정: test_struct_1021, test_ledger_rollback(새 키), test_resume/restore(원장 보존 단언만), test_p0_dialogue(앵커 6인 구별·회전은 유지) | `order_by_priority`·`record_asked`·`record_anchored`·`asked_for_chapter`·`snapshot/restore_ledger` 는 유지(§3-3). `avoidance_detector` 는 LLM 미호출 신호로만 남겨 사례 카드에 "직전 답 짧음/회피" 한 줄로 전달 |
| b | 사다리 탐침 기계 | `data/ladder_questions.py` 전체, `llm_judge.ladder_already_answered`·`judge_rubric_level`, T:`ladder_probed`/`mark_ladder_probed`, D: 1087~1157·1269~1274·2492~2501·3013~3030(8-x)·3319~3337, L3:199~205, `leak_lexicon.py:45` 소스 제거 | 삭제: test_p5_ladder, test_p0_dialogue 의 ladder 5건, test_p6 의 `LADDER_QUESTIONS` 임포트. 수정: test_transcript_lint `test_probe_aggregation` | `PERSONA_LINES.result_a/result_b/quantify/one_more` 와 `output_guard.result_fallback_question`·`RESULT_FALLBACKS`·`needs_quantify_probe`·`T.RESULT_PROBE_POOL` 도 삭제 — 호출처(a 의 `_anchor_fallback`, d 의 `direct_q` 교체, bare_ref 2376, 결과 폴백 2700·2733, Jessica 수치 2533)가 전부 삭제 대상 |
| c | 일반화 탐침 | D:1239~1268·2486~2491·3290~3295, `PERSONA_LINES.generalize`, L3:206~212, T:277~282 | 삭제: test_p4_generalize_probe. 수정: test_p2_unconfirmed_policy(§5 세 갈래), test_gate_generalized_hotfix(`avoidance_detector.is_generalized_answer` 는 입력 신호로 유지하므로 임포트만 유지) | `report_ledger.probe_deficit` 식 교체(§5). `level_gate.split_generalized`(분석 쪽)는 무관·유지 |
| d | "직접 하신 일" 탐침 | `PERSONA_LINES.action`, T:`ACTION_FALLBACK_QUESTION`·`_ACTION_Q_RE`·`is_action_probe_text`·`action_probed`, `output_guard._DIRECT_ACTION_Q_RE`·`is_direct_action_question`, D:1224~1234·2425(`_AFQ`)·2449·2477·2479~2485·2502~2522·3277·3314~3318 | 삭제: test_p22 `test_action_probe_ledger_mirrors_result_probe`, test_p0 `test_direct_action_question_detector_and_soft_lines`·`test_p1_anomaly_escalation_and_direct_cap_wired` | 감정·대조 질문 챕터당 1회 상한(D:2421~2478)도 삭제 — 교체 문장이 `_AFQ` 였고, 새 구조에선 슬롯 카드가 질문 방향을 준다 |
| e | 고정 전환 다리 | `intro_messages.TRANSITION_BRIDGES`·`transition_bridge`(이미 미호출)·`target_bridge`·`target_bridges`·`target_bridge_lines`·`target_bridge_line`, D:`_bridge_idx` 706·8-j 2624~2668·8-n `_fixed_n` 다리 항목·2819~2826·8-w `_fixed_w` 다리 항목·3306 | 삭제: test_p3 `test_target_bridges_three_per_persona_and_rotation`, test_p23 `test_transition_bridges_three_per_persona_and_not_banned`, test_p0 `test_transition_bridges_are_not_state_reports`, test_transcript_lint `test_repeat_metrics_bridge_and_tail` 의 다리 부분 | 새 사례 여는 턴(§9)은 LLM 다리 1문장 + 백엔드 앵커. 8-d 의 `chapter_end_bridge`(챕터 간)는 유지 |
| f | 되받기 폴백 문장 | `receive_check.receive_fallback`·`_GENERIC_RECEIVE`(폴백 문구), D:2883~2886(`receive_fix=2`), `_rcv_snap`·`receive_src`(진단용) | 수정: test_p3 `test_receive_check_statements_and_quotes`(폴백 단언 제거), test_transcript_lint(폴백 열 → 재생성 횟수·미해결 열) | `check_receive`·`quote_phrase`·`splice_receive`·`lead_cap_for` 는 유지(8-n·린트가 씀). 2회 재생성 뒤에도 되받기가 없으면 **그대로 내보내고** guard_log `receive_miss=1` — 린트 "되받기 없는 턴 0" 으로 잡는다 |
| g | 9/22 리드 1문장 상한 | `output_guard.cap_lead_sentences` 667, D:2415~2420·2696·2706~2724(`lead_cap` hard), `docs/prompt_reduction_2026-09-22.md` §리드 상한 항목에 폐지 표기 | 삭제: test_output_guard `test_cap_lead_sentences_*`, test_p0 `test_lead_cap_keeps_dependent_clause_of_compound_question`. 수정: test_p23 `test_persona_lead_caps`(라포만) | `cap_leads_persona`·`persona_lead_cap` 은 라포 스몰톡(D:1806~1822)에서만 유지. 되받기 3문장 초과는 재생성 사유(자르지 않음) |
| h' | ANCHOR_REASK 2·3회 변형 | D:955~970(`reask_anchor_2`·`skip_item`·`skip_bridge`), `PERSONA_LINES.reask_anchor_2/skip_item`, 8-j `skip_bridge` 2635 | 수정: test_p0 `test_ack_after_anchor_reasks_anchor`(1회만), `test_persona_lines_have_all_new_keys` | §2-3 로 재정의. `reask_anchor` 1회는 유지 |
| 기타 | 반례 탐침 `CONTRARY_NEEDED`·`should_do_contrary`·`has_contrary_probe`, 태도 계기 질문(D:1206~1222·2670~2677), 수치 질문 교체(D:2393~2403), 결과 질문 재생성·반복 교체(D:2679~2737), 의미 반복 → 다음 앵커(D:2596~2622 의 "다음 앵커" 부분만), `CHAPTER_NO_YIELD_ULTIMATUM`(§2-3 no_case 가 대체), `event_tracker.plan_event_update`·`probe_type_for`·`is_attitude_statement`, `event_service` STAR 계산, `conversation_compressor` 의 사건 요약은 Event 행 기준이므로 유지 | 삭제: test_event_tracker(plan_event_update 부분), test_result_probe_and_style(결과 탐침 부분), test_p20 `test_closing_request_routes_by_breadth`·`test_quantify_scope`, test_probe_fallback_p12_p13, test_listen_and_bridges 의 결과 폴백 단언 | `should_suggest_pause`·`sitting_stats`·`is_substantive` 는 유지(E:51·138·152) |

Layer3 instruction 가이드(L3:810~1104, 33종)는 유지 11종(라포·INTRO·CONFIRM·ASK·ALIGN·META·PAUSE·ABORT 3종·INVALID·READY_TO_END) + 신규 5종(§8)으로 줄인다. `docs/postprocess_pipeline.md` 는 새 단계표로 다시 쓴다.

---

## 7. 유지 목록 (위치와 바뀌는 점)

| 기능 | 위치 | 바뀌는 점 |
|---|---|---|
| 정의 질문 | `intro_messages.definition_question`, 8-k D:2921 | 없음 |
| ALIGN 되받기+정의+목록+안내 | `align_render.render_align` 99, 8-b D:1871~1980, 8-z D:3077 | 끝을 `align_bridge`("먼저 {phrase}부터요.") → **`align_open`("먼저 하나를 깊게 들어볼게요." 6종)** + 사례 1 여는 앵커로. `SUBCOMPETENCY_TOPIC_PHRASE`·`align_topic_bridge` 삭제 |
| 입력 이상 처리 | `input_anomaly.detect`, D:921~999 | `ack_reask` 1회만(§2-3), `repeat_any` 의 사건 자카드 비교는 `episodes[].slots.quote` 기준으로 |
| 8-i 누설·상태 보고문 가드 | D:2137~2384, `leak_lexicon`, `output_guard.strip_state_leak`, 8-y D:3046 | 위반 항목을 `praise·revisit·state_leak·leak·sub_names·no_question·same_question·bare_pronoun` 으로 줄인다(`off_target`·`transition` 삭제). 교정 순서는 그대로. 질문 없음의 폴백은 "앵커" 가 아니라 **재생성 2회 → 그래도면 사례 카드의 1순위 미충족 슬롯 고정 질문**(§7 슬롯 행 문장 재사용) |
| 8-n 입버릇 | D:2762~2832, `output_guard.find_banned_tail` | 고정 문장 제외 목록에서 다리·사다리 항목 제거, 슬롯·앵커만 남김 |
| 느낌표 | 8-h D:2939~2987, `style_tracker` | 없음 |
| 페르소나 어미 | `persona_voice.voice_question`, `_voiced_q` D:915 | **고정 문장에만**: 여는 앵커·SWEEP 앵커·슬롯 질문·정의 질문. LLM 문장은 변환하지 않는다. `_vv_total` 세션 누적 변주는 유지 |
| 슬롯(페르소나 고정 질문) | D:2556~2595, `PERSONA_LINES.slot_q/slot_q2/slot_lead`, 8-x2 복원 D:3032 | 조건을 **사례당 1회·되받기 뒤**로: 사례 리더 턴 3(없으면 4·5 재시도)에서 [LLM 되받기] + `slot_q`(Jessica·Lucas·Olivia 는 LLM 질문 대체, Daniel·Michael 은 기존 조립). 8-w 뒤에서 조립해 "되받기 뒤" 위치를 보장(지금은 8-w 앞). `episode_slot_used` |
| 시간 인사 | `time_greeting`, 라포 1턴 D:1477 | 없음 |
| 일시정지 | `should_suggest_pause` E:152, D:1619~1630·2989~3011, `pause_suggestion_text` | 없음. 제안 턴의 `pending_instruction` 은 새 instruction 이름으로 |
| 참여 이탈·3-Strike·주입 감지 | I:457~509, D:822~882 | 없음 |
| 앵커 사전 52문·회전 | `competencies.SUBCOMPETENCY_ANCHOR_QUESTIONS`, `anchor_render.dict_anchor`, `anchor_variant` | 없음(여는 질문·SWEEP 에서 재활용). `SUBCOMPETENCY_MUST_ASK` 는 매핑 프롬프트 재료로 유지 |
| 되받기 검사 | `receive_check.check_receive`·`splice_receive` | 재생성 사유로만(폴백 없음) |
| 한 턴 한 질문 | 8-o D:2834 | **열린 결정 ①**: 재생성 사유로 바꾸고 2회 뒤엔 `keep_last_question` 로 자르는 것을 제안(현행 유지) |

---

## 8. 프롬프트 구조

### 8-1. system (매 턴)

```
[Layer1-light]  역할·제4의 벽·사람처럼·대화 규칙 9개 (L1:12~46, 유지)
[BEI 절 재작성] "탐침 종류 6개" 절(L1:48~69) → 아래 6슬롯 설명 + "한 사례를 끝까지" 규칙으로 교체
[페르소나]      COACHES_PERSONA.system_prompt + tone_note (유지)
[챕터 정의]     L2 축약: 역량 정의 1문장 + 하위역량 이름·설명(내부용, 노출 금지). 목표·특수 지시·시작 스크립트·Backup 삭제
[사례 카드]     ─ 아래 8-2
[턴 형식]       되받기 1~3문장(리더 직전 답의 말을 넣어 받는다) + 질문 1개. 되받기 없이 질문만 쓰지 않는다
[금지]          하위역량 이름·분류 설명("이건 변화관리에 해당") · 상태 보고("이제 결과를 여쭙겠습니다") · 칭찬 · 질문 2개 · 회사명
```

### 8-2. 사례 카드 (백엔드가 매 턴 생성, 300토큰 이내)

```
# 지금 듣고 있는 사례 (n번째 / 리더 턴 k/8)
여는 질문: "<앵커 원문>"
채워진 것: 상황·시점 — "지난 3월 교육 개편 때 선임 둘이 …"(리더 말) / 리더 행동 — "제가 먼저 …"
아직 없는 것(이 순서로 하나씩): 상대 반응 → 결과 → 판단 기준
이번 턴: '상대 반응' 하나를 묻는다. 리더가 다른 데로 가면 한 번은 따라가되 질문은 이 사례로 돌아온다.
신호: 직전 답 2문장·구체적 / (짧음·회피면) "더 작은 단위(그날 그 자리에서 처음 한 말)로 묻는다"
```

- `[Turn State]` JSON·Global Memory·문체 블록·강제 블록(L3:65~255)은 삭제하고 사례 카드가 대신한다. `build_style_tail`(꼬리 블록)은 유지.
- 신규 instruction: `EPISODE_OPEN`(사례 2·3 여는 턴), `EPISODE_PROBE`(일반 턴), `EPISODE_RETRY`(no_case 재질문), `SWEEP_ANCHOR`, `SWEEP_FOLLOWUP`. 되받기 필수 집합(`RECEIVE_REQUIRED_INSTRUCTIONS`)은 이 5종.

### 8-3. user

`[Conversation History]` = 현 챕터, 종료된 사례는 Event 요약 1줄(compressor 유지), 최근 5턴 창(유지) + 꼬리 블록 + `[Latest User Message]`.

### 8-4. 턴 검사 순서 (새 후처리 단계표의 뼈대)

1. 마커·표식 제거 → 2. 8-i 감지(§7) → 3. 되받기 검사(`check_receive`)·질문 수(`count_questions`)·되받기 3문장 초과 → **재생성 최대 2회**(사유를 모아 한 번에 지시) → 4. 하드 교정(칭찬·누설·상태 보고문 삭제, 깨진 문장 처리 유지) → 5. 고정 문장 삽입(EPISODE_OPEN·SWEEP 앵커, 슬롯) → 6. 8-n 입버릇 → 7. 8-p Michael '좋습니다' → 8. 8-h 느낌표 → 9. 8-y 최종 누설 → 10. 8-z ALIGN 조립 → 11. 저장·원장.
   폴백 문장은 없다. 3 에서 2회 뒤에도 실패하면 guard_log 에 사유를 남기고 내보낸다(린트가 잡는다).

---

## 9. 사례 여는 질문

- **사례 1**: ALIGN 꼬리. 하위역량 = `order_by_priority(챕터 하위역량, ALIGN 키워드 우선)[0]`(정의 순서 첫 항목 고정, T:40). 앵커 = `dict_anchor(sub, anchor_variant)`, 페르소나 어미.
- **사례 2·3** (`EPISODE_OPEN`): 하위역량 = covered(strong)·no_case·이전 opener 를 뺀 우선순위 첫 항목. 코치 턴 = [LLM: 직전 사례를 닫는 되받기 1문장 + 잇는 다리 1문장] + [백엔드: 앵커]. LLM 의 자체 질문은 지운다. 다리에 금지: 상태 보고("다음 항목으로"), 하위역량 이름. 되받기·다리가 없으면 재생성(2회), 그래도면 앵커만 나간다(문장 폴백 없음).
- 사례 1 이 `no_case` 로 폐기된 경우의 다음 여는 턴도 `EPISODE_OPEN` 이다("그럼 다른 장면으로 여쭤볼게요" 류는 LLM 이 쓴다).

---

## 10. 시뮬 리더 도구 `tools/sim_leader.py`

- **모델** Haiku(`claude-haiku-5-5`), temperature 0, 시드로 단답 일정 고정(결정론: 같은 시드·같은 코치 출력이면 같은 답).
- **고정 설정** `tools/sim_profiles/edu_team_lead.json`:
  - 인물: 교육팀장(5년 차), 팀원 4명(이름·성향 1줄씩).
  - 사례 6개 사전 정의: 각 사례에 **6슬롯 사실**(상황·시점/행동/반응/결과/기준/배운 것)과 **정답 하위역량**(strong 1~2개, weak 0~1개). 조직관리 2·성과 1·사람 2·일 1 로 분포시켜 5챕터 완주 때 챕터별로 꺼낼 게 있게 한다. 사례가 없는 하위역량(예: 디지털 활용)은 "딱히 없었다" 로 답하게 해 no_case 경로를 밟는다.
  - 답변 규칙: 묻는 슬롯의 사실만 2~4문장으로 답한다. **묻지 않은 슬롯은 먼저 말하지 않는다**(코치가 끌어내야 6/6 이 된다 — 사례당 5~8턴 기준의 근거). 매 7번째 답(시드 가변)은 "네" 또는 "음… 그랬죠" 로 짧게. 정의 질문엔 1문장, ALIGN 앵커엔 사례 첫 문장만.
- **구동**: 재생 러너(`.fm_work/replay_full.py`)의 클라이언트 부분을 가져와 `/start` → 교대 → 전환 팝업·일시정지 자동 응답 → 5챕터 완주 또는 `--chapters 1`. 참가자 JWT 부착(11/02 P0 이후 필수).
- **출력**: `replay_result_*.json` 호환(기존 `transcript_lint.py` 그대로) + `ledger_*.json`(episodes·covered·unconfirmed) + `truth_*.json`(사례별 정답 라벨).
- **린트 추가 열**: 사례당 리더 턴 / 6슬롯 도달 턴 / 매핑 정확도(strong 라벨 ∩ 정답 ÷ 정답) / 커버리지 covered÷하위역량 / 되받기 없는 턴 / 고정 문장 연속 반복 / 챕터 리더 턴 / 사례 미확인·미탐색 수.
- **비용** 리더 턴당 ≈ 1.2k in + 0.1k out ≈ $0.0002. 2단계(2세션 × 1챕터 ≈ 40턴) ≈ $0.01, 3단계(6 × 5챕터 ≈ 600턴) ≈ $0.12. 코치 쪽이 대부분이다(아래).

---

## 11. 단계 계획·비용·통과 기준 (지시문 그대로, 비용만 보강)

| 단계 | 내용 | 비용(Haiku 0.10/0.50, Sonnet 2.00/10.0) | 통과 기준 |
|---|---|---|---|
| 1 | 구현 + `FM_LLM_STUB` 스모크(6코치 × 1챕터), pytest 전부, §6 삭제 | $0 | 스텁 완주, 테스트 passed/failed/error 보고 |
| 2 | 시뮬 2세션(Michael·Jessica, 조직관리 1챕터) → 전문 | 코치 본 호출 ≈ 20턴 × 6k in × 0.1 + 재생성 ≈ $0.02/세션, 슬롯·매핑 ≈ $0.005, 리더 ≈ $0.005 → **2세션 ≈ $0.06 (지시 ≈ $0.2 안)** | 사례당 리더 턴 5~8 · 되받기 없는 턴 0 · 고정 문장 반복 없음 · 챕터 리더 턴 ≤ 20 · 커버리지 ≥ 3/4 |
| 3 | 시뮬 6코치 5챕터 + 분석 1회 | 대화 6세션 ≈ $0.6~0.9(10/29 실측 $0.087/세션 기준, 사례 카드로 system 이 줄어 비슷하거나 낮음) · 분석 1세션 Sonnet **10/29 실측 ≈ $2.6**(지시 ≈ $1.5 보다 큼 — 심층 15 + 게이트 42 + 최종 4 호출) | measured ≥ 22/26 · 사례 미확인 ≤ 4 · 블라인드 6/6 · 누설 0 |

2·3단계 전에 비용 한 줄 보고 후 충전 대기. 단계 사이 push 없음.

---

## 12. 결정 사항 (2026-11-04 검토자 승인)

1. **8-o 한 질문**: 질문 2개 이상은 재생성 사유. 2회 뒤에도면 마지막 질문만 남긴다(`keep_last_question`).
2. **반례 탐침 폐지** 승인. Olivia 의 대조 질문은 페르소나 슬롯(`slot_q`)으로만 남는다.
3. **예산 B** 16/18/20/18/16 유지. 3번째 사례 조건의 SWEEP 예비 = **미커버 하위역량 수 × 1턴(앵커만)**. 후속은 예산이 남을 때만. 목표: `not_explored` 세션당 ≤ 1.
4. **SWEEP 후속 ≤1턴** 유지. 단 SWEEP 답이 슬롯 판정에서 행동+결과를 이미 채우면 후속 생략, 일반화(시점 없음)면 장면을 1회 묻는다.
5. **3단계 분석 비용** $2.6 기준으로 잡되 캐시 적용 후 실측은 $1.5 전후 예상. 실측 보고.
6. **ALIGN 안내 문구 교체**: 옛 "이 N 가지를 하나씩 여쭤볼 텐데, 항목마다 실제 있었던 일 하나씩" 은 새 구조와 모순 → "이 N 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 깊게 들어보겠습니다. 먼저 하나를 깊게 들어볼게요."(페르소나 어미 6종).
7. **매핑 strong/weak**: `covered` 는 strong 만. weak 는 SWEEP 대상이되, SWEEP 앵커 앞 LLM 다리에 "아까 [사례 N]에서 살짝 나왔는데, 그쪽을 하나 더" 를 허용한다(사례 카드에 weak 출처를 준다).
8. **페르소나**: 문장 대부분이 LLM 작성이므로 어미 변환 계층은 고정 문장에만 건다. system 의 페르소나 블록이 어미·질문 성향·슬롯을 진다. 2단계 전문에서 Michael·Jessica 가 구분되는지 검토자가 본다. 안 되면 LLM 출력에도 어미 변환을 거는 것을 3단계 전에 정한다.
9. **미탐색(not_explored) 리포트 표시**: 라벨 "시간 내 다루지 못한 항목", 점수 공란. 세션당 2개 이상이면 분석 린트 경고.

진행: 1단계 → 2단계(Michael·Jessica 시뮬 1챕터)까지 돌리고 전문 보고. 3단계는 2단계 전문 검토 뒤.

## 13. 1단계 구현 메모 (2026-11-05)

- 코드 위치: 상태기계 `services/bei_engine.py`, 판정·매핑 `services/slot_judge.py`(+`llm_schemas.slot_judge_schema/episode_map_schema`), 사례 카드 `prompts/phase3a/episode_card.py`,
  라우트 `routes/diagnoses.py` BEI 단계(LLM 호출 전)·8-w 턴 형식 검사·8-s 슬롯·`_write_episode_event`, 리포트 `services/report_ledger.py`(세 갈래)·`routes/reports._build_store_meta`.
- 설계와 다른 점: ① 사례 전문은 "사례를 연 코치 턴부터"(`opened_at` = 열 때의 챕터 메시지 수) — 첫 사례는 ALIGN 메시지가 포함된다(판정 프롬프트가 코치 말은 근거가 아니라고 못 박는다).
  ② 여는 답(재질문 답 포함)이 '없다'면 그 턴의 슬롯 채움을 버린다(없는 사례에 인용이 붙지 않게). ③ 같은 사례에서 2회째 단답·반복(ack/repeat_prev/repeat_any)은 입력 이상 고정 응답 대신 BEI 단계로 넘겨 재질문 1회 → 폐기.
  ④ 페르소나 슬롯은 8-w 뒤(8-s)에서 조립해 '되받기 뒤'를 보장하고, 사례당 1회는 `episodes[].slot_used` 로 센다. ⑤ `probe_type_used` 는 INCIDENT/SPECIFICATION/META 세 값만.
  ⑥ CHAPTER_READY_TO_END 메시지는 종전대로 다음 챕터(START_CHAPTER)로 태깅된다 — 린트·테스트는 챕터 필터 없이 마지막 코치 턴을 본다.
- 스텁(FM_LLM_STUB=1): 슬롯 판정은 실질 답 1개당 슬롯 1개가 순서대로 차고(없다는 답·단답은 비움), 매핑은 여는 하위역량 strong. 6코치 × 조직관리 완주: 사례 2개(각 6턴, 6/6), SWEEP 2건 없음→미확인, 챕터 리더 턴 16, covered 2/4(`tests/test_bei_stub_smoke.py`).
- 시뮬: `tools/sim_leader.py TAG --coaches 5,2 --chapters 1 [--stub]`, 설정 `tools/sim_profiles/edu_team_lead.json`(사례 6개, 조직관리 2·성과 1·사람 2·일 1, no_case 3). 전문 `--dump`, 린트 `tools/transcript_lint.py sim_result_*.json`.


## §14. 2단계 판정(2026-11-05) 반영 메모
- 2단계 s2d 통과. 추가 3건: ① 매핑 정밀도 — `map_episode` 프롬프트에 하위역량 정의 + Lv.2 행동 예 1줄, 하위역량마다 strong/weak/none + confidence(0~1), strong 은 confidence ≥ 0.8 이고 인용이 리더 원문에 있을 때만(느슨 검증 `quote_matches_loosely`). 고정 사례 8개 실 LLM 테스트 `tests/test_bei_map_precision_live.py`(FM_LIVE_MAP_TEST=1) — 2026-11-05 실측 정밀도 0.94(17/18)·재현율 1.00(15/15). 과다 매핑이 SWEEP 을 생략시켜 분석 gate_dropped 로 가는 것을 막는 항목.
  ② ANCHOR_REASK 는 형식 검사를 통과한 마지막 질문 문장만 되묻는다. 아니면 BEI 단계에서 새 질문(`bei_anomaly_reask`).
  ③ 유도형 이지선다·가정형 질문 금지 — EPISODE_PROBE 가이드·턴 형식 규칙 + 8-w `leading_choice` 재생성.
  ④ 종료 턴 인용 기반 2문장(6f7f2ca) 확정.
- 시뮬 프로필(`tools/sim_profiles/edu_team_lead.json`) 5챕터: 사례 13개(E1~E13), 정답 하위역량 24/26, no_case 2(디지털 활용 능력·공감). 정답 보정: E3 에 KPI(분기별 지연 표 점검), E6 에 자원 및 시간관리(운영 일부를 강사에게) 추가.
- 3단계 실행: `python3 tools/sim_leader.py s3 --coaches 1,2,3,4,5,6 --chapters 5 --provider claude` → 린트 → `tools/blind_transcript.py` 6벌 → `--analyze sim_result_s3_5.json`(Sonnet 1회) → `analysis_lint`.

## §15. P4 — 운영 Michael 완주 세션(2026-11-05) 검토 반영

검토자 판정: 대화 구조 OK, **반복·평가 말투·흉터 문장**이 남음. 반영 내용(코드 위치는 docs/postprocess_pipeline.md):

| # | 항목 | 반영 |
|---|---|---|
| P4-1 | 반복 상한 — 전부 세션 단위 | 페르소나 슬롯 챕터당 1회·세션 5회·문구 5종 순환(Michael 응원 5종은 검토자 문안 그대로) / Michael 실행 의지 질문 세션 3회·3종 / 정의 질문 5종 순환 + 앞에 LLM 의 '이 영역에서 무엇을 볼지' 1문장(5챕터 전부, 폴백 `CHAPTER_SCOPE_LINES`) / ALIGN 안내·다리 3종 순환 / 린트 "같은 고정 문장 세션 ≥3회 = 실패" |
| P4-2 | 평가 말투 금지 | '좋습니다/좋은 방향/좋은 흐름/잘하셨/인상적/훌륭' 류 리드·평서문은 상한이 아니라 전면 제거 — `praise` 를 재생성 키로, 문두 리드 정규식, Michael '좋습니다' 리드·꼬리·고정 문장 삭제. 응원은 P4-1 슬롯으로만 |
| P4-3 | 흉터 문장 | 가드 제거 뒤 (a) 서술어 없음 (b) 호칭만 (c) 조사 끝 → 그 문장 삭제(교체 아님, 8-v). 되받기 0 → 8-w 재생성. 테스트에 '…게 인데요'·'리더님.' 꼴 고정 |
| P4-4 | 사례 여는 질문 | [왜 묻는지 1문장] + [있었는지 질문] — LLM 이 하위역량 정의를 리더 말로 풀어 씀(`render_opener`), 전제형('~받으셨을 때 어떻게') 금지, 불합격은 사전 앵커 폴백 |
| P4-5 | SWEEP | 챕터당 3개 상한(나머지 not_explored, 세션 ≤2 는 린트), 앵커 앞 LLM 다리 1문장, 연속 2개째부터 다리 필수(없으면 재생성 1회) |
| P4-6 | 챕터 종료 | 인용은 재료 — LLM 이 사례 전부(2~3개)를 한 문장씩 + 고정 전환. 인용 나열 템플릿 삭제, 인용 시작 접속사 제거 |
| P4-7 | 확신도 | 점수에서 제거(최종 = 행동지표 + STAR), 표시만("AI 판정 확신도 ★★★"). 저장된 리포트는 읽을 때 재계산(`rescore_without_confidence`) — 운영 세션 전후: 조직 2.9→2.9 · 성과 2.5→2.3 · 사람 2.9→2.7 · 일 3.1→2.9 · 자기 2.7→2.6 · 종합 2.8→2.7 |
| P4-8 | Lv.3 판정 | "기준·틀·지표를 제안해 팀이 채택" = Lv.3(설계) — 루브릭 주입문(`LV3_DESIGN_RULE`, 성과관리 목표설정·KPI 예시)과 게이트 규칙 6에 명시, 프롬프트 버전 올려 캐시 무효화. 운영 세션 재분석은 push 뒤 [재분석]으로(≈ $1.5) |
| P4-9 | 자기-대화 차이 | ±0.5 이상 '다소 차이', ±1.0 이상 '차이 큼'(이전엔 +0.5 가 '일치') |

검증: 시뮬 Michael·Jessica 1챕터(Haiku ≈ $0.1) → 린트(슬롯 ≤1/챕터·평가 말투 0·흉터 0·고정문장 ≥3회 0) + 전문 → 검토자 읽기 → push.
프론트: `score_breakdown.confidence_stars/confidence_label` 을 '확신도 +0.2' 막대 대신 표시해야 한다(리포트 프론트 작업, 별도).

## §16. P5 — '고객 화면 보기' 열람 토큰 (2026-11-06)

배경: 관리자 도메인(fm-hr·fm-ops)에서 상대 경로 /report 가 콘솔 홈으로 튕기던 버그를 고치며 관리자 쿠키를 Domain=.connectn.co.kr 로 넓혔다가,
형제 앱(recruit 등) XSS 로 마스터 토큰이 샐 수 있어 같은 날 되돌렸다. 대신 쿠키 없이 여는 방식:
1. `POST /api/v1/admin/sessions/{sid}/view-token` (관리자 인증; 마스터 전부·대리 중이면 그 고객사, HR 은 자사 참여자만 — 타사 403) → 1회용 서명 토큰(typ=report_view, 60초, sid·pid 한정, jti)
2. 프론트가 `https://fm.connectn.co.kr/report?session_id=…#vt=<토큰>` 새 탭 — URL 조각은 서버·로그·리퍼러로 가지 않는다. fm 은 조각을 읽자마자 주소창에서 지운다.
3. `POST /api/v1/reports/{sid}/view-session` (Authorization: Bearer vt) → 세션 전용 열람 토큰(typ=report_viewer, 30분, sessionStorage). jti 는 소진(두 번째 401), 다른 세션은 403.
4. 열람 토큰은 그 세션의 GET 만(리포트·진행 상태·예상 시간). POST(재분석·대화)는 403. 만료되면 리포트 페이지가 첫 화면으로 튕기지 않고 "다시 [고객 화면 보기]" 안내.
코드: `services/report_view_token.py`, `participant_auth.get_caller`(Caller.view_*), `routes/admin.py`·`routes/reports.py`; 프론트 `lib/api.ts`(열람 토큰 인터셉터·교환), `lib/adminApi.issueReportViewToken`, `app/admin/reports/[id]`, `app/report`.
테스트: `tests/test_report_view_token.py`(마스터/HR/대리, 1회성, 만료, 세션 한정, POST 금지). 토큰 값은 서버 로그에 남기지 않는다(발급·교환 로그는 세션 id 만).

## §17. P6 — 사례 단위 게이트·근거 선택 우선순위·반복 인용 표시 (2026-11-06 착수)

원인(운영 Michael 재분석 11/6): 게이트가 칸별 인용 조각만 보고 판정 → 같은 사례가 문제해결·실행력·갈등관리 세 칸을 Lv.3 으로, KPI 는 채택 문장이
목표설정 칸에 가 있어 Lv.3 결락, 회차마다 조각이 달라 2↔3 교차.
1. **게이트 입력 = 선택 인용 + 그 인용이 속한 사례 전체**(`services/episode_context`): Event 1건 = 사례 1건, 그 구간의 리더 발화(ChatMessage.event_id 태깅,
   없으면 S/A/R 슬롯 인용 폴백, 상한 1,800자). 인용 → 사례는 느슨 비교(공백·따옴표 제거 앞 40자, 자기 챕터 우선). 배치 앞에 "[사례 A] … 리더 발화 전체"
   블록을 **한 번씩만**(별도 프롬프트 캐시 블록 — 같은 챕터의 투표·outer run 이 공유), 칸마다 "[사례 참조] 사례 A 의 일부 — 레벨은 사례 전체의 행동으로".
   GATE_SYSTEM 규칙 7, 캐시 키에 사례 해시, `GATE_PROMPT_VERSION=2026-11-06.v3-episode`. 사례 색인이 없는 옛 세션은 인용만으로(이전 동작).
2. **근거 선택 우선순위**: 자기 챕터 인용이 있으면 교차 챕터 인용 제외(`prioritize_own_chapter`, 출처 불명은 유지) + 심층 프롬프트 규칙 3-B(자기 챕터 먼저,
   한 문장이 두 칸 근거 가능 — 특히 지표·측정 방식 채택 문장은 KPI 칸에도). `_DEEP_PROMPT_VERSION_CLAUDE=2026-11-06.v5-evidence-priority`.
   한 사례가 Lv.3 이상으로 올린 칸 수 `coverage.episode_lift`·`episode_lift_warnings`(≥3칸), sub_ledger 행 `episode` 라벨, analysis_lint 경고.
3. **표시**: 같은 인용이 여러 칸(하위역량 근거·S/A/R)에 반복되면 두 번째부터 "(위 사례와 동일) 앞 18자…" — `evidence_display`/`quotes_display`(원본 보존), 프론트는 표시 필드 우선.
검증: Michael s3b 세션 분석 2회(캐시 디렉터리 분리, ≈ $3) — 갈등관리·동기부여·KPI·실행력의 레벨·안정성·근거 사례를 이전 분석과 대조. 투표 3→2 축소는 안정성이
좋아지면 그때 결정(게이트 비용 상쇄).
검토자 결정(2026-11-06 승인): (가) 사례 묶기는 같은 챕터 사례끼리만 — 교차 챕터 사례는 단독 근거 1건으로만, 다른 사례와 합쳐 요건 충족 금지(`episodes_for_cell`, 규칙 8).
(나) 투표 3 유지. 추가: **Lv.4 범위 조건** — 행동의 범위가 팀 밖(타 부서·다른 팀·전사·조직 단위·외부 기관)일 때만 Lv.4, 팀 안 장치는 Lv.3 상한(규칙 9 + 결정론 `scope_fix`:
사유에 팀 밖 표지가 없으면 4→3, p6b 팀워크 사유 2건 테스트 고정). `GATE_PROMPT_VERSION=2026-11-06.v4-scope`.
검증 결과(Michael s3b, 분석 2회 $2.54): 게이트 강등 표 27/54 → 9/55·5/50, Lv.3 9 → 17·15, P6 두 회차 불일치 4/26(팀워크·동기부여·자원시간·회복탄력성), 갈등관리 3 stable 로 고정,
KPI 2(이 세션엔 지표 채택 문장이 없음 — 운영 재분석에서 확인). 다음: 운영 Michael 세션 재분석 1회로 KPI 양쪽 근거·갈등관리 자기 챕터 판정 확인.

## §18. P7 — 사례 없는 리더 대응 + 전수 탐색 보장 (2026-11-06)

원인(11/6 Ella 운영 세션, 미탐색 14/26): 사례가 없는 리더에게도 사례를 열고 8턴까지 파고들어 예산이 소진돼 뒤 하위역량을 묻지 못했다.
- **P7-1** 사례 유무 판정을 사례 열기 전에: 슬롯 판정 호출에 `incident`(시점·인물·구체 행동 중 하나라도 있는가) 추가(콜 증가 없음). 여는 답이 incident=false 면
  `NO_CASE_REFRAME` 1턴(더 작게·다른 각도, 추궁 금지) → 그래도 없으면 no_case 기록·다음 하위역량(사례를 열지 않음, 하위역량당 최대 2턴). 사례 중 2턴 연속 슬롯 진전 0 → `stalled` 조기 종료(들은 슬롯만 매핑). EPISODE_RETRY 는 NO_CASE_REFRAME 으로 이름·의미를 바꿨다.
- **P7-2** 리포트에 '미탐색' 없음: 묻지 못한 칸도 1.0 '사례 미확인'(같은 라벨·점수, `unconfirmed_kind=not_explored` 로 관리자·린트만 구분). 레이더·대역량 평균·종합에 1.0 포함, '탐색 N/26' 표기 삭제(측정 26/26). 미확인 1.0 칸은 교육 추천 재료에서 제외. 전수 탐색 바닥(SWEEP 예비 턴)은 그대로.
- **P7-3** 그만하겠다는 요청(자발적): 바로 멈추지 않고 [수용 1문장] + "남은 항목은 이어서 하시면 채워지고, 지금 마치면 최저 수준으로 기록됩니다. 이어서 할까요, 마칠까요?" + 선택(이어서 하기 → 직전 질문 재발화 / 지금 마치기 → `POST /diagnoses/{sid}/finish` → completed → analyze). 쉬어가기 제안 뒤 '다음에 하기'는 종전대로 paused.
- **P7-4** 정의 질문 5틀 교체(뭐라고 생각 / 무엇이라고 보세요 / 리더님 말로 풀면 / 라고 하면 뭐가 먼저 / 한 문장으로), 범위 1문장 폴백 재검토.
- **P7-5** 밀어붙이는 되받기 금지: '진짜/정말 기억이', '솔직히 말씀하신', '마음에 걸려요', '다시 한 번 잘 생각' 류를 상태 보고문 사전에 — 문장 삭제. 가이드에도 "없다고 하면 받아들이고 전환".
검증: 시뮬 프로필 `tools/sim_profiles/no_case_team_lead.json`(답변 2문장, 사례 5개/5챕터, 모호 답 50%) → Ella·Michael 5챕터. 통과: asked 26/26, not_explored 0, no_case 집계, 챕터 리더 턴 ≤ 예산.


**검증 결과(p7b, Ella 코치1·Michael 코치5, 5챕터, $0.127+$0.138; 1차 p7a $0.318 포함 누계 $0.58)**: asked 26/26 양쪽, 미탐색 0, no_case Ella 22(+SWEEP 없음 2)·Michael 16(+7), 사례 성립 2/3,
챕터 리더 턴 Ella 8/14/18/10/12·Michael 13/17/20/10/6(예산 16/18/20/18/16 이내), INPUT_DUPLICATE 0/1, 턴 p50 5.6~6.1s·p95 9.7~9.8s. 1차(p7a) 교정 3건: SWEEP 상한이 '없음' 1턴을 세어 탐색 4/5 →
`sweep_count` no_case 제외 / '없어요' 반복이 INPUT_DUPLICATE 7~10턴 → input_anomaly 에서 no-case 류 제외 / 사례 없는 답에 인용 요구 재생성 40턴 → 8-w `_quote_required` 면제(린트도 같은 기준).
2차 교정(재시뮬 없이 커밋, 다음 시뮬에서 확인): 여는 문장 덧붙임 예시 '작은 일이어도요' 가 그대로 복사돼 18~24회 반복 → 예시 삭제·같은 덧붙임 반복 금지 / NO_CASE_REFRAME 이
"방금 말씀하신 '피드백'과도 닿아 있는데요" 처럼 하위역량 이름을 리더 말로 돌림(Ella 7회) → 8-x2 `strip_false_attribution`(리더 발화에 없는 인용 귀속 절 삭제, 결정론).
남은 관찰: 종료 요약이 사례 0 챕터에서 bridge_only / SWEEP 사전 앵커에 전제형("~했을 때 어떻게 하셨어요?") 존재(P4-4 규칙과 충돌) / 장시간 휴식 제안이 사례 1턴 직후 끼어듦(Ella 사람관리).
