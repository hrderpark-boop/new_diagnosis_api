"""tools/regression_table.py — 코치별 회귀 점검표 집계 검증. (2026-11-15)

가짜 sim_result(실제 서비스 문구와 겹치지 않는 창고·출고 이야기)로 지표 정의를 고정한다. LLM·DB·네트워크를 쓰지 않는다.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import regression_table as rt  # noqa: E402

REAL_FILE = "/Users/daniel/python_new/.fm_work/sim/sim_result_p12d_6.json"
CH = "organization_management"


def _m(instr, content, **guard):
    return {"role": "model", "chapter": CH, "instr": instr, "content": content, "guard": guard}


def _u(content):
    return {"role": "user", "chapter": CH, "content": content}


def make_fake(coach="5"):
    """사례 1개(꼬리 질문 3 + 다시 묻기 1) + 훑는 질문 2개(하나는 꼬리 질문, 하나는 사례 없음)."""
    rows = [
        _m("RAPPORT_BUILDING", "반갑습니다. 창고 이야기를 듣겠습니다."),
        _u("네."),
        _m("COMPETENCY_ALIGN", "창고 일을 그렇게 보시는군요.\n· 칸가\n· 칸나\n\n창고 동선을 손보신 일을 하나만 들려주세요.",
           llm=1.0, total=2.0, bei="open1", episode=1, ep_kind="episode"),
        _u("지난봄에 창고 동선이 꼬여서 출고가 자꾸 밀렸습니다."),                                  # 여는 답 — 직접 조치 없음
        _m("EPISODE_PROBE", "그때 리더님은 현장에서 무엇을 직접 하셨나요?",
           llm=1.0, total=4.0, ask_slot="action", bei="probe", episode=1, ep_kind="episode"),
        _u("제가 선반 배치도를 새로 만들어서 반장들에게 보여줬어요."),                              # 꼬리 1 — 직접 조치
        _m("EPISODE_PROBE", "배치도를 보셨군요. 교육생들은 그 배치도를 보고 어떻게 반응했나요?",
           llm=1.0, total=6.0, ask_slot="reaction", bei="probe", episode=1, ep_kind="episode"),
        _u("출고가 밀리지 않도록 했습니다."),                                                       # 꼬리 2 — 요약만
        _m("EPISODE_PROBE", "조금 더 풀어서 들려주시겠어요?", bei="reask", reask="clarify:llm", episode=1, ep_kind="episode"),
        _u("반장에게 \"오늘부터 이 순서로 싣자\"라고 말했습니다."),                                  # 꼬리 3 — 인용한 말
        _m("EPISODE_PROBE", "리더님이 그 자리에서 직접 건넨 말이 있었나요?",
           llm=1.0, total=8.0, regen_why=["guard"], bei="probe", episode=1, ep_kind="episode"),   # ask_slot 없음
        _u("네."),                                                                                 # 꼬리 4
        _m("SWEEP_ANCHOR", "그러셨군요. 창고 밖 거래처와 날짜를 맞추신 일, 떠오르는 게 있으세요?",
           regen_why=["format:no_receive", "guard"], format_miss=True, bei="sweep", closed="episode1:done", episode=1, ep_kind="sweep"),
        _u("거래처 담당자가 먼저 날짜를 바꿨어요."),                                                # 여는 답 — 제3자의 행동
        _m("SWEEP_FOLLOWUP", "그 연락을 받은 바로 그날 오후에 리더님은 배차를 놓고 어떻게 움직이셨나요?",
           ask_slot="action", bei="sweep_probe", episode=1, ep_kind="sweep"),
        _u("저는 그날 바로 배차표를 다시 짜서 기사님들께 공유했습니다."),                            # 꼬리 1 — 직접 조치
        _m("SWEEP_ANCHOR", "배차표를 다시 짜셨군요. 야간 조와 손발을 맞추신 일도 있으세요?",
           bei="sweep", closed="sweep1:sweep_done", episode=2, ep_kind="sweep"),
        _u("딱히 없습니다."),
        _m("CHAPTER_READY_TO_END", "창고 이야기는 여기까지입니다.", bei="close", closed="sweep2:no_case"),
    ]
    ledger = {
        "episodes": {CH: [
            {"kind": "episode", "idx": 1, "status": "done", "leader_turns": 4, "opener_sub": "칸가",
             "labels": [{"sub": "칸가", "strength": "strong", "quote": "선반 배치도를 새로 만들어서"},
                        {"sub": "칸나", "strength": "weak", "quote": "출고가 밀리지 않도록"}]},
            {"kind": "sweep", "idx": 1, "status": "sweep_done", "leader_turns": 2, "opener_sub": "칸다",
             "labels": [{"sub": "칸다", "strength": "strong", "quote": "배차표를 다시 짜서"}]},
            {"kind": "sweep", "idx": 2, "status": "no_case", "leader_turns": 1, "opener_sub": "칸라", "labels": []},
        ]},
        "covered": {CH: {
            "칸가": [{"episode": 1, "strength": "strong", "quote": "선반 배치도를 새로 만들어서"}],
            "칸다": [{"episode": "sweep1", "strength": "strong", "quote": "배차표를 다시 짜서 기사님들께 공유했습니다."}],
            "칸마": [{"episode": 1, "strength": "strong", "quote": "창고 동선이 꼬여서 출고가 자꾸 밀렸습니다"}],
            "칸바": [{"episode": 1, "strength": "strong", "quote": "은하수 건너편 등대지기 이야기"}],
        }},
    }
    return {"coach": coach, "turns": 9, "cost_usd": 0.0123, "rows": rows, "ledger": ledger}


@pytest.fixture()
def res():
    return rt.analyze(make_fake(), "가짜")


# ── (1) 꼬리 질문·행동 질문·제3자 질문 ──────────────────────────────────────────────────────────
def test_tail_and_reask_counts(res):
    assert res["tail_n"] == 4            # EPISODE_PROBE 3 + SWEEP_FOLLOWUP 1 (다시 묻기 제외)
    assert res["reask_n"] == 1


def test_action_question_counts_by_slot_and_by_sentence(res):
    assert res["action_slot"] == 2       # ask_slot == "action": 첫 꼬리 질문 + 훑는 질문의 꼬리
    assert res["action_sentence"] == 3   # 문장 기준: 위 둘 + ask_slot 없는 '직접 건넨 말' 질문
    assert (res["no_slot_n"], res["no_slot_action"]) == (1, 1)
    row = dict(rt.summary_rows(res))
    assert row["그중 리더 행동을 묻는 것: ask_slot 기준(문장 기준)"] == "2(3)"


def test_action_question_sentence_rule():
    assert rt.asks_leader_action("그때 리더님은 현장에서 무엇을 직접 하셨나요?")
    assert rt.asks_leader_action("리더님이 반장에게 가장 먼저 전한 말씀은 무엇이었나요?")
    assert rt.asks_leader_action("그 소식을 듣고 리더님은 어떻게 움직이셨나요?")
    assert rt.asks_leader_action("리더님은 그 말에 뭐라고 답하셨는지 들려주세요.")
    assert not rt.asks_leader_action("그때 무엇을 직접 하셨나요?")                               # '리더님' 없음(한계)
    assert not rt.asks_leader_action("리더님은 그 말을 어떻게 받아들이셨나요?")                   # 행동이 아니라 받아들임
    assert not rt.asks_leader_action("리더님은 그 순서를 어떻게 판단하셨나요?")                   # 판단
    assert not rt.asks_leader_action("리더님이 직접 실으셨다면 무엇부터 확인하셨을까요?")         # 가정
    assert not rt.asks_leader_action("리더님이 직접 실으셨군요.")                                 # 질문이 아님


def test_third_party_question(res):
    assert res["third_n"] == 1
    assert res["third_questions"] == ["교육생들은 그 배치도를 보고 어떻게 반응했나요?"]
    assert rt.asks_third_party("수강생 반응은 어땠어요?")
    assert rt.asks_third_party("그 말을 들은 참가자가 뭐라고 했는지 들려주세요.")
    assert not rt.asks_third_party("리더님은 교육생에게 무엇을 직접 건네셨나요?")                 # 리더님이 주어
    assert not rt.asks_third_party("그 상자를 다른 고객사에 보내기로 정하실 때 기준이 무엇이었나요?")   # 곳으로만 나온 낱말
    assert not rt.asks_third_party("반장들은 그 배치도를 보고 어떻게 반응했나요?")                # 목록에 없는 사람(함께 일하는 사람)
    assert not rt.asks_third_party("교육생들은 배치도를 보고 놀랐군요.")                          # 질문이 아님


# ── (1) 질문 길이 ───────────────────────────────────────────────────────────────────────────────
def test_question_length_uses_last_question_of_tail_and_reask(res):
    # 대상 5턴(꼬리 4 + 다시 묻기 1)의 마지막 질문 문장 어절 수: 6, 6, 4, 7, 11
    assert res["q_n"] == 5 and res["q_none"] == 0
    assert res["q_avg"] == pytest.approx((6 + 6 + 4 + 7 + 11) / 5)
    assert res["q_short_n"] == 4
    assert "그 연락을 받은 바로 그날 오후에 리더님은 배차를 놓고 어떻게 움직이셨나요?" not in res["q_short"]
    assert rt.last_question("배치도를 보셨군요. 교육생들은 어떻게 반응했나요?") == "교육생들은 어떻게 반응했나요?"
    assert rt.last_question("순서를 바꾸신 일을 편하게 들려주세요.") == "순서를 바꾸신 일을 편하게 들려주세요."   # 물음표 없는 요청형
    assert rt.eojeol_count("하나 둘  셋") == 3


# ── (1) 깨진 문장·조각 ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("s", [
    "그날 정한 순서는 무엇이었군요.",
    "그 창고에서 반장은 그 일을 어떻게 넘겼군요.",
    "남은 것은 어떤 상자였네요.",
])
def test_broken_a_wh_with_exclamatory_ending(s):
    assert rt.classify_broken(s) == "a"


@pytest.mark.parametrize("s", [
    "어떻게 실으면 좋을지 고민하셨군요.",          # '…지'로 안긴 절
    "왜 순서를 바꿔야 하는지는 직접 풀어 주셨군요.",
    "무엇보다 순서가 먼저였군요.",                  # 부정칭
    "반장이 왜 늦냐고 따졌군요.",                   # 인용 물음
    "'왜 이제 왔냐'고 물으셨군요.",                 # 따옴표 안
    "어떤 조짐을 보셨다는 뜻이군요.",               # 안긴 평서절
    "그 상자를 먼저 실으셨군요.",                   # 의문사 없음
    "그날 정한 순서는 무엇이었나요?",               # 정상 질문
])
def test_broken_a_exclusions(s):
    assert rt.classify_broken(s) is None


@pytest.mark.parametrize("s", [
    "언제 실었는지도 함께요.",
    "같은 선택지요.",
    "오늘 실을 상자는요?",
    "먼저 고르신 건요?",
    "떠오르는 장면 있으면요?",
    "작은 상자여도요.",
    "먼저 상자부터.",
])
def test_broken_b_fragment_without_predicate(s):
    assert rt.classify_broken(s) == "b"


@pytest.mark.parametrize("s", [
    "네.", "알겠습니다.",                           # 짧은 고정 응답
    "그 상자였나요?", "그게 맞을까요?", "그렇게 실었어요?", "어디에 두세요?", "그날이었죠?", "그 상자인가요?",
    "쉽지 않지요.", "늦게 오는 숙제지요.", "그렇게 실으셨고요.", "궁금해서요.", "마음이 가요.", "쉽지 않았을 텐데요.",
    "반갑습니다, 리더님.",                          # 호칭으로 끝남
    "창고는 세 곳입니다 — 북쪽, 남쪽, 강변.",       # 줄표 뒤 나열
    "기억나는 장면.",                               # '면'으로 끝난 명사 — 연결어미가 아니다
])
def test_broken_b_exclusions(s):
    assert rt.classify_broken(s) is None


@pytest.mark.parametrize("s", [
    "그 상자를 먼저 실으셨고,",
    "그 상자를 먼저 실으셨는데.",
    "순서를 바꾸셨지만.",
    "배치도를 다시 그리셨다면.",
    "상자가 늦게 도착하니까.",
])
def test_broken_c_comma_or_connective_ending(s):
    assert rt.classify_broken(s) == "c"


def test_broken_c_exclusions():
    assert rt.classify_broken("그렇게 하셨습니까?") is None      # 합쇼체 물음 '-습니까'
    assert rt.classify_broken("그때 바로 실으십니까?") is None   # '-ㅂ니까'
    assert rt.classify_broken("순서를 바꾸셨는데요.") is None    # '요'가 붙은 정상 종결


def test_broken_counts_in_analyze_skip_list_lines():
    d = make_fake()
    d["rows"].insert(1, _m("RAPPORT_BUILDING", "오늘 정한 순서는 무엇이었군요.\n· 칸가\n· 칸나\n\n먼저 상자부터. 그 상자를 실으셨고,"))
    r = rt.analyze(d, "가짜")
    assert {k: len(v) for k, v in r["broken"].items()} == {"a": 1, "b": 1, "c": 1}
    assert r["broken_total"] == 3
    assert "깨진 문장·조각 3개" in "\n".join(rt.render_detail(r))


# ── (1) 속 판단 노출 ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("s", [
    "여기까지 들었으니 다른 상자로 가겠습니다.",
    "이제 결과 쪽을 묻겠습니다.",
    "말씀에서는 순서 감각이 보입니다.",
    "앞의 것과 같은 장면으로 보입니다.",
    "사례 전체를 다시 훑겠습니다.",
    "이 사례는 여기서 접겠습니다.",
    "충분히 들었습니다.",
    "다 들었습니다.",
    "남은 질문은 둘입니다.",
    "다음으로 넘어가겠습니다.",
])
def test_inner_judgment_hits(s):
    assert rt.inner_judgment_hit(s) is not None


@pytest.mark.parametrize("s", [
    "그 상자를 먼저 실으셨군요.",
    "이제 '출고'입니다.",
    "소식을 전해 들었습니다.",
    "그 말은 반장에게서 들었다 들었습니다.",        # '다'가 낱말 끝 글자일 뿐
    "잘 들었습니다.",
])
def test_inner_judgment_misses(s):
    assert rt.inner_judgment_hit(s) is None


def test_inner_judgment_counted_once_per_sentence():
    d = make_fake()
    d["rows"].insert(1, _m("RAPPORT_BUILDING", "이 사례는 충분히 들었습니다. 다음으로 넘어가겠습니다."))
    r = rt.analyze(d, "가짜")
    assert len(r["inner"]) == 2


# ── (1) 원장: 사례당 턴·훑는 질문 ───────────────────────────────────────────────────────────────
def test_episode_turns_and_sweep_followups(res):
    assert res["ep_turns"] == ["조직 4"]
    assert res["close_dist"] == {"done": 1}
    assert (res["sweep_follow"], res["sweep_case"], res["sweep_total"]) == (1, 1, 2)
    d = make_fake()
    d["ledger"]["episodes"][CH].append({"kind": "episode", "idx": 2, "status": "no_case", "leader_turns": 2})
    r = rt.analyze(d, "가짜")
    assert r["ep_turns"] == ["조직 4,2(no_case)"]
    assert any("원장 사례 4개" in w for w in r["warnings"])       # 여는 턴 3개와 수가 안 맞으면 경고


# ── (1) 지연·재생성·형식미해결·말투 ─────────────────────────────────────────────────────────────
def test_percentile_nearest_rank():
    vals = list(range(1, 21))
    assert rt.percentile(vals, 0.5) == 10
    assert rt.percentile(vals, 0.95) == 19
    assert rt.percentile([3.0], 0.95) == 3.0
    assert rt.percentile([], 0.5) is None


def test_latency_uses_llm_turns_only(res):
    # guard.llm 이 있는 턴의 total: 2, 4, 6, 8 — 다시 묻기·훑는 턴(llm 없음)은 빠진다
    assert res["llm_turns"] == 4
    assert (res["p50"], res["p95"], res["max"]) == (4.0, 8.0, 8.0)


def test_regen_and_format_miss(res):
    assert res["regen_turns"] == 2
    assert res["regen_why"] == {"guard": 2, "format:no_receive": 1}
    assert res["format_miss"] == 1
    assert (res["cost_usd"], res["turns"]) == (0.0123, 9)


def test_register_cell_lucas_counts_endings_directly():
    rows = [_m("EPISODE_PROBE", "알겠습니다. 그렇게 실으셨군요.\n· 목록 줄은 빼요\n\n먼저 무엇을 하셨습니까? 그날은 어땠어요? 이쪽으로 오십시오.")]
    cell, raw = rt.register_cell("Lucas", rows)
    assert cell == "해요 2 / 합쇼 3"       # 해요: 실으셨군요·어땠어요 / 합쇼: 알겠습니다·하셨습니까·오십시오
    assert raw == {"polite": 2, "formal": 3}


def test_register_cell_other_coach_uses_register_violations():
    rows = [_m("EPISODE_PROBE", "그렇게 실으셨군요.\n· 그때 무엇을 하셨습니까?\n\n그때 무엇을 하셨습니까?")]
    cell, raw = rt.register_cell("Michael", rows)      # 해요체 코치 — 합쇼체 물음 1개(목록 줄은 빼고)
    assert cell == "1" and raw["violations"] == ["그때 무엇을 하셨습니까?"]
    assert rt.register_cell("Jessica", rows)[0] == "1"  # 합쇼체 코치 — strict 에서는 '~군요' 1개


# ── (2) '리더가 직접 한 말·조치' ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("answer", [
    "제가 선반 배치도를 새로 만들어서 반장들에게 보여줬어요.",
    "반장에게 \"오늘부터 이 순서로 싣자\"라고 말했습니다.",
    "저는 그날 바로 배차표를 다시 짜서 기사님들께 공유했습니다.",
    "야간 조를 따로 불러서 순서를 설명했어.",                      # 주어 생략
    "상자 크기별로 칸을 나누자고 제안했고, 표는 내가 직접 썼어.",
    "박반장이 늦게 왔고, 저는 그사이 출고표를 정리했습니다.",       # 제3자 주어 뒤에 1인칭 주어가 다시 나옴
])
def test_direct_action_positive(answer):
    assert rt.direct_action_evidence(answer)


@pytest.mark.parametrize("answer", [
    "출고가 밀리지 않도록 했습니다.",                              # 요약·방침만
    "매주 재고를 점검하기로 했습니다.",
    "동선을 바꾸려고 했습니다.",
    "기사님들이 헷갈리지 않게 신경 썼습니다.",
    "박반장이 \"그건 안 됩니다\"라고 했어요.",                      # 제3자의 말
    "거래처 담당자가 먼저 날짜를 바꿨어요.",                        # 제3자의 행동
    "김대리가 표를 직접 만들었어요.",                              # '직접'이 있어도 제3자 주어
    "최기사는 석 달 만에 자기 노선을 절반이나 바꿨고.",
    "박반장이 표를 들고 왔어요. 그걸 보고는 순서를 바꿨고요.",      # 주어 없는 문장은 앞 문장 주어를 이어받는다
    "처음엔 투덜대더니 표를 보고는 '제가 몰랐네요' 하더라.",        # 전하는 말
    "다시 한다면 제가 먼저 배치도를 만들었을 것 같아요.",           # 가정
    "그때 바로 설명했어야 했습니다.",                              # 후회
    "매주 표를 만들어서 공유해요.",                                # 과거 서술어 없음
    "네, 맞아요.",
    "",
])
def test_direct_action_negative(answer):
    assert rt.direct_action_evidence(answer) == []


def test_cases_split_open_and_tail_answers(res):
    by = {c["marker"]: c for c in res["cases"]}
    assert list(by) == ["episode1", "sweep1", "sweep2"]
    ep = by["episode1"]
    assert [a["kind"] for a in ep["answers"]] == ["open", "tail", "tail", "tail", "tail"]
    assert (ep["direct_open"], ep["direct_tail"], ep["direct_total"]) == (0, 2, 2)     # 꼬리 1(조치)·꼬리 3(인용한 말). 요약만 있는 꼬리 2 는 0
    assert ep["strong_subs"] == ["칸가"] and ep["opener_sub"] == "칸가" and ep["status"] == "done"
    sw = by["sweep1"]
    assert (sw["direct_open"], sw["direct_tail"]) == (0, 1)                           # 여는 답은 제3자의 행동
    assert by["sweep2"]["direct_total"] == 0 and len(by["sweep2"]["answers"]) == 1
    assert res["warnings"] == []
    text = "\n".join(rt.render_cases(res))
    assert "| 조직 | episode1 | 칸가 | 4 | done | 여는 답 0 + 꼬리 2 = 2 | 칸가 |" in text
    assert "여는 답 0 + 꼬리 1 = 1 (미달)" in text
    assert "미달: 전체 3개 중 2개 · 사례가 나온 것(no_case·repeat 제외) 2개 중 1개" in text


def test_segments_without_guard_keys_match_by_order_and_handle_reframe_and_duplicate():
    rows = [
        _m("COMPETENCY_ALIGN", "상자 쌓는 순서를 바꾸신 일을 들려주세요."),
        _u("음, 글쎄요."),
        _m("NO_CASE_REFRAME", "그러면 지게차 동선을 바꾸신 일은 어떠세요?"),
        _u("지게차 길에 노란 선을 제가 직접 붙였습니다."),            # 재질문 뒤 답 = 여는 답
        _m("EPISODE_PROBE", "그 선을 보고 기사님들은 뭐라고 했나요?"),
        _u("기사님들이 길이 헷갈리지 않는다고 했어요."),
        _m("EPISODE_PROBE", "그 뒤에는 무엇을 더 하셨나요?"),
        _u("기사님들이 길이 헷갈리지 않는다고 했어요."),              # 직전 답의 복사 — 바로 뒤 코치 턴이 같은 답 안내
        _m("INPUT_REPEATED", "앞의 답과 같습니다. 그 뒤에는 무엇을 더 하셨나요?"),
        _u("다음 날 야간 조에도 같은 선을 붙였습니다."),
        _m("EPISODE_OPEN", "야간 조까지 붙이셨군요. 납품 날짜가 겹쳤던 일도 있었나요?"),
        _u("없었습니다."),
    ]
    segs = rt.build_segments(rows)
    assert len(segs) == 2
    # 같은 답 안내를 받은 복사 답은 빠지고, 안내 뒤의 답은 직전 꼬리 질문의 답(꼬리 2번째)으로 남는다
    assert [(a["kind"], a["reframe"], a["n"]) for a in segs[0]["answers"]] == [
        ("open", False, 0), ("open", True, 0), ("tail", False, 1), ("tail", False, 2)]
    assert segs[0]["answers"][-1]["text"].startswith("다음 날 야간 조")
    ledger = {"episodes": {CH: [{"kind": "episode", "idx": 1, "status": "done", "leader_turns": 4},
                                {"kind": "episode", "idx": 2, "status": "no_case", "leader_turns": 1}]}}
    cases, warnings = rt.build_cases(rows, ledger)
    assert warnings == []
    assert (cases[0]["direct_open"], cases[0]["direct_tail"]) == (1, 1)
    assert rt.answer_label(cases[0]["answers"][1]) == "여는 답(재질문)"
    assert cases[1]["marker"] == "episode2" and cases[1]["direct_total"] == 0


# ── (3) strong 근거 인용의 출처 ─────────────────────────────────────────────────────────────────
def test_strong_quote_sources(res):
    by = {x["sub"]: x for x in res["sources"]}
    assert by["칸가"]["label"] == "꼬리 1번째 답" and by["칸가"]["marker"] == "episode1"
    assert by["칸다"]["label"] == "꼬리 1번째 답" and by["칸다"]["marker"] == "sweep1"    # 문장부호·공백 무시
    assert by["칸마"]["label"] == "여는 답"
    assert by["칸바"]["label"] == "못 찾음"
    assert res["source_summary"] == {"cells": 4, "open_only": 1, "has_tail": 2, "quotes": 4, "not_found": 1}
    text = "\n".join(rt.render_sources(res))
    assert "strong 칸 4개 중 근거가 여는 답에서만 나온 칸 1개" in text


def test_quote_source_fallbacks(res):
    by = {c["marker"]: c for c in res["cases"]}
    cases = res["cases"]
    # 의역한 인용 — 내용 어절 겹침이 가장 큰 답
    src = rt.quote_source("배차표 다시 짜서 기사님들 공유", by["sweep1"], cases)
    assert src["how"] == "overlap" and src["label"].startswith("꼬리 1번째 답(겹침 추정")
    # 그 사례 구간에는 없고 같은 영역의 다른 구간에 통째로 있는 인용
    src = rt.quote_source("거래처 담당자가 먼저 날짜를 바꿨어요", by["episode1"], cases)
    assert src == {"label": "여는 답(다른 구간 sweep1)", "kind": "open", "how": "other"}
    # '…'로 끊긴 인용 — 조각이 들어 있는 답
    src = rt.quote_source("선반 배치도를 새로 만들어서 … 반장들에게 보여줬어요", by["episode1"], cases)
    assert src["label"] == "꼬리 1번째 답" and src["how"] == "exact"
    assert rt.quote_source("", by["episode1"], cases)["label"] == "못 찾음"
    assert rt.quote_source("아무 답에도 없는 말", None, cases)["label"] == "못 찾음"


# ── 출력·실행 ───────────────────────────────────────────────────────────────────────────────────
def test_render_merges_coaches_into_one_table(tmp_path, capsys):
    p1 = tmp_path / "sim_result_fakea_5.json"
    p2 = tmp_path / "sim_result_fakeb_6.json"
    p1.write_text(json.dumps(make_fake("5"), ensure_ascii=False), encoding="utf-8")
    p2.write_text(json.dumps(make_fake("6"), ensure_ascii=False), encoding="utf-8")
    assert rt.main([str(p1), str(p2), "--detail"]) == 0
    out = capsys.readouterr().out
    assert "| 항목 | Michael(fakea) | Lucas(fakeb) |" in out
    assert "| 꼬리 질문 수(다시 묻기 제외) | 4 | 4 |" in out
    assert "| p50 / p95 / 최대(초) | 4.0 / 8.0 / 8.0 (LLM 턴 4) | 4.0 / 8.0 / 8.0 (LLM 턴 4) |" in out
    assert "| 재생성 걸린 턴 수(사유별) | 2 (guard 2 · format:no_receive 1) |" in out
    assert "| 실제 USD | 0.0123 | 0.0123 |" in out
    assert "해요 " in out and " / 합쇼 " in out                      # Lucas 열
    assert out.count("## (2) 사례별 표") == 2 and out.count("## (3) strong 근거 인용의 출처") == 2
    assert "## 상세 — Lucas(fakeb)" in out


def test_empty_and_missing_keys_do_not_raise():
    r = rt.analyze({}, "빈")
    assert r["tail_n"] == 0 and r["cases"] == [] and r["p50"] is None
    assert "## (1) 코치별 점검표" in rt.render([r], detail=True)
    r2 = rt.analyze({"coach": 6, "rows": [{"role": "model", "instr": "EPISODE_PROBE", "content": None, "guard": None}], "ledger": None}, None)
    assert r2["coach"] == "Lucas" and r2["tail_n"] == 1 and r2["q_none"] == 1


def test_real_file_runs_without_exception(capsys):
    if not os.path.exists(REAL_FILE):
        pytest.skip("실제 시뮬 결과 파일 없음")
    assert rt.main([REAL_FILE, "--detail"]) == 0
    out = capsys.readouterr().out
    assert "| 항목 | Lucas(p12d) |" in out
    assert "## (2) 사례별 표 — Lucas(p12d)" in out and "## (3) strong 근거 인용의 출처 — Lucas(p12d)" in out
