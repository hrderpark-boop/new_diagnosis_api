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
FILLERS = [
    "작년 하반기에 신규 서비스 런칭 일정이 두 달 밀렸을 때, 제가 직접 각 파트장과 주간 점검 회의를 새로 만들어서 병목을 하나씩 풀었습니다. 결과적으로 한 달 안에 일정을 회복했어요.",
    "올해 초 팀원 두 명이 같은 고객 건을 두고 서로 책임을 미루는 일이 있었는데, 제가 두 사람을 따로 만나 사실관계를 듣고 역할 경계를 문서로 정리해 줬습니다. 그 뒤로는 비슷한 충돌이 없었습니다.",
    "지난달 분기 목표를 다시 세울 때, 매출 숫자만 보던 방식을 바꿔 고객 재구매율을 핵심 지표로 넣었습니다. 팀원들에게 왜 바꾸는지 설명하는 자리를 두 번 가졌고, 다음 분기 재구매율이 8% 올랐습니다.",
    "제가 번아웃이 왔다고 느꼈던 게 작년 11월이었는데, 그때 주 1회는 업무 외 시간을 비우기로 정하고 팀에도 공유했습니다. 두 달쯤 지나니 집중력이 돌아왔어요.",
    "신입이 실수로 고객 데이터를 잘못 보낸 적이 있어서, 제가 먼저 고객에게 사과 전화를 하고 신입과는 재발 방지 체크리스트를 같이 만들었습니다. 그 신입은 지금 그 체크리스트 담당자예요.",
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
    gl = {g.get("t"): g for g in store.get("guard_log", []) if isinstance(g, dict)}
    out = [{"t": t, "role": role, "chapter": ch, "probe": probe, "instr": instr, "content": content,
            "guard": (gl.get(t) if role == "model" else None)} for t, role, ch, probe, instr, content in rows]
    json.dump({"session": sid, "coach": coach, "provider": PROVIDER, "status": sad[1] if sad else None,
               "topic": sad[2] if sad else None, "elapsed_s": round(elapsed), "rows": out},
              open(f"{W}/replay_result_{TAG}_{coach}.json", "w"), ensure_ascii=False, indent=1)
    print(f"=== {TAG}_{coach} coach={coach} status={sad[1] if sad else '?'} topic={sad[2] if sad else '?'} rows={len(rows)} {elapsed:.0f}s")


async def main():
    inputs = [] if "{name}" in INPUT else json.load(open(INPUT, encoding="utf-8"))
    for rep in range(REPEAT):
        tag_rep = TAG if REPEAT == 1 else f"{TAG}{rep + 1}"
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
