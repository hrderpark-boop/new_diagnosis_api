# Git Hygiene Plan
> Phase 1.2-A.5 산출물  
> 작성일: 2026-04-22  
> 목적: git init 후 add 누락된 86개 untracked 파일을 분류하고 안전하게 정리한다.

---

## 현황 요약

| 항목 | 수치 |
|------|------|
| Git 추적 중인 파일 | 13개 (Phase 1.1~1.2-A 작업분만) |
| Untracked 파일 | 86개 (프로젝트 전체 기존 코드) |
| 원격 저장소 | 없음 (GitHub push 이력 없음) |
| 원인 | git init 후 기존 파일을 한 번도 `git add`하지 않음 |

---

## ⚠️ 즉시 처리 필요 — 하드코딩된 API 키 발견

Step 1 조사 중 다음 파일에서 **API 키가 소스코드에 직접 하드코딩**된 것을 확인:

| 파일 | 키 (마지막 5자리) | 조치 |
|------|-------------------|------|
| `check_my_models.py:5` | `...4wNlo` | **커밋 금지 + 삭제** |
| `test_lite_model.py:6` | `...aRmj0` | **커밋 금지 + 삭제** |

→ Phase 1.1 A-3에서 `llm_service.py` 키는 제거했지만, 이 두 파일은 누락됨.  
→ 원격 저장소 없으므로 현재 외부 노출 없음. 그러나 절대 커밋하지 말 것.

---

## 그룹 A — 핵심 애플리케이션 코드 (git add 대상)

### A-1. 패키지 초기화 파일

| 파일 | 이유 |
|------|------|
| `diag_project/__init__.py` | Python 패키지 선언. 없으면 import 불가 |
| `diag_project/routes/__init__.py` | routes 패키지 선언 |
| `diag_project/schemas/__init__.py` | schemas 패키지 선언 |
| `diag_project/services/__init__.py` | services 패키지 선언 |
| `diag_project/data/__init__.py` | data 패키지 선언 |

### A-2. 핵심 인프라 (앱 구동에 필수)

| 파일 | 이유 |
|------|------|
| `diag_project/database.py` | SQLAlchemy 엔진·세션 팩토리. `get_db()` 의존성 |
| `diag_project/security.py` | `get_password_hash()` 등 인증 유틸. `seed.py`가 의존 |

### A-3. 데이터 레이어 (SSOT 포함)

| 파일 | 이유 |
|------|------|
| `diag_project/data/competencies.py` | **SSOT** — 5개 역량·27개 지표 원본. 절대 필수 |
| `diag_project/data/coaches_persona.py` | 6개 코치 페르소나 원본. `diagnoses.py`가 의존 |

### A-4. 모델 레이어

| 경로 | 이유 |
|------|------|
| `diag_project/models/` (전체) | SQLModel ORM 정의. DB 스키마의 원본 |

### A-5. 라우터 (기존 등록된 것)

| 파일 | 이유 |
|------|------|
| `diag_project/routes/participants.py` | `/api/v1/participants` 로그인·가입 |
| `diag_project/routes/coaches.py` | `/api/v1/coaches` 코치 목록 |
| `diag_project/routes/reports.py` | `/api/v1/reports` 결과 리포트 |
| `diag_project/routes/session.py` | 세션 관련 라우터 |
| `diag_project/routes/admin.py` | 어드민 라우터 |

> 나머지 `diag_project/routes/` 파일들(`competency.py`, `group.py` 등):  
> `main.py`에 현재 등록되어 있지 않으나 서비스 코드가 있으므로 add 대상.

### A-6. 스키마 (기존 파일들)

| 경로 | 이유 |
|------|------|
| `diag_project/schemas/base.py` | 공통 Base 스키마 |
| `diag_project/schemas/coach.py` | 코치 응답 스키마 |
| `diag_project/schemas/coach_persona.py` | 페르소나 스키마 |
| `diag_project/schemas/competency.py` | 역량 스키마 |
| `diag_project/schemas/diagnosis.py` | 진단 세션 스키마 |
| `diag_project/schemas/participant.py` | 참가자 스키마 |
| `diag_project/schemas/message.py` | 메시지 스키마 |
| `diag_project/schemas/session.py` | 세션 스키마 |
| `diag_project/schemas/` 나머지 전체 | 관련 엔티티 스키마 |

### A-7. 서비스 레이어

| 경로 | 이유 |
|------|------|
| `diag_project/services/analysis_service.py` | LLM 분석 파이프라인 (진단 결과 생성) |
| `diag_project/services/` 나머지 전체 | 각 도메인 비즈니스 로직 |

---

## 그룹 B — 인프라·설정 (git add 대상)

| 파일/경로 | 이유 |
|-----------|------|
| `alembic/` (전체) | DB 마이그레이션 히스토리. schema 변경 추적에 필수 |
| `alembic.ini` | Alembic 실행 설정 |
| `pyproject.toml` | 패키지 메타데이터·pytest 설정 |
| `run_tests.sh` | 테스트 실행 스크립트 (확인 필요 — 내용 미열람) |

