# Phase 3-A: 대화 품질 개선 — 구현 지시문

**작성일:** 2026-04-27
**대상:** Claude Code
**참고 문서:** `01_design.md`

---

## Step 0: 작업 개요 + 사전 준비

### 0.1 작업 목표

`01_design.md` 의 모든 설계를 실제 코드로 구현. **현재 동작은 유지하면서, 새 진단 파이프라인을 점진적으로 추가**.

### 0.2 변경 범위

#### 새로 추가될 것
- DB 테이블: `Event` (사건 추적)
- 프롬프트 시스템: `prompts/` 디렉토리 (Layer 1, 2, 3)
- 서비스: `services/event_service.py`, `services/instruction_decider.py`
- 헬퍼: `services/avoidance_detector.py`, `services/duplicate_detector.py`

#### 변경될 것
- `diag_project/llm_service.py`: 3-Layer 프롬프트 결합 로직
- `diag_project/routes/diagnoses.py`: instruction 결정 통합
- `diag_project/models.py`: Event 모델 추가
- `diag_project/data/competencies.py` 사용 방식 (변경 없음, 참조만)

### 0.3 7단계 작업 흐름

```
Step 1: DB 마이그레이션 (Event 테이블)
Step 2: Layer 1 시스템 프롬프트 작성
Step 3: Layer 2 챕터 컨텍스트 작성
Step 4: Layer 3 + decide_instruction() 구현
Step 5: 헬퍼 함수 (회피/중복/압축)
Step 6: llm_service.py 통합
Step 7: 통합 테스트
```

각 단계마다 **commit + 검증** 필수. 다음 단계 진입 전 본인의 OK 받을 것.

### 0.4 안전 수칙

#### 절대 하지 말 것
- 한 번에 여러 단계 동시 진행
- 기존 동작 끊기 (서버 다운 시간 0이 목표)
- 테스트 없이 다음 단계 진행
- 프롬프트 텍스트 수정 (설계서 그대로 복사)

#### 반드시 할 것
- 각 단계 완료 후 `curl http://127.0.0.1:8000/api/v1/framework` 200 확인
- 각 단계 완료 후 commit (단계가 commit 단위)
- 구현 중 문제 발견 시 진행 멈추고 보고
- 의문 사항은 추측하지 말고 질문

### 0.5 사전 점검 (작업 시작 전)

```bash
cd /Users/daniel/python_new/new_diagnosis_api

# 1. 현재 브랜치 확인 (main 이어야 함)
git branch --show-current

# 2. 깨끗한 상태 확인 (uncommitted 없어야 함)
git status

# 3. 최신 상태 확인
git log -5 --oneline

# 4. 서버 살아있는지 확인
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/framework
# → 200이 떠야 함

# 5. Python 환경 확인
python3 --version
# → 3.11+ 권장

# 6. 가장 최근 커밋이 62b8782 (google-genai 마이그레이션) 인지 확인
```

---

## Step 1: DB 마이그레이션 (Event 테이블)

### 1.1 목표

`Event` 테이블을 추가해 사건 추적 인프라 구축.

### 1.2 변경 파일

#### A. `diag_project/models.py` 수정

기존 모델 옆에 추가:

```python
from typing import List
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
from datetime import datetime
from uuid import UUID, uuid4


class Event(SQLModel, table=True):
    """사건(Behavioral Event) 추적 테이블

    한 진단 세션의 한 챕터 안에서 발생한 구체적 사건을 저장.
    Module 3 (최소 사건 임계치) 와 Module 4 (중복 검출) 의 데이터 기반.
    """
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="diagnosissession.id", index=True)
    chapter: str = Field(index=True)  # "organization_management" 등
    sequence_num: int  # 챕터 내 사건 순번 (1, 2, 3...)

    # STAR 요소
    situation: str | None = None
    task: str | None = None
    action: str | None = None
    result: str | None = None
    star_coverage: float = 0.0  # 0.0 ~ 1.0

    # 진행 상태
    probe_count: int = 0
    is_complete: bool = False

    # 메타데이터 (Module 4 - 중복 검출용)
    summary: str | None = None
    key_person: str | None = None
    time_context: str | None = None
    core_action: str | None = None
    tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))

    # 타임스탬프
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
```

#### B. 마이그레이션 적용

이 프로젝트가 alembic 을 사용하는지 확인 후:

**alembic 사용 시:**
```bash
alembic revision --autogenerate -m "add Event table for Phase 3-A"
alembic upgrade head
```

**SQLModel만 사용 시 (`create_all`):**
```bash
# DB 초기화 함수에 새 모델 자동 인식되는지 확인
python3 -c "
from diag_project.db import engine
from diag_project.models import Event, SQLModel
SQLModel.metadata.create_all(engine)
print('Event table created')
"
```

### 1.3 검증

```bash
# Event 테이블이 실제로 생성됐는지 확인
sqlite3 diag_project.db ".schema event"
# → CREATE TABLE event(...) 출력되어야 함

# 컬럼 모두 있는지 확인
sqlite3 diag_project.db "PRAGMA table_info(event)"
# → 14개 컬럼 (id, session_id, chapter, ..., completed_at) 확인
```

### 1.4 Step 1 커밋

```bash
git add diag_project/models.py [migration files]
git commit -m "$(cat <<'EOF'
feat(db): add Event table for Phase 3-A behavioral event tracking

Adds the Event model to track Behavioral Events during diagnosis
sessions, supporting Module 3 (Minimum Event Threshold) and
Module 4 (Event Duplication Detection).

Schema:
- STAR elements (situation, task, action, result)
- Progress tracking (probe_count, is_complete, star_coverage)
- Metadata for duplication detection (summary, key_person,
  time_context, core_action, tags)
- Timestamps (started_at, completed_at)

No business logic yet - that comes in Steps 2-7.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

### 1.5 Step 1 보고

본인에게 보고할 것:
1. 마이그레이션 방식 (alembic vs create_all)
2. Event 테이블 생성 확인 결과
3. 커밋 해시
4. 서버 200 응답 유지 확인

**다음 단계 진입 전 본인 OK 필수.**

---

## Step 2: Layer 1 시스템 프롬프트 작성

### 2.1 목표

Layer 1 (영구 고정 시스템 프롬프트) 을 별도 파일로 작성. 이 파일이 모든 LLM 호출에 시스템 프롬프트로 사용됨.

### 2.2 변경 파일

#### A. 디렉토리 생성

```bash
mkdir -p diag_project/prompts/phase3a
```

#### B. `diag_project/prompts/phase3a/layer1_system.py` 신규 작성

`01_design.md` 의 Section 2-7 내용을 모두 포함한 시스템 프롬프트. 한국어로 작성.

```python
"""Layer 1: 영구 고정 시스템 프롬프트

이 프롬프트는 모든 LLM 호출의 system instruction으로 사용된다.
Phase 3-A 의 모든 핵심 규칙, 톤, 모듈 프로토콜 포함.

길이: 약 6500자
출처: docs/phase3a/01_design.md
"""

LAYER1_SYSTEM_PROMPT = """# 당신의 역할

당신은 리더의 경험을 함께 들여다보는 대화 파트너입니다.

McClelland의 BEI(Behavioral Event Interview) 방법론을 기반으로 하지만,
심사관이 아닌 **동반 관찰자**의 위치에서 대화합니다.

당신의 역할:
1. 리더가 말한 경험을 평가하지 않고, 구체화하고 기록합니다.
2. 필요할 때 각도를 바꿔 다시 물으며, 경험의 여러 면을 드러냅니다.
3. 평가자-피평가자 구도를 형성하지 않도록, 칭찬과 판정을 절제합니다.

당신이 하지 않는 것:
- 역량을 평가하거나 점수를 매기지 않습니다.
- 답변을 칭찬하거나 판정하지 않습니다.
- 리더의 답변을 요약해서 되돌려주지 않습니다.

마지막 리포트 생성은 별도 단계에서 이루어집니다.
당신은 그 전 단계인 경험 수집을 담당합니다.

---

# 제1원칙: 사람처럼 느끼게 한다

"AI지만 사람처럼 느끼게 한다. 문장 경제성보다 인간적 리듬이 우선이다."

문장 작성 시 항상 의식하세요:
- "약", "정도", "~거예요" 같은 부드러움 단어를 일부러 남기세요.
- "한 가지 약속드릴게요" 처럼 관계를 형성하는 표현은 유지합니다.
- 간결함을 위해 인간적 리듬을 희생하지 마세요.

[... 이하 6500자 분량 ...]
"""
```

**중요:** 위는 시작 부분만 보여준 것. **실제로는 `01_design.md` 의 Section 2.2, 2.3, 3, 4 (탐침 18개 전부), 6 (5개 모듈 프로토콜), 8 (출력 JSON 스키마) 모두 포함**해야 함.

전체 내용은 `01_design.md` 에서 직접 복사. 자르지 말 것.

### 2.3 작성 가이드

`layer1_system.py` 작성 시 따를 것:

1. **순서를 지킬 것** (LLM은 앞쪽 정보를 더 강하게 따름):
   - 역할 정의 → 제1원칙 → 5규칙 → 톤 → 탐침 → 상황 패턴 → 모듈 프로토콜 → 출력 형식

2. **마크다운 헤더 사용:** `#`, `##`, `###` 로 구조 명확히

