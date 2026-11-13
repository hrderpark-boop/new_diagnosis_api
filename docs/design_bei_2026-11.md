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
**승인 조건 반영(2026-11-06, p7c Ella 조직관리+성과관리 $0.061)**: (1) '작은 일이어도요' 0회(교정 전 18~24회), 허위 귀속 0회 — 통과. (2) 사례 0 챕터 종료 = 고정 1문장(페르소나별 `close_no_case`) + 다리.
판정 기준은 종료 재료(`bei_close_episodes`: status done/turns/budget 사례)가 비었을 때 — stalled·SWEEP 만 있는 챕터도 포함된다('많지 않으셨네요'). (3) SWEEP 사전 앵커 전제형 10문장 → '~하신 적 있으셨어요?'.
p7c 에서 추가 교정 2건: '말씀이 마음에 걸리는 건' 어간을 추궁 사전에 / 모호 답('글쎄요, 그건 잘 모르겠어요')의 같은 문장 반복은 중복 입력('같은 사례로 보여요')이 아님.

## §19. P8 후보 (2026-11-10 검토자 지정, 미착수)

p7c 관찰 3건을 P8 로 묶는다. 지시가 오기 전에는 구현하지 않는다.
- **휴식 제안 시점**: 사례 진행 중(EPISODE 턴 1~4)에는 미루고, 사례 종료 턴 뒤에만 낸다(p7b·p7c 에서 사례 1턴 직후 끼어듦).
- **내용 없는 답에 감사 되받기 금지**: "네" 단답 뒤 "떠올려 주셔서 고마워요" — ANCHOR_REASK 경로로 보낸다.
- **사례 없는 리더 예산(견적만)**: 재질문을 하위역량당 1턴으로 줄이는 대신 챕터 끝에 "아까 못 들은 것 중 하나라도" 통합 재질문 1턴. 턴 절약안 견적만 낸다(p7c 성과관리 리더 턴 18 = 예산 18).

## §20. P9 — 운영 Jessica 완주 세션(11/10) 검토 반영 (2026-11-10)

- **P9-1 전수 질문 보장**: SWEEP 챕터당 3개 상한 삭제(`SWEEP_MAX_PER_CHAPTER=None`). 종료 조건은 "모든 하위역량 asked"(`bei_engine.unasked` 가 빈 목록) 하나 —
  미질문이 남아 있으면 예산이 0 이어도 SWEEP 앵커 1턴은 낸다. 예약: 사례를 열 때·사례 도중 모두 `남은 턴 > 미질문 수`를 지킨다. 침범하면 6슬롯 전이라도
  사례를 닫는다(`episode_done_reason → 'reserve'`). 사람관리 예산 20 → 24, 사례 2개까지(`CHAPTER_EPISODE_MAX`). SWEEP 대상은 미질문 먼저, 그 다음 물었지만
  strong 근거가 없는 항목(예산이 남았을 때만). `coverage_summary.not_explored` 는 '한 번도 묻지 않은 것'만. 테스트: 5챕터 × 200회 무작위 흐름에서 unasked 0·예산 초과 0.
- **P9-2 스몰톡 시간대**: 가이드에 지금 시간대(`time_greeting.current_daypart`)와 아직 오지 않은 시간대 금지를 준다. 가드: 되물음·받는 문장이 미래 시간대
  낱말(오전의 '점심·오후·저녁')을 말하거나 되물음이 물음표로 끝나지 않으면 그 문장을 지우고 고정 스몰톡 질문을 붙인다. 업무 질문 사전에 '목표·성과' 추가.
- **P9-3 내부 문구**: '도입 질문', '이번 역량·영역에서는 사례', '사례를 N가지 듣겠다', '이번 교육에서는' 을 상태 보고문 사전에. 출처 지시문에서 '영역 도입 —',
  '도입 + 범위 1문장', '사례 2~3개를 깊게 듣는다' 를 뺐다. 범위 문장 예시는 다른 영역 문장(베껴서 성과관리에 일관리 문장이 나감) 대신 진단과 무관한 분야의 문장.
- **P9-4 사례 닫는 턴**: 여는 턴(EPISODE_OPEN·SWEEP_ANCHOR)의 LLM 본문 = 받기 1문장(연속 SWEEP 은 다리 1문장 더). 질문·'여쭙고 싶습니다'·'궁금'·조언·가정·
  평서형 요청('…짚어 주시면 됩니다')은 지운다(`clean_close_side`, 조립 때와 8-w 재생성 뒤 두 번). 남는 받기가 없으면 페르소나 마무리 어구 1문장.
- **P9-5 대상 없는 질문**: 질문 하나만 남긴 턴(앞 질문 삭제) 또는 받는 문장이 없는 턴에서, 질문에 구체 명사가 없으면(`question_lacks_referent`) 재생성 1회 →
  그래도 없으면 리더 답의 핵심 명사구를 붙인다(`attach_referent`: ''분담표'와 관련해 달라진 부분이 …').
