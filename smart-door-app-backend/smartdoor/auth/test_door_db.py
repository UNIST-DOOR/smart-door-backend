"""DjangoDb 연결 끊김 처리 테스트 (Django 불필요, 가짜 django.db 사용).

실행: smartdoor 폴더에서  python -m unittest auth.test_door_db -v
"""
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock


class FakeOperationalError(Exception):
    pass


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.conn.executed.append(sql)
        if self.conn.fail_codes:
            raise FakeOperationalError(self.conn.fail_codes.pop(0), "연결 오류")
        self.conn.connection = self.conn.connection or object()  # 닫혀 있었다면 새로 연결된다

    def fetchall(self):
        return [(1,)]


class FakeConnection:
    def __init__(self):
        self.connection = object()
        self.usable = True
        self.closed = 0
        self.executed = []
        self.fail_codes = []  # 앞에서부터 하나씩 소모하며 execute 를 실패시킨다

    def is_usable(self):
        return self.usable

    def close(self):
        self.closed += 1
        self.connection = None
        self.usable = True

    def cursor(self):
        return FakeCursor(self)


_fake_conn = FakeConnection()
_fake_django = types.ModuleType("django")
_fake_django_db = types.ModuleType("django.db")
_fake_django_db.connection = _fake_conn
_fake_django_db.OperationalError = FakeOperationalError


