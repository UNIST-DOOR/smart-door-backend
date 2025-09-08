from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
ENV = os.environ.get("APP_ENV", "development").lower()
DEBUG = ENV == "development"

if DEBUG:
    SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-secret-key")
else:
    SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

if DEBUG:
    ALLOWED_HOSTS = [
        "localhost",
        "192.168.0.24",
        # "192.168.219.102"
    ]
else:
    ALLOWED_HOSTS = [
        "smartdoor-backend.unist.ac.kr",
        "smartdoor-backend.unist.re.kr",
    ]


# Application definition

INSTALLED_APPS = [
    "rest_framework",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "smartdoor.middleware.SetRemoteAddrFromForwardedFor",
    "smartdoor.middleware.MinBuildVersionMiddleware",
]

ROOT_URLCONF = "smartdoor.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "smartdoor.wsgi.application"


# Database (MySQL, env-driven)
# 운영/개발 공통으로 환경변수로 구성
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DB", "commax_mqtt"),
        "USER": os.environ.get("MYSQL_USER", "root"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
        "HOST": os.environ.get("MYSQL_HOST", "localhost"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "OPTIONS": {
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = "ko-kr"

TIME_ZONE = "Asia/Seoul"

USE_I18N = True

USE_TZ = True


# (Static/Media 미사용)

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "level": "INFO",  # INFO 이상의 로그를 출력하도록 설정
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console"],
            "level": "INFO",  # 최상위 로거에 대한 레벨 설정
            "propagate": True,
        },
    },
}

# DRF 최소 의존 설정: Django auth(AnonymousUser) 및 기본 인증 비활성화
REST_FRAMEWORK = {
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
}

# 최소 허용 안드로이드 빌드(버전코드). 환경변수 MIN_ANDROID_BUILD로 제어
MIN_ANDROID_BUILD = int(os.environ.get("MIN_ANDROID_BUILD", "1"))
MIN_IOS_BUILD = int(os.environ.get("MIN_IOS_BUILD", "1"))

# AUTHENTICATION_BACKENDS = ("django_auth_adfs.backend.AdfsAuthCodeBackend",)

# Configure django to redirect users to the right URL for login
# AUTH_USER_MODEL = "auth.User"
# LOGIN_URL = "django_auth_adfs:login"
# LOGOUT_URL = "django_auth_adfs:logout"
# LOGIN_REDIRECT_URL = "/oauth2/login_success"
# LOGOUT_REDIRECT_URL = "/"


SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# 개발 환경에서는 HTTPS로 강제 리다이렉트를 비활성화하여 로컬 HTTP 접근을 허용
SECURE_SSL_REDIRECT = not DEBUG

# SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# SESSION_COOKIE_AGE = 86400  # 1 day, in seconds
# SESSION_COOKIE_SECURE = True  # HTTPS 환경에서만 세션 쿠키가 전달되도록 설정
# SESSION_COOKIE_SAMESITE = "None"  # Cross-site 요청에서 쿠키 전달 허용

USE_X_FORWARDED_HOST = True

# 파일 업로드 용량 제한 20GB로 설정
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024 * 1024  # 20GB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000  # 최대 필드 수 설정 (필요에 따라 조정)
DATA_UPLOAD_MAX_SIZE = (
    20 * 1024 * 1024 * 1024
)  # 최대 업로드 크기 설정 (필요에 따라 조정)
