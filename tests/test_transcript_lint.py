"""tools/transcript_lint.py 검증 — 합성 전문(JSON rows)으로 7개 집계 항목과 사전 자동 추출을 확인한다."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import transcript_lint as tl  # noqa: E402
from diag_project.data.competencies import COMPETENCY_FRAMEWORK  # noqa: E402


@pytest.fixture(scope="module")
def lex():
    return tl.build_lexicon()


def _row(t, role, content, *, chapter="organization_management", probe=None, instr="CONTINUE_NORMAL", guard=None):
    if role == "model" and guard is None:
        guard = {"t": t, "ch": chapter, "instr": instr}
    return {"t": t, "role": role, "chapter": chapter, "probe": probe, "instr": instr, "content": content, "guard": guard}


def _data(rows, coach="1"):
    return {"session": "s", "coach": coach, "rows": rows}


ORG_LIST = "· 비전 제시 및 공유\n· 전략적 사고\n· 변화관리(변화지향)\n· 혁신적 사고\n"
ALIGN_OK = ("조직관리를 '방향을 맞추는 일'이라고 하셨군요. 저희는 네 가지를 봅니다.\n"
            + ORG_LIST + "\n먼저 방향을 세우고 사람을 모으는 쪽부터 볼게요.\n\n새로운 방향에 반신반의하는 팀원들을 설득하셨던 일, 최근에 있으셨어요?")


# ── 1. 사전 자동 추출 ─────────────────────────────────────────────────────────
def test_lexicon_contains_example_internal_words(lex):
    kor = lex["korean"]
    # '가이드' 는 사다리 질문("가이드로 만드신 적")에 코치 발화로 쓰여 사전에서 빠진다(코치 어휘 우선, 2026-10-28)
    for w in ("되받기", "다리", "탐침", "턴", "사건", "태그", "지시", "반례", "오버라이드"):
        assert w in kor, f"누설 사전에 '{w}' 가 없다"
    eng = lex["english"]
    for w in ("star", "instruction", "probe"):
        assert w in eng, f"누설 사전에 '{w}' 가 없다"
    assert tl.lexicon_size(lex) >= 100


def test_lexicon_excludes_coach_speech_vocab(lex):
    kor = lex["korean"]
    # 하위역량 이름(자기인식 등)·역량 이름은 코치가 말하도록 설계된 어휘 → 사전에 없어야 한다
    for ch, fw in COMPETENCY_FRAMEWORK.items():
        assert tl.norm_sentence(fw["name"]) not in kor
        for ind in fw["indicators"].values():
            assert tl.norm_sentence(ind["name"]) not in kor, ind["name"]
    assert "자기인식" not in kor
    assert "비전" not in kor
    assert "페르소나" in kor and "페르소" not in kor   # 조사 제거가 명사를 훼손하지 않는다
    # 기능어·조사·서술어 어간은 들어오지 않는다
    for w in ("그", "리더님", "네", "은", "는", "이라", "하셨", "있었", "알겠"):
        assert w not in kor, w


def test_lexicon_dump_and_sources(lex):
    txt = tl.render_lexicon(lex)
    assert "되받기" in txt and "# 누설 사전" in txt
    assert any("layer3_state.py" in f for f in lex["sources"]["되받기"])


# ── 1. 누설 탐지 ──────────────────────────────────────────────────────────────
def test_find_lexicon_leaks_token_level(lex):
    hits = tl.find_lexicon_leaks("이번 턴에는 탐침을 하나만 하겠습니다. STAR 기준으로 보면 사건이 하나 더 필요해요.", lex)
    assert {"턴", "탐침", "STAR", "사건"} <= set(hits)
    # '리턴'·'패턴' 은 '턴' 으로 잡히지 않는다(어절 시작 기준)
    assert "턴" not in tl.find_lexicon_leaks("리턴이 빨랐고 패턴이 보였어요.", lex)
    # 리더가 먼저 쓴 말을 되받은 것은 누설이 아니다
    assert "탐침" not in tl.find_lexicon_leaks("말씀하신 탐침 장비는 어떤 것이었나요?", lex, user_tokens={"탐침"})


def test_find_state_report_patterns():
    for s in ("이 영역은 여기서 마무리하겠습니다.", "사례가 충분히 모인 것 같습니다.", "충분히 들었습니다.",
              "조건이 충족되었으니 다음으로 가겠습니다.", "좋은 사례를 들려주셨네요.", "지금까지 이야기를 정리하겠습니다."):
        assert tl.find_state_report(s), s
    assert not tl.find_state_report("그때 팀원들에게 처음 꺼낸 말이 무엇이었나요?")


def test_analyze_counts_leaks_per_turn(lex):
    rows = [_row(1, "user", "네"), _row(1, "model", "이번 턴은 반례 탐침입니다. 충분히 들었습니다. 그 뒤에는 어떻게 됐어요?")]
    r = tl.analyze(_data(rows), lex)
    assert r["leak_total"] >= 3
    assert r["leaks"][0]["t"] == 1 and "탐침" in r["leaks"][0]["words"] and r["leaks"][0]["state"]


# ── 2. ALIGN ─────────────────────────────────────────────────────────────────
def test_check_align_turn_pass_and_fail():
    ok, reasons = tl.check_align_turn(ALIGN_OK, "organization_management")
    assert ok, reasons
    # (a) 하위역량 누락
    ok, reasons = tl.check_align_turn(ALIGN_OK.replace("· 혁신적 사고\n", ""), "organization_management")
    assert not ok and any("누락" in x and "혁신적 사고" in x for x in reasons)
    # (b) 물음표 2개
    ok, reasons = tl.check_align_turn(ALIGN_OK.replace("하셨군요.", "하셨군요?"), "organization_management")
    assert not ok and any("앵커 질문 1개 아님" in x for x in reasons)
    # (c) 확인 질문으로 끝남
    bad = ALIGN_OK.rsplit("\n\n", 1)[0] + "\n\n말씀하신 결과 크게 다르지 않죠?"
    ok, reasons = tl.check_align_turn(bad, "organization_management")
    assert not ok and any("확인 질문" in x for x in reasons)


def test_analyze_align_summary(lex):
    rows = [_row(7, "user", "조직관리는 방향을 맞추는 일입니다.", instr="COMPETENCY_ALIGN"),
            _row(7, "model", ALIGN_OK, instr="COMPETENCY_ALIGN", probe="INCIDENT"),
            _row(8, "user", "네", instr="COMPETENCY_ALIGN"),
            _row(8, "model", ALIGN_OK.replace("· 전략적 사고\n", ""), instr="COMPETENCY_ALIGN")]
    r = tl.analyze(_data(rows), lex)
    assert (r["align_pass"], r["align_total"]) == (1, 2)
    assert r["align"][1]["pass"] is False


# ── 3. 질문 잘림 ──────────────────────────────────────────────────────────────
def test_truncated_question_detection(lex):
    assert tl.is_truncated_question("있었다면 어떤 일이었을까요?")
    assert tl.is_truncated_question("하셨다면 언제였습니까?")
    assert tl.is_truncated_question("이유였는지, 아니면 시점이었는지 궁금합니다.")
    assert tl.is_truncated_question("결정이었는지, 어떤 장면이었나요?")
    assert not tl.is_truncated_question("그렇다면 어떻게 하셨나요?")
    assert not tl.is_truncated_question("그 결정을 내리신 이유는 무엇이었나요?")
    rows = [_row(1, "user", "네"), _row(1, "model", "그러셨군요. 있으셨다면 어떤 일이었을까요?")]
    r = tl.analyze(_data(rows), lex)
    assert r["truncated_total"] == 1 and r["truncated"][0]["t"] == 1


# ── 4. 반복·붙여넣기 미감지 ───────────────────────────────────────────────────
def test_repeat_user_input_detection(lex):
    same = "최근 AI 플랫폼 도입 때 팀원들의 반대가 있었습니다. 파일럿으로 설득했습니다."
    rows = [_row(1, "user", same), _row(1, "model", "그러셨군요. 그때 처음 꺼낸 말은 무엇이었나요?"),
            _row(2, "user", same + " "), _row(2, "model", "그 뒤에는 어떻게 됐어요?"),                      # 미감지
            _row(3, "user", same), _row(3, "model", "앞서 말씀하신 내용과 같은 답변이네요. 다른 장면 하나만 더 여쭤볼게요. 언제였어요?")]  # 감지
    r = tl.analyze(_data(rows), lex)
    assert (r["repeat_a_cases"], r["repeat_a_missed"]) == (2, 1)
    assert r["repeat_missed"][0]["t"] == 2 and r["repeat_missed"][0]["kind"] == "a"


def test_pasted_question_detection(lex):
    q = "그 방향을 팀과 같이 앉아 구체적인 계획으로 만든 적이 있었습니까?"
    rows = [_row(1, "user", "네"), _row(1, "model", "그러셨군요. " + q),
            _row(2, "user", q), _row(2, "model", "그 뒤에는 어떻게 됐어요?"),                                # 미감지
            _row(3, "user", "다른 답"), _row(3, "model", "알겠습니다. " + q),
            _row(4, "user", q), _row(4, "model", "질문이 그대로 돌아왔네요. 리더님 쪽 이야기로 돌아가 볼게요. 언제였어요?")]  # 감지
    r = tl.analyze(_data(rows), lex)
    assert (r["repeat_b_cases"], r["repeat_b_missed"]) == (2, 1)
    assert r["repeat_missed"][0]["kind"] == "b"


# ── 5. 탐침 집계 ──────────────────────────────────────────────────────────────
def test_probe_aggregation(lex):
    g_ladder = {"ladder_probe": "2_3", "ladder_level": 2}
    g_gen = {"generalize_probe": 1}
    rows = [_row(1, "user", "a"), _row(1, "model", "그때 리더님이 직접 하신 일은 무엇입니까?", guard=g_ladder),
            _row(2, "user", "b"), _row(2, "model", "그 자리에서 직접 어떻게 하셨어요?", guard=g_gen),
            _row(3, "user", "c"), _row(3, "model", "결과는요?", chapter="people_management", guard={"generalize_probe": 1, "ch": "people_management"})]
    r = tl.analyze(_data(rows), lex)
    assert r["ladder_turns"] == 1
    assert r["generalize_turns"] == 2
    assert r["generalize_by_chapter"] == {"organization_management": 1, "people_management": 1}
    assert r["direct_q_by_target"] == {"organization_management": 2}
    assert r["direct_excess"] == 1


def test_probe_target_prefers_guard_target_over_probe_type():
    row = _row(1, "model", "x", probe="INCIDENT", guard={"target": "vision_sharing"})
    assert tl._probe_target(row) == "vision_sharing"
    row = _row(1, "model", "x", probe="INCIDENT")
    assert tl._probe_target(row) == "organization_management"   # 탐침 종류(대문자)는 타겟이 아니다 → 챕터


# ── 6. 어미 분포 ──────────────────────────────────────────────────────────────
def test_ending_distribution(lex):
    rows = [_row(1, "user", "a"), _row(1, "model", "그러셨군요. 그 뒤에는 어떻게 됐습니까?"),
            _row(2, "user", "b"), _row(2, "model", "알겠습니다. 언제였을까요?"),
            _row(3, "user", "c"), _row(3, "model", "그 판단의 기준은 무엇이었습니까?")]
    r = tl.analyze(_data(rows), lex)
    assert r["endings"] == {"습니까?": 1, "었습니까?": 1, "였을까요?": 1}
    assert tl.ending_of("들려주시겠습니까?") == "시겠습니까?"
    assert tl.ending_of("크게 다르지 않죠?") == "죠?"


# ── 7. 코치 간 동일 앵커 ──────────────────────────────────────────────────────
def test_cross_anchor_pairs_only_between_different_coaches(lex):
    def file_for(coach, align_text):
        rows = [_row(7, "user", "정의", instr="COMPETENCY_ALIGN"), _row(7, "model", align_text, instr="COMPETENCY_ALIGN")]
        return tl.analyze(_data(rows, coach=coach), lex, label=f"f{coach}")
    same = [file_for("1", ALIGN_OK), file_for("2", ALIGN_OK), file_for("1", ALIGN_OK)]   # 1·2 다름, 1·1 같은 코치 두 벌
    cross = tl.cross_anchor_pairs(same)
    assert cross["pairs"] == 1 and cross["per_coach"] == {"1": 1, "2": 1}
    diff = [file_for("1", ALIGN_OK), file_for("2", ALIGN_OK.replace("있으셨어요?", "있으셨습니까?"))]
    assert tl.cross_anchor_pairs(diff)["pairs"] == 0


# ── 출력·CLI ──────────────────────────────────────────────────────────────────
def test_render_markdown_and_cli(tmp_path, capsys, lex):
    rows = [_row(None, "model", "반갑습니다, 리더님. 성함을 어떻게 부르면 좋을까요?", chapter=None, instr="RAPPORT_BUILDING"),
            _row(7, "user", "정의", instr="COMPETENCY_ALIGN"), _row(7, "model", ALIGN_OK, instr="COMPETENCY_ALIGN")]
    f1 = tmp_path / "replay_result_x_1.json"
    f2 = tmp_path / "replay_result_x_2.json"
    f1.write_text(json.dumps(_data(rows, "1"), ensure_ascii=False), encoding="utf-8")
    f2.write_text(json.dumps(_data(rows, "2"), ensure_ascii=False), encoding="utf-8")
    out_json = tmp_path / "out.json"
    assert tl.main([str(f1), str(f2), "--json", str(out_json)]) == 0
    out = capsys.readouterr().out
    assert "| 코치 | 파일 | 누설(전체/엄격) | 8-y | ALIGN pass/total |" in out   # (2026-10-29 P1) 8-y 열 추가
    assert "| Ella(1) |" in out and "| Jessica(2) |" in out
    assert "동일 앵커 문장 쌍 합계: **1**" in out
    assert "누설 사전 크기:" in out and "상위 50개" in out
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["cross"]["pairs"] == 1 and len(payload["files"]) == 2 and payload["lexicon"]["size"] >= 100


def test_truncation_ignores_complete_first_clause_with_connective_ending():
    import sys; sys.path.insert(0, "tools")
    from transcript_lint import is_truncated_question
    assert not is_truncated_question("저라면 그 자리에서 가장 먼저 부딪혔던 반발이 무엇이었을지 궁금해지는데요, 타 부서 리더들이 보고 회의를 놓기 어려워했던 이유가 무엇이었다고 느끼셨습니까?")
    assert is_truncated_question("있었다면 어떻게 설득하셨는지 말씀해 주시겠습니까?")
    assert is_truncated_question("어려웠다면, 그때 누구와 먼저 상의하셨습니까?")
