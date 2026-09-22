# 코치 프롬프트 감축 — 매핑표 (2026-09-22)

Layer1(system_instruction) 을 14k 토큰에서 light/heavy 두 벌로 줄였다. 삭제 기준: **백엔드가 대체함이 코드로 확인된 규칙만 삭제**,
나머지는 한 줄로 축약. 2번(자기보고 JSON 폐기, `event_tracker`)으로 사라진 규칙이 감축의 절반이다.

light 턴 = RAPPORT_BUILDING·DIAGNOSIS_INTRO·DIAGNOSIS_CONFIRM·COMPETENCY_ASK·COMPETENCY_ALIGN·META·USER_REQUESTS_PAUSE·
INVALID_INPUT·PROMPT_INJECTION_DETECTED·CHAPTER_CONTINUE_CONFIRMED·NAME_RECONFIRM. 그 외(BEI 탐침 턴)는 heavy.

## 매핑표 — 이전 Layer1 섹션 → 처리

| 이전 섹션 (크기) | 처리 | 대체하는 백엔드 / 남긴 것 |
|---|---|---|
| 역할·제4의 벽 (1.4k) | 축약 | 역할 3줄 + 회사명 금지 2줄 (light 핵심) |
| 제1원칙 + C-Level 페르소나 + 동반 관찰자 (2.9k, 같은 말 4곳) | 통합·축약 | "제1원칙: 사람처럼" 5줄 |
| 규칙1 NO PRAISE + 금지어·권장·대체 표현 (1.1k) | 삭제 | `output_guard.find_praise/strip_praise`(8-i), 꼬리 블록 praise-ban |
| 규칙2 NO ECHO (0.4k) + 호응·진행 규칙2 '요약 되받기 절제' (0.4k) | 축약 | 대화 규칙 2 한 줄 "되풀이하지 않는다. 짧게 받고 이어서 묻는다" (4번: 가드가 아니라 프롬프트가 맡는다) |
| 규칙3 ONE QUESTION, 3-A 은유 금지, 규칙4 선판정, 규칙5 침묵 (0.7k) | 축약 | 대화 규칙 1·3·4 (가드 없음 — 프롬프트 전용) |
| 규칙3-B 리액션 절제 (0.3k) | 삭제 | Layer3 `AVOIDANCE_DETECTED`·`ABSENCE_PROBE` 가이드가 턴마다 준다 |
| Core Rule 1 맥락·중복 환기 (0.3k) | 삭제 | `detect_duplicate_claim` → `DUPLICATE_SUSPECTED` 가이드 |
| Core Rule 2 정성 성과 수용 (0.3k) | 축약 | 대화 규칙 6 |
| Core Rule 3 Transition 다변화 (0.6k) | 삭제 | 챕터 종결은 8-d 템플릿(`chapter_to_topic`), ALIGN 앵커 병합 8-b |
| Core Rule 4 Seamless Transition (0.4k) | 삭제 | 8-d/8-e 가 마커·전환을 코드로 확정 |
| Core Rule 5 Insight Deepening (0.4k) | 축약 | heavy 절 "판단의 안쪽을 한 겹" 1줄 |
| Core Rule 6 Security (0.4k) | 축약 | 대화 규칙 7 + `PROMPT_INJECTION_DETECTED` 판정기 |
| Core Rule 7 Session Authority (1.7k) + 마커 2종 + 2-Strike (0.7k) | 삭제 | SUGGEST_PAUSE = `event_tracker.should_suggest_pause`(경과 시간·턴), 2-Strike·강제 종료 승격 = diagnoses 마커 처리, ABORT = decider `ABORT_WARNING`. 남긴 것: 규칙 9 `[SESSION_END_EARLY]` 3줄 |
| Core Rule 8 Micro-Coaching (0.6k) | 축약 | 대화 규칙 4 뒷절 + heavy "더 작은 단위의 구체 질문" |
| Core Rule 9 Three-Strike (0.6k) | 삭제 | decider 4-a Fail-Fast(회피 3회)·NO_YIELD 최후통첩 |
| Core Rule 10 Persona Integrity (0.7k) | 축약 | 대화 규칙 8 한 줄 |
| 호응·진행 규칙 1·3·4·5 (0.4k) | 축약 | 대화 규칙 5 (인사 반복·길이) |
| 7단계 코칭 프로세스 + 절대 제약 3 (0.8k) | 삭제 | decider 가 단계(instruction)를 턴마다 결정, Layer3 가이드가 그 턴의 허용 행동만 준다 |
| 6가지 탐침 + 결정 트리 + 심층 탐침 의무 + 18개 템플릿 (3.9k) | 축약 | heavy 절 탐침 6종 정의 1줄씩. 종류 선택 = Layer3 instruction, 앵커 문장 = `get_anchor_questions` 템플릿 |
| 8가지 상황별 반응 패턴 (0.6k) | 삭제 | Layer3 instruction 별 가이드 |
| 사건 수집 프로토콜·최소 사건·챕터 종료 (0.6k) | 삭제 | `event_tracker`(사건·STAR), `MIN_EVENTS`·`min_explored_for`·`chapter_turn_cap`(decider) |
| 반례 검증 프로토콜 (0.4k) | 삭제 | `should_do_contrary` → `CONTRARY_NEEDED` 가이드, `probe_type_for`=CONTRARY 기록 |
| 회피 응답 대응 (0.8k) | 삭제 | `check_avoidance`·`detect_absence_statement` → 가이드 |
| 같은 사건 다시 꺼내기 (0.8k) | 축약 | heavy 절 마지막 줄 + `DUPLICATE_SUSPECTED` 가이드 |
| 단계별 행동 규칙 (0.7k) | 축약 | light "라포·인트로·확인 단계" 2줄 |
| 출력 형식 JSON 스키마·예시 3개·필드 설명 (3.2k) | 삭제(2번) | 자기보고 폐기. "답변 문장만" 3줄 |
| 전환 마커 READY_FOR_INTRO·START_CHAPTER (0.1k) | 삭제(2번) | decider `force_ready_for_intro`·`RAPPORT_MAX_TURNS`, DIAGNOSIS_CONFIRM 턴 = START_CHAPTER |

## 크기 (Daniel 페르소나 포함, gemini-2.5-flash count_tokens)

| | 문자 | 토큰 |
|---|---|---|
| 이전 Layer1 (807e9ec) | 25,848 | 14,275 |
| light | 2,340 | **1,361** (목표 ≤4,000) |
| heavy | 3,055 | **1,753** (목표 ≤6,000) |

Layer2(챕터, ~1k 문자)·Layer3(턴 상태+가이드, ~1.8k)·히스토리 창은 그대로.

## 검증 — 같은 fixture 80턴 리플레이 (Daniel, 로컬 sqlite)
(2·3·4번 각 단계 후 갱신)