- **P9-6 페르소나 말투**: `services/persona_register.py` — Jessica·Daniel 합쇼체(Daniel 은 '~지요·~군요' 허용), Ella·Olivia·Michael 은 질문을 '~습니까'로 끝내지 않음,
  Lucas 는 설계상 혼용이라 검사 제외. 해라체 평서('…다르다.')·전언 꼴('…더랍니다')은 누구에게나 섞임. 어미표·받침 규칙으로 교정(재생성 없음), 표에 없는 꼴은
  guard_log `register_left`. 적용: 여는 문장(교정 뒤에도 섞이면 사전 앵커), 범위 문장(폴백 포함), 최종 단계에서 모든 코치 문장, 첫 인사. 원인이던 페르소나
  말투 프로필도 고쳤다 — 6명 공통 문구가 '~하셨습니까/어땠어요'를 함께 지시했고 Jessica 프로필은 종결 '~입니다/~죠'·예시 '속도였군요'였다.
- **P9-7 입버릇**: `services/phrase_caps.py` — '살펴보려고 (합니다/해요)' 세션 2회, '말씀해 주시겠습니까' 챕터 2회, 넘으면 대체 표현(순번 회전). 여는 문장 틀 3종
  (듣고 싶습니다 / 이번에는 ~ 쪽 이야기입니다 / ~은 팀마다 다릅니다)을 세션의 사례 순번으로 돌리고 '살펴보려고'는 지시문에서 금지.
- **P9-8 휴식 제안**: 시간 기준만 — 한 자리(세션 시작 또는 재개: 30분 공백·'다음에 하기' 뒤) 40분 이후 첫 제안, 이후 30분 간격, 사례가 끝난 턴(다음 사례를 여는 턴)에서만.
  턴 수 기준·횟수 상한 폐지. 14분째 제안의 원인: 옛 조건이 '45분 **또는 한 자리 코치 턴 30**'이라 답이 빠르면 시간과 무관하게 발동했다(코드상 14분에 제안이 나갈
  경로는 이것뿐 — 운영 로그로는 미확인). 제안 턴이 삼킨 사례 단계 지시는 재개 때 EPISODE_PROBE 로 정규화해 같은 답을 재판정한다.
- **P9-9 종료**: 세션 마지막 답은 받기 1문장(`close_render.render_last_receive`, 실패 시 마무리 어구) 뒤 종료 문구. 챕터 요약 재료 = 사례(조기 종료 포함) + 보완 답,
  합쳐 2~3문장(재료 중 2개 이상 되짚으면 통과). 토큰 상한에서 잘린 꼬리 문장은 버린다(`drop_unfinished_tail`).

검증(시뮬 Jessica 조직·성과·사람관리, edu_team_lead 프로필): p9a $0.108 → 결함 수정 → p9b $0.110. p9b 린트: 미탐색 0 · 말투 섞임 0/0 · 닫는 턴 질문 0 · 주어 없는 질문 0,
챕터 리더 턴 14/11/17(예산 16/18/24), 사람관리 9개 전부 asked(사례 2 + 보완 4). p9b 뒤 결정론 수정(해라체·전언 꼴, 잘린 요약 꼬리, 영역 첫 턴 허위 귀속, 스몰톡 목표 질문)은
재시뮬 없이 p9b 문장 재적용과 단위 테스트로 확인(새 규칙 기준 말투 위반 4 → 0).
남은 관찰: ALIGN 받기 인용이 어색한 낱말을 집음(''가게'를 중심에 두고 계십니다', p9a) · SWEEP 다리 누락 3~5(상한 삭제로 연속 SWEEP 이 길어짐) · 탐침 턴 예고 문장('먼저 여쭙겠습니다').

**P9 조건부 승인 반영(2026-11-10)**: (1) 말투 교정 범위 축소 — 어미 강제는 질문 문장과 고정 문장(여는 문장·범위 문장·첫 인사·안내 본문)에만. 받는 문장은 Jessica·Daniel 도
'~군요/~네요/~셨군요' 그대로(`apply_register(scope="questions")`, `_RECV_OK_RE`). p9b 에서 교정된 48문장 가운데 원시 응답과 대조된 34문장 중 30문장이 받는 문장이었다(군요 22·네요 5).
(2) 점검표 문장('아직 여쭙지 않은 부분은 …')을 상태 보고문 사전에, 사례 카드 미충족 슬롯 안내에 "리더에게 말하지 않는다" 명시(금지 예문은 쓰지 않음).
(3) 누구의 반응·태도·표정·변화인지 없는 질문은 길이와 무관하게 대상 없음 — 직전 답의 인물(`key_person`: '두 분', '박선임 님')을 붙인다.
(4) ALIGN 받기 폴백은 리더 정의의 구절을 그대로 받아 "'…'라고 보시는군요."(`definition_quote`) — 동의만 온 답('네')은 생략.
확인 시뮬 p9c(Jessica 3챕터 $0.115): 미탐색 0·말투 0/0·닫는 턴 질문 0·주어 없는 질문 0, 챕터 리더 턴 13/10/22. p9c 에서 본 것과 수정: 종료 요약이 지시문을 되읊음
("3번째 재료는 … 보완 답의 중복 문장이라") → 재료 꼬리표 삭제·중복 재료 제거·`drop_summary_noise`(되읊기·해석 문장 삭제)·한 문장짜리 요약은 재작성 /
여는 턴·영역 첫 턴의 "방금 말씀하신 '기준'과 이어서 여쭙니다" → 허위 귀속 삭제 확장 / '오늘 늦은 시간 시간은' 인사 낱말 중복. 1챕터 확인 p9d($0.032)에서 종료 요약 정상.

