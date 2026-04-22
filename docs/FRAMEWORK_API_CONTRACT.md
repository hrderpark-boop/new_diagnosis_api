# Framework API Contract
> Phase 1.2-A 산출물  
> 작성일: 2026-04-22  
> 목적: `GET /api/v1/framework`를 통해 `competencies.py`를 SSOT로 노출하고,  
> 프론트엔드와 LLM 프롬프트가 하드코딩 없이 프레임워크를 소비하도록 한다.

---

## 1. 엔드포인트 목록

| Method | Path | 용도 | 인증 |
|--------|------|------|------|
| `GET` | `/api/v1/framework` | 역량 프레임워크 전체 (지표·레벨·예시 포함) | 없음 |
| `GET` | `/api/v1/framework/topics` | 역량 순서 목록만 (chat 페이지 진행 표시용) | 없음 |

두 엔드포인트 모두 **읽기 전용 정적 데이터**다. DB 접근 없이 `data/competencies.py`를 직접 변환한다.

---

## 2. GET /api/v1/framework — 전체 프레임워크

### 응답 스키마

```json
{
  "framework_id": "leadership_v1",
  "name": "리더십 역량진단",
  "version": "1.0",
  "scoring": {
    "levels": [1, 2, 3, 4],
    "max_score": 5.0,
    "methodology": "STAR_BEI"
  },
  "competencies": [
    {
      "key": "organization_management",
      "name": "조직관리",
      "order": 1,
      "description": "조직의 비전, 전략, 변화, 혁신을 효과적으로 관리하고 구성원들의 참여를 이끌어내는 능력.",
      "indicators": [
        {
          "key": "vision_sharing",
          "name": "비전 제시 및 공유",
          "levels": {
            "1": "조직 비전의 필요성과 개념을 이해하고...",
            "2": "조직의 비전과 목표를 명확히 이해하고...",
            "3": "비전과 전략을 조직 상황에 맞게 구체화하고...",
            "4": "새로운 환경 변화에 맞춰 조직의 비전을 재정의하고..."
          },
          "examples": {
            "1": "・ 조직의 비전이나 목표에 대해 질문하거나 메모해 둠...",
            "2": "・ 회의에서 비전을 쉽게 설명하고...",
            "3": "・ 비전 달성을 위한 중장기 전략을 팀과 함께 설계함...",
            "4": "・ 새로운 산업 트렌드나 정책 변화에 따라..."
          }
        }
      ]
    }
  ]
}
```

### Pydantic 모델 대응 (schemas/framework.py)

```
FrameworkResponse
├── framework_id: str
├── name: str
├── version: str
├── scoring: ScoringInfo
│   ├── levels: List[int]        # [1, 2, 3, 4]
│   ├── max_score: float         # 5.0
│   └── methodology: str         # "STAR_BEI"
└── competencies: List[CompetencyOut]
    ├── key: str                 # "organization_management"
    ├── name: str                # "조직관리"
    ├── order: int               # 1 (진단 진행 순서)
    ├── description: str
    └── indicators: List[IndicatorOut]
        ├── key: str             # "vision_sharing"
        ├── name: str            # "비전 제시 및 공유"
        ├── levels: Dict[str, str]   # {"1": "...", "2": "...", ...}
        └── examples: Dict[str, str] # {"1": "...", "2": "...", ...}
```

---

## 3. GET /api/v1/framework/topics — 역량 순서 목록

### 응답 스키마

```json
{
  "framework_id": "leadership_v1",
  "topics": [
    {"key": "organization_management", "name": "조직관리", "order": 1},
    {"key": "performance_management",  "name": "성과관리", "order": 2},
    {"key": "people_management",       "name": "사람관리", "order": 3},
    {"key": "work_management",         "name": "일관리",   "order": 4},
    {"key": "self_management",         "name": "자기관리", "order": 5}
  ],
  "total_count": 5
}
```

### Pydantic 모델 대응

```
TopicsResponse
├── framework_id: str
├── topics: List[TopicOut]
│   ├── key: str
│   ├── name: str
│   └── order: int
└── total_count: int
```

---

## 4. 설계 결정 사항

### `order`를 명시적 필드로 두는 이유

Python 3.7+에서 `dict` 삽입 순서는 보장되지만, JSON 직렬화·클라이언트 파싱 등 여러 레이어를 거치면 순서 보장을 묵시적으로 가정하게 된다. `order: int`를 명시하면:
- 클라이언트가 순서를 보장할 책임에서 해방됨
- 미래에 역량 순서를 DB 또는 config로 관리할 때 API 계약이 변경되지 않음
- 프론트엔드에서 `topics.sort((a, b) => a.order - b.order)` 한 줄로 안전하게 정렬 가능

### `max_score`를 응답에 포함하는 이유

