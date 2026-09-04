# Find ME 코드베이스 전체 검토 (2026-09-02)

대상: `new_diagnosis_api/`(FastAPI·SQLModel·Gemini) + `diagnosis-frontend/`(Next 16).
검토 방식: 전 소스 정독 + 호출 경로 추적 + `tsc --noEmit`/ESLint/pytest 실측.

## 0. 확정 결정 (2026-09-02, 검토 후 4개 질문에 대한 답)

| 질문 | 결정 |
|---|---|
| H8 셧다운 임계 | **코드가 확정**: `composite_shown = measured_total ≥ COMPOSITE_MIN_MEASURED(18)`. "대역량 3개 이상에서 각 2건 이상 measured"(3×2)는 V-6 중간 단계였고 대체됨. `score_suppressed_structural`·`qualifying_competencies` 는 정보/회귀 보존용. |
| M3 depth 종료 조건 | 의도 아님. `MIN_EVENTS=1`, `MIN_TURNS` 제거 → 넓이 충족 + STAR≥0.7 사건 1건이면 자연 종료. (2단계) |
| M8 D트랙 게이트 모델 | pro 로 통일 + `analysis_cache` 편입. (2단계) |
| M18 회귀 테스트 기준 | "81개" 기준 목록 없음. 순수 pytest 테스트만 `testpaths` 로 정리하고 그 수를 새 기준으로. (2단계) |

## 1. 진단 플로우 실제 호출 경로 (요약)

```
POST /diagnoses/submit_message → _submit_message_phase3a
  가드(completed/aborted) → user 메시지 저장 → 참여이탈 카운터(classify_engagement)
  → build_turn_state → decide_instruction
  → [asked 배선] apply_probe_turn(LLM 이전 기록) → 전진 시 STAR_COMPLETE_NEW_EVENT 오버라이드
  → 3-Layer 프롬프트 → generate_phase3a_interaction(flash) 또는 시스템 템플릿
  → 마커 게이팅 → _handle_event_lifecycle → 챕터 전진/paused/aborted
POST /reports/{sid}/analyze
  → _build_chapter_transcripts + _build_asked_subcompetencies(원장)
  → generate_diagnosis_result: outer×3 { 5 병렬 _analyze_single_competency(pro) → _run_level_gate(fail-closed) → _finalize_ledger(measured = asked ∧ evidence ∧ gate) }
  → merge_outer_runs → _generate_comprehensive_summary(pro) → coverage(composite_shown) → build_course_recommendation
  → DiagnosisReport 저장 → resolve_completion_status
```

불변조건 점검: `asked=False → measured=True` 경로 없음. LLM 이 점수에 개입하는 경로는
`star_depth_bonus / confidence_adj`(클램프) 뿐. 26 분모는 coverage 에서 동적 합산.

## 2. 발견 항목

심각도: Critical / High / Medium / Low. 상태: ✅ 1단계(파일럿 전) / ⏭ 2단계(파일럿 후) / 🔗 (B) 인증 작업으로 이관.