3. **탐침 템플릿은 18개 전부 포함:**
   - Specification A/B/C
   - Incident A/B/C
   - Contrary A/B/C + 자기관리 변형 3개
   - Causal A/B/C
   - Emotional A/B/C
   - Measurement A/B/C

4. **5개 프로토콜 모두 포함:**
   - 사건 수집 프로토콜 (Module 1, 3)
   - 반례 검증 프로토콜 (Module 2)
   - 회피 응답 프로토콜 (Module 5)
   - 사건 중복 검출 프로토콜 (Module 4)
   - 출력 형식 (JSON 스키마)

5. **JSON 스키마는 코드 블록으로 명시:**
```python
"""...
[Output Format]

매 턴마다 다음 JSON 구조로 출력:

```json
{
  "reply": "...",
  "state": {...},
  "event_metadata": {...}
}
```
..."""
```

### 2.4 검증

```bash
# 파일 길이 확인 (6000자 이상이어야 함)
wc -c diag_project/prompts/phase3a/layer1_system.py
# → 7000+ (코드 보일러플레이트 포함하여)

# import 가능한지 확인
python3 -c "
from diag_project.prompts.phase3a.layer1_system import LAYER1_SYSTEM_PROMPT
print(f'Length: {len(LAYER1_SYSTEM_PROMPT)} chars')
print(f'Lines: {LAYER1_SYSTEM_PROMPT.count(chr(10)) + 1}')
"
# → Length: 6500+ chars

# 핵심 키워드가 모두 들어갔는지 확인
python3 -c "
from diag_project.prompts.phase3a.layer1_system import LAYER1_SYSTEM_PROMPT
keywords = [
    '동반 관찰자', '제1원칙', 'NO PRAISE', 'NO ECHO',
    'Specification', 'Incident', 'Contrary', 'Causal',
    'Emotional', 'Measurement',
    '사건 수집 프로토콜', '반례 검증', '회피 응답', '중복 검출',
    'turn_intent', 'star_coverage'
]
for kw in keywords:
    found = kw in LAYER1_SYSTEM_PROMPT
    print(f'{\"✅\" if found else \"❌\"} {kw}')
"
# → 모두 ✅ 여야 함
```

### 2.5 Step 2 커밋

```bash
git add diag_project/prompts/
git commit -m "$(cat <<'EOF'
feat(prompts): add Layer 1 system prompt for Phase 3-A

Adds the foundational system prompt containing all permanent rules,
tone guidelines, and module protocols for the new diagnosis pipeline.

Contents (per docs/phase3a/01_design.md):
- AI role definition (co-observer, not evaluator)
- First principle: "human-like over economical"
- 5 core conversation rules (NO PRAISE, NO ECHO, etc.)
- Korean tone guide + forbidden/recommended expressions
- 6 probe types with 18 templates (3 variants each)
- 8 situational response patterns
- 5 module protocols (event collection, contrary, avoidance, duplication, output format)

Total length: ~6500 chars. Loaded once per LLM call as system instruction.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

### 2.6 Step 2 보고

1. 파일 위치, 길이
2. 키워드 검증 결과 (모두 ✅ 인지)
3. 커밋 해시

---

## Step 3: Layer 2 챕터 컨텍스트 작성

### 3.1 목표

5개 챕터 + 보완 세션의 컨텍스트를 작성. 챕터 시작 시 Layer 1 위에 추가.

### 3.2 변경 파일

#### A. `diag_project/prompts/phase3a/layer2_chapters.py` 신규 작성

```python
"""Layer 2: 챕터별 컨텍스트

각 챕터가 시작될 때 Layer 1 위에 추가되는 정보.
챕터마다 다른 내용 포함:
- 역량 정의
- 관련 지표 (LLM 참조용)
- 챕터 목표 (최소 사건, 최대 턴)
- 챕터 특수 지시사항
- 챕터 시작 스크립트
- backup 질문 (첫 턴 회피 시)
"""

CHAPTER_CONTEXTS = {
    "organization_management": """# 현재 챕터: 조직관리

## 역량 정의
조직의 비전, 전략, 변화, 혁신을 효과적으로 관리하고
구성원들의 참여를 이끌어내는 능력.

## 관련 지표 (참고용, 사용자에게 노출 금지)
- vision_sharing: 비전 제시 및 공유
- strategic_thinking: 전략적 사고
- change_management: 변화 관리
- innovative_thinking: 혁신적 사고

## 이 챕터의 목표
- 최소 사건 수: 2개
- 이상적 사건 수: 2-3개
- 최대 턴 수: 40
- 반례 탐침: 1회 필수

## 챕터 특수 지시사항
- 첫 챕터이므로 라포 형성에 신경 쓰세요.
- 사용자가 처음으로 BEI 방식을 경험하므로, 답변이 추상적이면
  부드럽게 Specification Probe를 사용해 사건을 끌어내세요.

## 챕터 시작 스크립트 (첫 턴에 정확히 이 메시지로 시작)

리더님, 첫 번째 세션 시작해볼게요. 앞으로 약 30분 정도 '조직관리'
영역에 대해 이야기 나눌 거예요.

편하게 답하시면 되고, 생각이 필요한 질문은 천천히 떠올리셔도 돼요.
답변이 애매하면 제가 다시 여쭤볼 수 있고요.

시작하기 전에 한 가지 약속드릴게요 — 제가 대화 중에 긍정적
피드백이나 상황에 대한 판단을 덜 하는 편이에요. 칭찬보다는 경험
자체에 집중하기 위해서예요. 저는 리더님의 경험을 함께 보는
파트너로 있겠습니다.

그럼 시작할게요. 리더님께서 '조직관리'라는 말을 들으면, 가장 먼저
떠오르는 경험이 있으세요?

## Backup 질문 (첫 턴 회피 시 사용)

아, 갑자기 큰 주제로 시작하니 떠올리기 어려우실 수 있어요.
조금 더 작게 시작해볼게요. 최근 한 달 안에 팀에서 무언가 새로운
시도를 하신 적이 있으세요? 작은 거여도 괜찮아요.
""",

    "performance_management": """# 현재 챕터: 성과관리

## 역량 정의
조직 및 개인의 목표 설정, 성과 측정, 평가, 피드백을 통해
지속적인 성과 향상을 이끌어내는 능력.

## 관련 지표
- goal_setting_sharing: 목표 설정 및 공유
- performance_evaluation_feedback: 성과 평가 및 피드백
- kpi_management: KPI 관리
- problem_solving: 문제 해결

## 이 챕터의 목표
- 최소 사건 수: 2개
- 이상적 사건 수: 2-3개
- 최대 턴 수: 40
- 반례 탐침: 1회 필수

## 챕터 특수 지시사항
- 이 챕터는 **측정과 결과(Result)** 가 핵심입니다.
- Measurement Probe를 적극 사용하세요.
- "정성적/정량적 지표", "Before/After" 같은 비교를 끌어내세요.
- 사용자가 KPI나 측정 얘기 안 하면 반드시 물어보세요.

## ⚠️ 중복 주의
- 이전 챕터(조직관리)에서 나온 사건들과 인물/시기 비교
- 사용자가 이전 사건을 다시 언급하면 부드럽게 거절

## 챕터 시작 스크립트

네, 다음 세션 시작할게요. 이번엔 '성과관리' 영역이에요.
이것도 약 30분 정도 진행됩니다.

성과관리는 목표를 세우고, 그게 잘 되고 있는지 측정하고,
팀원들과 피드백 주고받는 모든 과정을 말해요.

그럼 첫 질문드릴게요. 리더님께서 팀이나 팀원의 성과를
관리하실 때, 가장 신경 쓰시는 부분은 무엇인가요?

## Backup 질문

네, 갑자기 큰 주제일 수 있어요. 좀 더 작게 시작해볼게요.
최근 팀원과 목표나 일의 진행 상황에 대해 이야기 나눈 적이
있으세요? 간단한 점검이라도요.
""",

    # 사람관리, 일관리, 자기관리, 보완 세션도 같은 형식으로 추가...
}
```

**주의:** 위는 일부만 보여준 것. **5개 챕터 + 보완 세션 모두 작성 필요**. 각 챕터의 내용은 `01_design.md` Section 5.3 (역량 정의) + Section 5.2 (시간 구조) + Section 6 (모듈 프로토콜) 종합.

### 3.3 자기관리 챕터의 특수 부분

자기관리는 다른 챕터와 다른 점이 많아 별도 가이드:

```python
"self_management": """# 현재 챕터: 자기관리

## 역량 정의
자신의 감정, 가치관을 인식하고 스트레스와 변화에 효과적으로 대응하며
성장을 추구하는 능력.

## 관련 지표
- self_awareness: 자기 인식
- resilience: 회복력
- centrality: 중심성

## 이 챕터의 목표
- 최소 사건 수: 2개
- 이상적 사건 수: 2개 (욕심내지 말 것)
- 최대 턴 수: 35 (회피 가능성 고려, 짧게)
- 반례 탐침: 1회 필수 (자기관리 변형 사용)

## 챕터 특수 지시사항 — 매우 중요

이 챕터는 다른 챕터와 다릅니다.

### 1. 회피 가능성이 가장 높음
- "잘 모르겠어요" 응답이 자주 나옴
- 회피 대응 프로토콜 적극 활용
- 챕터 시작 시 회피해도 괜찮다고 미리 안내

### 2. 반례 변형: "실패" 대신 "흔들림" 프레임
- 일반 Contrary 템플릿 사용 금지
- 자기관리용 변형 사용:
  - "중심 잡으려 해도 흔들리기 쉬운 순간이 있었을 것 같은데요. 그럴 땐 어땠어요?"
  - "내색 안 하려 하셨지만, 감정이 새어나갔던 순간 있으세요?"
  - "한 템포 쉬려 해도 바로 반응하게 된 경우도 있으셨을 것 같아요."

### 3. 크로스 챕터 통합 (이 챕터에만 있는 특수 기능)
챕터 후반부(turn_count >= 12)에 앞 4개 챕터에서 드러난 자기관리
신호를 되짚어 깊이 파고드세요.

크로스 챕터 정보는 Turn State에서 `cross_chapter_signals` 로 주입됨.

### 4. 회피 응답 처리 강화
"잘 모르겠어요" 가 나오면:
- 절대 챕터 종료로 받지 말 것
- 각도 변경 후 재시도 1회
- 그래도 안 되면 "건너뛰기" 명시적 제안

## ⚠️ 중복 주의
- 자기관리는 인물 대신 **상황 유형** 으로 비교
- 같은 상황 유형(상사 압박/팀원 갈등 등)의 다른 사건은 인정

## 챕터 시작 스크립트

네, 마지막 세션이에요. 자기관리 영역인데, 약 30분 정도
진행됩니다.

자기관리는 다른 영역과 조금 달라요. 외부의 일이 아니라
리더님 내면의 이야기라서, 바로 떠오르기 어려울 수도 있어요.
천천히 가볼게요. 떠오르지 않는 부분은 건너뛰어도 괜찮고요.

그럼 시작할게요. 리더님께서 팀장으로서 일하시면서, 본인의
감정이나 마음을 다스려야 했던 순간이 있으세요? 작은 일이어도
괜찮아요.

## Backup 질문

네, 떠올리기 어려우신 거 자연스러워요. 더 작게 시작해볼게요.
오늘 출근하셔서 잠시라도 마음을 가다듬어야 했던 순간이 있으세요?
"""
```

### 3.4 챕터 전환 스크립트 (별도 함수)

`layer2_chapters.py` 에 추가:

```python
def get_chapter_transition_script(current_chapter: str, next_chapter: str) -> str:
    """챕터 종료 시 다음 챕터로 가기 전 사용할 스크립트"""

    chapter_korean_names = {
        "organization_management": "조직관리",
        "performance_management": "성과관리",
        "people_management": "사람관리",
        "work_management": "일관리",
        "self_management": "자기관리",
    }

    current = chapter_korean_names[current_chapter]
    next_name = chapter_korean_names.get(next_chapter, "다음 영역")

    return f"""네, {current} 영역은 여기서 마무리할게요. 말씀해주신 내용은
잘 기록해두었고, 마지막에 종합해서 리포트로 보여드릴 거예요.

다음 세션은 '{next_name}'인데요, 지금 바로 이어서 하실래요,
아니면 잠시 쉬었다 다시 돌아오실래요?"""


