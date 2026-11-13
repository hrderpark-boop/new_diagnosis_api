"""(2026-11-12 P11b) Daniel 재시뮬 전 추가 수정 — 어미 변환(불규칙 용언 표)·안내 중복·연결 문구·관찰 슬롯 턴·받는 문장·질문·보완 사례 승격·휴식 제안."""
import pytest

from diag_project.services import conjugation as C
from diag_project.services import persona_register as R
from diag_project.services import persona_voice as V

# ── 1. 어미 변환: 불규칙 용언 표 ────────────────────────────────────────────
# 용언마다 (해요체 꼴, 합쇼체 꼴) — 코드가 쓰는 어미 전부: 질문 '~나요/~세요/~시나요/~어요/~었어요/~셨어요', 평서 '~어요/~네요/~는군요(군요)/~시네요/~ㄹ게요/~었어요'.
# 합쇼체 꼴이 None 이면 '표에 없는 꼴 — 바꾸지 않고 원문 유지'가 기대값이다.
VERBS: dict[str, dict[str, list[tuple[str, str | None]]]] = {
    "이끌다(ㄹ)": {
        "q": [("이끄나요?", "이끕니까?"), ("이끄세요?", "이끄십니까?"), ("이끄시나요?", "이끄십니까?"), ("이끌어요?", "이끕니까?"),
              ("이끌었어요?", "이끌었습니까?"), ("이끄셨어요?", "이끄셨습니까?")],
        "s": [("이끌어요.", "이끕니다."), ("이끄네요.", "이끕니다."), ("이끄는군요.", "이끕니다."), ("이끄시네요.", "이끄십니다."),
              ("이끌게요.", "이끌겠습니다."), ("이끌었어요.", "이끌었습니다.")]},
    "만들다(ㄹ)": {
        "q": [("만드나요?", "만듭니까?"), ("만드세요?", "만드십니까?"), ("만드시나요?", "만드십니까?"), ("만들어요?", "만듭니까?"),
              ("만들었어요?", "만들었습니까?"), ("만드셨어요?", "만드셨습니까?")],
        "s": [("만들어요.", "만듭니다."), ("만드네요.", "만듭니다."), ("만드는군요.", "만듭니다."), ("만드시네요.", "만드십니다."),
              ("만들게요.", "만들겠습니다."), ("만들었어요.", "만들었습니다.")]},
    "알다(ㄹ)": {
        "q": [("아나요?", "압니까?"), ("아세요?", "아십니까?"), ("아시나요?", "아십니까?"), ("알아요?", "압니까?"),
              ("알았어요?", "알았습니까?"), ("아셨어요?", "아셨습니까?")],
        "s": [("알아요.", "압니다."), ("아네요.", "압니다."), ("아는군요.", "압니다."), ("아시네요.", "아십니다."),
              ("알게요.", "알겠습니다."), ("알았어요.", "알았습니다.")]},
    "들다(ㄹ)": {
        "q": [("드나요?", "듭니까?"), ("드세요?", "드십니까?"), ("드시나요?", "드십니까?"), ("들어요?", None),     # '들어요' 는 듣다·들다 어느 쪽인지 모른다
              ("들었어요?", "들었습니까?"), ("드셨어요?", "드셨습니까?")],
        "s": [("들어요.", None), ("드네요.", "듭니다."), ("드는군요.", "듭니다."), ("드시네요.", "드십니다."),
              ("들게요.", None), ("들었어요.", "들었습니다.")]},
    "힘들다(ㄹ)": {
        "q": [("힘든가요?", "힘듭니까?"), ("힘드세요?", "힘드십니까?"), ("힘드셨어요?", "힘드셨습니까?"), ("힘들어요?", "힘듭니까?"),
              ("힘들었어요?", "힘들었습니까?")],
        "s": [("힘들어요.", "힘듭니다."), ("힘드네요.", "힘듭니다."), ("힘들군요.", "힘듭니다."), ("힘드시네요.", "힘드십니다."), ("힘들었어요.", "힘들었습니다.")]},
    "떠오르다(르)": {
        "q": [("떠오르나요?", "떠오릅니까?"), ("떠오르세요?", "떠오르십니까?"), ("떠오르시나요?", "떠오르십니까?"), ("떠올라요?", None),
              ("떠올랐어요?", "떠올랐습니까?"), ("떠오르셨어요?", "떠오르셨습니까?")],
        "s": [("떠올라요.", "떠오릅니다."), ("떠오르네요.", "떠오릅니다."), ("떠오르는군요.", "떠오릅니다."), ("떠오르시네요.", "떠오르십니다."),
              ("떠올랐어요.", "떠올랐습니다.")]},
    "고르다(르)": {
        "q": [("고르나요?", "고릅니까?"), ("고르세요?", "고르십니까?"), ("고르시나요?", "고르십니까?"), ("골라요?", None),
              ("골랐어요?", "골랐습니까?"), ("고르셨어요?", "고르셨습니까?")],
        "s": [("골라요.", "고릅니다."), ("고르네요.", "고릅니다."), ("고르는군요.", "고릅니다."), ("고르시네요.", "고르십니다."),
              ("고를게요.", "고르겠습니다."), ("골랐어요.", "골랐습니다.")]},
    "어렵다(ㅂ)": {
        "q": [("어려운가요?", "어렵습니까?"), ("어려우세요?", "어려우십니까?"), ("어려워요?", None), ("어려웠어요?", "어려웠습니까?"),
              ("어려우셨어요?", "어려우셨습니까?"), ("어렵나요?", "어렵습니까?")],
        "s": [("어려워요.", "어렵습니다."), ("어렵네요.", "어렵습니다."), ("어렵군요.", "어렵습니다."), ("어려우시네요.", "어려우십니다."),
              ("어려웠어요.", "어려웠습니다.")]},
    "쉽다(ㅂ)": {
        "q": [("쉬운가요?", "쉽습니까?"), ("쉬웠어요?", "쉬웠습니까?"), ("쉽나요?", "쉽습니까?")],
        "s": [("쉬워요.", "쉽습니다."), ("쉽네요.", "쉽습니다."), ("쉽군요.", "쉽습니다."), ("쉬웠어요.", "쉬웠습니다.")]},
    "돕다(ㅂ)": {
        "q": [("돕나요?", "돕습니까?"), ("도우세요?", "도우십니까?"), ("도우시나요?", "도우십니까?"), ("도와요?", None),
              ("도왔어요?", "도왔습니까?"), ("도우셨어요?", "도우셨습니까?")],
        "s": [("도와요.", "돕습니다."), ("돕네요.", "돕습니다."), ("돕는군요.", "돕습니다."), ("도우시네요.", "도우십니다."),
              ("도울게요.", "돕겠습니다."), ("도왔어요.", "도왔습니다.")]},
    "쓰다(ㅡ)": {
        "q": [("쓰나요?", "씁니까?"), ("쓰세요?", "쓰십니까?"), ("쓰시나요?", "쓰십니까?"), ("써요?", None),
              ("썼어요?", "썼습니까?"), ("쓰셨어요?", "쓰셨습니까?")],
        "s": [("써요.", "씁니다."), ("쓰네요.", "씁니다."), ("쓰는군요.", "씁니다."), ("쓰시네요.", "쓰십니다."), ("쓸게요.", "쓰겠습니다."), ("썼어요.", "썼습니다.")]},
    "크다(ㅡ)": {
        "q": [("큰가요?", "큽니까?"), ("크세요?", "크십니까?"), ("컸어요?", "컸습니까?")],
        "s": [("커요.", "큽니다."), ("크네요.", "큽니다."), ("크군요.", "큽니다."), ("컸어요.", "컸습니다.")]},
    "바쁘다(ㅡ)": {
        "q": [("바쁜가요?", "바쁩니까?"), ("바쁘세요?", "바쁘십니까?"), ("바빴어요?", "바빴습니까?"), ("바쁘셨어요?", "바쁘셨습니까?")],
        "s": [("바빠요.", "바쁩니다."), ("바쁘네요.", "바쁩니다."), ("바쁘군요.", "바쁩니다."), ("바쁘시네요.", "바쁘십니다."), ("바빴어요.", "바빴습니다.")]},
    "하다": {
        "q": [("하나요?", "합니까?"), ("하세요?", "하십니까?"), ("하시나요?", "하십니까?"), ("해요?", "합니까?"),
              ("했어요?", "했습니까?"), ("하셨어요?", "하셨습니까?")],
        "s": [("해요.", "합니다."), ("하네요.", "합니다."), ("하는군요.", "합니다."), ("하시네요.", "하십니다."), ("할게요.", "하겠습니다."), ("했어요.", "했습니다.")]},
    "생각하다": {
        "q": [("생각하나요?", "생각합니까?"), ("생각하세요?", "생각하십니까?"), ("생각하시나요?", "생각하십니까?"), ("생각해요?", "생각합니까?"),
              ("생각했어요?", "생각했습니까?"), ("생각하셨어요?", "생각하셨습니까?")],
        "s": [("생각해요.", "생각합니다."), ("생각하네요.", "생각합니다."), ("생각하는군요.", "생각합니다."), ("생각하시네요.", "생각하십니다."),
              ("생각할게요.", "생각하겠습니다."), ("생각했어요.", "생각했습니다.")]},
    "먹다(규칙)": {
        "q": [("먹나요?", "먹습니까?"), ("먹어요?", "먹습니까?"), ("먹었어요?", "먹었습니까?")],
        "s": [("먹어요.", "먹습니다."), ("먹네요.", "먹습니다."), ("먹는군요.", "먹습니다."), ("먹었어요.", "먹었습니다.")]},
    "좋다(규칙)": {
        "q": [("좋은가요?", "좋습니까?"), ("좋아요?", "좋습니까?"), ("좋았어요?", "좋았습니까?"), ("좋을까요?", "좋습니까?")],
        "s": [("좋아요.", "좋습니다."), ("좋네요.", "좋습니다."), ("좋군요.", "좋습니다."), ("좋았어요.", "좋았습니다.")]},
}
_PAIRS = [(v, kind, src, dst) for v, d in VERBS.items() for kind, rows in d.items() for src, dst in rows]