## §21. P10 — 대화 소수정 + 관리자 상세 확신도 가점 제거 (2026-11-10~11)

- **폐기 — 과거 세션 읽기 시 보정**: '한 번도 묻지 않은 하위역량의 1.0 을 평균에서 빼는' 읽기 보정(838a68b, 로컬 전용)은 검토자 결정(2026-11-11)으로 테스트까지 전부 버렸다.
  정책은 하나로 유지한다 — 리포트에 미탐색 없음, 26칸 전부 점수. 묻지 않은 칸 문제는 대화 쪽 전수 질문 보장(P9-1)으로만 막는다.
- **관리자 리포트 상세 = 고객 화면과 같은 값**: 관리자 상세 GET 도 저장 리포트를 확신도 가점 없이 다시 계산해 보여 준다(`report_ledger.confidence_free_view`,
  P4-7 의 `rescore_without_confidence` 재사용). 표시 전용 — DB·목록·조직 집계는 저장값 그대로, 관리자 교정본은 건드리지 않는다.
- **상태 보고문 변형**: '충분히 짚어봤습니다', '말씀을 짚어봤습니다' 를 사전에.
- **사례 번호 금지**: 코치 발화의 '사례 1에서'·'두 번째 사례에서는' 을 그 사례에서 리더가 쓴 낱말로 바꾼다(`rewrite_case_numbers` — '아까 말씀하신 개편 건에서', 낱말이 없으면
  '앞서 말씀하신 이야기에서'). 출처였던 SWEEP 다리 힌트('아까 N번째 사례에서 …')는 리더 인용으로 바꿨고, 시스템 프롬프트에 번호 대신 리더 말로 지칭하라고 명시.
- **요청형 받는 문장**: '…조금 더 듣고 싶습니다.' 처럼 받는 자리에서 묻는 문장은 뒤에 질문(슬롯 질문 포함)이 있으면 지운다(`drop_request_statements`, 슬롯 조립의 받는 문장 필터 포함).
  질문이 없는 턴에서는 그 요청이 질문이므로 그대로 둔다.

## §22. P10 — 운영 Olivia 완주(2026-11-11) 검토 반영

지시 7항목 + 확인 시뮬 p10a(Olivia 조직·성과관리, Haiku, $0.065)에서 본 것까지. 고정 문장을 줄이고(슬롯·받기), 남는 고정 문장은 코치 어미로 맞춘다.

- **P10-1 스몰톡 지연**: 원인은 재생성이 아니라 **누설 사전의 첫 적재**였다 — 사전은 프로세스당 한 번 소스에서 뽑는데(로컬 1.9초, 동기 코드라 이벤트 루프를 막는다)
  기동 뒤 첫 LLM 턴이 그 값을 치렀고, 세션의 첫 LLM 턴이 스몰톡 되물음이다. 시뮬 6벌 전부 스몰톡 턴만 후처리 1.3~2.0초(재생성 0), 스텁(LLM 0콜)에서도 1.9초.
  → 기동 때 별도 스레드에서 예열(`main.on_startup`). 운영 guard_log 는 접근 불가라 미확인(배포 직후 첫 세션이었는지로 대조 가능).
  대책(지시대로): 스몰톡 되물음은 LLM 1회만(`_tm["no_regen"]` — 재생성 래퍼가 건너뛴다), 검사 탈락은 재생성 없이 예비 되물음(`SMALLTALK_RESERVE` 코치별 3종 × 아침·낮·저녁),
  답이 10자 이하·내용 없음이면 LLM 없이 고정 받기 + 예비 되물음(`is_contentless_smalltalk`).
- **P10-2 질문 길이**: 정의 질문 5종을 완결 문장으로(`DEFINITION_VARIANTS`). 페르소나 슬롯은 고정 문장을 전부 지우고 `slot_render` 가 사례 내용을 넣어 쓴다(§ 후처리 8-s).
  탐침 질문 최소 길이: 대상·장면 없이 15자 이하면 직전 답의 사람·명사구를 붙인다(`is_short_bare_question`·`attach_referent`).
  Olivia 탐침 선호의 '대조 탐침' 지시는 삭제 — 본 호출이 쓰면 '반대로 했다면?' 꼴이 나오고 턴 형식 검사(가정형)와 부딪혔다.
- **P10-3 입버릇**: `phrase_caps` 에 '궁금' 챕터 1회·'이번에는 ~쪽 이야기' 세션 2회·채움 문장 금지. 여는 문장 틀에서 채움 문장 틀을 빼고 '주제 절 + 질문' 한 문장 틀을 넣었다.
  틀 순번 `opener_frame_for`(이번에는 틀은 세션 2회). 틀 설명·예시는 어미를 싣지 않고 진단과 무관한 분야(장보기)로.
- **P10-4 말투**: `persona_register` 에 scope="strict" — 여는 문장·범위 문장·다리는 코치 어미 강제(해요체 코치의 '~습니다/~ㅂ니다' 평서문 포함, 합쇼체 코치는 '~군요' 면제 없음).
  합쇼체 → 해요체 평서문 변환(`_polite_stmt`: 표 → 불규칙 예외 → 규칙). **확인 결과: p9 에서 범위를 줄일 때 여는 문장은 빠지지 않았다**(scope="all" 로 계속 검사).
  빠져 있던 것은 '해요체 코치의 평서문 어미 검사'였고(처음부터 없었다), 여는 문장 틀을 합쇼체로 써 둔 것이 Olivia 의 '~입니다/~다릅니다' 를 냈다.
  Olivia 사전 앵커의 '~을지요?' 변형도 폐기.
