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
    BEI_INSTRUCTIONS, SLOT_HINTS, SLOT_KEYS, SLOT_LABELS, ask_slot, detail_probe_hint, episode_turn_max, filled_slots, unfilled_slots,
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
    used_endings: list[str] | None = None,
) -> str:
    """사례 카드 본문(300토큰 이내). prev_episodes = [{"idx", "summary"}] 이 챕터·이전 챕터에서 끝난 사례.
    sweep_seq = 연속 SWEEP 순번(2 이상이면 앵커 앞 다리 문장 필수, P4-5). bridge_material = 앞 사례에서 리더가 쓴 말(다리 재료)."""
    L: list[str] = []
    if instruction in ("EPISODE_PROBE", "NO_CASE_REFRAME") and ep:
        n = ep.get("idx", 1)
        k = int(ep.get("leader_turns") or 0)
        _kmax = episode_turn_max(len((COMPETENCY_FRAMEWORK.get(chapter or "", {}) or {}).get("indicators") or {}))
        L.append(f"# 지금 듣고 있는 사례 ({n}번째 / 이 사례 리더 턴 {k}/{_kmax} / 이 영역 리더 턴 {bei_turns}/{budget})")
        filled = filled_slots(ep)
        partial = [x for x in SLOT_KEYS if ((ep.get("slots") or {}).get(x) or {}).get("status") == "partial"]
        missing = unfilled_slots(ep)
        if filled:
            L.append("채워진 것: " + " / ".join(_quote_line(ep, x) for x in filled))
        if partial:
            L.append("반쯤 나온 것(한 번 더 구체화해도 좋다): " + " / ".join(_quote_line(ep, x) for x in partial))
        if missing:
            L.append("아직 없는 것(이 순서로 하나씩): " + " → ".join(SLOT_LABELS[x] for x in missing))
            L.append("위 세 줄은 코치만 보는 점검표다. 무엇을 들었고 무엇이 남았는지를 리더에게 말하지 않는다 — 바로 질문한다.")   # (P9 승인 조건 2)
            nxt = ask_slot(ep)          # (P12-2) 같은 것을 두 번 물었으면 다음 것으로 넘어간 자리
            L.append(f"이번 턴: '{SLOT_LABELS[nxt]}' 하나를 묻는다 — {SLOT_HINTS[nxt]}. "
                     "리더가 다른 데로 가면 한 번은 따라가되 질문은 이 사례로 돌아온다.")
            if nxt in partial:
                # (2026-11-12 P11d-3) 반쯤 나온 것을 처음부터 다시 묻지 않게 — p11c: '작년 12월'·'이기획'을 말했는데 '언제, 누구와' 를 다시 물었다
                L.append("이 한 가지는 리더가 이미 일부를 말했다(위 '반쯤 나온 것'의 인용). 이미 말한 때·사람은 다시 묻지 않고, 빠진 것만 묻는다.")
        else:
            L.append(f"이번 턴(장면 구체화): 여섯 가지가 다 나왔다. 질문 하나 — {detail_probe_hint(ep)}.")
        # (2026-11-12 P11c-1) '첫 턴 규칙'(먼저 한 문장으로 받는다)은 삭제 — 질문 앞 평서문은 없어도 된다
    elif instruction == "EPISODE_OPEN":
        L.append("# 다음 사례로 넘어가는 턴")
        L.append("직전 답에서 들은 사실 하나를 리더가 쓴 낱말로 말하는 평서문 1문장만 쓴다(평가 없이). 질문과 다음 주제를 알리는 문장은 쓰지 않는다 — "
                 "시스템이 아래 문장을 그대로 붙인다.")
        if anchor_text:
            L.append(f"시스템이 붙일 문장: \"{anchor_text}\"")
    elif instruction == "SWEEP_ANCHOR":
        L.append("# 아직 듣지 못한 장면을 묻는 턴")
        # (2026-11-13 P12b-1) 안에서 부르던 이름이 출력에 나왔다("잇는 문장 하나만 쓰겠어요.") — 번호(①·②)로만 부른다
        L.append("평서문 두 가지만 쓴다 — ① 직전 답의 핵심 사실 1문장(평가 없이). ② '아까'로 시작해 앞에서 리더가 쓴 낱말 하나를 짚는 1문장. "
                 "질문은 쓰지 않는다 — 시스템이 아래 질문을 그대로 붙인다.")
        if anchor_text:
            L.append(f"시스템이 붙일 질문: \"{anchor_text}\"")
        if sweep_seq >= 2:
            L.append(f"이 턴은 연속 {sweep_seq}번째 추가 질문 — ②는 아래 재료의 낱말 하나를 짚어, 그 이야기에서 조금 나온 것을 하나 더 묻는다는 뜻을 전한다.")
        if bridge_material:
            L.append(f"②의 재료(앞 사례에서 리더가 쓴 말): {bridge_material}")
        if weak_hint:
            L.append(f"②의 힌트: {weak_hint}")
    elif instruction == "SWEEP_FOLLOWUP" and ep:
        missing = unfilled_slots(ep)
        L.append("# 방금 꺼낸 장면에 질문 하나만 더하는 턴")
        if missing:
            nxt = "action" if "action" in missing else ("result" if "result" in missing else missing[0])
            L.append(f"이번 턴: '{SLOT_LABELS[nxt]}' 하나 — {SLOT_HINTS[nxt]}. 이 장면은 이 질문으로 마무리한다(더 파지 않는다).")
    if prev_episodes and instruction != "NO_CASE_REFRAME":      # (P11e-1) 재질문 턴에는 지난 사례를 주지 않는다 — 재질문이 닫힌 사례를 끌어왔다
        L.append("지난 사례(코치가 먼저 꺼내지 않는다 — 리더가 다시 꺼낼 때만 참고해, 새 사례를 요구하지 말고 지금 묻는 것의 관점으로 이어서 묻는다): "
                 + " / ".join(f"[{p.get('idx')}] {p.get('summary', '')}" for p in prev_episodes[-5:]))
    if used_endings and instruction in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP"):
        # (2026-11-13 P12-4) 이번 영역에서 이미 여러 번 쓴 질문 끝맺음 — 치환표가 아니라 목록을 넘겨 다른 끝맺음을 쓰게 한다
        L.append("이번 영역에서 이미 여러 번 쓴 질문 끝맺음: " + " / ".join(f"'{x}'" for x in used_endings[:6])
                 + " — 이번 질문은 이 꼴로 끝내지 않는다. 무엇을·어떻게로 바로 묻는 꼴처럼 다른 끝맺음을 쓴다.")
    if signal:
        L.append(f"신호: {signal}")
    return "\n".join(L)