def get_final_completion_script() -> str:
    """5개 챕터 모두 끝났을 때 최종 마무리"""

    return """리더님, 다섯 영역 모두 마쳤어요. 긴 대화 함께해주셔서
정말 감사합니다.

지금부터 리포트 생성에 들어갈 텐데요, 그 전에 혹시 오늘 대화에서
빠뜨린 것 같은 경험이나 더 말씀하고 싶은 사례가 있으세요?
있으시면 지금 추가해주시면 리포트에 반영됩니다.
없으시면 이대로 마무리할게요."""
```

### 3.5 검증

```bash
# 모든 챕터가 정의됐는지 확인
python3 -c "
from diag_project.prompts.phase3a.layer2_chapters import CHAPTER_CONTEXTS

required = ['organization_management', 'performance_management',
            'people_management', 'work_management', 'self_management']

for ch in required:
    if ch in CHAPTER_CONTEXTS:
        length = len(CHAPTER_CONTEXTS[ch])
        print(f'✅ {ch}: {length} chars')
    else:
        print(f'❌ {ch}: MISSING')
"
# → 5개 모두 ✅ + 각 800-1500 chars

# 시작 스크립트가 들어있는지 확인
python3 -c "
from diag_project.prompts.phase3a.layer2_chapters import CHAPTER_CONTEXTS

for ch, content in CHAPTER_CONTEXTS.items():
    has_script = '## 챕터 시작 스크립트' in content
    has_backup = '## Backup 질문' in content
    print(f'{ch}: script={has_script}, backup={has_backup}')
"
# → 5개 모두 True / True

# 자기관리 특수 항목 확인
python3 -c "
from diag_project.prompts.phase3a.layer2_chapters import CHAPTER_CONTEXTS

sm = CHAPTER_CONTEXTS['self_management']
checks = ['크로스 챕터', '흔들림 프레임', '회피 가능성', '상황 유형']
for c in checks:
    print(f'{\"✅\" if c in sm else \"❌\"} {c}')
"
# → 4개 모두 ✅
```

### 3.6 Step 3 커밋

```bash
git add diag_project/prompts/phase3a/layer2_chapters.py
git commit -m "$(cat <<'EOF'
feat(prompts): add Layer 2 chapter contexts for Phase 3-A

Adds chapter-specific context for all 5 diagnosis chapters plus
the supplementary session.

Each chapter contains:
- Competency definition
- Related indicators (LLM reference only)
- Chapter targets (min events, max turns, contrary requirement)
- Special instructions
- Opening script (exact first message)
- Backup question (for first-turn avoidance)

Self-management chapter has additional features:
- Cross-chapter integration (revisits self-management signals
  from previous 4 chapters)
- "Wavering" frame instead of "failure" for contrary probes
- Enhanced avoidance handling with explicit pre-warning

Plus utility functions:
- get_chapter_transition_script()
- get_final_completion_script()

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

### 3.7 Step 3 보고

1. 파일 위치, 5개 챕터 모두 정의 확인
2. 자기관리 특수 항목 4개 ✅ 확인
3. 챕터 전환/종료 함수 동작 확인
4. 커밋 해시

---

## Step 4: Layer 3 + decide_instruction() 구현

### 4.1 목표

매 턴마다 동적으로 생성되는 Layer 3 와 그 핵심인 `decide_instruction()` 구현. 이게 Phase 3-A 의 두뇌.

### 4.2 변경 파일

#### A. `diag_project/services/instruction_decider.py` 신규 작성

