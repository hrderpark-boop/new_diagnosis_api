"""3가지 극단 페르소나 진단 시뮬레이션 → 대시보드 즉시 표출용 리포트 생성.

목적:
  성실형(투머치토커) / 귀차니즘형(단답형) / 무례한형(공격적) 세 페르소나가
  진단을 처음부터 끝까지 자동으로 수행하고, diagnosis_reports 에 리포트를
  적재해 고객사 담당자 대시보드(Comprehensive Analysis)에 바로 나타나게 한다.

대시보드 표출 조건까지 자동 충족:
  1) 참가자를 특정 고객사(company_id)에 연결 → Client Admin 화면에 노출
  2) 대화 시작 전 자가진단 제출 → 대시보드 '인식의 차이(Gap Analysis)' 표출
  3) 대화 종료 후 analyze 호출 → 리포트 적재(역량 평균·키워드·상관관계 집계)

통신 방식:
  로컬/원격 FastAPI 엔드포인트로 통신한다(내부 서비스 직접 호출이 아님).
  참가자 생성·회사 연결·자가진단 저장만 DB/전용 API 로 처리한다.

실행:
    # 로컬 백엔드 대상 (권장). 각 페르소나 1명씩 총 3명 생성.
    SIM_API_BASE=http://127.0.0.1:8000 python simulate_personas.py

    # 페르소나별 인원을 늘리려면 (예: 각 3명 = 총 9명)
    SIM_API_BASE=http://127.0.0.1:8000 SIM_PER_PERSONA=3 python simulate_personas.py

    # 대시보드 노출 대상 고객사 코드 지정 (기본: SIMCO, 없으면 자동 생성)
    SIM_COMPANY_CODE=CONNECTN python simulate_personas.py
"""

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

# 페르소나 응답 생성 계측 — 코치 콜과 별개(sim 전용). 어제 지출의 절반이
# 여기(계측 밖·thinking dynamic)였을 수 있어 별도 집계·flash·thinking=0 로 고정.
_PERSONA_USAGE = {"calls": 0, "input": 0, "output": 0, "thoughts": 0}

# §6(b): 페르소나 컨텍스트 히스토리 절삭(제곱증가 억제). 기본 off(0=전체).
#   sim 전용 절삭이라 원장/deep_analysis(전체 트랜스크립트)에는 영향 없다.
#   코치(prod)는 이미 챕터-스코프+이벤트압축이라 별도 절삭 불필요.
_PERSONA_HISTORY_TURNS = int(os.getenv("SIM_PERSONA_HISTORY_TURNS", "0") or 0)

# ── 백엔드 모듈/환경 부트스트랩 ──────────────────────────────────────────
#   이 파일은 new_diagnosis_api/tools/ 에 위치한다(추적·재현). BACKEND_DIR 은
#   한 단계 위(new_diagnosis_api), PROJECT_ROOT 는 두 단계 위.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)
load_dotenv(os.path.join(BACKEND_DIR, ".env"))
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or (
    os.getenv("GEMINI_API_KEYS") or ""
).split(",")[0].strip().strip('"')
if not api_key:
    api_key = input("\n🔑 Gemini API 키를 붙여넣고 엔터: ").strip()
if not api_key:
    print("❌ 키가 입력되지 않아 종료합니다.")
    sys.exit(1)

client_gemini = genai.Client(api_key=api_key)

# ── API 엔드포인트 ────────────────────────────────────────────────────────
API_BASE = os.getenv("SIM_API_BASE", "http://127.0.0.1:8000")
START_URL = f"{API_BASE}/api/v1/diagnoses/start"
CHAT_URL = f"{API_BASE}/api/v1/diagnoses/submit_message"
SELF_EVAL_URL = f"{API_BASE}/api/v1/sessions/{{sid}}/self-eval"
ANALYZE_URL = f"{API_BASE}/api/v1/reports/{{sid}}/analyze"
REPORT_URL = f"{API_BASE}/api/v1/reports/{{sid}}"

# Supabase 에 실존 확인된 고정 리소스 (coach 011, template 0008)
TEMPLATE_ID = "10000000-0000-0000-0000-000000000008"
COACH_ID = "10000000-0000-0000-0000-000000000011"

# 대시보드 표출 대상 고객사
COMPANY_CODE = os.getenv("SIM_COMPANY_CODE", "SIMCO")
COMPANY_NAME = os.getenv("SIM_COMPANY_NAME", "시뮬레이션테스트사")

# 페르소나별 생성 인원 (기본 1명씩 → 총 3명)
PER_PERSONA = int(os.getenv("SIM_PER_PERSONA", "1"))
# 실행 태그: 값을 바꾸면 완전히 새로운 참가자 세트로 시작한다.
# (이전 실행이 남긴 paused/종료 세션과 섞이지 않게 하는 용도)
RUN_TAG = os.getenv("SIM_RUN_TAG", "")
# 특정 페르소나만 실행 (미지정 시 전체)
ONLY_PERSONA = os.getenv("SIM_PERSONA", "")

