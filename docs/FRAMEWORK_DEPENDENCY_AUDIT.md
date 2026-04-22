# Framework Dependency Audit
> 작성일: 2026-04-22  
> 목적: `data/competencies.py`를 SSOT로 만들기 위해 프레임워크 가정에 묶인 코드 위치를 전수 조사

---

## 1. 역량 키/이름 하드코딩 위치

### 백엔드

| 파일 | 라인 | 내용 | 심각도 |
|------|------|------|--------|
| `diag_project/llm_service.py` | 26 | `ALL_COMPETENCIES = ["조직관리", "성과관리", ...]` — 5개 한국어 이름 리스트 | 치명적 |
| `diag_project/llm_service.py` | 27–33 | `KOREAN_TO_KEY` 딕셔너리 — 한국어↔영어 키 양방향 매핑 | 치명적 |
| `diag_project/llm_service.py` | 293 | 프롬프트 내부 문자열: `"5가지 영역(조직, 성과, 사람, 일, 자기관리)"` | 치명적 |
| `diag_project/llm_service.py` | 297 | 프롬프트 내부 문자열: `"'조직관리'부터 시작해볼까요?"` | 중요 |
| `diag_project/llm_service.py` | 428–432 | 발화 분류 프롬프트 JSON 템플릿에 5개 영어 키 하드코딩 | 치명적 |
| `diag_project/llm_service.py` | 436–440 | 발화 분류 기준 설명에 5개 한국어 이름 + 행동 키워드 하드코딩 | 중요 |
| `diag_project/routes/diagnoses.py` | 46 | `TOPIC_ORDER = ["조직관리", ...]` — 대화 흐름 순서 | 치명적 |
| `diag_project/services/analysis_service.py` | 94–98 | 레이더 차트 생성 코드에 5개 역량 (한국어+영어) 하드코딩 | 중요 |
| `diag_project/services/analysis_service.py` | 60–63 | 분석 프롬프트 JSON 예시에 `organization_management` 하드코딩 | 중요 |

> ⚠️ `analysis_service.py`는 현재 라우터에 미연결(dead code)이나, 향후 재활성화 시 동일 문제 재발.

### 프론트엔드

| 파일 | 라인 | 내용 | 심각도 |
|------|------|------|--------|
| `app/chat/page.tsx` | 15 | `ALL_TOPICS = ["조직관리", ...]` — 메달 UI, 진행률 계산 기준 | 치명적 |
| `app/report/page.tsx` | 23–29 | 레이더 차트 데이터 배열: 5개 역량, 한국어 라벨 + 영어 키 | 치명적 |
| `app/report/page.tsx` | 131–137 | `SUB_COMPETENCIES` 객체: 27개 지표 이름 모두 하드코딩 | 치명적 |
| `app/report/page.tsx` | 379–385 | `competencyLabels` 매핑: 영어 키 → 한국어 표시명 변환 | 치명적 |

---

## 2. "5개 역량" 가정에 묶인 코드

### 백엔드

| 파일 | 라인 | 내용 | 심각도 |
|------|------|------|--------|
| `diag_project/llm_service.py` | 26 | `ALL_COMPETENCIES` 리스트 길이 = 5 고정 | 치명적 |
| `diag_project/llm_service.py` | 633 | `sum(radar.values()) / len(radar)` — `len()`으로 계산하므로 역량 수 변경 시 자동 적응. **안전** | 안전 |
| `diag_project/routes/diagnoses.py` | 46 | `TOPIC_ORDER` 길이 = 5 고정 | 치명적 |
| `diag_project/routes/reports.py` | 139 | `sum(radar_chart.values()) / len(radar_chart)` — **안전** | 안전 |
| `diag_project/services/analysis_service.py` | 90 | `sum(my_scores.values()) / 5` — **5 하드코딩** | 치명적 |

### 프론트엔드

| 파일 | 라인 | 내용 | 심각도 |
|------|------|------|--------|
| `app/chat/page.tsx` | 15 | `ALL_TOPICS` 배열 길이 = 5 | 치명적 |
| `app/chat/page.tsx` | 187 | `completedList.length === 5` — 피날레 조건 | 치명적 |
| `app/chat/page.tsx` | 205 | `completedTopics.length < 5` — 조기 종료 방지 | 치명적 |
| `app/chat/page.tsx` | 283–295 | `grid-cols-5` — 메달 그리드 5열 고정 (CSS) | 중요 |
| `app/report/page.tsx` | 23–29 | 배열 원소 5개 고정 | 치명적 |
| `app/report/page.tsx` | 51 | `[1, 2, 3, 4, 5].map()` — 레이더 차트 눈금 | 중요 |

---

## 3. "4레벨 루브릭" 가정에 묶인 코드