@pytest.mark.parametrize("verb,kind,src,dst", _PAIRS)
def test_p11b_1_polite_to_formal_table(verb, kind, src, dst):
    out = R._formalize_sentence("그 일을 " + src)
    got = out[len("그 일을 "):]
    assert got == (dst if dst is not None else src), (verb, src, got)
    assert C.bad_form(out) is None, (verb, out)
    # apply_register 로 돌려도 같다(Jessica = 합쇼체, 범위 전체)
    assert R.apply_register("Jessica", "그 일을 " + src, scope="strict")[0] == out, (verb, src)


# 합쇼체 → 해요체(해요체 코치의 여는 문장·범위 문장·질문). None = 바꾸지 않는다.
FORMAL_TO_POLITE = [
    ("이끕니다.", "이끌어요."), ("만듭니다.", "만들어요."), ("압니다.", "알아요."), ("힘듭니다.", "힘들어요."), ("듭니다.", "들어요."),
    ("떠오릅니다.", "떠올라요."), ("고릅니다.", "골라요."), ("다릅니다.", "달라요."), ("모릅니다.", "몰라요."), ("부릅니다.", "불러요."),
    ("어렵습니다.", "어려워요."), ("쉽습니다.", "쉬워요."), ("돕습니다.", "도와요."), ("고맙습니다.", "고마워요."),
    ("씁니다.", "써요."), ("큽니다.", "커요."), ("바쁩니다.", "바빠요."), ("아픕니다.", "아파요."), ("기쁩니다.", "기뻐요."), ("슬픕니다.", "슬퍼요."), ("모읍니다.", "모아요."),
    ("합니다.", "해요."), ("생각합니다.", "생각해요."), ("됩니다.", "돼요."), ("했습니다.", "했어요."), ("하겠습니다.", "할게요."),
    ("먹습니다.", "먹어요."), ("좋습니다.", "좋아요."), ("많습니다.", "많아요."), ("갑니다.", "가요."), ("봅니다.", "봐요."), ("줍니다.", "줘요."),
    ("마십니다.", "마셔요."), ("하십니다.", "하세요."), ("따릅니다.", "따라요."), ("치릅니다.", "치러요."),
    ("합니까?", "하나요?"), ("이끕니까?", "이끄나요?"), ("만듭니까?", "만드나요?"), ("떠오릅니까?", "떠오르나요?"), ("씁니까?", "쓰나요?"),
    ("먹습니까?", "먹나요?"), ("어렵습니까?", "어렵나요?"), ("하십니까?", "하세요?"), ("했습니까?", "했어요?"), ("무엇입니까?", "무엇인가요?"),
    ("이릅니다.", None),
]


@pytest.mark.parametrize("src,dst", FORMAL_TO_POLITE)
def test_p11b_1_formal_to_polite_table(src, dst):
    out = R._politen_sentence("그 일을 " + src)
    assert out[len("그 일을 "):] == (dst if dst is not None else src), (src, out)
    assert C.bad_form(out) is None


def test_p11b_1_bad_forms_and_repair():
    # 틀린 꼴은 잡고, 맞는 꼴은 잡지 않는다
    for bad in ("떠오르시습니까?", "떠오르습니까?", "만들습니다.", "하습니다.", "이끄고 계시는군요.", "만드지 않았습니다.", "만들나요?", "만들세요.",
                "떠오르어요.", "고르었습니다.", "어렵어요.", "쉽었습니다.", "쓰어요.", "바뻐요.", "하았습니다.", "좋는지요?", "어떻는지 말씀해 주시겠습니까?",
                "하을까요?", "만들으셨습니까?", "알습니다."):
        assert C.bad_form(bad), bad
    for good in ("이끌고 계시는군요.", "이끄시는군요.", "이끕니다.", "만드는 일", "만들지 않았습니다.", "떠오르십니까?", "차이입니다.", "돕는지요?", "들으셨습니까?",
                 "힘드셨겠습니다.", "했는지 말씀해 주시겠습니까?", "어려운지요?", "좋은지요?", "알겠습니다.", "살펴보겠습니다.", "있으셨습니까?", "만들었습니다."):
        assert C.bad_form(good) is None, good
    assert C.repair_l_stem("교육팀을 이끄고 계시는군요.") == ("교육팀을 이끌고 계시는군요.", 1)
    assert C.repair_l_stem("표를 만드게 된 계기") == ("표를 만들게 된 계기", 1)
    assert C.repair_l_stem("표를 만들셨군요.") == ("표를 만드셨군요.", 1)
    assert C.repair_l_stem("팀을 이끄시는군요. 표를 만드는 일, 힘드셨겠습니다.")[1] == 0
    # 변환 결과가 틀린 꼴이면 원문 유지
    assert C.safe("만들어요?", "만들을까요?") == "만들어요?"
    assert C.safe("했어요?", "했습니까?") == "했습니까?"


def test_p11b_1_daniel_tail_and_register():
    # Daniel 꼬리 변주 — 형용사에 '~는지' 를 붙이지 않는다
    assert V.voice_question("Daniel", "그 방식이 팀에 좋았어요?", variant=0).endswith("좋았는지 말씀해 주시겠습니까?")
    assert V._daniel("그 방식이 지금도 좋습니까?", 1) == "그 방식이 지금도 좋은지요?"
    assert V._daniel("그 일이 어렵습니까?", 0) == "그 일이 어려운지 말씀해 주시겠습니까?"
    assert V._daniel("그때 분위기는 어떻습니까?", 1) == "그때 분위기는 어떤지요?"
    assert V._daniel("그 기준을 뚫습니까?", 0) == "그 기준을 뚫습니까?"          # 표에 없는 어간 — 원문 유지
    # 시뮬 p11a 의 두 꼴
    assert R.apply_register("Daniel", "그때 처음 꺼내신 말이 무엇이었는지 떠오르시나요?", scope="questions")[0].endswith("떠오르십니까?")
    assert R.apply_register("Daniel", "그 장면이 지금도 떠오르나요?", scope="questions")[0].endswith("떠오릅니까?")
    assert R.apply_register("Jessica", "그 표는 누가 만들어요?", scope="questions")[0].endswith("만듭니까?")
    assert R.apply_register("Jessica", "그 기준이 무엇이에요?", scope="questions")[0].endswith("무엇입니까?")
    # 해요체 코치: '합니까?' 도 섞임으로 본다(종전 식은 낱자 'ㅂ니까' 라 걸리지 않았다)
    assert R.register_violations("Ella", "그 뒤에는 어떻게 합니까?") and R.apply_register("Ella", "그 뒤에는 어떻게 합니까?")[0].endswith("하나요?")
    assert R.apply_register("Olivia", "팀을 어떻게 이끕니까?")[0].endswith("이끄나요?")


def test_p11b_1_dictionary_anchors_have_no_bad_forms():
    """사전 앵커 전부 × 코치 6명 × 변주 3 — 어미 변환 결과에 틀린 활용 꼴이 없다."""
    from diag_project.services import anchor_render as AR
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK as CF
    n = 0
    for ch, cv in CF.items():
        if ch == "supplementary":
            continue
        for key in (cv.get("indicators") or {}):
            for pos in range(3):
                q = AR.dict_anchor(key, pos)
                if not q:
                    continue
                for p in ("Ella", "Olivia", "Michael", "Jessica", "Daniel", "Lucas"):
                    for v in range(3):
                        out = V.voice_question(p, q, variant=v)
                        assert C.bad_form(out) is None, (p, v, q, out)
                        n += 1
    assert n > 300


# ── 2. 안내 중복 ────────────────────────────────────────────────────────────
def test_p11b_2_intro_announce_ack_dropped():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import turn_checks as T
    from diag_project.services.intro_messages import build_intro_anchor_section
    assert T.is_intro_announce("네, 그러면 오늘 흐름부터 안내드리겠습니다.")
    assert T.is_intro_announce("그럼 진행 순서를 설명해 드릴게요.")
    assert not T.is_intro_announce("특별히 바라시는 것 없이 오셨군요.")
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_iia_a(llm_acknowledgment)" in src and '_tm["intro_dup"] = 1' in src
    from diag_project.services.intro_messages import PERSONA_LINES
    for p in ("Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"):
        # 기대 답이 없을 때: 코치별 다리 + 본문(첫 문장 뺌) — 안내 예고는 다리 한 번뿐. 기대 답이 있을 때: 받는 문장 + 본문 — 예고는 본문 첫 문장 한 번뿐
        full, tail = build_intro_anchor_section(p), build_intro_anchor_section(p, lead=False)
        assert T.is_intro_announce(PERSONA_LINES[p]["intro_bridge"]), p
        assert len([x for x in full.split("\n") if T.is_intro_announce(x)]) == 1 and not [x for x in tail.split("\n") if T.is_intro_announce(x)]
        assert tail.startswith("진단은 5개 영역") and full.endswith(tail)
    assert "lead=False)}" in src


# ── 3. 내용 없는 연결 문구 · 진행 해설 ──────────────────────────────────────
def test_p11b_3_link_frames_and_commentary():
    from diag_project.services import turn_checks as T
    from diag_project.services.style_tracker import format_style_constraints
    said = '방금 말씀하신 "자원"과도 이어지는 부분입니다만, 설계 초안을 쓰면서 무엇을 확인하려 하셨습니까?'
    out, n = T.strip_link_frames("TF에 자원했다는 말씀이셨군요. " + said)
    assert n == 1 and out == "TF에 자원했다는 말씀이셨군요. 설계 초안을 쓰면서 무엇을 확인하려 하셨습니까?"     # 리더가 실제로 한 말이어도 틀을 지운다
    assert T.strip_link_frames("앞서 말씀하신 납기 이야기와도 닿아 있는 대목입니다. 그 뒤 무엇이 달라졌습니까?") == ("그 뒤 무엇이 달라졌습니까?", 1)
    assert T.strip_link_frames("그 결에서 이어 여쭙니다만, 그때 무엇을 먼저 하셨습니까?")[0] == "그때 무엇을 먼저 하셨습니까?"
    assert T.strip_link_frames("표로 정리해 보여주셨군요. 그 표를 본 팀원은 뭐라고 했습니까?")[1] == 0
    # 진행 해설 — 사례 여는 턴
    op = "본부 지시가 먼저 내려오는 상황에서 중장기 흐름을 어떻게 보고 결정을 내리시는지 살펴보는 대목입니다. 최근에 내년 이후를 내다보고 내리신 결정이 있었습니까?"
    assert T.strip_progress_commentary(op) == ("최근에 내년 이후를 내다보고 내리신 결정이 있었습니까?", 1)
    assert T.strip_progress_commentary("팀원에게 일을 어떻게 맡기시는지 살펴보겠습니다. 최근에 일을 통째로 맡기신 적이 있었습니까?")[1] == 1
    assert T.strip_progress_commentary("일을 맡기는 장면을 살펴보는 대목입니다만, 최근에 일을 통째로 맡기신 적이 있었습니까?")[0] == "최근에 일을 통째로 맡기신 적이 있었습니까?"
    assert T.strip_progress_commentary("이번에는 일을 맡기는 쪽 이야기입니다. 최근에 일을 통째로 맡기신 적이 있었습니까?")[1] == 0
    assert T.strip_progress_commentary("그 부분을 살펴보겠습니다.")[1] == 0                        # 질문이 남지 않으면 지우지 않는다
    # 프롬프트에서 틀 예시가 빠졌다
    for n_ in ("Daniel (다니엘)", "Ella (엘라)", "Michael (마이클)"):
        t = format_style_constraints({}, n_)
        assert "이어지는" not in t and "닿아 있" not in t and "쉽지 않은 자리" not in t and "연결 문구는 쓰지 않습니다" in t


