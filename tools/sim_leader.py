#!/usr/bin/env python
"""(2026-11-04 BEI) 시뮬 리더 — 고정 설정(교육팀장·팀원 4명·사례 6개)으로 코치와 번갈아 챕터를 완주한다.

리더 답은 Haiku(세션 provider 와 같은 호출 계층, temperature 0) 또는 --stub 결정론 스크립트(LLM 0콜). 묻는 슬롯의 사실만 2~4문장으로 답하고,
묻지 않은 슬롯은 먼저 말하지 않는다(코치가 끌어내야 6/6 이 된다). short_every 번째 답은 "네." 류 단답(시드 고정).

용법:
  python tools/sim_leader.py TAG --coaches 5,2 [--chapters 1] [--provider claude] [--stub] [--profile tools/sim_profiles/edu_team_lead.json]
    · 코치마다 sqlite 서버를 포트 RP_PORT_BASE(기본 8070)+i 에 띄우고(FM_PREWARM=0, 사전분석 없음) 교대로 턴을 보낸다.
    · --stub: 서버도 FM_LLM_STUB=1 (코치·슬롯 판정·매핑 전부 스텁) — 1단계 스모크·pytest 용.
출력(현재 디렉터리 또는 SIM_OUT):
  sim_result_{TAG}_{coach}.json  transcript_lint 입력 형식 + "ledger"(사례 원장) + "truth"(사례별 정답 하위역량) + "cost_usd"
  sim_server_{TAG}_{coach}.log · sim_usage_{TAG}_{coach}.jsonl(호출별 토큰)
전문 보기: python tools/sim_leader.py --dump sim_result_TAG_5.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMPLATE_ID = "10000000-0000-0000-0000-000000000008"
NEXT = "네, 다음으로 이어가 주세요."
CONTINUE = "괜찮아요, 계속 진행할게요."
ONBOARDING = ["안녕하세요, 박기진입니다."]   # 이름만 고정 — 스몰톡·역할·기대는 코치 턴 종류(probe ROLE_ASK 등)로 답한다
SLOT_ORDER = ("context", "action", "reaction", "result", "criterion", "reflection")
# 스텁 리더: 코치 질문의 낱말로 어느 슬롯을 묻는지 고른다(결정론). 못 고르면 아직 말 안 한 다음 슬롯.
_SLOT_CUES = [
    ("reflection", re.compile(r"다시 한다면|돌아보|배운|배우신|아쉬|바꾸고 싶|다르게 하")),
    ("criterion", re.compile(r"기준|이유|왜 |어떤 판단|고르신|선택하신|결정하신 근거|트레이드|버린")),
    ("result", re.compile(r"결과|달라|그 뒤|이후|어떻게 됐|성과|바뀌었|변화")),
    ("reaction", re.compile(r"반응|받아들|어떻게 들|표정|팀원들은|상대|분위기")),
    ("action", re.compile(r"하셨|무엇을|뭘 |어떻게 (대응|접근|움직|진행|이끄)|직접|첫 (마디|말)|처음 (한|꺼낸)")),
    ("context", re.compile(r"언제|어떤 (상황|장면|일)|누구|시점|최근에|있으셨|있었|떠오르|들려주")),
]
_NO_CASE_RE = re.compile(r"(없었|없어요|딱히|기억이 안)")


def _load_profile(path: str) -> dict:
    return json.load(open(path, encoding="utf-8"))


class Leader:
    """시뮬 리더 상태 — 챕터별로 아직 안 쓴 사례를 꺼내고, 슬롯 단위로 답한다."""

    def __init__(self, profile: dict, *, stub: bool, provider: str, seed: int | None = None):
        self.p = profile
        self.stub = stub
        self.provider = provider
        self.rng = random.Random(seed if seed is not None else profile.get("seed", 1))
        self.used: set[str] = set()
        self.current: dict | None = None
        self.said: set[str] = set()
        self.n_answers = 0
        self.history: list[tuple[str, str]] = []
        self.short_every = int(profile.get("short_every") or 7)
        self.short_answers = profile.get("short_answers") or ["네."]
        self._svc = None
        self.usage = {"calls": 0, "in": 0, "out": 0}

    # ── 사례 선택 ────────────────────────────────────────────────────────────
    def pick_episode(self, chapter: str, target_sub: str | None) -> dict | None:
        cands = [e for e in self.p["episodes"] if e["chapter"] == chapter and e["id"] not in self.used]
        if target_sub:
            hit = [e for e in cands if target_sub in e.get("subs", [])]
            if hit:
                return hit[0]
        if target_sub and target_sub in (self.p.get("no_case_subs") or []):
            return None
        return cands[0] if cands else None

    def start_episode(self, ep: dict | None) -> None:
        self.current = ep
        self.said = set()
        if ep:
            self.used.add(ep["id"])

    # ── 답 생성 ──────────────────────────────────────────────────────────────
    async def answer(self, coach_text: str, *, chapter: str | None, instr: str | None, target_sub: str | None, bei_state: str | None,
                     probe: str | None = None) -> str:
        self.n_answers += 1
        if instr == "RAPPORT_BUILDING":
            # 온보딩은 위치가 아니라 코치 턴의 종류로 답한다(스몰톡 → 역할 질문(ROLE_ASK) → 기대 질문)
            ob = self.p.get("onboarding") or {}
            if probe == "ROLE_ASK":
                return ob.get("role", "교육팀 팀장이고 팀원은 4명입니다.")
            if probe == "READY_FOR_INTRO" or re.search(r"기대하시는", coach_text or ""):
                return ob.get("expectation", "아니요, 특별히 기대하는 건 없어요.")
            if not getattr(self, "_smalltalk_done", False):
                self._smalltalk_done = True
                return ob.get("smalltalk", "바쁜 쪽이에요.")
            return ob.get("smalltalk_more", "네, 그 정도예요.")
        if instr == "DIAGNOSIS_INTRO":
            return "네, 시작하겠습니다."
        if instr in ("COMPETENCY_ASK", "DIAGNOSIS_CONFIRM") and chapter:
            return self.p["definitions"].get(chapter, "글쎄요, 팀이 잘 돌아가게 하는 일이요.")
        if instr in ("COMPETENCY_ALIGN", "EPISODE_OPEN", "SWEEP_ANCHOR"):
            ep = self.pick_episode(chapter or "", target_sub)
            self.start_episode(ep)
            if ep is None:
                return self._no_case_reply()
            return await self._say("context", coach_text, opening=True)
        if self.short_every and self.n_answers % self.short_every == 0:
            return self.rng.choice(self.short_answers)
        if self.current is None:
            ep = self.pick_episode(chapter or "", target_sub)
            self.start_episode(ep)
            if ep is None:
                return self._no_case_reply()
        slot = self._slot_for(coach_text)
        return await self._say(slot, coach_text)

    _NO_CASE_REPLIES = ["딱히 그런 일은 없었던 것 같아요.", "음, 그건 바로 떠오르는 게 없네요.", "그쪽은 기억이 잘 안 나요.", "그런 적은 없었어요."]

    def _no_case_reply(self) -> str:
        self.n_no_case = getattr(self, "n_no_case", 0) + 1
        return self._NO_CASE_REPLIES[(self.n_no_case - 1) % len(self._NO_CASE_REPLIES)]

    def _slot_for(self, coach_text: str) -> str:
        for slot, rx in _SLOT_CUES:
            if rx.search(coach_text or ""):
                if slot in self.said:
                    continue
                return slot
        for s in SLOT_ORDER:
            if s not in self.said:
                return s
        return "reflection"

    async def _say(self, slot: str, coach_text: str, *, opening: bool = False) -> str:
        ep = self.current or {}
        self.said.add(slot)
        fact = ep.get(slot, "")
        if self.stub or not fact:
            return fact or "그 부분은 특별히 기억나는 게 없어요."
        return await self._llm(slot, fact, coach_text, opening)

    async def _llm(self, slot: str, fact: str, coach_text: str, opening: bool) -> str:
        from diag_project.llm_service import GeminiService
        if self._svc is None:
            self._svc = GeminiService().bind_provider(self.provider)
        persona = self.p["persona"]
        system = (
            f"당신은 리더십 진단에 참여한 리더입니다. {persona['role']} 팀원: {', '.join(persona['members'])}.\n"
            f"말하는 방식: {persona['style']}\n"
            "규칙: 아래 [이번에 말할 사실]만 자기 말로 2~4문장으로 답한다. 사실에 없는 내용을 지어내지 않는다. 다른 슬롯(결과·기준·배운 점 등)을 먼저 꺼내지 않는다. "
            "코치의 말을 되풀이하지 않는다. 존댓말, 구어체. 질문하지 않는다. '음,'·'네,'·'그랬죠' 같은 추임새로 문장을 시작하지 않는다. "
            "코치 질문과 [이번에 말할 사실]이 어긋나도 '질문은 ~인데', '그 답이 아니라', '이번에 말할 사실' 같은 설명 없이 사실만 자연스럽게 말한다."
        )
        recent = "\n".join(f"{'코치' if r == 'model' else '나'}: {t}" for r, t in self.history[-6:])
        prompt = (f"[최근 대화]\n{recent}\n\n[코치의 이번 질문]\n{coach_text}\n\n[이번에 말할 사실 — {slot}]\n{fact}\n\n"
                  + ("사례의 첫 장면만 말한다(언제·누구·무엇이 걸렸는지). " if opening else "") + "답변:")
        try:
            out = await self._svc._generate_with_retry(prompt=prompt, system_instruction=system, max_tokens=300, thinking_budget=0,
                                                       call_type="sim_leader", temperature=0.0)
            self.usage["calls"] += 1
            return (out or fact).strip().split("\n")[0][:400] or fact
        except Exception as e:  # noqa: BLE001
            print(f"!! 시뮬 리더 LLM 실패({e}) → 사실 그대로")
            return fact


# ══════════════════════════════════════════════════════════════════════════════
# 서버(코치마다 sqlite + uvicorn) — --serve 로 자기 자신을 서브프로세스로 띄운다
# ══════════════════════════════════════════════════════════════════════════════
def _serve() -> None:
    port = int(os.environ["SIM_PORT"]); db = os.environ["SIM_DB"]; usage = os.environ["SIM_USAGE"]
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
    os.environ["USE_PHASE3A"] = "true"
    os.environ["FM_SYNTHETIC_CHECK"] = "0"
    os.environ.setdefault("FM_PREWARM", "0")
    os.chdir(ROOT)
    from diag_project import llm_service
    _orig_rec = llm_service.USAGE_METER.record

    def _rec(call_type, model, inp, out, thoughts, cache_write=0, cache_read=0):
        try:
            with open(usage, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), "call_type": call_type, "model": model, "in": int(inp or 0),
                                    "out": int(out or 0), "think": int(thoughts or 0), "cw": int(cache_write or 0), "cr": int(cache_read or 0)}) + "\n")
        except Exception:  # noqa: BLE001
            pass
        return _orig_rec(call_type, model, inp, out, thoughts, cache_write, cache_read)
    llm_service.USAGE_METER.record = _rec
    cap = usage.replace("sim_usage_", "sim_prompts_")
    _orig_gen = llm_service.GeminiService._generate_with_retry

    async def _patched(self, *args, **kwargs):
        out = await _orig_gen(self, *args, **kwargs)
        try:
            prompt = kwargs.get("prompt") if "prompt" in kwargs else (args[0] if args else "")
            if str(kwargs.get("call_type", "")).startswith("coach"):
                with open(cap, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), "call_type": kwargs.get("call_type"),
                                        "system_tail": (kwargs.get("system_instruction") or "")[-2500:], "prompt_tail": (prompt or "")[-1500:],
                                        "response": out if isinstance(out, str) else str(out)}, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
        return out
    llm_service.GeminiService._generate_with_retry = _patched
    import uvicorn
    uvicorn.run("diag_project.main:app", host="127.0.0.1", port=port, log_level="info")


def _start_server(tag: str, coach: str, port: int, out_dir: Path, *, provider: str, stub: bool) -> subprocess.Popen:
    db = out_dir / f"sim_{tag}_{coach}.db"
    usage = out_dir / f"sim_usage_{tag}_{coach}.jsonl"
    for f in (db, usage):
        if f.exists():
            f.unlink()
    env = dict(os.environ, SIM_PORT=str(port), SIM_DB=str(db), SIM_USAGE=str(usage), LLM_PROVIDER=provider)
    if stub:
        env["FM_LLM_STUB"] = "1"
    else:
        env.pop("FM_LLM_STUB", None)
    log = open(out_dir / f"sim_server_{tag}_{coach}.log", "w")
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"], env=env, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)


def _cost_usd(usage_path: Path) -> float:
    try:
        from diag_project.llm_service import _PRICE
    except Exception:  # noqa: BLE001
        return 0.0
    total = 0.0
    if not usage_path.exists():
        return 0.0
    for ln in usage_path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        pr = _PRICE.get(r.get("model") or "", {"in": 0.1, "out": 0.5})
        total += (r.get("in", 0) * pr["in"] + (r.get("out", 0) + r.get("think", 0)) * pr["out"]) / 1_000_000
    return round(total, 4)


# ══════════════════════════════════════════════════════════════════════════════
# 클라이언트 — 한 코치 한 세션
# ══════════════════════════════════════════════════════════════════════════════
async def run_session(tag: str, coach: str, port: int, out_dir: Path, profile: dict, *, chapters: int, provider: str, stub: bool,
                      max_turns: int = 160) -> dict:
    import httpx
    base = f"http://127.0.0.1:{port}/api/v1"
    db = out_dir / f"sim_{tag}_{coach}.db"
    coach_id = f"10000000-0000-0000-0000-0000000000{int(coach) + 10:02d}"
    leader = Leader(profile, stub=stub, provider=provider)
    async with httpx.AsyncClient(timeout=300.0) as c:
        for _ in range(180):
            try:
                await c.get(f"http://127.0.0.1:{port}/docs", timeout=2.0)
                break
            except Exception:  # noqa: BLE001
                await asyncio.sleep(1)
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
        from diag_project.database import async_session
        from diag_project.models.participant import Participant
        from diag_project.services.participant_auth import create_participant_token
        pid = uuid.uuid4()
        for _try in range(30):
            try:
                async with async_session() as s:
                    s.add(Participant(id=pid, email=f"{tag}-{coach}-{pid.hex[:6]}@local.test", name="박기진", is_active=True))
                    await s.commit()
                break
            except Exception:  # noqa: BLE001
                await asyncio.sleep(1)
        else:
            raise RuntimeError("participant insert 실패")
        hdr = {"Authorization": f"Bearer {create_participant_token(pid)}"}
        r = await c.post(f"{base}/diagnoses/start", json={"coach_id": coach_id, "participant_id": str(pid), "template_id": TEMPLATE_ID}, headers=hdr)
        r.raise_for_status()
        sid = r.json()["session_id"]
        coach_text = r.json().get("coach_response_message") or ""
        leader.history.append(("model", coach_text))
        t0 = time.time()
        queue = list(ONBOARDING)
        turns = 0
        chapters_done = 0
        meta: dict = {}
        while turns < max_turns:
            if queue:
                u = queue.pop(0)
            else:
                u = await leader.answer(coach_text, chapter=meta.get("chapter"), instr=meta.get("instruction_used"),
                                        target_sub=meta.get("target"), bei_state=meta.get("bei_state"), probe=meta.get("probe_type_used"))
            leader.history.append(("user", u))
            r = await c.post(f"{base}/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": u}, headers=hdr)
            turns += 1
            if r.status_code >= 400:
                print(f"!! {tag}_{coach} turn {turns} HTTP {r.status_code}: {r.text[:300]}")
                break
            body = r.json()
            coach_text = body.get("coach_response_message") or ""
            meta = body.get("_phase3a_metadata") or {}
            leader.history.append(("model", coach_text))
            if body.get("is_session_completed") or body.get("is_terminated"):
                break
            if body.get("needs_user_decision"):
                r2 = await c.post(f"{base}/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": CONTINUE}, headers=hdr)
                coach_text = (r2.json() or {}).get("coach_response_message") or coach_text
                meta = (r2.json() or {}).get("_phase3a_metadata") or meta
                leader.history.append(("model", coach_text))
            elif body.get("is_topic_completed") and body.get("has_next_chapter"):
                chapters_done += 1
                if chapters_done >= chapters:
                    break
                r2 = await c.post(f"{base}/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": NEXT}, headers=hdr)
                coach_text = (r2.json() or {}).get("coach_response_message") or coach_text
                meta = (r2.json() or {}).get("_phase3a_metadata") or meta
                leader.history.append(("model", coach_text))
        elapsed = time.time() - t0
    con = sqlite3.connect(str(db))
    sid_h = sid.replace("-", "")
    rows = con.execute("select turn_index, role, chapter, probe_type_used, instruction_used, content from chat_messages "
                       "where session_id=? order by created_at, turn_index", (sid_h,)).fetchall()
    sad = con.execute("select self_assessment_data, status, current_topic from diagnosis_sessions where id=?", (sid_h,)).fetchone()
    con.close()
    store = json.loads(sad[0]) if sad and sad[0] else {}
    gl = {(g.get("ch"), g.get("t")): g for g in store.get("guard_log", []) if isinstance(g, dict)}
    gl_t = {g.get("t"): g for g in store.get("guard_log", []) if isinstance(g, dict)}   # 종료 턴은 다음 챕터로 태깅되므로 t 로 보조 매칭
    out_rows = [{"t": t, "role": role, "chapter": ch, "probe": probe, "instr": instr, "content": content,
                 "guard": ((gl.get((ch, t)) or gl_t.get(t)) if role == "model" else None)} for t, role, ch, probe, instr, content in rows]
    ledger = {k: store.get(k) for k in ("chapter_state", "bei_turns", "episodes", "covered", "weak", "sweep_asked", "unconfirmed",
                                        "no_case_subs", "asked_subs", "anchored_subs") if store.get(k) is not None}
    truth = {"episodes": [{"id": e["id"], "chapter": e["chapter"], "subs": e["subs"], "used": e["id"] in leader.used} for e in profile["episodes"]],
             "no_case_subs": profile.get("no_case_subs") or []}
    result = {"session": sid, "coach": coach, "provider": provider, "stub": stub, "status": sad[1] if sad else None,
              "topic": sad[2] if sad else None, "elapsed_s": round(elapsed), "turns": turns, "rows": out_rows, "ledger": ledger, "truth": truth,
              "cost_usd": _cost_usd(out_dir / f"sim_usage_{tag}_{coach}.jsonl"), "leader_llm_calls": leader.usage["calls"]}
    json.dump(result, open(out_dir / f"sim_result_{tag}_{coach}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"=== {tag}_{coach} status={result['status']} topic={result['topic']} rows={len(rows)} turns={turns} {elapsed:.0f}s cost=${result['cost_usd']}")
    return result


def dump_transcript(path: str) -> str:
    d = json.load(open(path, encoding="utf-8"))
    from diag_project.data.coaches_persona import COACHES_PERSONA
    name = COACHES_PERSONA.get(str(d.get("coach")), {}).get("name", d.get("coach"))
    L = [f"# {name} · {d.get('provider')}{' · stub' if d.get('stub') else ''} · {d.get('topic')} · {d.get('turns')}턴 · ${d.get('cost_usd')}", ""]
    for r in d["rows"]:
        g = r.get("guard") or {}
        tag = ""
        if r["role"] == "model":
            bits = [r.get("instr") or ""]
            if g.get("episode") is not None:
                bits.append(f"사례{g.get('episode')}·턴{g.get('ep_turn')}·슬롯{g.get('slots_filled')}")
            if g.get("closed"):
                bits.append(f"종료 {g['closed']} → {g.get('mapped')}")
            if g.get("format_miss"):
                bits.append(f"형식미해결 {g['format_miss']}")
            tag = " [" + " | ".join(b for b in bits if b) + "]"
        who = "리더" if r["role"] == "user" else name.split(" ")[0]
        L.append(f"{who}{tag}: {r['content']}")
        L.append("")
    led = d.get("ledger") or {}
    if led:
        L.append("## 원장")
        L.append(json.dumps({k: led.get(k) for k in ("bei_turns", "covered", "sweep_asked", "unconfirmed", "no_case_subs", "chapter_state")}, ensure_ascii=False, indent=1))
    return "\n".join(L)


async def analyze_result(path: str) -> None:
    """(2026-11-05 3단계) sim_result_*.json 의 세션을 그 sqlite 로 서버를 다시 띄워 분석(Sonnet) 1회 실행 → 비용·analysis_lint 표.
    CLAUDE.md 규칙: 분석은 지시문에 횟수·USD 가 있을 때만, 1회씩."""
    import httpx
    out_dir = Path(path).resolve().parent
    m = re.match(r"sim_result_(.+)_(\d+)\.json$", Path(path).name)
    if not m:
        raise SystemExit("sim_result_TAG_COACH.json 형식이어야 합니다")
    tag, coach = m.group(1), m.group(2)
    d = json.load(open(path, encoding="utf-8"))
    sid = d["session"]
    db = out_dir / f"sim_{tag}_{coach}.db"
    usage = out_dir / f"sim_usage_{tag}_{coach}_analysis.jsonl"
    if usage.exists():
        usage.unlink()
    port = int(os.environ.get("RP_PORT_BASE", "8070"))
    env = dict(os.environ, SIM_PORT=str(port), SIM_DB=str(db), SIM_USAGE=str(usage), LLM_PROVIDER=d.get("provider") or "claude")
    env.pop("FM_LLM_STUB", None)
    log = open(out_dir / f"sim_server_{tag}_{coach}_analysis.log", "w")
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"], env=env, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    try:
        con = sqlite3.connect(str(db))
        uid = con.execute("select user_id from diagnosis_sessions where id=?", (sid.replace("-", ""),)).fetchone()[0]
        con.close()
        from diag_project.services.participant_auth import create_participant_token
        hdr = {"Authorization": f"Bearer {create_participant_token(uuid.UUID(str(uid)))}"}
        async with httpx.AsyncClient(timeout=3600.0) as c:
            for _ in range(180):
                try:
                    await c.get(f"http://127.0.0.1:{port}/docs", timeout=2.0)
                    break
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(1)
            t0 = time.time()
            r = await c.post(f"http://127.0.0.1:{port}/api/v1/reports/{sid}/analyze", headers=hdr)
            print(f"=== analyze {tag}_{coach} HTTP {r.status_code} {time.time() - t0:.0f}s {r.text[:200]}")
    finally:
        proc.terminate()
    print(f"분석 비용: ${_cost_usd(usage)} (usage {usage.name})")
    from tools.analysis_lint import main as _lint_main
    _lint_main(["--db", str(db)])


async def _main_async(args) -> None:
    out_dir = Path(os.environ.get("SIM_OUT") or os.getcwd())
    profile = _load_profile(args.profile)
    coaches = [c for c in args.coaches.split(",") if c]
    port_base = int(os.environ.get("RP_PORT_BASE", "8070"))
    servers = {c: (_start_server(args.tag, c, port_base + i, out_dir, provider=args.provider, stub=args.stub), port_base + i) for i, c in enumerate(coaches)}
    await asyncio.sleep(3)
    try:
        results = await asyncio.gather(*[run_session(args.tag, c, port, out_dir, profile, chapters=args.chapters, provider=args.provider, stub=args.stub)
                                         for c, (_, port) in servers.items()], return_exceptions=True)
        for c, res in zip(servers, results):
            if isinstance(res, Exception):
                print(f"!! {args.tag}_{c} 실패: {type(res).__name__}: {str(res)[:300]}")
    finally:
        for proc, _ in servers.values():
            proc.terminate()
    print("ALL DONE")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="BEI 시뮬 리더")
    ap.add_argument("tag", nargs="?")
    ap.add_argument("--coaches", default="5,2")
    ap.add_argument("--chapters", type=int, default=1)
    ap.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "claude"))
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--profile", default=str(ROOT / "tools/sim_profiles/edu_team_lead.json"))
    ap.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--dump", help="sim_result_*.json 전문 출력")
    ap.add_argument("--analyze", help="sim_result_*.json 의 세션을 분석(Sonnet 1회) — 지시문에 횟수·USD 가 있을 때만")
    args = ap.parse_args(argv)
    if args.serve:
        _serve()
        return 0
    if args.analyze:
        asyncio.run(analyze_result(args.analyze))
        return 0
    if args.dump:
        print(dump_transcript(args.dump))
        return 0
    if not args.tag:
        ap.error("TAG 가 필요합니다")
    asyncio.run(_main_async(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
