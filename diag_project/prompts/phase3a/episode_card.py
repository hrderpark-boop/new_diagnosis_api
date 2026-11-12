"""(2026-11-04 BEI) 사례 카드·BEI 턴 가이드 — system 프롬프트의 턴 동적 부분.

Layer3 의 Turn State JSON·Global Memory·강제 블록을 대체한다(docs/design_bei_2026-11.md §8).
  · chapter_context_bei : Layer2 축약 — 역량 정의 1문장 + 하위역량 이름·행동 단서(내부 참고, 노출 금지)
  · build_episode_card  : 지금 듣는 사례(n번째/리더 턴 k/8), 채워진 슬롯(리더 말 인용), 미충족 슬롯(순서), 이번 턴 지시, 직전 답 신호
  · bei_turn_text       : 카드 + instruction 가이드 + 턴 형식 + 금지 (format_turn_state_for_llm 이 BEI 턴에 이것을 반환)
문장은 LLM 이 쓴다. 여기 적힌 예시는 '결'만 — CLAUDE.md 규칙대로 테스트 입력·실제 발화와 겹치지 않게 쓴다.
"""
from __future__ import annotations

from diag_project.data.competencies import COMPETENCY_FRAMEWORK, SUBCOMPETENCY_ANCHORS, SUBCOMPETENCY_MUST_ASK
from diag_project.services.bei_engine import (
    BEI_INSTRUCTIONS, EPISODE_MAX_LEADER_TURNS, SLOT_HINTS, SLOT_KEYS, SLOT_LABELS, detail_probe_hint, filled_slots, unfilled_slots,
)


def sub_brief(sub_key: str) -> str:
    """하위역량 한 줄 단서(내부용): must_ask 의 '행동:' 항목, 없으면 첫 상황 서술 앞부분."""
    cues = [c.split(":", 1)[1].strip() for c in (SUBCOMPETENCY_MUST_ASK.get(sub_key) or []) if c.startswith("행동")]
    if cues:
        return cues[0]
    anchors = SUBCOMPETENCY_ANCHORS.get(sub_key) or []
    return (anchors[0] if anchors else "")[:60]


def chapter_context_bei(chapter: str | None) -> str:
    fw = COMPETENCY_FRAMEWORK.get(chapter or "", {})
    if not fw:
        return ""
    lines = [f"# 현재 챕터: {fw.get('name', '')}", "", "## 역량 정의", (fw.get("description") or "").strip(), "",
             "## 이 챕터의 하위역량 (내부 참고 — 리더에게 이름·분류를 말하지 않는다)"]
    for key, ind in (fw.get("indicators") or {}).items():
        lines.append(f"- {ind.get('name', '')}: {sub_brief(key)}")
    return "\n".join(lines)


def _quote_line(ep: dict, key: str) -> str:
    q = ((ep.get("slots") or {}).get(key) or {}).get("quote") or ""
    return f"{SLOT_LABELS[key]} — \"{q}\"(리더 말)" if q else SLOT_LABELS[key]


