# 코치 턴 후처리 파이프라인 — 단계표 (2026-09-21 도입 · 2026-11-04 BEI 개편)

`_submit_message_phase3a` (routes/diagnoses.py) 가 리더 메시지를 받아 코치 메시지를 DB 에 저장하기까지 거치는 단계를 **실행 순서대로** 적는다.
설계 원문: `docs/design_bei_2026-11.md`. 시스템 템플릿 턴(라포 1턴·안내·전환 팝업 대기·입력 이상 고정 응답)은 `system_override_text` 가 있어 ★ 표시 단계만 지난다.

## 절차 — 프롬프트 규칙을 추가할 때
새 규칙이 만들어 내는 **문장 형태**를 아래 표의 "무엇을 자를 수 있는가" 열과 대조한다.
1. 그 형태를 자를 수 있는 단계가 있으면 그 단계에 **예외**를 넣고 테스트를 추가한다.
2. 규칙이 만드는 문장이 **질문**이면 "질문 보존" 열이 '보장 안 함'인 단계를 지나는지 확인한다.
3. 같은 입력으로 시뮬(`tools/sim_leader.py`)을 돌려 전·후를 비교하고 guard_log 에서 그 규칙의 문장이 교정 대상이 된 턴 수를 센다.

## LLM 호출 '이전' — 사례 단계 (BEI)

| # | 단계 | 무엇을 하는가 | LLM 호출 |
|---|---|---|---|
| 4 | `build_turn_state` → `decide_instruction` | 라포·안내·정의·ALIGN·META·일시정지·이탈·주입은 결정기. 사례 단계면 `EPISODE_PROBE`(기본값)를 낸다. `bei_state == close` 또는 MAX_TURNS(35~50) 안전망이면 `CHAPTER_READY_TO_END` | 0 |
| 4-b | 페르소나 | `state["coach_persona"]` — 고정 문장(여는 앵커·정의 질문·슬롯)의 어미 변환이 BEI 단계 앞에서 본다 | 0 |
| 입력 이상 | `input_anomaly.detect` | 반복·붙여넣기·일시정지 오입력·안내 뒤 비실질·정의 10자 미만·질문 뒤 단답 → 고정 응답(LLM 없음). **같은 사례에서 2회째 단답·반복은 고정 응답 없이 BEI 단계로**(재질문 1회 → 사례 폐기). `ANCHOR_REASK`(단답 1회째)는 **직전 코치 턴이 형식 검사를 통과한 마지막 질문 문장만** 되묻는다 — 직전 턴이 `format_miss` 이거나 질문이 둘·유도형이면 되묻지 않고 BEI 단계에서 LLM 이 새 질문(`bei_anomaly_reask` 신호, 2026-11-05) | 0 |
| BEI | `services/bei_engine` + `services/slot_judge` | ① ALIGN 턴: 사례 1 열기(`pick_opener`, asked·anchored 기록). ② 사례 턴: 리더 턴 +1 → **슬롯 판정(Haiku 1콜)** → 병합(sticky·원문 검증) → 종료 판정(6/6 / 리더 턴 8 / 예산) → 종료면 **매핑(Haiku 1콜: 하위역량 정의 + Lv.2 행동 예, 하위역량마다 strong/weak/none + 확신도; strong = 확신도 ≥ 0.8 ∧ 인용이 리더 원문에)** → `covered`(strong)·`weak`·`asked_subs` → 다음 상태(`plan_after_episode`: 사례 / SWEEP / 종료). 없다는 답은 재질문 1회(`EPISODE_RETRY`) 뒤 폐기(`no_case_subs`·SWEEP 은 `unconfirmed`). SWEEP: 앵커 1 + 후속 ≤1(행동+결과가 차면 생략). 결과 instruction: `EPISODE_OPEN / EPISODE_PROBE / EPISODE_RETRY / SWEEP_ANCHOR / SWEEP_FOLLOWUP / CHAPTER_READY_TO_END` | 1~2 |
| 카드 | `episode_card.build_episode_card` | 지금 듣는 사례(n번째/리더 턴 k/8/예산)·채워진 슬롯(리더 말 인용)·미충족 슬롯 순서·이번 턴 슬롯·직전 답 신호·지난 사례·시스템이 붙일 앵커 | 0 |
| 6 | 프롬프트 | system = Layer1(light/heavy) + 페르소나 + Layer2 축약(`chapter_context_bei`) + Layer3(`format_turn_state_for_llm`: BEI 턴은 카드+가이드+턴 형식·금지, 그 외는 가이드) ; user = 현 챕터 이력(완료 사례는 Event 요약 1줄) + 꼬리 블록 + 최신 발화 | 본 호출 1 |

