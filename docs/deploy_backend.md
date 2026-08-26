# 백엔드 배포 가이드 (Render) — 초보자용

FastAPI 백엔드를 Render에 올려 인터넷에서 항상 접속되게 한다. DB는 기존 Supabase를
그대로 쓴다(데이터 유지).

> ✅ **현재 상태**: 백엔드는 이미 Render에 **수동 생성된 서비스**로 배포돼 있다
> (`https://new-diagnosis-api.onrender.com`). 따라서 아래 **A·B(Blueprint 생성)는
> 이미 끝난 단계**이며, 지금 필요한 것은 **C(환경변수 점검) · E(Vercel 연결) ·
> D/최신코드 확인**이다. `render.yaml`은 수동 서비스와 혼동을 피하려고 저장소에서
> 제외했다(수동 서비스는 render.yaml을 자동 적용하지 않는다). 새로 처음부터 만들
> 때만 A·B가 필요하다.
>
> **배포 방식**: Render 서비스가 GitHub `main`을 추적한다. 코드를 push하면 (Auto-Deploy
> 설정에 따라) 자동 배포되거나, 대시보드에서 **Manual Deploy → Deploy latest commit**
> 을 눌러 배포한다. 시작 명령·헬스체크는 아래 참고.
>
> **서비스 설정 참고값**(수동 서비스에 이미 반영돼 있어야 함):
> - Start Command: `uvicorn diag_project.main:app --host 0.0.0.0 --port $PORT`
> - Health Check Path: `/docs`
> - Branch: `main`

> ⚠️ 이 작업 전, 반영할 백엔드 커밋을 GitHub에 push해 둘 것(게이트·self-eval 수정 등).

---

## A. Render 계정 만들기 (~5분)
1. https://render.com 접속 → **Get Started** → **GitHub로 로그인(Sign in with GitHub)**.
2. Render가 GitHub 접근 권한을 요청 → **Authorize**.
3. 저장소 접근 화면에서 `new_diagnosis_api` 저장소를 **선택 허용**(All repositories 또는 Only select → new_diagnosis_api).

## B. Blueprint로 서비스 생성 (~5분)
1. Render 대시보드 우상단 **New +** → **Blueprint**.
2. 저장소 목록에서 **`new_diagnosis_api`** 선택 → **Connect**.
3. Render가 `render.yaml`을 자동 인식하고 서비스 이름 `diagnosis-api`, 시작 명령 등을
   미리 채워 보여준다 → 화면 하단 **Apply**.
4. (플랜) 기본은 `starter`(월 유료, 슬립 없음). 무료로 하려면 서비스 설정에서 Instance
   Type을 Free로 바꿀 수 있으나 **아래 F(무료 슬립) 경고**를 반드시 확인.

## C. 환경변수 입력 (~5분) — 가장 중요
Apply 직후(또는 서비스 → **Environment** 탭)에서 아래 값을 **직접 입력**한다.
값은 리더님이 준비(제가 목록·형식만 안내):

| Key | 값 형식/설명 |
|---|---|
| `DATABASE_URL` | 기존 Supabase 접속 URL. **반드시 `postgresql+asyncpg://...` 형식**. (기존 `.env`의 값 그대로) |
| `SECRET_KEY` | 길고 무작위인 문자열. 터미널: `openssl rand -hex 32` 결과를 붙여넣기. |
| `GEMINI_API_KEYS` | Gemini API 키(쉼표로 여러 개 가능). 기존 `.env` 값. |
| `USE_PHASE3A` | `false` (이미 render.yaml에 기본값 있음 — 확인만) |
| `PYTHON_VERSION` | `3.12` (render.yaml에 있음 — 확인만) |

> `ANALYSIS_OUTER_RUNS=3`, `GROUP_CODE_ENFORCED=true`는 render.yaml에 이미 있음.
> 입력 후 **Save Changes** → 자동으로 다시 배포된다.

## D. 배포 성공 확인 (~5~10분 빌드)
1. 서비스 페이지 상단 상태가 **"Live"**(초록)가 되면 성공.
2. 화면에 뜨는 서비스 주소(예: `https://diagnosis-api-xxxx.onrender.com`)를 클릭 →
   뒤에 `/docs`를 붙여 접속(`.../docs`) → **FastAPI 문서 페이지가 뜨면 정상**.
3. 이 **서비스 주소가 백엔드 주소**다. E단계에서 프론트에 연결한다.

## E. 배포 후 필수 연결 작업
1. **Vercel에 백엔드 주소 연결**:
   - Vercel → `diagnosis-frontend` → **Settings → Environment Variables**.
   - `NEXT_PUBLIC_API_URL` 항목을 찾는다.
     - 있으면 **Edit** → 값을 `https://<Render주소>/api/v1` 로 **덮어쓰기**(끝에 `/api/v1` 필수).
     - 없으면 **Add New**로 같은 이름·값 추가(Environment: Production 체크).
   - 저장 후 **프론트를 재배포**해야 반영됨(Vercel → Deployments → 최신 → Redeploy).
   - > Secret이라 기존 값이 안 보여도 괜찮다. **새 값으로 덮어쓰면 된다.**
2. **CORS 확인**: 백엔드는 기본적으로 `https://fm.connectn.co.kr`를 허용하도록 되어 있다
   (추가 조치 불필요). 다른 도메인을 쓰면 `CORS_ALLOWED_ORIGINS`에 추가.
3. **최신 코드 반영 확인**: 백엔드 주소 `/docs`에서 `POST /participants/token`을 열어
   무효 그룹코드로 시도 → **403**이면 게이트(최신 코드) 반영됨. `.../coaches` 응답의
   `avatar_url`이 `/images/...`(127.0.0.1 아님)이면 avatar 수정 반영됨.

## F. 무료 플랜의 함정 (반드시 확인)
- **Render 무료(Free)는 15분간 요청이 없으면 서버가 '슬립'**한다. 깨어날 때
  **30~60초 콜드스타트**가 걸린다.
- 파일럿 세션은 40~70분. 대화 중엔 요청이 이어져 슬립되지 않지만, **참가자가 중간에
  15분 이상 멈추면** 다음 응답이 크게 지연된다.
- → **파일럿은 `starter`(슬립 없음, 월 $7 수준) 권장.** 첫 참가자 전에 최소 starter로.

## G. 실패하면 로그 보기
- 서비스 페이지 → **Logs** 탭. 빌드 실패는 빨간 메시지, 실행 오류는 스택트레이스가 뜬다.
- 자주 나는 원인: `DATABASE_URL` 형식 오류(asyncpg 아님), `GEMINI_API_KEYS` 미입력,
  `SECRET_KEY` 미입력. → C단계 재확인.
- 긴 분석(리포트 생성)은 수 분 걸린다 — 그 사이 요청이 도는 것은 정상.

---

## 참고: 로컬 백엔드 끄기/켜기 (백엔드 위치 확정 테스트용)
- **지금 도는지 확인**: 터미널에서 `lsof -ti:8000` → 숫자가 나오면 실행 중.
- **끄기**: 백엔드를 실행 중인 터미널 창에서 **Ctrl+C**. (또는 `kill $(lsof -ti:8000)`)
- **다시 켜기**: 백엔드 폴더(`new_diagnosis_api`)에서
  `uvicorn diag_project.main:app --reload` (기존에 쓰던 실행 명령이 있으면 그것).
- **테스트**: 끈 상태에서 fm.connectn.co.kr이 멈추면 → **백엔드=로컬 확정**. 다시 켜면 복구.
  (위험 없음. 단 그 사이 접속자에겐 잠시 끊김.)
