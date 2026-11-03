from functools import wraps
from rest_framework import status
from rest_framework.response import Response
from .token import AuthUnavailable, TokenRejected, verify_jwt
import logging

logger = logging.getLogger(__name__)


def _unauthorized(detail):
    # DRF 의 AuthenticationFailed 는 인증 클래스가 없으면 401 이 403 으로 바뀐다.
    # 토큰 문제는 401 로 분명하게 알려서 앱이 "권한 없음(403)"과 구분하게 한다. body 의 detail 은 예전과 같은 형식이다.
    return Response(
        {"detail": detail, "error": "unauthorized"},
        status=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )


def token_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning("토큰 없음 - Authorization 헤더 누락")
            return _unauthorized("Token is required")

        token = auth_header.split(" ")[1]
        try:
            user_info = verify_jwt(token)
            request._user = user_info
        except TokenRejected as e:
            logger.warning(f"토큰 검증 실패: {e}")
            return _unauthorized(str(e))
        except AuthUnavailable as e:
            # 서버가 검증하지 못한 것이다. 앱은 로그아웃하지 말고 잠시 뒤 다시 시도해야 한다.
            logger.error(f"토큰 검증 불가 (서버 쪽 문제): {e}")
            return Response(
                {"detail": "Authentication service temporarily unavailable", "error": "auth_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"Retry-After": "5"},
            )

        return view_func(request, *args, **kwargs)

    return _wrapped_view