def test_p11b_3_6_opener_frames():
    from diag_project.services import anchor_render as AR
    from diag_project.services import turn_checks as T
    assert len(AR.OPENER_FRAMES) == 5 and not any("대목" in f for f in AR.OPENER_FRAMES)
    assert not any("대목" in e or e.startswith("장을 보다 보면") for e in AR.OPENER_FRAME_EXAMPLES + AR.OPENER_FRAME_EXAMPLES_FORMAL)
    used: list[int] = []
    for _ in range(10):
        f = AR.pick_opener_frame(used)
        assert not used or f != used[-1]
        used.append(f)
    assert all(used.count(i) == 2 for i in range(5))                                             # 같은 틀은 세션 2회까지, 직전 틀 제외
    assert T.strip_lean_start("하다 보면 팀원에게 큰 방향을 설명하고 함께 움직이도록 설득해야 할 때가 생깁니다.") == (
        "팀원에게 큰 방향을 설명하고 함께 움직이도록 설득해야 할 때가 생깁니다.", True)
    assert T.strip_lean_start("그러다 보면 일정이 밀려 우선순위를 다시 정해야 할 때가 생깁니다.")[1] is True
    assert T.strip_lean_start("팀을 맡다 보면 방향을 다시 설명해야 할 때가 생깁니다.")[1] is False


@pytest.mark.asyncio
async def test_p11b_3_opener_render_bare_and_commentary(monkeypatch):
    from diag_project.services import anchor_render as AR
    monkeypatch.delenv("FM_LLM_STUB", raising=False)

    class _LLM:
        def __init__(self, outs):
            self.outs, self.n = list(outs), 0

        async def _generate_with_retry(self, **kw):
            self.n += 1
            return self.outs.pop(0)
    fb = "최근에 내년 이후를 내다보고 내리신 결정이 있었습니까?"
    llm = _LLM([])
    assert await AR.render_opener(llm, chapter="organization_management", sub_key="strategic_thinking", persona_name="Daniel", leader_text="",
                                  fallback_question=fb, frame=AR.OPENER_BARE_FRAME) == (fb, "bare") and llm.n == 0
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK as CF
    key = next(iter(CF["organization_management"]["indicators"]))
    llm = _LLM(["하다 보면 중장기 흐름을 어떻게 보는지 살펴보는 대목입니다. 최근에 내년 이후를 내다보고 내리신 결정이 있었습니까?"])
    txt, mode = await AR.render_opener(llm, chapter="organization_management", sub_key=key, persona_name="Daniel", leader_text="", fallback_question=fb, frame=0)
    assert txt == "최근에 내년 이후를 내다보고 내리신 결정이 있었습니까?" and mode == "llm" and llm.n == 1          # 해설은 지우고 다시 쓰지 않는다
    llm = _LLM(["하다 보면 팀원에게 방향을 다시 설명해야 할 때가 생깁니다. 최근에 방향을 다시 설명하신 일이 있었습니까?"])
    txt, mode = await AR.render_opener(llm, chapter="organization_management", sub_key=key, persona_name="Daniel", leader_text="", fallback_question=fb, frame=0)
    assert txt.startswith("팀원에게 방향을") and mode == "llm" and llm.n == 1


# ── 4. 관찰 슬롯이 들어간 턴 ────────────────────────────────────────────────
def test_p11b_4_slot_turn_shape_and_repeat_word():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import slot_render as SR
    leader = ["김선임이랑 박선임이 반대했어. 전체 개편 대신 한 과정만 파일럿으로 돌려보자고 제안했고 파일럿 설계 초안은 내가 직접 썼어.",
              "파일럿 만족도가 높게 나와서 하반기에 전체 개편으로 넘어갔어. 김선임이랑 박선임이 개편 TF에 자원했어."]
    slot = "김선임과 박선임의 반대 속에 파일럿을 제안하며 쉽지 않은 자리를 지키셨습니다."      # (P12c-3) 관찰 문장은 12어절 이하
    q = "파일럿 설계 초안을 직접 쓰면서 쉽지 않은 대목은 무엇이었습니까?"
    assert SR.repeated_turn_words(slot, q, leader) == ["쉽지"]
    assert SR.slot_sentence_ok("observation", slot, leader, persona_name="Daniel", avoid_text=q) == (False, "repeat_word")
    assert SR.slot_sentence_ok("observation", slot, leader, persona_name="Daniel", avoid_text="파일럿 설계 초안을 직접 쓰면서 무엇을 확인하려 하셨습니까?")[0]
    assert SR.slot_sentence_ok("observation", slot, leader, persona_name="Daniel")[0]
    src = inspect.getsource(D._submit_message_phase3a)
    assert 'clean_reply = " ".join([_slot_txt] + ([_q_now_s] if _q_now_s else [])).strip()' in src          # 관찰·응원 슬롯 턴 = 슬롯 + 질문(받기 없음)
    assert 'avoid_text=(_q_now_s if _stmt_slot else None)' in src


# ── 5. 받는 문장 ────────────────────────────────────────────────────────────
def test_p11b_5_leader_prefix_and_repeat_cap():
    from diag_project.services import turn_checks as T
    from diag_project.services.receive_check import quote_receive
    bad = '리더님께서 억울해하던 이기획님이 표를 보고 "제가 몰랐네요"라고 하셨고, 월간 점검도 먼저 맡겠다고 나섰다는 거군요.'
    assert T.starts_with_leader_prefix(bad) and T.leader_prefix_wrong_subject(bad)
    assert T.strip_leader_prefix(bad).startswith("억울해하던 이기획님이")
    ok = "리더님께서 면담 전에 분기별 지연 건을 표로 정리해 보여주셨고, 다음 분기 목표는 두 분이 함께 다시 쓰셨군요."
    assert T.starts_with_leader_prefix(ok) and not T.leader_prefix_wrong_subject(ok)
    assert not T.starts_with_leader_prefix("표로 정리해 보여주셨군요.") and T.LEADER_PREFIX_SESSION_MAX == 2
    # 답 전체를 되풀이한 받기 — 상한(리더 답 어절 60% 이상 + 받기 내용 어절 10개 이상)
    u = "그날 저녁에 원인부터 쪼갰어. 강사 공백보다 교안이 그분 머릿속에만 있던 게 문제라서, 다음 날 박선임이랑 교안부터 문서로 복원했어."
    long_recv = "그날 저녁에 원인부터 쪼개셨고, 강사 공백보다 교안이 그분 머릿속에만 있던 게 문제라서 다음 날 박선임과 교안부터 문서로 복원하셨군요."
    a, b, n = T.receive_overlap(long_recv, u)
    assert b >= T.RECEIVE_REPEAT_MAX and n >= T.RECEIVE_REPEAT_MIN_CHUNKS
    a, b, n = T.receive_overlap("교안부터 문서로 복원하셨군요.", u)
    assert not (b >= T.RECEIVE_REPEAT_MAX and n >= T.RECEIVE_REPEAT_MIN_CHUNKS)
    # 반말 답에서도 구절 인용 받기가 만들어진다(시뮬 p11a 에서 받기가 빠진 두 턴 + 머리가 잘린 꼴)
    assert quote_receive("그 자리에선 말 안 했어. 첫 지연 때 바로 앉았어야 했는데, 평가 때까지 미뤘어.") == "'바로 앉았어야 했는데, 평가 때까지 미뤘다'는 말씀이셨군요."
    assert quote_receive(u + " 첫 회차는 내가 직접 맡기로 하고, 일정표도 날짜 단위로 다시 짜서 그 주 안에 팀에 공유했어.").endswith("팀에 공유했다'는 말씀이셨군요.")
    assert quote_receive("감정 말고 기록으로 봐야 다음 행동이 바뀐다고 봤어.") == "'기록으로 봐야 다음 행동이 바뀐다고 봤다'는 말씀이셨군요."
    assert quote_receive("다시 하면 본부 지시 오기 전에 내가 먼저 개편 얘기를 꺼냈을 거야. 지시로 시작하니까 반대부터 나오더라.") == "'먼저 개편 얘기를 꺼냈을 것이다'는 말씀이셨군요."
    assert "내가" not in quote_receive("그래서 내가 직접 첫 회차를 맡았어.")