## LLM 호출 '이후' — 단계표

| # | 단계명 (코드 표지) | 무엇을 하는가 | 무엇을 자를 수 있는가 | 질문 보존 |
|---|---|---|---|---|
| 8 | 마커 파싱 ★ | `[SESSION_END_EARLY]`·`[DIAGNOSIS_COMPLETE]`(남은 챕터 있으면 차단)·일시정지 제안(`should_suggest_pause`, 사례 탐침 턴만) | 플래그만 | 무관 |
| 8-0 | 라포 2·3·4턴 | LLM 되받기 + 백엔드 고정 질문(`persona_line`) | 되받기 외 전부 | 보장 |
| 8-a | DIAGNOSIS_INTRO | LLM 되받기 1문장 + 안내 본문 | 안 자름 | 보장 |
| 8-b | COMPETENCY_ALIGN | 인용 가드·누설 재생성(조립 전) → **되받기 인용 검사(P3-1: 리더 정의 명사구 인용, 2026-11-05)** 재생성 ≤2, 미해결이면 본문을 비워 8-z 가 `align_receive_quote`(리더 명사구 인용 1문장)로 받는다 — '네, 잘 들었어요' 폴백 삭제 → 재료 보관(`_align_ctx`: 사례 1 여는 앵커 = 사전 52문 + 페르소나 어미) | LLM 질문·인용 없는 되받기 | 보장(8-z 가 조립) |
| 8-d | CHAPTER_READY_TO_END | LLM 요약 2문장(질문·칭찬·상태 누설·전환 문장 제거) + 고정 `chapter_end_bridge`; 마지막 챕터는 `final_closing_message` + 리포트 예상 시간 | 전체 교체 | 의도적으로 질문 없음 |
| 8-f | 앵무새 | 직전 코치 턴과 동일하면 재생성 1회. 같으면 그대로 두고 guard_log `parrot=2`(폴백 문장 없음) | 전체 교체 | 보장 안 함 |
| 8-i0 | '사건' 낱말 치환 | '이번 사건'→'그 일' 류 | 낱말 | 보장 |
| 8-i | 통합 출력 가드 | 감지: praise·revisit·state_leak·leak·names_mention(사례 턴)·no_question·same_question·bare_ref(사례 탐침 턴). `names_mention/no_question/same_question/bare_ref/leak` 는 재생성 1회 → 남은 위반은 하드 교정(칭찬 제거 뒤 깨진 문장 재생성/삭제 포함). **앵커 폴백·off_target·transition 관찰 폐지** | 위반 문장만(질문 보존) | 보장(질문 없음은 8-w 가 다시 본다) |
| 8-i 끝 | BEI 조립 | `EPISODE_OPEN`·`SWEEP_ANCHOR`: LLM 본문의 질문을 지우고 [되받기+다리 ≤3문장] + **시스템 앵커**(`anchor_attached`). 사례 탐침 턴: 시점 문형 교정·권유 평서문 제거 | LLM 질문(여는 턴) | 보장(앵커) |
| — | 대명사 단독 질문·문법 | '그럴 때는 어떠셨습니까' 류 제거/교체 · '있으시겠습니까'→'있으셨습니까' | 질문 1문장(질문→질문) | 보장 |
| 8-n | 입버릇 | 되받기 마무리 어구 세션 집계. 2회째 재생성(앵커·슬롯 턴은 `splice_receive` 로 되받기만 교체), 3회째 삭제. 고정 문장(슬롯·시스템 앵커)은 집계 제외. '리더님,' 문두 호칭 3턴 1회 | 되받기 문장 | 보장 |
| 8-w | **턴 형식 검사** | 되받기 1~3문장(리더 명사구 인용) + 질문 1개. 위반(`no_receive/no_quote/long_receive/no_question/two_questions/leading_choice`)을 모아 **재생성 최대 2회**(앵커·슬롯 턴은 되받기만 교체). 폴백 문장 없음 — 2회 뒤에도면 그대로 내보내고 `format_miss`·`receive_miss`. 질문 2개가 남으면 복합 질문은 마지막 절, 문장이 여럿이면 마지막 질문만(`split_compound_question`·`keep_last_question`, 결정 1). `leading_choice`(2026-11-05) = 유도형 이지선다('~나요, 아니면 ~나요?')·가정형('~하셨다면 어떻게') — 열린 질문으로 재생성, 2회 뒤에는 그대로(결정론 교정 없음) | 되받기 교체·앞선 질문 | 보장(질문부 불변) |
| 8-s | 페르소나 슬롯 | **사례당 1회**, 사례 리더 턴 3~5, 되받기 뒤. Jessica·Lucas·Olivia 는 LLM 질문을 `slot_q` 로 대체 / Daniel 되받기+관찰(5종, 챕터 순서 인덱스에서 시작해 같은 챕터 안에서 쓴 문장은 건너뜀 — `daniel_obs_used`)+LLM 질문 / Michael 되받기+"그 선택, 응원합니다."+LLM 질문 → 다음 턴 `slot_q`. 되받기 없는 턴엔 넣지 않는다 | LLM 질문(3명) | 보장 |
| 8-p | Michael '좋습니다' | 턴당 1회·연속 금지·챕터 3회 상한 | 리드 어구 | 보장 |
| 8-k | 정의 턴 질문 고정 | LLM 질문 제거 후 `definition_question` | LLM 질문 | 보장 |
| 8-h | 느낌표 ★ | 페르소나 상한(Michael 1·안내 0) + 챕터 누적 2 → 재생성 1회 → 치환 | 부호 | 보장(재생성 결과는 8-i 를 다시 안 지남) |
| 일시정지 제안 | SUGGEST_PAUSE 턴 | 되받기 1문장 + `pause_suggestion_text`. **BEI 원장 되돌림**(`bei_engine.restore`) + `pending_instruction` 저장 — 재개 턴이 같은 답으로 다시 판정 | 질문 삼킴(pending) | 무관 |
| 8-x2 | 슬롯 복원 | 뒤 단계가 슬롯 고정 문장을 지웠으면 복원 | — | 보장 |
| 8-y | 최종 누설 소거 ★ | 재생성 출력에 남은 엄격 사전 어휘·상태 보고문 평서문 삭제 | 평서문 | 보장 |
| 8-z | ALIGN 조립 | [되받기] + [정의] + [목록] + [안내 "이 N가지가 실제로 어떻게 나타나는지…"] + ["먼저 하나를 깊게 들어볼게요."] + [사례 1 앵커] | — | 보장 |
| 9 | 저장 ★ | `probe_type_used`(INCIDENT/SPECIFICATION/META), **종료된 사례 → Event 행 1건**(situation/action/result = 슬롯 인용, mapped_subcompetency = strong 라벨, 그 사례 구간 메시지에 event_id 태깅), ChatMessage 저장 | — | 무관 |
| 11~12 | 챕터 전진·guard_log·커밋 ★ | 턴 끝 1회 커밋. guard_log 에 BEI 키(`bei/episode/ep_turn/slots_filled/slot_judge/closed/mapped/target/anchor_attached/format_regen/format_miss/receive_miss`) | — | 무관 |

