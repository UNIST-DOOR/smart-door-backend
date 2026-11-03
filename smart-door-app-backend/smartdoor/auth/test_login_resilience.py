"""로그인 직후와 앱 복귀 때 부르는 방 정보 조회가 DB 연결 끊김에 견디는지 확인한다. (실제 Django/DRF 필요, DB 는 가짜)

실행 (Django 가 설치된 환경, smartdoor 폴더에서):
    python -m unittest auth.test_login_resilience -v
개발 DB 에는 연결하지 않는다.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartdoor.settings")

import django  # noqa: E402

django.setup()

from django.db import OperationalError  # noqa: E402
from rest_framework.test import APIRequestFactory  # noqa: E402

from auth import views  # noqa: E402
from smartdoor.middleware import DbConnectionHealthMiddleware  # noqa: E402


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed += 1
        if self.conn.fail_codes:
            raise OperationalError(self.conn.fail_codes.pop(0), "연결 오류")

    def fetchone(self):
        return None  # umcs_mast 에 없는 사용자 → "UPN not mapped" (정상적인 조회 결과)

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self):
        self.connection = object()
        self.usable = True
        self.closed = 0
        self.executed = 0
        self.fail_codes = []  # 앞에서부터 하나씩 소모하며 execute 를 실패시킨다

    def is_usable(self):
        return self.usable

    def close(self):
        self.closed += 1
        self.connection = None
        self.usable = True

    def cursor(self):
        return FakeCursor(self)


def call_room_info(conn):
    request = APIRequestFactory().get("/api/room-info/", HTTP_AUTHORIZATION="Bearer test-token")
    with mock.patch("auth.decorators.verify_jwt", return_value={"upn": "student@unist.ac.kr"}), \
            mock.patch("auth.views.connection", conn), \
            mock.patch("auth.door_db.connection", conn):
        response = views.room_info(request)
    return response


class RoomInfoResilienceTest(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConnection()

    def test_normal_lookup_is_unchanged(self):
        response = call_room_info(self.conn)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["ok"])
        self.assertFalse(response.data["found"])  # 사용자가 매핑되지 않은 정상적인 조회 결과
        self.assertEqual(self.conn.closed, 0)

    def test_lost_connection_is_retried_and_succeeds(self):
        self.conn.fail_codes = [2013]  # 쉬던 연결로 보낸 첫 쿼리만 실패
        response = call_room_info(self.conn)
        self.assertEqual(response.status_code, 200)  # 예전에는 여기서 500 이었다
        self.assertEqual(response.data["reason"], "UPN not mapped in umcs_mast")
        self.assertEqual(self.conn.closed, 1)

    def test_gone_away_2006_is_also_recovered(self):
        self.conn.fail_codes = [2006]
        self.assertEqual(call_room_info(self.conn).status_code, 200)

    def test_persistent_failure_returns_503_not_a_login_failure(self):
        self.conn.fail_codes = [2013, 2013]
        response = call_room_info(self.conn)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {"ok": False, "error": "db_unavailable"})
        self.assertEqual(self.conn.executed, 2)  # 두 번 이상 시도하지 않는다

    def test_other_db_errors_keep_the_old_500_response(self):
        self.conn.fail_codes = [1045]  # 접근 거부 등 재시도로 해결되지 않는 오류
        response = call_room_info(self.conn)
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.data["ok"])
        self.assertEqual(self.conn.executed, 1)
        self.assertEqual(self.conn.closed, 0)

    def test_token_errors_are_not_touched(self):
        request = APIRequestFactory().get("/api/room-info/")  # Authorization 헤더 없음
        response = views.room_info(request)
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.conn.executed, 0)


class DbConnectionHealthMiddlewareTest(unittest.TestCase):
    def _run(self, conn):
        with mock.patch("auth.door_db.connection", conn):
            return DbConnectionHealthMiddleware().process_request(object())

    def test_dead_connection_is_replaced_before_the_request(self):
        conn = FakeConnection()
        conn.usable = False  # 쉬는 동안 끊긴 연결
        self.assertIsNone(self._run(conn))
        self.assertEqual(conn.closed, 1)

    def test_healthy_connection_is_kept(self):
        conn = FakeConnection()
        self.assertIsNone(self._run(conn))
        self.assertEqual(conn.closed, 0)

    def test_check_failure_never_blocks_the_request(self):
        conn = FakeConnection()
        conn.is_usable = mock.Mock(side_effect=RuntimeError("boom"))
        self.assertIsNone(self._run(conn))  # 예외가 밖으로 나가지 않는다

    def test_middleware_is_registered(self):
        from django.conf import settings

        self.assertIn("smartdoor.middleware.DbConnectionHealthMiddleware", settings.MIDDLEWARE)


if __name__ == "__main__":
    unittest.main()