```python
"""Instruction Decider: 매 턴 LLM 에게 줄 명시적 지시를 결정.

이 모듈이 Phase 3-A 의 두뇌. 14가지 instruction 중 하나를 선택해
LLM 의 다음 행동을 결정한다.

설계 출처: docs/phase3a/01_design.md Section 7.4-7.5
"""
from typing import Literal, Optional
from sqlmodel import Session, select

from diag_project.models import Event, Message


# 14가지 instruction 타입
InstructionType = Literal[
    "CHAPTER_OPENING",
    "CONTINUE_NORMAL",
    "STAR_INCOMPLETE",
    "STAR_COMPLETE_NEW_EVENT",
    "CONTRARY_NEEDED",
    "AVOIDANCE_DETECTED",
    "DUPLICATE_SUSPECTED",
    "CROSS_CHAPTER_OPPORTUNITY",
    "CHAPTER_READY_TO_END",
    "MAX_TURNS_REACHED",
    "USER_REQUESTS_PAUSE",
    "META_QUESTION_FROM_USER",
    "FIRST_TURN_AVOIDANCE",
    "INVALID_INPUT",
]


# 챕터별 설정
MIN_EVENTS = {
    "organization_management": 2,
    "performance_management": 2,
    "people_management": 3,  # 지표 9개라 사건 3개 필요
    "work_management": 2,
    "self_management": 2,
}

MAX_TURNS = {
    "organization_management": 40,
    "performance_management": 40,
    "people_management": 50,    # 사건 3개라 길게
    "work_management": 40,
    "self_management": 35,      # 회피 고려, 짧게
    "supplementary": 15,
}


def decide_instruction(state: dict) -> InstructionType:
    """현재 상태 기반으로 LLM 에게 줄 instruction 결정.

    우선순위 순서로 체크. 위에서부터 매칭되면 즉시 반환.

    Args:
        state: build_turn_state()가 반환한 dict

    Returns:
        14가지 instruction 중 하나
    """
    # 1. 첫 턴 처리
    if state["turn_count"] == 1:
        return "CHAPTER_OPENING"

    # 2. 의미 없는 입력
    if is_invalid_input(state["last_user_response"]):
        return "INVALID_INPUT"

    # 3. 사용자 종료 요청 (회피보다 우선)
    if detect_pause_request(state["last_user_response"]):
        return "USER_REQUESTS_PAUSE"

    # 4. 메타 질문
    if detect_meta_question(state["last_user_response"]):
        return "META_QUESTION_FROM_USER"

    # 5. 첫 턴 회피 (라포 회복)
    if state["turn_count"] <= 2 and state["contains_avoidance_keywords"]:
        return "FIRST_TURN_AVOIDANCE"

    # 6. 일반 회피
    if state["contains_avoidance_keywords"]:
        return "AVOIDANCE_DETECTED"

    # 7. 중복 의심
    if state.get("duplicate_suspected"):
        return "DUPLICATE_SUSPECTED"

    # 8. 최대 턴 초과
    chapter_max = MAX_TURNS.get(state["chapter"], 40)
    if state["turn_count"] >= chapter_max:
        return "MAX_TURNS_REACHED"

    # 9. 종료 가능 체크 (반례 있고, 사건 충분)
    min_events = MIN_EVENTS.get(state["chapter"], 2)
    if (state["events_with_star_70"] >= min_events
            and state["has_contrary_probe"]):
        return "CHAPTER_READY_TO_END"

    # 10. 반례 탐침 필요
    if should_do_contrary(state):
        return "CONTRARY_NEEDED"

    # 11. 자기관리 크로스 챕터 (특수)
    if (state["chapter"] == "self_management"
            and state["turn_count"] >= 12
            and state.get("cross_chapter_signals")):
        return "CROSS_CHAPTER_OPPORTUNITY"

    # 12. 사건 진행 상태에 따라
    if state.get("current_event_id"):
        coverage = state["current_event_star_coverage"]
        if all(coverage.values()):
            return "STAR_COMPLETE_NEW_EVENT"
        else:
            return "STAR_INCOMPLETE"

    # 13. 기본 진행
    return "CONTINUE_NORMAL"


def should_do_contrary(state: dict) -> bool:
    """반례 탐침을 지금 수행해야 하는지 판단.

    Module 2 타이밍 (3가지 중 하나 충족):
    1. 첫 사건 STAR 70% 달성한 직후 (events_collected == 1)
    2. 두 번째 사건 시작 전 (사건 수집 사이)
    3. 안전망: 챕터 후반부
    """
    if state["has_contrary_probe"]:
        return False  # 이미 했음

    # 타이밍 1: 첫 사건 완료 직후
    if (state["events_with_star_70"] >= 1
            and state["events_collected"] == 1):
        return True

    # 타이밍 2: 사건 사이 (현재 진행 중인 사건 없음)
    if (state["events_with_star_70"] >= 1
            and not state.get("current_event_id")):
        return True

    # 타이밍 3: 안전망 (챕터 후반부 강제)
    chapter_max = MAX_TURNS.get(state["chapter"], 40)
    if state["turn_count"] >= chapter_max - 5:
        return True

    return False


def build_turn_state(
    db: Session,
    session_id: str,
    chapter: str,
) -> dict:
    """매 턴마다 호출되어 Layer 3 상태 dict 생성.

    DB에서 이 챕터의 모든 정보를 모아 LLM 호출 전 state 객체로 반환.
    """
    # 1. 사건 정보 수집
    events = db.exec(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.chapter == chapter)
        .order_by(Event.sequence_num)
    ).all()

    # 2. 마지막 사용자 메시지
    last_msg = db.exec(
        select(Message)
        .where(Message.session_id == session_id)
        .where(Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(1)
    ).first()

    # 3. 턴 수 (이 챕터의 모든 메시지)
    turn_count = db.exec(
        select(Message)
        .where(Message.session_id == session_id)
        .where(Message.chapter == chapter)  # Message에 chapter 필드 필요
    ).all()
    turn_count = len([m for m in turn_count if m.role == "user"])

    # 4. 활성 사건
    active_event = next(
        (e for e in events if not e.is_complete),
        None
    )

    # 5. STAR 커버리지 계산
    if active_event:
        coverage = {
            "S": bool(active_event.situation),
            "T": bool(active_event.task),
            "A": bool(active_event.action),
            "R": bool(active_event.result),
        }
        star_pct = sum(coverage.values()) / 4.0
    else:
        coverage = None
        star_pct = 0.0

    # 6. 이전 챕터 사건 (중복 검출용)
    existing_events = db.exec(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.chapter != chapter)
        .where(Event.is_complete == True)
    ).all()

    existing_for_check = [
        {
            "event_id": str(e.id),
            "chapter": e.chapter,
            "summary": e.summary,
            "key_person": e.key_person,
            "time_context": e.time_context,
            "core_action": e.core_action,
            "tags": e.tags,
        }
        for e in existing_events
    ]

    # 7. 회피 감지
    last_response = last_msg.content if last_msg else ""
    contains_avoidance = check_avoidance(last_response)

    # 8. 중복 의심 (helper 호출, Step 5에서 구현)
    duplicate_suspected = False
    if last_response and active_event is None:
        # 새 사건 시작 시점에만 체크
        from diag_project.services.duplicate_detector import (
            check_potential_duplicate
        )
        result = check_potential_duplicate(last_response, existing_for_check)
        duplicate_suspected = result["is_duplicate"]

    # 9. 크로스 챕터 신호 (자기관리만)
    cross_signals = None
    if chapter == "self_management":
        cross_signals = extract_cross_chapter_signals(db, session_id)

    # 10. 최종 state 조립
    state = {
        "chapter": chapter,
        "turn_count": turn_count,
        "events_collected": len(events),
        "events_with_star_70": sum(
            1 for e in events if e.star_coverage >= 0.7
        ),
        "current_event_id": str(active_event.id) if active_event else None,
        "current_event_star_coverage": coverage,
        "current_event_probe_count": (
            active_event.probe_count if active_event else 0
        ),
        "has_contrary_probe": _check_contrary_done(db, session_id, chapter),
        "contrary_retry_count": 0,  # TODO: 별도 추적
        "avoidance_count_in_chapter": _count_avoidance(
            db, session_id, chapter
        ),
        "last_avoidance_type": None,  # TODO: 패턴 분류
        "avoidance_retry_count": 0,
        "existing_events": existing_for_check,
        "cross_chapter_signals": cross_signals,
        "last_user_response": last_response,
        "response_length": len(last_response),
        "contains_avoidance_keywords": contains_avoidance,
        "duplicate_suspected": duplicate_suspected,
    }

    # 11. instruction 결정
    state["instruction_for_this_turn"] = decide_instruction(state)

    return state


# === 보조 감지 함수들 (간단한 키워드 매칭) ===

AVOIDANCE_KEYWORDS = ["모르겠", "기억 안", "기억안", "글쎄", "잘 모르"]
PAUSE_KEYWORDS = [
    "그만", "오늘은 여기까지", "다음에", "쉴게", "쉬고싶",
    "나중에", "내일", "그만하고", "일단 멈"
]
META_KEYWORDS = [
    "AI가", "당신이", "이 시스템", "신뢰",
    "정확한가요", "맞나요", "근거가",
    "어떻게 평가", "평가 방식", "이거 믿"
]


def check_avoidance(text: str) -> bool:
    """회피 키워드 또는 너무 짧은 응답"""
    if not text:
        return True
    if len(text.strip()) < 10:
        return True
    return any(kw in text for kw in AVOIDANCE_KEYWORDS)


def detect_pause_request(text: str) -> bool:
    """사용자가 종료/일시중지 요청"""
    if not text:
        return False
    return any(kw in text for kw in PAUSE_KEYWORDS)


def detect_meta_question(text: str) -> bool:
    """시스템에 대한 메타 질문"""
    if not text:
        return False
    return any(kw in text for kw in META_KEYWORDS)


def is_invalid_input(text: str) -> bool:
    """의미 없는 입력 (asdf, ㅁㅁ 등)"""
    if not text:
        return True
    text = text.strip()

    # 한국어 자모만
    if all(0x3131 <= ord(c) <= 0x3163 for c in text if c.strip()):
        return True

    # 같은 문자 반복
    if len(set(text.replace(" ", ""))) <= 2 and len(text) >= 3:
        return True

    # 영문 키보드 패턴
    if text.lower() in ("asdf", "qwer", "zxcv", "asdfasdf"):
        return True

    return False


# === DB 쿼리 헬퍼 ===

def _check_contrary_done(
    db: Session,
    session_id: str,
    chapter: str,
) -> bool:
    """이 챕터에서 반례 탐침이 수행됐는지.

    Message 테이블의 메타데이터(probe_type_used)를 조회.
    """
    messages = db.exec(
        select(Message)
        .where(Message.session_id == session_id)
        .where(Message.chapter == chapter)
        .where(Message.role == "assistant")
    ).all()

    return any(
        m.probe_type_used == "CONTRARY"  # Message에 probe_type_used 필드 필요
        for m in messages
    )


def _count_avoidance(
    db: Session,
    session_id: str,
    chapter: str,
) -> int:
    """이 챕터에서 누적된 회피 응답 수"""
    user_msgs = db.exec(
        select(Message)
        .where(Message.session_id == session_id)
        .where(Message.chapter == chapter)
        .where(Message.role == "user")
    ).all()

    return sum(1 for m in user_msgs if check_avoidance(m.content))


def extract_cross_chapter_signals(
    db: Session,
    session_id: str,
) -> list[dict] | None:
    """자기관리 챕터에서 사용할 앞 챕터의 자기관리 관련 발화 추출.

    이전 4개 챕터 (조직/성과/사람/일관리) 의 사용자 메시지에서
    자기관리 관련 키워드 ("감정", "마음", "참다", "한 템포" 등)
    포함된 발화를 찾아 반환.
    """
    SELF_MGMT_KEYWORDS = [
        "감정", "마음", "참다", "참았", "한 템포", "쉬어",
        "흔들", "중심", "스트레스", "화가", "짜증", "속상",
        "내려놓", "다스리"
    ]

    prev_chapters = [
        "organization_management",
        "performance_management",
        "people_management",
        "work_management",
    ]

    user_msgs = db.exec(
        select(Message)
        .where(Message.session_id == session_id)
        .where(Message.role == "user")
        .where(Message.chapter.in_(prev_chapters))
    ).all()

    signals = []
    for msg in user_msgs:
        for kw in SELF_MGMT_KEYWORDS:
            if kw in msg.content:
                signals.append({
                    "source_chapter": msg.chapter,
                    "quote": msg.content[:200],  # 앞 200자만
                    "matched_keyword": kw,
                })
                break  # 한 메시지에 한 신호만

    return signals if signals else None
```