def build_episode_card(
    *,
    instruction: str,
    chapter: str | None,
    ep: dict | None,
    bei_turns: int,
    budget: int,
    prev_episodes: list[dict] | None = None,
    signal: str = "",
    anchor_text: str | None = None,
    sweep_sub: str | None = None,
    weak_hint: str | None = None,
    sweep_seq: int = 0,
    bridge_material: str | None = None,
) -> str:
    """사례 카드 본문(300토큰 이내). prev_episodes = [{"idx", "summary"}] 이 챕터·이전 챕터에서 끝난 사례.
    sweep_seq = 연속 SWEEP 순번(2 이상이면 앵커 앞 다리 문장 필수, P4-5). bridge_material = 앞 사례에서 리더가 쓴 말(다리 재료)."""
    L: list[str] = []
    if instruction in ("EPISODE_PROBE", "NO_CASE_REFRAME") and ep:
        n = ep.get("idx", 1)
        k = int(ep.get("leader_turns") or 0)
        L.append(f"# 지금 듣고 있는 사례 ({n}번째 / 이 사례 리더 턴 {k}/{EPISODE_MAX_LEADER_TURNS} / 이 영역 리더 턴 {bei_turns}/{budget})")
        filled = filled_slots(ep)
        partial = [x for x in SLOT_KEYS if ((ep.get("slots") or {}).get(x) or {}).get("status") == "partial"]
        missing = unfilled_slots(ep)
        if filled:
            L.append("채워진 것: " + " / ".join(_quote_line(ep, x) for x in filled))
        if partial:
            L.append("반쯤 나온 것(한 번 더 구체화해도 좋다): " + " / ".join(_quote_line(ep, x) for x in partial))
        if missing:
            L.append("아직 없는 것(이 순서로 하나씩): " + " → ".join(SLOT_LABELS[x] for x in missing))
            L.append("위 세 줄은 코치만 보는 점검표다. 무엇을 들었고 무엇이 남았는지를 리더에게 말하지 않는다 — 받는 문장 뒤에 바로 질문한다.")   # (P9 승인 조건 2)
            nxt = missing[0]
            L.append(f"이번 턴: '{SLOT_LABELS[nxt]}' 하나를 묻는다 — {SLOT_HINTS[nxt]}. "
                     "리더가 다른 데로 가면 한 번은 따라가되 질문은 이 사례로 돌아온다.")
        else:
            L.append(f"이번 턴(장면 구체화): 여섯 가지가 다 나왔다. 되받기 뒤 질문 하나 — {detail_probe_hint(ep)}.")
        if k <= 1:
            L.append("첫 턴 규칙: 먼저 리더가 방금 말한 상황을 한 문장으로 받는다(리더가 쓴 말 하나를 그대로 넣어서). '궁금합니다' 류로 시작하지 않는다. 그 다음에 질문.")
    elif instruction == "EPISODE_OPEN":
        L.append("# 다음 사례로 넘어가는 턴")
        L.append("직전 사례를 닫는 되받기 1문장(들은 핵심 사실 하나, 평가 없이)만 쓴다. 질문·'왜 묻는지' 문장은 쓰지 않는다 — "
                 "시스템이 아래 여는 문장(왜 묻는지 1문장 + 있었는지 질문)을 그대로 붙인다. 다리 문장도 쓰지 않는다(여는 문장이 다리 역할).")
        if anchor_text:
            L.append(f"시스템이 붙일 여는 문장: \"{anchor_text}\"")
    elif instruction == "SWEEP_ANCHOR":
        L.append("# 아직 듣지 못한 장면을 묻는 턴")
        L.append("되받기 1~2문장(직전 답의 핵심 사실, 평가 없이) + 다리 1문장. 질문은 쓰지 않는다 — 시스템이 아래 질문을 그대로 붙인다.")
        if anchor_text:
            L.append(f"시스템이 붙일 질문: \"{anchor_text}\"")
        if sweep_seq >= 2:
            L.append(f"이 턴은 연속 {sweep_seq}번째 추가 질문 — 다리 1문장이 필수다: 앞 사례에서 리더가 쓴 말 하나를 짚어 잇는다"
                     "('아까 ○○ 얘기에서 살짝 나왔는데' 결, ○○ 는 아래 재료의 명사구). 다리 없이 질문만 붙이면 실패다.")
        else:
            L.append("다리 1문장은 앞 사례의 한 단어에서 지금 질문으로 잇는다('아까 ○○ 얘기에서 살짝 나왔는데' 결).")
        if bridge_material:
            L.append(f"다리 재료(앞 사례에서 리더가 쓴 말): {bridge_material}")
        if weak_hint:
            L.append(f"다리 힌트: {weak_hint}")
    elif instruction == "SWEEP_FOLLOWUP" and ep:
        missing = unfilled_slots(ep)
        L.append("# 방금 꺼낸 장면에 질문 하나만 더하는 턴")
        if missing:
            nxt = "action" if "action" in missing else ("result" if "result" in missing else missing[0])
            L.append(f"이번 턴: '{SLOT_LABELS[nxt]}' 하나 — {SLOT_HINTS[nxt]}. 이 장면은 이 질문으로 마무리한다(더 파지 않는다).")
    if prev_episodes:
        L.append("지난 사례(참고 — 리더가 다시 꺼내면 새 사례를 요구하지 말고 지금 묻는 슬롯의 관점으로 이어서 묻는다): "
                 + " / ".join(f"[{p.get('idx')}] {p.get('summary', '')}" for p in prev_episodes[-5:]))
    if signal:
        L.append(f"신호: {signal}")
    return "\n".join(L)


