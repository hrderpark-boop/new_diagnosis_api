"""(2026-11-14 P12e) 영역 종료 요약 — 결과·인과 절, 다른 사람이 주어인 절을 절 단위로 지운다.

검토자 지시: 요약은 리더가 직접 한 일(언제·무엇을 했다)만. 결과·인과 표지로 시작하거나 이어지는 절, 다른 사람이 주어인 절은 그 절만 지우고
남은 앞 절을 말투에 맞는 종결로 맺는다. 시험 문장은 실제 시뮬 문장과 겹치지 않게 물류·출고 내용으로 새로 썼다.
"""
import asyncio
import inspect
import logging

import pytest

from diag_project.services import close_render as CR


def _drop(text, formal, people=None):
    return CR.drop_result_clauses(text, formal=formal, people=people)


# ── 시뮬에서 샌 다섯 꼴 — 문제 절만 지우고 앞 절을 맺는다 ─────────────────────────────────────────────
@pytest.mark.parametrize("text, people, polite, formal", [
    # ① 결과 표지 뒤에 다른 사람들의 행동
    ("리더님은 출고 지연 사유부터 물으셨고, 그 결과 황반장과 도주임이 야간 검수조에 먼저 손을 들었어요.", None,
     "리더님은 출고 지연 사유부터 물으셨어요.", "리더님은 출고 지연 사유부터 물으셨습니다."),
    # ② 표지 없이 이름이 주어 — 재료에서 확인된 이름(people)으로 잡는다
    ("리더님은 파손 건수를 적은 표를 들고 가셨고, 윤배차는 두 달 만에 배차표 절반을 새 양식으로 옮겼어요.", ["윤배차"],
     "리더님은 파손 건수를 적은 표를 들고 가셨어요.", "리더님은 파손 건수를 적은 표를 들고 가셨습니다."),
    # ③ '두 분이'
    ("리더님은 반품 사유를 먼저 들으셨고, 시범 3주차부터 두 분이 점검표를 먼저 써 왔습니다.", None,
     "리더님은 반품 사유를 먼저 들으셨어요.", "리더님은 반품 사유를 먼저 들으셨습니다."),
    # ④ 리더가 말하지 않은 인과(주어는 리더지만 결과 표지)
    ("리더님은 지게차 동선을 그림으로 보여주셨고, 이후 분기 점검을 먼저 맡겠다는 답을 끌어내셨습니다.", None,
     "리더님은 지게차 동선을 그림으로 보여주셨어요.", "리더님은 지게차 동선을 그림으로 보여주셨습니다."),
    # ⑤ 결과 표지 + 직함 주어
    ("리더님은 적재 기준안을 수치와 함께 가져가셨고, 그 결과 입고 담당자가 두 달 만에 검수의 절반을 스캐너로 바꾸었어요.", None,
     "리더님은 적재 기준안을 수치와 함께 가져가셨어요.", "리더님은 적재 기준안을 수치와 함께 가져가셨습니다."),
])
def test_five_leak_shapes_drop_only_the_clause(text, people, polite, formal):
    assert _drop(text, False, people) == (polite, 1)
    assert _drop(text, True, people) == (formal, 1)


