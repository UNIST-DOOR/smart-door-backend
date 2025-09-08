import base64
import os
import jwt
from jwt import PyJWKClient
import smartdoor.settings as settings
from jwt.algorithms import Algorithm


TENANT_ID = os.environ.get("AZURE_AD_TENANT_ID", "e8715ec0-6179-432a-a864-54ea4008adc2")
ISSUER_V2 = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
ISSUER_V1 = f"https://sts.windows.net/{TENANT_ID}/"
ALLOWED_ISSUERS = {ISSUER_V2, ISSUER_V1}
JWKS_URI = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
AUDIENCE = os.environ.get(
    "AZURE_AD_AUDIENCE",
    "api://b157dbcc-ab7d-4f22-84d4-6286abd37c3d",
)


_JWK_CLIENT = PyJWKClient(JWKS_URI)


def verify_jwt(token):

    # JWK에서 서명키 자동 해석
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
        raise Exception("Invalid issuer")
    return decoded_token
