## 운영 배포 가이드 (Docker)

### 1) .env 준비(같은 폴더에 배치)
현재 폴더의 `.env` 사용

### 2) 빌드
```
docker build -t smartdoor-backend:prod .
```

### 3) 실행(8000 포트)
```
docker rm -f smartdoor-backend || true
docker run -d --name smartdoor-backend --env-file .env -p 8000:8000 smartdoor-backend:prod
```

