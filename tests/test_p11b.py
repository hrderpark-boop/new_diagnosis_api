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
    assert "_ar_w3(" not in src      # (P12e-5) 8-w3(대상 붙이기)는 삭제
    assert 'not _reask_kind and _fp_final is None and instruction_used != "NO_CASE_REFRAME"):' in src                         # 8-w4 는 사례 없음 재질문 턴을 건너뛴다
    assert "_qrcv_w0" not in src and "_qrcv_5" not in src                                              # (P11c-1) 금지 꼴·되풀이 문장은 삭제만 — 구절 인용 대체 없음


# ── P11c 규칙 줄이기 ────────────────────────────────────────────────────────
def test_p11c_receive_optional_and_one_question():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import receive_check as RC
    from diag_project.services import turn_checks as T
    src = inspect.getsource(D._submit_message_phase3a)
    # 1. 탐침 턴은 받는 문장 필수 검사가 없다 · 금지 꼴·되풀이는 삭제만 · 구절 인용 대체는 닫고 넘어가는 턴에서 세션 2회까지
    assert 'issues.append("no_receive")' not in src and 'issues.append("no_quote")' not in src and RC.QUOTE_RECEIVE_SESSION_MAX == 2      # (P13c-2) 받는 문장 검사는 어디에도 없다
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
    assert "반쯤: 상황·시점" in card and "때·사람(언제였는지, 누가 함께 있었는지)만 따로 묻는 질문은 하지 않는다" in card      # (P13-2) 때·사람은 따로 묻지 않는다
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
    assert "무엇에 대해(리더가 말한 일·사람)와 무엇을 묻는지" in TURN_FORMAT_RULES and "질문 앞 평서문에 기대지 않는다" in TURN_FORMAT_RULES      # (P13-2)
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
    assert B.slot_asks(ep, "action") == 2 and B.next_slot(ep) == "criterion" and B.ask_slot(ep) == "action"       # 두 번 물었으면 다음 것으로(P13-1: 행동 다음은 기준)
    ep = B.bump_slot_ask(ep, B.next_slot(ep))
    assert B.ask_slot(ep) == "criterion"
    card = build_episode_card(instruction="EPISODE_PROBE", chapter="people_management", ep=ep, bei_turns=3, budget=24)
    assert "이번 질문: '판단 기준' 하나" in card and "리더 턴 2/6" in card
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
    from diag_project.services import turn_checks as TC
    from diag_project.services.turn_checks import ending_counts, ending_label, request_ending_key, tail_key
    assert not hasattr(TC, "QUESTION_ENDING_MAX")      # (P13d-1) 같은 끝맺음 4회째 다시 쓰기는 삭제 — 세기와 프롬프트 전달만 남는다
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
    assert '_do_map = status not in ("no_case", "repeat") and bool(_bei.filled_slots(ep))' in src


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
    assert "리더가 한 일에서 문장을 맺는다" in inspect.getsource(CR.render_close_summary)      # (P12c-5 → P12e-6) 결과·인과를 쓰지 않는다
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
    assert "한 턴에 묻는 것도 하나다" in TURN_FORMAT_RULES and "한 턴에 질문 문장은 하나다" in TURN_FORMAT_RULES and "선택지" not in TURN_FORMAT_RULES + "".join(BEI_GUIDES.values())
    src = inspect.getsource(D._submit_message_phase3a)
    assert '_tm["reask_prev"] = {"q": _orig_rq[:160], "is_last":' in src and '"reask_prev": _tm.get("reask_prev")' in src
    assert "그날 그 자리에서" not in src


def test_p12c_slot_length_summary_frame_and_banned_shapes():
    from diag_project.services import slot_render as SR
    from diag_project.services.output_guard import strip_state_leak
    lead = ["야간 출고표를 제가 직접 다시 짰고 조 반장에게는 검수만 맡겼어요.", "그 뒤로 지연이 사흘에서 하루로 줄었습니다."]
    long_cheer = "야간 출고표를 직접 다시 짜시고 조 반장에게는 검수만 맡기신 뒤 지연이 사흘에서 하루로 줄 때까지 지켜보신 그 선택, 응원해요."
    assert len(long_cheer.split()) > 16 and SR.slot_sentence_ok("cheer", long_cheer, lead, persona_name="Michael") == (False, "length")
    assert SR.slot_sentence_ok("cheer", "야간 출고표를 직접 다시 짜신 그 선택, 응원해요.", lead, persona_name="Michael")[1] != "length"
    assert SR.SLOT_STATEMENT_MAX_EOJEOL == 16      # (P12d-4) 12 → 16
    for bad in ("정의 질문은 곧 드릴게요.", "질문은 바로 이어서 드릴게요.", "그 사람이 말하거나 움직인 장면을 들려주세요.", "조 반장은 그 말을 어떻게 받아들였군요."):
        out, n = strip_state_leak(f"출고표는 직접 고치셨군요. {bad}")
        assert n == 1 and out == "출고표는 직접 고치셨군요.", (bad, out)
    for ok in ("어떻게 하면 좋을지 오래 고민하셨군요.", "왜 늦는지부터 물으셨군요.", "조 반장을 먼저 부르셨군요."):
        assert strip_state_leak(ok)[1] == 0, ok


# ───────────────────────── P12d (2026-11-14) 영역 시작 턴 조립 · 고정 받기 · 낱말 ─────────────────────────

def test_p12d_1_chapter_start_turn_is_assembled_without_llm():
    import inspect
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK as CF
    from diag_project.routes import diagnoses as D
    from diag_project.services import align_render as AL
    from diag_project.services import intro_messages as IM
    from diag_project.services.persona_register import apply_register, register_violations
    src = inspect.getsource(D._submit_message_phase3a)
    i = src.index("(2026-11-14 P12d-1) 둘째 이후 영역의 시작 턴(COMPETENCY_ASK)")
    blk = src[i: i + 1800]
    assert 'instruction_used == "COMPETENCY_ASK"' in blk and "system_override_text = f\"{_scope_ca} {_dq_ca(" in blk and '_tm["scope_fixed"] = 1' in blk
    chs = [k for k in CF if k != "supplementary"]
    for pn in ("Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"):
        for ch in chs:
            scope = apply_register(pn, IM.chapter_scope_line(ch, pn), scope="strict")[0]
            assert scope and not scope.endswith("?") and register_violations(pn, scope, scope="strict") == [], (pn, ch, scope)
            assert scope.endswith("짚어보겠습니다.") == (IM.line_register(pn) == "formal"), (pn, scope)      # Lucas 도 합쇼체 판
        assert len(set(IM.ALIGN_FIXED_RECEIVE[IM.persona_key(pn)])) == 3
    # ALIGN — 다시 쓰지 않는다. 받기가 비면 고정 받기
    assert 'why="align"' not in src and 'why="align_quote"' not in src and "_align_ctx[\"fixed_receive\"] = _afr_al(" in src
    out = AL.render_align(llm_text="", chapter="performance_management", sub_names=["가", "나"], persona_name="Michael", anchor="최근에 그런 일이 있으셨어요?",
                          user_text="목표를 같이 정하고 끝까지 가게 하는 일이요.", variant=1, fixed_receive=IM.align_fixed_receive("Michael", 1))
    assert out.startswith("그런 일로 보고 계시네요.") and out.rstrip().endswith("최근에 그런 일이 있으셨어요?")
    out2 = AL.render_align(llm_text="목표를 같이 정한다고 보시는군요.", chapter="performance_management", sub_names=["가", "나"], persona_name="Michael",
                           anchor="최근에 그런 일이 있으셨어요?", user_text="목표를 같이 정하고 끝까지 가게 하는 일이요.", variant=1,
                           fixed_receive=IM.align_fixed_receive("Michael", 1))
    assert out2.startswith("목표를 같이 정한다고 보시는군요.")          # LLM 받기가 살아 있으면 그대로


def test_p12d_2_3_4_rapport_receive_pool_and_wording():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B
    from diag_project.services import intro_messages as IM
    from diag_project.services import slot_render as SR
    from diag_project.services.output_guard import attach_referent
    for pn in ("Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"):
        a = IM.rapport_fixed_receive(pn, "", start=0)
        b = IM.rapport_fixed_receive(pn, f"{a} 오늘은 어떠셨어요?", start=1)
        c = IM.rapport_fixed_receive(pn, f"{b} 어떤 일을 맡고 계세요?", start=1)
        assert a != b and b != c, (pn, a, b, c)                       # 직전 턴에 쓴 것은 다시 쓰지 않는다
        assert IM.role_fixed_receive(pn) not in (a, b, c)
    assert attach_referent("반응은 어땠나요?", "그날 바로 보고했어요.") == "반응은 어땠나요?"
    assert "그 사람" not in B.SLOT_HINTS["reaction"] and "하지 않기로" not in B.SLOT_HINTS["criterion"] and B.SLOT_LABELS["reaction"] == "반응"
    assert SR.SLOT_STATEMENT_MAX_EOJEOL == 16
    src = inspect.getsource(D._submit_message_phase3a)
    assert 'str(_tm.get("closed") or "").endswith(":repeat")) and len(_recv_5.split()) > RECEIVE_MAX_EOJEOL' in src
    assert '_tm["case_word_cut"] = 1' in src and "_rfr1(" in src and "_rfr2(" in src and "_rfr3(" in src


# ───────────────────────── P12e (2026-11-14) 가장자리 경로 정리 ─────────────────────────

def test_p12e_1_2_no_hypothetical_questions_and_reason_slot_scope():
    from diag_project.prompts.phase3a.episode_card import TURN_FORMAT_RULES
    from diag_project.services import slot_render as SR
    from diag_project.services.intro_messages import SLOT_KINDS
    assert "일어나지 않은 일을 가정해서 묻지 않는다" in TURN_FORMAT_RULES and "다시 한다면" in TURN_FORMAT_RULES
    assert "하지 못해 아쉬워한 일은 리더가 하지 않은 일이다" in TURN_FORMAT_RULES
    assert "리더가 한 일로 단정해 높임말로 옮기지 않는다" in TURN_FORMAT_RULES
    assert "counterfactual" not in sum((list(v) for v in SLOT_KINDS.values()), [])
    spec = SR._SPEC["reason"] if isinstance(SR._SPEC["reason"], str) else " ".join(SR._SPEC["reason"])
    assert "리더 본인이" in spec and "다른 사람이 한 일의 이유는 묻지 않는다" in spec and "'없음'" in spec


def test_p12e_3_4_reframe_is_assembled_and_same_scene_is_judged_by_slot_judge():
    import asyncio
    import inspect
    from diag_project.llm_schemas import slot_judge_schema
    from diag_project.routes import diagnoses as D
    from diag_project.services import slot_judge as SJ
    from diag_project.services.turn_checks import incident_candidates
    closed = {1: "지난봄 창고 이전 때 반장 세 명을 먼저 불러 배치표를 다시 짰습니다. 그 뒤 출고 지연이 없었습니다.",
              2: "가을 재고 실사에서 수량이 맞지 않아 전산 담당과 이틀 동안 원장을 대조했습니다."}
    assert incident_candidates("창고 이전 때 반장 세 명을 불러 배치표를 다시 짰고 야간조도 따로 불렀습니다.", closed)[0] == 1
    assert incident_candidates("올여름 신규 거래처와 단가 협상을 제가 직접 했습니다.", closed) == []
    assert "same_as" in slot_judge_schema(with_same=True)["properties"] and "same_as" not in slot_judge_schema()["properties"]

    class _LLM:
        def __init__(self, out):
            self.out, self.prompt, self.schema = out, "", None

        async def _generate_with_retry(self, **kw):
            self.prompt, self.schema = kw.get("prompt") or "", kw.get("json_schema")
            return self.out
    slots = {k: {"status": "empty", "quote": ""} for k in ("context", "action", "reaction", "result", "criterion", "reflection")}
    import json as _json
    import os as _os
    _stub = _os.environ.pop("FM_LLM_STUB", None)
    try:
        tr = [("model", "최근에 일정이 밀렸을 때 직접 나서신 일이 있었습니까?"), ("user", "아까 말씀드린 창고 이전 때 반장 세 명을 불러 배치표를 다시 짰습니다.")]
        llm = _LLM(_json.dumps({"slots": slots, "no_case": False, "switched_case": False, "incident": True, "same_as": "(1)"}, ensure_ascii=False))
        out = asyncio.run(SJ.judge_slots(llm, transcript=tr, prev_slots=None, closed_cases={"1": closed[1]}))
        assert out["same_as"] == "1" and "[앞에서 이미 들은 이야기]" in llm.prompt and "same_as" in llm.schema["properties"]
        llm2 = _LLM(_json.dumps({"slots": slots, "no_case": False, "switched_case": False, "incident": True, "same_as": "7"}, ensure_ascii=False))
        assert asyncio.run(SJ.judge_slots(llm2, transcript=tr, prev_slots=None, closed_cases={"1": closed[1]}))["same_as"] is None      # 후보에 없는 표지는 버린다
        llm3 = _LLM(_json.dumps({"slots": slots, "no_case": False, "switched_case": False, "incident": True}, ensure_ascii=False))
        out3 = asyncio.run(SJ.judge_slots(llm3, transcript=tr, prev_slots=None))
        assert out3["same_as"] is None and "앞에서 이미 들은 이야기" not in llm3.prompt and "same_as" not in llm3.schema["properties"]   # 후보가 없으면 종전과 같은 호출
    finally:
        if _stub is not None:
            _os.environ["FM_LLM_STUB"] = _stub
    src = inspect.getsource(D._submit_message_phase3a)
    assert "closed_cases=(_cands_r or None)" in src and '_sa_r = _jd.get("same_as")' in src and '"same_judge": _tm.get("same_judge")' in src
    assert "def _reframe_question(sub" in src and '_anomaly_override_text = _rq_fix; _tm["reframe_fixed"] = 1' in src
    assert "_alt_rp = _reframe_question(_ep.get(\"opener_sub\"))" in src