현재 채점 방식은 루브릭 점수(1.0~4.0) + 보너스/조정치 = 최대 5.0점이다.  
`max_score`가 응답에 포함되면:
- 프론트엔드의 `/ 5` 하드코딩(`report/page.tsx:36,93,217`)을 제거할 수 있음
- 향후 10점 척도 또는 다른 만점 기준 프레임워크를 도입해도 UI 변경 없음

### `methodology`를 포함하는 이유

현재 유일한 값은 `"STAR_BEI"`이지만, 명시하는 이유:
- 미래 `"SCENARIO"` (상황 판단형), `"KNOWLEDGE"` (지식형) 역량 프레임워크 추가 시,  
  프론트엔드가 `methodology`를 기반으로 결과 UI를 다르게 렌더링할 수 있음
- LLM 서비스가 `methodology`를 읽어 분석 프롬프트를 동적으로 선택하는 구조로 확장 가능

### `framework_id`가 `leadership_v1`인 이유

`framework_id`는 진단 목적과 버전을 동시에 식별한다:
- `leadership_v1` — 현재 리더십 역량진단 (본 프로젝트)
- `common_v1` — 미래: 전사 공통역량 진단
- `dev_v1` — 미래: 직무별(개발자·영업 등) 역량 진단
- `leadership_v2` — 미래: 리더십 프레임워크 개정판

`DiagnosisSession`에 `framework_id`를 저장하면 세션이 어떤 버전의 프레임워크로 진행되었는지 추적 가능 (현재는 미구현, Phase 2 이후).

---

## 5. 변경 영향도 — 이 API 구현 후 제거 가능한 하드코딩

| 하드코딩 위치 | 타입 | 대체 방법 |
|---------------|------|-----------|
| `llm_service.py:26` `ALL_COMPETENCIES` | 리스트 | `get_topics()` 결과에서 `[t.name for t in topics]` |
| `llm_service.py:27–33` `KOREAN_TO_KEY` / `KEY_TO_KOREAN` | 딕셔너리 | `{c.name: c.key for c in framework.competencies}` |
| `routes/diagnoses.py:46` `TOPIC_ORDER` | 리스트 | `[t.name for t in get_topics().topics]` |
| `services/analysis_service.py:90` `/ 5` | 스칼라 | `/ get_active_framework().scoring.max_score` |
| `app/chat/page.tsx:15` `ALL_TOPICS` | 배열 | `GET /api/v1/framework/topics` 응답 |
| `app/chat/page.tsx:187` `length === 5` | 스칼라 | `length === response.total_count` |
| `app/report/page.tsx:131–137` `SUB_COMPETENCIES` | 객체 | `GET /api/v1/framework` 응답의 `competencies[].indicators` |
| `app/report/page.tsx:36,93,217` `/ 5` | 스칼라 | `/ response.scoring.max_score` |
| `app/report/page.tsx:379–385` `competencyLabels` | 객체 | `{c.key: c.name for c in response.competencies}` |

### 프론트엔드에서 이 API를 호출해야 하는 파일

| 파일 | 시점 | 이유 |
|------|------|------|
| `app/chat/page.tsx` | 마운트 시 1회 | `ALL_TOPICS` 배열 교체, 진행 메달 렌더링 |
| `app/report/page.tsx` | 마운트 시 1회 | `SUB_COMPETENCIES`, `competencyLabels`, 점수 스케일 |
| `app/select-coach/page.tsx` | 마운트 시 (현재 필요 없음) | 미래 역량 선택 UI 확장 시 |

> **권장:** `/framework/topics`를 Next.js `layout.tsx`에서 서버사이드로 fetch하여  
> 하위 페이지에 context로 전달하면 중복 호출 없음.

---

## 6. curl 테스트 예시

서버 실행 후 (`uvicorn diag_project.main:app --reload`):

```bash
# 전체 프레임워크
curl -s http://127.0.0.1:8000/api/v1/framework | python3 -m json.tool | head -40

# 역량 순서만
curl -s http://127.0.0.1:8000/api/v1/framework/topics | python3 -m json.tool

# Python 검증
python3 -c "
import httpx, asyncio
async def test():
    async with httpx.AsyncClient() as c:
        r = await c.get('http://127.0.0.1:8000/api/v1/framework')
        assert r.status_code == 200
        d = r.json()
        assert d['framework_id'] == 'leadership_v1'
        assert len(d['competencies']) == 5
        assert d['scoring']['max_score'] == 5.0
        total_indicators = sum(len(comp['indicators']) for comp in d['competencies'])
        assert total_indicators == 27
        print(f'OK — {len(d[\"competencies\"])} 역량, {total_indicators} 지표')
asyncio.run(test())
"
```

---

## 7. 알려진 확장 한계

- 현재 `methodology`는 프레임워크 레벨에 있음. 한 프레임워크 안에
  여러 방법론이 섞이는 경우(예: 지식형+행동형 혼합 직무역량)에는
  지표 레벨로 이동 필요. v2 API로 처리 예정
