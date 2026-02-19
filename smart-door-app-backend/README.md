# 🚪 Smart Door Backend

React Native 앱을 위한 Azure AD 로그인 연동 백엔드 시스템

## 🏗️ 아키텍처

- **Django REST Framework** 기반
- **Azure AD JWT** 토큰 인증
- **MySQL** 데이터베이스 연동
- **Docker** 컨테이너화

## 🏃‍♂️ 로컬 개발

### 빠른 Docker 실행 (추천)
```bash
# 1. .env 파일 생성 (개발용)
cat > .env << 'EOF'
APP_ENV=development
MYSQL_HOST=210.114.17.118
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=oa-homs21
MYSQL_DB=commax_mqtt
AZURE_AD_TENANT_ID=e8715ec0-6179-432a-a864-54ea4008adc2
AZURE_AD_AUDIENCE=api://b157dbcc-ab7d-4f22-84d4-6286abd37c3d
DJANGO_SECRET_KEY=dev-secret-key
EOF

# 2. 기존 컨테이너 정리
docker rm -f smartdoor-backend

# 3. 이미지 빌드
docker build -t smartdoor-backend:dev .

# 4. 컨테이너 실행
docker run -d --name smartdoor-backend --env-file .env -e APP_ENV=development -p 8000:8000 smartdoor-backend:dev

# 5. 동작 확인
curl -i http://localhost:8000/api/db-health/
```

### Docker Compose로 실행
```bash
docker compose up -d --build
```

### 직접 실행 (Python)
```bash
# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정 후 실행
cd smartdoor
python manage.py runserver 0.0.0.0:8000
```

## 📡 API 엔드포인트

- `GET /api/db-health/` - 데이터베이스 헬스체크
- `GET /api/me/` - 현재 사용자 정보 (인증 필요)
- `GET /api/room-info/` - 사용자 방 정보 (인증 필요)

## 🔐 인증

Bearer 토큰 방식의 Azure AD JWT 토큰을 사용합니다:

```
Authorization: Bearer <azure_ad_access_token>
```

## 🚀 서버 배포

Ubuntu 서버 배포는 `DEPLOY_GUIDE.md`를 참고하세요.

## 🔧 관리 명령어

```bash
# 로그 확인
docker logs smartdoor-backend -f

# 컨테이너 재시작
docker restart smartdoor-backend

# 컨테이너 중지
docker stop smartdoor-backend
```




!!!!!! 다음에 문제 발생시 실행해야하는 코드

# 1. 서버 상태 확인
docker ps
docker stats smartdoor-backend --no-stream

# 2. Azure AD 관련 문제 확인
docker logs smartdoor-backend 2>&1 | grep -i "auth.token\|JWT"

# 3. DB 관련 문제 확인
docker logs smartdoor-backend 2>&1 | grep -i "auth.views\|OperationalError"

# 4. 전체 에러 확인
docker logs smartdoor-backend 2>&1 | grep -i "error\|warning" | tail -50

# 5. 특정 날짜 로그 확인 (예: 2026-02-19)
docker logs smartdoor-backend 2>&1 | grep "2026-02-19" | tail -100

# 6. 워커 타임아웃 확인
docker logs smartdoor-backend 2>&1 | grep -i "timeout\|exited"

# 7. 실시간 로그 모니터링 (Ctrl+C로 중단)
docker logs -f smartdoor-backend