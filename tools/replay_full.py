"""5챕터 완주 재생 러너 (2026-10-28 P0): 코치 K개 병렬 서버 + 클라이언트, 입력 파일을 끝까지(세션 완료까지) 재생.

용법: python replay_full.py TAG INPUT_JSON COACHES PROVIDER [REPEAT]
  예: python replay_full.py p0a ../new_diagnosis_api/tests/fixtures/fixture_daniel_full_users.json 2,3,4,5,6 gemini 1
출력: replay_result_{TAG}_{coach}.json (transcript_lint 입력 형식), server_{TAG}_{coach}.log, prompt_capture_{TAG}_{coach}.jsonl
재생 규칙: 챕터 전환 팝업(is_topic_completed & has_next_chapter) → '네, 다음으로 이어가 주세요.',
          일시정지 제안(needs_user_decision) → '괜찮아요, 계속 진행할게요.', 세션 완료(is_session_completed) → 종료.
          입력이 바닥나면 보충 입력(FILLERS)을 순환한다(5챕터 완주가 목적).
"""
import asyncio, json, os, sqlite3, subprocess, sys, time, uuid
import httpx

W = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/daniel/python_new/new_diagnosis_api"
PY = sys.executable
TAG, INPUT = sys.argv[1], sys.argv[2]
COACHES = [c for c in sys.argv[3].split(",") if c]
PROVIDER = sys.argv[4] if len(sys.argv) > 4 else "gemini"
REPEAT = int(sys.argv[5]) if len(sys.argv) > 5 else 1
PORT_BASE = int(os.environ.get("RP_PORT_BASE", "8060"))
TEMPLATE_ID = "10000000-0000-0000-0000-000000000008"
COACH_FILE_KEY = {"1": "ella", "2": "jessica", "3": "olivia", "4": "daniel", "5": "michael", "6": "lucas"}   # INPUT 에 {name} 자리표시자
NEXT = "네, 다음으로 이어가 주세요."
CONTINUE = "괜찮아요, 계속 진행할게요."
FILLERS = [   # (2026-10-29) 25개 — 5개 순환 시 2바퀴째부터 INPUT_DUPLICATE(자카드 0.6) 로 세션이 멈춰 160턴 상한까지 공회전(s291 Olivia)
    "작년 하반기에 신규 서비스 런칭 일정이 두 달 밀렸을 때, 제가 직접 각 파트장과 주간 점검 회의를 새로 만들어서 병목을 하나씩 풀었습니다. 결과적으로 한 달 안에 일정을 회복했어요.",
    "올해 초 팀원 두 명이 같은 고객 건을 두고 서로 책임을 미루는 일이 있었는데, 제가 두 사람을 따로 만나 사실관계를 듣고 역할 경계를 문서로 정리해 줬습니다. 그 뒤로는 비슷한 충돌이 없었습니다.",
    "지난달 분기 목표를 다시 세울 때, 매출 숫자만 보던 방식을 바꿔 고객 재구매율을 핵심 지표로 넣었습니다. 팀원들에게 왜 바꾸는지 설명하는 자리를 두 번 가졌고, 다음 분기 재구매율이 8% 올랐습니다.",
    "제가 번아웃이 왔다고 느꼈던 게 작년 11월이었는데, 그때 주 1회는 업무 외 시간을 비우기로 정하고 팀에도 공유했습니다. 두 달쯤 지나니 집중력이 돌아왔어요.",
    "신입이 실수로 고객 데이터를 잘못 보낸 적이 있어서, 제가 먼저 고객에게 사과 전화를 하고 신입과는 재발 방지 체크리스트를 같이 만들었습니다. 그 신입은 지금 그 체크리스트 담당자예요.",
    "재작년 봄에 협력사 납품이 세 번 연속 지연됐을 때, 담당자를 바꾸는 대신 제가 협력사 대표를 직접 찾아가 생산 일정표를 같이 다시 짰습니다. 그 뒤 반년 동안 지연이 한 번도 없었어요.",
    "팀 회의가 늘 한 시간을 넘기길래 안건을 전날 공유하고 결정 사항만 다루는 방식으로 바꿨습니다. 처음엔 어색해했지만 세 주 만에 회의가 25분으로 줄었어요.",
    "지난 겨울 핵심 개발자가 갑자기 퇴사 의사를 밝혔을 때, 붙잡기보다 인수인계 기간을 넉넉히 잡고 후임이 옆에서 두 달간 같이 일하도록 했습니다. 서비스 장애 없이 넘어갔습니다.",
    "작년 연말 평가에서 한 팀원에게 낮은 등급을 줘야 했는데, 면담 전에 분기별 기록을 모아 구체적인 장면으로 설명했습니다. 그 팀원이 올해는 스스로 월간 점검을 하겠다고 먼저 제안했어요.",
    "본부장이 갑자기 새 프로젝트를 밀어붙였을 때, 기존 일정에 미칠 영향을 숫자로 정리해 보고하고 두 건 중 하나를 미루는 안을 제시했습니다. 결국 제 안대로 조정됐어요.",
    "올해 여름 고객사 담당자가 공개 자리에서 저희 팀을 심하게 질책한 적이 있습니다. 그 자리에서는 사실만 확인하고, 다음 날 따로 만나 원인과 재발 방지책을 설명했어요. 계약은 유지됐습니다.",
    "팀원들이 서로 뭘 하는지 모른다는 말이 나와서, 매주 금요일 15분짜리 공유 시간을 만들고 제가 먼저 제 실수담부터 이야기했습니다. 석 달 뒤에는 팀원들이 먼저 도움을 청하기 시작했어요.",
    "작년에 예산이 30% 깎였을 때, 모든 사업을 조금씩 줄이는 대신 성과가 낮은 두 사업을 아예 접고 나머지에 집중했습니다. 팀 안에서 반발이 있었지만 연말 성과는 전년보다 좋았습니다.",
    "제가 결정을 미루는 버릇이 있다는 피드백을 받고, 큰 결정은 48시간 안에 내리기로 스스로 규칙을 정했습니다. 수첩에 결정 날짜를 적어 두는 식으로 반년째 지키고 있어요.",
    "경력 입사자가 기존 팀원들과 겉돌 때, 그 사람에게 신규 과제의 설계 부분을 맡기고 기존 팀원 한 명을 짝으로 붙였습니다. 두 달 뒤 두 사람이 같이 사내 발표를 했어요.",
    "지난 분기 장애 보고가 늦어 고객 불만이 커진 일이 있어서, 장애 발생 10분 안에 1차 공지를 내는 규칙을 만들고 제가 첫 두 번은 직접 공지를 썼습니다. 이후 불만 접수가 절반으로 줄었습니다.",
    "팀원 한 명이 야근을 계속 자청하길래 따로 불러 이유를 물었더니 업무 배분이 한쪽으로 쏠려 있었습니다. 그 주에 업무를 다시 나누고, 매달 배분표를 같이 보기로 했어요.",
    "새 평가 제도를 도입할 때 위에서 내려온 안을 그대로 적용하지 않고, 팀원 세 명과 한 달간 시범 운영해 문제점을 먼저 찾았습니다. 그 결과를 반영해 수정안을 올렸고 채택됐어요.",
    "올봄 제 판단 착오로 납기를 놓친 적이 있는데, 팀에 먼저 제 실수라고 밝히고 고객에게도 제가 직접 사과했습니다. 그 뒤 일정 검토를 두 명이 교차 확인하는 절차를 넣었어요.",
    "매출이 석 달 연속 떨어졌을 때, 원인을 영업 탓으로 돌리지 않고 고객 열 곳을 제가 직접 방문해 이야기를 들었습니다. 거기서 나온 요구를 제품에 반영해 다음 분기에 회복했어요.",
    "팀 내 두 파트가 데이터 형식을 두고 반년 넘게 다투고 있어서, 제가 양쪽 실무자를 한자리에 모아 하루 동안 공통 형식을 정하게 했습니다. 그날 이후로는 같은 문제로 회의한 적이 없습니다.",
    "작년에 몸이 안 좋아 집중이 안 되던 시기에, 아침 한 시간은 회의를 잡지 않고 가장 중요한 일 하나만 하는 식으로 하루를 다시 짰습니다. 지금도 그 습관을 유지하고 있어요.",
    "후배 리더가 팀원과 갈등을 겪을 때 대신 해결해 주지 않고, 매주 한 번 상황을 같이 복기하며 다음 대화를 준비하게 했습니다. 두 달쯤 지나 그 후배가 스스로 면담을 마무리했어요.",
    "회사 방향이 바뀌어 우리 팀 역할이 축소됐을 때, 팀원들에게 사실을 숨기지 않고 설명한 뒤 새 역할 후보 세 가지를 같이 정리했습니다. 그중 하나가 지금 팀의 주 업무가 됐습니다.",
    "협업 부서가 요청을 늘 급하게 던져서, 요청 양식과 최소 리드타임을 정해 그 부서장과 직접 합의했습니다. 처음 한 달은 마찰이 있었지만 이후 급한 요청이 눈에 띄게 줄었어요.",
]


