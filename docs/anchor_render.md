# 앵커 렌더링 플래그 (ANCHOR_RENDER) — 2026-10-21 결정: 기본 off(dict)

- `ANCHOR_RENDER=dict`(기본): 앵커 질문은 `SUBCOMPETENCY_ANCHOR_QUESTIONS` 사전 문장. 운영은 이 모드.
- `ANCHOR_RENDER=llm`: 직전 2턴 + role_summary + `SUBCOMPETENCY_MUST_ASK` 로 1문장 렌더링 → 형식 검사 → flash 판정 → 불합격이면 사전 폴백.
  10/21 조직관리 재생(gemini·claude)에서 must_ask 키워드를 그대로 나열하고 한 문장에 두 가지를 묻는 긴 질문이 나와 보류.

재개 조건 두 줄:
1. must_ask 를 "담을 것" 지시가 아니라 판정 기준으로만 쓰도록 프롬프트를 바꾸고, 렌더 질문이 사전 문장보다 짧거나 같은 길이로 나올 것.
2. 폴백 중복 검사가 렌더 앵커까지 포함해(같은 타겟의 사전 문장을 다음 턴에 다시 묻지 않도록) 통과할 것. 두 조건 모두 4벌 재생으로 확인한 뒤 켠다.