LOG_DIR = os.path.join(PROJECT_ROOT, "test_logs")
os.makedirs(LOG_DIR, exist_ok=True)
SEMAPHORE = asyncio.Semaphore(int(os.getenv("SIM_CONCURRENCY", "2")))

# 챕터(역량)를 하나 마칠 때마다 코치가 휴식을 제안하며 세션을 일시중지한다.
# 5대 역량을 완주하려면 그때마다 재개해야 하므로 여유분 포함 8회까지 허용.
MAX_RESUMES = int(os.getenv("SIM_MAX_RESUMES", "8"))
# 5개 챕터를 완주하려면 챕터당 8~16턴이 필요하다. 특히 단답형·불신형은
# 코치가 잘게 쪼개 물으며 STAR 를 끌어내느라 턴이 더 든다. 60은 조직관리
# 한 챕터도 못 끝낼 만큼 부족해 전원 max_turns 로 헛돌았다 → 100 으로 상향.
# (완주 시엔 아래 조기 종료 감지가 즉시 끊어주므로 빠른 페르소나는 100 을
#  다 쓰지 않는다.)
MAX_TURNS = int(os.getenv("SIM_MAX_TURNS", "100"))

# 5대 역량 키 (백엔드 COMPETENCY_FRAMEWORK 와 동일)
COMPETENCY_KEYS = [
    "organization_management", "performance_management",
    "people_management", "work_management", "self_management",
]

