# 🚀 Smart Door Backend 배포 가이드


## 📋 사전 준비

### 1. 서버 접속

### 2. 시스템 업데이트 및 기본 도구 설치
```bash
# root 계정이므로 sudo 제거
apt update && apt upgrade -y
apt install -y curl git nano python3 python3-pip netcat-openbsd
```

### 3. Docker 설치
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# root 계정인 경우 usermod 단계 건너뛰고 진행

systemctl start docker
systemctl enable docker
rm get-docker.sh

# Docker 작동 확인
docker --version
docker ps
```


### 4. Docker Compose 설치
```bash
apt-get update
apt-get install -y docker-compose-plugin

# 설치 확인
docker compose version
```

## 🔧 배포 과정

### 1단계: 프로젝트 클론
```bash
git clone [GITHUB_REPOSITORY_URL]
cd smart-door-app-backend
```


### 2단계: 환경변수 파일 생성
```bash
cat > .env << 'EOF'
# Smart Door Backend 환경변수

# App Configuration
APP_ENV=production
MIN_ANDROID_BUILD=1
MIN_IOS_BUILD=1

# MySQL Database Configuration
MYSQL_HOST=210.114.17.118
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=oa-homs21
MYSQL_DB=commax_mqtt

# Azure AD Configuration
AZURE_AD_TENANT_ID=e8715ec0-6179-432a-a864-54ea4008adc2
AZURE_AD_AUDIENCE=api://b157dbcc-ab7d-4f22-84d4-6286abd37c3d

# Django Configuration
DJANGO_SECRET_KEY=O_yC1HNHtiFhUuwtbY7JUXDOKZoT01qnLQ4KKvWx-0SWy4pasXCMv_rA
EOF
```

### 3단계: Docker 컨테이너 실행
```bash
docker compose down
docker compose up -d --build
```

> **: 첫 실행시 "Bad Request" 오류 발생 → ALLOWED_HOSTS 문제

### 4단계: 배포 확인 및 문제 해결
```bash
docker compose ps
curl http://localhost:8000/api/db-health/
```


#### **ALLOWED_HOSTS 오류 해결**
만약 "Invalid HTTP_HOST header" 오류 발생시:

```bash
# settings.py 수정
nano /path/to/smartdoor/smartdoor/settings.py

# ALLOWED_HOSTS에 localhost 추가 (운영환경에서도)
# 또는 APP_ENV=development로 변경
sed -i 's/APP_ENV=production/APP_ENV=development/' .env

# 컨테이너 재시작
docker compose restart
```

## 관리 명령어

```bash
# 로그 확인
docker compose logs -f

# 컨테이너 재시작
docker compose restart

# 컨테이너 중지
docker compose down

# 업데이트 (코드 변경시)
git pull origin main
docker compose up -d --build
```

## 문제 해결


## API 엔드포인트

- **헬스체크**: `GET http://서버IP:8000/api/db-health/`