def test_name_subject_needs_people_or_title():
    text = "리더님은 파손 건수를 적은 표를 들고 가셨고, 윤배차는 두 달 만에 배차표 절반을 새 양식으로 옮겼어요."
    assert _drop(text, False) == (text, 0)                     # 한계: 직함도 '님/씨'도 없는 이름은 재료에서 확인돼야 잡는다
    # 재료에서 이름 뽑기 — '○○ 씨/님' 앞 낱말, 성 + 직무가 붙은 호칭. 직함으로 끝나는 호칭·일반 낱말은 넣지 않는다
    eps = [{"context": "그때 윤배차 씨가 배차표를 손으로 쓰고 있었어요", "action": "한 대리 님께 넘기고 표운영이랑 양식을 다시 봤어요",
            "result": "고객님 문의가 줄었고 선생님도 좋아하셨어요. 기준을 정했고 고객사 정확도가 올랐어요"}]
    assert CR.people_in_material(eps) == ["윤배차", "표운영"]
    assert _drop(text, False, CR.people_in_material(eps))[1] == 1
    # 직함이 붙으면 people 없이도 잡는다
    for clause in ("구 반장은 조를 다시 짰습니다", "황반장과 도주임이 먼저 손을 들었습니다", "입고 실무자가 스캐너를 맡았습니다", "팀원들이 먼저 표를 채웠습니다",
                   "허지안 씨가 야간조를 맡았습니다", "배 선임 님이 검수를 넘겨받았습니다", "세 사람이 번갈아 점검했습니다", "그분도 표를 따라 썼습니다",
                   "민책임은 예산을 다시 냈습니다", "두 분 모두 먼저 나섰습니다"):
        out, n = _drop(f"리더님은 하역 순서를 다시 정하셨고, {clause}.", True)
        assert (out, n) == ("리더님은 하역 순서를 다시 정하셨습니다.", 1), clause


# ── 사물 주어·시간 부사·안긴 절은 남는다 ──────────────────────────────────────────────────────────
def test_thing_subject_stays_without_marker_and_goes_with_marker():
    kept = "리더님은 검수 순서를 바꾸셨고, 상차 대기가 나흘에서 이틀로 줄었습니다."
    assert _drop(kept, True) == (kept, 0)                      # 표지 없는 사물 주어 절은 이번 지시의 대상이 아니다
    assert _drop("리더님은 검수 순서를 바꾸셨고, 그 결과 상차 대기가 나흘에서 이틀로 줄었습니다.", True) == ("리더님은 검수 순서를 바꾸셨습니다.", 1)
    for s in ("리더님은 안전 교안을 고치셨고, 일정이 이틀 당겨졌어요.", "리더님은 설문지를 돌리셨고, 만족도가 조금 올랐어요.",
              "리더님은 주차장이 좁아 하역 동선을 바꾸셨어요.", "리더님은 날씨가 궂은 날에도 야간 점검을 도셨어요.",
              "리더님은 누가 책임이 있는지 따지지 않으셨고, 재고표부터 맞추셨어요."):
        assert _drop(s, False) == (s, 0), s


def test_time_adverb_inside_leader_clause_stays():
    for s in ("리더님은 입고 면담 이후 검수표를 다시 짜셨고, 야간조에도 같은 표를 돌리셨습니다.",
              "리더님은 3월 재고 실사 이후에 창고 구역을 다시 나누셨습니다.",
              "리더님은 그 결과를 벽에 붙이셨고, 주마다 숫자를 고쳐 적으셨습니다."):       # '그 결과를'은 목적어 — 표지가 아니다
        assert _drop(s, True) == (s, 0), s


def test_embedded_other_subject_with_honorific_predicate_stays():
    # 서술어가 높임꼴이면 리더 행동 절로 본다 — '구 반장이 올린'은 안긴 절의 주어
    s = "리더님은 조 편성을 다시 보셨고, 구 반장이 올린 표를 직접 고치셨습니다."
    assert _drop(s, True) == (s, 0)
    # '님'으로 높인 다른 사람은 서술어가 높임꼴이어도 지운다 — 절만 지워 리더가 한 일은 남긴다
    assert _drop("리더님은 증차 안을 올리셨고, 대표님은 그 자리에서 승인하셨습니다.", True) == ("리더님은 증차 안을 올리셨습니다.", 1)
    assert _drop("리더님은 증차 안을 올리셨고, 두 분께서 먼저 서명하셨어요.", False) == ("리더님은 증차 안을 올리셨어요.", 1)
    assert _drop("리더님은 증차 안을 올리셨고, 두 분이 야간조에 직접 자원하셨습니다.", True) == ("리더님은 증차 안을 올리셨습니다.", 1)      # '분'은 서술어가 높임꼴이어도 지운다
    # 단 '분'·'께서' 뒤에 안긴 꼴(…ㄹ 때, …수 있, …다고 보셨)이 있고 서술어가 높임꼴이면 리더 행동 절이다
    for s in ("리더님은 조를 한꺼번에 바꾸면 두 분이 그만둘 수 있다고 보셨고, 한 조씩 나눠 옮기셨습니다.",
              "증차를 서두르면 두 분이 버티기 어렵다고 판단하셨고, 석 달로 나눠 올리셨습니다.",
              "허 주임께서 사흘 안에 되겠냐고 되물으셨을 때도 적재표를 문서로 내어 답하셨습니다.",
              "지난달 문 주임과 탁 사원이 하역 순서로 부딪혔을 때 리더께서는 두 사람을 따로 불러 들으셨습니다.",
              "본인이 첫 야간 점검을 직접 도셨습니다."):
        assert _drop(s, True) == (s, 0), s
    assert _drop("리더님은 적재표를 문서로 남기셨고, 본인이 다음 점검을 맡겠다고 나섰습니다.", True) == ("리더님은 적재표를 문서로 남기셨습니다.", 1)


