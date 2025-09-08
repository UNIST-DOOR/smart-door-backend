FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 시스템 패키지(빌드용 gcc + mysqlclient 빌드 헤더)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    python3-dev \
    pkg-config \
    default-libmysqlclient-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
    
# 파이썬 의존성
COPY requirements.txt .
RUN pip install --upgrade pip setuptools && \
    pip install --no-cache-dir -r requirements.txt

# 앱 소스
COPY ./smartdoor ./smartdoor

EXPOSE 8000

# 운영: gunicorn로 실행 (smartdoor 패키지 기준)
CMD ["gunicorn", "--chdir", "/app/smartdoor", "smartdoor.wsgi:application", "-b", "0.0.0.0:8000", "-w", "3", "--threads", "2", "--timeout", "120"]