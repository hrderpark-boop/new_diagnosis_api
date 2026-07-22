import asyncio
import httpx
import uuid
import pandas as pd
from google import genai
import time
import os
from dotenv import load_dotenv

# ==========================================
# 0. 보안 설정 (.env 로드)
# ==========================================
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    api_key = input("\n🔑 .env 파일을 찾지 못했습니다.\n여기에 Gemini API 키를 직접 붙여넣고 엔터를 치세요: ").strip()

if not api_key:
    print("❌ 키가 입력되지 않아 종료합니다.")
    exit()

client_gemini = genai.Client(api_key=api_key)

# ✅ 백엔드 진짜 주소 2개 (시작용, 대화용)
START_URL = "https://new-diagnosis-api.onrender.com/api/v1/diagnoses/start"
CHAT_URL = "https://new-diagnosis-api.onrender.com/api/v1/diagnoses/submit_message" 

LOG_DIR = "test_logs"
os.makedirs(LOG_DIR, exist_ok=True)
SEMAPHORE = asyncio.Semaphore(5) 

PERSONAS = {
    "성실한_팀장": "당신은 IT 회사의 성실하고 열정적인 5년차 팀장입니다. AI 코치의 질문에 구체적인 리더십 경험(STAR 기법)을 바탕으로 아주 상세하고 진지하게 3~4문장으로 대답합니다.",
    "단답형_불만자": "당신은 매우 바쁘고 피곤한 부장입니다. 진단이 귀찮아서 '네', '아니오', '그런 적 없습니다', '기억 안 납니다' 등 아주 짧고 불성실하게 대답합니다.",
    "동문서답_빌런": "당신은 엉뚱한 직원입니다. 리더십 진단 질문을 받아도, 갑자기 주식 이야기, 오늘 점심 메뉴, 기르고 있는 반려동물 이야기 등으로 주제를 돌리려 합니다.",
    "감정적_호소자": "당신은 최근 팀원들과의 갈등으로 스트레스가 극심한 리더입니다. 질문에 대한 논리적 답변보다는 자신의 억울함과 힘들다는 감정 토로에 집중합니다."
}

def generate_persona_reply(persona_prompt, ai_question, chat_history):
    prompt = f"{persona_prompt}\n[이전 대화 맥락]\n{chat_history}\n[AI 코치의 방금 질문]\n{ai_question}\n위 질문에 대해 1인칭 시점으로 한국어로 대답하세요."
    response = client_gemini.models.generate_content(model='gemini-2.5-flash', contents=prompt)
    return response.text.strip()

async def run_simulation(test_index, persona_name, persona_prompt, max_turns=15):
    async with SEMAPHORE:
        # ⚠️ 바로 이 부분입니다! DB에 있는 진짜 신분증 사용
        participant_id = "778ee6c1-a20c-4ab9-a4ed-3e7464d1f274" # 리더님의 진짜 ID (완료)
        template_id = "10000000-0000-0000-0000-000000000008" # 👈 이것만 채워주세요!
        coach_id = "10000000-0000-0000-0000-000000000011"
        
        results = {"test_no": test_index, "persona": persona_name, "session_id": None, "total_turns": 0, "status": "in_progress", "error": None, "log_file": ""}
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                # [STEP 1] 진단 세션 정상적으로 시작하기 (/start)
                start_payload = {
                    "coach_id": coach_id,
                    "participant_id": participant_id,
                    "template_id": template_id
                }
                start_res = await client.post(START_URL, json=start_payload)
                
                if start_res.status_code not in [200, 201]:
                    raise Exception(f"Start API 실패 ({start_res.status_code}): {start_res.text}")
                    
                start_data = start_res.json()
                real_session_id = start_data["session_id"]
                first_ai_msg = start_data["coach_response_message"]
                results["session_id"] = real_session_id
                
                print(f"🚀 [{persona_name}] 세션 정상 생성 완료 (ID: {real_session_id[:8]})")
                
                markdown_log = f"# 진단 테스트 리포트 #{test_index}\n- **성향**: {persona_name}\n- **세션 ID**: {real_session_id}\n========================================\n\n"
                markdown_log += f"🤖 **AI 코치 (첫 인사)**:\n> {first_ai_msg}\n\n"
                chat_context_for_llm = f"AI 코치: {first_ai_msg}\n"
                
                # [STEP 2] 주고받는 대화 루프 시작 (/submit_message)
                current_user_message = generate_persona_reply(persona_prompt, first_ai_msg, chat_context_for_llm)
                
                for turn in range(max_turns):
                    results["total_turns"] += 1
                    markdown_log += f"👤 **사용자 ({persona_name})**:\n> {current_user_message}\n\n"
                    chat_context_for_llm += f"사용자: {current_user_message}\n"
                    
                    # ⚠️ 백엔드 스펙에 맞게 'content'로 전송!
                    chat_payload = {
                        "session_id": real_session_id,
                        "content": current_user_message
                    }
                    
                    chat_res = await client.post(CHAT_URL, json=chat_payload)
                    if chat_res.status_code not in [200, 201]:
                        raise Exception(f"Chat API 실패 ({chat_res.status_code}): {chat_res.text}")
                        
                    chat_data = chat_res.json()
                    ai_reply = chat_data.get("coach_response_message", "")
                    
                    markdown_log += f"🤖 **AI 코치**:\n> {ai_reply}\n\n"
                    chat_context_for_llm += f"AI 코치: {ai_reply}\n"
                    print(f"  ↳ [{persona_name}] 턴 {results['total_turns']} 정상 수신")
                    
                    if chat_data.get("is_session_completed") or "[DIAGNOSIS_COMPLETE]" in ai_reply:
                        results["status"] = "completed"
                        break
                        
                    current_user_message = generate_persona_reply(persona_prompt, ai_reply, chat_context_for_llm)
                    await asyncio.sleep(2)
                    
            except Exception as e:
                results["status"] = "error"
                results["error"] = str(e)
                if 'markdown_log' not in locals():
                    markdown_log = f"# 오류 발생\n"
                markdown_log += f"\n\n❌ 상세 오류: {e}\n"
                print(f"❌ [{persona_name}] 에러 상세: {e}")
                
        safe_id = results['session_id'][:8] if results['session_id'] else 'error'
        file_name = f"{LOG_DIR}/{test_index:04d}_{persona_name}_{safe_id}.md"
        with open(file_name, "w", encoding="utf-8") as f: f.write(markdown_log)
        results["log_file"] = file_name
        print(f"✅ [{persona_name}] 대화 종료 -> 저장 완료")
        return results

async def main():
    print("🤖 엔터프라이즈급 AI 자동화 시뮬레이션 시작...")
    tasks, test_index = [], 1
    for _ in range(1):
        for name, prompt in PERSONAS.items():
            tasks.append(run_simulation(test_index, name, prompt))
            test_index += 1
    results = await asyncio.gather(*tasks)
    pd.DataFrame(results).to_csv("simulation_results.csv", index=False, encoding="utf-8-sig")
    print(f"\n✨ 테스트 완료! 'test_logs' 폴더를 열어보세요.")

if __name__ == "__main__": asyncio.run(main())