- **P10-5 받기**: 코치별 고정 받기 문구(`PERSONA_TAILS` 30문장)와 프롬프트의 "되받기 마무리 어구는 이 중에서 고른다" 지시를 삭제 — '흥미로운 지점이에요' 는 이 지시가 낸 것이었다.
  폴백은 리더가 한 말의 마지막 절 인용(`quote_receive`), 받을 낱말이 없으면 받기 없이. 세션 마지막 답 받기는 LLM 1문장·인용 필수(`last_receive_ok`).
- **P10-6 닫는 턴 누수**: '조금 더 듣고 싶어요' 가 남은 원인 둘 — 요청형 삭제(8-y)가 탐침 턴에만 걸려 있었고(SWEEP 여는 턴은 대상 밖), 닫는 쪽 금지 꼴에 '듣고 싶' 이 없었다.
  의문사 나열("언제, 누구와 …, 무엇이")·간접 질문 절 두 개는 질문 수로 센다(`wh_clause_count`). 평서문에 물음표만 붙인 꼴('궁금해요?')은 요청형으로 본다.
- **P10-7 첫 영역 진입 다리**: `first_chapter_bridge`(코치별 고정) — 종전에는 LLM 이 쓰는 문장이라 빠질 수 있었다.
- **p10a 뒤 결정론 수정**(재시뮬 없음, 단위 테스트): 세션 첫 사례의 틀 순번(이번 것 제외) / 받을 낱말 없는 답 뒤의 받는 문장 삭제("그럼 이 사례를 조금 더 펼쳐 볼게요.") /
  종료 요약 총평 문장("…점에서, 저희는 리더가 …힘을 봐요") / 평서문 꼴 질문("짚고 싶은 건 …는지예요.") / 전환 영역 진입 문장 중복 / 정의 턴 평가 리드는 재생성 없이 뗌 /
  한 문장 틀에는 리더 직전 말을 주지 않음.
- **지연 단축 a·b·단계 표시(11/6 보고분)**: 미착수. p10a 실측 — 턴 p50 5.2초·p95 10.1초, 재생성 걸린 턴 19/32(두 질문 미해결 5턴은 2회 돌고도 마지막 질문만 남김).
- **린트 P10 열**: 입버릇 초과(궁금/쪽 이야기/채움) · 질문 2개+ 턴 · 고정 받기(반복/미인용/내용 없음) · 슬롯 일반문 · 짧은 질문 · 요약 총평.

## §23. 지연 단축 b — 두 질문 0회 재생성 (2026-11-11)

- **b**: 질문을 LLM 이 쓰는 턴에서 질문이 둘이면 재생성하지 않고 바로 자른다(8-w `_trim_two`: 질문 뒤 도움말 문장 제거 → 복합 질문은 뒤 절 → 마지막 질문).
  남긴 질문에 대상이 없으면 8-w3(P9-5)이 그대로 보정한다. 다른 사유로 재생성한 본문이 두 질문이어도 다시 돌리지 않는다.
- **시뮬 lb1**(Olivia 조직관리 1챕터, $0.035): 두 질문 재생성 호출 16~17회(2챕터 기준 p10a·p10b) → 0회. 그러나 턴 소요는 p50 4.5초·p95 10.9초로 목표(4·8) 밖 —
  되받기 사유 재생성이 7회로 늘었다. 원인 둘: (1) 받는 문장이 질문 꼴("…뜻이었을까요?")이면 자르면서 받기가 사라진다 (2) 인용 판정이 명사만 봐서
  따옴표로 옮긴 구절("떠날 수 있다")이 든 받기도 미인용으로 떨어졌다.
- **lb1 뒤 수정(재시뮬 없음)**: 도움말 문장("예를 들어 … 떠올려 주시면 돼요")이 '마지막 질문'으로 남고 진짜 질문이 지워지던 것(`keep_main_question`) /
  인용 판정 완화(따옴표 구절·리더 어절 2개 이상, `check_receive`) / 범위 문장 자리의 예고 문장("먼저 여쭤볼게요.")은 영역별 범위 문장으로.
- 받기 폴백은 문장 전체 인용 대신 핵심 구절(`key_clause` — 안은 내용 절 또는 마지막 절을 평서 꼴로): "'지시로 시작하면 반대부터 나온다'는 말씀이셨군요."
- 남은 것: 단계 표시 → a(슬롯 판정 합치기, 사례 턴마다 1.8초). 턴이 긴 곳은 사례 종료 턴(매핑 + 여는 문장 렌더, 10.9초)과 챕터 종료 턴(요약 재생성, 11.1초).

## §24. 재생성 예산·호출 순서·단계 표시 (2026-11-11)

b 단독으로는 목표(p50 ≤ 4초·p95 ≤ 8초)에 못 미쳐 아래를 묶어 측정했다.

