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

ENV APP_ENV="production"

ENV MIN_ANDROID_BUILD=1
ENV MIN_IOS_BUILD=1

# MySQL
ENV MYSQL_HOST="210.114.17.118"
ENV MYSQL_PORT="3306"
ENV MYSQL_USER="root"
ENV MYSQL_PASSWORD="oa-homs21"
ENV MYSQL_DB="commax_mqtt"

# Azure AD
ENV AZURE_AD_TENANT_ID="e8715ec0-6179-432a-a864-54ea4008adc2"
ENV AZURE_AD_AUDIENCE="api://b157dbcc-ab7d-4f22-84d4-6286abd37c3d"

# Django
ENV DJANGO_SECRET_KEY="O_yC1HNHtiFhUuwtbY7JUXDOKZoT01qnLQ4KKvWx-0SWy4pasXCMv__oP83JS6i_t6O5yyuxBONmPAEaCmv_rA"

# 파이썬 의존성
COPY requirements.txt .
RUN pip install --upgrade pip setuptools && \
    pip install --no-cache-dir -r requirements.txt

# 앱 소스
COPY ./smartdoor ./smartdoor

EXPOSE 8000

# 운영: gunicorn로 실행 (smartdoor 패키지 기준)
CMD ["gunicorn", "--chdir", "/app/smartdoor", "smartdoor.wsgi:application", "-b", "0.0.0.0:8000", "-w", "3", "--threads", "2", "--timeout", "120"]