BEI_GUIDES: dict[str, str] = {
    "EPISODE_PROBE": (
        "사례 하나를 끝까지 듣는 턴입니다. 되받기 1문장 + 질문 1개. 되받기는 리더가 방금 쓴 말(명사구)을 그대로 하나 넣어 "
        "들은 사실을 받는 평서문이고, 질문은 카드의 '이번 턴' 슬롯 하나를 향합니다. 새 사례·다른 장면을 청하지 않습니다. "
        "질문은 열린 질문으로 — 선택지를 제시하거나('~하셨나요, 아니면 ~하셨나요?') 가정을 걸어('~하셨다면 어떻게') 답을 고르게 하지 않습니다."
    ),
    "NO_CASE_REFRAME": (
        "리더가 이 질문에 해당하는 일이 없다·글쎄요·특별히 없다고 답했습니다(사례 아님). 받아들이는 되받기 1문장(압박 없이) + "
        "더 작게·다른 각도로 묻는 질문 1개 — '작은 일이어도 됩니다, 예를 들어 회의에서 한마디 하신 것도요' 결로 범위를 낮추거나 "
        "다른 장면(동료와의 짧은 대화, 메신저 한 줄, 혼자 내린 결정)에서 찾게 합니다. 좁히는 말은 매번 다르게 씁니다(같은 문장 반복 금지). 추궁은 금지입니다 — '진짜 기억이 없으신가요', "
        "'솔직히 말씀하신 건가요', '마음에 걸려요' 류를 쓰지 않습니다. 이번에도 없다고 하면 그대로 받아들이고 시스템이 다음으로 넘깁니다."
    ),
    "EPISODE_OPEN": (
        "직전 사례를 닫고 다음 사례를 여는 턴입니다. [되받기 1문장]만 씁니다 — 질문·다리·'왜 묻는지' 문장은 시스템이 붙입니다(쓰면 삭제됩니다). "
        "되받기에 '다음 항목', '넘어가겠습니다' 같은 진행 상태 보고를 쓰지 않습니다."
    ),
    "SWEEP_ANCHOR": (
        "아직 듣지 못한 장면을 하나 더 묻는 턴입니다. [되받기 1~2문장] + [다리 1문장]만 쓰고 질문은 쓰지 않습니다(시스템이 붙입니다). "
        "다리는 앞 사례에서 리더가 쓴 말 하나를 짚어 '아까 ○○ 얘기에서 살짝 나왔는데' 결로 지금 질문에 겁니다. 연속 두 번째 추가 질문부터는 다리가 없으면 실패입니다."
    ),
    "SWEEP_FOLLOWUP": (
        "방금 꺼낸 장면에 질문 하나만 더합니다. 되받기 1문장 + 질문 1개. 카드의 슬롯 하나를 향하고, 그 뒤 시스템이 다음으로 넘어갑니다."
    ),
}