- **재생성 예산**: 한 턴에서 모든 검사를 합쳐 재생성은 최대 1회(`_timed_regen` 이 `_tm["budget_used"]` 를 본다). 집중 호출(여는 문장·슬롯·종료 요약·마지막 받기)의
  다시 쓰기도 같은 예산(`rounds=1|2`). 예산을 쓴 뒤의 위반은 결정론 수선만 — 두 질문 자르기, 긴 받기 3문장으로, 질문 없으면 `followup_from_user`,
  받기 없음·미인용은 구절 인용 받기(`quote_receive`), 대상 없는 질문은 대상 붙이기. 수선하지 못한 사유는 guard_log `format_miss` 로 남기고 그대로 내보낸다.
- **질문 꼴 받기 살리기**: "…조건부였다는 뜻이었을까요? 그때 …?" 처럼 받는 말이 질문 꼴이면 자르지 않고 평서 꼴("…뜻이었군요.")로 바꾼다
  (`question_to_statement`·`revive_question_receive` — 첫 문장이 리더 어절 2개 이상을 담았을 때만).
- **호출 순서**
  - 사례를 닫고 새로 여는 턴: 종전 `슬롯 판정 → 매핑 → 여는 문장 렌더(불합격 시 1회 더) → 코치 본 호출 → 재생성 0~2`.
    지금 `슬롯 판정 → 매핑 → [여는 문장 렌더 ∥ 코치 본 호출] → 재생성 ≤1`. 본 호출은 닫는 쪽 받기 1문장만 쓰므로 카드에는 사전 앵커(같은 하위역량)를 준다. ALIGN 턴도 같다.
  - 챕터 종료 턴: 종전 `슬롯 판정 → 매핑 → 코치 본 호출 → 요약 재생성 2회 → 요약 집중 호출`. 본 호출 출력은 쓰이지 않았다(시뮬 전부 집중 호출로 끝남).
    지금 `슬롯 판정 → 매핑 → 요약 집중 호출(재료를 다 못 짚으면 1회 더)`.
  - 순차로 남은 것: 판정 → 매핑(판정이 사례 종료라고 해야 돈다) → 다음 하위역량 선택(매핑 결과가 필요).
- **단계 표시**: `services/turn_progress.py`(세션별 in-memory) + `GET /diagnoses/{sid}/turn_stage`. reading(답변을 읽고 있어요) → thinking(질문을 고르고 있어요) →
  polishing(문장을 다듬고 있어요). 프론트는 답을 보낸 뒤 1.2초가 지나도 응답이 없으면 0.9초마다 읽어 점 세 개 아래 한 줄로 보여 준다(`lib/turnStage.ts`).
  11/6 에는 SSE 로 적었지만 분석 진행 표시와 같은 폴링 방식으로 했다 — 턴 핸들러(3,400줄)를 스트림으로 바꾸지 않아도 되고 실패해도 점만 보인다.
- **측정 lc1**(Olivia 조직·성과관리, Haiku, $0.041, LLM 턴 31개):

  | | p10a | p10b | lb1(b 만, 1챕터) | lc1 |
  |---|---|---|---|---|
  | p50 / p95 / 최대 | 5.15 / 10.1 / 10.9 | 4.75 / 9.0 / 10.7 | 4.45 / 10.9 / 11.1 | **3.7 / 6.5 / 8.8** |
  | 재생성 걸린 턴(2회 이상) | 19(11) / 32 | 18(9) / 30 | 10(3) / 20 | 6(0) / 31 |
  | LLM 호출 수(세션) | — | 92 | — | 71 |
  | 여는 턴 / 종료 턴 중앙값 | 9.8 / 9.9 | 8.3 / 10.1 | 10.9 / 11.1 | 6.4 / 6.0 |

  린트: 질문 지워짐 0 · 평가 말투 0 · 받기 없는 턴 1("네, 맞아요" 뒤 — 받을 내용이 없다) · 재생성 2회 이상 0. '궁금' 챕터 2회째 1건("…궁금해요, …검토하셨을까요?" —
  쉼표로 이은 두 질문) → 시뮬 뒤 판정 추가(`_COMPOUND_Q_RE`).
- **통계 주의**: 종전 시뮬 결과 파일의 행·guard 짝짓기가 챕터 종료 턴에서 어긋나 있었다(메시지가 다음 챕터로 태깅, t 가 챕터마다 겹침) — `sim_leader` 가 순서대로 잇도록 고쳤고,
  위 표는 전부 DB 의 guard_log 에서 직접 뽑았다(`.fm_work/p10/turn_stats.py`).


## §25. P11 — 11/12 운영 Daniel 세션(반말·초단답 리더) 검토 반영 (2026-11-12)

원인을 코드에서 먼저 확인하고 고쳤다. 추정과 달랐던 것은 A1·A5·G·E 넷이다.

