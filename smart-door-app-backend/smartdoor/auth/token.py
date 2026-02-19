import base64
import os
import jwt
from jwt import PyJWKClient
import smartdoor.settings as settings
from jwt.algorithms import Algorithm
import logging

logger = logging.getLogger(__name__)

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
            raise Exception("Invalid issuer")
        
        logger.debug(f"JWT 검증 성공: {decoded_token.get('upn', 'unknown')}")
        return decoded_token
        
    except jwt.ExpiredSignatureError:
        logger.warning("JWT 토큰 만료됨")
        raise Exception("Token has expired")
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT 토큰 유효하지 않음: {e}")
        raise Exception(f"Invalid token: {e}")
    except Exception as e:
        logger.error(f"JWT 검증 실패: {type(e).__name__} - {e}")
        raise