# (2026-11-12 P11c-1·3) 질문 앞 평서문은 없어도 된다(필수 검사 삭제). 완성 문장 예시와 안에서 쓰는 말(되받기·슬롯·다리)은 지시문에서 뺐다 —
#   p11b: 지시문의 '받는 문장' 이 출력 '…상황을 받겠습니다' 로, 예시 문장들이 낱말만 바뀐 채 출력으로 나왔다. 지시는 꼴을 설명하는 말로만 쓴다.
BEI_GUIDES: dict[str, str] = {
    "EPISODE_PROBE": (
        "사례 하나를 끝까지 듣는 턴입니다. 질문 1개로 끝냅니다. 질문은 카드의 '이번 턴' 한 가지만 향합니다. "
        "질문 앞에 평서문을 둘 때는 1문장만 — 리더가 방금 쓴 낱말 한두 개가 들어간, 들은 사실 그대로의 문장입니다(없어도 됩니다). "
        "새 사례·다른 장면을 청하지 않습니다. 질문은 열린 질문으로 — 고를 것을 늘어놓거나 가정을 걸어 답을 고르게 하지 않습니다."
    ),
    "NO_CASE_REFRAME": (
        "리더가 이 질문에 해당하는 일이 없다고 답했습니다. 그 답을 그대로 받아들이는 짧은 평서문 1문장(압박 없이, 없어도 됩니다) + 다른 각도의 질문 1개. "
        "질문은 그런 일이 있었는지를 다시 묻는 꼴이어야 합니다 — 아주 작은 일도 된다는 뜻으로 범위를 낮추거나, 다른 자리"
        "(동료와의 짧은 대화, 메신저 한 줄, 혼자 내린 결정)에서 찾게 합니다. 사례가 이미 있다고 전제하고 언제·누구와·무엇을 했는지를 묻지 않습니다. "
        "앞에서 들은 이야기를 끌어오지 않습니다 — 이 질문이 묻는 일에 해당하는, 평소 일하다 생기는 작은 장면을 새로 묻습니다. "
        "좁히는 말은 매번 다르게 씁니다. 추궁은 금지입니다 — 기억이나 솔직함을 의심하는 말을 쓰지 않습니다. "
        "이번에도 없다고 하면 그대로 받아들이고 시스템이 다음으로 넘깁니다."
    ),
    "EPISODE_OPEN": (
        "직전 사례를 닫고 다음 사례를 여는 턴입니다. 평서문 1문장만 씁니다 — 질문과 다음 주제를 알리는 문장은 시스템이 붙입니다(쓰면 삭제됩니다). "
        "진행 상태를 알리는 말은 쓰지 않습니다."
    ),
    "SWEEP_ANCHOR": (
        "아직 듣지 못한 장면을 하나 더 묻는 턴입니다. 카드의 ①·② 평서문만 쓰고 질문은 쓰지 않습니다(시스템이 붙입니다). "
        "무엇을 쓸지 미리 알리는 말은 쓰지 않습니다."
    ),
    "SWEEP_FOLLOWUP": (
        "방금 꺼낸 장면에 질문 하나만 더합니다. 질문 1개(앞의 평서문 1문장은 없어도 됩니다). 카드의 '이번 턴' 한 가지를 향하고, 그 뒤 시스템이 다음으로 넘어갑니다."
    ),
}

