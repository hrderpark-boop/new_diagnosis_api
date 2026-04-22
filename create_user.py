# create_user.py
import sqlite3
import datetime
import bcrypt # passlib 대신 bcrypt 직접 사용

# 1. 비밀번호 해싱 (bcrypt 직접 사용으로 호환성 문제 해결)
password = "password"
# bcrypt는 bytes 타입을 원하므로 encode() 필요
hashed_bytes = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
# DB에는 문자열(str)로 저장해야 하므로 decode() 필요
hashed_password = hashed_bytes.decode('utf-8')

db_file = "sql_app.db"
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

print(f"📂 DB 연결: {db_file}")

try:
    # 2. 그룹(G-TEST)이 있는지 확인하고 없으면 생성
    group_code = "G-TEST"
    cursor.execute("SELECT id FROM groups WHERE group_code = ?", (group_code,))
    group = cursor.fetchone()
    
    if not group:
        print(f"✨ 그룹 '{group_code}' 생성 중...")
        cursor.execute("INSERT INTO groups (name, group_code, created_at, updated_at) VALUES (?, ?, ?, ?)", 
                       ("테스트 그룹", group_code, datetime.datetime.now(), datetime.datetime.now()))
        conn.commit()
        group_id = cursor.lastrowid
    else:
        print(f"✅ 그룹 '{group_code}' 이미 존재함.")
        group_id = group[0]

    # 3. 사용자(test@example.com)가 있는지 확인
    email = "test@example.com"
    cursor.execute("SELECT id FROM participants WHERE email = ?", (email,))
    user = cursor.fetchone()

    if user:
        # 이미 있으면 비밀번호만 'password'로 강제 초기화
        print(f"🔄 사용자 '{email}' 비밀번호 초기화 중...")
        cursor.execute("UPDATE participants SET password_hash = ?, group_code = ?, group_id = ? WHERE email = ?", 
                       (hashed_password, group_code, group_id, email))
    else:
        # 없으면 새로 생성
        print(f"✨ 사용자 '{email}' 새로 생성 중...")
        cursor.execute("""
            INSERT INTO participants 
            (email, name, password_hash, group_code, group_id, gender, age_group, is_active, created_at, updated_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (email, "테스트유저", hashed_password, group_code, group_id, "male", "30s", 1, datetime.datetime.now(), datetime.datetime.now()))

    conn.commit()
    print("="*50)
    print("🎉 [계정 복구 완료]")
    print(f"📧 이메일: {email}")
    print(f"🔑 비밀번호: {password}")
    print(f"🏢 그룹코드: {group_code}")
    print("👉 이제 다시 로그인 해보세요!")
    print("="*50)

except Exception as e:
    print(f"❌ 오류 발생: {e}")
finally:
    conn.close()