| 항목 | 원인(코드) | 처리 | 위치 |
|---|---|---|---|
| A1 스몰톡 '밥' | 고정 받기는 라포 1턴에만 있었다. 예비 되물음의 답은 라포 2턴(담당 업무 질문 턴)에 오고 거기는 LLM 받기였다 | 라포 2턴도 10자 이하·내용 없는 답이면 LLM 없이 고정 받기 + 역할 질문. 받는 문장 금지 꼴(리더가 질문한 것처럼·말투 언급·해석형) 검사 | `routes/diagnoses.py`(7단계·8-0·8-w00), `services/turn_checks.receive_ban_reason` |
| A2 동의·거절 | 동의 판정식이 5곳에 따로 있었고 자모·반말을 몰랐다. 'ㅇㅋ'는 의미 없는 입력으로도 읽혔다 | 사전 한 곳(`services/short_input`)을 5곳이 함께 읽는다. 안내 뒤 거절은 재촉 없는 고정 문장(`confirm_decline`) | `input_anomaly`·`instruction_decider`·`layer3_state`·`avoidance_detector`·`bei_engine` |
| A3 되묻기 | '뭔소리야'는 답으로 읽혀 슬롯 판정으로 갔다 | 이상 종류 `clarify` — 사례 턴은 원장 그대로(리더 턴·슬롯 판정 없음) 코치가 질문만 다시 쓰고 고정 사과 한 마디를 붙인다. 사례 밖은 사과 + 같은 질문 | `input_anomaly.detect`, `diagnoses.py`(입력 이상·사례 단계 `bei_reask_only`·8-w0) |
| A4 반말 | — | 프롬프트 규칙(말씨 유지·언급 금지) + 받는 문장 금지 꼴. 반말 답도 구절 인용 받기가 되게 어미 처리 | `prompts/phase3a/episode_card.TURN_FORMAT_RULES`, `receive_check._PLAIN_END` |
| A5 고정 문장 말투 | 말투 교정(8-zz)은 있었으나 시스템 고정 턴에서 `split_sentences` 지역 import 때문에 UnboundLocalError 로 조용히 건너뛰었다 | import 를 모듈 수준으로 올리고, 안내 본문·시스템 문장을 말투별 두 벌로 따로 쓴다 | `diagnoses.py` 머리, `intro_messages._INTRO_BODY`, `services/system_lines.py` |
| B 슬롯 문장 | 관찰 예시 하나('…자리, 가볍지 않으셨겠습니다')의 꼴을 그대로 베꼈다 | 예시 5종 순환, 쓴 문장을 프롬프트에 넘김, 같은 끝맺음·문형 불합격, 1인칭 옮김은 수선 없이 버림(6명 공통) | `services/slot_render` |
| C 질문 완결성 | 두 질문을 자를 때 뒤 질문의 끝 절만 남았다 | 수선(머리말 떼기·열린 질문 남기기) → 재생성 1회(예산) → 슬롯 기본 질문 | `turn_checks.question_issues`·`prefer_open_question`, `diagnoses.py` 8-w·8-w4 |
| D 예고·귀속·감사 | 허위 귀속 정규식에 합쇼체 꼴('이어지는 부분입니다만')이 없었다 | 예고 문장 삭제(유일한 질문이면 묻는 꼴로), 인용·'말씀하신 ○○'은 세션 리더 발화와 문자열 대조, 감사는 닫는 턴만 | `turn_checks`, `diagnoses.py` 8-y |
| F 여는 문장 | 틀 3종 + 순번표가 한 문장 틀을 세 번에 한 번 골랐다 | 틀 5종, 원장 `opener_frames` 로 직전 틀 제외·세션 2회 상한 | `anchor_render.pick_opener_frame` |
| H 받는 문장 | — | 탐침 턴 받기 1문장(결정론 자르기), 내용 없는 답 뒤는 받기 없이 좁혀 묻기, 해석·짐작형 금지. 겹침 비율은 기록만(`recv_overlap`) | `diagnoses.py` 8-w, `turn_checks.receive_overlap` |
| I 같은 답 | 문구 1종 | 1회째 안내 + 같은 질문, 2회째부터 다른 장면을 청하는 3종 순환 | `intro_messages.duplicate_answer_line` |

보고만(수정 없음): E 사례 2턴 종료 — 최소 4턴 규칙은 사례(kind=episode)의 6슬롯 종료에만 걸린다. 보완 질문(kind=sweep)은 설계상 앵커 1턴 + 후속 1턴이고,
`reserve`·`stalled`·`no_case` 종료도 4턴 전에 닫는다. G 휴식 제안 — 제안은 이미 사례가 닫힌 턴에서만 나가고 직전 답은 보관·재판정된다(P9-8). 재개 지시문만 '그 답을 한 문장으로 받는다'로 고쳤다.

검증 시뮬 p11a(Daniel × `tools/sim_profiles/banmal_short_lead.json`, 2챕터, $0.0445): p50 4.0s · p95 6.6s · 재생성 턴 11/31(2회 이상 0).
전문에서 읽어 찾은 후속 7건(어미 변환 '시나요→시습니까', 주어 없는 질문 조각, 예고 꼴 질문, 다시 묻기의 딴 질문, 짐작·감상 받기, 반말 답 인용 실패, 기본 질문 머리)은
결정론으로 고치고 단위 테스트만 했다(재시뮬 없음).

## §26. P11b — 시뮬 p11a 검토 반영과 재시뮬 p11b (2026-11-12)

재시뮬 1회(Daniel × 반말·초단답, 2챕터, $0.0597, 44턴). 전문 `.fm_work/transcript_p11b_daniel.md`, 린트 `.fm_work/lint_p11b.md`.

**원인이 추정과 달랐던 것**
- '교육팀을 이끄고 계시는군요' 는 어미 변환이 아니라 LLM 출력이었다 — 라포 프롬프트 예시 두 개('이끄시는군요'·'맡고 계시는군요')를 섞었다. 예시를 바꾸고 긴 ㄹ 어간은 표로 수선한다(`conjugation.repair_l_stem`).
- 안내 중복은 LLM 문장과 고정 문장이 아니라 고정 문장 둘(기대 답이 없을 때의 코치별 다리 + 안내 본문 첫 문장)이었다.
- '방금 말씀하신 ○○과도 이어지는 부분입니다만' 은 문체 제약 프롬프트(style_tracker '연결 한 절', 2026-09-17)의 예시가 그대로 나온 것이다. 규칙과 예시를 지웠다.

