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