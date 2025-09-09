# Nginx 도메인 설정 가이드

Docker 컨테이너 실행 후 도메인 연결하는 방법


## Nginx 설정

### 1. Nginx 설치
```bash
# root 계정에서 실행
apt update
apt install -y nginx
systemctl start nginx
systemctl enable nginx
```

### 2. Nginx 설정 파일 생성
```bash
nano /etc/nginx/sites-available/smartdoor
```

### 3. 설정 내용 작성
```nginx
server {
    listen 80;
    server_name smartdoor-backend.unist.ac.kr;  # 실제 사용 도메인

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 4. 설정 활성화
```bash
ln -s /etc/nginx/sites-available/smartdoor /etc/nginx/sites-enabled/
rm /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

### 5. 방화벽 설정
```bash
sudo ufw allow @@
sudo ufw allow ssh
sudo ufw enable
```

##  SSL 인증서 설정 (HTTPS)

###  **SSL 인증서 발급 실패 문제**

Let's Encrypt 자동 발급이 외부 접근 제한으로 실패하므로 다음 방법 중 선택:

#### 방법 1: 학교에서 SSL 파일 제공받기 
```bash
# SSL 파일을 받은 경우
mkdir -p /etc/ssl/smartdoor
mv ssl.crt /etc/ssl/smartdoor/
mv ssl.key /etc/ssl/smartdoor/
chmod 644 /etc/ssl/smartdoor/ssl.crt
chmod 600 /etc/ssl/smartdoor/ssl.key
```

#### 방법 2: Let's Encrypt (80포트 외부 접근 필요)
```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d smartdoor-backend.unist.ac.kr
```


## ✅ 확인

### HTTP 접근 (현재 동작 중)
```bash
curl http://smartdoor-backend.unist.ac.kr/api/db-health/
```

### HTTPS 접근 (SSL 설정 후)
```bash
curl https://smartdoor-backend.unist.ac.kr/api/db-health/
```

## 🎯 **최종 상태 및 추후 작업**

### ✅ **완료된 항목:**
- Docker 컨테이너 정상 실행
- Nginx 프록시 설정 완료
- HTTP API 정상 동작 (`http://smartdoor-backend.unist.ac.kr`)

### 🔄 **학교측 요청 필요:**
1. **SSL 인증서 제공** 또는 **80포트 외부 접근 허용**
2. **GitHub Actions 자동 배포**용 포트 개방:
   - 22번 포트 (SSH)
   - 443번 포트 (HTTPS)

## 🔧 관리 명령어

```bash
# Nginx 상태 확인
sudo systemctl status nginx

# Nginx 재시작
sudo systemctl restart nginx

# 설정 파일 테스트
sudo nginx -t

# 로그 확인
sudo tail -f /var/log/nginx/error.log
```