def _load_door_db_with_fake_django():
    """door_db.py 를 가짜 Django 에 묶어서 '따로' 불러온다.

    일반 import 를 쓰면 이미 불러온 진짜 auth.door_db(실제 Django, 실제 DB)를 그대로 받을 수 있다.
    다른 테스트(test_login_resilience 등)와 한 번에 돌릴 때 이 테스트가 개발 DB 에 접속하는 사고가 난다.
    파일에서 직접, 다른 이름으로 불러오면 sys.modules 와 auth 패키지에 아무 흔적도 남지 않는다.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "door_db.py")
    spec = importlib.util.spec_from_file_location("door_db_under_test_with_fake_django", path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"django": _fake_django, "django.db": _fake_django_db}):
        spec.loader.exec_module(module)
    return module


door_db = _load_door_db_with_fake_django()
assert door_db.connection is _fake_conn, "가짜 Django 에 연결되어야 한다 (실제 DB 에 접속하면 안 된다)"


class DjangoDbTest(unittest.TestCase):
    def setUp(self):
        _fake_conn.connection = object()
        _fake_conn.usable = True
        _fake_conn.closed = 0
        _fake_conn.executed = []
        _fake_conn.fail_codes = []

    def test_healthy_connection_is_kept(self):
        db = door_db.DjangoDb()
        self.assertEqual(db.query("SELECT 1"), [(1,)])
        self.assertEqual(_fake_conn.closed, 0)

    def test_dead_connection_is_replaced_at_request_start(self):
        _fake_conn.usable = False  # 쉬는 동안 DB 가 끊어 버린 연결
        db = door_db.DjangoDb()
        self.assertEqual(_fake_conn.closed, 1)
        self.assertEqual(db.query("SELECT 1"), [(1,)])

    def test_no_connection_yet_is_not_checked(self):
        _fake_conn.connection = None
        _fake_conn.usable = False
        door_db.DjangoDb()
        self.assertEqual(_fake_conn.closed, 0)

    def test_select_is_retried_once_after_lost_connection(self):
        db = door_db.DjangoDb()
        _fake_conn.fail_codes = [2013]  # 첫 실행만 실패
        self.assertEqual(db.query("SELECT MAST_IDNO FROM umcs_mast"), [(1,)])
        self.assertEqual(_fake_conn.closed, 1)
        self.assertEqual(len(_fake_conn.executed), 2)  # 실패 1회 + 재시도 1회

    def test_gone_away_2006_is_also_retried(self):
        db = door_db.DjangoDb()
        _fake_conn.fail_codes = [2006]
        self.assertEqual(db.query("SELECT 1"), [(1,)])

    def test_second_failure_is_raised(self):
        db = door_db.DjangoDb()
        _fake_conn.fail_codes = [2013, 2013]
        with self.assertRaises(FakeOperationalError):
            db.query("SELECT 1")
        self.assertEqual(len(_fake_conn.executed), 2)  # 두 번 이상 재시도하지 않는다

    def test_other_errors_are_not_retried(self):
        db = door_db.DjangoDb()
        _fake_conn.fail_codes = [1045]  # 접근 거부 등
        with self.assertRaises(FakeOperationalError):
            db.query("SELECT 1")
        self.assertEqual(len(_fake_conn.executed), 1)
        self.assertEqual(_fake_conn.closed, 0)

    def test_last_insert_id_query_is_not_retried(self):
        db = door_db.DjangoDb()
        _fake_conn.fail_codes = [2013]
        with self.assertRaises(FakeOperationalError):
            db.query("SELECT LAST_INSERT_ID()")  # 새 연결에서는 값이 0 이라 재시도하면 틀린 값이 나온다
        self.assertEqual(len(_fake_conn.executed), 1)

    def test_writes_are_never_retried(self):
        db = door_db.DjangoDb()
        _fake_conn.fail_codes = [2013]
        with self.assertRaises(FakeOperationalError):
            db.execute("INSERT INTO ble_open_log VALUES (1)")
        self.assertEqual(len(_fake_conn.executed), 1)


class CloseDeadConnectionTest(unittest.TestCase):
    def setUp(self):
        _fake_conn.connection = object()
        _fake_conn.usable = True
        _fake_conn.closed = 0

    def test_dead_connection_is_closed(self):
        _fake_conn.usable = False
        self.assertTrue(door_db.close_dead_connection())
        self.assertEqual(_fake_conn.closed, 1)

    def test_healthy_connection_is_kept(self):
        self.assertFalse(door_db.close_dead_connection())
        self.assertEqual(_fake_conn.closed, 0)

    def test_no_connection_yet_is_not_checked(self):
        _fake_conn.connection = None
        _fake_conn.usable = False
        self.assertFalse(door_db.close_dead_connection())
        self.assertEqual(_fake_conn.closed, 0)


class RetryOnLostConnectionTest(unittest.TestCase):
    def setUp(self):
        _fake_conn.connection = object()
        _fake_conn.usable = True
        _fake_conn.closed = 0

    def _flaky(self, errors):
        """errors 를 앞에서부터 하나씩 던지고, 다 던진 뒤에는 'ok' 를 돌려주는 가짜 뷰"""
        calls = []

        def view(request):
            calls.append(request)
            if errors:
                raise FakeOperationalError(errors.pop(0), "연결 오류")
            return "ok"

        return door_db.retry_on_lost_connection(view), calls

    def test_success_is_not_retried(self):
        wrapped, calls = self._flaky([])
        self.assertEqual(wrapped("req"), "ok")
        self.assertEqual(len(calls), 1)
        self.assertEqual(_fake_conn.closed, 0)

    def test_lost_connection_is_retried_once_after_reconnect(self):
        wrapped, calls = self._flaky([2013])
        self.assertEqual(wrapped("req"), "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(_fake_conn.closed, 1)  # 새로 연결하려고 한 번 닫는다

    def test_gone_away_2006_is_also_retried(self):
        wrapped, calls = self._flaky([2006])
        self.assertEqual(wrapped("req"), "ok")
        self.assertEqual(len(calls), 2)

    def test_second_failure_is_raised_and_not_retried_again(self):
        wrapped, calls = self._flaky([2013, 2013])
        with self.assertRaises(FakeOperationalError):
            wrapped("req")
        self.assertEqual(len(calls), 2)

    def test_other_errors_are_not_retried(self):
        wrapped, calls = self._flaky([1045])  # 접근 거부 등
        with self.assertRaises(FakeOperationalError):
            wrapped("req")
        self.assertEqual(len(calls), 1)
        self.assertEqual(_fake_conn.closed, 0)


if __name__ == "__main__":
    unittest.main()
