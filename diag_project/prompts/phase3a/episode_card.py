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


FIRST_PROBE_HEADER = "# 방금 들은 일에서 리더가 직접 한 것을 묻는 턴"


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
    if instruction == "EPISODE_PROBE" and ep and ep.get("ask_first"):
        # (2026-11-15 P13d-2 → P13e) 사례의 첫 꼬리 질문 턴 — 질문은 전용 호출(first_probe_render)이 만든다. 본 호출을 부르지 않으므로 카드는 머리 한 줄뿐.
        return FIRST_PROBE_HEADER
    if instruction in ("EPISODE_PROBE", "NO_CASE_REFRAME") and ep:
        n = ep.get("idx", 1)
        k = int(ep.get("leader_turns") or 0)
        _kmax = episode_turn_max(len((COMPETENCY_FRAMEWORK.get(chapter or "", {}) or {}).get("indicators") or {}))
        L.append(f"# 지금 듣고 있는 사례 ({n}번째 / 이 사례 리더 턴 {k}/{_kmax} / 이 영역 리더 턴 {bei_turns}/{budget})")
        filled = filled_slots(ep)
        partial = [x for x in SLOT_KEYS if ((ep.get("slots") or {}).get(x) or {}).get("status") == "partial"]
        missing = unfilled_slots(ep)
        # (2026-11-15 P13-3) 들은 것·남은 것을 문장이 아니라 자료(항목: 값)로만 넘긴다 — 11/14 운영 Lucas: "이 사례는 …까지 들었으니, 이제 …를 묻겠습니다",
        #   "지금 주신 답에서는 … 기준이 보입니다". 이 자료의 내용·낱말은 리더에게 말하지 않는다.
        L.append("[코치만 보는 자료 — 아래 내용과 낱말을 리더에게 말하지 않는다. 무엇을 들었는지·무엇이 남았는지·무엇을 물을지를 알리는 문장을 쓰지 않는다. 바로 질문한다]")
        if filled:
            L.append("들음: " + " | ".join(_quote_line(ep, x) for x in filled))
        if partial:
            L.append("반쯤: " + " | ".join(_quote_line(ep, x) for x in partial))
        if missing:
            L.append("아직: " + ", ".join(SLOT_LABELS[x] for x in missing))
        nxt = ask_slot(ep) if missing else None
        if nxt:
            L.append(f"이번 질문: '{SLOT_LABELS[nxt]}' 하나 — {SLOT_HINTS[nxt]}. 리더가 다른 데로 가면 한 번은 따라가되 질문은 지금 이야기로 돌아온다.")
            if nxt in partial:
                L.append("이 한 가지는 리더가 이미 일부를 말했다(위 '반쯤'의 인용). 이미 말한 것은 다시 묻지 않고 빠진 것만 묻는다.")
            L.append("때·사람(언제였는지, 누가 함께 있었는지)만 따로 묻는 질문은 하지 않는다.")
            # (2026-11-15 P13e-3) 다른 사람의 반응은 사례당 한 번 — 이미 물었으면 이번 질문에서는 묻지 않게 한 줄을 넣는다(물은 적이 없으면 넣지 않는다)
            if int(ep.get("reaction_asked") or 0) >= 1 and nxt != "reaction":
                L.append("이 사례에서 다른 사람이 어떻게 받았는지는 이미 한 번 물었다 — 이번 질문에서는 다시 묻지 않는다. 리더 본인이 한 것만 묻는다.")
            # (P13-2 → P13b-1) 상황이 아직 비어 있으면 둘째 꼬리 질문에 한 번만 곁들인다 — 첫 꼬리 질문 턴은 물을 것이 하나뿐이라 거기에는 싣지 않는다
            if (((ep.get("slots") or {}).get("context") or {}).get("status", "empty") == "empty"
                    and sum(int(v or 0) for v in (ep.get("slot_asks") or {}).values()) == 2):
                L.append("때와 함께 있던 사람이 아직 나오지 않았다 — 이 질문에 곁들여 한 번만 묻는다(따로 묻지 않는다).")
        else:
            L.append(f"이번 질문(장면 구체화): {detail_probe_hint(ep)}.")
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
        return FIRST_PROBE_HEADER      # 훑는 질문의 꼬리 질문도 전용 호출이 만든다
    # (2026-11-15 P13-3) 지난 사례 목록은 넘기지 않는다 — 코치가 앞 이야기를 끌어오거나 "이전 … 같은 장면으로 보이네요" 처럼 판정을 입 밖에 냈다.
    #   리더가 닫힌 이야기를 다시 말하는 경우는 사례 단계(같은 장면 판정)가 따로 받는다.
    _ = prev_episodes
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
        "방금 꺼낸 장면에 질문 하나만 더합니다. 질문 문장 1개(앞의 평서문 1문장은 없어도 됩니다). 묻는 것은 카드에 적힌 한 가지뿐입니다. 그 뒤 시스템이 다음으로 넘어갑니다."
    ),
}