**넣은 것**(위치는 docs/postprocess_pipeline.md 'P11b 추가 단계')
1. 어미 변환 — `services/conjugation.py`: 불규칙 용언 표(ㄹ 탈락·르·ㅂ·ㅡ·하다), 해요체↔합쇼체 변환, 결과 검사(`bad_form`), 틀린 꼴이면 원문 유지(`safe`). `tests/test_p11b.py` 가 용언 17개 × 어미 전부를 표로 시험한다.
2. 안내 예고 한 번. 3. 연결 문구 틀·여는 턴 진행 해설 삭제, 여는 문형 틀 3 은 질문만. 4. 관찰·응원 슬롯 턴 = 슬롯 + 질문.
5. '리더님께서' 받기 세션 2회·주어 어긋나면 뗌, 되풀이 받기 상한(60% + 10어절) → 구절 인용. 6. 한 문장 두 질문 → 슬롯 질문 하나, 꼬리·다시 묻기 검사, 기대는 머리.
7. 보완 사례 승격(`bei_engine.sweep_promote_decision`·`promoted_done_reason`). 8. 휴식 제안은 자연스러운 닫힘에서만(`is_natural_close`). 영역 경계는 영역 종료 턴의 '다음 챕터로 이동' 대기 화면이 맡는다.

**재시뮬 수치** LLM 턴 40 · p50 4.75s · p95 8.3s · 최대 12.8s · 재생성 걸린 턴 17(사유: 받기 없음 7, 질문 완결성 5, ALIGN 2, 대상 없는 질문 1, 두 질문 1, 미인용 1). p11a(4.0·6.6·7.7, 11/31)보다 나쁘다.
받기 없음 7회 가운데 4회는 받는 문장 금지 꼴(p11a 뒤 넓힌 짐작·감상 꼴)을 지운 뒤에 났고, 질문 완결성 5회는 사례 앞 답의 낱말을 가리킨 질문을 위반으로 본 탓이다.

**재시뮬 전문에서 찾아 고친 것(재시뮬 없음, 단위 시험만)**
여는 질문 유실(한 문장 틀의 여는 질문을 8-w 가 자르고 8-w2 가 지움) · 다시 묻기 턴에 8-w3 재생성이 끼어듦 · '…상황을 받겠습니다'(새 지시문의 낱말) ·
사례 없음 재질문이 기본 질문으로 바뀜 · 입버릇 대체 '짚어 주십시오' 가 질문으로 읽히지 않아 그 뒤 '네, 맞아요' 가 다시 묻기로 못 감(+ 같은 대체 표현 7회) ·
'전면 도입을…' 의 '전면' 을 조건절로 읽어 두 질문이 남음 · 한 문장 두 질문의 다른 꼴 둘 · 관찰 문장 '…그 무게를 알아주셨습니다' · 짐작 받기 '…때문이겠지요' ·
인용 구절 속 '내가' · 범위 문장이 '그 과정에서' 로 시작 · 금지 꼴 삭제 뒤 재생성 → 구절 인용으로 · 가리키는 말의 대상을 사례 전체에서 찾음.

**남긴 것** 슬롯이 하나도 안 찬 사례가 8턴까지 간다(무진전 종료는 찬 슬롯이 있을 때만) — 상태기계 규칙이라 고치지 않고 보고.

## §27. P11e 판정(2026-11-12)과 다음 묶음 후보 (미착수)

**P11e(ea36411, 11/12 배포)** 재질문 뒤의 거절은 즉시 사례 없음으로 닫는다 · 같은 답은 종류를 합쳐 세고 두 번째에 사례를 닫는다 ·
여는 답이 이번 영역에서 이미 닫힌 사례와 같은 사건이면 새 사례·보완 사례로 올리지 않는다(`repeat_of`) · 요약의 주어는 리더님만 ·
받는 문장 12어절 초과·리더 1인칭 삭제. 시뮬 p11e(Daniel × 사례 없는 팀장 1챕터): $0.0141 · 16턴 · p50 3.0s · p95 4.4s · 재생성 걸린 턴 2 · 형식미해결 0.

**판정** 닫힌 사례를 다시 말한 답에서 나온 새 사실은 원래 사례의 `addenda`(칸·인용·출처 턴)로 **기록만** 한다. 대화 중 매핑은 다시 돌리지 않는다(현행 그대로).
같은 사건을 다시 말해 칸 점수가 오르는 길을 열지 않기 위해서다.