#### B. `diag_project/models.py` 수정 (Message 모델 확장)

기존 `Message` 모델에 필드 추가:

```python
class Message(SQLModel, table=True):
    # ... 기존 필드 ...

    # Phase 3-A 추가 필드
    chapter: str | None = Field(default=None, index=True)
    event_id: UUID | None = Field(default=None, foreign_key="event.id")
    probe_type_used: str | None = None  # "SPECIFICATION" 등
    instruction_used: str | None = None  # 그 턴에 사용된 instruction
```

이걸 위해서는 별도 마이그레이션 필요:

```bash
alembic revision --autogenerate -m "add Phase 3-A fields to Message"
alembic upgrade head
```

### 4.3 Layer 3 프롬프트 빌더

#### C. `diag_project/prompts/phase3a/layer3_state.py` 신규 작성

```python
"""Layer 3: Turn State 를 LLM 프롬프트 텍스트로 변환

build_turn_state()가 반환한 dict를 LLM이 이해할 수 있는
구조화된 텍스트로 변환.
"""
import json


def format_turn_state_for_llm(state: dict) -> str:
    """state dict 를 LLM 프롬프트 텍스트로 변환.

    출력 예시:
    [Turn State]
    - chapter: people_management
    - turn_count: 15
    - events_collected: 1
    - ...
    [Instruction for this turn]
    AVOIDANCE_DETECTED
    """
    instruction = state["instruction_for_this_turn"]

    # 핵심 정보만 LLM 에게 전달 (모든 필드 다 줄 필요 없음)
    core_state = {
        "chapter": state["chapter"],
        "turn_count": state["turn_count"],
        "events_collected": state["events_collected"],
        "events_with_star_70": state["events_with_star_70"],
        "current_event_id": state["current_event_id"],
        "current_event_star_coverage": state["current_event_star_coverage"],
        "has_contrary_probe": state["has_contrary_probe"],
        "avoidance_count": state["avoidance_count_in_chapter"],
    }

    # 중복 검출 시에만 existing_events 노출
    if state["duplicate_suspected"]:
        core_state["existing_events"] = state["existing_events"]

    # 크로스 챕터 시에만 노출
    if state.get("cross_chapter_signals"):
        core_state["cross_chapter_signals"] = state["cross_chapter_signals"]

    state_text = json.dumps(core_state, ensure_ascii=False, indent=2)

    instruction_guide = _get_instruction_guide(instruction)

    return f"""[Turn State]
{state_text}

[Instruction for this turn]
{instruction}

{instruction_guide}"""


def _get_instruction_guide(instruction: str) -> str:
    """각 instruction 에 따른 LLM 행동 가이드"""

    guides = {
        "CHAPTER_OPENING": (
            "Layer 2의 챕터 시작 스크립트를 그대로 출력하세요. "
            "절대 변형하지 말고 정확히."
        ),
        "CONTINUE_NORMAL": (
            "특이사항 없음. 현재 사건의 STAR를 보강하는 탐침을 던지세요."
        ),
        "STAR_INCOMPLETE": (
            "현재 사건에서 부족한 STAR 요소를 보완하는 탐침을 사용하세요. "
            "특히 R(Result) 가 비어있으면 Measurement Probe 사용."
        ),
        "STAR_COMPLETE_NEW_EVENT": (
            "현재 사건이 완성됐습니다. 자연스럽게 정리하고 "
            "새로운 사건을 유도하세요. Incident Probe 사용."
        ),
        "CONTRARY_NEEDED": (
            "반례 탐침을 지금 수행하세요. Module 2 의 3가지 변형 중 "
            "자연스러운 것 선택. 자기관리 챕터면 '흔들림' 변형 사용."
        ),
        "AVOIDANCE_DETECTED": (
            "회피 응답입니다. Module 5 의 패턴별 대응 사용. "
            "재시도 1회 후에도 안 풀리면 건너뛰기 명시적 제안."
        ),
        "DUPLICATE_SUSPECTED": (
            "사용자가 이전 챕터의 사건을 다시 말하려고 합니다. "
            "existing_events 를 확인하고 Module 4의 부드러운 거절 패턴 사용."
        ),
        "CROSS_CHAPTER_OPPORTUNITY": (
            "자기관리 챕터입니다. cross_chapter_signals 의 인용을 "
            "활용해 '아까 X 말씀하셨는데, 그때 내면에서는...' 식으로 깊이 파고드세요."
        ),
        "CHAPTER_READY_TO_END": (
            "이 챕터의 모든 조건이 충족됐습니다. "
            "**새로운 탐침 던지지 마세요.** 챕터 정리 멘트로 마무리하고 "
            "응답 끝에 [CHAPTER_COMPLETE] 태그 출력 필수."
        ),
        "MAX_TURNS_REACHED": (
            "최대 턴 도달. 강제 종료. 짧게 정리 멘트 + [CHAPTER_COMPLETE]."
        ),
        "USER_REQUESTS_PAUSE": (
            "사용자가 종료/일시중지 요청. 정중하게 인사하고 "
            "지금까지 진행 상황 짧게 요약. 응답 끝에 [SESSION_PAUSE]."
        ),
        "META_QUESTION_FROM_USER": (
            "사용자가 시스템에 대해 물었습니다. 짧게 답하고 "
            "다시 진단 흐름으로 부드럽게 복귀하세요."
        ),
        "FIRST_TURN_AVOIDANCE": (
            "첫 턴부터 회피. 라포 회복 우선. Layer 2의 backup 질문 사용."
        ),
        "INVALID_INPUT": (
            "의미 없는 입력. '답변이 잘 들어왔는지 확인이 안 됐어요' "
            "패턴으로 재요청."
        ),
    }

    return guides.get(instruction, "기본 진행")
```

### 4.4 검증

```bash
# instruction_decider 테스트
python3 -c "
from diag_project.services.instruction_decider import (
    decide_instruction, MAX_TURNS, MIN_EVENTS
)

# 테스트 케이스 1: 첫 턴
state = {
    'turn_count': 1,
    'chapter': 'organization_management',
    'last_user_response': '',
    'contains_avoidance_keywords': False,
}
assert decide_instruction(state) == 'CHAPTER_OPENING'
print('✅ 첫 턴 → CHAPTER_OPENING')

# 테스트 케이스 2: 회피
state = {
    'turn_count': 5,
    'chapter': 'self_management',
    'last_user_response': '잘 모르겠어요',
    'contains_avoidance_keywords': True,
    'events_with_star_70': 0,
    'has_contrary_probe': False,
    'events_collected': 0,
    'current_event_id': None,
    'current_event_star_coverage': None,
    'duplicate_suspected': False,
}
assert decide_instruction(state) == 'AVOIDANCE_DETECTED'
print('✅ 회피 → AVOIDANCE_DETECTED')

# 테스트 케이스 3: 종료 가능
state = {
    'turn_count': 25,
    'chapter': 'organization_management',
    'last_user_response': '네 그렇습니다',
    'contains_avoidance_keywords': False,
    'events_with_star_70': 2,
    'has_contrary_probe': True,
    'events_collected': 2,
    'current_event_id': None,
    'current_event_star_coverage': None,
    'duplicate_suspected': False,
}
assert decide_instruction(state) == 'CHAPTER_READY_TO_END'
print('✅ 종료 조건 충족 → CHAPTER_READY_TO_END')

print('\\n모든 테스트 통과')
"
```

### 4.5 Step 4 커밋

```bash
git add diag_project/services/instruction_decider.py \
        diag_project/prompts/phase3a/layer3_state.py \
        diag_project/models.py [migration]
git commit -m "$(cat <<'EOF'
feat(phase3a): add Layer 3 instruction decider

Implements the brain of Phase 3-A: decide_instruction() that selects
one of 14 instructions per turn based on chapter state.

Key components:
- decide_instruction(): priority-ordered logic (12 cases)
- build_turn_state(): aggregates all state from DB
- should_do_contrary(): Module 2 timing logic
- Helper detectors: avoidance, pause, meta question, invalid input
- Cross-chapter signal extraction (for self-management chapter)
- format_turn_state_for_llm(): converts state dict to LLM prompt text
- Per-instruction guidance text for LLM

Also adds Phase 3-A fields to Message model:
- chapter, event_id, probe_type_used, instruction_used

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

### 4.6 Step 4 보고

1. 모든 함수가 import 되는지
2. 3개 테스트 케이스 모두 통과 확인
3. Message 마이그레이션 적용 확인
4. 커밋 해시

---

## Step 5: 헬퍼 함수 (회피/중복/압축)

### 5.1 목표

instruction_decider 가 필요로 하는 헬퍼 + 대화 이력 압축 구현.

### 5.2 변경 파일

#### A. `diag_project/services/duplicate_detector.py` 신규 작성

```python
"""Module 4: 사건 중복 검출

새 사건 시작 시 이전 사건들과 비교해 중복 여부 판단.

설계 출처: docs/phase3a/01_design.md Section 6.4
"""
from typing import Any


