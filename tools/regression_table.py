#!/usr/bin/env python
"""코치별 회귀 점검표 — 시뮬 결과(sim_result_<tag>_<coach>.json)만 읽어 마크다운 표로 낸다. (2026-11-15)

읽기 전용 집계 도구다. LLM 호출·네트워크·DB 접근이 없다(정규식과 가드 기록·원장만 본다).

용법
    python3 tools/regression_table.py <sim_result.json> [<sim_result.json> ...] [--detail]

    여러 파일을 주면 (1)은 한 표에 파일별 열로 합치고, (2)(3)은 파일(코치)별로 이어서 낸다.
    --detail 을 주면 깨진 문장·속 판단 노출·제3자 질문·8어절 미만 질문·'직접 한 말·조치' 근거 조각을 목록으로 덧붙인다.

입력 구조(없는 키는 전부 .get 으로 읽는다)
    d["rows"]   턴 목록 {"t","role"("model"|"user"),"chapter","probe","instr","content","guard"}
                ※ 리더(user) 줄의 instr 는 '그 답을 받은 코치 턴의 종류'라서 구간을 끊는 데 쓰지 않는다. 코치(model) 줄만 본다.
    d["ledger"] 대화 원장 {"episodes": {영역: [사례…]}, "covered": {영역: {칸: [{"episode","strength","quote"}]}}}
    d["cost_usd"], d["turns"], d["coach"](1 Ella·2 Jessica·3 Olivia·4 Daniel·5 Michael·6 Lucas)

────────────────────────────────────────────────────────────────────────────────────────────
(1) 코치별 점검표 — 지표 정의와 한계
────────────────────────────────────────────────────────────────────────────────────────────
· 꼬리 질문 수        instr 이 EPISODE_PROBE·SWEEP_FOLLOWUP 인 코치 턴 가운데 guard.bei == "reask"(다시 묻기)를 뺀 수.
                      다시 묻기 턴 수는 따로 한 줄.
· 리더 행동을 묻는 것 `a(b)` — a = guard.ask_slot == "action" 인 꼬리 질문 턴 수(가드 기록 기준),
                      b = 그 턴의 질문 문장이 리더 행동을 묻는 꼴(ACTION_Q_RE)인 꼬리 질문 턴 수(문장 기준, ask_slot 과 무관하게 전부 본다).
                      ask_slot 이 없는 턴은 문장으로만 판정할 수 있으므로 'ask_slot 없는 턴 n개 중 문장 기준 m개'를 따로 한 줄 낸다.
                      문장 기준: 질문 문장에 "리더님"이 있고 ACTION_Q_RE(직접 / 말씀·결정·대응…하셨 / 하신 말·행동 / 움직이셨 /
                      의문사 … 하셨)에 걸리며, 가정('…셨을까요')이 아닌 것.
                      한계: 주어를 생략한 질문("그때 무엇을 하셨나요?")은 "리더님"이 없어 세지 않는다. '직접'은 맥락과 무관하게 걸린다.
· 제3자 장면 질문     꼬리 질문 턴(다시 묻기 제외)의 질문 문장에 제3자 낱말(THIRD_PARTY_WORDS: 교육생·수강생·참가자·참석자·학습자·고객사·
                      고객·수료생·신입사원(들)·학생)이 주어·대상 자리(뒤에 은/는/이/가/도/의/께서/에게/한테/을/를/과/와 또는
                      반응·표정·태도·모습·분위기·말·질문·피드백·만족도·평가·변화)에 있고, "리더님"이 주어(리더님은/이/께서/도)로 없는 것.
                      "다른 고객사에 쓰기로 결정하실 때"처럼 곳·쓰임새로만 나온 낱말은 세지 않는다.
                      한계: 낱말 목록에 없는 제3자(예: 협력사 직원)는 못 잡는다. "리더님이 이끄는 팀의 교육생은…"처럼 리더님이 안긴 절의
                      주어이기만 해도 제외된다. 리더가 실제로 교육생을 직접 이끄는 직무라도 구분하지 못한다.
· 질문 평균 어절 수 / 8어절 미만 수
                      대상은 '꼬리 질문 + 다시 묻기' 턴의 **마지막 질문 문장**(output_guard.is_question — 물음표 없는 요청형 포함).
                      어절 = 공백으로 나눈 수. 질문 문장이 없는 턴은 빼고 그 수를 괄호로 밝힌다.
· 깨진 문장·조각 수   코치 턴 전체의 문장(목록 줄 '· …' 제외)을 꼴별로 한 번씩만 센다(우선순위 a → c → b).
    (a) 의문사 뒤 평서 감탄 어미: 의문사(무엇|어떻게|왜|누가|누구|언제|어디|어떤|뭐|뭘|무슨)가 있고 '~군요/~네요/~구나/~군'으로 끝나며
        질문이 아닌 문장. 의문사 뒤에 '…지'로 안긴 절(받침 ㄴ·ㄹ 뒤의 '지': 하는지·좋을지·인지), 인용 물음(…냐고·…냐며·…까 싶),
        안긴 평서절(…다는/다고/라는/라고 — "어떤 신호를 보셨다는 뜻이군요")이 있으면 제외.
        '무엇보다·누구나·언제나·어떻게든·왜냐하면·뭔가' 같은 부정칭 쓰임도 제외. 따옴표 안은 보지 않는다.
        한계: '어떤 분은 반대하셨군요'처럼 '어떤'이 '일부'의 뜻일 때도 걸린다. "무엇을 하셨다는 말씀이군요"는 안긴 평서절로 보아 놓친다.
    (b) 서술어 없는 조각: ① '요'로 끝나는데 용언 종결(…어요/아요/해요/세요/예요/이에요/네요/군요/까요/나요/ㄴ가요/ㄴ데요/고요/…서요/…지요/
        죠 등 — _is_verbal_yo)이 아닌 것("…함께요." "…선택지요." "…일은요?" "…건요?" "…있으면요?" "…어도요.").
        '…지요'는 앞 음절 받침이 ㄱ·ㅇ 일 때만 명사+요('선택지요')로 본다 — '하지요·않지요·과제(이)지요'는 서술어.
        ② '요' 없이 조사(부터·까지·에서·에게·한테·으로·보다·처럼·마다·만·도·은·는·을·를·의·에·와·과·로·랑)로 끝나는 것("먼저 하나부터.").
        제외: "네." 같은 짧은 고정 응답(FIXED_SHORT), 호칭으로 끝난 문장("…, 리더님."), 줄표(—) 뒤 나열(줄표 앞 절로 판정).
        한계: 형태소 분석이 없어 '평가요/휴가요' 같은 명사+요 가운데 용언 꼴과 같은 것은 놓치고, '부서요'처럼 드문 꼴도 놓친다.
        Lucas 의 의도된 짧은 물음('…은요?' '…면요?')도 조각으로 센다(검토자 요구).
    (c) 쉼표나 연결어미로 끝난 문장: 문장 끝이 쉼표이거나 연결어미(…했고/하고/이고/지만/는데/아서·어서·해서/으면·하면·다면/으며/
        면서/도록/다가/거나/려고/…니까(합쇼체 물음 '-ㅂ니까/습니까' 제외))로 끝난 것. '…고요/…는데요'처럼 '요'가 붙은 것은 정상 종결로 본다.
        한계: '장면·전면'류 명사는 피했지만 '참고.'처럼 목록에 없는 명사+고 는 걸리지 않고, 반대로 '말고.'는 걸린다.
· 속 판단 노출 수     코치 문장이 진행·판정 상태를 말하는 꼴(INNER_JUDGMENT_PATTERNS)에 걸린 문장 수. 한 문장은 한 번만 센다.
                      한계: 정규식 목록에 있는 꼴만 잡는다. 영역 전환 고정 문구("다음으로 넘어가…")도 걸린다.
· 사례당 턴 수        원장 kind=="episode" 사례의 leader_turns 를 영역별로 나열("조직 5,4 / 사람 5,4"). 사례 없음·반복으로 닫힌 것은
                      '2(no_case)'처럼 사유를 붙인다. 닫힌 사유 분포는 그 사례들의 status 건수.
· 훑는 질문 꼬리      원장 kind=="sweep" 가운데 leader_turns ≥ 2 인 수 / 사례가 나온(status 가 no_case·repeat 이 아닌) 수 / 전체 수.
· 말투 혼용 문장 수   코치 턴마다 목록 줄('· …')을 뺀 본문에 persona_register.register_violations(코치, 본문, scope="strict") 를 돌린 길이 합.
                      Lucas 는 혼용 허용 코치라 함수가 빈 목록을 주므로 대신 `해요 n / 합쇼 m` — 해요체: '…요[.?!]'로 끝남,
                      합쇼체: '…니다[.]' '…니까[?]' '…시오[.]'로 끝남(문장부호가 없는 마지막 줄도 센다. '~죠'는 어느 쪽에도 넣지 않는다).
· p50 / p95 / 최대    guard.llm 이 있는(0 이 아닌) 코치 턴의 guard.total(초). p50·p95 모두 올림 순위(nearest-rank: ceil(q·n) 번째).
· 재생성              guard.regen_why 가 있는 턴 수와 사유별 건수.
· 형식미해결 수       guard.format_miss 가 있는 턴 수.
· 끝맺음별 사용 횟수  (P13d) 영역마다 코치 턴의 질문 문장(여는 질문·대체 문장 포함)에서 청하는 꼴 끝맺음(turn_checks.request_ending_key —
                      '말씀해 주시겠습니까', '들려주세요' …)을 세어, 영역별로 가장 많이 쓴 끝맺음과 횟수를 적는다. 바로 묻는 질문('무엇이었습니까?')은
                      세지 않는다. 같은 끝맺음 4회째 다시 쓰기를 없앤 뒤 입버릇이 되살아나는지 보는 숫자다(종전 상한 3). 상세에 전체 분포.
· 첫 꼬리 질문        (P13d) guard.first_probe 의 llm / fallback 건수와 fallback 사유, 전용 호출 평균 시간(guard.first_probe_s, 초).
· 받는 말 탈락        (P13d) guard.recv_allow(허용 목록에서 떨어져 지운 받는 말) 문장 수와 사유별 건수. 상세에 문장.
· 실제 USD·턴 수      d["cost_usd"], d["turns"].

────────────────────────────────────────────────────────────────────────────────────────────
(2) 사례별 표 — 원장의 사례(episode·sweep, no_case·repeat 포함)마다 한 줄
────────────────────────────────────────────────────────────────────────────────────────────
· 사례 구간           rows 를 순서대로 훑으며 코치 턴의 instr 로 끊는다. 여는 턴(COMPETENCY_ALIGN·EPISODE_OPEN·SWEEP_ANCHOR) 다음 리더 답부터
                      다음 여는 턴이나 영역 종료 턴(CHAPTER_READY_TO_END) 전까지가 한 사례의 리더 답이다. 원장 사례와는 가드 기록
                      (ep_kind, episode)이 있으면 그것으로, 없으면 같은 영역 안에서 여는 턴이 나온 순서로 대응시킨다. 수가 안 맞으면 경고를 낸다.
                      같은 답 안내(INPUT_REPEATED·INPUT_DUPLICATE)를 받은 리더 답(직전 답의 복사)은 구간에서 뺀다.
· 답의 종류           '여는 답' = 여는 턴이나 재질문 턴(NO_CASE_REFRAME·ANCHOR_REASK·EPISODE_RETRY) 바로 뒤의 답,
                      '꼬리 답' = 꼬리 질문(다시 묻기 포함) 뒤의 답. 그래서 재질문이 있으면 여는 답이 2개일 수 있다.
· '리더가 직접 한 말·조치'가 담긴 리더 발화 수 — `여는 답 a + 꼬리 b = 합`. 목표는 사례당 합 2 이상.
    판정(답 하나에 아래를 만족하는 절이 하나라도 있으면 1):
      ① 답에 과거 서술어(받침 ㅆ 음절 — 했·었·았·였·썼… 단 '있·겠' 제외)가 있다.
      ② 그 절의 주어가 1인칭(FIRST_PERSON_RE: 제가·저는·저도·내가·나는·나도·저희가·저희는)이거나 생략됐다.
         절에 제3자 주어(직함·호칭+이/가/은/는/께서/도, '성+두 글자'+조사 꼴 이름, '자기')가 있고 1인칭 주어가 없으면 제3자의 행동으로 보고 건너뛴다.
         1인칭 주어도 제3자 주어도 없는 절에 '직접'이나 낮춤말('드렸·말씀드…')이 있으면 리더 본인으로 본다.
         주어가 생략된 절은 앞 절(앞 문장 포함)의 주어를 이어받는다(답의 첫 절이면 리더 본인). '…더라/…더군/(과거 아닌)…더니'로 전하는 절도 건너뛴다.
      ③ 그 절에 (가) 따옴표 인용 + (라고/하고/고) + 말한 과거 서술어(말했·했·물었·답했…)가 있거나,
         (나) 구체 조치 동사의 실현 꼴(ACTION_DONE_RE: 만들었·정리했·작성했·썼·짰·불러·보여줬·가져갔·설명했·제안했·바꿨·맡겼·가르쳤·공유했·
         확인했·조정했·나눴·정했·미뤘·줄였·넘겼·소개했·물었·요청했·보고했 등), 또는 (다) '…자고 했/말했/제안했'(구체 제안)이 있다.
      '…하기로 했습니다 / …하려고 했습니다 / …할 수 있도록 했습니다 / 신경 썼습니다'처럼 방침·요약만 있는 답은 조치 동사가 실현 꼴이 아니라 0.
      '…했어야 / …했을 것 같' 같은 가정·후회, '안/못 …'도 뺀다.
    한계: 형태소 분석·개체명 인식이 없다. 답 첫머리부터 주어를 생략하고 제3자의 행동을 말하면 리더 행동으로 잘못 세고,
          반대로 제3자 주어 뒤에 주어 없이 이어진 리더 본인의 행동은 (이어받기 때문에) 놓친다.
          조사 없이 쓴 이름·목록에 없는 직함은 제3자로 못 잡는다. 반대로 '성+두 글자' 꼴 일반 낱말(불용어 목록 밖)은 제3자 주어로 잘못 보아
          리더 행동을 놓칠 수 있다. 조치 동사 목록 밖의 행동("…자리를 비웠어요")은 세지 않는다.
· strong 라벨 칸      그 사례 labels 가운데 strength == "strong" 인 칸.

────────────────────────────────────────────────────────────────────────────────────────────
(3) strong 근거 인용의 출처
────────────────────────────────────────────────────────────────────────────────────────────
· 원장 covered[영역][칸] 의 strong 근거 인용마다, 그 사례 구간의 리더 답과 대조한다(공백·문장부호 무시).
    1순위 그 사례 구간의 답에 통째로(또는 '…'로 끊긴 조각이 가장 많이) 들어 있는 답 → '여는 답' | '꼬리 n번째 답'
          (n = 그 구간 꼬리 답 가운데 순번. 다시 묻기 뒤의 답도 순번에 든다)
    2순위 같은 영역의 다른 사례 구간 답에 통째로 들어 있으면 그 답(다른 구간 표시 — 덧붙임(addenda)으로 들어온 근거)
    3순위 내용 어절(2글자 이상) 겹침이 가장 큰 그 구간 답('겹침 추정' 표시. 겹침이 2어절 미만이거나 절반 미만이면 '못 찾음')
· 요약: "strong 칸 N개 중 근거가 여는 답에서만 나온 칸 M개" — 칸의 strong 근거가 전부 여는 답(재질문 뒤 답 포함)에서 나온 칸 수.
  한계: 인용이 요약·의역이면 3순위 추정에 기대므로 틀릴 수 있다. 한 칸에 근거가 여러 개면 전부 여는 답일 때만 M 에 든다.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diag_project.services.output_guard import is_question, split_sentences  # noqa: E402
from diag_project.services.persona_register import register_violations  # noqa: E402
from diag_project.services.turn_checks import ending_label, request_ending_key  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
# 상수
# ══════════════════════════════════════════════════════════════════════════════
COACH_NAMES: dict[str, str] = {"1": "Ella", "2": "Jessica", "3": "Olivia", "4": "Daniel", "5": "Michael", "6": "Lucas"}
CHAPTER_SHORT: dict[str, str] = {"organization_management": "조직", "performance_management": "성과", "people_management": "사람",
                                 "work_management": "일", "self_management": "자기"}

TAIL_INSTR = frozenset({"EPISODE_PROBE", "SWEEP_FOLLOWUP"})                       # 꼬리 질문 턴
OPEN_INSTR = frozenset({"COMPETENCY_ALIGN", "EPISODE_OPEN", "SWEEP_ANCHOR"})      # 사례를 여는 턴
REFRAME_INSTR = frozenset({"NO_CASE_REFRAME", "ANCHOR_REASK", "EPISODE_RETRY"})   # 여는 질문을 다시 묻는 턴(사례는 그대로)
DUP_INSTR = frozenset({"INPUT_REPEATED", "INPUT_DUPLICATE"})                      # 같은 답 안내
# 사례 구간을 닫는 턴(영역 종료·영역 밖 턴)
CLOSE_INSTR = frozenset({"CHAPTER_READY_TO_END", "RAPPORT_BUILDING", "DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM", "COMPETENCY_ASK",
                         "AWAIT_NEXT_CHAPTER_CHOICE", "START_CHAPTER"})
NO_CASE_STATUS = frozenset({"no_case", "repeat"})                                 # 사례가 나오지 않고 닫힌 사유
SHORT_Q_EOJEOL = 8                                                                # 이 어절 수 미만이면 '짧은 질문'
DIRECT_TARGET = 2                                                                 # 사례당 '직접 한 말·조치' 발화 목표

# ── 리더 행동을 묻는 질문(문장 기준) ──
# "리더님"이 있는 질문 문장에서 다음 가운데 하나:
#   · '직접'
#   · 말씀/결정/대응/조치/제안/설명/요청/지시/개입/답/행동 + 하셨·하신        ("무엇이라고 답하셨나요", "어떻게 대응하셨는지")
#   · 하신·건넨·전한·꺼낸·취한·한 + (첫) 말/말씀/행동/조치/결정              ("직접 하신 말이나 결정", "가장 먼저 전한 말씀")
#   · 말/말씀/행동/조치/결정 + (을/를/이나…) + 하셨·건네셨·전하셨·꺼내셨·취하셨·내리셨
#   · 움직이셨
#   · 의문사(어떻게·무엇을·무엇부터·뭘·뭐라고·무엇이라고·무슨 말·어떤 말) 뒤 세 어절 안의 '…하셨' — 단 생각·판단·예상·기대·고민하셨 은 제외
ACTION_Q_RE = re.compile(
    r"직접"
    r"|(?:말씀|결정|대응|조치|제안|설명|요청|지시|개입|답|행동)하(?:셨|신)"
    r"|(?:하신|건넨|건네신|전한|전하신|꺼낸|꺼내신|취한|취하신|한)\s*(?:첫\s*)?(?:말씀|말|행동|조치|결정)"
    r"|(?:말씀|말|행동|조치|결정)(?:을|를|이나|이|은)?\s*(?:하셨|건네셨|전하셨|꺼내셨|취하셨|내리셨)"
    r"|움직이셨"
    r"|(?:어떻게|무엇을|무엇부터|뭘|뭐라고|무엇이라고|무슨\s*말을?|어떤\s*말을?)\s*(?:[가-힣]+\s+){0,3}?[가-힣]*"
    r"(?<!생각)(?<!판단)(?<!예상)(?<!기대)(?<!고민)하셨"
)
# 가정 질문("…직접 앉으셨다면, 무엇부터 확인하셨을까요?")은 실제 행동을 묻는 게 아니다
HYPOTHETICAL_Q_RE = re.compile(r"(셨|했|었|았|였)을까요[.?!]*$")

# ── 제3자 장면 질문 ──
THIRD_PARTY_WORDS: tuple[str, ...] = ("교육생", "수강생", "참가자", "참석자", "학습자", "고객사", "고객", "수료생", "신입사원들", "신입사원", "학생")
# 낱말이 주어·대상 자리에 있을 때만: 뒤에 조사(은/는/이/가/도/의/께서/에게/한테/을/를/과/와)나 반응 명사가 붙은 꼴.
# "다른 고객사에 쓰기로 결정하실 때" "고객사용으로 다듬는"처럼 곳·쓰임새로만 나온 것은 뺀다(시뮬 말뭉치 6건 중 5건이 이 오탐이었다).
THIRD_PARTY_RE = re.compile(
    "(?:" + "|".join(THIRD_PARTY_WORDS) + ")(?:들)?"
    r"(?:(?:은|는|이|가|도|의|께서|에게|한테|을|를|과|와)(?![가-힣])|\s?(?:반응|표정|태도|모습|분위기|말|질문|피드백|만족도|평가|변화|쪽))"
)
LEADER_SUBJECT_RE = re.compile(r"리더님(?:은|이|께서는|께서도|께서|도)(?![가-힣])")   # 리더님이 주어로 선 꼴

# ── 깨진 문장 (a): 의문사 뒤 평서 감탄 어미 ──
WH_RE = re.compile(r"(?<![가-힣])(무엇|어떻게|왜|누가|누구|언제|어디|어떤|뭐|뭘|무슨)")
# 의문사가 부정칭으로 쓰인 꼴(무엇보다·뭐든·누구나·언제나·어디서나·어떻게든·왜냐하면·뭔가…)
WH_INDEFINITE_RE = re.compile(r"^(보다|이든|든|이나|나(?![가-힣])|라도|이라도|냐하면|곡|서나|서든|에나|에서나|에서든|ㄴ가|인가(?!요))")
EXCLAIM_END_RE = re.compile(r"(군요|네요|구나|군)$")
# 인용 물음: "왜 바꾸냐고 버텼군요" — 의문사가 남의 물음을 옮긴 것
QUOTED_Q_RE = re.compile(r"(냐['’\"”]?\s?(?:고|며|는)|느냐|나\s?싶|까\s?싶|까\s?하[는고며]|까를|까라는)")
# 안긴 평서절: "어떤 신호를 보셨다는 뜻이군요" "누가 이기면 한 분이 떠날 거라고 보셨군요" — 의문사가 안긴 절 안에서 '어떤/누군가'의 뜻
EMBEDDED_STATEMENT_RE = re.compile(r"(다는|다고|라는|라고|다며|라며)(?=[\s,]|$)")

# ── 깨진 문장 (b): 서술어 없는 조각 ──
FIXED_SHORT: frozenset[str] = frozenset({"네", "예", "아", "아하", "음", "좋아요", "그렇군요", "알겠습니다", "잠시만요", "잠깐만요"})
# '요' 앞이 이 꼴이면 용언 종결로 본다(그 밖의 '…가요/…데요/…서요/…지요/…에요'는 _is_verbal_yo 에서 앞 음절을 본다)
_VERBAL_YO_SUFFIXES: tuple[str, ...] = (
    "어요", "아요", "여요", "해요", "돼요", "되요", "세요", "셔요", "예요", "네요", "군요", "까요", "나요", "게요", "래요", "걸요", "든요",
    "고요", "구요", "대요", "려요", "혀요", "겨요", "껴요", "져요", "쳐요", "켜요", "펴요", "써요", "춰요", "꿔요", "눠요", "둬요", "줘요",
    "워요", "와요", "봐요", "놔요", "내요", "애요", "라요", "러요", "잖아요",
)
PARTICLE_END_RE = re.compile(r"(부터|까지|에서|에게|한테|으로|보다|처럼|마다|조차|밖에|만|도|은|는|을|를|의|에|와|과|로|랑)$")
VOCATIVE_END_RE = re.compile(r"(리더님|팀장님|님)$")

# ── 깨진 문장 (c): 쉼표·연결어미로 끝남 ──
COMMA_END_RE = re.compile(r"[,，、]\s*[\"'”’]?$")
# '장면·전면·측면' 같은 명사를 피하려고 '면'은 앞 음절을 붙여 적는다. '니까'는 _ends_connective 에서 합쇼체 물음과 가른다.
CONNECTIVE_END_RE = re.compile(
    r"((?:셨|었|았|였|했|겠)고|하고|이고|시고|되고|있고|없고|않고|말고"
    r"|지만|습니다만|입니다만"
    r"|는데|은데|인데|한데|던데|텐데|건데"
    r"|아서|어서|해서|여서|셔서|라서|워서|와서"
    r"|으면|하면|되면|시면|다면|라면|려면|거면"
    r"|으며|하며|이며|시며|되며|면서"
    r"|도록|다가|거나|든지|더니|길래|느라|수록|자마자|려고|고자|으니)$"
)

# ── 속 판단 노출 ──
INNER_JUDGMENT_PATTERNS: tuple[str, ...] = (
    r"까지 들었으니",
    r"이제 .{0,20}(묻겠|여쭙겠|짚겠)",
    r"(답|말씀)에서는? .{0,20}(이|가) 보입니다",
    r"같은 (장면|사례|건)으로 보(이|입)",
    r"사례 전체를",
    r"이 사례(는|에서)",
    r"(충분히|(?<![가-힣])다)\s*들었",
    r"남은 (것|질문)",
    r"다음으로 넘어가",
)
INNER_JUDGMENT_RES = tuple(re.compile(p) for p in INNER_JUDGMENT_PATTERNS)

# ── 말투(Lucas 전용 직접 세기) ──
POLITE_END_RE = re.compile(r"요[.?!]*[\"'”’]?$")                      # 해요체: '…요[.?!]'
FORMAL_END_RE = re.compile(r"(니다\.?|니까\??|시오\.?)[\"'”’]?$")     # 합쇼체: '…니다[.]' '…니까[?]' '…시오[.]'

# ── '리더가 직접 한 말·조치' ──
QUOTE_SPAN_RE = re.compile(r"[\"“”][^\"“”\n]{1,160}[\"“”]|['‘’][^'‘’\n]{1,160}['‘’]")
QUOTE_MARK = "◇"                                                      # 따옴표 인용을 지운 자리
FIRST_PERSON_RE = re.compile(r"(?<![가-힣])(제가|저는|저도|내가|나는|나도|저희가|저희는)")
# 약한 1인칭 표지: '직접'과 낮춤말(드렸·말씀드…)은 말하는 사람의 행동이지만, 같은 절에 제3자 주어가 있으면 제3자가 이긴다("김대리가 직접 만들었어요")
SELF_HINT_RE = re.compile(r"(?<![가-힣])직접|드렸|드리(?:고|니|면서|며)|말씀드|여쭤|여쭸")
# 제3자 주어: 직함·호칭 + 주격/보조사. '30분은' '부분은' 같은 낱말을 피하려고 '분·명'은 앞말을 붙여 적는다.
_ROLE_WORDS = ("씨|님|선임|책임|수석|주임|대리|과장|차장|부장|팀장|실장|본부장|대표|이사|상무|전무|사장|매니저|강사|선생|담당자|본부|회사"
               "|본인|자기|걔|(?:팀원|직원|사원|사람|친구|후배|선배|동료)들?|(?:그|이|저|두|세|네|여러|몇)\\s?분들?|(?:두|세|네|다섯|여섯|\\d+)\\s?명|둘")
THIRD_ROLE_RE = re.compile(rf"(?:{_ROLE_WORDS})(?:이|가|은|는|께서는|께서|도)(?=[\s,]|$)")
THIRD_BARE_RE = re.compile(r"(?<![가-힣])(다들|각자|서로|자기(?!관리))")
# '성 + 두 글자' 꼴 이름 + 조사("최운영은", "이기획이"). 같은 꼴 일반 낱말은 불용어로 뺀다(목록 밖 낱말은 한계로 남는다).
_SURNAMES = "김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모"
THIRD_NAME_RE = re.compile(rf"(?<![가-힣])([{_SURNAMES}][가-힣]{{2}})(?:이|가|은|는|도)(?=[\s,]|$)")
NAME_STOPWORDS: frozenset[str] = frozenset({
    "이야기", "이번에", "이것들", "이때부", "이후에", "이전에", "이제부", "이것저", "이렇게", "이런저",
    "하반기", "하나씩", "하나하", "하루하", "한마디", "한동안", "한가지", "한번씩", "한꺼번", "한편으",
    "기획안", "기획서", "기획팀", "기본안", "기준표", "고객사", "고객들", "고민들",
    "우리팀", "우선순", "나머지", "지난번", "지난주", "지난달", "지난해", "지금까", "지금부",
    "정리본", "정기회", "조정안", "성과급", "성과표", "설계안", "설명회", "방향성", "공유안", "공지문",
    "문제점", "문서화", "최종안", "최우선", "최소한", "전체적", "전반적", "전부다", "구성안", "주간회", "주말에", "주중에",
    "제안서", "제안들", "제도들", "모든것", "모두들", "여기까", "여러번", "연말에", "연초에", "원인들", "원래는",
    "민감도", "진행안", "진행표", "선택지", "소통방", "도입안", "마지막", "길게는", "인사팀", "인원들", "현장에", "반기별",
})
HEARSAY_RE = re.compile(r"더(라|군|니)|대요|답니다|다네요")
# 인용한 말을 리더가 했다는 서술어(과거): ◇라고 말했 / ◇ 하고 물었 / ◇고 했
SAY_AFTER_QUOTE_RE = re.compile(
    QUOTE_MARK + r"\s*(?:이?라고|하고|고|라며|하며)?\s*"
    r"(말했|했|물었|답했|얘기했|이야기했|전했|제안했|부탁했|요청했|설명했|말씀드렸|물어봤|여쭸|여쭤봤|말해\s?줬|해\s?줬)"
)
# 구체 제안을 옮긴 말: "한 과정만 파일럿으로 돌리자고 했고"
PROPOSAL_RE = re.compile(r"자고\s?(했|말했|제안했|요청했|말씀드렸)")
# 구체 조치 동사의 '실현 꼴'만 — '…하기로/하려고/할 수 있도록 했다'는 여기 걸리지 않는다
_HADA_NOUNS = ("정리|작성|설명|제안|공유|확인|조정|소개|요청|보고|복원|인정|지시|전달|안내|발표|수정|중재|면담|상의|설득|부탁|약속|사과"
               "|질문|대답|연락|배정|분담|기록|점검|검토|보완|소집|통보|공지")
ACTION_DONE_RE = re.compile(
    rf"(?:{_HADA_NOUNS})(?:을|를)?\s?(?:했|하였|해서|하며|하면서|하고(?!\s?(?:싶|자|있))|해\s?(?:줬|주었|주고|드렸|드리고|봤|보았|놨|뒀|두었)|드렸|드리고|드리니)"
    r"|만들(?:었|어서|어\s|고\s)"
    r"|(?<!애)(?<!힘)(?<!신경\s)(?<!신경을\s)썼|써서|써\s?(?:줬|드렸|봤)"
    r"|짰|짜서"
    r"|불렀|불러(?:서|\s)"
    r"|보여\s?(?:줬|주었|주고|주니|드렸|드리고|드리니)"
    r"|가져갔|가져가서|가져왔|가지고\s?갔|들고\s?갔"
    r"|바꿨|바꾸었|바꿔서|바꿔\s?(?:줬|드렸|봤|놨)"
    r"|맡겼|맡기고"
    r"|가르쳤|가르쳐\s?(?:줬|드렸)"
    r"|나눴|나누었|나눠서|나눠\s?(?:줬|드렸)"
    r"|(?<!결)정했"
    r"|미뤘|줄였|넘겼"
    r"|물었|물어\s?봤|물어보았"
    r"|앉혔|적게\s?했|열었|짚었|보냈|고쳤|붙였|찾아갔|만났|전했|건넸|모았|꺼냈|돌렸|쪼개\s?봤|쪼갰|뽑았"
)
# 실현 꼴 바로 뒤가 이러면 가정·후회·의무("…했어야", "…꺼냈을 것 같아")라 뺀다
UNREAL_AFTER_RE = re.compile(r"^(어야|었어야|을\s?(것|거|걸|텐|지)|으면|더라면|다면|을까)")
NEGATION_BEFORE_RE = re.compile(r"(안|못)\s$")


# ══════════════════════════════════════════════════════════════════════════════
# 작은 도구
# ══════════════════════════════════════════════════════════════════════════════
def _jong(ch: str) -> int:
    """한글 음절의 받침 번호(없으면 0, 한글이 아니면 -1). ㄴ=4 ㄹ=8 ㅂ=17 ㅆ=20 ㅎ=27."""
    if ch and "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28
    return -1


def _guard(row: dict) -> dict:
    g = row.get("guard")
    return g if isinstance(g, dict) else {}


def coach_name(data: dict) -> str:
    c = str(data.get("coach") or "").strip()
    return COACH_NAMES.get(c, c or "?")


def file_tag(path: str | Path) -> str:
    """sim_result_<tag>_<coach>.json → <tag>."""
    m = re.match(r"sim_result_(.+)_(\d+)$", Path(path).stem)
    return m.group(1) if m else Path(path).stem


def chapter_short(ch: str | None) -> str:
    return CHAPTER_SHORT.get(ch or "", ch or "-")


def body_without_list(text: str | None) -> str:
    """목록 줄('· …')을 뺀 본문."""
    return "\n".join(ln for ln in (text or "").split("\n") if not ln.strip().startswith("·"))


def sentences(text: str | None) -> list[str]:
    """줄 단위로 나눈 뒤 문장으로 나눈다. 목록 줄('· …')은 뺀다(문장부호가 없어 다음 문장에 붙는 것을 막는다)."""
    out: list[str] = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line or line.startswith("·"):
            continue
        out.extend(s.strip() for s in split_sentences(line) if s.strip())
    return out


def question_sentences(text: str | None) -> list[str]:
    return [s for s in sentences(text) if is_question(s)]


def last_question(text: str | None) -> str | None:
    qs = question_sentences(text)
    return qs[-1] if qs else None


def eojeol_count(sentence: str | None) -> int:
    return len((sentence or "").split())


def percentile(values: list[float], q: float) -> float | None:
    """올림 순위(nearest-rank) 백분위: 정렬한 값의 ceil(q·n) 번째."""
    vs = sorted(values)
    if not vs:
        return None
    k = max(1, int(math.ceil(q * len(vs))))
    return vs[min(len(vs), k) - 1]


def _strip_quotes(s: str) -> str:
    return QUOTE_SPAN_RE.sub(QUOTE_MARK, s or "")


def _core(s: str) -> str:
    """문장 끝의 문장부호·따옴표·괄호를 떼어 낸 몸통."""
    return (s or "").strip().rstrip(" .?!…~\"'”’)")


# ══════════════════════════════════════════════════════════════════════════════
# 코치 턴 분류·질문 판정
# ══════════════════════════════════════════════════════════════════════════════
def is_coach(row: dict) -> bool:
    return row.get("role") == "model"


def is_reask_turn(row: dict) -> bool:
    return is_coach(row) and row.get("instr") in TAIL_INSTR and _guard(row).get("bei") == "reask"


def is_tail_turn(row: dict) -> bool:
    """꼬리 질문 턴(다시 묻기 제외)."""
    return is_coach(row) and row.get("instr") in TAIL_INSTR and _guard(row).get("bei") != "reask"


def asks_leader_action(sentence: str) -> bool:
    """질문 문장이 리더의 행동을 묻는가(문장 기준)."""
    s = sentence or ""
    if "리더님" not in s or not is_question(s):
        return False
    if HYPOTHETICAL_Q_RE.search(s.strip()):
        return False
    return bool(ACTION_Q_RE.search(s))


def asks_third_party(sentence: str) -> bool:
    """질문 문장이 제3자(리더가 이끌거나 함께 일하는 사람이 아닌 사람)의 장면을 묻는가."""
    s = sentence or ""
    if not is_question(s) or not THIRD_PARTY_RE.search(s):
        return False
    return not LEADER_SUBJECT_RE.search(s)


# ══════════════════════════════════════════════════════════════════════════════
# 깨진 문장·조각
# ══════════════════════════════════════════════════════════════════════════════
def _has_embedded_clause(rest: str) -> bool:
    """의문사 뒤에 '…지'로 안긴 절(받침 ㄴ·ㄹ 뒤의 '지' + 조사)이나 인용 물음이 있는가."""
    if QUOTED_Q_RE.search(rest) or EMBEDDED_STATEMENT_RE.search(rest):
        return True
    for m in re.finditer(r"([가-힣])지(?:는|도|를|가|에|만|부터|까지|조차|요)?(?=[\s,.?!]|$)", rest):
        if _jong(m.group(1)) in (4, 8):
            return True
    return False


def _wh_as_statement(bare: str) -> bool:
    """의문사가 물음의 뜻으로 남은 채 평서 감탄 어미로 끝났는가(따옴표를 지운 문장을 받는다)."""
    for m in WH_RE.finditer(bare):
        rest = bare[m.end():]
        if WH_INDEFINITE_RE.match(rest):
            continue
        if m.group(1) == "어떤" and re.match(r"\s*[가-힣]+\s?[가-힣]*든", rest):   # '어떤 식으로든'
            continue
        if _has_embedded_clause(rest):
            continue
        return True
    return False


def _is_verbal_yo(core: str) -> bool:
    """'요'로 끝난 몸통이 용언 종결인가(명사·부사·조사 + 요 가 아닌가)."""
    if not core.endswith("요") or len(core) < 2:
        return False
    if core.endswith(_VERBAL_YO_SUFFIXES):
        return True
    prev2 = core[-3] if len(core) >= 3 else ""
    tail = core[-2:]
    if tail == "가요":                       # …인가요/는가요/던가요(받침 ㄴ) · 넘어가요/나가요 · 띄어 쓴 '가요'(짐작이 가요)
        return _jong(prev2) == 4 or (prev2 != "" and prev2 in "어아러나 ")
    if tail == "데요":                       # …는데요/은데요/텐데요(받침 ㄴ)
        return _jong(prev2) == 4
    if tail == "서요":                       # …해서요/라서요 는 용언, '…에서요'는 조사
        return prev2 != "에" and prev2 != ""
    if tail == "지요":                       # …는지요/겠지요/않지요/하지요/과제(이)지요 는 서술어. 받침 ㄱ·ㅇ 뒤('선택지요' '공지요')만 명사+요 로 본다
        return _jong(prev2) not in (1, 21, -1)
    if tail == "에요":                       # …이에요/아니에요/거에요
        return prev2 != "" and prev2 in "이니거게"
    if core.endswith("니까요"):
        return True
    return False


def _ends_connective(core: str) -> bool:
    if core.endswith("니까"):
        prev = core[-3] if len(core) >= 3 else ""
        return not (prev == "습" or _jong(prev) == 17)      # '-습니까/-ㅂ니까'는 합쇼체 물음
    return bool(CONNECTIVE_END_RE.search(core))


_FIXED_BRIDGE_C: set[str] | None = None


def _is_fixed_bridge(sentence: str) -> bool:
    """(2026-11-15 P13b-3) 고정 다리 문장('먼저 하나부터.', '첫 장면부터.' 등 — 영역 시작 턴에 시스템이 붙이는 문장)은 조각으로 세지 않는다."""
    global _FIXED_BRIDGE_C
    if _FIXED_BRIDGE_C is None:
        from diag_project.services.intro_messages import ALIGN_OPEN_VARIANTS
        _FIXED_BRIDGE_C = {re.sub(r"[\s.,!?…]+", "", x) for v in ALIGN_OPEN_VARIANTS.values() for x in v}
    return re.sub(r"[\s.,!?…]+", "", sentence or "") in _FIXED_BRIDGE_C


_DEMO_GAP_RE = re.compile(r"(?<![가-힣])(그|이|저)\s+((들려|말씀해|알려|짚어|설명해|전해|옮겨|떠올려)\s*주|하셨|했|되었|됐|있었|있으셨)")      # turn_checks.DEMONSTRATIVE_GAP_RE 와 같다


def classify_broken(sentence: str) -> str | None:
    """깨진 문장이면 꼴("a" 의문사+감탄 어미 | "b" 서술어 없는 조각 | "c" 쉼표·연결어미 끝)을, 아니면 None."""
    s = (sentence or "").strip()
    if not s or s.startswith("·") or _is_fixed_bridge(s):
        return None
    bare = _strip_quotes(s)
    core = _core(bare)
    if not core or core.endswith(QUOTE_MARK):
        return None
    # (d) (2026-11-17 P14c-5) 지시어(그·이·저) 바로 뒤에 서술어 — 사이의 말이 지워져 깨진 문장('…가늠하셨는지, 그 들려주시겠어요?')
    if _DEMO_GAP_RE.search(bare):
        return "d"
    # (a) 의문사 뒤 평서 감탄 어미
    if not s.endswith("?") and not is_question(s) and EXCLAIM_END_RE.search(core) and _wh_as_statement(bare):
        return "a"
    # (c) 쉼표·연결어미로 끝남
    if COMMA_END_RE.search(bare.rstrip()) or _ends_connective(core):
        return "c"
    # (b) 서술어 없는 조각 — 줄표 뒤 나열은 줄표 앞 절로 판정한다
    if "—" in core:
        core = _core(core.split("—", 1)[0])
        if not core:
            return None
    if core in FIXED_SHORT:
        return None
    if core.endswith("요"):
        return None if _is_verbal_yo(core) else "b"
    if VOCATIVE_END_RE.search(core):
        return None
    last = core.split()[-1] if core.split() else ""
    if PARTICLE_END_RE.search(last) and not re.search(r"(니다|니까|시오|죠)$", core):
        return "b"
    return None


def inner_judgment_hit(sentence: str) -> str | None:
    """속 판단(진행·판정 상태)을 말하는 문장이면 걸린 정규식을, 아니면 None."""
    for pat, rx in zip(INNER_JUDGMENT_PATTERNS, INNER_JUDGMENT_RES):
        if rx.search(sentence or ""):
            return pat
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 말투
# ══════════════════════════════════════════════════════════════════════════════
def register_cell(name: str, coach_rows: list[dict]) -> tuple[str, dict]:
    """말투 혼용 칸의 표시 문자열과 원자료."""
    if name == "Lucas":
        polite = formal = 0
        for r in coach_rows:
            for s in sentences(r.get("content")):
                if POLITE_END_RE.search(s):
                    polite += 1
                elif FORMAL_END_RE.search(s):
                    formal += 1
        return f"해요 {polite} / 합쇼 {formal}", {"polite": polite, "formal": formal}
    bad: list[str] = []
    for r in coach_rows:
        bad.extend(register_violations(name, body_without_list(r.get("content")), scope="strict"))
    return str(len(bad)), {"violations": bad}


# ══════════════════════════════════════════════════════════════════════════════
# '리더가 직접 한 말·조치'
# ══════════════════════════════════════════════════════════════════════════════
def _has_past(text: str) -> bool:
    """과거 서술어(받침 ㅆ 음절 — '있·겠' 제외)가 있는가."""
    return any(_jong(ch) == 20 and ch not in "있겠" for ch in text)


def _third_subject(clause: str) -> bool:
    if THIRD_ROLE_RE.search(clause) or THIRD_BARE_RE.search(clause):
        return True
    return any(m.group(1) not in NAME_STOPWORDS for m in THIRD_NAME_RE.finditer(clause))


def _hearsay(clause: str) -> bool:
    """'…하더라/…하더군/(과거 아닌)…더니/…대요'처럼 남의 행동을 전하는 절인가. '했더니'는 말하는 사람의 행동이라 뺀다."""
    for m in HEARSAY_RE.finditer(clause):
        if m.group(0).startswith("더"):
            prev = clause[m.start() - 1] if m.start() > 0 else ""
            if _jong(prev) == 20:
                continue
        return True
    return False


def _realized(clause: str, m: re.Match) -> bool:
    """걸린 조치 동사가 실제로 한 일인가(가정·후회·부정이 아닌가)."""
    if UNREAL_AFTER_RE.match(clause[m.end():]):
        return False
    if NEGATION_BEFORE_RE.search(clause[:m.start()]):
        return False
    return True


def direct_action_evidence(answer: str | None) -> list[str]:
    """리더 답에서 '리더 본인이 한 구체적 말·조치'로 판정한 근거 조각 목록(비어 있으면 0으로 센다)."""
    text = (answer or "").strip()
    if not text or not _has_past(_strip_quotes(text)):
        return []
    hits: list[str] = []
    subject = "first"                                       # 답의 첫 절에서 주어가 생략되면 리더 본인으로 본다
    for sent in sentences(text):
        bare = _strip_quotes(sent)
        for clause in re.split(r"[,，;]", bare):            # 주어가 생략된 절은 앞 절(앞 문장 포함)의 주어를 이어받는다
            if not clause.strip():
                continue
            if FIRST_PERSON_RE.search(clause):
                subject = "first"
            elif _third_subject(clause):
                subject = "third"
            elif SELF_HINT_RE.search(clause):
                subject = "first"
            if subject != "first" or _hearsay(clause):
                continue
            found = None
            for rx in (SAY_AFTER_QUOTE_RE, ACTION_DONE_RE, PROPOSAL_RE):
                for m in rx.finditer(clause):
                    if _realized(clause, m):
                        found = m
                        break
                if found:
                    break
            if found:
                lo = max(0, found.start() - 12)
                hits.append(clause[lo:found.end() + 4].strip())
    return hits


# ══════════════════════════════════════════════════════════════════════════════
# 사례 구간 · 원장 대응
# ══════════════════════════════════════════════════════════════════════════════
def build_segments(rows: list[dict]) -> list[dict]:
    """rows 를 순서대로 훑어 사례 구간을 만든다.
    구간: {"chapter","open_row","open_instr","kind","idx","answers":[{"row","text","kind"("open"|"tail"),"reframe","n"}]}
    answers[].n 은 꼬리 답 가운데 순번(여는 답은 0)."""
    segs: list[dict] = []
    cur: dict | None = None
    ans_kind, reframe = "open", False
    for i, r in enumerate(rows or []):
        if is_coach(r):
            instr = r.get("instr")
            g = _guard(r)
            ch = r.get("chapter") or g.get("ch")
            if instr in OPEN_INSTR:
                cur = {"chapter": ch, "open_row": i, "open_instr": instr, "kind": g.get("ep_kind"), "idx": g.get("episode"), "answers": []}
                segs.append(cur)
                ans_kind, reframe = "open", False
            elif instr in CLOSE_INSTR:
                cur = None
            elif cur is not None:
                if ch and cur["chapter"] and ch != cur["chapter"]:
                    cur = None                              # 영역이 바뀌었으면 구간을 닫는다
                elif instr in TAIL_INSTR:
                    ans_kind, reframe = "tail", False
                elif instr in REFRAME_INSTR:
                    ans_kind, reframe = "open", True
                # 그 밖의 턴(같은 답 안내·잠시 멈춤 등)은 직전 질문의 종류를 그대로 둔다
        elif r.get("role") == "user" and cur is not None:
            nxt = next((x for x in rows[i + 1:] if is_coach(x)), None)
            if nxt is not None and nxt.get("instr") in DUP_INSTR:
                continue                                    # 같은 답 안내를 받은 답(직전 답의 복사)은 뺀다
            cur["answers"].append({"row": i, "text": r.get("content") or "", "kind": ans_kind, "reframe": reframe, "n": 0})
    for s in segs:
        n = 0
        for a in s["answers"]:
            if a["kind"] == "tail":
                n += 1
                a["n"] = n
    return segs


def case_marker(kind: str | None, idx) -> str:
    return f"{kind or 'episode'}{idx if idx is not None else '?'}"


def covered_marker(v) -> str:
    """covered 의 episode 값(사례는 번호, 훑는 질문은 'sweepN') → 사례 표지."""
    if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
        return f"episode{v}"
    return str(v)


def build_cases(rows: list[dict], ledger: dict | None) -> tuple[list[dict], list[str]]:
    """원장의 사례마다 대화 구간을 대응시킨다. (사례 목록, 경고 목록)"""
    ledger = ledger if isinstance(ledger, dict) else {}
    episodes = ledger.get("episodes") if isinstance(ledger.get("episodes"), dict) else {}
    segs = build_segments(rows)
    by_ch: dict[str, list[dict]] = {}
    for s in segs:
        by_ch.setdefault(s["chapter"] or "-", []).append(s)
    warnings: list[str] = []
    cases: list[dict] = []
    chapters = list(episodes) + [c for c in by_ch if c not in episodes]
    for ch in chapters:
        eps = [e for e in (episodes.get(ch) or []) if isinstance(e, dict)]
        ch_segs = by_ch.get(ch, [])
        if len(eps) != len(ch_segs):
            warnings.append(f"{chapter_short(ch)}: 원장 사례 {len(eps)}개 ≠ 대화의 여는 턴 {len(ch_segs)}개 — 구간 대응이 어긋날 수 있습니다.")
        keyed = {(s["kind"], s["idx"]): s for s in ch_segs if s["kind"] and s["idx"] is not None}
        for pos, ep in enumerate(eps):
            kind = ep.get("kind") or "episode"
            idx = ep.get("idx")
            seg = keyed.get((kind, idx))
            if seg is None and pos < len(ch_segs) and not (ch_segs[pos]["kind"] and ch_segs[pos]["idx"] is not None):
                seg = ch_segs[pos]                          # 가드 기록이 없으면 여는 턴이 나온 순서로 대응
            marker = case_marker(kind, idx)
            if seg is None:
                warnings.append(f"{chapter_short(ch)} {marker}: 대화에서 여는 턴을 찾지 못했습니다(리더 답 0개로 처리).")
            answers = seg["answers"] if seg else []
            open_n = tail_n = 0
            evidence: list[tuple[str, list[str]]] = []
            for a in answers:
                ev = direct_action_evidence(a["text"])
                if not ev:
                    continue
                if a["kind"] == "open":
                    open_n += 1
                else:
                    tail_n += 1
                evidence.append((answer_label(a), ev))
            labels = [x for x in (ep.get("labels") or []) if isinstance(x, dict)]
            cases.append({
                "chapter": ch, "marker": marker, "kind": kind, "idx": idx, "opener_sub": ep.get("opener_sub"),
                "leader_turns": ep.get("leader_turns"), "status": ep.get("status"), "answers": answers,
                "direct_open": open_n, "direct_tail": tail_n, "direct_total": open_n + tail_n, "direct_evidence": evidence,
                "strong_subs": [x.get("sub") for x in labels if x.get("strength") == "strong" and x.get("sub")],
            })
    return cases, warnings


def answer_label(a: dict) -> str:
    if a.get("kind") == "open":
        return "여는 답(재질문)" if a.get("reframe") else "여는 답"
    return f"꼬리 {a.get('n')}번째 답"


# ══════════════════════════════════════════════════════════════════════════════
# strong 근거 인용의 출처
# ══════════════════════════════════════════════════════════════════════════════
def _norm(s: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s or "")


def _content_words(s: str | None) -> list[str]:
    return [w for w in re.sub(r"[^0-9A-Za-z가-힣\s]", " ", s or "").split() if len(w) >= 2]


def quote_source(quote: str | None, case: dict | None, chapter_cases: list[dict]) -> dict:
    """인용이 어느 답에서 나왔는지. {"label": 표시, "kind": "open"|"tail"|None, "how": "exact"|"other"|"overlap"|"none"}"""
    nq = _norm(quote)
    answers = (case or {}).get("answers") or []
    if not nq:
        return {"label": "못 찾음", "kind": None, "how": "none"}
    # 1순위: 그 사례 구간의 답에 통째로 / 조각이 가장 많이
    for a in answers:
        if nq in _norm(a["text"]):
            return {"label": answer_label(a), "kind": a["kind"], "how": "exact"}
    pieces = [p for p in (_norm(x) for x in re.split(r"…|\.{2,}|(?<=[.!?])\s+", quote or "")) if len(p) >= 6]
    if len(pieces) > 1:
        best, best_n = None, 0
        for a in answers:
            na = _norm(a["text"])
            n = sum(1 for p in pieces if p in na)
            if n > best_n:
                best, best_n = a, n
        if best is not None:
            return {"label": answer_label(best), "kind": best["kind"], "how": "exact"}
    # 2순위: 같은 영역의 다른 사례 구간
    for other in chapter_cases:
        if other is case:
            continue
        for a in other.get("answers") or []:
            if nq in _norm(a["text"]):
                return {"label": f"{answer_label(a)}(다른 구간 {other['marker']})", "kind": a["kind"], "how": "other"}
    # 3순위: 내용 어절 겹침이 가장 큰 답
    qw = _content_words(quote)
    best, best_n = None, 0
    for a in answers:
        na = _norm(a["text"])
        n = sum(1 for w in qw if w in na)
        if n > best_n:
            best, best_n = a, n
    if best is not None and best_n >= 2 and best_n * 2 >= len(qw):
        return {"label": f"{answer_label(best)}(겹침 추정 {best_n}/{len(qw)})", "kind": best["kind"], "how": "overlap"}
    return {"label": "못 찾음", "kind": None, "how": "none"}


def strong_sources(cases: list[dict], ledger: dict | None) -> tuple[list[dict], dict]:
    """covered 의 strong 근거마다 출처를 판정한다. (줄 목록, 요약)"""
    ledger = ledger if isinstance(ledger, dict) else {}
    covered = ledger.get("covered") if isinstance(ledger.get("covered"), dict) else {}
    lines: list[dict] = []
    cells: dict[tuple[str, str], list[dict]] = {}
    for ch, subs in covered.items():
        if not isinstance(subs, dict):
            continue
        ch_cases = [c for c in cases if c["chapter"] == ch]
        for sub, entries in subs.items():
            for e in entries or []:
                if not isinstance(e, dict) or e.get("strength", "strong") != "strong":
                    continue
                marker = covered_marker(e.get("episode"))
                case = next((c for c in ch_cases if c["marker"] == marker), None)
                src = quote_source(e.get("quote"), case, ch_cases)
                line = {"chapter": ch, "sub": sub, "marker": marker, "quote": e.get("quote") or "", **src}
                lines.append(line)
                cells.setdefault((ch, sub), []).append(line)
    open_only = sum(1 for v in cells.values() if all(x["kind"] == "open" for x in v))
    has_tail = sum(1 for v in cells.values() if any(x["kind"] == "tail" for x in v))
    not_found = sum(1 for x in lines if x["kind"] is None)
    return lines, {"cells": len(cells), "open_only": open_only, "has_tail": has_tail, "quotes": len(lines), "not_found": not_found}


# ══════════════════════════════════════════════════════════════════════════════
# 파일 단위 분석
# ══════════════════════════════════════════════════════════════════════════════
def analyze(data: dict, label: str | None = None) -> dict:
    rows = [r for r in (data.get("rows") or []) if isinstance(r, dict)]
    ledger = data.get("ledger") if isinstance(data.get("ledger"), dict) else {}
    name = coach_name(data)
    coach_rows = [r for r in rows if is_coach(r)]

    # ── 꼬리 질문 ──
    tails = [r for r in coach_rows if is_tail_turn(r)]
    reasks = [r for r in coach_rows if is_reask_turn(r)]
    action_slot = sum(1 for r in tails if _guard(r).get("ask_slot") == "action")
    action_sent_rows = [r for r in tails if any(asks_leader_action(q) for q in question_sentences(r.get("content")))]
    no_slot = [r for r in tails if not _guard(r).get("ask_slot")]
    no_slot_action = sum(1 for r in no_slot if any(asks_leader_action(q) for q in question_sentences(r.get("content"))))
    third_qs = [q for r in tails for q in question_sentences(r.get("content")) if asks_third_party(q)]
    third_turns = sum(1 for r in tails if any(asks_third_party(q) for q in question_sentences(r.get("content"))))

    # ── 질문 길이(꼬리 + 다시 묻기, 마지막 질문 문장) ──
    last_qs: list[str] = []
    no_q = 0
    for r in coach_rows:
        if r.get("instr") in TAIL_INSTR:
            q = last_question(r.get("content"))
            if q:
                last_qs.append(q)
            else:
                no_q += 1
    lens = [eojeol_count(q) for q in last_qs]
    short_qs = [q for q in last_qs if eojeol_count(q) < SHORT_Q_EOJEOL]

    # ── 깨진 문장·속 판단 ──
    broken: dict[str, list[str]] = {"a": [], "b": [], "c": [], "d": []}
    inner: list[tuple[str, str]] = []
    for r in coach_rows:
        for s in sentences(r.get("content")):
            k = classify_broken(s)
            if k:
                broken[k].append(s)
            pat = inner_judgment_hit(s)
            if pat:
                inner.append((s, pat))

    # ── 원장: 사례·훑는 질문 ──
    episodes = ledger.get("episodes") if isinstance(ledger.get("episodes"), dict) else {}
    ep_turns: list[str] = []
    close_dist: Counter = Counter()
    sweeps: list[dict] = []
    for ch, eps in episodes.items():
        parts = []
        for e in eps or []:
            if not isinstance(e, dict):
                continue
            if (e.get("kind") or "episode") == "sweep":
                sweeps.append(e)
                continue
            st = e.get("status")
            close_dist[str(st)] += 1
            parts.append(f"{e.get('leader_turns')}" + (f"({st})" if st in NO_CASE_STATUS else ""))
        if parts:
            ep_turns.append(f"{chapter_short(ch)} {','.join(parts)}")
    sweep_follow = sum(1 for e in sweeps if (e.get("leader_turns") or 0) >= 2)
    sweep_case = sum(1 for e in sweeps if e.get("status") not in NO_CASE_STATUS)

    # ── 말투·지연·재생성 ──
    reg_cell, reg_raw = register_cell(name, coach_rows)
    totals = [float(_guard(r).get("total") or 0) for r in coach_rows if _guard(r).get("llm")]
    regen_rows = [r for r in coach_rows if _guard(r).get("regen_why")]
    regen_why: Counter = Counter()
    for r in regen_rows:
        why = _guard(r).get("regen_why")
        for w in (why if isinstance(why, (list, tuple)) else [why]):
            regen_why[str(w)] += 1
    format_miss = sum(1 for r in coach_rows if _guard(r).get("format_miss"))

    # ── (P13d) 끝맺음별 사용 횟수 · 첫 꼬리 질문 · 받는 말 탈락 ──
    endings: dict[str, Counter] = {}
    for r in coach_rows:
        ch = r.get("chapter")
        if not ch:
            continue
        for q in question_sentences(r.get("content")):
            k = request_ending_key(q)
            if k:
                endings.setdefault(ch, Counter())[ending_label(k)] += 1
    fp_rows = [r for r in coach_rows if _guard(r).get("first_probe")]
    fp_mode = Counter(str(_guard(r).get("first_probe")) for r in fp_rows)
    fp_why = Counter(str(_guard(r).get("first_probe_why")) for r in fp_rows if _guard(r).get("first_probe") == "fallback")
    fp_secs = [float(_guard(r).get("first_probe_s")) for r in fp_rows if _guard(r).get("first_probe_s") is not None]
    fp_cut = [str(_guard(r).get("first_probe_cut")) for r in fp_rows if _guard(r).get("first_probe_cut")]
    recv_cut = [c for r in coach_rows for c in (_guard(r).get("recv_allow") or []) if isinstance(c, (list, tuple)) and len(c) >= 2]

    cases, warnings = build_cases(rows, ledger)
    src_lines, src_summary = strong_sources(cases, ledger)

    return {
        "label": label or name, "coach": name,
        "tail_n": len(tails), "reask_n": len(reasks),
        "action_slot": action_slot, "action_sentence": len(action_sent_rows),
        "no_slot_n": len(no_slot), "no_slot_action": no_slot_action,
        "third_n": third_turns, "third_questions": third_qs,
        "q_n": len(last_qs), "q_none": no_q, "q_avg": (sum(lens) / len(lens)) if lens else None,
        "q_short_n": len(short_qs), "q_short": short_qs,
        "broken": broken, "broken_total": sum(len(v) for v in broken.values()),
        "inner": inner,
        "ep_turns": ep_turns, "close_dist": dict(close_dist),
        "sweep_follow": sweep_follow, "sweep_case": sweep_case, "sweep_total": len(sweeps),
        "register_cell": reg_cell, "register_raw": reg_raw,
        "llm_turns": len(totals), "p50": percentile(totals, 0.5), "p95": percentile(totals, 0.95), "max": max(totals) if totals else None,
        "regen_turns": len(regen_rows), "regen_why": dict(regen_why),
        "format_miss": format_miss,
        "endings": {ch: dict(c) for ch, c in endings.items()},
        "fp_mode": dict(fp_mode), "fp_why": dict(fp_why), "fp_sec_avg": (sum(fp_secs) / len(fp_secs)) if fp_secs else None, "fp_cut": fp_cut,
        "recv_cut": recv_cut, "recv_cut_why": dict(Counter(str(c[0]) for c in recv_cut)),
        "cost_usd": data.get("cost_usd"), "turns": data.get("turns"),
        "cases": cases, "warnings": warnings, "sources": src_lines, "source_summary": src_summary,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 출력
# ══════════════════════════════════════════════════════════════════════════════
def _cell(v) -> str:
    """표 칸에 넣을 문자열(세로줄·줄바꿈 제거)."""
    return str(v).replace("|", "/").replace("\n", " ")


def _num(v) -> str:
    return "-" if v is None else (f"{v:.1f}" if isinstance(v, float) else str(v))


def _dist(d: dict) -> str:
    return " · ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))) or "-"


def summary_rows(res: dict) -> list[tuple[str, str]]:
    """(1) 표의 (항목, 값) 줄."""
    b = res["broken"]
    q_avg = "-" if res["q_avg"] is None else f"{res['q_avg']:.1f}"
    q_note = f" (질문 {res['q_n']}개" + (f", 질문 없는 턴 {res['q_none']}" if res["q_none"] else "") + ")"
    lat = f"{_num(res['p50'])} / {_num(res['p95'])} / {_num(res['max'])} (LLM 턴 {res['llm_turns']})"
    regen = f"{res['regen_turns']}" + (f" ({_dist(res['regen_why'])})" if res["regen_why"] else "")
    end_top = " / ".join(f"{chapter_short(ch)} {max(c.items(), key=lambda kv: kv[1])[0]} {max(c.values())}" for ch, c in res["endings"].items() if c) or "-"
    fp = (f"llm {res['fp_mode'].get('llm', 0)} · fallback {res['fp_mode'].get('fallback', 0)}"
          + (f" ({_dist(res['fp_why'])})" if res["fp_why"] else "")
          + (f" · 평균 {res['fp_sec_avg']:.1f}초" if res["fp_sec_avg"] is not None else ""))
    recv = f"{len(res['recv_cut'])}" + (f" ({_dist(res['recv_cut_why'])})" if res["recv_cut"] else "")
    return [
        ("꼬리 질문 수(다시 묻기 제외)", str(res["tail_n"])),
        ("다시 묻기 턴 수", str(res["reask_n"])),
        ("그중 리더 행동을 묻는 것: ask_slot 기준(문장 기준)", f"{res['action_slot']}({res['action_sentence']})"),
        ("└ ask_slot 없는 꼬리 질문 턴 중 문장 기준 행동 질문", f"{res['no_slot_n']}턴 중 {res['no_slot_action']}"),
        ("제3자 장면을 묻는 것", str(res["third_n"])),
        ("질문 평균 어절 수(꼬리+다시 묻기, 마지막 질문 문장)", q_avg + q_note),
        (f"{SHORT_Q_EOJEOL}어절 미만 질문 수", str(res["q_short_n"])),
        ("깨진 문장·조각 수(합계)", str(res["broken_total"])),
        ("└ (a) 의문사 뒤 평서 감탄 어미", str(len(b["a"]))),
        ("└ (b) 서술어 없는 조각", str(len(b["b"]))),
        ("└ (c) 쉼표·연결어미로 끝남", str(len(b["c"]))),
        ("└ (d) 지시어 바로 뒤에 서술어", str(len(b.get("d") or []))),
        ("속 판단 노출 수", str(len(res["inner"]))),
        ("사례당 리더 턴 수(원장, 사례만)", " / ".join(res["ep_turns"]) or "-"),
        ("사례 닫힌 사유 분포", _dist(res["close_dist"])),
        ("훑는 질문: 꼬리 질문 한 칸 / 사례 나온 칸 / 전체", f"{res['sweep_follow']} / {res['sweep_case']} / {res['sweep_total']}"),
        ("말투 혼용 문장 수(Lucas 는 해요/합쇼 문장 수)", res["register_cell"]),
        ("p50 / p95 / 최대(초)", lat),
        ("재생성 걸린 턴 수(사유별)", regen),
        ("형식미해결 수", str(res["format_miss"])),
        ("끝맺음별 사용 횟수(영역별 최다)", end_top),
        ("첫 꼬리 질문 llm / fallback(사유) · 전용 호출 평균", fp),
        ("받는 말 탈락 문장 수(사유별)", recv),
        ("실제 USD", "-" if res["cost_usd"] is None else str(res["cost_usd"])),
        ("턴 수", _num(res["turns"])),
    ]


def render_summary(results: list[dict]) -> list[str]:
    out = ["## (1) 코치별 점검표", ""]
    out.append("| 항목 | " + " | ".join(_cell(r["label"]) for r in results) + " |")
    out.append("|---|" + "---|" * len(results))
    table = [summary_rows(r) for r in results]
    for i, (name, _) in enumerate(table[0]):
        out.append(f"| {name} | " + " | ".join(_cell(t[i][1]) for t in table) + " |")
    out.append("")
    return out


def render_cases(res: dict) -> list[str]:
    out = [f"## (2) 사례별 표 — {res['label']}", ""]
    for w in res["warnings"]:
        out.append(f"> 경고: {w}")
    if res["warnings"]:
        out.append("")
    out.append("| 영역 | 사례 | 여는 칸 | 리더 턴 | 닫힌 사유 | 직접 한 말·조치 발화(여는 답 + 꼬리 = 합) | strong 라벨 칸 |")
    out.append("|---|---|---|---|---|---|---|")
    short_all = short_case = n_case = 0
    for c in res["cases"]:
        has_case = c["status"] not in NO_CASE_STATUS
        miss = c["direct_total"] < DIRECT_TARGET
        short_all += miss
        n_case += has_case
        short_case += miss and has_case
        direct = f"여는 답 {c['direct_open']} + 꼬리 {c['direct_tail']} = {c['direct_total']}" + (" (미달)" if miss else "")
        out.append(f"| {chapter_short(c['chapter'])} | {c['marker']} | {_cell(c['opener_sub'] or '-')} | {_num(c['leader_turns'])} | "
                   f"{_cell(c['status'] or '-')} | {direct} | {_cell(', '.join(c['strong_subs']) or '-')} |")
    out.append("")
    out.append(f"목표(사례당 합 {DIRECT_TARGET} 이상) 미달: 전체 {len(res['cases'])}개 중 {short_all}개 · "
               f"사례가 나온 것(no_case·repeat 제외) {n_case}개 중 {short_case}개")
    out.append("")
    return out


def render_sources(res: dict) -> list[str]:
    out = [f"## (3) strong 근거 인용의 출처 — {res['label']}", ""]
    out.append("| 영역 | 칸 | 사례 | 출처 | 근거 인용 |")
    out.append("|---|---|---|---|---|")
    for x in res["sources"]:
        q = x["quote"] if len(x["quote"]) <= 60 else x["quote"][:60] + "…"
        out.append(f"| {chapter_short(x['chapter'])} | {_cell(x['sub'])} | {x['marker']} | {_cell(x['label'])} | {_cell(q)} |")
    s = res["source_summary"]
    out.append("")
    out.append(f"strong 칸 {s['cells']}개 중 근거가 여는 답에서만 나온 칸 {s['open_only']}개 "
               f"(꼬리 답 근거가 있는 칸 {s['has_tail']}개 · 근거 인용 {s['quotes']}개 중 못 찾음 {s['not_found']}개)")
    out.append("")
    return out


def render_detail(res: dict) -> list[str]:
    out = [f"## 상세 — {res['label']}", ""]
    names = {"a": "(a) 의문사 뒤 평서 감탄 어미", "b": "(b) 서술어 없는 조각", "c": "(c) 쉼표·연결어미로 끝남", "d": "(d) 지시어 바로 뒤에 서술어"}
    out.append(f"### 깨진 문장·조각 {res['broken_total']}개")
    for k in ("a", "b", "c"):
        out.append(f"- {names[k]} {len(res['broken'][k])}개")
        out.extend(f"  - {s}" for s in res["broken"][k])
    out.append("")
    out.append(f"### 속 판단 노출 {len(res['inner'])}개")
    out.extend(f"- {s}  ← `{pat}`" for s, pat in res["inner"])
    out.append("")
    if "violations" in res["register_raw"]:
        out.append(f"### 말투 혼용 문장 {len(res['register_raw']['violations'])}개")
        out.extend(f"- {s}" for s in res["register_raw"]["violations"])
        out.append("")
    out.append(f"### 제3자 장면 질문 {len(res['third_questions'])}개")
    out.extend(f"- {s}" for s in res["third_questions"])
    out.append("")
    out.append(f"### {SHORT_Q_EOJEOL}어절 미만 질문 {res['q_short_n']}개")
    out.extend(f"- ({eojeol_count(s)}어절) {s}" for s in res["q_short"])
    out.append("")
    out.append("### 끝맺음별 사용 횟수(영역별 전체)")
    for ch, c in res["endings"].items():
        out.append(f"- {chapter_short(ch)}: {_dist(c)}")
    out.append("")
    out.append(f"### 첫 꼬리 질문에서 떨어진 LLM 질문 {len(res['fp_cut'])}개")
    out.extend(f"- {s}" for s in res["fp_cut"])
    out.append("")
    out.append(f"### 받는 말 탈락 {len(res['recv_cut'])}개")
    out.extend(f"- ({c[0]}) {c[1]}" for c in res["recv_cut"])
    out.append("")
    out.append("### '직접 한 말·조치' 판정 근거(사례별)")
    for c in res["cases"]:
        out.append(f"- {chapter_short(c['chapter'])} {c['marker']} — 합 {c['direct_total']}")
        for lab, ev in c["direct_evidence"]:
            out.append(f"  - {lab}: " + " / ".join(ev))
    out.append("")
    return out


def render(results: list[dict], detail: bool = False) -> str:
    out = ["# 회귀 점검표", ""]
    out.extend(render_summary(results))
    for res in results:
        out.extend(render_cases(res))
        out.extend(render_sources(res))
        if detail:
            out.extend(render_detail(res))
    return "\n".join(out).rstrip() + "\n"


def make_labels(paths: list[str], datas: list[dict]) -> list[str]:
    """열 이름: '코치(tag)'. 같은 이름이 겹치면 순번을 붙인다."""
    labels = [f"{coach_name(d)}({file_tag(p)})" for p, d in zip(paths, datas)]
    seen: Counter = Counter()
    out = []
    for lb in labels:
        seen[lb] += 1
        out.append(lb if labels.count(lb) == 1 else f"{lb}#{seen[lb]}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="코치별 회귀 점검표(시뮬 결과 읽기 전용 집계)")
    ap.add_argument("files", nargs="+", help="sim_result_<tag>_<coach>.json 파일(여러 개 가능)")
    ap.add_argument("--detail", action="store_true", help="깨진 문장·속 판단 노출 등 해당 문장을 목록으로 덧붙인다")
    args = ap.parse_args(argv)
    datas = []
    for p in args.files:
        with open(p, encoding="utf-8") as f:
            datas.append(json.load(f))
    labels = make_labels(args.files, datas)
    results = [analyze(d, lb) for d, lb in zip(datas, labels)]
    sys.stdout.write(render(results, detail=args.detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