**다음 묶음 후보** 검토자 지정(2026-11-12). 지시가 오기 전에는 구현하지 않는다.
- **물음표 없이 '…여쭙겠습니다'로 끝나는 질문**: p11e 3턴(사례 1 첫 탐침·넷째 탐침, 재질문 1).
- **한 문장에 질문 둘 이상**: p11e 2턴, 많게는 셋(누구의 표정·말인지 / 실제로 한 행동).
- **예고 문장**: 재질문 턴의 '…조금 더 가까운 일로 돌려 보겠습니다'가 남는다.
- **'다시 한다면'을 묻지 않고 닫힌 사례**: 5칸이 찬 사례가 남은 한 칸(배운 점)을 묻지 않은 채 2턴 진전 없음으로 닫혔다(마지막 두 질문이 이미 들은 쪽을 다시 물음).
- **재질문 문장이 사전 질문으로 바뀐 원인**: p11e 재질문 2에서 LLM 이 쓴 작은 장면 질문이 사전 질문으로 나갔다. 그 문장은 꼴 검사를 통과하고 닫힌 사례도 끌어오지 않는다 —
  8-q 가 본 마지막 질문 문장과 바꾼 사유를 남기는 기록 키가 필요하다.
- **1인칭 검사의 범위**: 질문 앞 첫 평서문만 본다(둘째 평서문은 놓친다). **관찰 문장**에는 길이 기준이 없다(p11e 16어절).
- **시뮬 프로필 '사례 없는 팀장'**: 사례 1에서 두 칸이 strong 이 되고 두 칸이 사례 없음으로 닫히면 리더 턴 9개에서 영역이 끝나, 네 번째 여는 질문 주입(닫힌 사례 다시 말하기)과
  탐침 6~8번째 주입이 실행되지 않는다. 주입 위치를 앞당겨 그 경로가 시뮬에서 실행되게 한다(지금은 단위 시험·스텁 강제 점검·p11dn 답 오프라인 대조로만 확인).

## §28. P12 — 11/13 운영 Michael 세션(CNC-CLAUDE) 검토 반영 (2026-11-13)

프롬프트 수정 위주, 검사 추가는 둘(8-w4b 한 단계에 합침, 재생성은 합쳐 1회).

1. **질문이 스스로 서게** 턴 형식 지시문: 질문 문장 안에 리더가 직전 답에서 쓴 낱말(사람·일·때)을 넣는다 — 질문 앞 평서문에 기대지 않는다.
   검사(8-w4b ①): 질문 문장에 리더 답과 겹치는 내용 낱말이 하나도 없으면 다시 쓰기 1회(`turn_checks.question_overlap`, 지시어는 보지 않는다).
   직전 답과 겹치지 않아도 이 사례의 앞선 답과 겹치면 통과로 본다(기록 `q_overlap_src` = prev|case). 못 고치면 그대로 내보낸다.
   기본 질문의 머리(`'○○'와 관련해`, `말씀하신 '○○' 건에서`)는 삭제 — 머리 없이 질문만.
2. **한 장면을 쪼개 캐묻지 않기** 같은 것(슬롯)을 채우려는 질문은 사례당 2회(`SLOT_ASK_MAX`, 사례의 `slot_asks`·`ask_slot`). 두 번 물어도 안 나오면 다음 것으로,
   남은 것을 모두 두 번씩 물었으면 닫는다. 결과를 두 번 물어도 안 나오면 '다시 한다면'으로 넘어간다. 지시문: 아직 듣지 못한 것(결과·기준·다시 한다면)으로 나아간다,
   이미 들은 대화를 거슬러 올라가며 되묻지 않는다.
3. **턴 배분** 아직 묻지 않은 칸의 예약 1턴 → 2턴(`RESERVE_PER_UNASKED`). 칸이 7개 이상인 영역(사람관리)은 사례당 리더 턴 최대 8 → 6(`episode_turn_max`).
   훑는 질문에서 사례가 나오면 꼬리 질문 1회는 한다(`sweep_followup_allowed` — 여섯 가지가 다 나왔거나 남은 칸의 여는 질문을 못 내게 될 때만 생략).
4. **입버릇** 이번 영역에서 두 번 이상 쓴 청하는 꼴의 끝맺음을 사례 카드에 넘긴다(`request_ending_key`·`ending_counts`). 검사(8-w4b ②): 같은 끝맺음 4회째면 다시 쓰기 1회, 실패하면 그대로.
   사전 질문(여는·훑는 질문)은 꼬리 변형 가운데 이번 영역에서 가장 덜 쓴 끝맺음을 고른다. Michael 꼬리 3종 → 5종. 치환표는 쓰지 않는다.
5. **평가·해설 말투** 금지 문구 8종 추가(걸린 문장만 삭제). 전환 영역 정의 턴 지시문에 남아 있던 옛 질문 예시 4개 삭제(ALIGN 받기에 흘러든 낱말의 출처로 본다).
6. **여는 문장** 칸 설명을 문형에 끼워 넣지 않는다 — 여는 문장은 전부 질문만(사전 질문, LLM 호출 없음). `render_opener` 와 틀 4종은 쓰이지 않는다(코드 정리는 승인 뒤).
   지시문: 지금 듣는 이야기의 말만 쓴다 — 앞에서 끝난 다른 이야기를 끌어오지 않는다.
7. **말투·오독** 영역 종료 요약에 코치 말투 강제(`apply_register(strict)`), 해요체 코치는 평서문도 말투 교정 대상(합쇼체 코치는 종전대로 질문 문장만).
   라포 담당 업무 답이 조사 없는 낱말 나열이면 고정 받기 + 기대 질문(`input_anomaly.is_bare_noun_list`), 스몰톡 10자 기준에도 같은 판정을 더했다.
시뮬 도구: `--topics '조직관리,사람관리'`(시뮬 서버의 영역 순서만 바꾼다).