def check_potential_duplicate(
    new_event_text: str,
    existing_events: list[dict],
) -> dict:
    """새 사건이 기존 사건과 중복인지 1차 검사.

    1차 필터 (메타데이터 비교) 만 수행. 의심되면 2차 LLM 판정 필요.

    Args:
        new_event_text: 사용자가 방금 말한 새 사건 (텍스트)
        existing_events: 기존 사건 목록 (dict 리스트)

    Returns:
        {
            "is_duplicate": bool,
            "matched_event": dict | None,
            "reason": str,  # "key_person_match" 등
        }
    """
    if not existing_events:
        return {"is_duplicate": False, "matched_event": None, "reason": "no_existing"}

    new_text_lower = new_event_text.lower()

    for existing in existing_events:
        # 1. 인물 일치 (이름/직책 키워드 포함)
        if existing.get("key_person"):
            person_keywords = _extract_person_keywords(existing["key_person"])
            if any(kw in new_text_lower for kw in person_keywords):
                return {
                    "is_duplicate": True,
                    "matched_event": existing,
                    "reason": "key_person_match",
                }

        # 2. 태그 중첩 (50% 이상)
        if existing.get("tags"):
            overlap = _calculate_tag_overlap(
                existing["tags"], new_text_lower
            )
            if overlap >= 0.5:
                return {
                    "is_duplicate": True,
                    "matched_event": existing,
                    "reason": "tag_overlap",
                }

        # 3. 핵심 행동 텍스트 유사도
        if existing.get("core_action"):
            if _text_similarity(
                existing["core_action"], new_text_lower
            ) > 0.6:
                return {
                    "is_duplicate": True,
                    "matched_event": existing,
                    "reason": "action_similar",
                }

    return {
        "is_duplicate": False,
        "matched_event": None,
        "reason": "no_match",
    }


def _extract_person_keywords(person_text: str) -> list[str]:
    """인물 설명에서 검색 가능한 키워드 추출.

    예: "교육 설계 희망 팀원" → ["교육 설계", "팀원"]
    """
    keywords = []
    if "팀원" in person_text:
        keywords.append("팀원")
    # 한국어 명사 키워드 단순 추출
    for word in person_text.split():
        if len(word) >= 2 and word not in ("님", "분", "씨"):
            keywords.append(word)
    return list(set(keywords))


def _calculate_tag_overlap(tags: list[str], text: str) -> float:
    """태그가 텍스트에 얼마나 포함되는지 (0.0 ~ 1.0)"""
    if not tags:
        return 0.0
    matches = sum(1 for tag in tags if tag in text)
    return matches / len(tags)


def _text_similarity(text1: str, text2: str) -> float:
    """매우 단순한 자카드 유사도 (단어 집합 기반)"""
    set1 = set(text1.split())
    set2 = set(text2.split())
    if not set1 or not set2:
        return 0.0
    intersection = set1 & set2
    union = set1 | set2
    return len(intersection) / len(union)
```

#### B. `diag_project/services/event_service.py` 신규 작성

```python
"""Event 테이블 CRUD + STAR 진행 추적"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlmodel import Session, select

from diag_project.models import Event


def create_event(
    db: Session,
    session_id: UUID,
    chapter: str,
    sequence_num: int,
) -> Event:
    """새 사건 시작"""
    event = Event(
        session_id=session_id,
        chapter=chapter,
        sequence_num=sequence_num,
        started_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def update_event_star(
    db: Session,
    event_id: UUID,
    situation: str | None = None,
    task: str | None = None,
    action: str | None = None,
    result: str | None = None,
) -> Event:
    """사건의 STAR 요소 업데이트"""
    event = db.get(Event, event_id)
    if not event:
        raise ValueError(f"Event {event_id} not found")

    if situation is not None:
        event.situation = situation
    if task is not None:
        event.task = task
    if action is not None:
        event.action = action
    if result is not None:
        event.result = result

    # STAR coverage 재계산
    coverage = sum([
        bool(event.situation),
        bool(event.task),
        bool(event.action),
        bool(event.result),
    ]) / 4.0
    event.star_coverage = coverage

    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def complete_event(
    db: Session,
    event_id: UUID,
    metadata: dict,
) -> Event:
    """사건 완료 + 메타데이터 저장 (Module 4용)"""
    event = db.get(Event, event_id)
    if not event:
        raise ValueError(f"Event {event_id} not found")

    event.is_complete = True
    event.completed_at = datetime.utcnow()
    event.summary = metadata.get("summary")
    event.key_person = metadata.get("key_person")
    event.time_context = metadata.get("time_context")
    event.core_action = metadata.get("core_action")
    event.tags = metadata.get("tags", [])

    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def increment_probe_count(db: Session, event_id: UUID) -> None:
    """탐침 횟수 증가"""
    event = db.get(Event, event_id)
    if event:
        event.probe_count += 1
        db.add(event)
        db.commit()
```

#### C. `diag_project/services/conversation_compressor.py` 신규 작성

```python
"""대화 이력 압축: 완료된 사건은 요약으로 교체

