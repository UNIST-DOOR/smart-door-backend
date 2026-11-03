"""door_log 가 로그인 토큰 등 민감한 요청 헤더를 로그에 남기지 않는지 확인한다. (실제 Django/DRF 필요, DB 는 가짜)

실행 (Django 가 설치된 환경, smartdoor 폴더에서):
    python -m unittest auth.test_door_log_privacy -v
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartdoor.settings")

import django  # noqa: E402

django.setup()

from rest_framework.test import APIRequestFactory  # noqa: E402

from auth import views  # noqa: E402

SECRET = "SECRET-TOKEN-VALUE-ABC123"


class BrokenConnection:
    """door_log 가 DB 를 만지는 순간 실패시킨다. 로그를 남기는 앞부분만 확인하면 된다."""

    def cursor(self):
        raise RuntimeError("db unavailable in test")


def make_request(**headers):
    extra = {f"HTTP_{k.upper().replace('-', '_')}": v for k, v in headers.items()}
    return APIRequestFactory().post("/api/door/log/", {"platform": "ios", "doorType": "door"}, format="json", **extra)


class HeaderAllowListTest(unittest.TestCase):
    def test_only_allowed_headers_are_logged(self):
        request = make_request(
            Authorization=f"Bearer {SECRET}",
            Cookie="session=abc",
            X_App_Platform="ios",
            X_App_Build="5",
            X_Forwarded_For="10.0.0.1",
        )
        logged = views._headers_for_log(request)

        self.assertEqual(logged["X-App-Platform"], "ios")
        self.assertEqual(logged["X-App-Build"], "5")
        self.assertNotIn("Authorization", logged)
        self.assertNotIn("Cookie", logged)
        self.assertNotIn(SECRET, str(logged))

    def test_missing_headers_are_left_out(self):
        self.assertEqual(views._headers_for_log(make_request()).get("X-App-Build"), None)


class DoorLogDoesNotLeakTokenTest(unittest.TestCase):
    def call(self):
        request = make_request(Authorization=f"Bearer {SECRET}", X_App_Platform="android", X_App_Build="4")
        with mock.patch("auth.decorators.verify_jwt", return_value={"upn": "student@unist.ac.kr"}), \
                mock.patch("auth.views.connection", BrokenConnection()):
            # 이 프로젝트는 auth 로거를 루트와 분리해 두었다(propagate=False). auth 아래의 모든 로그(views, decorators, token)를 본다.
            with self.assertLogs("auth", level="DEBUG") as captured:
                response = views.door_log(request)
        return response, "\n".join(captured.output)

    def test_token_is_not_in_any_log_line(self):
        _, logs = self.call()

        self.assertNotIn(SECRET, logs)
        self.assertNotIn("Bearer", logs)
        self.assertNotIn("Authorization", logs)

    def test_useful_request_information_is_still_logged(self):
        _, logs = self.call()

        self.assertIn("Door log API called", logs)
        self.assertIn("X-App-Platform", logs)  # 앱 플랫폼/버전은 문제 추적에 필요해서 남긴다
        self.assertIn("X-App-Build", logs)
        self.assertIn("doorType", logs)

    def test_response_behaviour_is_unchanged(self):
        response, _ = self.call()

        self.assertEqual(response.status_code, 500)  # 이 테스트에서는 DB 가 일부러 실패한다
        self.assertFalse(response.data["ok"])


if __name__ == "__main__":
    unittest.main()