def start_server(coach: str, port: int):
    # FM_PREWARM=0: 대화 재생에서는 챕터 종료 사전분석(Sonnet 심층분석·게이트)을 돌리지 않는다 — 세션당 LLM 호출의 약 1/5, 비용의 대부분.
    env = dict(os.environ, RP_PROVIDER=PROVIDER, RP_PORT=str(port), RP_TAG=f"{TAG}_{coach}", RP_REPO=REPO, FM_PREWARM=os.environ.get("FM_PREWARM", "0"))
    for f in (f"{W}/replay_{TAG}_{coach}.db", f"{W}/prompt_capture_{TAG}_{coach}.jsonl"):
        if os.path.exists(f):
            os.remove(f)
    return subprocess.Popen([PY, f"{W}/replay_server.py"], env=env, cwd=REPO,
                            stdout=open(f"{W}/server_{TAG}_{coach}.log", "w"), stderr=subprocess.STDOUT)


async def run_client(coach: str, port: int, inputs: list[str]):
    if "{name}" in INPUT:   # 코치별 자기 세션 입력
        inputs = json.load(open(INPUT.format(name=COACH_FILE_KEY[coach]), encoding="utf-8"))
    base = f"http://127.0.0.1:{port}/api/v1"
    db = f"{W}/replay_{TAG}_{coach}.db"
    coach_id = f"10000000-0000-0000-0000-0000000000{int(coach) + 10:02d}"
    async with httpx.AsyncClient(timeout=300.0) as c:
        for _ in range(180):
            try:
                await c.get(f"http://127.0.0.1:{port}/docs", timeout=2.0)
                break
            except Exception:
                await asyncio.sleep(1)
        # 참가자 행(로그인 생략) — 서버의 sqlite 에 직접
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
        sys.path.insert(0, REPO)
        from diag_project.database import async_session
        from diag_project.models.participant import Participant
        pid = uuid.uuid4()
        for _try in range(30):
            try:
                async with async_session() as s:
                    s.add(Participant(id=pid, email=f"{TAG}-{coach}-{pid.hex[:6]}@local.test", name="박기진", is_active=True))
                    await s.commit()
                break
            except Exception as _e:   # 테이블 미생성·잠금 — 잠시 뒤 재시도
                await asyncio.sleep(1)
        else:
            raise RuntimeError("participant insert 실패")
        r = await c.post(f"{base}/diagnoses/start", json={"coach_id": coach_id, "participant_id": str(pid), "template_id": TEMPLATE_ID})
        r.raise_for_status()
        sid = r.json()["session_id"]
        queue = list(inputs)
        fill_i = 0
        turns = 0
        t0 = time.time()
        while turns < 160:
            if queue:
                u = queue.pop(0)
            else:
                u = FILLERS[fill_i % len(FILLERS)]
                fill_i += 1
            r = await c.post(f"{base}/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": u})
            turns += 1
            if r.status_code >= 400:
                print(f"!! {TAG}_{coach} turn {turns} HTTP {r.status_code}: {r.text[:300]}")
                break
            body = r.json()
            if body.get("is_session_completed") or body.get("is_terminated"):
                break
            if body.get("needs_user_decision"):
                await c.post(f"{base}/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": CONTINUE})
            elif body.get("is_topic_completed") and body.get("has_next_chapter"):
                await c.post(f"{base}/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": NEXT})
        elapsed = time.time() - t0
    con = sqlite3.connect(db)
    sid_h = sid.replace("-", "")
    rows = con.execute("select turn_index, role, chapter, probe_type_used, instruction_used, content from chat_messages "
                       "where session_id=? order by created_at, turn_index", (sid_h,)).fetchall()
    sad = con.execute("select self_assessment_data, status, current_topic from diagnosis_sessions where id=?", (sid_h,)).fetchone()
    con.close()
    store = json.loads(sad[0]) if sad and sad[0] else {}
    gl = {(g.get("ch"), g.get("t")): g for g in store.get("guard_log", []) if isinstance(g, dict)}   # t 는 챕터별 번호 → (챕터, t) 키
    out = [{"t": t, "role": role, "chapter": ch, "probe": probe, "instr": instr, "content": content,
            "guard": (gl.get((ch, t)) if role == "model" else None)} for t, role, ch, probe, instr, content in rows]
    json.dump({"session": sid, "coach": coach, "provider": PROVIDER, "status": sad[1] if sad else None,
               "topic": sad[2] if sad else None, "elapsed_s": round(elapsed), "rows": out},
              open(f"{W}/replay_result_{TAG}_{coach}.json", "w"), ensure_ascii=False, indent=1)
    print(f"=== {TAG}_{coach} coach={coach} status={sad[1] if sad else '?'} topic={sad[2] if sad else '?'} rows={len(rows)} {elapsed:.0f}s")


TAG0 = TAG


async def main():
    inputs = [] if "{name}" in INPUT else json.load(open(INPUT, encoding="utf-8"))
    for rep in range(REPEAT):
        tag_rep = TAG0 if REPEAT == 1 else f"{TAG0}{rep + 1}"   # (2026-10-29) TAG 를 덮어쓰면 s301→s3012→… 로 누적되던 버그
        globals()["TAG"] = tag_rep
        servers = {}
        for i, coach in enumerate(COACHES):
            port = PORT_BASE + i
            servers[coach] = (start_server(coach, port), port)
        await asyncio.sleep(3)
        results = await asyncio.gather(*[run_client(coach, port, inputs) for coach, (_, port) in servers.items()], return_exceptions=True)
        for coach, res in zip(servers.keys(), results):
            if isinstance(res, Exception):
                print(f"!! {tag_rep}_{coach} 클라이언트 실패: {type(res).__name__}: {str(res)[:200]}")
        for proc, _ in servers.values():
            proc.terminate()
        await asyncio.sleep(2)
    print("ALL DONE")


asyncio.run(main())