# ── 6. 질문 ─────────────────────────────────────────────────────────────────
def test_p11b_6_inline_two_questions_and_tail():
    from diag_project.services import turn_checks as T
    q = "파일럿 설계 초안을 직접 쓰면서 두 달 동안 무엇을 확인하려 하셨고, 다른 과정이 아니라 그 과정을 고르신 판단 기준은 무엇이었습니까?"
    assert len(T.inline_question_clauses(q)) == 2
    assert T.keep_slot_question(q, "criterion", formal=True) == ("다른 과정이 아니라 그 과정을 고르신 판단 기준은 무엇이었습니까?", True)
    assert T.keep_slot_question(q, "action", formal=True) == ("파일럿 설계 초안을 직접 쓰면서 두 달 동안 무엇을 확인하려 하셨습니까?", True)
    assert T.keep_slot_question(q, "action", formal=False)[0].endswith("확인하려 하셨어요?")
    assert T.keep_slot_question("그때 팀원은 뭐라고 했는지, 그 뒤 무엇이 달라졌는지 들려주시겠어요?", "reaction", formal=False) == (
        "그때 팀원은 뭐라고 했는지 들려주시겠어요?", True)
    one = "면담 전에 표로 정리해 보여주셨을 때, 이기획님은 뭐라고 했습니까?"
    assert T.keep_slot_question(one, "reaction", formal=True) == (one, False)                    # 의문사 절이 하나면 그대로
    assert T.keep_slot_question("누가 언제 무엇을 했는지 말씀해 주시겠습니까?", "context", formal=True)[1] is False
    # (P11c-5) 꼬리 규칙(자른 뒤 남은 질문을 기본 질문으로)은 삭제 — 함수도 없다
    assert not hasattr(T, "question_shares_words")
    # 다시 묻는 질문에 리더가 말하지 않은 사실
    orig = "그때 리더님께서 직접 팀원들에게 하신 말이나 결정 가운데 가장 먼저 떠오르는 것이 무엇이었습니까?"
    lead = ["올해 1월에 대표가 교육 운영에 AI 도구를 바로 전면 도입하자고 했어. 근데 팀에 그걸 쓸 줄 아는 사람이 나 말고는 없었어."]
    assert not hasattr(T, "unsaid_fact_words") and orig and lead      # (P11d-1) 다시 묻기 후보 검사 삭제 — 전용 호출의 지시문이 맡는다


# ── 7. 보완 질문에서 나온 사례 · 8. 휴식 제안 ───────────────────────────────
def _sweep_store(budget_left: int, unasked_n: int):
    from diag_project.services import bei_engine as B
    ch = "performance_management"
    subs = ["목표설정 및 공유", "성과지표 관리(KPI)", "성과평가 및 피드백", "문제해결", "실행력"]
    asked = subs[: len(subs) - unasked_n]
    store = {"bei_turns": {ch: B.chapter_budget(ch) - budget_left}, "asked_subs": {ch: list(asked)}, "sweep_asked": {ch: [asked[-1]]}}
    store, ep = B.new_episode(store, ch, asked[-1], "k", kind="sweep")
    store, ep = B.record_leader_turn(store, ch, ep)
    return B, ch, subs, store, ep


def test_p11b_7_sweep_promotion():
    B, ch, subs, store, ep = _sweep_store(budget_left=7, unasked_n=1)       # 방금 1턴 썼으니 남은 6, 미질문 1 → 여유 5
    assert B.sweep_promote_decision(store, ch, subs, ep, incident=True) == "promoted"
    assert B.sweep_promote_decision(store, ch, subs, ep, incident=False) is None                  # 사건이 아니면 종전대로
    assert B.sweep_promote_decision(store, ch, subs, ep, incident=None) is None
    B2, ch2, subs2, store2, ep2 = _sweep_store(budget_left=3, unasked_n=1)  # 남은 2, 미질문 1 → 여유 1 → 올리지 않는다
    assert B2.sweep_promote_decision(store2, ch2, subs2, ep2, incident=True) == "no_budget"
    ep_done = dict(ep, promote="promoted")
    assert B.sweep_promote_decision(store, ch, subs, ep_done, incident=True) is None             # 이미 정했다
    # 올린 사례: 여섯 가지가 차면 닫고, 리더 턴 4 에서 닫고, 미질문 예약을 침범하면 닫는다
    assert B.promoted_done_reason(ep_done, store, ch, subs) is None
    full = dict(ep_done, slots={k: {"status": "filled", "quote": "x"} for k in B.SLOT_KEYS})
    assert B.promoted_done_reason(full, store, ch, subs) == "slots"
    assert B.promoted_done_reason(dict(ep_done, leader_turns=4), store, ch, subs) == "turns"
    tight = dict(store, bei_turns={ch: B.chapter_budget(ch) - 1})                                  # 남은 1 = 미질문 1 → 예약 침범
    assert B.promoted_done_reason(dict(ep_done, leader_turns=2), tight, ch, subs) == "reserve"
    assert B.SWEEP_PROMOTE_MAX_TURNS == 4


def test_p11b_8_pause_only_on_natural_close():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B
    assert B.is_natural_close("episode2:done") and B.is_natural_close("episode1:turns")
    for tag in ("sweep1:sweep_done", "sweep2:no_case", "episode2:stalled", "episode1:reserve", "episode3:budget", "episode1:no_case", None, ""):
        assert not B.is_natural_close(tag), tag
    src = inspect.getsource(D._submit_message_phase3a)
    assert "case_closed=_natural_close" in src and '_tm["pause_block"]' in src


def test_p11b_5_plain_ending_after_past_tense():
    """받침 ㅆ(과거) 뒤의 종결 어미는 '다' — 스텁 점검에서 '바꿨습니다' 가 '바꿨는다' 로 인용됐다."""
    from diag_project.services.receive_check import _plain_ending, quote_receive
    for src, dst in (("그 도구로 바꿨습니다", "그 도구로 바꿨다"), ("그 도구로 바꿨더라", "그 도구로 바꿨다"), ("일을 맡겼어요", "일을 맡겼다"),
                     ("직접 가르쳤지", "직접 가르쳤다"), ("표를 받습니다", "표를 받는다"), ("그게 좋습니다", "그게 좋다")):
        assert _plain_ending(src) == dst, src
    assert "바꿨는다" not in quote_receive("최운영은 석 달 만에 자기 업무 절반을 그 도구로 바꿨습니다.")


# ── 재시뮬 p11b 전문에서 찾아 고친 것(재시뮬 없음 — 단위 시험만) ──────────────
def test_p11b_after_sim_question_forms():
    from diag_project.services import output_guard as G
    from diag_project.services import turn_checks as T
    from diag_project.services.input_anomaly import last_question_of
    # '짚어 주십시오' 도 질문 — 입버릇 대체 표현이 질문으로 읽히지 않아 그 뒤의 '네, 맞아요' 가 다시 묻기로 가지 못했다
    q = "그 첫 지연이 났던 날, 어떤 일이었고 누구와 함께 있었는지 조금 더 짚어 주십시오."
    assert G.is_question(q) and last_question_of("첫 지연 때 바로 앉으셨어야 했다는 말씀이군요. " + q) == q
    # '전면 도입을 …' 의 '전면' 은 조건절이 아니다 — 두 질문이면 마지막 하나만
    t = ("대표님이 월별 계획을 보고 받아들이셨군요. 그 판단은 무엇을 기준으로 하셨습니까? "
         "전면 도입을 미루고 운영팀 두 명부터 가자고 정하실 때, 어떤 점을 가장 무겁게 따져 보셨는지 궁금합니다.")
    out, n = G.keep_last_question(t)
    assert n == 1 and "무엇을 기준으로" not in out and G.count_question_markers(out) == 1
    assert G.starts_without_main_clause("있었다면 언제였는지 말씀해 주시겠습니까?") and not G.starts_without_main_clause("전면 도입을 미루실 때 무엇을 보셨습니까?")
    # 한 문장 안 두 질문 — 앞 절이 이미 질문으로 끝난 꼴 · '~는지, 있었다면 ~는지'
    q1 = "그때 이기획 님의 반응은 어떠했습니까, 말이나 표정, 혹은 이후 일하는 태도에서 달라진 것이 있었습니까?"
    assert T.keep_slot_question(q1, "reaction", formal=True) == ("그때 이기획 님의 반응은 어떠했습니까?", True)
    q2 = "그럴 때 5점 설문을 바꿔 보자고 직접 나서셨던 일이 있으셨는지, 있었다면 그때 리더님께서 무엇을 먼저 하셨는지 말씀해 주시겠습니까?"
    assert T.keep_slot_question(q2, "action", formal=True) == ("그때 리더님께서 무엇을 먼저 하셨는지 말씀해 주시겠습니까?", True)
    assert T.keep_slot_question("언제쯤이었고 누구와 함께 있었는지 짚어 주시겠습니까?", "context", formal=True)[1] is False
    assert T.strip_question_start("특히 과정을 맡은 강사분들이 어떤 말로 받아들였는지 들려주시겠습니까?").startswith("과정을 맡은")
    # 가리키는 말의 대상은 이 사례에서 리더가 한 말 전체에서 찾는다
    ctx = ["작년 12월 평가 때 이기획한테 낮은 등급을 줘야 했어.", "올해 상반기엔 납기 한 번도 안 놓쳤어."]
    assert T.question_issues("그 평가 자리에서 무엇을 먼저 말씀하셨습니까?", ctx[-1]) == []      # (P11d-2) 가리키는 말 검사 삭제


def test_p11b_after_sim_receive_and_slot_forms():
    from diag_project.services import slot_render as SR
    from diag_project.services import turn_checks as T
    from diag_project.services.phrase_caps import enforce_phrase_caps
    from diag_project.services.receive_check import quote_receive, quote_receive_count
    from diag_project.services.style_tracker import format_style_constraints
    assert T.receive_ban_reason("우선 대표님 지시 앞에서 쓸 줄 아는 사람이 리더님 한 분뿐이었다는 상황을 받겠습니다.") == "meta"
    assert T.receive_ban_reason("낮은 등급을 주셔야 했던 건, 그 간극을 리더님께서 무겁게 보셨기 때문이겠지요.") == "interpretive"
    assert T.receive_ban_reason('"네, 맞아요"라고 짧게 확인해 주셨는데, 그 답이 어떻게 받아들여졌는지까지 닿았는지는 아직 잘 보이지 않습니다.') == "speech_style"
    assert T.receive_ban_reason("표로 정리해 보여주셨군요.") is None
    assert "받겠" not in format_style_constraints({}, "Daniel (다니엘)") and "받는 문장" not in format_style_constraints({}, "Daniel (다니엘)")
    # 구절 인용 받기 — 리더의 1인칭을 옮기지 않고, 두 꼴을 번갈아 쓴다
    u = "전체 대신 한 과정만 두 달 파일럿으로 해보자고 제안했어. 파일럿 설계 초안은 내가 직접 썼어."
    assert quote_receive(u) == "'파일럿 설계 초안은 직접 썼다'는 말씀이셨군요." and quote_receive(u, 1) == "'파일럿 설계 초안은 직접 썼다'고 하셨군요."
    assert quote_receive_count([quote_receive(u), "다른 문장입니다.", quote_receive(u, 1) + " 그 뒤 무엇이 달라졌습니까?"]) == 2
    # 관찰 슬롯 — 지시문의 말을 옮긴 문장은 불합격
    leader = ["작년 3월에 본부에서 교육 체계 바꾸라고 했을 때, 김선임이랑 박선임이 반대했어.", "전체 대신 한 과정만 파일럿으로 해보자고 제안했어."]
    bad = "작년 3월 본부 지시와 김선임·박선임의 반대 사이에서 개편의 순서를 직접 정하셨던 그 무게를 알아주셨습니다."
    assert SR.slot_sentence_ok("observation", bad, leader, persona_name="Daniel")[0] is False      # 누설 낱말('알아주셨습니다') 또는 지시문 되읊기
    assert "알아주" not in SR._SPEC["observation"][0] and "선배로서" not in SR._SPEC["observation"][0]
    # 입버릇 대체 표현 — 영역 안에서 돌려 쓴다(같은 대체 표현만 되풀이하지 않는다)
    ch: list[str] = []
    for _ in range(6):
        out, _n = enforce_phrase_caps("그 장면을 말씀해 주시겠습니까?", session_texts=ch, chapter_texts=ch, formal=True)
        ch.append(out)
    assert set(ch) == {"그 장면을 말씀해 주시겠습니까?"}      # (P11c-5) 상한을 넘어도 바꾸지 않는다 — 치환표로 같은 대체 표현이 되풀이되던 것을 없앴다