# ── 절 나누기·맺기 ──────────────────────────────────────────────────────────────────────────────
def test_split_and_close_variants():
    assert _drop("리더님은 상차 순서를 직접 바꾸셨고 그 결과 대기 줄이 짧아졌어요.", False) == ("리더님은 상차 순서를 직접 바꾸셨어요.", 1)       # 쉼표 없음
    assert _drop("리더님은 송장 양식을 새로 만드셨으며, 덕분에 오배송이 줄었습니다.", True) == ("리더님은 송장 양식을 새로 만드셨습니다.", 1)
    assert _drop("리더님은 팰릿 수를 손으로 세어 적었고, 그 뒤로 재고 차이가 사라졌습니다.", True) == ("리더님은 팰릿 수를 손으로 세어 적었습니다.", 1)
    assert _drop("리더님은 상차표를 직접 보시며, 그 덕분에 지연이 줄었습니다.", False) == ("리더님은 상차표를 직접 보셨어요.", 1)             # 높임 '시' + 며
    assert _drop("리더님은 하역 분담표를 다시 짜셨는데 그 뒤로 야간조가 조용해졌습니다.", True) == ("리더님은 하역 분담표를 다시 짜셨습니다.", 1)   # ㅆ 받침 + 는데
    assert _drop("리더님은 반송 건을 하나씩 확인하셨고, 그 일이 야간조의 자원으로 이어졌습니다.", True) == ("리더님은 반송 건을 하나씩 확인하셨습니다.", 1)
    # 가운데 절만 지우면 맺을 필요가 없다 — 앞뒤 절을 그대로 잇는다
    assert _drop("리더님은 조 편성표를 새로 그리셨고, 그 뒤 구 반장이 조를 다시 짰고, 주간 점검표도 직접 만드셨습니다.", True) == (
        "리더님은 조 편성표를 새로 그리셨고, 주간 점검표도 직접 만드셨습니다.", 1)
    # 지운 절에 이어지는 절은 리더 행동으로 돌아오기 전까지 같이 지운다
    out, info = CR.drop_result_clauses_detail("리더님은 하역 순서를 먼저 정하셨고, 덕분에 두 사람이 먼저 나섰고, 오출고도 절반으로 줄었습니다.", formal=True)
    assert out == "리더님은 하역 순서를 먼저 정하셨습니다." and info["clauses"] == 2 and info["reasons"] == ["marker_head", "follows"]