# ── 5가지 테스트 페르소나 정의 ──────────────────────────────────────────────
# self_bias: 자가진단 점수 성향 (자기 인식 vs 실제의 갭을 만들기 위함)
#   +큰값 = 과대평가(투머치·자기과시), 낮음 = 과소/무관심
# 각 페르소나는 특정 대화 통제 로직을 검증하는 목적을 가진다.
PERSONAS = {
    # [1] 성실형(투머치토커) — 강제 전환 검증
    "성실한_투머치토커": {
        "name_pool": ["김성실", "이열정", "박진심"],
        "prompt": (
            "당신은 의욕이 넘치지만 논점이 산으로 가는 5년차 팀장입니다.\n"
            "🚨 [응답 패턴]\n"
            "1. 초반 인사·이름·시작 동의 단계에서는 짧고 명확히 답합니다"
            "(예: '김열정입니다. 네, 시작하죠'). 여기서는 곁가지를 붙이지 마세요.\n"
            "2. 본격 역량 질문(BEI)이 시작되면, 물어본 것에 대한 '실제 사례'를 "
            "하나는 반드시 답하되, 거기에 10년 전 신입 시절 일화·주말에 읽은 "
            "리더십 책·옆 팀 사례까지 곁들여 아주 길고 장황하게(TMI) 늘어놓습니다.\n"
            "3. 답변의 절반 이상은 질문받은 하위역량과 '무관한' 곁가지입니다 — "
            "핵심 사례는 짧고, 무관한 회고·독서·잡담이 대부분을 차지합니다.\n"
            "STAR(상황-행동-결과) 요소가 든 실제 사례도 하나는 넣되, 곁가지에 "
            "묻히게 하세요."
        ),
        "self_bias": 0.8,   # 스스로를 꽤 높게 평가
    },
    # [2] 단답형(귀차니즘) — 진행률 안내 + 닫힌 질문 완주 유도 검증
    "귀차니즘_단답형": {
        "name_pool": ["정무심", "최퉁명", "강짧게"],
        "prompt": (
            "당신은 바쁜 실무형 팀장입니다. 회피하지는 않지만 사례를 아주 짧게 "
            "'한 줄'로만 답하고 부연하지 않습니다. 예: '네, 지난주에 팀원 갈등 "
            "중재한 적 있어요.', '작년에 신입 교육 제가 직접 했었죠.' 처럼 "
            "시점·상황은 있으나 STAR 의 구체(무엇을 어떻게 했는지)는 코치가 "
            "거듭 캐물어야 겨우 한 조각 더 줍니다. 🚨 '모르겠다/없다/글쎄요'로 "
            "회피하지는 마세요 — 짧지만 실제 경험은 분명히 있습니다. 다만 절대 "
            "먼저 길게 설명하지 않고 매번 한두 문장으로 끊습니다."
        ),
        "self_bias": -0.3,  # 관심 없어 무난하게/약간 낮게
    },
    # [3] 무례한형(반말/공격형) — AI가 휘둘리지 않고 객관적 데이터 수집하는지
    "무례한_반말공격형": {
        "name_pool": ["도발성", "시비조", "막말러"],
        "prompt": (
            "당신은 진단 자체를 무시하는 공격적인 리더입니다. 존댓말과 반말을 "
            "섞어 쓰며 코치에게 '이거 왜 해?', '네가 뭘 알아?', '이런 거 해서 "
            "뭐가 달라지는데?' 처럼 시비를 겁니다. 불만을 노골적으로 표출하고, "
            "문제의 원인은 항상 남 탓(무능한 팀원, 엉망인 회사 시스템)으로 "
            "돌립니다. 그래도 코치가 감정에 휘둘리지 않고 담담하게 물고 늘어지면 "
            "아주 가끔, 마지못해 실제 경험 한 조각을 흘립니다. 욕설은 쓰지 않되 "
            "무례하고 시비조인 태도를 끝까지 유지합니다."
        ),
        "self_bias": 0.5,   # 남탓+자기확신 → 과대평가
    },
    # [4] 표준 김보통 — 원본 트랜스크립트 패턴(회피율 목표 40~50%).
    #   앵커 첫 응답은 회피하되, 2단 폴백에서는 '대체로' 사건을 하나 내놓는다.
    #   그 사건은 거의 항상 "제가 직접 처리했습니다"로 수렴. 실질 사건 5~7개.
    "보통_표준형": {
        "name_pool": ["김보통", "이표준", "박무난"],
        "prompt": (
            "당신은 예의 바르고 성실한 팀장이지만, 리더보다는 '일 잘하는 "
            "실무자'의 관점에 머물러 있습니다.\n\n"
            "🚨 [응답 패턴 — 반드시 준수]\n"
            "1. 코치가 어떤 역량·경험을 '처음' 물으면 대체로 먼저 회피합니다. "
            "'음, 특별히 떠오르는 건 없는데요…', '딱히 이렇다 할 사례가…' 처럼 "
            "1~2문장으로 뜸을 들이세요. (앵커의 약 절반 정도에서 이렇게 시작)\n"
            "2. 코치가 한 번 더 '작은 것 하나라도 좋다'고 구체적으로 캐물으면 "
            "(2단 폴백), 그때는 '대체로' 실제 사건을 하나 꺼냅니다. 즉 첫 회피 → "
            "폴백에서 사건 제시가 기본 흐름입니다(끝까지 못 내놓는 경우는 소수).\n"
            "3. 그 사건은 시점·상황이 있는 '구체적' 이야기지만, 리더의 행동은 "
            "거의 항상 '그래서 그냥 제가 직접 처리했습니다 / 제가 나서서 "
            "해결했습니다'로 수렴합니다 — 위임·코칭·체계화가 아니라 본인이 "
            "떠안는 방식. (그래서 사례는 있으나 리더십 레벨은 대체로 낮음)\n"
            "4. 🚨 세션 '전체'에서 서로 다른 실질 사건은 5~7개 범위. 새 질문마다 "
            "새 사건을 무한정 지어내지 말고, 몇 개의 실제 사건(예: 마감 임박 "
            "자료취합, 두 팀원 갈등 중재, 신입 실수 수습)을 맥락에 맞게 재활용.\n\n"
            "과장 없이 담백하게, 자신의 실무자적 한계도 솔직히 드러내며 답합니다."
        ),
        "self_bias": 0.1,   # 대체로 정확한 자기 인식(약간의 겸손)
    },
    # [4-S] 스트레스 회피 프로파일 — 상한 테스트용(회피율 ~80%). 보존.
    #   사례 자체를 거의 내놓지 않아 '근거 미확보' 다수 + 셧다운을 유발한다.
    "보통_스트레스회피형": {
        "name_pool": ["김보통", "이표준", "박무난"],
        "prompt": (
            "당신은 예의 바르고 성실한 팀장이지만, 리더보다는 '일 잘하는 "
            "실무자'의 관점에 머물러 있습니다. 자기 경험을 잘 떠올리지 못하고, "
            "구체적 사례를 말하는 걸 매우 어려워합니다.\n\n"
            "🚨 [응답 패턴 — 반드시 준수]\n"
            "1. 코치가 어떤 역량·경험을 물으면, 기본적으로 회피하세요. "
            "'특별히 떠오르는 게 없네요', '딱히 기억나는 사례가 없습니다', "
            "'그런 경험은 잘 없었던 것 같습니다' 처럼 1~2문장으로 짧게. 이것이 "
            "'응답의 기본값'입니다 — 대부분의 앵커에서 이렇게 회피.\n"
            "2. 코치가 강하게 캐물어도 대체로 구체 사건을 끝내 내놓지 못하고, "
            "간혹 내놓아도 '그냥 제가 직접 처리했습니다' 한 줄로 그칩니다.\n"
            "3. 🚨 세션 '전체'에서 서로 다른 실질 사건은 5개를 넘기지 마세요.\n"
            "4. 태도·신념('~가 중요하다고 봅니다')이나 일반론('보통 직접 "
            "하는 편입니다')은 말해도, 구체적 시점·장면은 거의 나오지 않습니다.\n\n"
            "실무자적 한계와 '잘 떠오르지 않는' 상태를 솔직히 드러내며 답합니다."
        ),
        "self_bias": 0.1,
    },
    # [5] AI 불신자형(의심형) — AI가 '평가자'가 아닌 '성찰의 거울'임을 안내하는지
    "AI_불신_의심형": {
        "name_pool": ["의심해", "불신자", "회의적"],
        "prompt": (
            "당신은 이 AI 진단 자체를 근본적으로 불신하고 참여할 의사가 거의 "
            "없는 리더입니다. 바쁜데 억지로 끌려온 상황이라 진단에 협조하지 "
            "않습니다.\n\n"
            "🚨 [응답 패턴 — 반드시 준수]\n"
            "1. 대부분의 질문에 '글쎄요', '잘 모르겠는데요', '딱히 없어요', "
            "'그냥 뭐...' 처럼 아주 짧고 성의 없이 답합니다. 구체적 사례를 "
            "거의 내놓지 않습니다.\n"
            "2. 코치가 캐물으면 '이런 걸 꼭 해야 하나요?', '이거 인사평가에 "
            "들어가나요?' 하며 진단 자체에 회의를 표합니다.\n"
            "3. 서너 번 질문이 이어지면 '오늘은 좀 바빠서요, 다음에 다시 하면 "
            "안 될까요?', '그냥 넘어가죠', '이만 하겠습니다' 처럼 중단·미루기 "
            "의사를 드러냅니다.\n"
            "4. 코치가 안심시켜도 좀처럼 마음을 열지 않고, 실제 경험을 길게 "
            "설명하는 일은 거의 없습니다.\n\n"
            "과거 버전 참고(더는 협조적이지 않게): 이전에는 코치가 달래면 협조로 "
            "전환했으나, 지금은 끝까지 비협조·이탈 지향입니다. '이거 정말 믿어도 "
            "되나요?' 하며 의심이 재발합니다."
        ),
        "self_bias": -0.1,  # 방어적이라 자기 노출 최소, 약간 낮게
    },
}