| # | 심각도 | 위치 | 문제 | 제안 | 상태 |
|---|---|---|---|---|---|
| C1 | Critical | `config.py:18` | SECRET_KEY 개발 기본값 폴백 → 어드민 JWT 위조 가능 | 기본값 제거, 미설정 시 기동 실패 | ✅ |
| C2 | Critical | `participants.py:141` 등 | 참가자 토큰이 가짜 문자열, 참가자 API 전부 무인증 | 실 JWT + 소유자 검증 + AUTH_ENFORCED 킬스위치 | 🔗 (B) |
| C3 | Critical | `diagnoses.py /reset` | 무인증 파괴 엔드포인트(자식 테이블 미삭제로 FK 500) | 제거 | ✅ |
| C4 | Critical | `reports.py` GET `/`, GET `/{sid}`, POST `/analyze` | 무인증 열람/재분석 트리거 | `GET /reports/` 삭제, 나머지는 (B) 소유자 검증 | 🔗 (B) |
| H1 | High | `reports.py analyze` | 분석 전 기존 리포트 삭제 → 실패 시 복구 불가, 교정본 소실 | 생성 성공 후 동일 트랜잭션 삭제, 교정본 보호 | ✅ |
| H2 | High | `reports.py total_score 폴백` | radar 전부 None 이면 TypeError 500 | 폴백 제거 | ✅ |
| H3 | High | `diagnoses.py /start,/active,가드` | `aborted_disengaged` 재개 불가(설계 A-4 위반) | RESUMABLE 상수 통일 + 재개 시 in_progress 복원 | ✅ |
| H4 | High | `chat/page.tsx`, `avoidance_detector.py`, `instruction_decider.py` | "잠시 쉬기/다음에 하기" 문구가 refusal 로 분류 → ABORT_CONFIRM 체인 | pause 를 A 블록보다 먼저 평가, pause 라벨 분리, 버튼 문구 PAUSE 전용 | ✅ |
| H5 | High | `diagnoses.py 프로브 스텝` vs LLM 폴백 | LLM 실패 시 asked 원장 전진이 남음(허수) | 폴백 분기에서 원장 롤백 + LLM_ERROR 태깅 | ✅ |
| H6 | High | `report/page.tsx` | 가짜 이름/소속/비교 평균 하드코딩 | 응답에 participant·company 추가, 없으면 숨김, 비교 차트 제거 | ✅ |
| H7 | High | `requirements.txt` | openpyxl 누락 → 엑셀 내보내기 500 | 추가 | ✅ |
| H8 | 설계 | `scoring.py`, `llm_service.py` | 셧다운 기준 문서/코드 불일치 | 코드 확정, 문서·주석 갱신 | ✅ (본 문서) |
| M1 | Medium | `instruction_decider._SUB_COUNTS`, `report/page.tsx:694` | 하위역량 수 하드코딩 | 프레임워크에서 계산, `coverage.total` 사용 | ⏭ |
| M2 | Medium | `diagnoses.py 전진 오버라이드` | CONTRARY_NEEDED 가 삼켜질 가능성 | 실세션 로그 관찰 후 결정(관찰만) | ⏭ 관찰 |
| M3 | Medium | `instruction_decider depth 조건` | STAR 3건+8턴 조건이 3턴 상한 아래서 도달 불가 | MIN_EVENTS=1, MIN_TURNS 제거 | ⏭ |
| M4 | Medium | `avoidance_detector.check_avoidance` | 10자 미만 전부 회피 카운트 → no_yield_forced 오판 | 길이 조건 제거(키워드만) | ✅ |
| M5 | Medium | `llm_service` 게이트/heavy 8192 | dynamic thinking 절단 → pending/state 소실 | 배치 분할 + MAX_TOKENS 재시도 | ⏭ |
| M6 | Medium | `llm_service._generate_with_retry` | 키 로테이션×재시도 폭주, 결정적 오류도 재시도 | 429/503 만 재시도, 총 상한 시간 | ⏭ |
| M7 | Medium | `llm_service:770` | "사용자:" 절단이 JSON 응답에도 적용 | 평문 호출에만 적용 | ⏭ |
| M8 | Medium | `course_recommender._strength_gate_pass` | flash·미캐시 | pro 통일 + 캐시 | ⏭ |
| M9 | Medium | `analysis_cache`, `level_gate._GATE_CACHE` | 파일 전체 재기록, 무한 성장 | 메모리 캐시/DB | ⏭ |
| M10 | Medium | `GeminiService` | 요청마다 생성, 호출마다 Client | 싱글턴 | ⏭ |
| M11 | Medium | `build_turn_state` | 턴당 ~16 쿼리 | 1회 로드 후 집계 | ⏭ |
| M12 | Medium | `admin.list_reports/stats` | scores 전체 JSON 페이로드 | 요약만 반환 | ⏭ |
| M13 | Medium | `submit_message` | 세션 잠금 없음(더블 서밋) | 세션 락 / idempotency key | ⏭ |
| M14 | Medium | `config.phase3a_enabled`, `.env.example` | USE_PHASE3A 기본 false | 기본 true | ✅ |
| M15 | Medium | `app/login`, `app/select-coach` | 죽은/깨진 페이지 노출 | 삭제 | ⏭ |
| M16 | Medium | `admin/participants`, `chat/page.tsx` | 상태 라벨 불일치(incomplete 잔존, aborted_disengaged 누락) | 상태 상수 통일 | ✅ |
| M17 | Medium | `models/__init__`, `database.py` | 레거시 테이블 생성, 마이그레이션 예외 무음 | 정리 | ⏭ |
| M18 | Medium | `tests/` | 스크립트형 테스트, fixture 부재 | pytest 순수화 + testpaths | ⏭ |
| M19 | Medium | 프론트 전반 | `any` 71곳, ESLint 71 error | 응답 타입 정의 후 치환 | ⏭ |
| M20 | Medium | `config.py` | 미사용 GEMINI_API_KEY, CORS env 포맷 | 정리 | ⏭ |
| M21 | Medium | 모델/`admin.stats_daily` | naive/aware datetime 혼재 | UTC 통일 | ⏭ |
| M22 | Medium | `reports.py analyze 상태 전이` | aborted/paused 를 in_progress 로 부활 | 상태 전이 표 명시 | ✅ |
| M23 | Medium | `layer3_state.py:173`, `layer1_system.py:861` | Ella 예시/폴백 잠재 누출 | 변수화 | ⏭ |
| L1~L13 | Low | (검토 보고서 참조) | 소속 동기화 대소문자, report_by_pid 임의, 죽은 설정/분기, 로그 중복 등 | 정리 | ⏭ |