def test_p11b_after_sim_handler_guards():
    import inspect
    from diag_project.routes import diagnoses as D
    src = inspect.getsource(D._submit_message_phase3a)
    assert '_tm["opener_restored"] = 1' in src and '_tm["opener_restored"] = 2' in src                # 여는 턴의 질문 유실 → 다시 조립 · 마지막 안전망
    assert "split_compound_question" not in src and "_ksq_" not in src                                  # (P11c-2) 한 문장짜리 질문은 자르지 않는다
    assert "_align_ctx is None and not _reask_kind):   # (시뮬 p11b) 다시 묻기 턴은 8-w0 가 조립한 그대로" in src   # 8-w3 는 다시 묻기 턴을 건너뛴다
    assert 'not _reask_kind and instruction_used != "NO_CASE_REFRAME"):' in src                         # 8-w4 는 사례 없음 재질문 턴을 건너뛴다
    assert "_qrcv_w0" not in src and "_qrcv_5" not in src                                              # (P11c-1) 금지 꼴·되풀이 문장은 삭제만 — 구절 인용 대체 없음


# ── P11c 규칙 줄이기 ────────────────────────────────────────────────────────
def test_p11c_receive_optional_and_one_question():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import receive_check as RC
    from diag_project.services import turn_checks as T
    src = inspect.getsource(D._submit_message_phase3a)
    # 1. 탐침 턴은 받는 문장 필수 검사가 없다 · 금지 꼴·되풀이는 삭제만 · 구절 인용 대체는 닫고 넘어가는 턴에서 세션 2회까지
    assert 'if _recv_optional or _q_expected or _tm.get("recv_ban"):' in src and "_qr_variant < QUOTE_RECEIVE_SESSION_MAX" in src and RC.QUOTE_RECEIVE_SESSION_MAX == 2
    assert '_drop_5 = "repeat"' in src and '_drop_5 = "quote_cap"' in src
    assert RC.is_quote_receive("'바로 앉았어야 했다'는 말씀이셨군요.") and RC.is_quote_receive("'직접 썼다'고 하셨군요.") and RC.is_quote_receive('"제가 몰랐네요"라고 하셨군요.')
    assert not RC.is_quote_receive("표로 정리해 보여주셨군요.")
    assert RC.quote_receive_count(["'직접 썼다'고 하셨군요. 그 뒤 무엇이 달라졌습니까?", "표로 정리해 보여주셨군요.", "'미뤘다'는 말씀이셨군요."]) == 2
    # 2. 질문 수는 문장 수 — 한 문장짜리 질문은 자르지 않는다 · 질문이 0개면 붙인다
    assert "split_compound_question" not in src and "keep_slot_question" not in src and "(tail)" not in src
    assert '_tm["q_added"] = "none→"' in src and "# 8-q." in src
    # 5. 다시 묻기 턴에는 재생성이 끼어들지 않는다 · 대상 없는 질문은 재생성 없이 고친다
    assert '_tm["no_regen"] = 1      # (2026-11-12 P11c-5)' in src and 'why="no_referent"' not in src
    # 4. 사례 없음 뒤 재질문은 '있었는지'를 다른 각도로 — 사례가 있다고 전제한 질문은 아니다 · 같은 질문은 한 사례에서 2회까지
    assert T.reframe_question_ok("작은 일이어도 괜찮으니, 최근에 팀원과 진행 상황을 짚다가 일이 어긋났던 순간이 있었는지 여쭤봐도 될까요?")
    assert not T.reframe_question_ok("언제 누구와 있었던 일인지 말씀해 주시겠습니까?")
    assert not T.reframe_question_ok("그때 리더님이 직접 하신 말이나 행동은 무엇이었습니까?")
    a = "그 지연이 났던 날, 어떤 건이었는지 기억나는 대로 짚어 주십시오."
    assert T.same_question(a, "그 지연이 나던 날, 어떤 건이었는지 떠오르는 대로 짚어 주십시오.")
    assert T.same_question("그 첫 지연이 난 장면을 다시 떠올려 보시면, 언제쯤이었고 누구와 함께 있었는지 짚어 주시겠습니까?",
                           "그때 실제로 지연을 보고 계셨던 시점을 떠올리시면, 언제쯤이었고 누구와 같이 계셨는지 짚어 주시겠습니까?")
    assert not T.same_question(a, "그 뒤로 월간 점검은 실제로 어떻게 돌아갔습니까?")


def test_p11c_stalled_empty_closes_as_no_case():
    from diag_project.services import bei_engine as B
    ch = "performance_management"
    store = {"bei_turns": {ch: 8}}
    store, ep = B.new_episode(store, ch, "문제해결", "k")
    ep = dict(ep, leader_turns=2, stall=2)
    assert B.episode_done_reason(ep, store, ch) == "stalled_empty"                       # 채운 칸 없이 2턴 무진전
    assert B.episode_done_reason(dict(ep, stall=1), store, ch) is None
    filled = dict(ep, slots={**B.empty_slots(), "context": {"status": "filled", "quote": "x"}})
    assert B.episode_done_reason(filled, store, ch) == "stalled"                         # 채운 칸이 있으면 종전대로
    assert B.promoted_done_reason(dict(ep, kind="sweep", promote="promoted"), store, ch) == "stalled_empty"


def test_p11c_prompts_have_no_copyable_sentences_or_inner_terms():
    import re
    from diag_project.data.coaches_persona import COACHES_PERSONA
    from diag_project.prompts.phase3a import episode_card as EC, layer1_system as L1
    from diag_project.services.output_guard import BANNED_STATE_LEAK
    from diag_project.services.persona_voice import persona_guide_block
    from diag_project.services.style_tracker import format_style_constraints
    end = r"(요|다|까|죠|군요|네요|세요|니다|니까|데요)[.?!…]*"
    quoted = re.compile(r"['‘\"“]([^'‘’\"“”\n~/]{6,90}?" + end + r")['’\"”]")
    for cid, c in COACHES_PERSONA.items():
        name = c["name"]
        txt = (L1.build_layer1_with_persona(coach_id=cid, user_name="박기진", visit_count=1, mode="heavy") + "\n" + "\n".join(EC.BEI_GUIDES.values())
               + EC.TURN_FORMAT_RULES + format_style_constraints({}, name, "EPISODE_PROBE") + persona_guide_block(name))
        txt = txt.replace('"이 리더십 진단 과정을 함께 진행하는 전문 코치"', "")              # 소속을 물으면 이렇게만 답한다 — 지정 문구
        assert quoted.findall(txt) == [], (name, quoted.findall(txt))
        for w in ("되받기", "받는 문장", "받기", "슬롯", "다리", "무게", "알아주", "예시 발화"):
            assert w not in txt, (name, w)
    for w in ("받겠습니다", "알아주셨습니다", "짧게 확인해 주셨는데"):
        assert w in BANNED_STATE_LEAK


# ── P11d ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_p11d_1_reask_is_one_dedicated_call(monkeypatch):
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import reask_render as RR
    monkeypatch.delenv("FM_LLM_STUB", raising=False)

    class _LLM:
        def __init__(self, out):
            self.out, self.n, self.prompt = out, 0, ""

        async def _generate_with_retry(self, **kw):
            self.n += 1
            self.prompt = kw.get("prompt") or ""
            return self.out
    prev = "두 달 파일럿을 마친 뒤 교육팀에는 무엇이 달라졌습니까?"
    lead = ["전면 개편 대신 한 과정만 두 달 파일럿으로 해보자고 했어."]
    llm = _LLM("파일럿이 끝나고 나서 팀에서 바뀐 것이 있었습니까?")
    assert await RR.render_reask(llm, kind="clarify", prev_question=prev, leader_texts=lead, persona_name="Daniel") == ("파일럿이 끝나고 나서 팀에서 바뀐 것이 있었습니까?", "llm")
    assert llm.n == 1 and "더 쉬운 낱말" in llm.prompt and "같은 문장을 쓰지 않는다" in llm.prompt and prev in llm.prompt
    llm = _LLM(prev)                                                                    # 직전 질문과 글자가 같으면 불합격(다시 쓰지 않는다)
    assert await RR.render_reask(llm, kind="clarify", prev_question=prev, leader_texts=lead, persona_name="Daniel") == (None, "miss:same") and llm.n == 1
    llm = _LLM("제 질문이 어려웠습니다.")
    assert (await RR.render_reask(llm, kind="contentless", prev_question=prev, leader_texts=lead, persona_name="Daniel"))[1] == "miss:no_question"
    llm = _LLM("파일럿 뒤에 가장 먼저 바뀐 한 가지는 뭐였어요?")                        # 합쇼체 코치의 어미로
    q, mode = await RR.render_reask(llm, kind="contentless", prev_question=prev, leader_texts=lead, persona_name="Daniel")
    assert mode == "llm" and q.endswith("습니까?") and "묻는 것을 바꾸지 않습니다" in llm.prompt and "한 가지" not in llm.prompt and "그 자리에서" not in llm.prompt   # (P11e-6 → P12c-1) 묻는 것은 그대로
    assert RR.same_text("그 뒤 무엇이 달라졌습니까?", "그 뒤  무엇이 달라졌습니까 ?") and not RR.same_text("a?", "")
    src = inspect.getsource(D._submit_message_phase3a)
    assert "elif _reask_kind and chapter and _bei_ep is not None:" in src and "_rr_rq(llm, kind=_reask_kind" in src      # 본 호출 대신 전용 호출
    assert src.count("clean_reply = _reask_final") == 2 and "reask_candidate_ok" not in src and "unsaid_fact_words" not in src