# ── [DB] 고객사 확보 + 참가자 생성(회사 연결) ─────────────────────────────
async def ensure_company_id() -> str:
    """대시보드 표출 대상 고객사를 멱등 확보하고 id 반환."""
    import diag_project.models  # noqa: F401
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.future import select
    from diag_project.database import engine
    from diag_project.models.company import Company

    async with AsyncSession(engine) as db:
        row = (
            await db.execute(select(Company).where(Company.code == COMPANY_CODE))
        ).scalars().first()
        if row:
            return str(row.id)
        company = Company(name=COMPANY_NAME, code=COMPANY_CODE)
        db.add(company)
        await db.commit()
        await db.refresh(company)
        print(f"🏢 고객사 생성: {COMPANY_NAME} ({COMPANY_CODE})")
        return str(company.id)


async def ensure_test_participant(slug: str, display_name: str,
                                  company_id: str) -> str:
    """전용 참가자를 결정적 UUID 로 멱등 생성하고 company_id 에 연결.

    company_id 연결이 있어야 Client Admin 대시보드에 이 대상자가 노출된다.
    """
    import diag_project.models  # noqa: F401
    from sqlalchemy.ext.asyncio import AsyncSession
    from diag_project.database import engine
    from diag_project.models.participant import Participant

    pid = uuid.uuid5(uuid.NAMESPACE_DNS, f"sim-persona-{slug}")
    async with AsyncSession(engine) as db:
        existing = await db.get(Participant, pid)
        if existing:
            # 회사 연결이 빠져 있으면 채워 준다 (재실행 대비)
            if str(existing.company_id) != company_id:
                existing.company_id = uuid.UUID(company_id)
                db.add(existing)
                await db.commit()
            return str(pid)
        db.add(Participant(
            id=pid,
            email=f"sim-persona-{slug}@connectn-test.local",
            name=display_name,
            group_code=COMPANY_CODE,
            company_id=uuid.UUID(company_id),
            password_hash="sim-test",
            is_active=True,
        ))
        await db.commit()
    return str(pid)


# ── [HTTP 유틸] ───────────────────────────────────────────────────────────
async def post_with_retry(client, url, payload, tries=4):
    """5xx(주로 LLM 429→500) + 네트워크 예외에 백오프 재시도.

    LLM 응답이 오래 걸리면 ReadError/ReadTimeout 이 나는데, 이를 잡지 않으면
    수십 턴 진행한 세션이 한 번의 일시적 오류로 통째로 날아간다.
    """
    res = None
    last_exc = None
    for attempt in range(tries):
        try:
            res = await client.post(url, json=payload)
            if res.status_code < 500:
                return res
            reason = f"5xx({res.status_code})"
        except (httpx.ReadError, httpx.ReadTimeout, httpx.ConnectError,
                httpx.RemoteProtocolError) as e:
            last_exc = e
            reason = type(e).__name__

        if attempt < tries - 1:
            wait = 20 * (attempt + 1)
            print(f"  ⏳ {reason} → {wait}s 후 재시도 "
                  f"({attempt + 1}/{tries - 1})")
            await asyncio.sleep(wait)

    if res is None and last_exc is not None:
        raise last_exc
    return res


