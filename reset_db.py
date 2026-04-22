# reset_db.py
import os
import asyncio
from seed import seed_data

def force_reset():
    print("🔄 데이터베이스 강제 초기화를 시작합니다...")
    
    # 1. 기존 DB 파일 강제 삭제
    db_file = "diagnosis.db"
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
            print(f"🗑️  기존 {db_file} 파일을 삭제했습니다.")
        except Exception as e:
            print(f"❌ 삭제 실패 (파일이 사용 중일 수 있습니다): {e}")
            return
    else:
        print(f"⚠️  {db_file} 파일이 없습니다. (새로 생성합니다)")

    # 2. 시드 데이터 다시 채우기 (Ella 생성)
    print("🌱 Ella(엘라) 데이터를 심는 중...")
    try:
        asyncio.run(seed_data())
        print("✅ 모든 작업 완료! 이제 서버를 켜면 Ella가 보입니다.")
    except Exception as e:
        print(f"❌ 시딩 실패: {e}")

if __name__ == "__main__":
    force_reset()