def test_p11d_2_3_4_deletions_prompts_and_fixed_lines():
    import inspect
    from diag_project.prompts.phase3a.episode_card import TURN_FORMAT_RULES, build_episode_card
    from diag_project.routes import diagnoses as D
    from diag_project.services import anchor_render as AR
    from diag_project.services import close_render as CR
    from diag_project.services import persona_register as R
    from diag_project.services import slot_render as SR
    from diag_project.services.output_guard import BANNED_STATE_LEAK
    src = inspect.getsource(D._submit_message_phase3a)
    # 2. 삭제 — 가리키는 말 검사 · 선택지 질문 재생성 · 관찰 문장 길이 초과 다시 쓰기
    assert "dangling_ref" not in src and 'issues.append("leading_choice")' not in src
    assert 'if why == "length" and kind == "observation":' in inspect.getsource(SR.render_slot)
    # 3. 프롬프트 — 행위자·이미 말한 때와 사람·요약의 주어
    assert "누가 한 일인지를 바꾸지 않는다" in TURN_FORMAT_RULES and "이미 말한 때·사람·일은 다시 묻지 않는다" in TURN_FORMAT_RULES
    assert "그 사람의 이름을 주어로 쓴다" not in inspect.getsource(CR.render_close_summary)      # (P11e-4) 되돌림 — 주어는 언제나 리더님
    ep = {"idx": 1, "leader_turns": 1, "slots": {**{k: {"status": "empty", "quote": ""} for k in ("action", "reaction", "result", "criterion", "reflection")},
                                                "context": {"status": "partial", "quote": "작년 12월에 이기획 평가가"}}}
    card = build_episode_card(instruction="EPISODE_PROBE", chapter="performance_management", ep=ep, bei_turns=1, budget=18)
    assert "이미 말한 때·사람은 다시 묻지 않고, 빠진 것만 묻는다" in card
    # 4. 합쇼체 코치의 여는 문형 — '건데요' 없음 · 말투별 예시 5종
    for i in range(5):
        for p, bad in (("Daniel", r"(요|죠)[.?,]"), ("Jessica", r"(요|죠)[.?,]"), ("Ella", r"(습니다|습니까|입니다)[.?]"), ("Olivia", r"(습니다|습니까|입니다)[.?]")):
            import re as _re
            assert not _re.search(bad, AR._frame_example(p, i)), (p, i, AR._frame_example(p, i))
    assert "건데요" not in AR.OPENER_FRAME_2_FORMAL and "관한 것입니다" in AR.OPENER_FRAME_2_FORMAL
    fixed = R.apply_register("Daniel", "이번 질문은 앞으로 몇 년을 내다보는 판단에 관한 건데요, 최근에 내년 이후를 보고 내리신 결정이 있으셨습니까?", scope="strict")
    assert fixed[0] == "이번 질문은 앞으로 몇 년을 내다보는 판단에 관한 것입니다. 최근에 내년 이후를 보고 내리신 결정이 있으셨습니까?" and fixed[2] == []
    for w in ("사례의 결", "분명하게 들립니다", "분명해졌습니다"):
        assert w in BANNED_STATE_LEAK


# ───────────────────────── P11e (2026-11-12) 사례 없음 경로 · 닫힌 사례 다시 말하기 · 요약 주어 · 받는 문장 길이 ─────────────────────────

def test_p11e_1_decline_after_reframe_and_dragged_case():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import input_anomaly as IA
    from diag_project.services.bei_engine import is_no_case_text
    from diag_project.services.short_input import is_decline_word
    from diag_project.services.turn_checks import mentions_closed_case
    # 재질문 뒤의 거절은 '없다'는 답이다 — 내용 없는 답(다시 묻기)으로 읽지 않는다
    for t in ("없어.", "없어요", "없습니다.", "놉", "딱히", "별로", "글쎄요"):
        assert is_decline_word(t), t
        a = IA.detect(user_text=t, prev_user_text="그런 일은 드물어요.", earlier_user_texts=[], prev_coach_text="요즘 주간 점검 때 순서를 바꿔 본 적이 있었습니까?",
                      prev_instruction="NO_CASE_REFRAME", event_texts=[], pause_pending=False, awaiting_choice=False, definition_reasked=False)
        assert a is None or a.kind != "ack_reask", (t, a)
    assert is_no_case_text("없어.") and is_no_case_text("없습니다")
    assert not is_decline_word("창고에 재고가 없어서 발주를 다시 냈어요.")
    # 재질문이 닫힌 사례를 끌어오면 걸린다 — 상황 인용의 낱말 3개 이상, 또는 '…처럼' 과 함께 2개 이상
    ctx = ["재작년 가을에 물류센터 이전 일정이 석 달 당겨졌다는 통보를 받았을 때였어요"]
    assert mentions_closed_case("물류센터 이전 일정처럼 급하게 바뀐 일을 두고 누군가와 이야기한 적이 있습니까?", ctx)
    assert mentions_closed_case("이전 통보 때처럼 갑자기 정해진 일이 또 있었습니까?", ctx)
    assert mentions_closed_case("요즘 아침 점검 자리에서 순서를 바꿔 보자고 말한 적이 있습니까?", ctx) is None
    assert mentions_closed_case("평소 일정이 밀릴 때 누구와 먼저 상의하십니까?", ctx) is None
    src = inspect.getsource(D._submit_message_phase3a)
    assert '_tm["reframe_drag"] = _drag_q' in src and "(_drag_q or not _rqo_q(_qs_q[-1]))" in src
    # 같은 답: 종류를 합쳐 세고, 두 번째(또는 그 질문이 이미 두 번 나갔으면)에는 사례를 닫는다
    assert '_ac_kind = "repeat" if _anomaly.kind in ("repeat_prev", "repeat_any")' in src and "_q_seen_an >= 2" in src
    assert '_tm["dup_close"] = 1' in src


def test_p11e_2_same_incident_is_not_a_new_case():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services.turn_checks import is_new_fact, same_incident
    closed = {1: "재작년 가을에 물류센터 이전 일정이 석 달 당겨졌다는 통보를 받았어요. 저는 반장 세 명을 먼저 불러 인력 배치표를 다시 짰습니다. "
                 "그 뒤로 출고 지연이 하루도 없었습니다.", "sweep1": "분기마다 협력사 단가표를 직접 다시 봅니다."}
    assert same_incident("아까 말씀드린 그 이전 건에서요, 반장 세 명을 불러 배치표를 다시 짰고 야간조 수당도 제가 올리자고 했습니다.", closed) == 1
    assert same_incident("재작년 가을 물류센터 이전 일정이 석 달 당겨졌을 때 반장 세 명을 먼저 불러 인력 배치표를 다시 짰어요.", closed) == 1
    assert same_incident("지난달에 신규 거래처 반품이 몰려서 검수 인원을 하루 늘렸습니다.", closed) is None
    assert same_incident("그냥 그랬습니다.", closed) is None
    assert is_new_fact("야간조 수당도 제가 올리자고 했습니다", closed[1]) and not is_new_fact("반장 세 명을 먼저 불러 인력 배치표를 다시 짰습니다", closed[1])
    src = inspect.getsource(D._submit_message_phase3a)
    assert '_ep["repeat_of"] = _rep_tag' in src and '_orig_r["addenda"]' in src and '"repeat_case": _tm.get("repeat_case")' in src


def test_p11e_3_4_no_judging_the_answer_and_summary_subject():
    import inspect
    from diag_project.prompts.phase3a.episode_card import TURN_FORMAT_RULES
    from diag_project.services import close_render as CR
    from diag_project.services.turn_checks import receive_ban_reason
    assert "그렇다는 말을 하지 않는다" in TURN_FORMAT_RULES
    for t in ("그 말씀만으로는 그날 모습이 잘 그려지지 않습니다.", "답이 한 줄로만 남아 있는 것이 조금 걸립니다."):
        assert receive_ban_reason(t) == "judges_answer", t
    assert receive_ban_reason("납품 날짜를 사흘 앞당기셨군요.") is None
    out, n = CR.drop_non_leader_subject("상무님은 납품 날짜를 사흘 앞당기라고 하셨습니다. 리더님은 검수 순서를 바꾸셨습니다. 한 대리 님이 야간 검수를 맡았습니다.")
    assert (out, n) == ("리더님은 검수 순서를 바꾸셨습니다.", 2)
    assert CR.drop_non_leader_subject("리더님은 한 대리 님께 검수표를 넘기셨습니다. 그 결과 출고가 하루 빨라졌습니다.")[1] == 0      # 받는 사람으로 나온 이름은 주어가 아니다
    src = inspect.getsource(CR.render_close_summary)
    assert "문장의 주어는 언제나" in src and "drop_non_leader_subject" in src


def test_p11e_5_6_receive_length_first_person_and_words():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import reask_render as RR
    from diag_project.services.output_guard import BANNED_STATE_LEAK
    from diag_project.services.slot_render import has_leader_first_person
    from diag_project.services.turn_checks import RECEIVE_MAX_EOJEOL, default_slot_question
    assert RECEIVE_MAX_EOJEOL == 12
    src = inspect.getsource(D._submit_message_phase3a)
    assert "len(_recv_5.split()) > RECEIVE_MAX_EOJEOL" in src and '_drop_5 = "first_person"' in src
    assert has_leader_first_person("이 일을 저 혼자 끌고 간 것은 아니셨군요.") and has_leader_first_person("제가 먼저 나섰다고 하셨군요.")
    assert not has_leader_first_person("검수 순서를 먼저 바꾸셨군요.")
    for w in ("어떤 한 가지", "한 가지 말씀이나", "떠안으셨"):
        assert w in BANNED_STATE_LEAK
    assert "한 가지" not in RR._KIND_TASK["contentless"]
    # 기본 질문 머리: 낱말을 못 고르면 머리 없이 질문만
    q0 = default_slot_question("action", formal=True, topic_text="")
    assert q0 and "건에서" not in q0 and q0.endswith("?")
    assert "'상태'" not in default_slot_question("action", formal=True, topic_text="그때는 상태가 좀 그랬어요")


