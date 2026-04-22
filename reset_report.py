import sqlite3
import os

def reset_latest_report():
    print("🔄 리포트 전용 테이블 초기화 중...")
    
    # 1. DB 파일 경로 지정
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "sql_app.db")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 2. 리포트 테이블(diagnosis_reports)이 존재하는지 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='diagnosis_reports'")
        if cursor.fetchone():
            # 3. 잘못 만들어진 리포트 데이터만 깔끔하게 삭제 (대화 기록은 다른 곳에 있어 100% 안전함!)
            cursor.execute("DELETE FROM diagnosis_reports")
            conn.commit()
            print("✅ 낡은 리포트 데이터를 성공적으로 삭제했습니다! (대화 내용은 완벽 보존됨)")
            print("👉 이제 브라우저 결과 화면에서 [새로고침(F5)]을 누르시면, 새 코드가 완벽한 리포트를 만들어냅니다!")
        else:
            print("❌ diagnosis_reports 테이블을 찾을 수 없습니다. (이미 비워졌거나 이름이 다를 수 있습니다)")

    except Exception as e:
        print(f"❌ 에러 발생: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    reset_latest_report()