TURN_FORMAT_RULES = (
    "[턴 형식]\n"
    "- 질문 1개로 끝낸다. 질문 문장은 하나만 쓰고, 한 턴에 묻는 것은 하나다 — 둘 가운데 고르게 하는 꼴과, 두 가지를 이어 한 문장에 묻는 꼴을 쓰지 않는다.\n"
    "- 질문 문장 안에 리더가 직전 답에서 쓴 낱말(사람·일·때 가운데 하나)을 넣는다. 앞 문장 없이 그 질문만 읽어도 무엇에 대한 질문인지 "
    "알 수 있어야 한다 — 질문 앞 평서문에 기대지 않고, 가리키는 말만으로 대상을 대신하지 않는다.\n"
    "- 다음 질문은 아직 듣지 못한 것(그 뒤의 결과, 그렇게 정한 기준, 다시 한다면 달리할 점)으로 나아간다. 이미 들은 대화를 한 마디씩 "
    "거슬러 올라가며 되묻지 않는다.\n"
    "- 지금 듣는 이야기의 말만 쓴다. 앞에서 끝난 다른 이야기를 평서문이나 질문에 끌어오지 않는다.\n"
    "- 질문 앞의 평서문은 없어도 된다. 쓰면 1문장 — 리더가 방금 쓴 낱말 한두 개만 넣는다. 답 전체를 다시 읊지 않고, 뜻을 풀이하지 않고, "
    "리더가 말하지 않은 사정·심정·까닭을 보태지 않는다.\n"
    "- 리더가 쓰지 않은 낱말을 리더가 한 말처럼 따옴표에 넣지 않는다. 리더의 말과 질문을 잇기만 하는 문구도 쓰지 않는다.\n"
    "- 리더의 말을 옮길 때 누가 한 일인지를 바꾸지 않는다 — 리더가 한 일은 리더가 한 일로, 다른 사람이 한 일은 그 사람이 한 일로 쓴다.\n"
    "- 리더가 이미 말한 때·사람·일은 다시 묻지 않는다. 아직 나오지 않은 것만 묻는다.\n"
    "- 리더의 답이 짧거나 모자라도 그렇다는 말을 하지 않는다. 더 쉬운 질문 하나로 넘어간다.\n"
    "- 질문은 접속어·조건절로 시작하지 않는다.\n"
    "- 무엇을 물을지 미리 알리는 문장을 쓰지 않는다. 고맙다는 말은 사례를 닫을 때만 한다.\n"
    "- 리더가 반말이나 아주 짧은 말로 답해도 코치의 말씨는 그대로다. 리더의 말씨·말 길이를 입에 올리지 않고 따라 하지도 않는다.\n"
    "- 질문은 열린 질문 하나. 고를 것을 늘어놓는 질문은 쓰지 않는다 — 무엇을 했는지는 리더가 말한다.\n"
    "- 실제로 있었던 일만 묻는다. 일어나지 않은 일을 가정해서 묻지 않는다(다시 한다면 달리할 점을 묻는 것만 예외다).\n"
    "- 리더가 하지 못해 아쉬워한 일은 리더가 하지 않은 일이다. 한 일로 여기고 그 까닭이나 방법을 묻지 않는다.\n"
    "- 리더의 답에 누가 한 일인지가 없으면 리더가 한 일로 단정해 높임말로 옮기지 않는다. 그런 답 뒤에는 평서문 없이 질문만 한다.\n"
    "- 새 장면을 청할 때는 그런 일이 있었는지부터 묻는다 — 있었음을 전제하는 문형은 쓰지 않는다.\n"
    "- 평가하는 말은 쓰지 않는다(시스템이 지운다). 평서문은 들은 사실만.\n"
    "- 밀어붙이지 않는다: 리더가 없다·형식적으로 답하겠다고 하면 그대로 받아들이고 다음으로 간다. 기억이나 솔직함을 의심하는 말, "
    "다시 생각해 보라는 말은 쓰지 않는다.\n"
    "[금지]\n"
    "- 하위역량 이름·분류 설명, 진행 상태를 알리는 말, 칭찬·평가, 느낌표 남발, 회사명.\n"
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