### 백엔드 프롬프트 (llm_service.py)

| 라인 | 내용 | 심각도 |
|------|------|--------|
| 479–484 | `STEP A — Base Score: 1.0 ~ 4.0` + `Level 1 ~ Level 4` 명시 | 치명적 |
| 471–478 | `[평가 방법론 — 3단계 채점]` 프롬프트 내부에 4레벨 기준 서술 | 치명적 |
| 568–571 | `_build_sub_scores_json_template()` — `<float 1.0~5.0>` 최종 점수는 5점 스케일 | 중요 |

> 참고: `competencies.py` 자체도 `levels: {1, 2, 3, 4}`로 4레벨을 정의하고 있음.  
> 레벨 수 변경 시 competencies.py + 위 프롬프트 모두 수정 필요 (SSOT 부재).

### 프론트엔드

| 파일 | 라인 | 내용 | 심각도 |
|------|------|------|--------|
| `app/report/page.tsx` | 36, 93 | `(value / 5) * radius` — 5점 만점 가정 | 중요 |
| `app/report/page.tsx` | 217 | `{score} / 5.0` — UI 표시 | 중요 |
| `app/report/page.tsx` | 51 | `[1, 2, 3, 4, 5].map()` — 레이더 차트 눈금 5레벨 | 중요 |

---

## 4. STAR/BEI 방법론 가정에 묶인 위치

### 백엔드 (llm_service.py)

| 라인 | 내용 |
|------|------|
| 49–53 | `COACHING_GUIDELINE_TEMPLATE` — "STAR 기법 고도화" + Situation/Action/Learning 용어 |
| 478–484 | 채점 프롬프트에 `STEP B — STAR+R 구조 완성도 보너스` 명시 |
| 497–498 | 분석 JSON 필드 이름: `1_situation`, `2_action`, `3_result`, `4_rubric_mapping` |
| 462 | 함수명 주석: `"STAR + Result 구조 완성"` |

### 프론트엔드 (app/report/page.tsx)

| 라인 | 내용 |
|------|------|
| 197 | `"STAR 깊이"` 라벨 |
| 225 | 주석: `"STAR+R 5단계"` |
| 230–236 | "상황 (Situation)", "행동 (Action)", "결과 (Result)", "기준 매핑 (Rubric)", "어조 분석 (Tone)" 탭 |
| 415 | `"행동사건면접(BEI) 기반"` 레이블 |

### STAR/BEI 방법론의 적용 가능성 평가

- 현재 방법론은 **리더십 행동 역량** 진단에 최적화되어 있음.
- 지식형 역량(예: 전문 기술 지식, 법규 이해도)이 추가된다면 STAR 구조로는 불충분.
- 기술 역량·태도 역량에는 `Scenario-Based`, `Knowledge Test` 등 다른 방법론이 필요.
- **현재 5개 역량은 모두 행동 역량** → STAR/BEI 적용 적합. 방법론 변경은 역량 범위 확장 시 이슈.

---

## 5. competencies.py를 우회하는 코드

### 완전히 우회하는 곳 (복제)

| 위치 | 내용 |
|------|------|
| `app/report/page.tsx:131–137` | `SUB_COMPETENCIES` 객체에 27개 지표 이름 전부 복제. `competencies.py`의 지표 추가/수정 시 이 파일도 반드시 수정해야 함. **가장 심각한 SSOT 위반.** |
| `llm_service.py:436–440` | 발화 분류 기준 설명: 5개 역량의 핵심 키워드를 직접 기술. `competencies.py`의 description과 별개로 관리됨. |
| `llm_service.py:428–432` | 분석 프롬프트 JSON 구조에 영어 키 5개 직접 나열. |

### competency_indicator.py DB 모델 재확인

- `models/competency_indicator.py`에 `Competency`, `Indicator` SQLModel 테이블이 정의되어 있음.
- **실제 사용 여부:** `database.py`에서 import되어 테이블은 생성되나, 어떤 라우터에서도 데이터를 insert/select하지 않음.
- 결론: DB 테이블은 존재하지만 **완전히 빈 테이블**. 실제 역량 데이터는 `data/competencies.py`에서만 관리됨.
- 이 테이블은 미래의 DB 기반 역량 관리를 위한 준비물처럼 보이나, 현재 연결 고리 없음.

---

## 6. current_topic 문자열 흐름

```
[초기값] DB: current_topic = "General"
    ↓ (사용자가 진단 동의 → [START_SESSION] 태그)
[백엔드] diagnoses.py:249-252
    current_topic == "General" 이면 → TOPIC_ORDER[0] = "조직관리"

[대화 진행] 역량별 진단
    ↓ (LLM이 [TOPIC_COMPLETED] 태그 반환)
[백엔드] diagnoses.py:257-265
    current_idx = TOPIC_ORDER.index(current_topic)
    next_topic = TOPIC_ORDER[current_idx + 1]  or  "Completed"

[최종] current_topic = "Completed" or session.status = "completed"
```