# ───────────────────────── P12 (2026-11-13) 11/13 운영 Michael 검토 반영 ─────────────────────────

def test_p12_1_question_stands_alone():
    import inspect
    from diag_project.prompts.phase3a.episode_card import TURN_FORMAT_RULES
    from diag_project.routes import diagnoses as D
    from diag_project.services.output_guard import attach_referent
    from diag_project.services.turn_checks import answer_has_words, default_slot_question, question_overlap
    assert "질문 문장 안에 리더가 직전 답에서 쓴 낱말" in TURN_FORMAT_RULES and "질문 앞 평서문에 기대지 않고" in TURN_FORMAT_RULES
    ans = "지난주 수요일에 물류 3팀 조 반장이 야간 출고표를 혼자 고쳐 왔어요."
    assert question_overlap("그 결정을 다른 분들은 어떻게 받아들였는지도 함께 알려 주세요.", ans) == []          # 가리키는 말뿐 — 겹치는 낱말 없음
    assert question_overlap("조 반장이 고쳐 온 출고표를 보고 뭐라고 하셨어요?", ans)                               # 사람·일이 겹친다
    assert answer_has_words(ans) and not answer_has_words("그냥 그랬습니다.") and not answer_has_words("네.")
    for slot in ("context", "action", "reaction", "result", "criterion", "reflection"):
        q = default_slot_question(slot, formal=False, topic_text="야간 출고표를 혼자 고쳐 왔어요")
        assert "건에서" not in q and "관련해" not in q and "'" not in q, q                                       # 머리 없이 질문만
    assert attach_referent("달라진 점이 있었나요?", ans) == "달라진 점이 있었나요?"                               # ''출고표'와 관련해' 머리 삭제
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_qov_b(" not in src and "q_stand:overlap" not in src and '"q_overlap"' not in src      # (P12b-1) 겹침 검사와 그 다시 쓰기는 삭제 — 지시문만 남는다


def test_p12_2_3_slot_ask_cap_and_turn_reserve():
    from diag_project.prompts.phase3a.episode_card import TURN_FORMAT_RULES, build_episode_card
    from diag_project.services import bei_engine as B
    assert "거슬러 올라가며 되묻지 않는다" in TURN_FORMAT_RULES and "아직 듣지 못한 것" in TURN_FORMAT_RULES
    ep = {"idx": 1, "leader_turns": 2, "slots": {k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}}
    ep["slots"]["context"] = {"status": "filled", "quote": "지난주 수요일 야간 출고 때"}
    assert B.next_slot(ep) == "action"
    ep = B.bump_slot_ask(ep, "action"); ep = B.bump_slot_ask(ep, "action")
    assert B.slot_asks(ep, "action") == 2 and B.next_slot(ep) == "reaction" and B.ask_slot(ep) == "action"       # 두 번 물었으면 다음 것으로
    ep = B.bump_slot_ask(ep, B.next_slot(ep))
    assert B.ask_slot(ep) == "reaction"
    card = build_episode_card(instruction="EPISODE_PROBE", chapter="people_management", ep=ep, bei_turns=3, budget=24)
    assert "이번 턴: '그 말을 들은 사람의 반응'" in card and "리더 턴 2/6" in card
    assert "리더 턴 2/6" in build_episode_card(instruction="EPISODE_PROBE", chapter="organization_management", ep=ep, bei_turns=3, budget=16)
    # 결과를 두 번 물어도 안 나오면 '다시 한다면'으로 넘어간다
    ep2 = dict(ep, slot_asks={"result": 2})
    assert "reflection" in B.unfilled_slots(ep2) and "reflection" not in B.unfilled_slots(ep)
    # 남은 것을 모두 두 번씩 물었으면 닫는다
    ep3 = dict(ep, slot_asks={k: 2 for k in B.SLOT_KEYS})
    assert B.next_slot(ep3) is None and B.episode_done_reason(ep3, {"bei_turns": {"organization_management": 3}}, "organization_management", ["a", "b"]) == "stalled"
    # 예약: 아직 묻지 않은 칸마다 2턴
    assert B.RESERVE_PER_UNASKED == 2 and B.episode_turn_max(9) == 6 and B.episode_turn_max(4) == 6
    subs = ["가", "나", "다", "라"]
    st, e = B.new_episode({}, "organization_management", "가", "k")
    st["bei_turns"] = {"organization_management": 10}                    # 남은 6 = 미질문 3칸 × 2턴
    assert B.reserve_turns(st, "organization_management", subs) == 6
    assert B.episode_done_reason(dict(e, leader_turns=3), st, "organization_management", subs) == "reserve"
    st["bei_turns"] = {"organization_management": 9}
    assert B.episode_done_reason(dict(e, leader_turns=3), st, "organization_management", subs) is None


def test_p12_4_question_endings():
    import inspect
    from diag_project.prompts.phase3a.episode_card import build_episode_card
    from diag_project.routes import diagnoses as D
    from diag_project.services import persona_voice as V
    from diag_project.services.turn_checks import QUESTION_ENDING_MAX, ending_counts, ending_label, request_ending_key, tail_key
    assert QUESTION_ENDING_MAX == 3
    assert request_ending_key("그날 장면을 조금 더 떠올려 주실 수 있을까요?") == request_ending_key("출고표를 고친 순서를 떠올려 주실 수 있을까요?")
    assert request_ending_key("그 뒤 일을 들려주실 수 있을까요?") != request_ending_key("그 뒤 일을 떠올려 주실 수 있을까요?")
    assert request_ending_key("조 반장은 뭐라고 했나요?") is None and request_ending_key("그 뒤로 무엇이 달라졌습니까?") is None      # 바로 묻는 질문은 세지 않는다
    assert ending_label(request_ending_key("천천히 떠올려 주실 수 있을까요?")) == "떠올려 주실 수 있을까요"
    cnt = ending_counts(["하나 떠올려 주실 수 있을까요?", "또 떠올려 주실 수 있을까요?", "그건 왜였나요?", "편하게 들려주세요."])
    assert cnt == {"떠올려주실수있을까요": 2, "들려주세요": 1}
    assert tail_key("최근에 직접 맡기셨던 일, 하나만 들려주세요.") == "들려주세요" and tail_key("요즘 그런 일이 있으세요?") == "일이 있으세요"
    ep = {"idx": 1, "leader_turns": 1, "slots": {k: {"status": "empty", "quote": ""} for k in ("context", "action", "reaction", "result", "criterion", "reflection")}}
    card = build_episode_card(instruction="EPISODE_PROBE", chapter="people_management", ep=ep, bei_turns=2, budget=24, used_endings=["떠올려 주실 수 있을까요"])
    assert "이미 여러 번 쓴 질문 끝맺음: '떠올려 주실 수 있을까요'" in card
    assert "끝맺음" not in build_episode_card(instruction="EPISODE_OPEN", chapter="people_management", ep=ep, bei_turns=2, budget=24, used_endings=["들려주세요"])
    # Michael 사전 질문의 꼬리 5종
    q = "새로 온 직원에게 일을 넘기신 적이 최근에 있으셨어요?"
    outs = [V.voice_question("Michael", q, variant=v) for v in range(V.MICHAEL_TAIL_N)]
    assert len({tail_key(o) for o in outs}) == 5, outs
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_chapter_question_tails()" in src and "_used_end_b = [" in src


def test_p12_5_6_banned_commentary_and_bare_opener():
    import inspect
    from diag_project.prompts.phase3a import layer3_state as L3
    from diag_project.prompts.phase3a.episode_card import TURN_FORMAT_RULES
    from diag_project.routes import diagnoses as D
    from diag_project.services.output_guard import strip_state_leak
    for bad in ("말씀하신 흐름이 잘 보입니다.", "기준이 분명하게 잡혀 있네요.", "그날 일이 구체적으로 보이네요.", "의지가 분명하게 느껴지네요.",
                "그 대목이 눈에 들어왔어요.", "이번에는 그 뒤를 짚어 보려고 해요.", "이제 사례 하나의 마무리로 가 볼게요.", "그것을 기준으로 본 순간이었군요."):
        out, n = strip_state_leak(f"{bad} 조 반장은 그때 뭐라고 했나요?")
        assert n == 1 and out == "조 반장은 그때 뭐라고 했나요?", (bad, out)
    assert "떠오르세요" not in inspect.getsource(L3) and "떠오르는 장면" not in inspect.getsource(L3)          # ALIGN 받기에 흘러든 옛 예시
    assert "앞에서 끝난 다른 이야기를 평서문이나 질문에 끌어오지 않는다" in TURN_FORMAT_RULES
    src = inspect.getsource(D._submit_message_phase3a)
    i = src.index("async def _opener_for(")
    body = src[i: src.index("def ", i + 30)]
    assert 'return fallback_q, "bare"' in body and "render_opener" not in body                                # 여는 문장은 질문만 — LLM 호출 없음


def test_p12_7_register_of_summary_and_noun_list_receive():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services.input_anomaly import is_bare_noun_list, is_contentless_smalltalk
    from diag_project.services.persona_register import apply_register
    out, n, left = apply_register("Michael", "리더님은 야간 출고표를 직접 고치셨습니다. 그 뒤 지연이 줄었습니다. 그 까닭이 궁금합니다.", scope="strict")
    assert n == 3 and left == [] and "습니다" not in out and out.endswith("궁금해요.")
    assert apply_register("Daniel", "리더님은 야간 출고표를 직접 고치셨습니다.", scope="strict")[1] == 0
    assert is_bare_noun_list("물류 3팀 반장 야간 배송") and is_bare_noun_list("인사팀, 채용 담당, 팀원 5명")
    assert not is_bare_noun_list("물류 3팀 반장이고 야간 출고를 맡고 있습니다.") and not is_bare_noun_list("반장")
    assert not is_bare_noun_list("물류 3팀 야간 출고")          # 조사와 같은 글자로 끝나는 낱말('출고')이 있으면 나열로 보지 않는다(LLM 받기로 간다 — 안전한 쪽)
    assert is_contentless_smalltalk("물류 3팀 반장 야간 배송")
    src = inspect.getsource(D._submit_message_phase3a)
    assert '_tm["smalltalk"] = "fixed3"' in src and '("strict" if _polite_zz else "questions")' in src and "_areg_cs(" in src


# ───────────────────────── P12b (2026-11-13) 다시 쓰기 줄이기 · 닫힌 사례를 다시 말한 답 ─────────────────────────

def test_p12b_1_2_fewer_rewrites_and_six_turn_cap():
    import inspect
    from diag_project.prompts.phase3a.episode_card import BEI_GUIDES, build_episode_card
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B
    from diag_project.services.slot_render import repeats_used_shape
    src = inspect.getsource(D._submit_message_phase3a)
    assert 'why="sweep_bridge"' not in src and "slot_render:" not in src                       # 잇는 문장·페르소나 슬롯은 다시 쓰지 않는다
    assert '_tm["slot_tried"] = 1' in src and src.count("rounds=1") >= 2                       # 영역당 1회만 시도
    assert '_only_long_w = bool(_iss) and set(_iss) == {"long_receive"}' in src                # 긴 받기만이면 다시 쓰지 않고 넘친 문장을 지운다
    assert repeats_used_shape("그 판단을 끝까지 밀고 가신 것, 응원해요.", ["먼저 이유를 들으신 그 순서, 응원해요."]) is None      # 끝맺음이 같아도 걸리지 않는다
    card = build_episode_card(instruction="SWEEP_ANCHOR", chapter="people_management", ep=None, bei_turns=9, budget=24, anchor_text="Q?", sweep_seq=2,
                              bridge_material="'분기 계획표'", weak_hint="앞서 들은 이야기에서 이쪽이 살짝 나왔다")
    assert "잇는 문장" not in card and "잇는 문장" not in BEI_GUIDES["SWEEP_ANCHOR"] and "②" in card
    assert B.EPISODE_MAX_LEADER_TURNS == 6 and B.episode_turn_max(4) == 6 and B.episode_turn_max(9) == 6
    ep = {"idx": 1, "leader_turns": 6, "slots": {k: {"status": "filled", "quote": "x"} for k in B.SLOT_KEYS}}
    assert B.episode_done_reason(ep, {"bei_turns": {"organization_management": 6}}, "organization_management", ["a", "b"]) == "slots"      # 다 찼으면 턴 상한보다 먼저
    ep["slots"]["reflection"] = {"status": "empty", "quote": ""}
    assert B.episode_done_reason(ep, {"bei_turns": {"organization_management": 6}}, "organization_management", ["a", "b"]) == "turns"


def test_p12b_3_repeat_answer_asks_once_then_closes_as_repeat():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B
    from diag_project.services import intro_messages as IM
    from diag_project.services.turn_checks import same_incident
    # 같은 프로젝트의 다른 사건은 같은 사건이 아니다 — 앞 이야기를 가리키는 말이 있어도
    proj = ("작년 3월에 본부에서 교육과정 개편을 맡으라는 지시가 왔어요. 강사 두 분이 왜 바꾸냐고 반대해서 따로 불러 이유를 들었고, "
            "한 과정만 두 달 파일럿으로 돌리자고 제안했습니다. 파일럿 만족도가 높게 나와 하반기에 전체 개편으로 넘어갔어요.")
    closed = {1: proj}
    for other in ("아까 말씀드린 교육과정 개편 때 일인데요, 중간에 외부 강사료 예산이 30% 모자랐어요. 그래서 재무팀 정 과장을 찾아가 분기 예산을 앞당겨 쓰는 안을 냈습니다.",
                  "그 개편을 하던 중에 과정마다 교안 양식이 제각각이라 검수가 안 됐어요. 제가 한 장짜리 표준 양식을 만들어 다음 주부터 그것만 받겠다고 공지했습니다.",
                  "같은 개편 프로젝트에서 강의실 예약이 자꾸 겹쳤습니다. 공유 캘린더를 새로 만들고 운영 담당 한 명에게 배정 권한을 넘겼어요.",
                  "앞서 말한 개편 건인데, 이번에는 수강생 설문 문항을 제가 직접 다시 짰고 응답률이 두 배가 됐습니다."):
        assert same_incident(other, closed) is None, other
    assert same_incident("아까 말씀드린 그 개편 일에서요, 강사 두 분을 따로 불러 이유를 들었고 한 과정만 두 달 파일럿으로 돌리자고 제안했습니다.", closed) == 1
    # 상태·원장: repeat 는 사례 없음과 구분해 적고, 그 칸은 다시 묻지 않는다
    subs = ["가", "나", "다"]
    st, ep = B.new_episode({}, "organization_management", "가", "k", kind="sweep")
    st = B.close_episode(st, "organization_management", ep, "repeat", [], subs)
    st = B.mark_repeat(st, "organization_management", "가")
    assert st["repeat_subs"]["organization_management"] == ["가"] and "가" not in (st.get("no_case_subs") or {}).get("organization_management", [])
    assert "가" not in B.uncovered(st, "organization_management", subs) and "가" not in B.unasked(st, "organization_management", subs)
    assert B.coverage_summary(st, "organization_management", subs)["repeat"] == ["가"] and B.sweep_count(st, "organization_management") == 0
    for pn in ("Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"):
        assert IM.persona_line(pn, "repeat_heard").endswith(".") and len(IM.persona_line(pn, "repeat_heard")) <= 16
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_repeat_ask_now = True" in src and 'await _close_and_map(_ep, "repeat")' in src and "'repeat_heard')} 그 일 말고, " in src
    assert '"sub": _ep.get("opener_sub"), "quote": _s_r[:200]' in src                         # 그 답의 문장을 전부, 묻던 칸을 붙여 원래 사례에 남긴다
    assert 'if status not in ("no_case", "repeat") and _bei.filled_slots(ep):' in src