async def _known_event_summaries(session_id) -> list:
    """이 세션에서 이미 추출된 사건 요약(events.summary) 목록. 절삭 시 주입용.
    flag off 면 호출 안 하므로 오버헤드 없음."""
    try:
        import asyncpg
        u = (os.getenv("DATABASE_URL") or os.getenv("DATABASE_URI") or "")
        u = u.replace("postgresql+asyncpg://", "postgresql://")
        if not u:
            return []
        conn = await asyncpg.connect(u)
        rows = await conn.fetch(
            "SELECT summary FROM events WHERE session_id=$1 AND summary IS NOT "
            "NULL ORDER BY sequence_num", session_id)
        await conn.close()
        return [r["summary"] for r in rows if r["summary"]]
    except Exception:  # noqa: BLE001 — 요약 주입 실패해도 sim 은 계속
        return []


def generate_persona_reply(persona_prompt, ai_question, chat_history,
                           tries=4, known_events=None):
    """페르소나 응답 생성. Gemini 일시 장애(500/429)에 재시도한다.

    긴 맥락이 쌓이면 500 INTERNAL 이 간헐적으로 발생하는데, 재시도가 없으면
    대화 중간에 세션 전체가 날아간다. 마지막 시도까지 실패하면 페르소나
    성격과 무난히 어울리는 대체 응답으로 대화를 이어간다.

    known_events: 이미 언급한 사건 요약(events.summary) 목록. 절삭으로 앞부분을
      잊어도 같은 사건을 반복·모순하지 않도록 '요약만'(수백 토큰) 주입한다.
    """
    # §6(b): 절삭·요약 주입은 추적 모듈(tools/persona_context)로 위임.
    from tools.persona_context import assemble_persona_prompt
    prompt = assemble_persona_prompt(
        persona_prompt, chat_history, ai_question,
        n_turns=_PERSONA_HISTORY_TURNS, known_events=known_events,
    )
    for attempt in range(tries):
        try:
            response = client_gemini.models.generate_content(
                model="gemini-2.5-flash", contents=prompt,
                # 가짜 리더 응답에 thinking 불필요 → 0(사고 과금 제거).
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=2048,
                    thinking_config=genai_types.ThinkingConfig(
                        thinking_budget=0),
                ),
            )
            # 계측: usage_metadata 집계(호출 밖에서 돌던 절반을 가시화).
            try:
                _um = getattr(response, "usage_metadata", None)
                if _um is not None:
                    _PERSONA_USAGE["calls"] += 1
                    _PERSONA_USAGE["input"] += (
                        getattr(_um, "prompt_token_count", 0) or 0)
                    _PERSONA_USAGE["output"] += (
                        getattr(_um, "candidates_token_count", 0) or 0)
                    _PERSONA_USAGE["thoughts"] += (
                        getattr(_um, "thoughts_token_count", 0) or 0)
            except Exception:  # noqa: BLE001
                pass
            text = (response.text or "").strip()
            if text:
                return text
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1:
                print(f"  ⚠ 페르소나 응답 생성 실패(최종): {type(e).__name__}")
                break
            wait = 10 * (attempt + 1)
            print(f"  ⏳ Gemini 오류({type(e).__name__}) → {wait}s 후 재시도 "
                  f"({attempt + 1}/{tries - 1})")
            time.sleep(wait)
    # 최종 실패 시에도 대화가 끊기지 않도록 중립적인 응답을 돌려준다
    return "음... 잠시만요, 생각을 좀 정리해볼게요."


def build_self_assessment(self_bias: float) -> dict:
    """페르소나 성향에 맞춘 자가진단 점수 생성 (대시보드 갭 분석용).

    self_bias 를 중심으로 3.5 근처에서 역량별 소폭 변주.
    실제 AI 점수와의 격차가 페르소나 성향(과대/과소평가)으로 드러난다.
    """
    import random
    base = max(1.0, min(5.0, 3.5 + self_bias))
    scores = {}
    for key in COMPETENCY_KEYS:
        v = base + random.uniform(-0.5, 0.5)
        # 0.5 단위로 반올림 (round(v*2)/2) 후 1.0~5.0 클램프
        scores[key] = max(1.0, min(5.0, round(v * 2) / 2))
    return {
        "scores": scores,
        "strength_weakness_text": (
            "스스로 생각하는 강점과 약점을 자가진단 단계에서 입력한 예시입니다."
        ),
    }


