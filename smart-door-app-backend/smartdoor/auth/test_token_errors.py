"""토큰 오류(401)와 서버 쪽 검증 불가(503)가 구분되는지 확인한다. (실제 Django/DRF/PyJWT 필요, 네트워크·DB 미사용)

실행 (라이브러리가 설치된 환경, smartdoor 폴더에서):
    python -m unittest auth.test_token_errors -v
Microsoft 키 서버에는 접속하지 않고, 테스트용 RSA 키로 직접 서명한 토큰을 쓴다.
"""
import json
import os
import time
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartdoor.settings")

import django  # noqa: E402

django.setup()

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWKSetError  # noqa: E402
from rest_framework.test import APIRequestFactory  # noqa: E402

from auth import token as token_module  # noqa: E402
from auth import views  # noqa: E402
from auth.token import AuthUnavailable, TokenRejected, verify_jwt  # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(**override):
    claims = {
        "iss": token_module.ISSUER_V2,
        "aud": token_module.AUDIENCE,
        "exp": int(time.time()) + 3600,
        "upn": "student@unist.ac.kr",
        "name": "학생",
        "sub": "sub-1",
        "tid": token_module.TENANT_ID,
    }
    key = override.pop("signing_key", _KEY)
    claims.update(override)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-kid"})


def jwk_client(**kwargs):
    """Microsoft 키 서버 대신 쓰는 가짜. key 를 주면 그 공개키를 돌려주고, error 를 주면 그 오류를 던진다."""
    client = mock.Mock()
    if "error" in kwargs:
        client.get_signing_key_from_jwt.side_effect = kwargs["error"]
    else:
        client.get_signing_key_from_jwt.return_value = SimpleNamespace(key=_KEY.public_key())
    return client


class VerifyJwtTest(unittest.TestCase):
    def verify(self, token, **client_kwargs):
        with mock.patch.object(token_module, "_JWK_CLIENT", jwk_client(**client_kwargs)):
            return verify_jwt(token)

    def test_valid_token(self):
        claims = self.verify(make_token())
        self.assertEqual(claims["upn"], "student@unist.ac.kr")

    def test_v1_issuer_is_still_accepted(self):
        self.assertEqual(self.verify(make_token(iss=token_module.ISSUER_V1))["sub"], "sub-1")

    def test_expired_token_is_rejected(self):
        with self.assertRaisesRegex(TokenRejected, "Token has expired"):
            self.verify(make_token(exp=int(time.time()) - 10))

    def test_wrong_audience_is_rejected(self):
        with self.assertRaisesRegex(TokenRejected, "Invalid token"):
            self.verify(make_token(aud="api://someone-else"))

    def test_wrong_issuer_is_rejected(self):
        with self.assertRaisesRegex(TokenRejected, "Invalid issuer"):
            self.verify(make_token(iss="https://evil.example.com/"))

    def test_token_signed_with_another_key_is_rejected(self):
        with self.assertRaisesRegex(TokenRejected, "Invalid token"):
            self.verify(make_token(signing_key=_OTHER_KEY))

    def test_garbage_token_is_rejected(self):
        with self.assertRaises(TokenRejected):
            self.verify("abc.def.ghi")

    def test_unknown_key_id_is_a_token_problem(self):
        with self.assertRaises(TokenRejected):
            self.verify(make_token(), error=PyJWKClientError("Unable to find a signing key that matches: 'x'"))

    def test_token_errors_keep_the_old_message_text(self):
        # 앱과 로그가 쓰던 문구가 바뀌지 않아야 한다
        with self.assertRaises(TokenRejected) as ctx:
            self.verify(make_token(exp=int(time.time()) - 10))
        self.assertEqual(str(ctx.exception), "Token has expired")

    def test_key_server_unreachable_is_a_server_problem(self):
        with self.assertRaises(AuthUnavailable):
            self.verify(make_token(), error=PyJWKClientConnectionError("Fail to fetch data from the url"))

    def test_bad_key_set_is_a_server_problem(self):
        with self.assertRaises(AuthUnavailable):
            self.verify(make_token(), error=PyJWKSetError("The JWK Set did not contain any keys"))

    def test_unexpected_errors_are_a_server_problem_not_a_login_failure(self):
        for error in (TimeoutError("timed out"), OSError("network down"), json.JSONDecodeError("x", "y", 0), RuntimeError("boom")):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(AuthUnavailable):
                    self.verify(make_token(), error=error)


class NoDbConnection:
    """토큰 단계에서 막혀야 하는 요청이 DB 에 접근하면 실패시키는 가짜"""

    def cursor(self):
        raise AssertionError("토큰 검증 전에 DB 에 접근하면 안 된다")


class ViewStatusTest(unittest.TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        patcher = mock.patch("auth.views.connection", NoDbConnection())
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, view, method="get", token=None, header=None, **client_kwargs):
        extra = {}
        if header is not None:
            extra["HTTP_AUTHORIZATION"] = header
        elif token is not None:
            extra["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        request = getattr(self.factory, method)("/api/x/", **extra)
        with mock.patch.object(token_module, "_JWK_CLIENT", jwk_client(**client_kwargs)):
            return view(request)

    def test_missing_token_is_401_with_challenge_header(self):
        for view, method in ((views.me, "get"), (views.room_info, "get"), (views.open_result, "post")):
            with self.subTest(view=view.__name__):
                response = self.call(view, method=method)
                self.assertEqual(response.status_code, 401)  # 예전에는 403
                self.assertEqual(response.data["detail"], "Token is required")
                self.assertEqual(response.data["error"], "unauthorized")
                self.assertEqual(response["WWW-Authenticate"], "Bearer")

    def test_non_bearer_header_is_401(self):
        response = self.call(views.me, header="Basic abc")
        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_401(self):
        response = self.call(views.room_info, token=make_token(exp=int(time.time()) - 10))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["detail"], "Token has expired")

    def test_garbage_token_is_401(self):
        response = self.call(views.room_info, token="abc.def.ghi")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.data["detail"].startswith("Invalid token"))

    def test_key_server_down_is_503_and_retryable(self):
        response = self.call(
            views.room_info,
            token=make_token(),
            error=PyJWKClientConnectionError("Fail to fetch data from the url"),
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"], "auth_unavailable")
        self.assertEqual(response["Retry-After"], "5")
        self.assertNotIn("Fail to fetch", json.dumps(response.data))  # 내부 오류 문구는 노출하지 않는다

    def test_valid_token_still_works(self):
        response = self.call(views.me, token=make_token())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(response.data["upn"], "student@unist.ac.kr")

    def test_real_permission_denied_is_still_403(self):
        # 토큰은 정상이지만 문을 열 권한이 없는 경우는 401 이 아니라 403 이다 (앱이 구분한다)
        from auth import door_access

        denied = door_access.AccessDenied("stay_expired")
        with mock.patch.object(door_access, "find_student_id", return_value="1234569"),                 mock.patch.object(door_access, "count_recent_requests", return_value=0),                 mock.patch.object(door_access, "check_access", side_effect=denied),                 mock.patch.object(door_access, "insert_issue_log"),                 mock.patch("auth.views.DjangoDb"):
            request = self.factory.post("/api/door/open-packet/", {"bleid": "301201"}, format="json",
                                        HTTP_AUTHORIZATION=f"Bearer {make_token()}")
            with mock.patch.object(token_module, "_JWK_CLIENT", jwk_client()):
                response = views.open_packet(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"], "forbidden")
        self.assertEqual(response.data["reason"], "stay_expired")


if __name__ == "__main__":
    unittest.main()