### 비교가 일어나는 모든 위치

**백엔드:**
- `diagnoses.py:143` — 세션 생성 시 초기값 `"General"`
- `diagnoses.py:194` — `session.current_topic or "General"` (None 방어)
- `diagnoses.py:212` — `if current_topic in TOPIC_ORDER`
- `diagnoses.py:215` — `elif current_topic == "Completed"`
- `diagnoses.py:249` — `if is_session_starting and current_topic == "General"`
- `diagnoses.py:261` — `next_topic = "Completed"`
- `diagnoses.py:263` — `next_topic = "General"` (ValueError fallback)
- `diagnoses.py:280` — `or updated_topic == "Completed"`
- `diagnoses.py:348–351` — state 조회 시 동일 패턴 반복
- `reports.py:159` — analyze 완료 후 `"Completed"` 설정
- `llm_service.py:303` — `if current_topic == "General"`

**프론트엔드:**
- `chat/page.tsx:15` — `ALL_TOPICS` 기준으로 completedTopics 비교
- `chat/page.tsx:187` — `completedList.length === 5`로만 비교 (topic 이름 비교 없음)

### 특기 사항

`diagnoses.py:263`에 `ValueError` fallback: `TOPIC_ORDER.index(current_topic)` 실패 시 `next_topic = "General"` 로 초기화됨. 알 수 없는 topic 값이 들어왔을 때 조용히 처음으로 되돌아가는 silent failure.

---

## 7. 리팩토링 우선순위 제안

### 치명적 (다음 단계에서 즉시 수정)

| 우선순위 | 대상 | 이유 |
|----------|------|------|
| 1 | `llm_service.py`: `ALL_COMPETENCIES`, `KOREAN_TO_KEY` | `competencies.py`에서 동적 생성으로 교체 가능. 역량 추가 시 llm_service.py 수정 불필요하게 됨. |
| 2 | `routes/diagnoses.py`: `TOPIC_ORDER` | `competencies.py`의 키 순서에서 파생. SSOT 위반. |
| 3 | `app/report/page.tsx`: `SUB_COMPETENCIES` | 백엔드 API 응답에서 지표 목록을 받아 렌더링해야 함. 27개 지표 이름 복제는 유지보수 불가. |

### 중요 (이번 Phase에서 수정)

| 우선순위 | 대상 | 이유 |
|----------|------|------|
| 4 | `current_topic` 문자열 — `"General"`, `"Completed"` | Enum 또는 상수로 교체하여 오타 방지. |
| 5 | `llm_service.py` 발화 분류 프롬프트 — 역량 키/이름 | `COMPETENCY_FRAMEWORK`에서 동적 생성 |
| 6 | `app/chat/page.tsx`: `ALL_TOPICS`, `length === 5` | API로부터 역량 목록 수신 |

### 나중에 (Phase 2+)

| 우선순위 | 대상 | 이유 |
|----------|------|------|
| 7 | `llm_service.py` 분석 프롬프트 — STAR/BEI 방법론 | 역량 범위가 행동 역량에 한정된 동안은 긴급하지 않음 |
| 8 | `app/report/page.tsx`: `/ 5` 점수 스케일 | API 응답에 `max_score` 필드 추가로 해결 |
| 9 | `competency_indicator.py` DB 모델 활성화 | `data/competencies.py`를 DB에 시드하여 단일 관리 (큰 아키텍처 결정) |
| 10 | STAR/BEI → 방법론 플러그인화 | 역량 범위 확장 시 필요 |

---

## 추가 발견 사항 (감사 중 발견된 별도 이슈)

1. **`select-coach/page.tsx`의 UUID 매핑 오류**: 이 파일의 코치→페르소나 매핑 테이블이 `coaches.py` 라우터가 반환하는 UUID와 불일치. 예) Ella 코치 UUID: 이 파일 `...000010` vs `coaches.py` 반환 `...000011`. A-1에서 수정된 백엔드와 불일치 가능성 있음. **별도 확인 필요.**

2. **`services/analysis_service.py:90`의 `/5` 하드코딩**: 이 서비스 자체가 현재 dead code이나, 재활성화 시 4개 역량 진단에서도 5로 나누는 버그 발생.

3. **`competency_indicator.py` DB 모델과 `data/competencies.py` 데이터 동기화 없음**: DB 테이블이 존재하나 빈 상태. 역량 데이터는 코드에만 있어 DB 기반 검색·수정·버전 관리 불가.
