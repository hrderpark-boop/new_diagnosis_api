"""Claude 5.5 API 제약 실호출 확인 (2026-10-15 ■2) — 운영자가 ANTHROPIC_API_KEY 를 가진 환경에서 실행한다.

확인 항목(각 1회 호출, 최소 토큰):
  1) Haiku 5.5  thinking=disabled + temperature=0      → 문서상 400 (temperature 는 1 만 허용)
  2) Haiku 5.5  thinking=disabled, temperature 생략    → 200 (우리 코치 턴 설정)
  3) Sonnet 5.5 thinking=disabled                      → 문서상 400 (disabled 거부, between_tools 사용)
  4) Sonnet 5.5 thinking=between_tools + temperature=0 → 문서상 400
  5) Sonnet 5.5 thinking 생략(adaptive), temperature 생략 → 200 (우리 분석 설정)
용법: ANTHROPIC_API_KEY=... python tools/claude_probe.py
결과가 문서와 다르면(예: 1 또는 4 가 200) llm_provider.build_request 에 temperature=0 을 되살린다.
"""
import os
import sys

import anthropic

CASES = [
    # anthropic SDK 1.14 은 temperature 키워드 자체를 제거했다(TypeError) → API 응답을 보기 위해 extra_body 로 실어 보낸다.
    ("1 Haiku disabled + temperature=0", dict(model="claude-haiku-5-5", thinking={"type": "disabled"}, extra_body={"temperature": 0.0})),
    ("2 Haiku disabled (temperature 생략)", dict(model="claude-haiku-5-5", thinking={"type": "disabled"})),
    ("3 Sonnet disabled", dict(model="claude-sonnet-5-5", thinking={"type": "disabled"})),
    ("4 Sonnet between_tools + temperature=0", dict(model="claude-sonnet-5-5", thinking={"type": "between_tools"}, extra_body={"temperature": 0.0})),
    ("6 Sonnet between_tools (temperature 생략)", dict(model="claude-sonnet-5-5", thinking={"type": "between_tools"})),
    ("5 Sonnet adaptive (temperature 생략)", dict(model="claude-sonnet-5-5")),
]


def main() -> int:
    if not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        print("ANTHROPIC_API_KEY 가 없습니다.")
        return 2
    client = anthropic.Anthropic(max_retries=0)
    for label, kw in CASES:
        try:
            r = client.messages.create(max_tokens=64, messages=[{"role": "user", "content": "한 단어로 인사"}], **kw)
            text = "".join(b.text for b in r.content if b.type == "text")
            print(f"  200  {label:<42} stop={r.stop_reason} text={text[:20]!r}")
        except anthropic.APIStatusError as e:
            msg = str(getattr(e, "message", e))
            print(f"  {e.status_code}  {label:<42} {msg[:220]}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERR  {label:<42} {type(e).__name__}: {str(e)[:140]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