## 폐지된 단계(2026-11-04) — 코드·테스트 함께 삭제
하위역량 단위 앵커 루프(`apply_probe_turn`·3턴 상한·넓이 게이트·서킷브레이커·`STAR_*`·`CONTINUE_NORMAL`), 사다리 탐침(`ladder_questions`·8-x), 일반화 탐침, '직접 하신 일' 탐침·상한, 감정·대조 질문 챕터 상한, 결과 질문 강제·반복 교체·수치 질문, 고정 전환 다리(8-j·`target_bridges`·`bridge_idx`), 되받기 폴백 문장(`receive_fallback`), 9/22 리드 1문장 상한(`cap_lead_sentences`), `ANCHOR_REASK` 2·3회 변형(`reask_anchor_2`·`skip_item`), 반례 탐침(`CONTRARY_NEEDED`), 부재·회피·무수확 instruction(`ABSENCE_PROBE`·`AVOIDANCE_DETECTED`·`ABSTRACT_AVOIDANCE`·`CHAPTER_NO_YIELD_ULTIMATUM`·`CHAPTER_ONE_MORE_ASK`), STAR 휴리스틱 사건 추적(`plan_event_update`), `CHAPTER_OPENING` 템플릿·앵커 프레임 풀, Layer2 챕터 스크립트(`layer2_chapters.py`), Layer3 Turn State JSON·Global Memory·강제 블록.

주의
- 8-h 의 느낌표 재생성 결과는 8-i 검사를 다시 받지 않는다(위반이 드물어 감수).
- 8-w 는 `RECEIVE_REQUIRED_INSTRUCTIONS`(사례 턴 5종)에만 돈다. META·라포·정의·ALIGN 은 각자 보장한다.