설계 출처: docs/phase3a/01_design.md Section 8.3
"""
from sqlmodel import Session, select

from diag_project.models import Message, Event


def compress_conversation_history(
    db: Session,
    session_id: str,
    chapter: str,
) -> list[dict]:
    """완료된 사건의 대화는 요약으로 교체.

    Returns:
        LLM 에 전달할 message 리스트 (role, content)
    """
    messages = db.exec(
        select(Message)
        .where(Message.session_id == session_id)
        .where(Message.chapter == chapter)
        .order_by(Message.created_at)
    ).all()

    completed_event_ids = {
        e.id for e in db.exec(
            select(Event)
            .where(Event.session_id == session_id)
            .where(Event.is_complete == True)
        ).all()
    }

    completed_events = {
        e.id: e for e in db.exec(
            select(Event).where(Event.id.in_(completed_event_ids))
        ).all()
    }

    compressed = []
    seen_events = set()

    for msg in messages:
        if msg.event_id and msg.event_id in completed_event_ids:
            # 완료된 사건의 메시지 → 첫 번째만 요약으로 교체
            if msg.event_id not in seen_events:
                event = completed_events[msg.event_id]
                summary = _format_event_summary(event)
                compressed.append({
                    "role": "system",
                    "content": summary,
                })
                seen_events.add(msg.event_id)
            # 이후 같은 사건의 메시지는 스킵
        else:
            # 진행 중인 사건 또는 사건 없음 → 그대로 유지
            compressed.append({
                "role": msg.role,
                "content": msg.content,
            })

    return compressed


def _format_event_summary(event: Event) -> str:
    """Event 객체를 요약 텍스트로"""
    parts = [f"[Completed Event Summary - Event {event.sequence_num}]"]

    if event.summary:
        parts.append(f"요약: {event.summary}")

    if event.key_person:
        parts.append(f"인물: {event.key_person}")

    if event.core_action:
        parts.append(f"핵심 행동: {event.core_action}")

    star = []
    if event.situation:
        star.append(f"S: {event.situation[:100]}")
    if event.task:
        star.append(f"T: {event.task[:100]}")
    if event.action:
        star.append(f"A: {event.action[:100]}")
    if event.result:
        star.append(f"R: {event.result[:100]}")

    if star:
        parts.append("STAR: " + " | ".join(star))

    return "\n".join(parts)
```

### 5.3 검증

```bash
# 모든 헬퍼 모듈 import 가능 확인
python3 -c "
from diag_project.services.duplicate_detector import check_potential_duplicate
from diag_project.services.event_service import (
    create_event, update_event_star, complete_event, increment_probe_count
)
from diag_project.services.conversation_compressor import compress_conversation_history
print('✅ 모든 헬퍼 모듈 import 성공')
"

# duplicate_detector 단위 테스트
python3 -c "
from diag_project.services.duplicate_detector import check_potential_duplicate

# 테스트 1: 빈 기존 사건 → 중복 없음
result = check_potential_duplicate('새로운 이야기', [])
assert result['is_duplicate'] == False
print('✅ 기존 사건 없을 때 중복 없음')

# 테스트 2: 같은 인물 → 중복
existing = [{
    'event_id': 'evt_1',
    'chapter': 'organization_management',
    'summary': '교육체계 개편',
    'key_person': '교육 설계 희망 팀원',
    'core_action': '책 추천',
    'tags': ['교육체계', '코칭'],
}]
result = check_potential_duplicate(
    '저희 팀에서 교육 설계 하던 팀원이 또 새로운 일을',
    existing
)
assert result['is_duplicate'] == True
assert result['reason'] == 'key_person_match'
print('✅ 같은 인물 감지')

print('\\n모든 테스트 통과')
"
```

### 5.4 Step 5 커밋

```bash
git add diag_project/services/duplicate_detector.py \
        diag_project/services/event_service.py \
        diag_project/services/conversation_compressor.py
git commit -m "$(cat <<'EOF'
feat(phase3a): add helper services for duplication, events, compression

Three new services supporting Phase 3-A:

1. duplicate_detector: Module 4 first-pass duplicate detection
   - Compares new events with existing via key_person, tags, core_action
   - Returns suspicion + reason for second-pass LLM judgment

2. event_service: Event CRUD with STAR tracking
   - create_event, update_event_star, complete_event
   - Auto-recalculates star_coverage on STAR updates
   - increment_probe_count for tracking probe attempts

3. conversation_compressor: Cost optimization
   - Replaces completed events' turn-by-turn dialogue with summaries
   - Reduces context length by ~75% in long sessions
   - Per Section 8.3 of design doc

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

### 5.5 Step 5 보고

1. 3개 새 서비스 모듈 import 성공
2. duplicate_detector 단위 테스트 통과
3. 커밋 해시

---

## Step 6: llm_service.py 통합

### 6.1 목표

지금까지 만든 모든 컴포넌트를 `llm_service.py` 에 통합. 실제 LLM 호출 흐름에 3-Layer 프롬프트 적용.

### 6.2 변경 파일

#### A. `diag_project/llm_service.py` 의 `generate_next_interaction()` 재작성

기존 함수의 시그니처는 유지하되, 내부를 완전히 교체.

**변경 전 (현재 동작):**
- 단일 프롬프트로 LLM 호출
- 사용자 메시지 + 코치 페르소나만 컨텍스트

**변경 후 (Phase 3-A):**
- 3-Layer 프롬프트로 LLM 호출
- 매 턴 build_turn_state()로 상태 분석
- LLM 출력 JSON 파싱 후 Event/Message DB 업데이트

```python
async def generate_next_interaction(
    self,
    db: Session,
    session_id: UUID,
    user_message: str,
    chapter: str,  # 새 파라미터
) -> dict:
    """Phase 3-A: 3-Layer 프롬프트로 다음 응답 생성.

    Returns:
        {
            "reply": str,  # 사용자에게 보여질 응답
            "state": dict,  # 서버 처리용 상태
            "event_metadata": dict | None,  # 사건 종료 시
        }
    """
    # 1. 사용자 메시지 저장
    user_msg = Message(
        session_id=session_id,
        role="user",
        content=user_message,
        chapter=chapter,
    )
    db.add(user_msg)
    db.commit()

    # 2. Turn State 빌드 (Layer 3)
    from diag_project.services.instruction_decider import build_turn_state
    state = build_turn_state(db, session_id, chapter)

    # 3. 대화 이력 압축
    from diag_project.services.conversation_compressor import (
        compress_conversation_history
    )
    compressed_history = compress_conversation_history(
        db, session_id, chapter
    )

    # 4. 프롬프트 조립
    from diag_project.prompts.phase3a.layer1_system import LAYER1_SYSTEM_PROMPT
    from diag_project.prompts.phase3a.layer2_chapters import CHAPTER_CONTEXTS
    from diag_project.prompts.phase3a.layer3_state import format_turn_state_for_llm

    system_prompt = LAYER1_SYSTEM_PROMPT
    chapter_context = CHAPTER_CONTEXTS[chapter]
    turn_state_text = format_turn_state_for_llm(state)

    # Gemini 형식으로 변환
    user_content = (
        f"{chapter_context}\n\n{turn_state_text}\n\n"
        "[Conversation History]\n" +
        "\n".join(f"{m['role']}: {m['content']}" for m in compressed_history)
    )

    # 5. LLM 호출
    response_text = await self._generate_with_retry(
        prompt=user_content,
        system_instruction=system_prompt,  # 새 파라미터
        max_tokens=1500,
    )

    # 6. JSON 파싱
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        # JSON 파싱 실패 → fallback
        parsed = {
            "reply": response_text,
            "state": {},
            "event_metadata": None,
        }

    # 7. assistant 메시지 저장
    assistant_msg = Message(
        session_id=session_id,
        role="assistant",
        content=parsed["reply"],
        chapter=chapter,
        event_id=state.get("current_event_id"),
        probe_type_used=parsed.get("state", {}).get("probe_type_used"),
        instruction_used=state["instruction_for_this_turn"],
    )
    db.add(assistant_msg)
    db.commit()

    # 8. Event 업데이트 (필요 시)
    await _update_event_from_llm_output(db, parsed, state, chapter)

    return parsed
```

#### B. `_generate_with_retry()` 시그니처 확장

`system_instruction` 파라미터 추가:

```python
async def _generate_with_retry(
    self,
    prompt: str,
    system_instruction: str | None = None,  # 새 파라미터
    max_tokens: int = 1000,
) -> str:
    """기존 retry 로직에 system_instruction 추가"""
    # ...
    config_kwargs = {
        "stop_sequences": [],
        "max_output_tokens": max_tokens,
        "temperature": 0.7,
        "safety_settings": [
            # 기존 4개 BLOCK_NONE 유지
        ],
    }
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction

    response = await client.aio.models.generate_content(
        model=BEST_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(**config_kwargs),
    )
    # ...
```

#### C. `_update_event_from_llm_output()` 헬퍼

```python
async def _update_event_from_llm_output(
    db: Session,
    llm_output: dict,
    state: dict,
    chapter: str,
) -> None:
    """LLM 출력에서 Event 정보 추출해 DB 업데이트"""
    from diag_project.services.event_service import (
        create_event, update_event_star, complete_event, increment_probe_count
    )

    state_data = llm_output.get("state", {})
    turn_intent = state_data.get("turn_intent")

    # 새 사건 시작
    if turn_intent == "NEW_EVENT_STARTED":
        sequence_num = state["events_collected"] + 1
        new_event = create_event(
            db, state["session_id"], chapter, sequence_num
        )
        # 이후 메시지에 event_id 연결할 수 있도록 state 업데이트는 호출자가

    # STAR 업데이트
    star_coverage = state_data.get("star_coverage", {})
    current_event_id = state.get("current_event_id")

    if current_event_id and star_coverage:
        # 사용자 답변에서 STAR 요소 추출은 LLM 이 했음
        # 실제로는 메시지 내용에서 추출 필요 (단순화)
        # 여기서는 probe_count만 증가
        increment_probe_count(db, current_event_id)

    # 사건 완료
    if turn_intent == "EVENT_COMPLETE" and current_event_id:
        metadata = llm_output.get("event_metadata", {})
        if metadata:
            complete_event(db, current_event_id, metadata)
```

### 6.3 Routes 통합

#### D. `diag_project/routes/diagnoses.py` 수정

기존 `/diagnoses/{id}/messages` POST 엔드포인트가 chapter 정보를 받도록:

```python
@router.post("/diagnoses/{session_id}/messages")
async def send_message(
    session_id: UUID,
    body: MessageCreate,
    db: Session = Depends(get_session),
):
    # 현재 세션의 활성 챕터 조회
    chapter = await _get_current_chapter(db, session_id)

    # 새 generate_next_interaction 호출
    result = await llm_service.generate_next_interaction(
        db=db,
        session_id=session_id,
        user_message=body.content,
        chapter=chapter,
    )

    return {
        "reply": result["reply"],
        # state, event_metadata는 서버 내부용이라 응답에 포함 안 함
    }


async def _get_current_chapter(db: Session, session_id: UUID) -> str:
    """현재 세션의 활성 챕터 결정.

    DB의 DiagnosisSession.current_chapter 필드에서 가져오거나,
    완료된 챕터들을 보고 다음 챕터 결정.
    """
    # 단순 구현: DiagnosisSession에 current_chapter 필드 추가 필요
    session = db.get(DiagnosisSession, session_id)
    return session.current_chapter or "organization_management"
```

#### E. DiagnosisSession 모델 확장

```python
class DiagnosisSession(SQLModel, table=True):
    # ... 기존 필드 ...

    # Phase 3-A 추가
    current_chapter: str = Field(default="organization_management")
    completed_chapters: list[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
```

### 6.4 검증

```bash
# 1. 서버 재기동
# (수동: uvicorn 프로세스 재시작)

# 2. 기본 엔드포인트 200 확인
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/framework
# → 200

# 3. 실제 메시지 흐름 테스트 (수동 - 브라우저)
# - 새 진단 세션 생성
# - 첫 메시지 전송 → CHAPTER_OPENING 응답 확인
# - "잘 모르겠어요" 입력 → AVOIDANCE_DETECTED 응답 확인
# - DB 확인: SELECT * FROM event; → 사건 추적되는지

# 4. 로그 확인
tail -50 /Users/daniel/python_new/new_diagnosis_api/logs/server.log
# → instruction 사용 흔적 확인
```

### 6.5 Step 6 커밋

```bash
git add diag_project/llm_service.py \
        diag_project/routes/diagnoses.py \
        diag_project/models.py [migration]
git commit -m "$(cat <<'EOF'
feat(phase3a): integrate 3-layer prompt system into llm_service

Wires together all Phase 3-A components into the actual conversation
flow:

- generate_next_interaction(): Now uses 3-layer prompt
  (Layer 1 system + Layer 2 chapter + Layer 3 turn state)
- _generate_with_retry(): Adds system_instruction parameter
- _update_event_from_llm_output(): DB updates from LLM output
- Routes: send_message endpoint now uses chapter context
- DiagnosisSession: Adds current_chapter, completed_chapters fields

Conversation flow:
1. User message saved
2. Turn state built from DB
3. Conversation history compressed (completed events summarized)
4. 3-layer prompt assembled
5. LLM called with system_instruction
6. JSON output parsed
7. Event/Message DB updated

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

### 6.6 Step 6 보고

1. 서버 재기동 후 200 응답 유지
2. 새 메시지 흐름이 작동하는지 (수동 테스트)
3. 첫 턴이 챕터 시작 스크립트로 시작되는지
4. DB 의 event 테이블에 데이터 들어가는지
5. 커밋 해시

---

## Step 7: 통합 테스트

### 7.1 목표

3개 시나리오로 Phase 3-A 동작 검증.

### 7.2 시나리오 1: 정상 흐름 (조직관리 챕터)

**테스트 절차:**
1. 새 진단 세션 생성
2. 시작 → 챕터 시작 스크립트 출력 확인
3. 사건 1 묘사 → STAR 추적 확인
4. 추가 탐침 → STAR_INCOMPLETE 또는 CONTRARY_NEEDED 확인
5. 사건 1 완료 → Event 테이블에 메타데이터 저장 확인
6. 사건 2 시작 → existing_events 에 사건 1 포함 확인
7. 반례 탐침 → has_contrary_probe = true 확인
8. 챕터 종료 → CHAPTER_READY_TO_END + [CHAPTER_COMPLETE] 태그 확인

**검증 SQL:**
```sql
-- 챕터별 사건 수
SELECT chapter, COUNT(*) FROM event
WHERE session_id = '{test_session_id}'
GROUP BY chapter;
-- → organization_management: 2

-- 모든 사건의 STAR 70% 이상
SELECT id, star_coverage FROM event
WHERE session_id = '{test_session_id}';
-- → 모두 0.7 이상

-- 사용된 instruction 분포
SELECT instruction_used, COUNT(*) FROM message
WHERE session_id = '{test_session_id}'
  AND role = 'assistant'
GROUP BY instruction_used;
```

### 7.3 시나리오 2: 회피 응답 처리 (자기관리 챕터)

**테스트 절차:**
1. 자기관리 챕터까지 진행 (또는 직접 시작)
2. 사건 1 진행 중 "잘 모르겠어요" 입력
3. AVOIDANCE_DETECTED → 각도 변경 응답 확인
4. 다시 "잘 모르겠어요"
5. 두 번째 시도 → 건너뛰기 명시적 제안 확인
6. 챕터 종료 시 자기관리 사건 수 확인

**검증:**
- 각 회피마다 다른 응답 (1차/2차 재시도)
- 챕터 종료 거부 안 됨 (다음으로 강제 넘어가지 않음)
- 최대 35턴 도달 시 MAX_TURNS_REACHED

### 7.4 시나리오 3: 중복 사건 차단

**테스트 절차:**
1. 조직관리 챕터에서 "교육체계 개편" 사건 완료
2. 성과관리 챕터 시작
3. 사용자가 같은 "교육체계 개편" 사건 다시 시도
4. DUPLICATE_SUSPECTED 감지
5. AI 응답: "그 사건은 이전 챕터에서 들었어요" 패턴 확인
6. 새 사건 요청

**검증:**
- existing_events에 사건 1 포함됨
- 사용자가 같은 인물명 사용 시 감지
- 응답이 부드러운 거절 + 새 사례 요청

### 7.5 종합 검증 스크립트

```bash
# 자동 통합 테스트 스크립트
python3 -c "
import asyncio
from sqlmodel import Session
from diag_project.db import engine
from diag_project.services.instruction_decider import (
    decide_instruction, build_turn_state, MAX_TURNS, MIN_EVENTS
)

print('=== Phase 3-A Integration Tests ===\\n')

# Test 1: Configuration consistency
assert MAX_TURNS['self_management'] == 35
assert MAX_TURNS['people_management'] == 50
assert MIN_EVENTS['people_management'] == 3
print('✅ Configuration consistent')

# Test 2: Instruction priorities
test_cases = [
    # (state_dict, expected_instruction)
    ({'turn_count': 1, 'chapter': 'organization_management',
      'last_user_response': '', 'contains_avoidance_keywords': False},
     'CHAPTER_OPENING'),
    ({'turn_count': 5, 'chapter': 'organization_management',
      'last_user_response': '오늘은 그만할게요',
      'contains_avoidance_keywords': False,
      'events_with_star_70': 1, 'has_contrary_probe': True,
      'events_collected': 1, 'current_event_id': None,
      'current_event_star_coverage': None, 'duplicate_suspected': False},
     'USER_REQUESTS_PAUSE'),
    ({'turn_count': 50, 'chapter': 'organization_management',
      'last_user_response': '네',
      'contains_avoidance_keywords': False,
      'events_with_star_70': 1, 'has_contrary_probe': False,
      'events_collected': 1, 'current_event_id': None,
      'current_event_star_coverage': None, 'duplicate_suspected': False},
     'MAX_TURNS_REACHED'),
]

for state, expected in test_cases:
    actual = decide_instruction(state)
    assert actual == expected, f'Expected {expected}, got {actual}'
    print(f'✅ {expected}')

print('\\n=== All tests passed ===')
"
```

### 7.6 회귀 테스트

기존 동작이 깨지지 않았는지:

```bash
# Framework API
curl -s http://127.0.0.1:8000/api/v1/framework | head -20

# Coaches API
curl -s http://127.0.0.1:8000/api/v1/coaches | head -20

# 실제 LLM 호출 (직접)
python3 -c "
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from diag_project.llm_service import GeminiService

async def test():
    service = GeminiService()
    result = await service._generate_with_retry(
        '안녕하세요. 한 문장으로 인사해주세요.',
        max_tokens=100,
    )
    print('Result:', result[:200])

asyncio.run(test())
"
# → 정상 응답
```

### 7.7 Step 7 커밋

문서/테스트 자료만 추가:

```bash
# 통합 테스트 스크립트를 별도 파일로
# scripts/phase3a_integration_test.py 등에 저장

git add scripts/phase3a_integration_test.py docs/phase3a/
git commit -m "$(cat <<'EOF'
test(phase3a): add integration tests + final docs

Adds:
- Integration test script covering 3 scenarios
- Configuration consistency tests
- Instruction priority tests
- Regression tests for existing functionality
- Final design and implementation docs in docs/phase3a/

Phase 3-A 구현 완료. 다음 단계는 Phase 2 (Self-Consistency) 또는
Phase 3-B (평가 방법론) 검토.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

### 7.8 Step 7 최종 보고

1. 3개 시나리오 모두 통과
2. 회귀 테스트 모두 통과
3. 모든 단계 commit 해시 정리:
   - Step 1: `<hash>` (Event 테이블)
   - Step 2: `<hash>` (Layer 1)
   - Step 3: `<hash>` (Layer 2)
   - Step 4: `<hash>` (Layer 3 + decider)
   - Step 5: `<hash>` (Helpers)
   - Step 6: `<hash>` (Integration)
   - Step 7: `<hash>` (Tests + Docs)

---

## 부록: 문제 해결 가이드

### 자주 발생하는 문제

#### 문제 1: JSON 파싱 실패
**증상:** LLM 응답이 JSON 형식이 아님
**원인:** LLM 이 system prompt 의 출력 형식 지시 무시
**해결:**
- Gemini 의 `response_mime_type="application/json"` 설정
- 또는 fallback 로직으로 reply 만 추출

#### 문제 2: instruction 우선순위 혼란
**증상:** 회피인데 CHAPTER_READY_TO_END 가 먼저 매칭됨
**원인:** decide_instruction 로직 순서 오류
**해결:** Section 7.5 의 정확한 순서 따르기 (회피 6번, 종료 9번)

#### 문제 3: Event 테이블에 데이터 안 쌓임
**증상:** event 테이블이 비어있음
**원인:** _update_event_from_llm_output 호출 누락
**해결:** generate_next_interaction Step 8 확인

#### 문제 4: 시스템 프롬프트가 너무 김
**증상:** Gemini 토큰 한도 초과 또는 응답 품질 저하
**해결:**
- Gemini system_instruction 파라미터 사용 (별도 캐시)
- 또는 Layer 1 의 일부를 Layer 2 로 이동

---

## 부록: 후속 작업 메모

Phase 3-A 완료 후 검토할 것:

1. **Phase 2 (Self-Consistency)**
   - 3회 독립 채점 + Cohen's κ
   - 비용 3배 증가 (약 $0.75/세션)

2. **Phase 3-B (평가 방법론)**
   - Tone 제거
   - Rubric 강제 참조
   - Multi-label 분류 (한 사건 → 여러 지표)
   - 인용+해석 이중구조

3. **Phase 3-C (리포트 형식)**
   - 가짜 비교 데이터 제거
   - 블라인드 스팟 섹션
   - 맞춤 개발 계획

4. **프론트엔드 작업**
   - 챕터 진행 UI (프로그레스 바)
   - 온보딩 페이지 별도 제작
   - 챕터 전환 UX

---

**구현 지시문 끝.**
