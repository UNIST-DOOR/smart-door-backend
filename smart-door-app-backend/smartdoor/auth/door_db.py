import logging
from functools import wraps

from django.db import OperationalError, connection

logger = logging.getLogger(__name__)

# 2006: MySQL server has gone away / 2013: Lost connection to server during query
_LOST_CONNECTION_CODES = (2006, 2013)


def is_lost_connection(error):
    """DB 연결이 끊겨서 난 오류인지 (재연결하면 해결될 수 있는 오류)."""
    return bool(error.args) and error.args[0] in _LOST_CONNECTION_CODES


_is_lost_connection = is_lost_connection  # 예전 이름 (호환)


def close_dead_connection():
    """
    쉬는 사이에 DB 서버나 중간 네트워크 장비가 끊어 버린 연결이면 닫는다. (다음 쿼리 때 새로 연결된다)

    연결은 CONN_MAX_AGE 동안 재사용되는데, Django 3.2 는 이전 요청에서 오류가 난 뒤에만 연결이 살아 있는지 확인한다.
    그래서 오래 쉰 뒤의 첫 요청이 죽은 연결로 쿼리를 보내 2013(Lost connection) 오류를 낸다.
    닫았으면 True.
    """
    if connection.connection is not None and not connection.is_usable():
        logger.warning("DB 연결이 끊어져 있어 새로 연결합니다")
        connection.close()
        return True
    return False


def retry_on_lost_connection(view):
    """
    DB 연결 끊김(2006/2013)으로 실패하면 연결을 새로 맺어 한 번만 다시 실행한다.
    읽기 전용 작업에만 쓴다. 쓰기는 다시 실행하면 중복될 수 있다.
    두 번째에도 실패하면 그 오류를 그대로 던진다. 연결 끊김이 아닌 오류는 재시도하지 않는다.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except OperationalError as error:
            if not is_lost_connection(error):
                raise
            logger.warning("DB 연결이 끊겨 새로 연결한 뒤 다시 실행합니다 (%s)", error.args[0])
            connection.close()
            return view(*args, **kwargs)

    return wrapper


class DjangoDb:
    """door_packet.Db 프로토콜의 Django 구현.

    LAST_INSERT_ID() 는 DB 연결 단위라 같은 요청(스레드) 안에서는 같은 연결을 쓴다.

    연결은 CONN_MAX_AGE 동안 재사용되는데, 쉬는 사이에 DB 서버나 중간 네트워크가 끊어 버린 연결로
    첫 쿼리를 날리면 2013(Lost connection) 오류가 난다. 문 열기는 DB 에 의존하므로 다음 두 가지로 막는다.
      1) 요청을 시작할 때 연결이 살아 있는지 점검하고, 죽었으면 닫고 새로 연결한다.
      2) 조회(SELECT)가 연결 끊김으로 실패하면 연결을 새로 맺어 한 번만 다시 실행한다.
         (쓰기는 다시 실행하면 안 되므로 재시도하지 않는다)
    """

    def __init__(self):
        close_dead_connection()

    def _run_query(self, sql, params):
        with connection.cursor() as cursor:
            cursor.execute(sql, list(params))
            return list(cursor.fetchall())

    def query(self, sql, params=()):
        try:
            return self._run_query(sql, params)
        except OperationalError as error:
            # LAST_INSERT_ID() 는 연결마다 값이 달라서, 새 연결에서 다시 실행하면 틀린 값(0)이 나온다.
            if not is_lost_connection(error) or "LAST_INSERT_ID" in sql:
                raise
            logger.warning("DB 연결이 끊겨 새로 연결한 뒤 조회를 다시 실행합니다 (%s)", error.args[0])
            connection.close()
            return self._run_query(sql, params)

    def execute(self, sql, params=()):
        with connection.cursor() as cursor:
            cursor.execute(sql, list(params))
            return cursor.rowcount