TURN_FORMAT_RULES = (
    "[턴 형식]\n"
    "- 되받기 1문장 + 질문 1개. 되받기 없이 질문만 쓰지 않는다. 질문 두 개를 잇지 않는다 — '~는지, 그리고 ~는지' 처럼 한 문장에 두 가지를 묻는 것도 두 질문이다.\n"
    "- 되받기에는 리더가 방금 쓴 낱말을 한두 개만 넣는다. 답 전체를 다시 읊지 않고, 뜻을 풀이하지도 않는다. 리더가 말하지 않은 사정을 보태지 않는다.\n"
    "- 리더가 쓰지 않은 낱말을 리더가 한 말처럼 따옴표에 넣거나 '방금·앞서 말씀하신 ~'이라고 하지 않는다.\n"
    "- 질문은 혼자 읽어도 뜻이 서야 한다 — 접속어·조건절로 시작하지 않고, 누구의 무엇을 묻는지가 문장 안에 낱말로 있다.\n"
    "- 무엇을 물을지 미리 알리는 문장을 쓰지 않는다. 사례를 들려줘 고맙다는 말은 사례를 닫을 때만 한다.\n"
    "- 리더가 반말이나 아주 짧은 말로 답해도 코치의 말씨는 그대로다. 리더의 말씨·말 길이를 입에 올리지 않고 따라 하지도 않는다.\n"
    "- 질문은 리더가 쓴 말(명사구)로 대상을 분명히 한다. '그것·그럴 때·그렇게'만으로 가리키지 않는다.\n"
    "- 질문은 열린 질문 하나. 선택지를 주는 질문('~하셨나요, 아니면 ~하셨나요?')과 가정형 질문('~하셨다면 어떻게')은 쓰지 않는다 — 무엇을 했는지는 리더가 말한다.\n"
    "- 새 장면을 청할 때는 있었는지부터 묻는다 — '~받으셨을 때 어떻게' 처럼 있었음을 전제하는 문형은 쓰지 않는다.\n"
    "- 평가 말투 금지: '좋습니다/좋은 방향/좋은 흐름/잘하셨/인상적' 같은 리드·평서문은 전부 삭제·재생성된다. 되받기는 사실 재진술만.\n"
    "- 밀어붙이지 않는다: 리더가 없다·형식적으로 답하겠다고 하면 그대로 받아들이고 다음으로 간다. '진짜·정말 기억이 없으신가요', '솔직히 말씀하신 건가요', "
    "'마음에 걸려요', '다시 한 번 잘 생각해 보시면' 류 추궁 문장은 쓰지 않는다.\n"
    "[금지]\n"
    "- 하위역량 이름·분류 설명('이건 변화관리에 해당'), 진행 상태 보고('이제 결과를 여쭙겠습니다', '다음 항목으로'), 칭찬·평가, 느낌표 남발, 회사명.\n"
    "- 사례 요약을 길게 되풀이하기, 같은 질문 되묻기, 은유 질문.\n"
)


def bei_turn_text(state: dict) -> str:
    """BEI 턴의 Layer3 본문: 페르소나 상기 + 사례 카드 + instruction 가이드 + 턴 형식·금지."""
    instruction = state.get("instruction_for_this_turn") or ""
    persona = state.get("coach_persona") or {}
    persona_block = ""
    if persona.get("name"):
        from diag_project.services.persona_voice import persona_guide_block
        persona_block = (
            f"[🎭 페르소나 유지] 당신은 {persona['name']} — {persona.get('coaching_style', '')} ({persona.get('tags', '')}). "
            "문장 길이·종결어미·호응 방식은 시스템 프롬프트의 【말투 프로필】대로. 어느 코치든 같은 톤이 나오면 실패입니다.\n"
            + persona_guide_block(persona["name"])
        )
    card = state.get("bei_card") or ""
    guide = BEI_GUIDES.get(instruction, "")
    return f"{persona_block}{card}\n\n[Instruction for this turn]\n{instruction}\n\n{guide}\n\n{TURN_FORMAT_RULES}"


def is_bei_instruction(instruction: str | None) -> bool:
    return instruction in BEI_INSTRUCTIONS