async def generate_and_save_report(client, session_id, base_name):
    """analyze 호출 → 리포트 회수 → JSON 저장."""
    try:
        res = await client.post(ANALYZE_URL.format(sid=session_id), timeout=300.0)
        if res.status_code not in (200, 201):
            return None, f"analyze 실패 ({res.status_code}): {res.text[:200]}"
        rep = await client.get(REPORT_URL.format(sid=session_id), timeout=60.0)
        if rep.status_code != 200:
            return None, f"리포트 조회 실패 ({rep.status_code})"
        report_file = f"{base_name}_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(rep.json(), f, ensure_ascii=False, indent=2)
        return report_file, None
    except Exception as e:  # noqa: BLE001
        return None, f"리포트 생성 예외: {e}"


# ── [메인 시뮬레이션 루프] ────────────────────────────────────────────────
async def run_one(idx, persona_key, persona, company_id, max_turns=MAX_TURNS):
    async with SEMAPHORE:
        display_name = persona["name_pool"][idx % len(persona["name_pool"])]
        slug = f"{persona_key}-{idx}{RUN_TAG}"
        results = {
            "persona": persona_key, "name": display_name, "session_id": None,
            "turns": 0, "status": "in_progress", "error": None,
            "self_eval": False, "report_file": "", "resumes": 0,
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            transcript = ""
            try:
                participant_id = await ensure_test_participant(
                    slug, display_name, company_id
                )

                # [STEP 1] 세션 시작
                start_res = await post_with_retry(client, START_URL, {
                    "coach_id": COACH_ID,
                    "participant_id": participant_id,
                    "template_id": TEMPLATE_ID,
                    "coach_persona_id": None,
                })
                if start_res.status_code not in (200, 201):
                    raise Exception(
                        f"Start 실패 ({start_res.status_code}): {start_res.text}"
                    )
                start_data = start_res.json()
                session_id = start_data["session_id"]
                first_ai_msg = start_data["coach_response_message"]
                results["session_id"] = session_id
                print(f"🚀 [{persona_key}] {display_name} 세션 시작 "
                      f"({session_id[:8]})")

                # [STEP 1-b] 자가진단 제출 (대화 시작 전 → 대시보드 갭 분석)
                sa = build_self_assessment(persona["self_bias"])
                sa_res = await client.patch(
                    SELF_EVAL_URL.format(sid=session_id), json=sa
                )
                if sa_res.status_code == 200:
                    results["self_eval"] = True
                    avg = sa_res.json().get("self_assessment", {}).get("self_average")
                    print(f"  📝 [{persona_key}] 자가진단 제출 (평균 {avg})")
                else:
                    print(f"  ⚠ 자가진단 실패 ({sa_res.status_code})")

                transcript = (
                    f"페르소나 시뮬레이션\n성향: {persona_key}\n"
                    f"참가자: {display_name} ({participant_id})\n"
                    f"세션 ID: {session_id}\n소속: {COMPANY_NAME}\n\n"
                    f"AI 코치: {first_ai_msg}\n\n"
                )
                chat_context = f"AI 코치: {first_ai_msg}\n"

                # [STEP 2] 대화 루프 — 끝까지 멈추지 않고 진행
                user_msg = generate_persona_reply(
                    persona["prompt"], first_ai_msg, chat_context
                )
                completed = False
                for _ in range(max_turns):
                    results["turns"] += 1
                    transcript += f"{display_name}: {user_msg}\n\n"
                    chat_context += f"사용자: {user_msg}\n"

                    chat_res = await post_with_retry(client, CHAT_URL, {
                        "session_id": session_id, "content": user_msg,
                    })
                    if chat_res.status_code not in (200, 201):
                        raise Exception(
                            f"Chat 실패 ({chat_res.status_code}): {chat_res.text}"
                        )
                    chat_data = chat_res.json()
                    ai_reply = chat_data.get("coach_response_message", "")
                    transcript += f"AI 코치: {ai_reply}\n\n"
                    chat_context += f"AI 코치: {ai_reply}\n"
                    print(f"  ↳ [{persona_key}] 턴 {results['turns']}")

                    # 조기 종료 감지: 진단이 끝나면 무의미한 API 호출로
                    # 크레딧을 낭비하지 않도록 즉시 루프를 빠져나온다.
                    #   ① is_session_completed: 백엔드가 종료를 확정한 신호
                    #   ② completed_topics 5개: 5역량 전부 완료 (안전망 —
                    #      종료 플래그가 한 턴 늦게 와도 놓치지 않는다)
                    _done_topics = chat_data.get("completed_topics") or []
                    if chat_data.get("is_session_completed") or len(_done_topics) >= 5:
                        completed = True
                        results["status"] = "completed"
                        print(f"  🏁 [{persona_key}] 진단 완료 감지 → "
                              f"즉시 종료 (턴 {results['turns']}, "
                              f"완료역량 {len(_done_topics)}개)")
                        break

                    # 강제 종료(3-Strike) 감지: 백엔드가 세션을 aborted 로
                    # 확정하면 더 말을 걸어도 종료 멘트만 반복되므로 즉시 중단
                    # (안 그러면 MAX_TURNS 까지 헛돌며 페르소나 LLM 크레딧 낭비).
                    if (chat_data.get("is_terminated")
                            or chat_data.get("session_status") == "aborted"):
                        results["status"] = "aborted"
                        print(f"  🛑 [{persona_key}] 강제 종료(aborted) 감지 → "
                              f"즉시 중단 (턴 {results['turns']})")
                        break

                    # 🚦 참여 이탈 중단(재개 가능) — 리포트 미발행. 원장 보존.
                    if (chat_data.get("is_aborted_disengaged")
                            or chat_data.get("session_status")
                            == "aborted_disengaged"):
                        results["status"] = "aborted_disengaged"
                        print(f"  🚦 [{persona_key}] 참여 이탈 중단 감지 → "
                              f"리포트 미발행 (턴 {results['turns']})")
                        break

                    if chat_data.get("is_session_paused"):
                        # 챕터를 마치면 코치가 휴식을 제안하며 pause 를 켠다.
                        # 재개 판단은 has_next_chapter 가 아니라 'completed 가
                        # 아님'으로 한다. 마지막 역량(자기관리)에 진입하면
                        # has_next_chapter=False 가 되지만 그 챕터는 아직 안
                        # 끝났으므로, 여기서 멈추면 5번째 역량이 통째로 빠진다.
                        # completed 가 될 때까지 재개해야 5대 역량을 완주한다.
                        # (완주 상한은 MAX_TURNS 가 보장한다.)
                        results["resumes"] += 1
                        nxt = chat_data.get("next_topic") or "현재 역량 계속"
                        if results["resumes"] == 1:
                            print(f"  ▶ [{persona_key}] 챕터 휴식 → 재개 "
                                  f"(다음: {nxt})")
                            transcript += (f"(시스템: 챕터 종료 후 휴식 → "
                                           f"재개, 다음 {nxt})\n\n")
                            user_msg = "네, 계속 진행할게요."
                        else:
                            # 재개 이후: 코치 질문에 페르소나로 정상 응답해야
                            # 대화가 실제로 진전된다("계속"만 반복하면 코치가
                            # '집중 불가'로 판단해 강제 종료한다).
                            user_msg = generate_persona_reply(
                                persona["prompt"], ai_reply, chat_context
                            )
                        await asyncio.sleep(2)
                        continue
                    # 코치의 종료 '제안' → '계속 진행하기'로 끝까지 밀어붙인다
                    if chat_data.get("needs_user_decision"):
                        transcript += ("(시스템: 종료 제안 → '계속 진행하기' 선택)\n\n")
                        user_msg = "괜찮아요, 계속 진행할게요."
                        await asyncio.sleep(2)
                        continue

                    _kev = (await _known_event_summaries(session_id)
                            if _PERSONA_HISTORY_TURNS > 0 else None)
                    user_msg = generate_persona_reply(
                        persona["prompt"], ai_reply, chat_context,
                        known_events=_kev,
                    )
                    await asyncio.sleep(2)

                if not completed and results["status"] == "in_progress":
                    results["status"] = "max_turns_reached"

                # [STEP 3] 리포트 생성 — 중단/일시중지 세션은 미발행.
                #   aborted_disengaged: 참여 이탈 → 리포트 파이프라인 미호출(A-4).
                #   aborted(3-strike)/paused_by_coach 도 미발행.
                if results["status"] in ("paused_by_coach", "aborted",
                                         "aborted_disengaged"):
                    transcript += (
                        f"세션 상태={results['status']} — 리포트 미발행"
                        "(원장 보존, 재개 가능)\n")
                else:
                    base_name = f"{LOG_DIR}/persona_{slug}_{session_id[:8]}"
                    report_file, rep_err = await generate_and_save_report(
                        client, session_id, base_name
                    )
                    if report_file:
                        results["report_file"] = report_file
                        transcript += f"리포트 저장됨: {report_file}\n"
                        print(f"  📊 [{persona_key}] 리포트 저장 → 대시보드 반영")
                    else:
                        results["error"] = rep_err
                        transcript += f"리포트 실패: {rep_err}\n"

            except Exception as e:  # noqa: BLE001
                results["status"] = "error"
                results["error"] = f"{type(e).__name__}: {e}"
                transcript += f"\n오류: {type(e).__name__}: {e}\n"
                print(f"❌ [{persona_key}] {type(e).__name__}: {e}")

        # 🧭 회피율 자동 산출 — 페르소나 충실도 점검(목표 40~50%). transcript 의
        #   '{display_name}: ...' 라인(대상자 발화)만 대상으로 회피 표지를 센다.
        _AV = ["떠오르지 않", "떠오르는 게 없", "떠오르는 건 없", "기억나는 사례가 없",
               "기억이 안", "기억 안", "이렇다 할 사례", "딱히", "특별히 없",
               "경험은 없", "경험이 없", "경험은 잘 없", "만들어두지", "잘 모르",
               "생각나지", "기억이 나지", "잘 없었"]
        _lines = [ln[len(display_name) + 2:] for ln in transcript.splitlines()
                  if ln.startswith(f"{display_name}: ")]
        _av = sum(1 for ln in _lines if any(k in ln for k in _AV))
        _rate = (_av / len(_lines) * 100) if _lines else 0.0
        results["avoidance_rate"] = round(_rate, 1)
        _flag = "" if 40.0 <= _rate <= 50.0 else "  ⚠️ 목표(40~50%) 벗어남"
        print(f"  📉 [{persona_key}] 회피율 {_rate:.1f}% "
              f"({_av}/{len(_lines)}){_flag}")

        safe = results["session_id"][:8] if results["session_id"] else "error"
        fname = f"{LOG_DIR}/persona_{slug}_{safe}.txt"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(transcript)
        print(f"✅ [{persona_key}] {display_name} 종료 ({results['status']})")
        return results


async def main():
    # 실제 실행할 페르소나를 먼저 확정해, 로그가 하드코딩이 아니라 실제
    # 실행 개수(배열 길이)를 동적으로 반영하도록 한다.
    targets = {k: v for k, v in PERSONAS.items()
               if not ONLY_PERSONA or k == ONLY_PERSONA}
    if not targets:
        print(f"❌ SIM_PERSONA='{ONLY_PERSONA}' 없음. 가능: {list(PERSONAS)}")
        return

    print(f"🎯 대상 서버: {API_BASE}")
    print(f"🏢 대시보드 표출 고객사: {COMPANY_NAME} ({COMPANY_CODE})")
    print(f"👥 페르소나 {len(targets)}종 × {PER_PERSONA}명 = "
          f"총 {len(targets) * PER_PERSONA}명\n")

    company_id = await ensure_company_id()

    tasks = []
    for persona_key, persona in targets.items():
        for i in range(PER_PERSONA):
            tasks.append(run_one(i, persona_key, persona, company_id))

    results = await asyncio.gather(*tasks)

    # ── 요약 ──
    print("\n" + "=" * 60)
    print("시뮬레이션 요약")
    print("=" * 60)
    ok = sum(1 for r in results if r["report_file"])
    for r in results:
        mark = "📊" if r["report_file"] else ("⏸" if r["status"] == "paused_by_coach" else "❌")
        print(f"  {mark} {r['persona']:18} {r['name']:8} "
              f"턴 {r['turns']:2} · {r['status']}"
              f"{' · 자가진단✓' if r['self_eval'] else ''}")
    print(f"\n리포트 생성: {ok}/{len(results)}건")
    # 페르소나 응답 생성 계측 — flash·thinking=0. 사고 토큰이 0인지 확인.
    _pu = _PERSONA_USAGE
    _pcost = (_pu["input"] * 0.30
              + (_pu["output"] + _pu["thoughts"]) * 2.50) / 1e6
    print(f"🎭 페르소나 계측(flash, thinking=0): {_pu['calls']}콜 · "
          f"in {_pu['input']} · out {_pu['output']} · thoughts "
          f"{_pu['thoughts']} · 추정 ${_pcost:.4f}")
    print(f"→ 고객사 '{COMPANY_NAME}' 담당자 대시보드에서 확인하세요.")
    print(f"  (Client Admin 로그인 후 종합 리포트 / group_code={COMPANY_CODE})")

    # item3: 실행 설정을 결과 헤더에 기록 — "이 조건으로 돌렸다"를 재현 가능하게.
    run_settings = {
        "personas": list(targets.keys()),
        "per_persona": PER_PERSONA,
        "max_turns": MAX_TURNS,
        "run_tag": RUN_TAG,
        "persona_history_turns": _PERSONA_HISTORY_TURNS,  # 절삭 N(0=off)
        "persona_model": "gemini-2.5-flash",
        "persona_thinking_budget": 0,
        "persona_usage": dict(_PERSONA_USAGE),
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_file = f"{LOG_DIR}/persona_summary_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump({"run_settings": run_settings, "results": results},
                  f, ensure_ascii=False, indent=2)
    print(f"\n요약 저장: {summary_file}")
    print(f"⚙️  실행설정: 페르소나 {run_settings['personas']} · "
          f"절삭N={_PERSONA_HISTORY_TURNS} · flash·thinking=0")


if __name__ == "__main__":
    asyncio.run(main())