def test_first_clause_hit_drops_sentence_and_all_hit_returns_empty():
    out, info = CR.drop_result_clauses_detail("리더님은 적재표를 고치셨습니다. 이후 야간조 두 분이 점검을 나눠 맡았습니다.", formal=True)
    assert out == "리더님은 적재표를 고치셨습니다." and info["sentences"] == 1 and info["unsafe"] == 0
    # 첫 절이 걸려도 뒤에 '리더님' 주어로 새로 시작하는 절이 있으면 거기서부터 남긴다 — 없으면 문장 전체
    assert _drop("윤 주임은 스캐너를 먼저 익혔고, 리더님은 그 표를 받으셨습니다.", True) == ("리더님은 그 표를 받으셨습니다.", 1)
    assert _drop("윤 주임은 스캐너를 먼저 익혔고, 그 표도 직접 받으셨습니다. 리더님은 적재표를 고치셨습니다.", True)[0] == "리더님은 적재표를 고치셨습니다."
    assert _drop("윤 주임 님이 스캐너를 익혔고, 탁 사원이 표를 채운 것은 리더님이 길러 둔 힘으로 보입니다.", True)[0] == ""      # 절 머리가 리더님이 아니면 문장 전체
    assert _drop("리더님은 그 결과 반품 창구를 하나로 줄이셨습니다.", True)[0] == ""            # '리더님은' 바로 뒤의 표지도 절 머리로 본다
    out, info = CR.drop_result_clauses_detail("그 결과 오출고가 절반으로 줄었어요. 덕분에 야간조가 먼저 움직였어요.", formal=False)
    assert out == "" and info["sentences"] == 2
    assert _drop("", True) == ("", 0) and _drop(None, False) == ("", 0)


def test_unclosable_clause_keeps_original():
    for s in ("리더님은 적재표를 고치신 뒤, 그 결과 오출고가 절반으로 줄었습니다.",
              "리더님은 창고를 돌면서, 두 분이 재고를 다시 셌습니다.",
              "리더님은 상차 순서를 바꾸려고, 덕분에 대기가 줄었습니다."):
        out, info = CR.drop_result_clauses_detail(s, formal=True)
        assert out == s and info == {"clauses": 0, "sentences": 0, "unsafe": 1, "reasons": []}, s
        assert _drop(s, True) == (s, 0)


def test_unchanged_text_is_returned_as_is():
    s = "리더님은 3월에 재고 실사표를 직접 만드셨습니다.  리더님은 야간조 인수인계를 표로 바꾸셨습니다."
    assert _drop(s, True) == (s, 0)                            # 손댈 것이 없으면 공백까지 원문 그대로


# ── 기존 문장 단위 삭제는 그대로 ────────────────────────────────────────────────────────────────
def test_drop_non_leader_subject_unchanged():
    out, n = CR.drop_non_leader_subject("전무님은 입고 마감을 이틀 당기라고 하셨습니다. 리더님은 하역 순서를 바꾸셨습니다. 문 주임 님이 새벽 하역을 맡았습니다.")
    assert (out, n) == ("리더님은 하역 순서를 바꾸셨습니다.", 2)
    s = "리더님은 문 주임 님께 하역표를 넘기셨습니다. 그 결과 입고가 하루 빨라졌습니다."
    assert CR.drop_non_leader_subject(s) == (s, 0)             # 받는 사람으로 나온 이름은 주어가 아니다 · 결과 문장은 이 함수의 몫이 아니다
    assert CR.drop_non_leader_subject("문 주임이 새벽 하역을 맡았습니다.")[1] == 0            # '○○ 님' 꼴만 본다(직함만 있는 주어는 절 삭제의 몫)
    assert CR.drop_non_leader_subject(None) == ("", 0)


# ── render_close_summary — 프롬프트와 적용 순서 ─────────────────────────────────────────────────
class _FakeLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    async def _generate_with_retry(self, *, prompt, **kw):
        self.prompts.append(prompt)
        return self.outputs.pop(0) if self.outputs else ""


_EPS = [
    {"context": "작년 가을에 출고 지연이 잦았어요", "action": "출고 지연 사유부터 반장들에게 물었어요", "result": "황반장이랑 도주임이 야간 검수조에 먼저 손을 들었어요"},
    {"context": "윤배차 씨가 배차표를 손으로 쓰고 있었어요", "action": "파손 건수를 적은 표를 들고 갔어요", "result": "두 달 만에 배차표 절반을 새 양식으로 옮겼어요"},
]
_LEAKY = ("리더님은 출고 지연 사유부터 반장들에게 물으셨고, 그 결과 황반장과 도주임이 야간 검수조에 먼저 손을 들었어요. "
          "리더님은 파손 건수를 적은 표를 들고 가셨고, 윤배차는 두 달 만에 배차표 절반을 새 양식으로 옮겼어요.")