def test_p12e_5_7_attach_repair_removed_and_first_chapter_assembled_on_consent():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services.input_anomaly import is_consent
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_ar_w3(" not in src and "attach_referent as" not in src
    i = src.index("(2026-11-14 P12e-7) 첫 영역 시작 턴(DIAGNOSIS_CONFIRM)")
    blk = src[i: i + 1600]
    assert "_is_consent_dc(request.content)" in blk and "system_override_text = f\"{_fcb_dc(_cn_dc, _pn_dc)} {_scope_dc} {_dq_dc(" in blk
    assert is_consent("ㅇㅋ") and is_consent("네, 시작하겠습니다.") and not is_consent("얼마나 걸려요?") and not is_consent("잠깐만요")


# ───────────────────────── P13 (2026-11-15) 11/14 운영 Lucas 검토 반영 — 측정 축 복구 ─────────────────────────

def test_p13_1_first_probe_is_leader_action_and_ask_order():
    from diag_project.prompts.phase3a.episode_card import TURN_FORMAT_RULES, build_episode_card
    from diag_project.services import bei_engine as B
    from diag_project.services import slot_judge as SJ
    assert B.ASK_ORDER == ("action", "criterion", "result", "reaction", "reflection") and B.slot_ask_max("reaction") == 1 and B.slot_ask_max("action") == 2
    ep = {"idx": 1, "leader_turns": 1, "slots": {k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}}
    ep["slots"]["context"] = {"status": "filled", "quote": "지난달 야간 출고 때"}
    ep["slots"]["action"] = {"status": "filled", "quote": "검수 순서를 바꾸자고 제안했습니다"}       # 여는 답의 한 줄 요약으로 이미 '채움'
    assert B.first_probe_pending(ep) and B.next_slot(ep) == "action"                                   # 그래도 첫 꼬리 질문은 리더 행동
    ep = B.bump_slot_ask(ep, B.next_slot(ep))
    assert ep["ask_first"] is True and B.ask_slot(ep) == "action"
    card = build_episode_card(instruction="EPISODE_PROBE", chapter="work_management", ep=ep, bei_turns=2, budget=18)
    from diag_project.prompts.phase3a.episode_card import FIRST_PROBE_HEADER
    assert card == FIRST_PROBE_HEADER      # (P13e) 전용 호출이 질문을 만든다 — 카드는 머리 한 줄
    assert "들음:" not in card and "아직:" not in card and "때와 함께 있던 사람" not in card           # (P13b-1) 전용 지시 — 들은 것·남은 것 목록을 주지 않는다
    assert B.next_slot(ep) == "criterion"                                                              # 그 뒤로는 기준 → 결과 → 반응
    ep = B.bump_slot_ask(ep, "criterion"); ep["slots"]["criterion"] = {"status": "filled", "quote": "x"}
    ep = B.bump_slot_ask(ep, "result"); ep["slots"]["result"] = {"status": "filled", "quote": "y"}
    assert B.next_slot(ep) == "reaction"
    ep = B.bump_slot_ask(ep, "reaction")
    assert B.next_slot(ep) == "reflection"                                                             # 반응은 사례당 1회 — 안 나와도 다음으로
    ep0 = {"idx": 1, "leader_turns": 1, "slots": {k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}}
    ep0 = B.bump_slot_ask(ep0, B.next_slot(ep0))
    assert "때와 함께 있던 사람" not in build_episode_card(instruction="EPISODE_PROBE", chapter="work_management", ep=ep0, bei_turns=1, budget=18)
    ep0 = B.bump_slot_ask(ep0, B.next_slot(ep0))                                                       # (P13b-1) 상황은 둘째 꼬리 질문에 한 번만 곁들인다
    assert ep0["ask_first"] is False and "때와 함께 있던 사람이 아직 나오지 않았다 — 이 질문에 곁들여 한 번만 묻는다" in build_episode_card(
        instruction="EPISODE_PROBE", chapter="work_management", ep=ep0, bei_turns=2, budget=18)
    # 사례 완성 = 묻는 다섯 가지가 차고 상황은 채움 또는 반쯤
    full = {"slots": {**{k: {"status": "filled", "quote": "q"} for k in B.ASK_ORDER}, "context": {"status": "partial", "quote": "지난달"}}}
    assert B.slots_complete(full) and not B.slots_complete({"slots": {**full["slots"], "context": {"status": "empty", "quote": ""}}})
    # 칸 판정 기준
    assert "한 줄 요약" in SJ._SLOT_RULES and "팀 밖 사람의 반응은 reaction 이 아니라 result" in SJ._SLOT_RULES
    assert "이끌거나 함께 일하는 사람이 아닌 사람" in TURN_FORMAT_RULES and "무엇에 대해(리더가 말한 일·사람)와 무엇을 묻는지" in TURN_FORMAT_RULES


def test_p13_3_card_is_data_and_announce_is_not_a_question():
    import inspect
    from diag_project.prompts.phase3a.episode_card import build_episode_card
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B
    from diag_project.services.turn_checks import is_announce_ask, request_to_question
    ep = {"idx": 2, "leader_turns": 2, "slot_asks": {"action": 1}, "ask_slot": "criterion",
          "slots": {**{k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}, "action": {"status": "filled", "quote": "검수표를 제가 다시 짰습니다"}}}
    card = build_episode_card(instruction="EPISODE_PROBE", chapter="work_management", ep=ep, bei_turns=4, budget=18,
                              prev_episodes=[{"idx": 1, "summary": "창고 이전 때 배치표를 다시 짬"}])
    assert "코치만 보는 자료" in card and "리더에게 말하지 않는다" in card and "들음: " in card and "아직: " in card
    assert "채워진 것" not in card and "아직 없는 것" not in card and "지난 사례" not in card and "창고 이전" not in card      # 지난 사례 목록은 넘기지 않는다
    assert is_announce_ask("이제 판단 기준을 묻겠습니다.") and is_announce_ask("그 부분을 짚겠습니다.") and not is_announce_ask("그때 무엇을 하셨습니까?")
    # (P13 중간 판정 5) '…인지/는지 묻겠습니다·여쭙겠습니다·짚겠습니다' 도 질문으로 세지 않는다 — 묻는 꼴로 바꾸지 않고, 질문 보장 단계가 지우고 기본 질문을 붙인다
    assert is_announce_ask("그때 정하신 기준이 무엇이었는지 여쭙겠습니다.") and is_announce_ask("어느 쪽이 먼저였는지 묻겠습니다.")
    assert request_to_question("그때 정하신 기준이 무엇이었는지 여쭙겠습니다.", formal=True) is None
    assert request_to_question("그때 정하신 기준이 무엇이었는지 여쭙고 싶습니다.", formal=True) == "그때 정하신 기준이 무엇이었는지 말씀해 주시겠습니까?"
    src = inspect.getsource(D._submit_message_phase3a)
    assert "is_question_sentence(x) and not _iaa_q(x)" in src and '_tm["announce_ask_cut"] = len(_ann_q)' in src
    assert "리더가 앞에서 이미 들은 이야기를 다시 말했다" not in src                                      # 같은 장면 판정 결과는 생성 프롬프트에 넘기지 않는다


def test_p13_4_broken_shapes_and_leftovers():
    from diag_project.services.output_guard import delete_broken_statements, is_broken_sentence, strip_state_leak
    for bad in ("검수 순서를 바꾼 기준은 무엇이었군요.", "그 방식은 어떤 것이었네요.", "그게 언제였군요.", "새 순서를 본 반장들은 어땠군요.", "그날 현장 분위기는 어떠셨네요."):
        out, n = strip_state_leak(f"{bad} 그 뒤에는 무엇을 하셨습니까?")
        assert n == 1 and out == "그 뒤에는 무엇을 하셨습니까?", (bad, out)
    for ok in ("누구보다 먼저 나서셨군요.", "어떤 일이든 직접 챙기셨군요.", "왜 늦는지부터 물으셨군요."):
        assert strip_state_leak(ok)[1] == 0, ok
    assert strip_state_leak("그 방식은 어떤 것이었네요.") == ("", 1)                                      # 구절만 지우고 조각을 남기지 않는다
    assert is_broken_sentence("그 자리에 누가 있었는지도 함께요.") and is_broken_sentence("새 순서 같은 선택지요.")
    assert not is_broken_sentence("그렇게 하셨지요.") and not is_broken_sentence("검수표를 먼저 보여 주셨군요.")
    # 흉터 삭제 단계가 조각을 지운다(질문·온전한 문장은 그대로)
    assert delete_broken_statements("그 자리에 누가 있었는지도 함께요. 검수표는 누가 먼저 보셨습니까?") == ("검수표는 누가 먼저 보셨습니까?", 1)


def test_p13_6_7_persona_question_scope_and_align_receive_shape():
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import slot_render as SR
    lead = ["검수 순서를 제가 바꿨고 조 반장에게 야간 검수를 맡겼습니다."]
    assert SR.slot_sentence_ok("reason", "검수 순서를 바꾸고 예전 순서를 버리신 이유, 한 줄로 하면 무엇입니까?", lead, persona_name="Lucas") == (False, "garbled_choice")
    for kind in ("reason", "criterion"):
        desc, example = SR._SPEC[kind][0], SR._SPEC[kind][-1]
        assert "리더가 직접 말한 것일 때만" in desc and "대신" not in example and "말고" not in example, kind      # 예시에 견줄 대안을 넣지 않는다
    src = inspect.getsource(D._submit_message_phase3a)
    # (P13b-4) ALIGN 받기는 LLM 을 부르지 않는다 — 고정 받기만(모양 검사는 대상이 없어져 삭제)
    assert '_tm["align_fixed"] = 1' in src and "_recv_sents_al" not in src and 'llm_output = {"reply": ""}' in src


def test_p13_mid_summary_profile_and_fixed_opening():
    """(2026-11-15 P13 중간 판정 1) 요약형 팀장 프로필 — 여는 답은 프로필 문장 그대로(LLM 없음), 조직관리·사람관리 칸마다 사례 하나."""
    import asyncio
    import json
    from pathlib import Path
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    from tools.sim_leader import Leader, _load_profile
    path = Path(__file__).resolve().parents[1] / "tools/sim_profiles/summary_team_lead.json"
    prof = _load_profile(str(path))
    assert prof["name"].startswith("요약형 팀장") and not prof["no_case_subs"] and prof["short_every"] >= 100
    for ch in ("organization_management", "people_management"):
        subs = [v["name"] for v in COMPETENCY_FRAMEWORK[ch]["indicators"].values()]
        have = [s for e in prof["episodes"] if e["chapter"] == ch for s in e["subs"]]
        assert sorted(have) == sorted(subs), (ch, have)                     # 칸마다 사례 하나 — 여는 질문과 여는 답이 어긋나지 않게
    for e in prof["episodes"]:
        assert all(e.get(k) for k in ("opening", "context", "action", "reaction", "result", "criterion", "reflection")), e["id"]
        assert e["opening"].startswith("네, ")
        assert "선임" not in json.dumps(e, ensure_ascii=False)             # 이름을 말하지 않는다('한 팀원', '해당 팀원')
    lead = Leader(prof, stub=True, provider="claude")
    out = asyncio.run(lead.answer("새 방법을 시도하신 적이 있습니까?", chapter="organization_management", instr="EPISODE_OPEN",
                                  target_sub="혁신적 사고", bei_state=None))
    s2 = next(e for e in prof["episodes"] if e["id"] == "S2")
    assert out == s2["opening"] and lead.current["id"] == "S2"
    out2 = asyncio.run(lead.answer("그때 직접 무엇을 하셨습니까?", chapter="organization_management", instr="EPISODE_PROBE",
                                   target_sub="혁신적 사고", bei_state=None))
    assert out2 == s2["action"]                                             # 꼬리 질문에는 묻는 칸의 재료로 답한다


def test_p13_mid_two_questions_pass_and_announce_tail():
    """(P13 중간 판정 3·5) 질문이 둘이면 그대로 내보낸다 · '…는지 묻겠습니다' 꼴은 질문으로 세지 않는다 · 붙여 쓴 '어땠군요' 금지 꼴."""
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services.output_guard import strip_state_leak
    from diag_project.services.persona_register import register_hint
    from diag_project.services.turn_checks import is_announce_ask
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_trim_two" not in src and '"first_q_kept": _tm.get("first_q_kept")' in src          # (P13b-2) 질문 문장이 둘 이상이면 첫 질문 문장만
    for s in ("그 배치를 누가 정했는지 묻겠습니다.", "언제부터였는지 여쭙겠습니다.", "무엇이 걸렸는지 짚겠습니다."):
        assert is_announce_ask(s), s
    for s in ("그 배치는 누가 정했습니까?", "언제부터였나요?", "무엇이 걸렸는지 말씀해 주시겠어요?"):
        assert not is_announce_ask(s), s
    assert strip_state_leak("출고 담당은 어땠군요. 그 뒤에 무엇을 바꾸셨습니까?") == ("그 뒤에 무엇을 바꾸셨습니까?", 1)
    assert strip_state_leak("어떻게 나눌지 오래 고민하셨군요.")[1] == 0
    assert "질문 문장은 줄이지 않는다" in register_hint("Lucas") and "짧은 단문" not in register_hint("Lucas")
    assert "repeat_notice_line as _rnl_an" in src and "duplicate_answer_line" not in src       # (P13-5) 같은 답 안내 = 짧은 안내 + 방금 한 질문


def test_p13b_first_probe_turn_has_its_own_instruction():
    """(2026-11-15 P13b-1) 사례의 첫 꼬리 질문 턴은 전용 지시 — 묻는 것은 리더가 직접 한 말·조치 하나, 까닭·결과·다른 사람의 말은 이 턴에 묻지 않는다."""
    import inspect
    from diag_project.prompts.phase3a import episode_card as EC
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B
    ep = {"idx": 1, "leader_turns": 1, "slots": {k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}}
    ep["slots"]["action"] = {"status": "filled", "quote": "출고 순서를 바꾸자고 했습니다"}
    ep = B.bump_slot_ask(ep, B.next_slot(ep))
    card = EC.build_episode_card(instruction="EPISODE_PROBE", chapter="work_management", ep=ep, bei_turns=2, budget=18, used_endings=["말씀해 주시겠습니까"])
    # (P13d-2 → P13e) 첫 꼬리 질문은 전용 호출이 만든다 — 본 호출용 전용 카드·가이드·형식 규칙은 삭제, 카드는 머리 한 줄뿐
    assert card == EC.FIRST_PROBE_HEADER
    for gone in ("FIRST_PROBE_GUIDE", "first_probe_format_rules", "_first_probe_lines", "_FIRST_RULE_WHAT"):
        assert not hasattr(EC, gone), gone
    # 둘째 꼬리 질문부터는 종전 카드·규칙
    ep2 = B.bump_slot_ask(ep, B.next_slot(ep))
    card2 = EC.build_episode_card(instruction="EPISODE_PROBE", chapter="work_management", ep=ep2, bei_turns=3, budget=18)
    txt2 = EC.bei_turn_text({"instruction_for_this_turn": "EPISODE_PROBE", "bei_card": card2, "coach_persona": {"name": "Daniel"}})
    assert not card2.startswith(EC.FIRST_PROBE_HEADER) and "들음:" in card2 and "다음 질문은 아직 듣지 못한 것(" in txt2
    # 꼬리 질문이 하나뿐인 훑는 질문도 같은 지시
    card3 = EC.build_episode_card(instruction="SWEEP_FOLLOWUP", chapter="work_management", ep=ep, bei_turns=9, budget=18)
    txt3 = EC.bei_turn_text({"instruction_for_this_turn": "SWEEP_FOLLOWUP", "bei_card": card3, "coach_persona": {"name": "Daniel"}})
    assert card3 == EC.FIRST_PROBE_HEADER and txt3
    # 기준 칸 지시문 — 출력에 옮겨지던 낱말을 뺐다
    assert "판단의 근거" not in B.SLOT_HINTS["criterion"] and "리더가 먼저 말했을 때만" in B.SLOT_HINTS["criterion"]
    # 떠오르지 않는다·옮기기 어렵다 → 방금 향한 칸은 더 묻지 않는다
    assert B.is_no_recall_text("그 부분은 따로 기억나는 게 없습니다.") and B.is_no_recall_text("그대로 옮기기는 어렵습니다.") and not B.is_no_recall_text("제가 먼저 물었습니다.")
    e = {"slots": {k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}, "slot_asks": {"action": 1}, "ask_slot": "action"}
    e = B.exhaust_slot(e, "action")
    assert e["slot_asks"]["action"] == B.slot_ask_max("action") and B.next_slot(e) == "criterion"
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_bei.is_no_recall_text(_bei_user_text)" in src and '_tm["no_recall_skip"] = _prev_slot_nr' in src
    assert 'not _reask_kind and _fp_final is None and not _bei_ep.get("ask_first")):' in src                                 # 페르소나 문장은 첫 꼬리 턴에 쓰지 않는다


def test_p13b_first_question_only_and_wording():
    """(P13b-2·3) 질문 문장이 둘 이상이면 첫 문장만(문장 단위) · 금지 꼴 · 여는 질문은 낱말을 빼지 않는다 · 고정 다리 문장은 조각이 아니다."""
    from diag_project.data.competencies import SUBCOMPETENCY_ANCHOR_QUESTIONS
    from diag_project.services.output_guard import keep_first_question, strip_state_leak
    from diag_project.services.persona_voice import voice_question
    from diag_project.services.turn_checks import is_announce_ask
    from tools.regression_table import classify_broken
    t = "검수표를 다시 짜셨군요. 그 표를 누구에게 먼저 보여 주셨습니까? 그때 반장들은 무엇이라고 했는지 말씀해 주시겠습니까?"
    assert keep_first_question(t) == ("검수표를 다시 짜셨군요. 그 표를 누구에게 먼저 보여 주셨습니까?", 1)
    one = "그 표를 누구에게 먼저 보여 주셨는지, 그리고 반장들은 무엇이라고 했는지 말씀해 주시겠습니까?"
    assert keep_first_question(one) == (one, 0)                                                        # 한 문장 안의 두 물음은 손대지 않는다
    ann = "먼저 순서를 묻겠습니다. 그 표를 누구에게 먼저 보여 주셨습니까?"
    assert keep_first_question(ann, not_question=is_announce_ask) == (ann, 0)                          # 알리는 문장은 질문으로 세지 않는다
    fixed = "그 표를 누구에게 먼저 보여 주셨습니까? 최근에 일정이 밀린 적 있었나요?"
    assert keep_first_question(fixed, is_fixed=lambda x: "일정이 밀린" in x) == (fixed, 0)             # 시스템이 붙인 질문은 세지 않는다
    for bad in ("검수 순서를 바꾼 까닭이 분명하네요.", "리더님이 순서의 뜻을 짚어 주셨네요.", "판단의 근거를 잘 들었습니다."):
        assert strip_state_leak(f"{bad} 그 뒤에는 무엇을 하셨습니까?") == ("그 뒤에는 무엇을 하셨습니까?", 1), bad
    # 여는 질문: Lucas 도 사전 문안의 낱말을 그대로 둔다(끝맺음만 다르다)
    drop_ok = ("있", "어떤", "무엇")
    for qs in SUBCOMPETENCY_ANCHOR_QUESTIONS.values():
        for q in (qs if isinstance(qs, list) else [qs]):
            out = voice_question("Lucas", q, variant=0)
            words = [w.strip(",.?") for w in q.split()[:-1]]
            assert all(w in out for w in words if w), (q, out)
            for c in ("Jessica", "Olivia"):
                o = voice_question(c, q, variant=0)
                assert o.split()[0] == q.split()[0] or q.split()[0] in ("뭘", "걸"), (c, q, o)         # 문두의 '혹시·한번'도 떼지 않는다
    assert drop_ok
    assert classify_broken("먼저 하나부터.") is None and classify_broken("첫 장면부터.") is None and classify_broken("그 자리에 누가 있었는지도 함께요.") == "b"


def test_p13b_align_fixed_and_last_chapter_summary():
    """(P13b-4·5·6) ALIGN 받기는 LLM 없이 고정 받기 · 훑는 질문을 여는 턴은 받는 문장이 없어도 정상 · 마지막 영역도 요약 뒤 종료 문구."""
    import inspect
    from diag_project.routes import diagnoses as D
    from tools.sim_leader import Leader
    src = inspect.getsource(D._submit_message_phase3a)
    i = src.index('elif instruction_used == "COMPETENCY_ALIGN":')
    assert 'llm_output = {"reply": ""}' in src[i:i + 600] and '_tm["align_fixed"] = 1' in src[i:i + 600]
    assert "_fq(clean_reply, request.content, exempt=_exempt_q)" not in src and '_tm["align_receive_miss"] = 1' not in src      # LLM 받기에 걸던 검사는 삭제
    assert 'issues.append("no_receive")' not in src                                                    # (P13c-2) 받는 문장 검사는 전부 삭제
    j = src.index("# (2026-11-15 P13b-6) 마지막 영역도")
    k = src.index("wrap_up = f\"{_sum} {final_closing_message(", j)
    assert "render_close_summary as _rcs" in src[j:k] and "await _rlr(" not in src
    assert hasattr(Leader, "_answer_matched") and "기억나는 게 없" in Leader.NO_MATERIAL


def test_p13c_first_probe_check_and_fallback():
    """(2026-11-15 P13c-1) 사례의 첫 꼬리 질문 확인(표지) · 불합격이면 말투별 대체 문장 · 첫 꼬리 턴에는 프로필 탐침 선호 문구 없음."""
    import inspect
    from diag_project.prompts.phase3a import episode_card as EC
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B, intro_messages as IM
    from diag_project.services.leak_lexicon import GUARD_KEEP, guard_lexicon
    from diag_project.services.output_guard import is_question
    from diag_project.services.persona_register import apply_register
    from diag_project.services.persona_voice import persona_guide_block
    from diag_project.services.turn_checks import first_probe_asking_part, first_probe_question_ok as ok
    good = ("그 출고표를 바꾸실 때 리더님이 직접 하신 말은 무엇이었습니까?", "반장들이 반대했을 때, 리더님께서는 무엇을 먼저 말씀하셨습니까?",
            "야간 조에 그 순서를 알리실 때 뭐라고 하셨나요?", "검수 담당에게 그 일을 넘기면서 어떤 조치를 하셨는지 들려주시겠어요?")
    bad = (("그 순서를 바꾸신 것은 언제였습니까?", "off:언제"), ("그 회의에서 가장 먼저 떠오르는 장면은 무엇입니까?", "off:떠오르는 장면"),
           ("순서를 바꾸자고 하셨을 때 반장들은 어떤 반응을 보였습니까?", "off:어떤 반응"), ("그렇게 정하신 기준은 무엇이었습니까?", "off:기준은 무엇"),
           ("순서를 바꾼 뒤 출고 시간은 어떻게 됐습니까?", "off:어떻게 됐"), ("그 순서를 어떻게 생각하셨습니까?", "no_action"), ("", "no_question"))
    for q in good:
        assert ok(q) == (True, "ok"), (q, ok(q))
    for q, why in bad:
        assert ok(q) == (False, why), (q, ok(q))
    # 앞에 놓인 때 절은 보지 않는다 — 묻는 자리만 본다
    assert first_probe_asking_part("반장들이 언제 올지 몰라 하셨을 때, 리더님은 뭐라고 하셨습니까?") == "리더님은 뭐라고 하셨습니까?"
    assert ok("반장들이 어떤 반응을 보였을 때 리더님은 뭐라고 하셨습니까?") == (True, "ok")
    # 대체 문장: 코치마다 6종(P13d), 스스로 합격, 질문 꼴, 말투 교정에 바뀌지 않는다, 돌려 쓰면 직전 것과 겹치지 않는다
    for coach, pool in IM.FIRST_PROBE_FALLBACK.items():
        assert len(pool) == 6 and len(set(pool)) == 6      # (P13d-2) 3종 → 6종
        for i, x in enumerate(pool):
            assert ok(x) == (True, "ok") and is_question(x) and apply_register(coach, x, scope="strict")[0] == x, (coach, x)
            assert IM.first_probe_fallback(coach, i) == x and IM.first_probe_fallback(coach, i + 1) != x
            assert x in IM.all_fixed_sentences()
    assert "리더님" not in "".join(IM.FIRST_PROBE_FALLBACK["Lucas"]) and all("리더님이" not in x for x in IM.FIRST_PROBE_FALLBACK["Daniel"])
    # 첫 꼬리 턴에는 프로필 탐침 선호 문구를 넣지 않는다(여섯 코치 모두)
    ep = {"idx": 1, "leader_turns": 1, "slots": {k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}}
    ep = B.bump_slot_ask(ep, B.next_slot(ep))
    card = EC.build_episode_card(instruction="EPISODE_PROBE", chapter="work_management", ep=ep, bei_turns=2, budget=18)
    for coach in ("Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"):
        txt = EC.bei_turn_text({"instruction_for_this_turn": "EPISODE_PROBE", "bei_card": card, "coach_persona": {"name": coach}})
        assert "탐침 선호" not in txt and "리더가 방금 쓴 낱말이 들어가야 한다" in txt, coach
        assert "탐침 선호" in persona_guide_block(coach) and "탐침 선호" not in persona_guide_block(coach, with_preference=False)
    ep2 = B.bump_slot_ask(ep, B.next_slot(ep))
    card2 = EC.build_episode_card(instruction="EPISODE_PROBE", chapter="work_management", ep=ep2, bei_turns=3, budget=18)
    assert "탐침 선호" in EC.bei_turn_text({"instruction_for_this_turn": "EPISODE_PROBE", "bei_card": card2, "coach_persona": {"name": "Daniel"}})
    # 지시문에 쓴 낱말이 가드 사전에 들어가 다른 턴의 문장이 지워지지 않는다. (GUARD_KEEP 은 '누설 낱말로 남기는' 목록이라 여기에 넣으면 반대로 지워진다)
    g = guard_lexicon()["korean"]
    for w in ("반응", "장면", "자리", "결과", "기준", "판단"):
        assert w not in g and w not in GUARD_KEEP, w
    # (P13d-2) 확인·대체는 전용 호출 자리로 옮겼다 — 8-q2 에는 하는 일이 없다
    src = inspect.getsource(D._submit_message_phase3a)
    i = src.index("# 8-q2. (2026-11-15 P13c-1 → P13d-2)")
    assert "_tm[" not in src[i: src.index("# 8-z.", i)]
    assert '"first_probe": _tm.get("first_probe")' in src


def test_p13c_no_receive_requirement_left_and_wording():
    """(P13c-2·3) 받는 문장을 요구하는 곳이 없다 · 페르소나 문장은 받는 문장 유무와 무관 · 금지 꼴·지시문."""
    import inspect
    from diag_project.prompts.phase3a.episode_card import TURN_FORMAT_RULES
    from diag_project.routes import diagnoses as D
    from diag_project.services.output_guard import strip_state_leak
    src = inspect.getsource(D._submit_message_phase3a)
    for gone in ('issues.append("no_receive")', 'issues.append("no_quote")', "quote_receive as _qrcv_w", '_tm["receive_fallback"] = "quote"', "_recv_optional_w2"):
        assert gone not in src, gone
    assert 'if _pn_s == "Michael" and _mq_pending:' in src and '_slot_kind in ("observation", "cheer") and _q_now_s))' not in src
    assert 'not _reask_kind and _fp_final is None and not _bei_ep.get("ask_first")):' in src                                 # 첫 꼬리 턴에는 페르소나 문장을 넣지 않는다
    assert "_c_w2 = _bei_anchor_text.strip()" in src
    for bad in ("출고 지연이 줄었다는 점이 분명하게 드러나는군요.", "검수 순서가 가장 큰 변화로 보이는군요.", "반장들의 뜻이 그런 것으로 보이네요."):
        assert strip_state_leak(f"{bad} 그 뒤에는 무엇을 하셨습니까?") == ("그 뒤에는 무엇을 하셨습니까?", 1), bad
    assert strip_state_leak("표가 잘 보이게 벽에 붙이셨군요.")[1] == 0
    assert "받는 말은 리더가 쓴 낱말로만 쓴다" in TURN_FORMAT_RULES and "짐작하게 하는 질문도 하지 않는다" in TURN_FORMAT_RULES


def test_p13d_ending_regen_gone_and_first_probe_dedicated_call():
    """(2026-11-15 P13d-1·2) 끝맺음 반복 다시 쓰기 삭제 · 첫 꼬리 질문은 전용 호출(넘기는 재료 셋) · 표지 추가 · 대체 문장 6종."""
    import asyncio
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import first_probe_render as FP, intro_messages as IM
    from diag_project.services.turn_checks import first_probe_question_ok as ok, tail_key
    src = inspect.getsource(D._submit_message_phase3a)
    assert "q_stand:ending" not in src and "_qem_b" not in src and "_used_end_b = [" in src            # 검사·다시 쓰기는 없고 프롬프트 전달은 남는다
    # 전용 호출 분기: 본 호출보다 먼저, 다른 재생성 없이, 끝에서 다시 놓는다
    i = src.index('elif ((instruction_used == "SWEEP_FOLLOWUP" or (instruction_used == "EPISODE_PROBE" and (_bei_ep or {}).get("ask_first"))) and chapter):')
    j = src.index('elif instruction_used == "COMPETENCY_ALIGN":', i)
    blk = src[i:j].split('elif instruction_used == "EPISODE_PROBE" and (_bei_ep or {}).get("specify_now")')[0]      # (P14b-3) 뒤에 구체화 전용 호출 분기가 생겼다
    assert "render_first_probe" in blk and "generate_phase3a_interaction" not in blk and "_timed_regen" not in blk
    # (P15 판정 2 → P15b 판정 1) 한 번의 호출에서 후보 둘을 받아 먼저 통과하는 것을 쓴다. 둘 다 떨어졌을 때만 한 번 더 부른다
    assert '_tm["first_probe"] = "llm_retry" if _retry_fp else "llm"' in blk and '_tm["first_probe"] = "fallback"' in blk and '_tm["no_regen"] = 1' in blk and '_tm["first_probe_s"]' in blk
    assert src.count("clean_reply = _fp_final") == 2
    # 넘기는 것: 리더의 직전 답 · 말투 · 이번 영역에서 쓴 끝맺음. 넘기지 않는 것: 칸 상태 · 방향 힌트 · 코치 프로필 · 영역 정의
    assert set(inspect.signature(FP.render_first_probe).parameters) == {"llm", "leader_answer", "persona_name", "used_endings", "angle", "retry_note"}
    pr = FP.build_first_probe_prompt(leader_answer="야간 조 반장과 출고표를 다시 짰습니다.", persona_name="Daniel (다니엘)", used_endings=["말씀해 주시겠습니까"])
    assert "야간 조 반장과 출고표를 다시 짰습니다." in pr and "합쇼체" in pr and "'말씀해 주시겠습니까'" in pr
    assert "묻지 않는 것: 때·자리·장면, 다른 사람의 반응, 리더의 생각·기준, 결과" in pr
    for w in ("Daniel", "다니엘", "들음:", "아직:", "이번 질문:", "탐침 선호", "업무관리", "하위역량"):
        assert w not in pr, w
    assert "끝맺음" not in FP.build_first_probe_prompt(leader_answer="출고표를 다시 짰습니다.", persona_name="Ella (엘라)")

    class _LLM:
        def __init__(self, out):
            self.out, self.calls = out, []

        async def _generate_with_retry(self, **kw):
            self.calls.append(kw)
            return self.out
    llm = _LLM("반장과 출고표를 다시 짜실 때 리더님께서 먼저 꺼내신 말씀은 무엇이었습니까?")
    # (P15 판정 2) 전용 호출은 질문 후보 목록을 돌려준다(최대 둘) — 한 줄에 하나씩
    qs, mode = asyncio.run(FP.render_first_probe(llm, leader_answer="야간 조 반장과 출고표를 다시 짰습니다.", persona_name="Daniel (다니엘)"))
    assert mode == "llm" and len(qs) == 1 and ok(qs[0]) == (True, "ok") and llm.calls[0]["call_type"] == "first_probe_render" and len(llm.calls) == 1
    two = _LLM("1. 출고표를 다시 짜실 때 반장에게 직접 뭐라고 하셨나요?\n2. 반장과 출고표를 놓고 직접 어떤 말을 건네셨나요?")
    qs2, _ = asyncio.run(FP.render_first_probe(two, leader_answer="출고표를 다시 짰습니다.", persona_name="Ella (엘라)"))
    assert qs2 == ["출고표를 다시 짜실 때 반장에게 직접 뭐라고 하셨나요?", "반장과 출고표를 놓고 직접 어떤 말을 건네셨나요?"] and len(two.calls) == 1
    # 한 줄에 두 질문을 이어 쓰면 문장으로 갈라 후보 둘로 본다. 한 후보 안에 혼잣말이 섞여 문장이 둘 이상이면 그대로 돌려줘 확인에서 떨어지게 한다
    qs3, _ = asyncio.run(FP.render_first_probe(_LLM("출고표를 다시 짜실 때 뭐라고 하셨나요? 반장에게는 무엇을 맡기셨나요?"), leader_answer="출고표를 다시 짰습니다.", persona_name="Ella (엘라)"))
    assert qs3 == ["출고표를 다시 짜실 때 뭐라고 하셨나요?", "반장에게는 무엇을 맡기셨나요?"]
    from diag_project.services.turn_checks import first_probe_question_ok as _ok_g
    qs4, _ = asyncio.run(FP.render_first_probe(_LLM("끝맺음을 바꿉니다. 출고표를 다시 짜실 때 뭐라고 하셨나요?\n반장에게는 무엇을 맡기셨나요?"), leader_answer="출고표를 다시 짰습니다.", persona_name="Ella (엘라)"))
    assert len(qs4) == 2 and _ok_g(qs4[0], "출고표를 다시 짰습니다.") == (False, "meta")
    assert asyncio.run(FP.render_first_probe(_LLM("출고표를 다시 짜셨군요."), leader_answer="출고표를 다시 짰습니다.", persona_name="Ella (엘라)")) == ([], "miss:no_question")
    assert asyncio.run(FP.render_first_probe(None, leader_answer="출고표를 다시 짰습니다.", persona_name="Ella (엘라)")) == ([], "miss:no_llm")
    # (나) 표지 추가: 시점 · 어떤 생각 · 어떤 마음
    assert ok("반장이 반대하는 것을 보고 어떤 생각이 드셨는지, 그리고 말을 꺼내신 시점이 조회 직후였는지 말씀해 주시겠습니까?")[0] is False
    assert ok("그 표를 꺼내신 시점은 조회 뒤였습니까?") == (False, "off:시점") and ok("어떤 마음으로 그 말을 꺼내셨습니까?") == (False, "off:어떤 마음")
    assert ok("표를 고치기로 한 시점에 리더님은 뭐라고 하셨습니까?") == (True, "ok")      # 앞에 놓인 때 절은 보지 않는다
    # 대체 문장 6종: 시작 낱말·끝맺음이 서로 겹치지 않고, '그 일에서'로 시작하는 것은 하나뿐
    for coach, pool in IM.FIRST_PROBE_FALLBACK.items():
        assert len({x.split()[0] for x in pool}) == 6 and len({tail_key(x) for x in pool}) == 6, coach
        assert sum(1 for x in pool if x.startswith("그 일에서")) <= 1, coach      # (P13e-1) 각도별로 다시 써서 지금은 0개


def test_p13d_receive_allow_list_and_request_forms():
    """(P13d-3·4) 받는 말은 허용 목록(되짚는 끝맺음 · 리더 낱말 둘 이상 · 12어절 이하)일 때만 · 청하는 꼴도 질문 문장."""
    import inspect
    from diag_project.prompts.phase3a.episode_card import TURN_FORMAT_RULES
    from diag_project.routes import diagnoses as D
    from diag_project.services.output_guard import is_question, keep_first_question
    from diag_project.services.turn_checks import RECEIVE_ALLOWED_ENDINGS, receive_allowed as ra
    ans = "야간 조 반장과 출고표를 다시 짰고, 검수 순서는 앞으로 당겼습니다."
    for s in ("야간 조 반장과 출고표를 다시 짜셨군요.", "검수 순서를 앞으로 당기셨다는 말씀이군요.", "출고표를 다시 짜고 검수 순서를 당기신 거군요.",
              "출고표를 반장과 다시 짰다고 하셨네요.", "검수 순서를 앞으로 당기셨다는 거죠."):
        assert ra(s, ans) == (True, "ok"), (s, ra(s, ans))
    # 추측·평가·소감 어미는 목록에 없어 떨어진다
    for s in ("출고표를 다시 짠 것은 쉽지 않은 결정이었겠습니다.", "검수 순서를 당긴 것이 핵심으로 보입니다.", "반장과 출고표를 다시 짠 점을 짚어 두고 싶습니다.",
              "출고표와 검수 순서 이야기는 분명히 들었습니다.", "반장과 출고표를 다시 짜신 모습이 인상적이네요.", "검수 순서가 달라진 것으로 보이는군요."):
        assert ra(s, ans, formal=True) == (False, "ending"), (s, ra(s, ans, formal=True))
    assert ra("그렇게 하셨군요.", ans) == (False, "overlap") and ra("회의 자료를 미리 돌리셨군요.", ans) == (False, "overlap")      # 리더 낱말이 둘 미만
    long_s = "야간 조 반장과 출고표를 다시 짜고 검수 순서도 앞으로 당기고 그 뒤 표를 벽에 붙여 모두가 보게 하셨군요."
    assert len(long_s.split()) > 12 and ra(long_s, ans) == (False, "long")
    # 합쇼체 코치만 '…셨습니다' 꼴
    s_f = "야간 조 반장과 출고표를 다시 짜셨습니다."
    assert ra(s_f, ans, formal=True) == (True, "ok") and ra(s_f, ans) == (False, "ending")
    assert set(RECEIVE_ALLOWED_ENDINGS) == {"common", "formal"}
    src = inspect.getsource(D._submit_message_phase3a)
    i = src.index("# 8-wa. (2026-11-15 P13d-3)")
    blk = src[i: src.index("# 8-w00.", i)]
    assert "_timed_regen" not in blk and "await" not in blk and '_tm["recv_allow"]' in blk and "_fp_final is None" in blk
    assert src.count("_recv_allow_pass()") == 3 and '"recv_allow": _tm.get("recv_allow")' in src      # 정의 1 + 호출 2(금지 꼴 앞 · 8-w5 앞)
    # (P14-1) 받는 말은 전용 호출이 쓴다 — 본 호출 지시문에는 '질문만 쓴다'가 들어가고 받는 말 꼴 지시는 전용 호출 쪽으로 갔다
    from diag_project.services.turn_checks import RECEIVE_ENDING_HINT as _REH
    assert "질문 문장만 쓴다" in TURN_FORMAT_RULES and "-셨군요" in _REH and "-말씀이군요" in _REH.replace("다는 ", "")
    # 청하는 꼴도 질문 문장 — 물음 + 청함이 함께 있으면 첫 문장만 남는다
    for s in ("그 자리에서 실제로 꺼내신 말씀을 그대로 옮겨 주십시오.", "순서대로 말씀해 주십시오.", "하나씩 들려주세요.", "그 일을 풀어 주세요.", "먼저 한 일을 짚어 주세요."):
        assert is_question(s), s
    for s in ("그렇게 표를 옮겨 주셨군요.", "말씀해 주셔서 감사합니다."):
        assert not is_question(s), s
    assert keep_first_question("표가 막힌 곳은 어디였습니까? 그때 꺼내신 말씀을 그대로 옮겨 주십시오.") == ("표가 막힌 곳은 어디였습니까?", 1)


def test_p13e_first_probe_angles_reaction_cap_and_marks():
    """(2026-11-15 P13e) 첫 꼬리 질문의 각도 넷 · 닫힌 질문·맺지 않은 문장은 대체 · 반응 질문 사례당 1회 · 부호 수선 · Olivia 슬롯 없음."""
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B, first_probe_render as FP, intro_messages as IM, slot_judge as SJ, turn_checks as TC
    from diag_project.services.output_guard import is_question
    # 각도 — 답에 이미 나온 각도와 직전 각도는 피한다
    ans = "출고가 밀려서 제가 먼저 야간조에 물량을 넘기자고 제안했습니다."
    assert "said" in TC.first_probe_angles_in(ans) and TC.pick_first_probe_angle(ans, []) != "said"
    assert TC.pick_first_probe_angle("창고 일이 밀린 적이 있습니다.", ["said"]) == "did"
    used = []
    for _ in range(8):
        a = TC.pick_first_probe_angle("창고 일이 밀린 적이 있습니다.", used)
        assert not used or a != used[-1]
        used.append(a)
    assert set(used) == set(TC.FIRST_PROBE_ANGLES)
    for a in TC.FIRST_PROBE_ANGLES:
        pr = FP.build_first_probe_prompt(leader_answer=ans, persona_name="Daniel", angle=a)
        assert FP.ANGLE_ASK[a] in pr and "지어내지 않는다" in pr and "그렇다·아니다로 답하게 되는 꼴" in pr and "높임은 리더에게만" in pr
    # 확인 — 조치·순서·준비 표지, 닫힌 질문, 맺지 않은 문장
    ok = TC.first_probe_question_ok
    for q in ("창고 물량을 넘기기 전에 미리 확인하신 것은 무엇이었습니까?", "그 일을 무엇부터 시작해 어떤 순서로 진행하셨는지 말씀해 주십시오.",
              "야간조에 물량을 넘기면서 직접 취하신 조치를 들려주시겠습니까?"):
        assert ok(q) == (True, "ok"), (q, ok(q))
    assert ok("야간조 반장에게 먼저 말을 건네셨습니까?") == (False, "closed")
    assert ok("그 자리에서 하신 조치가 있었나요?") == (False, "closed")
    assert ok("그 자리에서 직접 어떤 말을 건네셨는지 짚어 주시겠습니다만…") == (False, "unfinished")
    # 대체 문장 — 말투별 6종, 네 각도가 모두 들어 있고 각도를 주면 그 각도의 문장
    for coach, pairs in IM.FIRST_PROBE_FALLBACK_BY_ANGLE.items():
        assert len(pairs) == 6 and {a for a, _t in pairs} == set(TC.FIRST_PROBE_ANGLES), coach
        for a, t in pairs:
            assert ok(t) == (True, "ok") and is_question(t), (coach, t)
            assert IM.first_probe_fallback(coach, 0, a) in [x for y, x in pairs if y == a]
    src = inspect.getsource(D._submit_message_phase3a)
    assert "first_probe_angle" in src and "_pick_fp(_llm_user_text, _angles_fp)" in src and "_fpp_fp(_pn_fp, _angle_fp, _used_fb_fp)" in src
    # 반응 질문 — 사례당 한 번: 물은 것이 적히면 방향 후보에서 빠진다
    assert B.asks_reaction("그 말을 듣고 반장은 어떤 반응을 보였습니까?") and B.asks_reaction("그 제안을 야간조가 어떻게 받아들였는지 말씀해 주시겠습니까?")
    assert not B.asks_reaction("그 제안을 리더님은 어떻게 받아들이셨습니까?") and not B.asks_reaction("팀 분위기가 가라앉았던 일이 최근에 있으셨습니까?")
    ep = {"idx": 1, "slots": {k: {"status": "filled", "quote": "x"} for k in B.SLOT_KEYS}, "slot_asks": {"action": 1}}
    ep["slots"]["reaction"] = {"status": "empty", "quote": ""}
    assert B.next_slot(ep) == "reaction"
    assert B.next_slot(B.note_reaction_asked(ep)) is None
    assert "_bei.asks_reaction(_prev_coach_rx)" in src
    # 부호 수선 — 뜻은 그대로
    assert TC.finish_sentence_marks("어떤 말로 전하셨는지 궁금해요?") == ("어떤 말로 전하셨는지 궁금해요.", 1)
    assert TC.finish_sentence_marks("어떤 말씀을 하셨는지 들려주실 수 있을까요") == ("어떤 말씀을 하셨는지 들려주실 수 있을까요?", 1)
    assert TC.finish_sentence_marks("그렇게 정하셨군요. 그 뒤에 무엇을 하셨습니까?")[1] == 0
    # 같은 장면 — 기준은 리더의 결정·행동, 애매하면 다른 장면
    sj = inspect.getsource(SJ.judge_slots)
    assert "리더의 결정·행동이 그 이야기의 결정·행동과 같은 것" in sj and "애매하면 다른 장면으로 본다" in sj and "같은 때·같은 사람·같은 일" not in sj.split("same_as: 아래")[1]
    # Olivia — '그 사람 자리' 슬롯 삭제
    assert IM.slot_kind_for("Olivia", 0) is None and "Olivia" not in IM.SLOT_KINDS


def test_p13f_addressee_check_three_angles_and_parallel_close():
    """(2026-11-15 P13f) 첫 꼬리 질문의 상대 확인 · 각도 셋 · 표지 오탐 · 다른 사람의 말을 묻는 질문도 반응으로 · 매핑과 받는 말 동시 실행(실패 경로)."""
    import asyncio
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B, close_receive_render as CR, first_probe_render as FP, intro_messages as IM, turn_checks as TC
    ok = TC.first_probe_question_ok
    # 1. 상대 확인 — 질문의 '○○에게'는 리더가 직전 답에서 말을 건넨 상대로 말한 사람이어야 한다
    a1 = "출고가 밀려서 야간조 반장과 따로 이야기했고, 물량을 넘기기로 정했습니다."
    # (P13g-1) 통째로 바꾸지 않고 걸린 어절만 지운다 — 아래 test_p13g 에서 본다. 여기서는 확인 함수가 상대를 보지 않는 것만.
    assert ok("그때 거래처 담당자에게 직접 어떤 말을 건네셨습니까?", a1) == (True, "ok")
    assert ok("그 일을 함께 풀면서 리더님께서 직접 어떤 조치를 하셨습니까?", a1) == (True, "ok")
    # 2. 각도 셋 — 준비·확인 각도 삭제, 대체 문장은 각도마다 둘, '상대에게' 없음
    assert TC.FIRST_PROBE_ANGLES == ("said", "did", "order") and set(FP.ANGLE_ASK) == set(TC.FIRST_PROBE_ANGLES)
    assert TC.pick_first_probe_angle("창고 일이 밀린 적이 있습니다.", ["prep", "said"]) == "did"      # 옛 세션 기록의 prep 은 무시
    for coach, pairs in IM.FIRST_PROBE_FALLBACK_BY_ANGLE.items():
        assert [a for a, _t in pairs] == ["said", "said", "did", "did", "order", "order"], coach
        assert not any("상대에게" in t for _a, t in pairs) and all(ok(t, "창고 일이 밀렸습니다.") == (True, "ok") for _a, t in pairs), coach
    pr = FP.build_first_probe_prompt(leader_answer=a1, persona_name="Ella", angle="did")
    assert "두 번 겹쳐 묻지 않는다" in pr and "리더가 말하지 않은 상대를 지어내지 않는다" in pr
    # 3. 표지 오탐 — 리더가 쓴 낱말 하나가 그대로 들어간 것은 표지가 아니다. 의문사가 붙은 표지는 그대로 본다
    a3 = "역할을 나누고, 공통 마감일과 중간 점검 시점을 정해 함께 움직이도록 조정했습니다."
    assert ok("공통 마감일과 중간 점검 시점을 정하기까지 리더님이 직접 어떤 말을 건네셨나요?", a3) == (True, "ok")
    assert ok("공통 마감일과 중간 점검 시점을 정하기까지 리더님이 직접 어떤 말을 건네셨나요?", "역할을 나눴습니다.")[1] == "off:시점"
    assert ok("그 일이 있고 나서 팀에서는 어떤 반응이 나왔습니까?", "팀 반응이 좋았습니다.")[1].startswith("off:")
    assert ok("그 자료를 두고 어떤 방식으로 개선 방향을 찾아가셨나요?", a3) == (True, "ok")
    # 5. 다른 사람의 말을 묻는 질문도 반응 질문으로 센다
    assert B.asks_reaction("그 자리에서 반장이 어떤 말을 했는지 들려주시겠어요?") is False      # 목록에 없는 직함은 세지 않는다(한계)
    assert B.asks_reaction("그 자리에서 팀원이 어떤 말을 했는지 들려주시겠어요?") and B.asks_reaction("그렇게 물으셨을 때 어떤 대답이 돌아왔는지 들려주시겠어요?")
    assert not B.asks_reaction("리더님이 그 팀원에게 어떤 말을 하셨는지 들려주시겠어요?")
    # 4. 매핑과 받는 말 동시 실행 — 실패 경로
    async def _map_ok():
        await asyncio.sleep(0.05); return [{"sub": "x", "strength": "strong"}]
    async def _map_fail():
        raise RuntimeError("map down")
    async def _recv_ok():
        await asyncio.sleep(0.05); return ("물량을 야간조에 넘기기로 정하셨군요.", "llm")
    async def _recv_fail():
        raise RuntimeError("recv down")
    import time
    t0 = time.perf_counter()
    labels, txt, mode = asyncio.run(CR.map_and_receive(_map_ok(), _recv_ok()))
    assert labels and txt and mode == "llm" and time.perf_counter() - t0 < 0.095          # 차례가 아니라 동시에 돈다
    labels, txt, mode = asyncio.run(CR.map_and_receive(_map_ok(), _recv_fail()))
    assert labels and txt is None and mode == "miss:error"                                  # 받는 말만 실패 → 매핑 결과는 그대로, 본 호출은 호출자가 종전대로
    try:
        asyncio.run(CR.map_and_receive(_map_fail(), _recv_ok()))
        raise AssertionError("매핑 실패는 올라가야 한다")
    except RuntimeError as e:
        assert "map down" in str(e)
    class _Boom:
        async def _generate_with_retry(self, **kw):
            raise RuntimeError("llm down")
    assert asyncio.run(CR.render_close_receive(_Boom(), leader_answer="물량을 넘겼습니다.", persona_name="Ella")) == (None, "miss:error")
    assert asyncio.run(CR.render_close_receive(None, leader_answer="물량을 넘겼습니다.", persona_name="Ella")) == (None, "miss:no_llm")
    src = inspect.getsource(D._submit_message_phase3a)
    # (P14-1 → P15-1) 받는 말은 사례를 닫을 때 매핑과 함께(조건이 맞을 때만) 받는다. 닫는 턴이 본 호출 없이 나가는 것은 그대로.
    assert "_mar_c(" not in src and "_aio_c.gather(" in src and "_aio_r.gather(" not in src and 'instruction_used in ("EPISODE_OPEN", "SWEEP_ANCHOR") and chapter:' in src
    assert "state[\"_pre_recv_text\"]" not in src                                           # 세션 상태에 남기지 않는다


def test_p13g_addressee_partial_cut_retry_marks_and_short_question_context():
    """(2026-11-15 P13g) 상대 어절만 지우기 · 떨어지면 한 번 더 쓰기 · 문장 끝 수선 · 짧은 질문 앞 받는 말 남기기 · 받아 둔 받는 말에는 재생성 없음."""
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import first_probe_render as FP, intro_messages as IM, turn_checks as TC
    fix, ok = TC.first_probe_addressee_fix, TC.first_probe_question_ok
    # 1. 부분 삭제 — 제3자 목록의 사람이 말을 건넨 상대로 나오지 않았거나, 답에 없는 사람이면 그 어절만 지운다
    a1 = "납품이 늦어 고객 불만이 컸습니다. 야간조 반장이 반대했지만 물량을 넘기기로 정했습니다."
    assert fix("물량을 넘기기로 정하실 때, 고객들에게 직접 어떤 말씀을 하셨습니까?", a1) == ("물량을 넘기기로 정하실 때, 직접 어떤 말씀을 하셨습니까?", ["고객들에게"], True)
    assert fix("반장이 반대했을 때 반장에게 직접 어떤 말을 건네셨습니까?", a1)[1] == []                    # 주어로만 나와도 합격(제3자 목록이 아니다)
    assert fix("그때 하청 담당자에게 직접 어떤 말을 건네셨습니까?", a1) == ("그때 직접 어떤 말을 건네셨습니까?", ["하청 담당자에게"], True)   # 답에 없는 사람 — 앞에 붙은 명사까지
    assert fix("고객에게 사과하셨을 때 어떤 말로 시작하셨습니까?", "고객에게 먼저 전화해 사과했습니다.")[1] == []      # 말을 건넨 상대로 말했다
    assert fix("그 교육을 듣는 수강생들에게 직접 어떤 말씀을 하셨습니까?", a1)[2] is False                  # 꾸미는 절이 남는다 → 온전하지 않음(한 번 더 쓴다)
    assert fix("고객들이 항의했을 때, 리더께서 그들에게 직접 어떤 말씀을 하셨습니까?", a1)[1] == ["그들에게"]
    assert "교육생" in TC.THIRD_PARTY_WORDS and "고객" in TC.THIRD_PARTY_WORDS and "팀원" not in TC.THIRD_PARTY_WORDS
    # 2. 한 번 더 쓰기 — 혼잣말·두 문장·코치 주어 동사는 불합격, 사유를 한 줄로 넘긴다
    assert ok("순서대로 말씀해 주십시오 — 아니, 규칙상 질문 한 문장이어야 하므로: 무엇부터 하셨습니까?", a1) == (False, "meta")
    assert ok("무엇을 하셨습니까? 그다음에는 무엇을 하셨습니까?", a1) == (False, "meta")
    assert ok("물량을 어떤 순서로 넘기셨는지 여쭙고 싶습니까?", a1) == (False, "self_verb")
    # (P15 판정 2 → P15b 판정 1) 후보 둘이 다 떨어졌을 때만(하나만 온 경우 포함) 사유를 한 줄로 넘겨 한 번 더 부른다
    for why in ("closed", "off:어떤 반응", "no_action", "unfinished", "meta", "self_verb", "who", "register", "short", "no_noun", "borrow"):
        note = TC.first_probe_retry_note(why)
        assert note and note in FP.build_first_probe_prompt(leader_answer=a1, persona_name="Daniel", angle="did", retry_note=note)
    assert "앞서 쓴 질문은 쓸 수 없었다" not in FP.build_first_probe_prompt(leader_answer=a1, persona_name="Daniel", angle="did")
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_one_fp(" not in src and "retry_note=_note_fp(_whys_fp[0] if _whys_fp else \"no_question\")" in src
    assert 'if not _q_fp and _mode_fp not in ("stub", "miss:no_llm", "miss:no_material"):' in src
    # 대체 문장 — 세션에서 같은 문장은 한 번만
    used = []
    for _ in range(6):
        t = IM.first_probe_fallback_pick("Ella", "said", used)
        assert t not in used
        used.append(t)
    assert IM.first_probe_fallback_pick("Ella", "said", [])[:3] == "거기서" and IM.first_probe_fallback_pick("Ella", "said", used)
    # 3. 문장 끝 수선
    f = TC.finish_sentence_marks
    assert f("그다음 무엇을 하셨는지 순서대로 말씀해 주십시오?")[0].endswith("주십시오.")
    assert f("그 뒤 무엇을 하셨는지 들려주세요")[1] == 0                                                   # 청하는 꼴에는 물음표를 붙이지 않는다
    assert f("직접 진행하신 순서를 여쭙겠습니다: 무엇을 먼저 하셨습니까?")[0] == "무엇을 먼저 하셨습니까?"
    assert f("어떤 말씀을 하셨는지 들려주실 수 있을까요")[0].endswith("있을까요?")
    # 4. 짧은 질문 앞의 받는 말 — 길이만으로 떨어진 것은 20어절까지 남긴다(끝맺음·겹침은 그대로)
    ans = "하반기 운영 횟수는 줄었지만 현장 사례를 넣은 교재 초안을 만들 수 있었습니다. 내년 과정 계획도 이 교재를 기준으로 세우기로 했습니다."
    recv = "하반기에 운영 횟수는 줄이셨지만 교재 초안까지 만드셨고, 내년 계획을 그 교재 기준으로 세우기로 하셨군요."
    assert TC.receive_allowed(recv, ans) == (False, "long") and TC.receive_allowed(recv, ans, max_eojeol=TC.RECEIVE_KEEP_LONG_MAX) == (True, "ok")
    assert TC.receive_allowed("그 결정이 내년까지 이어진 것으로 보입니다.", ans, max_eojeol=20)[1] == "ending"
    assert "recv_keep_long" in src and "not _tm.get(\"recv_keep_long\")" in src
    # 5. 받아 둔 받는 말에는 입버릇 재생성을 걸지 않는다
    i = src.index("(2026-11-15 P13g-5)")
    assert src.rfind('_tm.get("pre_recv") == "used" and _pre_recv_text', 0, i) > 0 and src.index('_timed_regen(why="tail"', i) > i


def test_regression_check_judge_limits():
    """(2026-11-15) 회귀 점검 스크립트의 조건 판정 — 상한 이하면 통과, 값이 없으면 통과로 보지 않는다."""
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location("regression_check", pathlib.Path(__file__).resolve().parent.parent / "tools" / "regression_check.py")
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    # (P15 → P15b 판정) 조건표 15항목 — p50 4.6초(이번 묶음) · 대체 문장 ≤ 1 · (A) 10% · a 되짚는 턴 · b 꼬리 턴 받는 말 ·
    #   c 사례당 청하는 꼴 2회 이상인 사례 0 · d 호칭으로 시작 · 전환 턴 · 8어절 미만 꼬리 질문 ≤ 1 · 구체화. 받는 말 어절·끝맺음은 참고로만 표시한다
    good = {"p50": 4.6, "p95": 8.0, "regen_turns": 8, "format_miss": 0, "broken_total": 0, "fp_fallback": 1, "ctx_bare_pct": 10.0, "echo_pct": 30.0,
            "tail_recv_n": 0, "req_case_multi": 0, "lead_addr_n": 0, "trans_cover_pct": 100.0, "echo_trans_max": 2, "tail_short_n": 1, "specify_multi": 0}
    assert all(ok for _n, _v, ok in rc.judge(good)) and len(rc.judge(good)) == 15
    lim_keys = {k for _n, k, _lo, _hi in rc.LIMITS}
    assert not lim_keys & {"trans_recv_pct", "recv_have_pct", "recv_streak4", "short_bare", "bare_pct", "req_tail_pct", "recv_avg_eojeol", "recv_top_end_pct"}
    assert {k for _n, k in rc.INFO_ROWS} >= {"req_tail_pct", "recv_avg_eojeol", "recv_top_end_pct"}
    for key, bad in (("p50", 4.7), ("p95", 8.2), ("regen_turns", 9), ("format_miss", 1), ("broken_total", 1), ("fp_fallback", 2), ("p95", None),
                     ("ctx_bare_pct", 10.5), ("echo_pct", 30.5), ("tail_recv_n", 1), ("req_case_multi", 1), ("lead_addr_n", 1), ("trans_cover_pct", 90.0),
                     ("echo_trans_max", 3), ("tail_short_n", 2), ("specify_multi", 1), ("ctx_bare_pct", None), ("echo_pct", None)):
        assert not all(ok for _n, _v, ok in rc.judge(dict(good, **{key: bad}))), key
    # 참고 값(받는 말 어절·끝맺음·청하는 꼴 %)은 판정에 들어가지 않는다
    assert all(ok for _n, _v, ok in rc.judge(dict(good, recv_avg_eojeol=12.0, recv_top_end_pct=100.0, req_tail_pct=60.0)))
    rows = [{"role": "model", "instr": "EPISODE_PROBE", "content": "야간조에 물량을 넘기셨군요. 그 뒤에 무엇을 하셨습니까?", "guard": {"recv_out": "셨군요", "recv_rule": "B"}},
            {"role": "model", "instr": "EPISODE_PROBE", "content": "그 뒤에 무엇이 달라졌습니까?", "guard": {"recv_out": None, "recv_rule": "D-"}},
            {"role": "model", "instr": "SWEEP_ANCHOR", "content": "반장과 물량을 나누셨네요. 요즘 새로 시도하신 일이 있습니까?", "guard": {"recv_out": "셨네요", "recv_rule": "C"}},
            {"role": "model", "instr": "EPISODE_PROBE", "content": "그 자리를 지키셨습니다. 그렇게 정하신 기준은 무엇이었습니까?", "guard": {"recv_out": "slot"}}]
    st = rc.receive_stats(rows)
    assert st["recv_have_pct"] == 66.7 and st["recv_top_end_pct"] == 50.0 and st["recv_by_instr"] == {"EPISODE_PROBE": "1/2", "SWEEP_ANCHOR": "1/1"}
    assert st["short_bare"] == 1 and st["recv_over12"] == 0 and st["recv_rules"] == {"B": 1, "D-": 1, "C": 1}
    # (P14e) (A)(B) — 리더 직전 답을 함께 준 행으로 따로 본다
    ua = "야간조에 물량 삼백 상자를 넘기자고 반장에게 제안했습니다."
    rows2 = [{"role": "user", "content": ua}, {"role": "model", "instr": "EPISODE_PROBE", "content": "그 뒤에 무엇이 달라졌습니까?", "guard": {"recv_out": None}},
             {"role": "user", "content": ua}, {"role": "model", "instr": "EPISODE_PROBE", "content": "야간조에 물량을 넘기자고 제안하셨을 때, 반장에게 어떤 말로 꺼내셨습니까?", "guard": {"recv_out": None}},
             {"role": "user", "content": ua}, {"role": "model", "instr": "SWEEP_ANCHOR", "content": "물량을 넘기셨군요. 요즘 새로 시도하신 일이 있습니까?", "guard": {"recv_out": "셨군요"}},
             {"role": "user", "content": "네."}, {"role": "model", "instr": "SWEEP_ANCHOR", "content": "요즘 새로 시도하신 일이 있습니까?", "guard": {"recv_out": None}}]
    st2 = rc.receive_stats(rows2)
    assert st2["bare_list"] == ["그 뒤에 무엇이 달라졌습니까?"] and st2["main_n"] == 3 and st2["bare_pct"] == 33.3      # '네.' 뒤의 턴은 따지지 않는다
    assert st2["trans_recv_pct"] == 100.0 and len(st2["trans_list"]) == 1 and st2["recv_streak4"] == 0


def test_p14_receive_call_everywhere_specificity_and_rapport():
    """(2026-11-16 P14) 받는 말 전용 호출을 모든 본론 턴으로 · 구체화 질문 · 라포 되묻기 답 · 호칭 '리더님' · 질문 문구."""
    import asyncio
    import inspect
    from diag_project.llm_schemas import slot_judge_schema
    from diag_project.prompts.phase3a import episode_card as EC
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B, intro_messages as IM, receive_render as RR, slot_judge as SJ, turn_checks as TC
    from diag_project.services.output_guard import find_state_leak
    ans = "출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 반장에게 제안했습니다. 반장은 인력이 모자란다고 했습니다."
    # 1. 받는 말 확인 — 되짚는 끝맺음(넓힌 목록)·12어절·겹치는 낱말·금지 꼴·직전 두 번과 같은 끝맺음
    assert RR.check_receive("야간조에 물량 삼백 상자를 넘기자고 제안하셨군요.", ans) == (True, "ok")
    assert RR.check_receive("물량 삼백 상자를 넘기자고 하셨지요.", ans) == (True, "ok") and TC.receive_ending_key("물량을 넘기자고 하셨지요.") == "셨지요"
    assert RR.check_receive("쉽지 않은 결정이었을 것으로 보입니다.", ans)[1] == "ending"
    assert RR.check_receive("그 일을 어떻게 하셨습니까?", ans)[1] == "question"
    # (P14c-1) '직전 두 번과 다른 꼴'에서 '이번 세션에서 가장 많이 쓴 꼴은 쓰지 않는다'로 — 넘긴 꼴과 같으면 탈락
    # (P14e-3) 끝맺음 제한은 지시문에만 둔다 — 넘긴 꼴과 같아도 탈락시키지 않는다
    assert RR.check_receive("야간조에 물량 삼백 상자를 넘기자고 제안하셨군요.", ans, avoid_endings=["셨군요"]) == (True, "ok")
    assert not RR.receivable("네") and not RR.receivable("없어요") and not RR.receivable(ans, prev_answer=ans) and RR.receivable(ans)
    pr = RR.build_receive_prompt(leader_answer=ans, persona_name="Lucas", kind="probe", avoid_endings=["셨군요", "셨네요"])
    assert "가운데 하나만 골라 짧은 한 문장으로" in pr and "9어절을 넘기지 않는다" in pr and "평가·짐작·감상·칭찬" in pr and "리더님" in pr and "이번에는 끝을 -셨군요, -셨네요 꼴로 맺지 않는다" in pr
    assert "출력: 다시 말하는 한 문장만." in pr and "'" + "출고" not in pr      # 완성 문장 예시는 넣지 않는다
    # 라포 — 내용 낱말이 모두 리더 답에 있어야 한다(숫자·직함을 다른 뜻으로 풀면 불합격)
    assert RR.check_receive("나른하시군요.", "나른하네", kind="smalltalk") == (True, "ok")
    assert RR.check_receive("오늘 많이 피곤하시군요.", "나른하네", kind="smalltalk")[1] == "words"
    assert RR.check_receive("교육팀장으로 팀원 4명과 교육기획을 맡고 계시군요.", "교육팀장 4명 팀원 교육기획", kind="role") == (True, "ok")
    assert RR.check_receive("팀장 네 분과 교육기획을 하시는군요.", "교육팀장 4명 팀원 교육기획", kind="role")[1] == "words"
    assert TC.is_counter_question("그게 왜 궁금함?") and TC.is_counter_question("왜 물어?") and not TC.is_counter_question("나른하네")
    assert IM.rapport_counter_reply("Lucas") == "본론 전에 가볍게 여쭌 겁니다." and IM.rapport_counter_reply("Ella") in IM.all_fixed_sentences()
    # 실패 경로 — 전용 호출이 실패해도 예외를 올리지 않고 None
    class _Boom:
        async def _generate_with_retry(self, **kw):
            raise RuntimeError("llm down")
    assert asyncio.run(RR.render_receive(_Boom(), leader_answer=ans, persona_name="Ella")) == (None, "miss:error")
    assert asyncio.run(RR.render_receive(_Boom(), leader_answer="네", persona_name="Ella")) == (None, "skip:empty")
    class _Twice:
        n = 0
        async def _generate_with_retry(self, **kw):
            _Twice.n += 1
            return "쉽지 않은 결정이었을 것으로 보입니다." if _Twice.n == 1 else "야간조에 물량 삼백 상자를 넘기자고 제안하셨군요."
    # (P14b-2) 본론 받는 말은 다시 쓰지 않는다 — 한 번 떨어지면 받는 말 없이. 영역 정의·라포는 종전대로 한 번 더 쓴다
    # (P14b-2 → P14e-2) 본론 받는 말의 다시 쓰기를 되살렸다 — 떨어지면 사유를 넘겨 한 번 더 쓴다
    assert asyncio.run(RR.render_receive(_Twice(), leader_answer=ans, persona_name="Ella")) == ("야간조에 물량 삼백 상자를 넘기자고 제안하셨군요.", "llm_retry")
    _Twice.n = 0
    assert asyncio.run(RR.render_receive(_Twice(), leader_answer=ans, persona_name="Ella", kind="align"))[1] == "llm_retry"
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_aio_c.gather(" in src and "f\"{_pre_recv_text} {clean_reply}\"" in src and '_rapport_recv("smalltalk")' in src and 'kind="align"' in src
    assert "질문 문장만 쓴다" in EC.TURN_FORMAT_RULES and "'리더님'이라고만" in EC.TURN_FORMAT_RULES and "묻는 절을 쉼표나 '그리고'로 이어 붙이지 않는다" in EC.TURN_FORMAT_RULES
    # 호칭
    assert TC.fix_leader_address("리더께서 그 자리에서 리더가 하신 말") == "리더님께서 그 자리에서 리더님이 하신 말" and TC.fix_leader_address("리더님께서") == "리더님께서"
    # 2. 구체화 질문 — 판정 항목·카드 한 줄
    assert "specific" in slot_judge_schema()["properties"] and "specific: 리더의 **마지막 답**에 구체 표지" in inspect.getsource(SJ.judge_slots)
    ep = {"idx": 1, "leader_turns": 2, "slots": {k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}, "slot_asks": {"action": 1}, "specify_now": "result", "ask_slot": "result"}
    card = EC.build_episode_card(instruction="EPISODE_PROBE", chapter="work_management", ep=ep, bei_turns=3, budget=18)
    assert "리더가 방금 한 답을 구체로 만드는 질문 하나" in card and "눈에 보인 장면 하나여도 된다" in card and "다른 것으로 넘어가지 않는다" in card
    card2 = EC.build_episode_card(instruction="EPISODE_PROBE", chapter="work_management", ep=dict(ep, specify_now=None), bei_turns=3, budget=18)
    assert "구체로 만드는 질문" not in card2
    assert '_tm.get("specific") is False' in src and "_sp_n_ch < 3" in src and '"specificity_probe"' in src
    # 4. 질문 문구 — 방향 낱말이 그대로 나온 꼴, 묻는 꼴이 아닌 끝, 높임 없는 질문
    assert find_state_leak("이번에는 결과 쪽을 여쭙겠습니다.") and find_state_leak("근거 쪽으로 넘어가겠습니다.") and not find_state_leak("그 결과를 누구와 나누셨습니까?")
    ok = TC.first_probe_question_ok
    assert ok("그 자리에서 직접 어떤 말을 건네셨는지 궁금하네요.", ans) == (False, "wonder") and ok("직접 어떤 말을 건네셨는지 여쭤봐도 될까요?", ans) == (False, "wonder")
    assert ok("본인이 반장에게 직접 어떤 말을 건넸는지 알려줄 수 있나요?", ans) == (False, "no_honorific")
    for coach, pairs in IM.FIRST_PROBE_FALLBACK_BY_ANGLE.items():
        assert all(ok(t, "창고 일이 밀렸습니다.") == (True, "ok") for _a, t in pairs), coach


def test_p14b_one_receive_per_turn_specify_call_and_role_echo():
    """(2026-11-16 P14b) 한 턴에 리더 말을 되짚는 것은 한 번 · 받는 말 9어절·다시 쓰기 없음 · 구체화 전용 호출 · 낱말 나열 답은 그대로 넣어 조립 · 두 물음 다시 쓰기."""
    import asyncio
    import inspect
    from diag_project.prompts.phase3a import episode_card as EC
    from diag_project.routes import diagnoses as D
    from diag_project.services import intro_messages as IM, receive_render as RR, specify_render as SP, turn_checks as TC
    ans = "출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 반장에게 제안했습니다. 반장은 인력이 모자란다고 했습니다."
    # 1. 붙이는 규칙(A·B·D)은 P15 에서 지웠다 — 사례 안 꼬리 질문 턴에는 받는 말을 붙이지 않는다. 본 호출이 쓴 평서문을 지우는 것과 전환 턴(C)만 남는다
    assert not hasattr(TC, "receive_attach_rule")
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_rar_b(" not in src and '_tm["main_stmt_cut"] = len(_cut_b)' in src and '_tm["recv_rule"] = "C"' in src
    # 2. 받는 말 — 리더가 아닌 사람에게 높임, '말씀' 두 번, 인용꼴 상한, 머리의 호칭
    assert RR.check_receive("담당자가 인력이 모자란다고 하셨다는 말씀이네요.", ans) == (True, "ok")      # (P14f-1) 제3자 높임 확인은 없앴다
    assert RR.check_receive("리더님이 말씀하신 것은 물량을 넘기자는 말씀이네요.", ans)[1] == "dup"
    assert RR.check_receive("물량 삼백 상자를 넘기자고 하셨다는 말씀이네요.", ans, no_quote=True) == (True, "ok")      # (P14e-3) 인용꼴 상한도 지시만
    assert RR.strip_lead_address("리더님이 물량을 넘기자고 하셨다는 말씀이네요.") == "물량을 넘기자고 하셨다는 말씀이네요."
    assert RR.strip_lead_address("리더님께서 물량을 넘기자고 제안하셨군요.") == "물량을 넘기자고 제안하셨군요."      # (P14c-3) 모든 끝맺음에서 뗀다
    # (P14e-4) 모른다는 말이 답의 일부로 섞였으면 부른다 — 답 전체가 모른다·없다일 때만 부르지 않는다
    assert RR.receivable("그 부분은 따로 기억나는 게 없습니다. 다만 그 뒤에 반장과 물량을 다시 나눴습니다.") and not RR.receivable("그 부분은 따로 기억나는 게 없습니다.")
    pr = RR.build_receive_prompt(leader_answer=ans, persona_name="Ella", kind="probe", no_quote=True)
    assert "이번에는 '-다는 말씀이네요'" in pr and "문장을 '리더님'으로 시작하지 않는다" in pr
    # 3. 구체화 질문 — 전용 호출, 확인(구체화 표지가 있고 반응·이유 표지가 묻는 자리에 없다), 한 번 더 쓰기
    ok = TC.specify_question_ok
    assert ok("물량을 넘기셨다고 하셨는데, 몇 상자를 며칠에 걸쳐 넘기셨습니까?") == (True, "ok")
    assert ok("물량을 넘긴 뒤 달라진 것을 보여 주는 장면 하나를 들려주시겠습니까?") == (True, "ok")
    assert ok("물량을 넘기자고 했을 때 반장은 어떤 반응을 보였습니까?")[1].startswith("off:") and ok("그때 어떻게 하셨습니까?") == (False, "no_mark")
    psp = SP.build_specify_prompt(leader_answer=ans, target="result", persona_name="Daniel")
    assert "리더가 방금 말한 결과 가운데 두루뭉술한 대목 하나" in psp and "다른 사람의 반응·생각, 리더의 이유는 묻지 않는다" in psp and "'" + "몇 상자" not in psp
    class _Two:
        n = 0
        async def _generate_with_retry(self, **kw):
            _Two.n += 1
            return "그때 반장은 어떤 반응을 보였습니까?" if _Two.n == 1 else "야간조에 넘기신 물량이 하루에 몇 상자였는지 말씀해 주시겠습니까?"
    q, mode = asyncio.run(SP.render_specify(_Two(), leader_answer=ans, target="action", persona_name="Daniel"))
    assert mode == "llm_retry" and "몇 상자" in q
    class _Bad:
        async def _generate_with_retry(self, **kw):
            return "그때 반장은 어떤 반응을 보였습니까?"
    assert asyncio.run(SP.render_specify(_Bad(), leader_answer=ans, target="action", persona_name="Daniel")) == (None, "miss:off:어떤 반응") or \
        asyncio.run(SP.render_specify(_Bad(), leader_answer=ans, target="action", persona_name="Daniel"))[0] is None
    # (P14d-5) 구체화 전용 호출은 방향을 정하는 자리로 옮겼다 — 합격했을 때만 구체화 턴으로 삼고, 떨어지면 평소 방향
    assert "_specify_q_text and instruction_used == \"EPISODE_PROBE\" and chapter:" in src and "_rsp_s(llm, leader_answer=_bei_user_text" in src
    assert "_ep = dict(_ep, specificity_probe=dict(_sp_j, after_specific=_jd.get(\"specific\")))" in src      # 닫히는 턴에도 원장에 남는다
    # 4. 낱말 나열 답 — 리더가 쓴 말을 그대로 넣는다
    assert IM.role_echo_receive("Ella", "교육팀장 4명 팀원 교육기획") == "교육팀장 4명 팀원 교육기획, 알겠어요."
    assert IM.role_echo_receive("Lucas", "교육팀장 4명 팀원 교육기획.") == "교육팀장 4명 팀원 교육기획, 알겠습니다." and IM.role_echo_receive("Ella", "가" * 41) is None
    assert "_rer3(_pn_s3, request.content)" in src and '_rapport_recv("role")' not in src
    # 5. 한 문장 두 물음 — 지시문 맨 끝 한 줄 + 걸리면 본 호출 한 번 다시
    assert EC.TURN_FORMAT_RULES.rstrip().endswith("- 묻는 것은 하나다. 쉼표로 두 번째 물음을 잇지 않는다.")
    assert '_why_2.append(("two_q"' in src and '"two_questions" in _qi_2(_qs_2[0])' in src      # (P15) 두 물음과 꼬리 질문 한계를 한 번의 다시 쓰기로 — 실제로 남는 첫 문장을 본다


def test_p14c_ending_ban_streak_cap_third_honorific_and_empty_open_turn():
    """(2026-11-17 P14c) 가장 많이 쓴 끝맺음 금지 · 받는 말 연속 상한 · 제3자 높임 확인 넓힘 · 받는 말 누설 검사 · 깨진 문장 꼴 · 빈 여는 턴 수정."""
    import inspect
    import importlib.util
    import pathlib
    from diag_project.routes import diagnoses as D
    from diag_project.services import receive_render as RR, turn_checks as TC
    ans = "출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 제안했습니다. 담당자는 인력이 모자란다고 걱정했지만 동의했습니다."
    # 1. 가장 많이 쓴 끝맺음(동률이면 가장 최근 것)
    assert TC.most_used_receive_ending(["셨군요", "셨네요", "셨군요", "말씀이네요"]) == "셨군요" and TC.most_used_receive_ending(["셨군요", "셨네요"]) == "셨네요"
    assert TC.most_used_receive_ending([]) is None
    pr = RR.build_receive_prompt(leader_answer=ans, persona_name="Ella", kind="probe", avoid_endings=["셨군요"])
    assert "이번에는 끝을 -셨군요 꼴로 맺지 않는다" in pr and "그 사람을 주어로 밝혀 쓴다" in pr and "리더가 한 일처럼 읽히게 쓰지 않는다" in pr
    # 2. 연속 상한은 P15 에서 지웠다 — 꼬리 질문 턴에 받는 말이 없으니 이어질 일이 없다
    assert not hasattr(TC, "receive_streak") and not hasattr(TC, "RECEIVE_STREAK_MAX")
    src = inspect.getsource(D._submit_message_phase3a)
    assert '_rule_b = False, "cap"' not in src
    # 3. 제3자 높임 — '…셨군요', '…셨지만'도 탈락. 머리의 호칭은 모든 끝맺음에서 뗀다
    # (P14f-1) 제3자 높임 확인은 없앴다 — 높여 말해도 통과한다
    assert RR.check_receive("담당자가 인력이 모자란다고 걱정하셨지만 동의했다는 말씀이네요.", ans) == (True, "ok")
    assert RR.check_receive("담당자는 물량을 넘기는 데 동의하셨군요.", ans) == (True, "ok")
    assert RR.check_receive("야간조에 물량 삼백 상자를 넘기자고 제안하셨군요.", ans) == (True, "ok")
    assert RR.strip_lead_address("리더님은 물량을 넘기자고 하셨네요.") == "물량을 넘기자고 하셨네요." and "리더님,\\s*" in src
    # 4. 받는 말에도 엄격 누설 검사
    assert '_pre_recv_text, _tm["pre_recv"] = None, "miss:leak"' in src
    # 5. 깨진 문장 — 지시어 바로 뒤에 서술어 / 받는 말에 끝 부호 / 빈 여는 턴
    assert "fragment" in TC.question_issues("어떤 기준으로 강점을 가늠하셨는지, 그 들려주시겠어요?") and not TC.question_issues("그 뒤에 무엇을 하셨습니까?")
    spec = importlib.util.spec_from_file_location("regression_table", pathlib.Path(__file__).resolve().parent.parent / "tools" / "regression_table.py")
    rt = importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
    assert rt.classify_broken("어떤 기준으로 강점을 가늠하셨는지, 그 들려주시겠어요?") == "d" and rt.classify_broken("그 뒤에 무엇을 하셨습니까?") is None
    # (P15-2) 받는 말이 없는 전환 턴은 넘김말 + 시스템 질문으로 나간다(빈 턴이 되지 않는다)
    assert '_tm["recv_rule"] = "pass"' in src and 'clean_reply = f"{_fixed_e} {str(_bei_anchor_text).strip()}".strip()' in src
    # 6. 길이 상한 — P14c 에서 10어절로 낮췄다가 P14d 에서 12어절로 되돌렸다(test_p14d 에서 확인)
    assert RR.PROBE_CHECK_EOJEOL == 12


def test_p14d_plain_past_endings_drop_trace_and_specify_at_decision():
    """(2026-11-18 P14d) 높임 없는 과거 끝맺음 허용 · 평가 낱말 확인 · 길이 12어절 · 탈락 문장 기록 · 구체화 호출은 방향을 정하는 자리에서."""
    import asyncio
    import inspect
    import importlib.util
    import pathlib
    from diag_project.routes import diagnoses as D
    from diag_project.services import receive_render as RR, specify_render as SP, turn_checks as TC
    ans = "출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 제안했습니다. 담당자는 인력이 모자란다고 걱정했지만 동의했습니다. 창고 재고표가 새로 나왔습니다."
    # 1. 과거·완료 뒤의 '-군요/-네요/-지요/-죠'는 높임 없이도 통과 — 추측·지금 상태·상태 보고는 그대로 탈락
    for s_ok, key in (("담당자는 인력이 모자란다고 걱정했지만 동의했군요.", "했군요"), ("창고 재고표가 새로 나왔네요.", "했네요"),
                      ("담당자가 인력이 모자란다고 걱정했다는 말씀이네요.", "말씀이네요"), ("야간조에 물량 삼백 상자를 넘기자고 제안하셨군요.", "셨군요")):
        assert RR.check_receive(s_ok, ans) == (True, "ok") and TC.receive_ending_key(s_ok) == key, s_ok
    for s_bad in ("물량을 넘기기가 쉽지 않았겠군요.", "야간조 인력 걱정이 있군요.", "담당자가 동의했다는 점을 확인했습니다.", "물량을 넘기신 판단이 좋아 보입니다."):
        assert RR.check_receive(s_bad, ans)[1] == "ending", s_bad
    assert TC.past_retell_ending("그렇게 됐군요.") == "군요" and TC.past_retell_ending("그렇겠네요.") is None and TC.past_retell_ending("그 일이 있죠.") is None
    # 평가 낱말은 문장 안에 있어도 탈락(리더가 쓴 낱말이면 그대로 옮긴 것이라 통과)
    assert RR.check_receive("물량을 넘기자는 제안이 핵심이라고 짚으셨군요.", ans)[1] == "praise"
    assert RR.check_receive("물량을 넘기자는 제안이 핵심이라고 하셨군요.", ans + " 그 제안이 핵심이었습니다.") == (True, "ok")
    # 2. 지시문 — 제3자는 주어로 밝혀 쓰고 높임 없이
    pr = RR.build_receive_prompt(leader_answer=ans, persona_name="Jessica", kind="probe")
    assert "그 사람을 주어로 밝혀 쓴다" in pr and "-했군요" in pr and "주어 없이 쓴다" not in pr
    assert RR.check_receive("담당자가 물량을 넘기는 데 동의하셨군요.", ans) == (True, "ok")      # (P14f-1) 제3자 높임 확인 삭제
    # 3. 길이 상한 12어절
    assert RR.PROBE_CHECK_EOJEOL == 12
    # 4. 탈락 문장 기록
    class _Bad:
        async def _generate_with_retry(self, **kw):
            return "물량을 넘기기가 쉽지 않았겠군요."
    tr = []
    assert asyncio.run(RR.render_receive(_Bad(), leader_answer=ans, persona_name="Ella", trace=tr)) == (None, "miss:ending")
    assert tr == [["receive:probe", "ending", "물량을 넘기기가 쉽지 않았겠군요."]] * 2      # (P14e-2) 한 번 더 쓰므로 두 건
    class _BadQ:
        async def _generate_with_retry(self, **kw):
            return "그때 담당자는 어떤 반응을 보였습니까?"
    tr2 = []
    assert asyncio.run(SP.render_specify(_BadQ(), leader_answer=ans, target="result", persona_name="Daniel", trace=tr2))[0] is None and len(tr2) == 2 and tr2[0][0] == "specify"
    src = inspect.getsource(D._submit_message_phase3a)
    assert '"call_drops": (_call_drops or None)' in src and '_call_drops.append(["first_probe", _why, (_q2 or _c_fp)[:200]])' in src
    # 5. 구체화 — 방향을 정하는 자리에서 호출하고 합격했을 때만 구체화 턴. 본 호출에 맡기는 길은 없다
    i = src.index("_specify_q_text, _mode_s = await _rsp_s(")
    assert src.index("if _specify_q_text:", i) < src.index('_bei_ep["specify_now"] = _specify_slot', i)
    j = src.index('elif _specify_q_text and instruction_used == "EPISODE_PROBE" and chapter:')
    assert "generate_phase3a_interaction" not in src[j: src.index('elif instruction_used in ("EPISODE_OPEN", "SWEEP_ANCHOR") and chapter:', j)]
    # 6. 첫 꼬리 — '…궁금합니다.'는 불합격이 아니다. '…여쭤봐도 될까요?'는 그대로
    ok = TC.first_probe_question_ok
    assert ok("야간조에 직접 어떤 말을 건네셨는지 궁금합니다.", ans) == (True, "ok") and ok("직접 어떤 말을 건네셨는지 여쭤봐도 될까요?", ans) == (False, "wonder")
    # 7. 회귀 점검 — 최소 조합은 해요체 + 합쇼체
    spec = importlib.util.spec_from_file_location("regression_check", pathlib.Path(__file__).resolve().parent.parent / "tools" / "regression_check.py")
    rc = importlib.util.module_from_spec(spec); spec.loader.exec_module(rc)
    assert rc.POLITE_COACHES == {"1", "3", "5"} and rc.FORMAL_COACHES == {"2", "4"}
    st = rc.call_stats([{"role": "model", "guard": {"pre_recv": "miss:ending", "call_drops": [["receive:probe", "ending", "쉽지 않았겠군요."]]}},
                        {"role": "model", "guard": {"pre_recv": "used", "pre_recv_mode": "llm"}}])
    assert st["recv_calls"] == {"miss:ending": 1, "통과": 1} and st["call_drops"] == {"receive:probe·ending": ["쉽지 않았겠군요."]}


def test_p14e_receive_prompt_meta_retry_gate_and_transition_receive():
    """(2026-11-18 P14e) 받는 말 지시문(말투와 무관한 끝맺음·혼잣말 탈락) · 다시 쓰기(판정이 끝나기 전에만, 전환 턴은 미뤄서) · 전환 턴 받는 말 보장."""
    import asyncio
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import receive_render as RR
    ans = "출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 제안했습니다. 담당자는 인력이 모자란다고 걱정했지만 동의했습니다."
    # 1. 지시문 — 합쇼체 코치도 받는 말만은 '-군요/-네요/-지요', 말투 지시 줄은 본론 받는 말에 넣지 않는다
    pj = RR.build_receive_prompt(leader_answer=ans, persona_name="Jessica", kind="probe")
    assert "평소 말투와 무관하게 -군요, -네요, -지요 꼴로 맺는다" in pj and "평소 말투가 합쇼체여도 이 문장만은 예외" in pj and "'~요'로 끝내지 않는다" not in pj
    pe = RR.build_receive_prompt(leader_answer=ans, persona_name="Ella", kind="probe")
    assert "평소 말투가 합쇼체여도" not in pe and "가운데 하나만 골라 짧은 한 문장으로" in pe and "낱말 하나만 집어" not in pe
    assert "설명, 고쳐 쓰기, 따옴표 풀이를 덧붙이지 않는다" in pe and "지난 일은 지난 일로 쓴다" in pe
    assert "말투:" in RR.build_receive_prompt(leader_answer="나른하네", persona_name="Jessica", kind="smalltalk")      # 라포는 종전대로
    # 혼잣말·설명이 섞인 문장은 탈락
    for bad in ("담당자가 걱정했다는 말씀이군요 — no, must avoid -셨군요 ending", "가장 구체적인 낱말은 '물량'입니다.",
                "물량을 넘기자고 하셨다는 말씀이군요, 혹은 더 정확히는: 물량을 넘기기로 하신 거군요."):
        assert RR.check_receive(bad, ans)[1] == "meta", bad
    # 2. 다시 쓰기 — 떨어지면 사유를 넘겨 한 번 더 쓴다. (P15) 슬롯 판정과 함께 돌던 호출(render_receive_gated)과 미룬 다시 쓰기는 지웠다
    class _T:
        n = 0
        async def _generate_with_retry(self, **kw):
            _T.n += 1
            return "물량을 넘기기가 쉽지 않았겠군요." if _T.n == 1 else "야간조에 물량 삼백 상자를 넘기자고 제안하셨군요."
    assert asyncio.run(RR.render_receive(_T(), leader_answer=ans, persona_name="Ella")) == ("야간조에 물량 삼백 상자를 넘기자고 제안하셨군요.", "llm_retry")
    assert asyncio.run(RR.render_receive(None, leader_answer="네.", persona_name="Ella")) == (None, "skip:empty")
    assert not hasattr(RR, "render_receive_gated") and not hasattr(RR, "render_receive_retry")
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_rrg_r(" not in src and "_rrr_o(" not in src
    # 5. 전환 턴 — 통과한 받는 말은 끝에서 다시 놓는다
    assert '_tm["recv_rule"] = "C+"' in src


def test_p14f_no_third_honorific_check_transition_fixed_receive_long_retry_stem_overlap_and_self_talk():
    """(2026-11-18 P14f) 제3자 높임 확인 삭제 · 전환 턴 고정 받기 · 길이 탈락 다시 쓰기 · 낱말 겹침 어간 기준 · 혼잣말 표지."""
    import asyncio
    import inspect
    import importlib.util
    import pathlib
    from diag_project.routes import diagnoses as D
    from diag_project.services import intro_messages as IM, receive_render as RR, turn_checks as TC
    ans = "출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 제안했습니다. 담당자는 인력이 모자란다고 걱정했지만 동의했습니다."
    # 1. 제3자 높임 확인 삭제 — 높임이 리더 행동에 붙은 문장(오탐)도, 제3자를 높인 문장도 통과한다. 지시문에는 '주어로 밝혀 쓴다'만 남긴다
    assert not hasattr(RR, "_THIRD_HONORIFIC_RE") and "third_honorific" not in RR.RETRY_NOTES
    assert RR.check_receive("담당자가 걱정했지만 물량을 넘기자고 제안하셨군요.", ans) == (True, "ok")
    assert RR.check_receive("담당자가 인력이 모자란다고 걱정하셨군요.", ans) == (True, "ok")
    assert RR.check_receive("담당자가 인력이 모자란다고 걱정했군요.", ans) == (True, "ok")      # 높임 없는 끝맺음도 그대로 허용
    pr = RR.build_receive_prompt(leader_answer=ans, persona_name="Jessica", kind="probe")
    assert "그 사람을 주어로 밝혀 쓴다" in pr and "높임 어미를 붙이지 않는다" not in pr and "높임은 리더에게만" not in pr
    # 3. 길이 — 지시문에 '쉼표로 두 절을 잇지 않는다', 길이로 떨어져 다시 쓸 때는 앞 문장을 보여 주고 절 하나만 남기게 한다
    assert "쉼표로 두 절을 잇지 않는다" in pr and "가운데 하나만 골라" in pr
    assert RR.retry_note("long") == "문장이 너무 길었다 — 앞 문장의 절 하나만 남겨 9어절 이내로 쓴다" and "16어절" in RR.retry_note("long", "align")
    long_s = "출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 담당자에게 먼저 제안하셨고 담당자는 걱정했지만 결국 동의했다는 말씀이네요."
    assert RR.check_receive(long_s, ans)[1] == "long"
    seen: list[str] = []

    class _T:
        n = 0

        async def _generate_with_retry(self, **kw):
            _T.n += 1
            seen.append(kw["prompt"])
            return long_s if _T.n == 1 else "야간조에 물량 삼백 상자를 넘기자고 제안하셨군요."

    r1 = asyncio.run(RR.render_receive(_T(), leader_answer=ans, persona_name="Ella"))
    assert r1 == ("야간조에 물량 삼백 상자를 넘기자고 제안하셨군요.", "llm_retry")
    assert f"- 앞서 쓴 문장: {long_s}" in seen[1] and "절 하나만 남겨 9어절 이내로" in seen[1] and "앞서 쓴 문장:" not in seen[0]
    # 길이가 아닌 사유로 떨어졌을 때는 앞 문장을 보여 주지 않는다(베껴 쓰지 않게)
    pr_e = RR.build_receive_prompt(leader_answer=ans, persona_name="Ella", kind="probe", **{"retry_note": RR._retry_args("ending", "probe", "x")["note"],
                                                                                           "retry_prev": RR._retry_args("ending", "probe", "x")["prev"]})
    assert "앞서 쓴 문장:" not in pr_e and "앞서 쓴 문장은 쓸 수 없었다" in pr_e
    # 2. 전환 턴 넘김말 — (P15) 말투별 8종, 이번 영역에서 아직 쓰지 않은 것을 순서대로. 평가·감사 낱말 없음. 고정 문장 목록에 들어 있다
    pol, frm = IM.TRANSITION_FIXED_RECEIVE["polite"], IM.TRANSITION_FIXED_RECEIVE["formal"]
    assert len(pol) >= 3 and len(frm) >= 3 and len(set(pol + frm)) == len(pol + frm)
    assert not any(w in x for x in pol + frm for w in ("감사", "좋", "훌륭", "인상", "대단", "핵심"))
    assert all(x in IM.all_fixed_sentences() for x in pol + frm)
    assert IM.transition_fixed_receive("Ella", []) == pol[0] and IM.transition_fixed_receive("Jessica", []) == frm[0]
    assert IM.transition_fixed_receive("Lucas", []) == frm[0]                                    # Lucas 의 고정 문장은 합쇼체
    assert IM.transition_fixed_receive("Ella", [pol[0] + " 최근에 그런 일이 있었나요?"]) == pol[1]
    assert IM.transition_fixed_receive("Ella", [pol[1] + " 다음 질문", "다른 턴", pol[0] + " 앞 질문"]) == pol[2]
    assert RR.echoes_no_recall("포장 순서를 어떻게 짰는지는 기억이 안 난다고 하셨군요.") and RR.echoes_no_recall("그 숫자는 잘 모르겠다고 하셨네요.")
    assert not RR.echoes_no_recall("야간조에 물량 삼백 상자를 넘기자고 제안하셨군요.")
    src = inspect.getsource(D._submit_message_phase3a)
    assert '_tm["recv_rule"] = "pass"' in src and '_pre_recv_text, _tm["pre_recv"] = None, "miss:no_recall"' in src and '_tm["recv_out"] = "fixed"' in src
    # 4. 낱말 겹침 — 앞 두 음절을 어간 꼴로 편다(줄어든 과거형 ↔ 높임 꼴)
    for a, b in (("넘겼고", "넘기셨을"), ("바꿨습니다", "바꾸신"), ("세웠고", "세우셨을"), ("골랐습니다", "고르셨는지"), ("줄였고", "줄이신"), ("정했습니다", "정하셨을"),
                 ("넘겨야", "넘기기로"), ("바꾼", "바꾸실"), ("정해서", "정하신"), ("맡길", "맡겼습니다")):      # 연결형·관형형도 같은 열쇠
        assert TC.overlap_stem(a) == TC.overlap_stem(b), (a, b)
    assert TC.overlap_stem("순번") == TC.overlap_stem("순번을") and TC.overlap_stem("순번") != TC.overlap_stem("순서")      # 명사는 서로 그대로 맞고, 다른 낱말과 섞이지 않는다
    assert TC.overlap_stem("있었") == "있어" and TC.overlap_stem("하겠") == "하겠" and TC.overlap_stem("창고") == "창고"
    ans2 = "반장과 재고표를 다시 맞췄고 야간조 순번을 바꿨습니다."
    q2 = "재고표를 맞추시고 순번을 바꾸신 뒤, 반장에게는 무엇을 맡기셨습니까?"
    assert len(TC.question_overlap(TC.question_front_clause(q2), ans2)) >= 2
    assert TC.question_overlap("그때 무엇을 하셨습니까?", "그때 제가 직접 했습니다.") == []      # 흔한 낱말은 어간으로 펴도 세지 않는다
    # 5. 혼잣말 표지 — 첫 꼬리·구체화·받는 말 전용 호출 공통, 60자를 넘으면서 쉼표 3개 이상도 다시 쓴다
    for bad in ("리더님께서 직접 하신 조치가 맞는지 여쭤봐도 되겠느냐는 뜻이 아니라, 반장의 말을 어떻게 들으셨는지 알려 주시겠습니까?",
                "리더님께서 물량을 넘기자고 하신 것을 묻는 꼴로 쓰면, 반장에게 직접 무엇을 맡기셨습니까?"):
        assert TC.first_probe_question_ok(bad, ans)[1] == "meta", bad
        assert TC.specify_question_ok(bad)[1] == "meta", bad
    assert RR.check_receive("담당자가 동의했다는 점을 골라, 끝을 다른 꼴로 맺어 한 문장으로 말합니다.", ans)[1] == "meta"
    ramble = "리더님께서 출고가 밀렸을 때, 야간조에 물량을 넘기자고 하시면서, 반장에게 먼저 말을 꺼내셨는데, 그 자리에서 직접 어떤 조치를 취하셨습니까?"
    assert len(ramble) > TC.RAMBLE_CHARS and ramble.count(",") >= TC.RAMBLE_COMMAS and TC.is_self_talk(ramble)
    assert TC.first_probe_question_ok(ramble, ans)[1] == "meta"
    assert TC.first_probe_question_ok("야간조에 물량을 넘기자고 하셨을 때, 반장에게 직접 어떤 말을 건네셨습니까?", ans) == (True, "ok")
    assert not TC.is_self_talk("야간조에 물량 삼백 상자를 넘기자고 제안하셨군요.")
    # 회귀 점검 — 고정 받기는 (B)·(C)에 받는 말로 세고 끝맺음 분포·어절 수에는 넣지 않는다
    spec = importlib.util.spec_from_file_location("regression_check_p14f", pathlib.Path(__file__).resolve().parent.parent / "tools" / "regression_check.py")
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    rows = [{"role": "user", "content": ans},
            {"role": "model", "instr": "SWEEP_ANCHOR", "content": frm[0] + " 최근에 일정을 다시 짜신 적이 있습니까?", "guard": {"recv_out": "fixed", "recv_rule": "C-fixed"}},
            {"role": "user", "content": ans2},
            {"role": "model", "instr": "EPISODE_OPEN", "content": "순번을 바꾸셨군요. 최근에 새로 시도하신 일이 있습니까?", "guard": {"recv_out": "셨군요", "recv_rule": "C"}}]
    st = rc.receive_stats(rows)
    assert st["trans_recv_pct"] == 100.0 and len(st["trans_fixed"]) == 1 and st["recv_ends"] == {"셨군요": 1} and st["recv_top_end_pct"] == 100.0
    assert st["recv_have_pct"] == 100.0 and st["recv_avg_eojeol"] == 2.0


def test_p15_no_receive_in_tail_turns_transition_pass_first_probe_shape_and_direct_endings():
    """(2026-11-18 P15) 메아리 줄이기 — 꼬리 질문 턴에는 받는 말 없음 · 전환 턴 넘김말(되짚는 받는 말은 영역당 두 번) ·
    첫 꼬리 질문의 꼴(되짚는 앞 절 금지·명사구 하나·8~20어절) · 청하는 꼴은 사례당 한 번."""
    import inspect
    import importlib.util
    import pathlib
    from diag_project.prompts.phase3a import episode_card as EC
    from diag_project.routes import diagnoses as D
    from diag_project.services import first_probe_render as FP, intro_messages as IM, receive_render as RR, specify_render as SP, turn_checks as TC
    from diag_project.services.leak_lexicon import find_leaks, find_state_report
    from diag_project.services.output_guard import find_state_leak
    ans = "출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 반장에게 제안했습니다. 반장은 인력이 모자란다고 했습니다."
    src = inspect.getsource(D._submit_message_phase3a)
    # 1. 꼬리 질문 턴 — 받는 말 호출이 슬롯 판정 자리에 없다. 붙이는 규칙·연속 상한 없음. 본 호출이 쓴 평서문만 지운다
    i = src.index("_jd = await _judge_slots(llm, transcript=_tr")
    assert "render_receive" not in src[i - 600: i + 200] and "_rar_b(" not in src and "receive_streak" not in src
    assert not hasattr(TC, "receive_attach_rule") and not hasattr(RR, "render_receive_gated")
    assert "받는 말은 따로 붙" not in EC.TURN_FORMAT_RULES and "따로 붙습니다" not in EC.BEI_GUIDES["EPISODE_PROBE"]
    # 꼬리 질문의 아래·위 한계 — 리더 답에서 온 명사구 하나 이상, 8어절 이상 20어절 이하. 지시어만으로 가리키면 낱말 없음
    assert TC.tail_question_issue("그때 직접 하신 조치는 무엇이었습니까?", ans) == "no_noun"
    assert TC.tail_question_issue("그 결정을 하실 때 무엇을 기준으로 삼으셨습니까?", ans) == "no_noun"
    assert TC.tail_question_issue("야간조 물량은 어떻게 됐습니까?", ans) == "short"
    assert TC.tail_question_issue("야간조에 물량을 넘긴 뒤 창고 출고 일정은 실제로 어떻게 달라졌습니까?", ans) is None
    assert TC.tail_question_issue("야간조에 물량을 넘긴 뒤 " + "창고 " * 16 + "어떻게 달라졌습니까?", ans) == "long"
    assert TC.leader_nouns("반장에게 물량 이야기를 꺼내셨을 때 무엇이 달라졌습니까?", ans) == ["반장에게", "물량"]      # 서술어('꺼내셨을')·흔한 낱말은 세지 않는다
    # (판정 3) 확인 대상은 실제로 남는 첫 질문 문장 · '다시 한다면·배운 것' 질문은 리더 낱말 요건에서 뺀다
    assert '_tqi_2(_qs_2[0], _case_leader_text(_tr, _llm_user_text), need_noun=(_tm.get("ask_slot") != "reflection"))' in src and '_tm["tail_regen"] = _iss_2' in src
    assert TC.tail_question_issue("이 일을 돌아보실 때 지금이라면 다르게 해 보고 싶은 것이 있습니까?", ans, need_noun=False) is None
    assert TC.tail_question_issue("이 일을 돌아보실 때 지금이라면 다르게 해 보고 싶은 것이 있습니까?", ans) == "no_noun"
    # (판정 1) 리더 답을 옮긴 부분은 6어절 이하 — 끊기지 않고 이어진 가장 긴 구간으로 잰다
    assert TC.BORROW_MAX_EOJEOL == 6
    assert TC.borrowed_run("출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 반장에게 제안하신 뒤 무엇이 달라졌습니까?", ans) == 9
    assert TC.tail_question_issue("출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 반장에게 제안하신 뒤 무엇이 달라졌습니까?", ans) == "borrow"
    assert TC.borrowed_run("야간조에 물량을 넘기자고 하셨을 때 창고 일정은 실제로 어떻게 다시 짜셨습니까?", ans) == 3
    # (판정 5) 질문 머리의 '그럼', '다음은'
    assert TC.strip_head_filler("그럼 야간조 물량은 그 뒤에 어떻게 나누셨습니까?") == "야간조 물량은 그 뒤에 어떻게 나누셨습니까?"
    assert TC.strip_head_filler("다음은 반장과 일정을 어떻게 맞추셨습니까?") == "반장과 일정을 어떻게 맞추셨습니까?" and TC.strip_head_filler("그럼에도 하셨습니까?") == "그럼에도 하셨습니까?"
    assert "_shf_e(clean_reply)" in src
    assert "질문은 한 문장, 8어절 이상 20어절 이하로 쓴다. 리더가 한 말을 다시 쓰는 부분은 절 하나, 6어절 이하다." in EC.build_episode_card(instruction="EPISODE_PROBE", chapter="people_management",
                                                                          ep={"idx": 1, "leader_turns": 2, "slots": {}}, bei_turns=3, budget=24)
    # 2. 전환 턴 — 받는 말은 매핑과 함께, 영역당 두 번까지·직전 답이 리더 본인의 행동이나 배운 점일 때만. 그 밖은 넘김말
    assert D.TRANS_ECHO_MAX == 2 and '_asked_c in ("action", "reflection")' in src and "_echo_n_c < TRANS_ECHO_MAX" in src
    assert "_aio_c.gather(_map_c(), _recv_c(), return_exceptions=True)" in src and '_tm["recv_rule"] = "pass"' in src and '_te[chapter] = int(_te.get(chapter) or 0) + 1' in src
    for reg in ("polite", "formal"):
        pool = IM.TRANSITION_FIXED_RECEIVE[reg]
        assert len(pool) == 8 and len(set(pool)) == 8 and all(x in IM.all_fixed_sentences() for x in pool)
        for x in pool:      # 누설 낱말·상태 보고·평가 없음, 리더 말을 되짚지 않는다(리더 답과 겹치는 낱말 없음)
            assert not find_leaks(x, [], strict=True) and not find_state_report(x) and not find_state_leak(x), x
            assert not TC.content_keys(x) & TC.content_keys(ans) and not any(w in x for w in ("감사", "좋", "훌륭", "인상", "대단")), x
    pol = IM.TRANSITION_FIXED_RECEIVE["polite"]
    used: list[str] = []
    for _ in range(8):      # 영역 안에서 여덟 번까지 겹치지 않는다
        nxt = IM.transition_fixed_receive("Ella", used)
        assert not any(u.startswith(nxt) for u in used)
        used.insert(0, nxt + " 최근에 그런 일이 있으셨어요?")
    assert IM.transition_fixed_receive("Ella", used) == pol[0]                                   # 다 썼으면 가장 오래전에 쓴 것부터
    plain = [pol[i] for i in IM.TRANSITION_PASS_PLAIN]
    assert IM.transition_fixed_receive("Ella", [], plain=True) == plain[0] and not any("들었" in x for x in plain)      # 받을 내용 없는 답 뒤
    assert IM.transition_fixed_receive("Ella", [plain[0] + " 다음 질문"], plain=True) == plain[1]
    # 3. 첫 꼬리 질문 — 되짚는 앞 절 금지, 리더 낱말은 명사구 하나, 호칭으로 시작하지 않는다, 8~20어절, 순서 표지가 있으면 '순서' 각도 제외
    fp = FP.build_first_probe_prompt(leader_answer=ans, persona_name="Lucas", angle="did")
    # (판정 1·2) 앞 절 금지는 철회 — 옮기는 것은 절 하나·6어절 이하. 한 번의 호출에서 후보 둘, 걸린 후보는 쓰지 않는다
    assert "다시 쓰는 부분은 절 하나, 6어절 이하다" in fp and "앞 절로 다시 말하지 않는다" not in fp and "문장을 '리더님'으로 시작하지 않는다" in fp
    assert "8어절 이상 20어절 이하로 쓴다" in fp and "\"" not in fp.split("[규칙]")[1]                # 지시문에 따옴표로 묶은 예시 문장 없음
    assert "서로 다른 질문 두 개를 한 줄에 하나씩" in fp and "질문을 두 개 씁니다" in fp
    assert TC.first_probe_echo_issue("야간조에 물량을 넘기자고 제안하셨을 때, 반장에게 직접 어떤 말을 건네셨습니까?", ans) is None      # 앞 절이 있어도 6어절 이하면 통과
    assert TC.first_probe_echo_issue("출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 반장에게 제안하실 때 직접 어떤 말을 건네셨습니까?", ans) == "borrow"
    assert TC.first_probe_echo_issue("야간조 물량을 두고 반장에게 직접 건네신 말은 무엇이었습니까?", ans) is None
    assert TC.first_probe_echo_issue("그때 직접 건네신 말은 무엇이었습니까?", ans) == "no_noun"
    assert TC.first_probe_echo_issue("야간조에 넘기신 실제로 어떤 말씀을 하셨습니까?", ans) == "short"                       # 비문·길이 미달은 쓰지 않는다
    assert FP.split_candidates("1. 가 질문입니까?\n2) 나 질문입니까?") == ["가 질문입니까?", "나 질문입니까?"]
    assert '_tm["first_probe_pick"] = _pick_fp' in src and "for _i_fp, _c_fp in enumerate(_cands[:2], 1):" in src
    # (P15b 판정 2) 후보 확인에 기존 말투 검사 — 합쇼체 코치의 '-ㄹ래요/-어요?' 끝맺음은 탈락(Lucas 는 섞어 쓰므로 걸리지 않는다)
    from diag_project.services.persona_register import register_violations as _rv
    assert '_rv_fp(_pn_fp, _q2, scope="questions")' in src and '_ok, _why = False, "register"' in src
    assert _rv("Daniel", "반장에게 물량을 두고 직접 어떤 말을 건네셨는지 짚어 주실래요?", scope="questions") and _rv("Jessica", "야간조 물량은 어떻게 나누셨어요?", scope="questions")
    assert not _rv("Daniel", "반장에게 물량을 두고 직접 어떤 말을 건네셨습니까?", scope="questions") and not _rv("Lucas", "반장에게 직접 어떤 말을 건네셨는지 짚어 주실래요?", scope="questions")
    assert TC.strip_lead_address_q("리더님께서는 야간조 물량을 두고 무엇을 하셨습니까?") == "야간조 물량을 두고 무엇을 하셨습니까?"
    assert TC.strip_lead_address_q("물량을 넘기셨군요. 리더님이 직접 하신 말은 무엇이었나요?") == "물량을 넘기셨군요. 직접 하신 말은 무엇이었나요?"
    assert TC.strip_lead_address_q("리더님의 판단은 무엇이었나요?") == "리더님의 판단은 무엇이었나요?"
    assert not hasattr(TC, "FIRST_PROBE_SOFT_REASONS") and "_soft_fp" not in src      # 걸린 질문을 그대로 쓰던 길은 없앴다
    for txt in ("먼저 반장과 이야기했습니다.", "이후 물량을 넘겼습니다.", "그다음 일정을 다시 짰습니다.", "그 뒤 창고를 정리했습니다."):
        assert "order" in TC.first_probe_angles_in(txt) and TC.pick_first_probe_angle(txt, []) != "order", txt
    assert "order" not in TC.first_probe_angles_in("반장에게 물량을 넘기자고 제안했습니다.")
    # 4. 질문 끝맺음 — 청하는 꼴은 사례당 한 번까지, 그 뒤는 직접 묻는 꼴
    for q in ("무엇을 하셨는지 말씀해 주시겠습니까?", "어떻게 달라졌는지 들려주실 수 있을까요?", "그 일이 궁금합니다.", "순서를 여쭤봐도 되겠습니까?", "하나만 알려 주세요."):
        assert TC.is_request_ending(q), q
    for q in ("무엇을 하셨습니까?", "어떻게 달라졌나요?", "기억나세요?"):
        assert not TC.is_request_ending(q), q
    for src_q, want in (("창고 일정이 어떻게 달라졌는지 말씀해 주시겠습니까?", "창고 일정이 어떻게 달라졌습니까?"),
                        ("반장이 어떤 반응을 보였는지 들려주시겠어요?", "반장이 어떤 반응을 보였나요?"),
                        ("그 기준이 무엇인지 알려 주실 수 있을까요?", "그 기준이 무엇인가요?"),
                        ("창고에서 무엇을 보시는지 설명해 주시겠습니까?", "창고에서 무엇을 보십니까?"),
                        ("물량이 어떻게 나뉘었는지 궁금합니다.", "물량이 어떻게 나뉘었습니까?"),
                        ("일정을 어떤 순서로 짜셨는지 여쭤봐도 되겠습니까?", "일정을 어떤 순서로 짜셨습니까?")):
        assert TC.request_to_direct(src_q) == want, src_q
    assert TC.request_to_direct("그 일을 예 하나로 들어 주시겠습니까?") is None and TC.request_to_direct("무엇이 달라졌습니까?") is None
    assert "_case_request_n(_tr) >= 1" in src and '_tm["direct_fix"] = 1' in src
    card = EC.build_episode_card(instruction="EPISODE_PROBE", chapter="people_management", ep={"idx": 1, "leader_turns": 3, "slots": {}}, bei_turns=4, budget=24,
                                 used_endings=["말씀해 주시겠습니까"], direct_only=True)
    assert "직접 묻는 어미로 끝낸다" in card and "이미 여러 번 쓴 질문 끝맺음" not in card
    assert "직접 묻는 어미로 끝낸다" in SP.build_specify_prompt(leader_answer=ans, target="action", persona_name="Ella", direct_only=True)
    assert "직접 묻는 어미로 끝낸다" not in SP.build_specify_prompt(leader_answer=ans, target="action", persona_name="Ella")
    # 회귀 점검 — a 되짚는 턴(받는 말 문장·질문 앞 절) · b 꼬리 턴 받는 말 · c 청하는 꼴 · d 호칭으로 시작 · (A) 리더 낱말 없는 질문 · 전환 턴 갈래
    spec = importlib.util.spec_from_file_location("regression_check_p15", pathlib.Path(__file__).resolve().parent.parent / "tools" / "regression_check.py")
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    frm = IM.TRANSITION_FIXED_RECEIVE["formal"]
    rows = [{"role": "user", "content": ans},
            {"role": "model", "instr": "EPISODE_PROBE", "chapter": "pm", "content": "야간조에 물량을 넘기자고 제안하셨군요. 그 뒤에 무엇을 하셨습니까?", "guard": {}},
            {"role": "user", "content": ans},
            {"role": "model", "instr": "EPISODE_PROBE", "chapter": "pm", "content": "리더님께서 출고가 밀려서 야간조에 물량 삼백 상자를 넘기자고 제안하셨을 때, 반장에게 무엇을 맡기셨는지 말씀해 주시겠습니까?", "guard": {}},
            {"role": "user", "content": ans},
            {"role": "model", "instr": "EPISODE_PROBE", "chapter": "pm", "content": "야간조 물량을 두고 반장과는 그 뒤에 일정을 어떻게 다시 맞추셨습니까?", "guard": {}},
            {"role": "user", "content": ans},
            {"role": "model", "instr": "EPISODE_PROBE", "chapter": "pm", "content": "그때 무엇을 기준으로 삼으셨습니까?", "guard": {}},
            {"role": "user", "content": ans},
            {"role": "model", "instr": "SWEEP_ANCHOR", "chapter": "pm", "content": frm[0] + " 최근에 일정을 다시 짜신 적이 있습니까?", "guard": {"recv_out": "fixed", "recv_rule": "pass"}},
            {"role": "user", "content": ans},
            {"role": "model", "instr": "EPISODE_OPEN", "chapter": "pm", "content": "반장에게 물량을 넘기자고 제안하셨군요. 최근에 새로 시도하신 일이 있습니까?", "guard": {"recv_rule": "C"}}]
    st = rc.echo_stats(rows)
    assert st["echo_main_n"] == 6 and st["echo_stmt_n"] == 2 and st["echo_front_n"] == 1 and st["echo_pct"] == 50.0
    assert st["tail_recv_n"] == 1 and st["tail_n"] == 4 and st["req_tail_pct"] == 25.0 and st["lead_addr_n"] == 1
    assert st["tail_short_n"] == 2 and st["tail_len_min"] == 4 and st["ctx_bare_pct"] == 16.7 and st["ctx_bare_list"] == ["그때 무엇을 기준으로 삼으셨습니까?"]
    assert [k for k, _c, _t in st["trans2"]] == ["넘김말", "받는 말"] and st["trans_cover_pct"] == 100.0 and st["echo_trans_max"] == 1
    assert [x["nouns"][:2] for x in st["tail_rows"]][2] == ["야간조", "물량을"] and [x["borrow"] for x in st["tail_rows"]] == [0, 8, 2, 0]
    # '다시 한다면·배운 것' 질문은 리더 낱말이 없어도 (A)에 넣지 않는다 · 첫 꼬리 후보 통과 내역
    rows_r = [{"role": "user", "content": ans},
              {"role": "model", "instr": "EPISODE_PROBE", "chapter": "pm", "content": "이 일을 돌아보실 때 지금이라면 다르게 해 보고 싶은 것이 있습니까?", "guard": {"ask_slot": "reflection"}},
              {"role": "user", "content": ans},
              {"role": "model", "instr": "EPISODE_PROBE", "chapter": "pm", "content": "반장에게 물량을 두고 직접 건네신 말은 무엇이었습니까?", "guard": {"first_probe": "llm", "first_probe_pick": 2}},
              {"role": "user", "content": ans},
              {"role": "model", "instr": "SWEEP_FOLLOWUP", "chapter": "pm", "content": "거기서 직접 하신 말은 무엇이었나요?", "guard": {"first_probe": "fallback", "first_probe_pick": 0, "regen_why": []}}]
    assert rc.echo_stats(rows_r)["ctx_bare_list"] == ["거기서 직접 하신 말은 무엇이었나요?"]
    assert rc.first_probe_pick_stats(rows_r)["fp_pick"] == {"2번 통과": 1, "대체 문장": 1}
    # (P15b 판정) c) 사례당 청하는 꼴 2회 이상인 사례 수 — 전환 턴에서 사례를 끊어 센다. 다시 써서 통과한 첫 꼬리 질문
    rows_c = [{"role": "user", "content": ans},
              {"role": "model", "instr": "EPISODE_PROBE", "chapter": "pm", "content": "반장에게 물량을 두고 무엇을 맡기셨는지 말씀해 주시겠습니까?", "guard": {"first_probe": "llm_retry", "first_probe_pick": 1}},
              {"role": "user", "content": ans},
              {"role": "model", "instr": "EPISODE_PROBE", "chapter": "pm", "content": "야간조 물량이 그 뒤에 어떻게 나뉘었는지 들려주시겠습니까?", "guard": {}},
              {"role": "user", "content": ans},
              {"role": "model", "instr": "SWEEP_ANCHOR", "chapter": "pm", "content": frm[0] + " 최근에 일정을 다시 짜신 적이 있습니까?", "guard": {"recv_out": "fixed"}},
              {"role": "user", "content": ans},
              {"role": "model", "instr": "SWEEP_FOLLOWUP", "chapter": "pm", "content": "반장과 일정을 놓고 직접 하신 말씀이 무엇이었는지 알려 주시겠습니까?", "guard": {"first_probe": "llm", "first_probe_pick": 1}}]
    st_c = rc.echo_stats(rows_c)
    assert st_c["req_case_multi"] == 1 and st_c["req_case_max"] == 2 and st_c["req_tail_pct"] == 100.0
    assert rc.first_probe_pick_stats(rows_c)["fp_pick"] == {"1번 통과": 1, "다시 써서 통과": 1}
    # (P15b 판정 3) 대체 문장 — 말투마다 여섯 개 모두 직접 묻는 꼴·8어절 이상, 호칭으로 시작하지 않는다
    for coach, pairs in IM.FIRST_PROBE_FALLBACK_BY_ANGLE.items():
        for _a, t in pairs:
            assert not TC.is_request_ending(t) and len(t.split()) >= 8 and "리더님" not in t and TC.strip_lead_address_q(t) == t, (coach, t)


def test_p15b_reason_slot_direct_form_and_no_repeated_frame():
    """(2026-11-18 P15 판정 4) 이유를 묻는 슬롯 질문 — '이유를 한 줄로 말씀해 주시겠습니까' 틀 삭제, 직접 묻는 꼴, 같은 틀은 세션에 한 번."""
    from diag_project.services import slot_render as SR
    lead = ["야간조에 물량 삼백 상자를 넘기기로 정했습니다. 반장은 인력이 모자란다고 했습니다."]
    spec, example = SR._SPEC["reason"]
    assert "한 줄로" not in spec and "직접 묻는 어미" in spec and example == ""
    ok = SR.slot_sentence_ok
    assert ok("reason", "야간조에 물량을 넘기기로 정하신 이유를 한 줄로 말씀해 주시겠습니까?", lead, persona_name="Lucas")[1] == "request_ending"
    assert ok("reason", "야간조에 물량을 넘기기로 정하신 이유는 무엇이었습니까?", lead, persona_name="Lucas") == (True, "")
    used = ["반장에게 일정을 맡기신 이유는 무엇이었습니까?"]
    assert ok("reason", "야간조에 물량을 넘기기로 정하신 이유는 무엇입니까?", lead, persona_name="Lucas", used=used)[1] == "same_frame"
    assert ok("reason", "야간조에 물량을 넘기기로 하신 까닭이 어디에 있었습니까?", lead, persona_name="Lucas", used=used) == (True, "")
    assert ok("criterion", "야간조에 물량을 넘기기로 정하실 때 무엇을 기준으로 삼으셨는지 말씀해 주시겠습니까?", lead, persona_name="Jessica")[1] == "request_ending"


def test_p16_coach_v2_switch_prompts_checks_and_wrap_timing(monkeypatch):
    """(2026-11-23 P16-1) 코치 턴 새 방식 — 스위치(FM_COACH_V2) · 지시문(원칙만) · 출력 확인(말투·누설·질문 유무) · 마무리 턴을 쓰는 때."""
    import asyncio
    import inspect
    from diag_project.routes import diagnoses as D
    from diag_project.services import bei_engine as B, coach_v2 as V
    # 1. 스위치 — 기본은 꺼져 있다(운영 영향 없음). '1' 일 때만 켠다
    monkeypatch.delenv("FM_COACH_V2", raising=False)
    assert V.enabled() is False
    monkeypatch.setenv("FM_COACH_V2", "0")
    assert V.enabled() is False
    monkeypatch.setenv("FM_COACH_V2", "1")
    assert V.enabled() is True
    src = inspect.getsource(D._submit_message_phase3a)
    assert "_v2_on = _cv2.enabled()" in src and "and not _v2_on):" in src                      # 새 경로에서는 구체화 전용 호출을 부르지 않는다
    assert src.index('_v2_text, _v2_how = await _v2_render("mid", _bei_ep)') < src.index("render_first_probe as _rfp_fp")      # 종전 경로보다 먼저, 실패하면 종전 경로
    assert "_fp_final = _v2_text" in src and "and not _v2_turn):" in src                        # 겉모양 처리(평서문 삭제·청하는 꼴 변환)를 걸지 않는다
    assert 'elif _v2_on and _ep.get("wrap_asked"):' in src and "_own_c = False" in src           # 마무리 턴의 답 뒤에는 닫고 넘김말로
    # 2. 지시문 — 원칙만. 따옴표로 묶은 예시 문장 없음, 닫음 표지를 고르게 하지 않음(닫는 것은 상태 기계)
    for mode in ("mid", "wrap"):
        sysm = V.build_system(mode, "Lucas")
        assert "경험 많은 역량 면접관" in sysm and "[닫음]" not in sysm
        assert not [q for q in __import__("re").findall(r"[\"“]([^\"”]{6,})[\"”]", sysm)], mode
        assert "인상 깊" not in sysm and "분명히" not in sysm and "의미 있는" not in sysm       # 지시에 적힌 따옴표 문구를 그대로 넣지 않는다
        assert ("예·아니오로 답할 수 있는 질문은 쓰지 않는다" in sysm) == (mode == "mid") and "안쪽 낱말은 리더에게 말하지 않는다" in sysm
    mid, wrap = V.build_system("mid", "Lucas", react=True), V.build_system("wrap", "Lucas")
    assert "값을 매기는 말을 쓰지 않는다" in mid and "말로 풀어 설명하지 않는다" in mid and "팀 밖(다른 부서·전사·외부)으로 이어졌는지" in mid
    assert "코치가 하는 마지막 말" in wrap and "확실히 들었다고 단정하지 않는다" in wrap and "셋을 다 들었으면 첫째 토막만 쓰고 끝낸다" in wrap
    assert "사례의 결과나 끝" in wrap and "팀의 운영 방식이 됐는지" in wrap and "팀 밖(다른 부서·전사·외부)으로 이어졌는지" in wrap
    case = [("model", "최근에 창고 일정을 다시 짜신 적이 있습니까?"), ("user", "지난달 출고가 밀려서 야간조에 물량 삼백 상자를 넘기기로 정했습니다.")]
    user = V.build_user(chapter="work_management", sub_name="자원 및 시간관리", case=case, coach_said=["앞에서 한 말"], missing=["결과", "판단 기준"])
    assert "[자원 및 시간관리]" in user and "Lv.4: 조직 전체 자원 운영 방식" in user and "팀 밖(타 부서·다른 팀·전사·외부 기관)" in user
    assert "결과, 판단 기준" in user and "리더: 지난달 출고가 밀려서" in user and "- 앞에서 한 말" in user and "[업무분장]" not in user
    assert "[업무분장]" in V.build_user(chapter="work_management", sub_name=None, case=case, coach_said=[], missing=[])      # 하위역량을 모르면 영역 전체
    # 3. 출력 확인 — 말투·누설·(중간 턴은) 질문 유무만. 어절 수나 낱말 겹침은 보지 않는다
    lead = [case[1][1]]
    ok = lambda t, m="mid", p="Lucas": V.check(t, mode=m, persona_name=p, leader_texts=lead)      # noqa: E731
    long_q = "일정이 빠듯했겠습니다. " + "야간조에 물량을 넘기기로 정하신 뒤 " * 6 + "반장과는 그 일을 어떻게 풀어 가셨는지 들려주시겠습니까?"
    assert ok(long_q) == (True, "ok")
    assert ok("")[1] == "empty" and ok("[닫음] 더 물을 것이 없습니다.")[1] == "closed_tag"
    assert ok("야간조에 물량을 넘기신 것으로 이해했습니다.")[1] == "no_question"
    assert ok("야간조에 물량을 넘기신 것으로 이해했습니다.", "wrap") == (True, "ok")              # 마무리 턴은 확인만 해도 된다
    assert ok("야간조에 물량을 어떻게 넘기셨어요?", "mid", "Daniel")[1] == "register"              # 합쇼체 코치의 해요체 끝맺음
    assert ok("행동 쪽은 들었고 결과 쪽이 남았습니다. 그 뒤 무엇이 달라졌습니까?")[1] == "leak"
    assert V.clean('1. "야간조 물량은 그 뒤에 어떻게 나누셨습니까?"') == "야간조 물량은 그 뒤에 어떻게 나누셨습니까?"
    assert V.has_question("그렇게 이해했습니다. 그 뒤 창고에서는 무엇이 달라졌습니까?") and not V.has_question("그렇게 이해했습니다.")

    class _LLM:
        def __init__(self, outs):
            self.outs, self.calls = list(outs), []

        async def _generate_with_retry(self, **kw):
            self.calls.append(kw)
            return self.outs.pop(0)
    monkeypatch.delenv("FM_LLM_STUB", raising=False)
    kw = dict(mode="mid", chapter="work_management", sub_name="자원 및 시간관리", case=case, coach_said=[], missing=["결과"], persona_name="Lucas")
    good = "일정이 빠듯했겠습니다. 야간조에 물량을 넘긴 뒤 창고 일은 어떻게 풀려 갔는지 들려주시겠습니까?"
    llm = _LLM([good])
    assert asyncio.run(V.render(llm, **kw)) == (good, "llm")
    assert llm.calls[0]["call_type"] == "coach_v2_mid" and "model" not in llm.calls[0] and len(llm.calls) == 1      # 지금 대화 모델(Haiku) 한 번
    tr: list = []
    llm2 = _LLM(["그 일은 그렇게 이해했습니다.", good])
    assert asyncio.run(V.render(llm2, trace=tr, **kw)) == (good, "llm_retry") and tr[0][:2] == ["coach_v2:mid", "no_question"]      # 확인에서 떨어지면 한 번 다시
    assert asyncio.run(V.render(_LLM(["", ""]), **kw)) == (None, "miss:empty")                   # 두 번 다 떨어지면 None — 호출자가 종전 경로를 쓴다
    monkeypatch.setenv("FM_LLM_STUB", "1")
    assert asyncio.run(V.render(_LLM([good]), **kw)) == (None, "stub")
    # 4. 마무리 턴을 쓰는 때 — 이번 질문이 그 사례의 마지막 질문일 때(턴을 더 쓰지 않는다) · 닫으려는 사례에 턴이 남아 있을 때
    store = {"bei_turns": {"work_management": 4}}
    subs = ["업무계획 및 조직력", "자원 및 시간관리", "업무분장", "업무 개선 관리(표준화)", "디지털 활용 능력"]
    filled = {k: {"status": "filled", "quote": "x"} for k in ("context", "action")}
    ep = {"kind": "episode", "leader_turns": 3, "slots": filled}
    assert V.last_question_next(dict(ep, leader_turns=B.episode_turn_max() - 1), store, "work_management", []) is True      # 다음 답에서 턴 상한
    assert V.last_question_next(ep, store, "work_management", []) is False
    assert V.last_question_next(dict(ep, wrap_asked=1, leader_turns=5), store, "work_management", []) is False               # 이미 마무리 턴을 썼다
    near = {"bei_turns": {"work_management": B.chapter_budget("work_management") - 1}}
    assert V.last_question_next(ep, near, "work_management", []) is True                                                     # 다음 답에서 예산 소진
    assert V.last_question_next({"kind": "sweep", "leader_turns": B.SWEEP_PROMOTE_MAX_TURNS - 1, "slots": filled}, store, "work_management", []) is True
    assert V.can_extend(ep, store, "work_management", []) is True
    assert V.can_extend(dict(ep, leader_turns=B.episode_turn_max()), store, "work_management", []) is False                  # 사례 턴 상한
    assert V.can_extend(dict(ep, slots={}), store, "work_management", []) is False                                           # 찬 칸이 없으면 확인할 것이 없다
    assert V.can_extend(ep, {"bei_turns": {"work_management": B.chapter_budget("work_management")}}, "work_management", []) is False
    assert V.can_extend(ep, {"bei_turns": {"work_management": B.chapter_budget("work_management") - 2}}, "work_management", subs) is False      # 미질문 예약을 침범하지 않는다


def test_p16b_reaction_slot_tidy_question_form_and_wrap_leak(monkeypatch):
    """(2026-11-24 P16-1 판정) 반응을 붙일지는 코드가 정한다(세 턴에 한 번 이하·연속 없음) · 머리 호칭 떼기 · 값 매기는 말이 든 문장 지우기 ·
    질문 하나 · 허락 꼴/고르기/예아니오/같은 끝맺음은 한 번 다시 쓰기(턴당 합쳐 한 번) · 마무리 턴의 '아직 듣지 못한' 뜻의 말은 누설이 아니다."""
    import asyncio
    import inspect
    import json
    import re as _re
    from pathlib import Path
    from diag_project.routes import diagnoses as D
    from diag_project.services import coach_v2 as V
    # 1. 반응을 붙이는 턴 — (P16-1b) 이 사례에서 이미 나간 중간 턴 수로 센다. 첫 꼬리 질문 턴부터 두 턴에 한 번, 연달아 붙지 않는다
    allow = [V.reaction_allowed(n) for n in range(12)]
    assert allow[:4] == [True, False, True, False] and V.reaction_allowed(None) is True
    assert not any(a and b for a, b in zip(allow, allow[1:])) and sum(allow) * 2 == len(allow)
    # 2. 지시문 — 이번 턴의 꼴을 밝혀 넘긴다. 마무리 턴 지시문에는 닫는다는 낱말을 쓰지 않는다. 지시에 적힌 따옴표 문구는 넣지 않는다
    only_q, with_r, wrap = V.build_system("mid", "Lucas"), V.build_system("mid", "Lucas", react=True), V.build_system("wrap", "Lucas")
    assert "질문 한 문장만 쓴다" in only_q and "[반응]" not in only_q
    assert "반응 한 문장을 먼저 쓰고" in with_r and "열두 어절 이하 한 문장" in with_r and "리더가 쓴 낱말을 일부 써도 된다" in with_r
    assert "질문은 리더의 답을 앞 절로 되풀이하지 않고 바로 묻는다" in with_r and "앞 절로 되풀이" not in only_q      # (P16-1b) 반응이 붙는 턴에서만
    assert "마무리" not in wrap and "간추림" not in wrap and "스물다섯 어절 안팎" in wrap and "코치가 그렇게 이해했다는 말로 맺는다" in wrap
    # (P16-1b) 마무리 턴 세 토막 — 이해 확인 한 문장 · 마지막 보충 확인임을 알리는 말 · 확인 안 된 것 하나를 짧게 묻는 질문(예아니오 꼴 허용)
    assert wrap.index("[첫째 토막]") < wrap.index("[둘째 토막]") < wrap.index("[셋째 토막]") < wrap.index("[무엇을 묻는가")
    assert "그것이 마지막이라는 뜻을 짧게 알린다" in wrap and "여러 가지 늘어놓지 않는다" in wrap and "열다섯 어절 이하" in wrap
    assert "예·아니오로 답할 수 있는 꼴이어도 된다" in wrap and "둘 가운데 고르게 하지 않는다" not in wrap
    order = [wrap.index(x) for x in ("사례의 결과나 끝이 아직 나오지 않았으면", "그 방식이 팀의 운영 방식이 됐는지", "팀 밖(다른 부서·전사·외부)으로 이어졌는지")]
    assert order == sorted(order) and "기억나지 않는다고 답한 것은 건너뛴다" in wrap and "토막의 이름·번호·머리말·따옴표는 쓰지 않는다" in wrap
    for sysm in (only_q, with_r, wrap):
        assert "허락을 구하는 말로 끝내지 않는다" in sysm and "앞의 두 코치 턴과 같은 말로 끝내지 않는다" in sysm
        assert "이해했습니다" not in sysm and "보충 확인임" not in sysm
        assert "수 있을까요" not in sysm and "될까요" not in sysm and "제가 이해하기로는" not in sysm and "하셨군요" not in sysm
        assert not _re.findall(r"[\"“]([^\"”]{6,})[\"”]", sysm)
    # 3. 다듬기
    ans = "지난달 출고가 밀려서 야간조에 물량 삼백 상자를 넘기기로 정했습니다."
    td = lambda t, mode="mid", react=False: V.tidy(t, mode=mode, react=react, last_answer=ans)      # noqa: E731
    assert td("리더님, 그 뒤 창고에서는 무엇이 달라졌습니까?") == ("그 뒤 창고에서는 무엇이 달라졌습니까?", {"addr": 1, "react": 0})
    assert td("리더님이 그렇게 정하신 까닭은 무엇입니까?")[0] == "그렇게 정하신 까닭은 무엇입니까?"
    assert td("일정이 빠듯했겠습니다. 그 뒤 창고에서는 무엇이 달라졌습니까?") == ("그 뒤 창고에서는 무엇이 달라졌습니까?", {"react_cut": ["not_allowed"], "react": 0})
    assert td("일정이 빠듯했겠습니다. 그 뒤 창고에서는 무엇이 달라졌습니까?", react=True) == ("일정이 빠듯했겠습니다. 그 뒤 창고에서는 무엇이 달라졌습니까?", {"react": 1, "react_text": "일정이 빠듯했겠습니다."})
    part = "야간조에 물량을 넘기기로 하셨군요. 그 뒤 창고에서는 무엇이 달라졌습니까?"                                    # (P16-1b) 리더의 낱말을 일부 쓴 반응은 둔다(넷까지)
    assert td(part, react=True) == (part, {"react": 1, "react_text": "야간조에 물량을 넘기기로 하셨군요."})
    out, info = td("지난달 출고가 밀려 야간조에 물량 삼백 상자를 넘기셨군요. 그 뒤 창고에서는 무엇이 달라졌습니까?", react=True)      # 직전 답과 내용 낱말 다섯 이상 — 그 문장만 지운다
    assert out == "그 뒤 창고에서는 무엇이 달라졌습니까?" and info == {"react_cut": ["overlap"], "react": 0}
    long_r = "갑자기 일이 몰려서 사람도 시간도 모자란 가운데 혼자서 순서를 다시 잡아야 했던 빠듯한 한 주였겠습니다."            # 열두 어절을 넘는 반응
    assert len(long_r.split()) > V.REACT_MAX_EOJEOL and td(long_r + " 그 뒤 창고에서는 무엇이 달라졌습니까?", react=True)[1] == {"react_cut": ["long"], "react": 0}
    assert td("일정이 빠듯했겠습니다. 그 판단은 쉽지 않았겠습니다. 그 뒤 창고에서는 무엇이 달라졌습니까?", react=True)[1] == {"react_cut": ["extra"], "react": 1, "react_text": "일정이 빠듯했겠습니다."}
    # 안쪽 표지·토막 번호가 문장 머리에 나오면 뗀다
    lab = V.tidy("간추림: 야간조에 물량을 넘기기로 정하신 일로 이해했습니다. 확인 질문: 그 방식이 다른 창고로도 이어졌습니까?", mode="wrap", react=False, last_answer=ans)
    assert lab == ("야간조에 물량을 넘기기로 정하신 일로 이해했습니다. 그 방식이 다른 창고로도 이어졌습니까?", {"label": 1, "parts": "13"})
    assert V.tidy("① 야간조에 물량을 넘기기로 정하신 일로 이해했습니다.", mode="wrap", react=False, last_answer=ans)[0] == "야간조에 물량을 넘기기로 정하신 일로 이해했습니다."
    out, info = td("그 판단은 인상적입니다. 그 뒤 창고에서는 무엇이 달라졌습니까?", react=True)                          # 값 매기는 말이 든 문장
    assert out == "그 뒤 창고에서는 무엇이 달라졌습니까?" and info == {"eval_cut": 1, "react": 0}
    out, info = td("반장과는 그 일을 어떻게 풀어 가셨습니까? 그리고 그 뒤 창고에서는 무엇이 달라졌습니까?")                  # 질문은 하나
    assert out == "반장과는 그 일을 어떻게 풀어 가셨습니까?" and info == {"q_cut": 1, "react": 0}
    assert td("의미 있는 결정이었는데 그 뒤 무엇이 달라졌습니까?")[1].get("q_lost") == 1                                 # 질문이 통째로 지워지면 다시 쓴다
    w = "야간조에 물량을 넘기기로 정하신 일로 저는 이해했습니다. 다만 그 뒤 창고가 어떻게 됐는지는 아직 듣지 못했습니다. 그 뒤 창고에서는 무엇이 달라졌습니까?"
    assert td(w, mode="wrap") == (w.replace(" 다만 그 뒤 창고가 어떻게 됐는지는 아직 듣지 못했습니다.", ""), {"wrap_cut": 1, "parts": "13"})      # (P16-1c) 세 토막 밖의 문장은 지운다
    # 4. 질문 꼴 — 한 번 다시 쓰게 할 것
    qi = V.question_issue
    assert qi("그 뒤 창고가 어떻게 됐는지 들려주실 수 있을까요?", "") == "permit" and qi("그 뒤 일을 여쭤봐도 될까요?", "") == "permit"
    assert qi("그 표는 직접 만드신 것입니까, 아니면 전부터 쓰던 것입니까?", "") == "alt"
    assert qi("그 방식이 다른 창고로도 이어졌습니까?", "") == "yesno"
    assert qi("그 뒤 창고에서는 무엇이 달라졌습니까?", "반장에게는 무엇이 달라졌습니까?") == "same_end"
    assert qi("그 뒤 창고에서는 무엇이 달라졌습니까?", "반장과는 그 일을 어떻게 풀어 가셨습니까?") is None
    # (P16-1b) 끝 두 어절은 앞의 두 코치 턴과 견준다(세 턴 앞은 보지 않는다)
    assert qi("그 뒤 창고에서는 무엇이 달라졌습니까?", ["반장에게는 무엇이 달라졌습니까?", "반장과는 그 일을 어떻게 풀어 가셨습니까?"]) == "same_end"
    assert qi("그 뒤 창고에서는 무엇이 달라졌습니까?", ["반장에게는 무엇이 달라졌습니까?", "그 일은 어떻게 풀어 가셨습니까?", "그 까닭은 무엇입니까?"][-V.PREV_END_TURNS:]) is None
    # (P16-1b) 마무리 턴은 확인 질문 — 예아니오·고르기는 다시 쓰지 않는다. 허락 꼴과 같은 끝맺음은 그대로 본다
    assert qi("그 방식이 다른 창고로도 이어졌습니까?", [], mode="wrap") is None
    assert qi("그 표는 직접 만드신 것입니까, 아니면 전부터 쓰던 것입니까?", [], mode="wrap") is None
    assert qi("그 뒤 창고가 어떻게 됐는지 들려주실 수 있을까요?", [], mode="wrap") == "permit"
    assert qi("그 방식이 다른 창고로도 이어졌습니까?", ["그 틀이 다른 창고로도 이어졌습니까?"], mode="wrap") == "same_end"
    assert qi("그 일을 어떻게 그렇게 빨리 하실 수 있었습니까?", "") is None and qi("그렇게 이해했습니다.", "") is None
    assert V.end_key("무엇이 달라졌습니까? ") == "무엇이 달라졌습니까"
    # 5. 누설 — 마무리 턴은 '아직 듣지 못한 …' 뜻의 말만 봐준다. 닫는다고 알리는 말은 그대로 걸린다
    ck = lambda t, m: V.check(t, mode=m, persona_name="Lucas", leader_texts=[ans])      # noqa: E731
    unheard = "야간조에 물량을 넘기기로 정하신 일로 저는 이해했습니다. 아직 듣지 못한 것은 그 뒤의 일입니다. 그 뒤 창고에서는 무엇이 달라졌습니까?"
    assert ck(unheard, "wrap") == (True, "ok") and ck(unheard, "mid")[1] == "leak"
    assert ck("야간조에 물량을 넘기기로 정하신 일로 저는 이해했습니다. 여기서 마무리하겠습니다.", "wrap")[1] == "leak"
    # (P16-1b) 마무리 턴 — 마지막으로 하나만 더 확인한다는 말과 간추린 문장 속 '없음'은 통과. 다른 턴과 누설 사전은 그대로
    last_one = "야간조에 물량을 넘기기로 정하신 일로 이해했습니다. 마지막 질문을 드리겠습니다. 그 방식이 다른 창고로도 이어졌습니까?"
    assert ck(last_one, "wrap") == (True, "ok") and ck(last_one, "mid")[1] == "leak"
    none_word = "출고 지연 없음과 야간조 물량 조정으로 그 일을 정리하셨다고 이해했습니다. 그 방식이 다른 창고로도 이어졌습니까?"
    assert ck(none_word, "wrap") == (True, "ok") and ck(none_word, "mid")[1] == "leak"
    assert ck("그 일을 정리하셨다고 이해했습니다. 슬롯 하나가 남았습니다. 그 방식이 다른 창고로도 이어졌습니까?", "wrap")[1] == "leak"      # 사전의 다른 낱말은 그대로 걸린다
    from diag_project.services.leak_lexicon import guard_lexicon
    assert "없음" in guard_lexicon()["korean"] and len(guard_lexicon()["korean"]) == 17                                    # 사전 낱말 수는 그대로

    # 6. 다시 쓰기는 턴당 합쳐 한 번
    class _LLM:
        def __init__(self, outs):
            self.outs, self.calls = list(outs), []

        async def _generate_with_retry(self, **kw):
            self.calls.append(kw)
            return self.outs.pop(0)
    monkeypatch.delenv("FM_LLM_STUB", raising=False)
    case = [("model", "최근에 창고 일정을 다시 짜신 적이 있습니까?"), ("user", ans), ("model", "반장과는 그 일을 어떻게 풀어 가셨습니까?"), ("user", "반장과 둘이 교대표를 다시 짰습니다.")]
    kw = dict(mode="mid", chapter="work_management", sub_name="자원 및 시간관리", case=case, coach_said=["반장과는 그 일을 어떻게 풀어 가셨습니까?"], missing=["결과"], persona_name="Lucas", mid_n=1)
    permit, good = "그 뒤 창고가 어떻게 됐는지 들려주실 수 있을까요?", "그 뒤 창고에서는 무엇이 달라졌습니까?"
    llm, meta, tr = _LLM([permit, good]), {}, []
    assert asyncio.run(V.render(llm, meta=meta, trace=tr, **kw)) == (good, "llm_retry")
    assert meta == {"react_slot": 0, "rewrite": "permit", "react": 0} and tr[0][:2] == ["coach_v2:mid", "rewrite:permit"]
    assert "팀에 자리 잡았는지, 팀 밖으로 이어졌는지는 이 턴에서 묻지 않는다" in llm.calls[0]["system_instruction"]      # (P16-1c) 이 사례의 두 번째 중간 턴 — 아직 팀 쪽 물음을 고르지 않는다
    assert "[다시 쓰기]" not in llm.calls[0]["prompt"] and "[다시 쓰기] 앞서 쓴 질문은 허락을 구하는 말로 끝났다" in llm.calls[1]["prompt"]
    assert "질문 한 문장만 쓴다" in llm.calls[0]["system_instruction"]                          # 이 사례의 두 번째 중간 턴 — 반응을 붙이지 않는 턴
    llm, meta = _LLM([permit, permit, good]), {}
    assert asyncio.run(V.render(llm, meta=meta, **kw)) == (permit, "llm_retry") and meta["left"] == "permit" and len(llm.calls) == 2      # 세 번째 호출은 없다
    llm, meta = _LLM([permit, "", good]), {}
    assert asyncio.run(V.render(llm, meta=meta, **kw)) == (permit, "llm_first") and meta["left"] == "permit" and len(llm.calls) == 2      # 다시 쓴 것이 떨어지면 처음 것
    llm, meta = _LLM(["", permit, good]), {}
    assert asyncio.run(V.render(llm, meta=meta, **kw)) == (permit, "llm_retry") and meta.get("left") == "permit" and len(llm.calls) == 2  # 확인 탈락으로 이미 한 번 다시 썼다
    assert asyncio.run(V.render(_LLM(["", ""]), **kw)) == (None, "miss:empty")
    first_turn = dict(kw, case=case[:2], coach_said=[], mid_n=0)
    llm = _LLM(["일정이 빠듯했겠습니다. " + good])
    assert asyncio.run(V.render(llm, **first_turn)) == ("일정이 빠듯했겠습니다. " + good, "llm") and "반응 한 문장을 먼저 쓰고" in llm.calls[0]["system_instruction"]
    # 7. 기록 · 시뮬 재료
    src = inspect.getsource(D._submit_message_phase3a)
    assert '"v2_meta": _tm.get("v2_meta")' in src and "meta=_meta_v2" in src
    # (P16-1b) 중간 턴 순번은 사례 원장에 — 새 방식의 중간 턴이 나갔을 때만 하나 는다(다시 묻기 턴·종전 경로 턴은 세지 않는다)
    assert 'mid_n=int(ep_v2.get("v2_mid_n") or 0)' in src and '_bei_ep["v2_mid_n"] = int(_bei_ep.get("v2_mid_n") or 0) + 1' in src
    # 마무리 턴의 예아니오 질문은 다시 쓰지 않고 그대로 나간다
    wkw = dict(kw, mode="wrap", coach_said=[])
    yn = "야간조에 물량을 넘기기로 정하신 일로 이해했습니다. 마지막으로 하나만 더 확인하겠습니다. 그 방식이 다른 창고로도 이어졌습니까?"
    llm_w, meta_w = _LLM([yn, good]), {}
    assert asyncio.run(V.render(llm_w, meta=meta_w, **wkw)) == (yn, "llm") and len(llm_w.calls) == 1 and "rewrite" not in meta_w
    root = Path(__file__).resolve().parents[1]
    assert '("team_use", "그 방식이 지금 팀에서 쓰이는 모습"), ("beyond_team", "팀 밖(다른 부서·전사)으로 이어졌는지")' in (root / "tools/sim_leader.py").read_text(encoding="utf-8")
    eps = json.loads((root / "tools/sim_profiles/edu_team_lead.json").read_text(encoding="utf-8"))["episodes"]
    assert all(e.get("team_use") and e.get("beyond_team") for e in eps)
    stayed = [e["id"] for e in eps if _re.search(r"가지 않았|이어진 건 없", e["beyond_team"])]
    assert abs(len(stayed) * 2 - len(eps)) <= 1                                                # 절반은 팀 밖으로 가지 않았다


def test_p16c_one_ask_reaction_repeat_wrap_three_parts_and_team_question_timing(monkeypatch):
    """(2026-11-24 P16-1c 판정) 한 턴 한 물음(문장 하나에 물음 둘이면 다시 쓰기) · 이 영역에서 이미 나간 반응과 겹치는 반응 지우기 ·
    마무리 턴 세 토막을 코드로도 확인 · 팀의 방식/팀 밖 물음은 그 사례의 세 번째 중간 턴부터."""
    import asyncio
    import inspect
    import json
    import re as _re
    from pathlib import Path
    from diag_project.routes import diagnoses as D
    from diag_project.services import coach_v2 as V
    root = Path(__file__).resolve().parents[1]
    # 1. 한 문장 안의 두 물음
    two = V.two_asks
    assert two("그 상자는 어떤 순서로 나누셨고, 반장의 일은 어떻게 다시 맡기셨습니까?")                 # 의문사 절 둘을 이음 어미로 이음
    assert two("그 순서는 누가 정하고 어떻게 굳히셨습니까?")                                          # 쉼표 없이 이은 꼴
    assert two("그 교대표가 창고의 정해진 방식이 됐는지, 그리고 다른 창고로도 이어졌는지 말씀해 주시겠습니까?")
    assert two("반장은 그 교대표를 어떻게 받아들였고, 지금도 그대로 쓰고 있습니까?")                      # 앞쪽은 의문사, 뒤쪽은 예아니오
    assert not two("그 교대표를 어떤 근거로 짜셨는지, 그 과정을 직접 말씀해 주시겠습니까?")              # 물음 하나 + 청하는 말
    assert not two("그 뒤 무엇을 어떻게 바꾸셨는지 들려주시겠습니까?") and not two("물량을 따져 보셨고 그다음에는 무엇을 하셨습니까?")
    assert not two("그 교대표가 다른 창고에도 쓰이게 됐습니까?") and not two("")
    qi = V.question_issue
    assert qi("그 상자는 어떤 순서로 나누셨고, 반장의 일은 어떻게 다시 맡기셨습니까?", []) == "two"
    assert qi("이해했습니다. 그 교대표가 창고의 방식이 됐는지, 그리고 다른 창고로도 이어졌는지 확인하고 싶습니다만 어떻습니까?", [], mode="wrap") == "two"
    # 2. 마무리 턴의 확인 질문 — 열다섯 어절 초과 · 청하는 말/궁금하다는 말로 끝남은 다시 쓰기. 예아니오 꼴의 짧은 질문은 그대로
    long_q = "그 교대표는 반장이 처음에는 꺼렸는데도 지금까지 창고의 주간 회의에서 달마다 빠짐없이 그대로 함께 보고 있다는 것이 맞습니까?"
    assert len(long_q.split()) > V.WRAP_Q_MAX_EOJEOL and qi(long_q, [], mode="wrap") == "long" and qi(long_q, []) != "long"
    assert qi("그 교대표가 다른 창고로도 이어졌는지 궁금합니다.", [], mode="wrap") == "request"
    assert qi("그 교대표가 다른 창고로도 이어졌는지 말씀해 주시겠습니까?", [], mode="wrap") == "request"
    assert qi("그 교대표가 다른 창고로도 이어졌습니까?", [], mode="wrap") is None and qi("그 교대표가 다른 창고에도 쓰이게 됐나요?", [], mode="wrap") is None
    assert qi("그 뒤 창고 일이 어떻게 풀렸는지 들려주시겠습니까?", []) is None                         # 사례 중간 턴은 청하는 끝맺음을 다시 쓰지 않는다(종전대로)
    assert set(V.RETRY_NOTES) >= {"two", "long", "request"}
    # 3. 마무리 턴 다듬기 — 세 토막(이해 확인 · 하나만 더 확인한다는 말 · 질문)만 남긴다
    ans = "지난달 출고가 밀려서 야간조에 물량 삼백 상자를 넘기기로 정했습니다."
    tw = lambda t: V.tidy(t, mode="wrap", react=False, last_answer=ans)      # noqa: E731
    one, note, q = "야간조에 물량을 넘기기로 정하신 일로 이해했습니다.", "한 가지만 더 확인하겠습니다.", "그 교대표가 다른 창고로도 이어졌습니까?"
    assert tw(f"{one} {note} {q}") == (f"{one} {note} {q}", {"parts": "123"})
    assert tw(f"{one} 그 방식이 자리 잡았는지와 다른 창고로 이어졌는지는 아직 듣지 못했습니다. 그중 하나만 확인하겠습니다. {q}") == (f"{one} 그중 하나만 확인하겠습니다. {q}", {"wrap_cut": 1, "parts": "123"})
    assert tw(f"{one} 그 뒤 무엇을 바꾸셨는지는 잘 들었습니다. {note} {q}") == (f"{one} {note} {q}", {"wrap_cut": 1, "parts": "123"})
    assert tw(f"지난달 출고가 밀렸습니다. {one} {note} {q}") == (f"{one} {note} {q}", {"wrap_cut": 1, "parts": "123"})      # 첫째 토막은 이해했다는 말로 맺은 문장
    assert tw(f"{one} {q}") == (f"{one} {q}", {"parts": "13"})
    assert tw(f"{one} 마지막으로 하나만 확인하면, 그 교대표가 다른 창고로도 이어졌습니까?")[1] == {"parts": "123"}      # 둘째 토막이 질문 문장에 붙은 꼴
    assert tw(f"{one} 덧붙일 말은 없습니다.") == (one, {"wrap_cut": 1, "parts": "1"})                                  # 물을 것이 없으면 첫째 토막만
    # 4. 반응 되풀이 — 이 영역에서 이미 나간 반응과 내용 낱말 둘 이상 겹치면 지운다
    good = "그 뒤 창고에서는 무엇이 달라졌습니까?"
    tm = lambda t, prior: V.tidy(t, mode="mid", react=True, last_answer=ans, prior_reacts=prior)      # noqa: E731
    assert tm(f"그 무게가 느껴집니다. {good}", ["한 사람에게 쏠린 그 무게가 짐작됩니다."])[1] == {"react": 1, "react_text": "그 무게가 느껴집니다."}      # 겹치는 낱말 하나 — 둔다
    out, info = tm(f"한 사람에게 쏠린 무게가 느껴집니다. {good}", ["한 사람에게 쏠린 그 무게가 짐작됩니다."])
    assert out == good and info == {"react_cut": ["repeat"], "react": 0}
    assert tm(f"일정이 빠듯했겠습니다. {good}", ["한 사람에게 쏠린 그 무게가 짐작됩니다."])[1]["react"] == 1
    # 5. 지시문 — 물음은 하나 · 팀 쪽 물음은 세 번째 중간 턴부터 · 마무리 턴은 묻는 말로 끝냄
    assert [V.team_question_allowed(n) for n in range(4)] == [False, False, True, True]
    early, late = V.build_system("mid", "Lucas", react=True, team_q=False), V.build_system("mid", "Lucas", react=False, team_q=True)
    assert "팀에 자리 잡았는지, 팀 밖으로 이어졌는지는 이 턴에서 묻지 않는다" in early and "팀의 운영 방식이 됐는지, 팀 밖(다른 부서·전사·외부)으로 이어졌는지." not in early
    assert "그 방식이 이후 팀에 남았는지" not in early and "리더 본인의 행동·판단·결과 쪽에서 고른다" in early
    assert "팀의 운영 방식이 됐는지, 팀 밖(다른 부서·전사·외부)으로 이어졌는지." in late and "이 턴에서 묻지 않는다" not in late
    wrap = V.build_system("wrap", "Lucas")
    for sysm in (early, late, wrap):
        assert "물음은 하나다. 한 문장에 두 가지를 이어 묻지 않는다" in sysm
        assert not _re.findall(r"[\"“]([^\"”]{6,})[\"”]", sysm) and "궁금합니다" not in sysm and "잘 들었습니다" not in sysm
    assert "묻는 말로 끝낸다" in wrap and "궁금하다는 말" in wrap and "세 토막 밖의 문장은 쓰지 않는다" in wrap
    assert "이미 들은 것을 다시 확인하지 않는다" in wrap and "팀 안에서 지금 어떻게 쓰이는지를 이미 들었으면 팀 밖으로 이어졌는지를 묻는다" in wrap

    # 6. 호출 — 두 물음은 한 번 다시 쓴다(턴당 합쳐 한 번). 붙은 반응은 돌려준다. 순번에 따라 지시문이 달라진다
    class _LLM:
        def __init__(self, outs):
            self.outs, self.calls = list(outs), []

        async def _generate_with_retry(self, **kw):
            self.calls.append(kw)
            return self.outs.pop(0)
    monkeypatch.delenv("FM_LLM_STUB", raising=False)
    case = [("model", "최근에 창고 일정을 다시 짜신 적이 있습니까?"), ("user", ans)]
    kw = dict(mode="mid", chapter="work_management", sub_name="자원 및 시간관리", case=case, coach_said=[], missing=["결과"], persona_name="Lucas")
    double = "그 상자는 어떤 순서로 나누셨고, 반장의 일은 어떻게 다시 맡기셨습니까?"
    llm, meta = _LLM([double, "일정이 빠듯했겠습니다. " + good]), {}
    assert asyncio.run(V.render(llm, meta=meta, mid_n=0, **kw)) == ("일정이 빠듯했겠습니다. " + good, "llm_retry")
    assert meta["rewrite"] == "two" and meta["react_text"] == "일정이 빠듯했겠습니다." and "한 문장에 두 가지를 물었다" in llm.calls[1]["prompt"]
    assert "이 턴에서 묻지 않는다" in llm.calls[0]["system_instruction"]
    llm, meta = _LLM([double, double, good]), {}
    assert asyncio.run(V.render(llm, meta=meta, mid_n=0, **kw))[1] == "llm_retry" and meta["left"] == "two" and len(llm.calls) == 2
    llm, meta = _LLM(["한 사람에게 쏠린 무게가 느껴집니다. " + good]), {}
    assert asyncio.run(V.render(llm, meta=meta, mid_n=2, prior_reacts=["한 사람에게 쏠린 그 무게가 짐작됩니다."], **kw)) == (good, "llm")
    assert meta["react_cut"] == ["repeat"] and "이 턴에서 묻지 않는다" not in llm.calls[0]["system_instruction"]      # 세 번째 중간 턴 — 팀 쪽 물음을 고를 수 있다
    wkw = dict(kw, mode="wrap")
    wreq = f"{one} {note} 그 교대표가 다른 창고로도 이어졌는지 궁금합니다."
    llm, meta = _LLM([wreq, f"{one} 잘 들었습니다. {note} {q}"]), {}
    assert asyncio.run(V.render(llm, meta=meta, **wkw)) == (f"{one} {note} {q}", "llm_retry") and meta["rewrite"] == "request" and meta["parts"] == "123"
    # 7. 턴 핸들러 — 이 영역에서 나간 반응을 원장에 적고 다음 호출에 넘긴다
    src = inspect.getsource(D._submit_message_phase3a)
    assert 'prior_reacts=list(((session.self_assessment_data or {}).get("v2_reacts") or {}).get(chapter) or [])' in src
    assert '_sd_v2["v2_reacts"] = _rs_v2' in src and '(_tm.get("v2_meta") or {}).get("react_text")' in src
    # 8. 시뮬 준비 — 회귀 점검이 새 방식으로 돌고, 요약형 팀장 프로필에도 재료 두 줄(절반은 팀 밖으로 가지 않음)
    reg = (root / "tools/regression_check.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--v2"' in reg and 'os.environ["FM_COACH_V2"] = "1"' in reg and "def v2_report(" in reg
    for name in ("summary_team_lead.json", "edu_team_lead.json"):
        eps = json.loads((root / "tools/sim_profiles" / name).read_text(encoding="utf-8"))["episodes"]
        assert all(e.get("team_use") and e.get("beyond_team") and isinstance(e.get("beyond_kw"), list) for e in eps), name
        assert all(all(k in e["beyond_team"] for k in e["beyond_kw"]) for e in eps), name
        assert abs(sum(1 for e in eps if not e["beyond_kw"]) * 2 - len(eps)) <= 1, name