def test_p12b_4_wording():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B
    from diag_project.services import close_render as CR
    from diag_project.services.output_guard import strip_state_leak
    from diag_project.services.turn_checks import default_slot_question
    for bad in ("상대인 조 반장은 그 말을 어떻게 받았나요?", "상대 쪽 반응은 어땠나요?", "버리신 다른 선택지가 있었다면 그것도 알려 주세요.", "그 결과가 분명하게 남았네요.",
                "사람 단위로 보신다는 게 먼저 느껴지네요.", "걱정했다는 말씀이 기억에 남네요.", "그 맥락과 이어져 들려요.", "그 대목이 이번 장면과 이어지네요.", "잇는 문장 하나만 쓰겠어요."):
        out, n = strip_state_leak(f"출고표는 직접 고치셨군요. {bad}")
        assert n == 1 and out == "출고표는 직접 고치셨군요.", (bad, out)
    assert "상대" not in B.SLOT_LABELS["reaction"] + B.SLOT_HINTS["reaction"] and "선택지" not in B.SLOT_HINTS["criterion"]
    assert "상대" not in default_slot_question("reaction", formal=True) + default_slot_question("reaction", formal=False)
    assert "[리더가 한 일] + [리더가 말한 수치나 달라진 상태]" in inspect.getsource(CR.render_close_summary)      # (P12c-5) 문장 틀을 좁힘
    src = inspect.getsource(D._submit_message_phase3a)
    assert r"들어\\s?보고" in src or "들어\\s?보고" in src or "들어" in src[src.index("(lb1) 범위 문장 자리에 예고 문장"):][:900]
    assert "이번에는|이번엔|다음은" in src


# ───────────────────────── P12c (2026-11-14) 다시 묻기 대상 · 사례 첫 꼬리 질문 · 슬롯 길이 · 금지 꼴 ─────────────────────────

def test_p12c_reask_keeps_what_is_asked_and_first_probe_hint():
    import inspect
    from diag_project.prompts.phase3a.episode_card import BEI_GUIDES, TURN_FORMAT_RULES
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B
    from diag_project.services import reask_render as RR
    task = RR._KIND_TASK["contentless"]
    assert "묻는 것을 바꾸지 않습니다" in task and "이미 답한 것은 다시 묻지 않습니다" in task and "그 자리에서" not in task and "무슨 말을 했는지" not in task
    assert "방금 말한 일" in B.SLOT_HINTS["action"] and "그때 리더님이 직접" not in B.SLOT_HINTS["action"] and "상대" not in B.SLOT_HINTS["context"]
    assert "한 턴에 묻는 것은 하나다" in TURN_FORMAT_RULES and "선택지" not in TURN_FORMAT_RULES + "".join(BEI_GUIDES.values())
    src = inspect.getsource(D._submit_message_phase3a)
    assert '_tm["reask_prev"] = {"q": _orig_rq[:160], "is_last":' in src and '"reask_prev": _tm.get("reask_prev")' in src
    assert "그날 그 자리에서" not in src


def test_p12c_slot_length_summary_frame_and_banned_shapes():
    from diag_project.services import slot_render as SR
    from diag_project.services.output_guard import strip_state_leak
    lead = ["야간 출고표를 제가 직접 다시 짰고 조 반장에게는 검수만 맡겼어요.", "그 뒤로 지연이 사흘에서 하루로 줄었습니다."]
    long_cheer = "야간 출고표를 직접 다시 짜시고 조 반장에게는 검수만 맡기신 뒤 지연이 사흘에서 하루로 줄 때까지 지켜보신 그 선택, 응원해요."
    assert len(long_cheer.split()) > 12 and SR.slot_sentence_ok("cheer", long_cheer, lead, persona_name="Michael") == (False, "length")
    assert SR.slot_sentence_ok("cheer", "야간 출고표를 직접 다시 짜신 그 선택, 응원해요.", lead, persona_name="Michael")[1] != "length"
    assert SR.SLOT_STATEMENT_MAX_EOJEOL == 12
    for bad in ("정의 질문은 곧 드릴게요.", "질문은 바로 이어서 드릴게요.", "그 사람이 말하거나 움직인 장면을 들려주세요.", "조 반장은 그 말을 어떻게 받아들였군요."):
        out, n = strip_state_leak(f"출고표는 직접 고치셨군요. {bad}")
        assert n == 1 and out == "출고표는 직접 고치셨군요.", (bad, out)
    for ok in ("어떻게 하면 좋을지 오래 고민하셨군요.", "왜 늦는지부터 물으셨군요.", "조 반장을 먼저 부르셨군요."):
        assert strip_state_leak(ok)[1] == 0, ok
