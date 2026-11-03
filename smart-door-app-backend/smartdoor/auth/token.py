import base64
import os
import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWKSetError
import smartdoor.settings as settings
from jwt.algorithms import Algorithm
import logging

logger = logging.getLogger(__name__)


class TokenRejected(Exception):
    """토큰 자체가 문제다 (만료, 서명·대상·발급자 불일치, 형식 오류). 다시 로그인하거나 토큰을 갱신해야 한다 → 401."""


class AuthUnavailable(Exception):
    """토큰은 문제가 없을 수 있지만 서버가 검증하지 못했다 (Microsoft 키 서버 접속 실패 등). 잠시 뒤 다시 시도하면 된다 → 503."""

TENANT_ID = os.environ.get("AZURE_AD_TENANT_ID", "e8715ec0-6179-432a-a864-54ea4008adc2")
ISSUER_V2 = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
ISSUER_V1 = f"https://sts.windows.net/{TENANT_ID}/"
ALLOWED_ISSUERS = {ISSUER_V2, ISSUER_V1}
JWKS_URI = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
AUDIENCE = os.environ.get(
    "AZURE_AD_AUDIENCE",
    "api://b157dbcc-ab7d-4f22-84d4-6286abd37c3d",
)

# Azure AD JWT 키 클라이언트 (타임아웃 30초 설정 - PyJWT 기본값)
_JWK_CLIENT = PyJWKClient(JWKS_URI, timeout=30)


def verify_jwt(token):
    """
    Azure AD JWT 토큰 검증
    - 타임아웃: 30초
    - 실패 시 상세 로그 기록
    - 토큰이 잘못된 경우 TokenRejected, 서버 쪽 문제로 검증하지 못한 경우 AuthUnavailable 을 던진다.
      (앱이 "다시 로그인해야 하는 상황"과 "잠시 뒤 다시 시도하면 되는 상황"을 구분하게 하기 위함)
    """
    try:
        logger.debug("JWT 검증 시작")

        # JWK에서 서명키 자동 해석 (타임아웃 적용됨)
        signing_key = _JWK_CLIENT.get_signing_key_from_jwt(token).key

        decoded_token = jwt.decode(
            token,
            key=signing_key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            options={"verify_iss": False},
        )

        iss = decoded_token.get("iss")
        if iss not in ALLOWED_ISSUERS:
            logger.warning(f"Invalid issuer: {iss}")
            raise TokenRejected("Invalid issuer")

        logger.debug(f"JWT 검증 성공: {decoded_token.get('upn', 'unknown')}")
        return decoded_token

    except TokenRejected:
        raise
    except jwt.ExpiredSignatureError:
        logger.warning("JWT 토큰 만료됨")
        raise TokenRejected("Token has expired")
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT 토큰 유효하지 않음: {e}")
        raise TokenRejected(f"Invalid token: {e}")
    except PyJWKClientConnectionError as e:
        # 서버가 Microsoft 키 서버에 접속하지 못했다. 사용자의 토큰 잘못이 아니다.
        logger.error(f"JWKS 조회 실패 (키 서버 접속 불가): {e}")
        raise AuthUnavailable(str(e))
    except PyJWKSetError as e:
        logger.error(f"JWKS 형식 오류: {e}")
        raise AuthUnavailable(str(e))
    except PyJWKClientError as e:
        # 토큰이 가리키는 키(kid)가 키 목록에 없음 등. 토큰이 잘못된 경우다.
        logger.warning(f"JWT 서명키를 찾을 수 없음: {e}")
        raise TokenRejected(f"Invalid token: {e}")
    except Exception as e:
        # 위에서 분류하지 못한 오류(네트워크 응답 이상, 라이브러리 오류 등)는 토큰이 아니라 서버 쪽 문제로 본다.
        logger.error(f"JWT 검증 실패: {type(e).__name__} - {e}")
        raise AuthUnavailable(f"{type(e).__name__}: {e}")