def test_render_close_summary_drops_clauses_by_register_and_logs(caplog):
    caplog.set_level(logging.INFO, logger="diag_project.services.close_render")
    llm = _FakeLLM([_LEAKY])
    out, n = asyncio.run(CR.render_close_summary(llm, episodes=_EPS, persona_name="Olivia"))
    assert out == "리더님은 출고 지연 사유부터 반장들에게 물으셨어요. 리더님은 파손 건수를 적은 표를 들고 가셨어요."
    assert n == 2 and len(llm.prompts) == 1                    # 반환 꼴 (요약, 되짚은 사례 수)는 그대로
    logs = [r.getMessage() for r in caplog.records if "close_summary_clause_drop" in r.getMessage()]
    assert logs and "clauses=2" in logs[0] and "unsafe=0" in logs[0] and "marker_head,other_subject" in logs[0]
    llm2 = _FakeLLM([_LEAKY])
    out2, _ = asyncio.run(CR.render_close_summary(llm2, episodes=_EPS, persona_name="Jessica"))
    assert out2 == "리더님은 출고 지연 사유부터 반장들에게 물으셨습니다. 리더님은 파손 건수를 적은 표를 들고 가셨습니다."


def test_render_close_summary_clause_drop_runs_before_sentence_drop():
    # 문장 단위 삭제가 먼저면 첫 문장이 통째로 사라진다 — 절 삭제가 먼저라 리더가 한 일은 남는다
    llm = _FakeLLM(["리더님은 출고 지연 사유부터 반장들에게 물으셨고, 전무님은 그 자리에서 증차를 승인하셨습니다. 리더님은 파손 건수를 적은 표를 들고 가셨습니다."])
    out, n = asyncio.run(CR.render_close_summary(llm, episodes=_EPS, persona_name="Daniel"))
    assert out == "리더님은 출고 지연 사유부터 반장들에게 물으셨습니다. 리더님은 파손 건수를 적은 표를 들고 가셨습니다." and n == 2


def test_render_close_summary_prompt_has_no_result_frame_or_marker_words():
    llm = _FakeLLM(["리더님은 출고 지연 사유부터 반장들에게 물으셨습니다. 리더님은 파손 건수를 적은 표를 들고 가셨습니다."])
    asyncio.run(CR.render_close_summary(llm, episodes=_EPS, persona_name="Ella", register_hint="해요체"))
    prompt = llm.prompts[0]
    assert "리더가 직접 한 일 두 가지만 쓴다" in prompt and "결과나 까닭을 잇는 말로 문장을 늘이지 않는다" in prompt
    assert "문장의 주어는 언제나 '리더님'이다" in prompt
    # 금지할 낱말을 프롬프트에 나열하지 않는다(적으면 베낀다) — 재료에도 없으니 프롬프트 전체에 없어야 한다
    for w in ("그 결과", "이후", "그 뒤", "덕분에", "끌어내", "이어졌", "이어지"):
        assert w not in prompt, w
    # 결과를 쓰라고 하거나 허용하던 문구는 없다
    src = inspect.getsource(CR.render_close_summary)
    for old in ("수치나 달라진 상태", "뒤에 올 수 있는 것은", "없으면 상황·결과", "행동과 그 결과만 쓴다", "~하셨고 …했습니다' 꼴, 존댓말"):
        assert old not in src, old
    three = _FakeLLM([""])
    asyncio.run(CR.render_close_summary(three, episodes=_EPS + [{"action": "반송 건을 하나씩 확인했어요"}], persona_name="Ella", rounds=1))
    assert "리더가 직접 한 일 두세 가지만 쓴다" in three.prompts[0]