---

## 그룹 C — 개발 유틸리티 (선별 add)

| 파일 | 용도 | 판정 |
|------|------|------|
| `seed.py` | SQLAlchemy 모델로 초기 데이터(코치·그룹·참가자) 삽입. 신규 개발환경 셋업에 필수 | **add** |
| `create_user.py` | sqlite3로 테스트 계정 직접 생성. 빠른 계정 추가 시 유용 | **add** |
| `reset_report.py` | `diagnosis_reports` 테이블 전체 초기화. 개발 중 리포트 재생성 시 사용 | **add** |
| `reset_db.py` | DB 파일 삭제 후 seed 재실행. 개발환경 완전 초기화 | **add** |

---

## 그룹 D — 삭제 권장

| 파일 | 삭제 이유 |
|------|-----------|
| `check_my_models.py` | **API 키 하드코딩** (`...4wNlo`). 커밋 불가. 기능도 일회성 |
| `test_lite_model.py` | **API 키 하드코딩** (`...aRmj0`). 커밋 불가. 기능도 일회성 |
| `test_key.py` | API 키를 stdout에 출력(`🔑 로드된 API 키: {api_key}`). 로그 유출 위험. 일회성 |
| `test_api_live.py` | pytest 미사용 일회성 Gemini 연결 테스트. `tests/`로 승격할 품질 아님 |
| `force_result_final.py` | 가짜 점수 데이터를 DB에 직접 삽입. 테스트용 일회성 핵 |
| `nuke_db.py` | `diagnosis.db` 파일 탐색·삭제. `sql_app.db`(현 DB명)와도 불일치 |
| `unlock.py` | 특정 세션 UUID 하드코딩(`cb2ebf50-...`). 일회성 운영 픽스 |
| `check_db.py` | DB 테이블 구조 출력. `sqlite3` CLI나 `where_is_db.py`로 대체 가능 |
| `check_keys.py` | GEMINI_API_KEY 파싱 디버그. 기능 정상화 후 불필요 |
| `where_is_db.py` | DB 파일 경로 추적. 개발 초기 디버그용. 현재 불필요 |
| `diag_project/check_gemini_models.py` | `diag_project/` 내부의 모델 목록 조회 스크립트. 소속 부적절 |

---

## 그룹 E — 이동 권장

| 파일 | 현재 위치 | 이동 대상 | 이유 |
|------|-----------|-----------|------|
| `tests/test_api.py` 외 8개 | `tests/` | `tests/` (그대로 add) | 이미 올바른 위치. pytest 구조 사용. 그냥 추적 시작 |

> `tests/__pycache__/`는 `.gitignore`에 이미 `__pycache__/` 패턴이 있어 자동 무시됨.

---

## 그룹 F — 확인 필요 (사용자 판단 요청)

| 파일/경로 | 확인 이유 |
|-----------|-----------|
| `__init__.py` (루트) | 내용 비어있음. 루트에 `__init__.py`가 필요한 이유 불명확. 삭제 무방한지? |
| `package.json` | `html2canvas`, `jspdf` 의존성. 백엔드 루트에 있는 이유는? 프론트엔드 프로젝트에 속해야 하지 않는지? 아니면 백엔드에서 PDF 생성 용도? |
| `coaches/` (이미지 6개) | 각 1.2~1.4MB PNG. `main.py`는 `images/` 디렉터리를 마운트하는데 실제 파일은 `coaches/`에 있음 → **디렉터리명 불일치 버그**. `coaches/`→`images/` 리네임 or `main.py` 수정 후 add? |
| `new_diagnosis_api.code-workspace` | VS Code 워크스페이스 파일. 팀 공유 목적이면 add, 개인 설정이면 `.gitignore`에 추가. |
| `run_tests.sh` | 내용 미확인. 확인 후 B or D 결정 |

---

## Step 3 실행 계획 (승인 후 진행)

```
커밋 1: chore: add core application source (groups A + B)
  → diag_project/ 전체, alembic/, pyproject.toml

커밋 2: chore: add dev utilities and test suite (groups C + E)
  → seed.py, create_user.py, reset_*.py, tests/

커밋 3: docs: commit framework API contract amendment
  → docs/FRAMEWORK_API_CONTRACT.md (7절 추가분)

삭제 (커밋 전): Group D 파일 10개 삭제 후 .gitignore 패턴 추가 검토
```

---

## 부수 발견 사항 (Phase 1.2-B 이후 처리 권장)

| 항목 | 내용 |
|------|------|
| 이미지 서빙 버그 | `main.py`가 `images/` 마운트하지만 실제 아바타는 `coaches/`에 존재 → 서버 로그 경고 원인 |
| 로그인 토큰 미저장 | `login/page.tsx:18` — axios 응답을 localStorage에 저장 안 함 |