TURN_FORMAT_RULES = (
    "[턴 형식]\n"
    "- 질문 1개로 끝낸다. 한 턴에 질문 문장은 하나다 — 질문 문장 뒤에 다른 질문 문장을 잇지 않는다. 한 턴에 묻는 것도 하나다 — "
    "둘 가운데 고르게 하는 꼴과, 두 가지를 이어 한 문장에 묻는 꼴을 쓰지 않는다.\n"
    "- 질문 문장에는 두 가지가 들어간다 — 무엇에 대해(리더가 말한 일·사람)와 무엇을 묻는지. 앞 문장 없이 그 질문만 읽어도 무엇에 대한 질문인지 "
    "알 수 있어야 한다. 때나 자리나 앞의 말을 가리키는 말만으로 질문을 시작하지 않는다. 질문 앞 평서문에 기대지 않는다.\n"
    "- 묻는 것은 리더 본인이 한 말·조치와 그 까닭·결과다. 리더가 이끌거나 함께 일하는 사람이 아닌 사람(가르친 사람, 고객)의 장면은 캐묻지 않는다 — "
    "그런 사람의 반응은 리더가 결과로 말할 때만 듣는다.\n"
    "- 다음 질문은 아직 듣지 못한 것(그 뒤의 결과, 그렇게 정한 기준, 다시 한다면 달리할 점)으로 나아간다. 이미 들은 대화를 한 마디씩 "
    "거슬러 올라가며 되묻지 않는다.\n"
    "- 지금 듣는 이야기의 말만 쓴다. 앞에서 끝난 다른 이야기를 평서문이나 질문에 끌어오지 않는다.\n"
    "- 질문 앞의 평서문은 없어도 된다. 쓰면 1문장 — 리더가 방금 쓴 낱말 한두 개만 넣는다. 답 전체를 다시 읊지 않고, 뜻을 풀이하지 않고, "
    "리더가 말하지 않은 사정·심정·까닭을 보태지 않는다. 받는 말은 리더가 쓴 낱말로만 쓴다 — 리더가 하지 않은 말, 평가, 짐작을 보태지 않는다.\n"
    # (2026-11-15 P13d-3) 받는 말은 허용 목록(되짚는 끝맺음·리더 낱말 둘 이상·12어절 이하)을 넘을 때만 나간다 — 그 꼴을 지시문에도 적는다
    #   (완성 문장 예시가 아니라 어미만 적는다 — 따옴표로 묶은 문장 꼴은 그대로 베낀다)
    "- 질문 앞의 평서문을 쓸 때는 리더가 한 말을 그대로 다시 말하는 꼴로 끝낸다 — 끝을 -셨군요, -말씀이군요, -거군요 가운데 하나로 맺는다. "
    "리더가 쓴 낱말을 둘 이상 넣고 12어절을 넘기지 않는다. 평가·짐작을 말하는 끝맺음으로 끝내지 않는다(그런 문장은 지워진다).\n"
    # (2026-11-15 P13e-5) 높임 방향 — p13d: 팀원의 행동에 높임 어미를 붙이거나, 리더가 팀원에게 한 행동에 낮춤말을 썼다. 설명으로만 적는다.
    "- 높임은 리더에게만 쓴다. 팀원·강사처럼 리더가 아닌 사람이 한 행동에는 높임 어미를 붙이지 않고, 리더가 그 사람에게 한 행동을 낮춤말로 옮기지 않는다.\n"
    "- 리더가 쓰지 않은 낱말을 리더가 한 말처럼 따옴표에 넣지 않는다. 리더의 말과 질문을 잇기만 하는 문구도 쓰지 않는다.\n"
    "- 리더의 말을 옮길 때 누가 한 일인지를 바꾸지 않는다 — 리더가 한 일은 리더가 한 일로, 다른 사람이 한 일은 그 사람이 한 일로 쓴다.\n"
    "- 리더가 이미 말한 때·사람·일은 다시 묻지 않는다. 아직 나오지 않은 것만 묻는다.\n"
    "- 리더의 답이 짧거나 모자라도 그렇다는 말을 하지 않는다. 더 쉬운 질문 하나로 넘어간다.\n"
    "- 리더가 떠오르지 않는다·그대로 옮기기 어렵다고 답한 것은 다시 묻지 않는다. 아직 묻지 않은 다른 것으로 넘어간다.\n"
    "- 사람은 리더가 쓴 이름·직함·말 그대로 쓴다. 리더가 쓰지 않은 말로 사람을 바꿔 쓰지 않는다.\n"
    "- 질문은 접속어·조건절로 시작하지 않는다.\n"
    "- 무엇을 물을지 미리 알리는 문장을 쓰지 않는다. 고맙다는 말은 사례를 닫을 때만 한다.\n"
    "- 리더가 반말이나 아주 짧은 말로 답해도 코치의 말씨는 그대로다. 리더의 말씨·말 길이를 입에 올리지 않고 따라 하지도 않는다.\n"
    "- 질문은 열린 질문 하나. 고를 것을 늘어놓는 질문은 쓰지 않는다 — 무엇을 했는지는 리더가 말한다.\n"
    "- 실제로 있었던 일만 묻는다. 일어나지 않은 일을 가정해서 묻지 않는다(다시 한다면 달리할 점을 묻는 것만 예외다). "
    "다른 사람이 속으로 무엇을 생각했는지·왜 그렇게 했는지를 리더에게 짐작하게 하는 질문도 하지 않는다.\n"
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


_RULE_WHAT = "- 묻는 것은 리더 본인이 한 말·조치와 그 까닭·결과다."
_RULE_NEXT = "- 다음 질문은 아직 듣지 못한 것("

def bei_turn_text(state: dict) -> str:
    """BEI 턴의 Layer3 본문: 페르소나 상기 + 사례 카드 + instruction 가이드 + 턴 형식·금지."""
    instruction = state.get("instruction_for_this_turn") or ""
    persona = state.get("coach_persona") or {}
    persona_block = ""
    if persona.get("name"):
        from diag_project.services.persona_voice import persona_guide_block
        # (2026-11-15 P13c-1) 사례의 첫 꼬리 질문 턴에는 코치 프로필의 탐침 선호 문구를 넣지 않는다(Daniel '결정의 기준과 책임' 등 여섯 코치 모두) —
        #   그 턴에 묻는 것은 리더가 직접 한 말·조치 하나로 정해져 있다.
        _first = str(state.get("bei_card") or "").startswith(FIRST_PROBE_HEADER)
        persona_block = (
            f"[🎭 페르소나 유지] 당신은 {persona['name']} — {persona.get('coaching_style', '')} ({persona.get('tags', '')}). "
            "문장 길이·종결어미·호응 방식은 시스템 프롬프트의 【말투 프로필】대로. 어느 코치든 같은 톤이 나오면 실패입니다.\n"
            + persona_guide_block(persona["name"], with_preference=not _first)
        )
    card = state.get("bei_card") or ""
    guide = BEI_GUIDES.get(instruction, "")
    rules = TURN_FORMAT_RULES
    return f"{persona_block}{card}\n\n[Instruction for this turn]\n{instruction}\n\n{guide}\n\n{rules}"


def is_bei_instruction(instruction: str | None) -> bool:
    return instruction in BEI_INSTRUCTIONS