## 2-b. 2단계 착수 메모 (2026-09-03 추가)

- **첫 항목**: `diagnosis-frontend/app/assessment/self-eval/page.tsx:71` — mount effect 안에서
  `chatUrl` 을 선언 전에 접근(ESLint `react-hooks` error). 직전 작업(d945bc0, 재개 세션
  자가진단 스킵)에서 생긴 것. 런타임은 정상이나 선언 순서를 정리한다.
- **M2 관찰**: 1단계 배포 후 완주 테스트 로그에서 `🧭 T2 타겟 전진 감지 … 오버라이드
  CONTRARY_NEEDED→STAR_COMPLETE_NEW_EVENT` 가 찍히는지, 그리고 그 챕터의 `has_contrary_probe`
  가 끝까지 False 로 남는지 확인 후 보고. 삼켜지면 CONTRARY_NEEDED 는 오버라이드 대상에서 제외.
- 1단계 판단 확정(2026-09-03): H1 은 교정본 존재 시 재분석 스킵(200), H4 는 정중한 긴 미루기도
  pause, H6 은 비교 차트 컴포넌트 삭제. 모두 승인됨.

## 2-c. 조건부 후처리 목록 (2026-09-04 전수 확인 — 2단계 검토 대상)

LLM 응답이 나온 뒤 "조건 X면 덧붙임/교체/무시"로 동작하는 코드. 한 수정이 다른 규칙을
깨우는 부작용의 전형이라 목록으로 보존한다(`routes/diagnoses.py` `_submit_message_phase3a`).
✅ = 2026-09-04 수정 완료.

| # | 위치 | 조건 | 동작 | 상태 |
|---|---|---|---|---|
| 1 | 8-a DIAGNOSIS_INTRO | 빈 응답 (~~"죄송합니다" 포함~~) | "말씀 감사합니다." + 안내 본문 | ✅ 조건 축소 |
| 2 | 8-b COMPETENCY_ALIGN | 빈 응답 (~~"죄송합니다" 포함~~) | 고정 폴백 문장 | ✅ 조건 축소 |
| 3 | 8-d CHAPTER_READY_TO_END | 빈 응답 | "이 영역, 여기서 잘 매듭짓겠습니다." + 완료·시작 마커 강제 | 보존 (`?` 조건은 제거됨) |
| 4 | 8-e CHAPTER_CONTINUE_CONFIRMED | 빈 응답 | 고정 브릿지 문장 | 보존(죽은 경로) |
| 5 | 8-f 앵무새 방어 | 직전 코치 메시지와 동일 | ~~무작위 3문장 교체~~ → 제약 추가 후 LLM 재생성 1회, 재생성도 동일하면 타겟 질문 폴백 | ✅ |
| 6 | SESSION_END_EARLY | 조기 종료 마커 | 고정 마무리 문장 덧붙임 | 보존 |
| 7 | 마커 게이트 | `[DIAGNOSIS_COMPLETE]` + 다음 챕터 존재 | 마커 무시 | 보존(의도된 방어) |
| 8 | 마커 게이트 | `[CHAPTER_COMPLETE]` + 비허용 instruction | 마커 무시 | 보존 |
| 9 | 마커 게이트 | `[SESSION_PAUSE]` ↔ USER_REQUESTS_PAUSE | 무시 / 강제 paused(양방향) | 보존 |
| 10 | 마커 게이트 | `[SESSION_END_EARLY]` + 비허용 instruction | pause 로 격하 | 보존 |
| 11 | SUGGEST_PAUSE 2-Strike | 3번째 제안 | 강제 종료로 변환 | 보존 |
| 12 | `_suppress_mechanical_text` | 조기 종료·제안·일시중지 턴 | 1·2번 덧붙임 건너뜀 | 보존 |
| 13 | `build_turn_state` 9-f | 라포 3턴+동의 | `[READY_FOR_INTRO]` 강제 | 보존 |
| 14 | `llm_service._generate_with_retry` | 출력에 "User:"/"사용자:" | 이후 절단 (M7) | 2단계 |

## 3. 진행 순서

1. 1단계(파일럿 차단): C1, C3, H1, H2, H3(+M16, M22), H4, H5, H6, H7, M4, M14 — 항목별 커밋.
2. (B) 인증: C2·C4 포함, 프론트 먼저 → 백엔드, AUTH_ENFORCED 킬스위치.
3. 2단계(파일럿 후): 나머지 M/L, M3·M8·M18 은 위 결정대로.
