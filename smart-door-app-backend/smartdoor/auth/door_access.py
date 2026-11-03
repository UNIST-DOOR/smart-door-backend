"""문 열기 권한 확인과 BLE_OPEN_LOG 기록.

DB는 door_packet.Db 프로토콜(query/execute)을 구현한 객체를 받는다.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .door_packet import KST, Db, digits_only

RESULT_CODES = ("OK", "NO_RESPONSE", "BLE_FAIL", "DOOR_FAIL")
RATE_LIMIT_PER_MINUTE = 10


class AccessDenied(Exception):
    """권한 없음(403). reason 은 클라이언트에 내려가도 되는 짧은 코드."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Assignment:
    student_id: str
    room_key: str
    room_num: str
    bleid: str
    checkout_date: Optional[str]
    checkout_time: Optional[str]


def find_student_id(db: Db, upn: str) -> Optional[str]:
    rows = db.query(
        """
        SELECT MAST_IDNO
        FROM umcs_mast
        WHERE LOWER(TRIM(MAST_MAIL)) = LOWER(TRIM(%s))
        AND MAST_STCO = '1'
        ORDER BY MAST_UPDT DESC
        LIMIT 1
        """,
        [upn],
    )
    return str(rows[0][0]) if rows else None


def find_assignment(db: Db, student_id: str) -> Assignment:
    """학번의 최신 방 배정. 없으면 AccessDenied. bleid 는 서버가 방 정보에서 찾는다."""
    rows = db.query(
        """
        SELECT DOOR_TRAN_ROOM, DOOR_TRAN_ODATE, DOOR_TRAN_OTIME
        FROM fo_door_tran
        WHERE (CAST(DOOR_TRAN_STNO AS CHAR) = %s OR CAST(DOOR_TRAN_STNO AS UNSIGNED) = CAST(%s AS UNSIGNED))
        ORDER BY DOOR_TRAN_FDATE DESC, DOOR_TRAN_LDATE DESC, DOOR_TRAN_IDATE DESC, DOOR_TRAN_SEQ DESC
        LIMIT 1
        """,
        [student_id, student_id],
    )
    if not rows:
        raise AccessDenied("no_room")
    room_key, odate, otime = rows[0]

    rows = db.query(
        """
        SELECT ROOM_CODE_NUM, ROOM_CODE_BLEID
        FROM fo_room_code
        WHERE ROOM_CODE_KEY = %s
        LIMIT 1
        """,
        [str(room_key)],
    )
    if not rows or not digits_only(rows[0][1]):
        raise AccessDenied("room_not_found")

    return Assignment(
        student_id=student_id,
        room_key=str(room_key),
        room_num=str(rows[0][0]),
        bleid=digits_only(rows[0][1]),
        checkout_date=str(odate) if odate is not None else None,
        checkout_time=str(otime) if otime is not None else None,
    )


def parse_door_tran_datetime(date_str: Optional[str], time_str: Optional[str]) -> Optional[datetime]:
    """fo_door_tran 의 날짜/시간을 KST datetime 으로. 앱 DoorControlScreen.doorTranToDate 와 같은 규칙."""
    d = re.sub(r"[^0-9]", "", date_str or "")
    if len(d) != 8:
        return None
    hour = minute = 0
    t = re.sub(r"[^0-9]", "", time_str or "")
    if len(t) >= 2:
        hour = int(t[:2])
    if len(t) >= 4:
        minute = int(t[2:4])
    if hour == 24 and minute == 0:  # '24:00' 은 해당 일자 23:59 로 처리
        hour, minute = 23, 59
    try:
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), hour, minute, tzinfo=KST)
    except ValueError:
        return None


def is_stay_expired(assignment: Assignment, now: datetime) -> bool:
    """퇴실 일시가 지났으면 True. 정보가 없으면 막지 않는다(기존 앱 규칙)."""
    out_at = parse_door_tran_datetime(assignment.checkout_date, assignment.checkout_time)
    return out_at is not None and now > out_at


def check_access(db: Db, student_id: Optional[str], requested_bleid: Optional[str], now: datetime) -> Assignment:
    """권한 확인. 통과하면 Assignment, 아니면 AccessDenied."""
    if not student_id:
        raise AccessDenied("not_registered")
    assignment = find_assignment(db, student_id)
    if requested_bleid and digits_only(requested_bleid) != assignment.bleid:
        raise AccessDenied("bleid_mismatch")
    if is_stay_expired(assignment, now):
        raise AccessDenied("stay_expired")
    return assignment


# ── BLE_OPEN_LOG ─────────────────────────────────────────────

def count_recent_requests(db: Db, user_id: str, seconds: int = 60) -> int:
    rows = db.query(
        "SELECT COUNT(*) FROM BLE_OPEN_LOG WHERE USER_ID = %s AND ISSUE_DATE > (NOW() - INTERVAL %s SECOND)",
        [user_id, seconds],
    )
    return int(rows[0][0]) if rows else 0


def retry_of_is_valid(db: Db, user_id: str, req_id: str) -> bool:
    rows = db.query("SELECT 1 FROM BLE_OPEN_LOG WHERE REQ_ID = %s AND USER_ID = %s", [req_id, user_id])
    return bool(rows)


def insert_issue_log(
    db: Db,
    *,
    req_id: str,
    retry_of: Optional[str],
    user_id: str,
    bleid: str,
    room: Optional[str],
    issued: bool,
    signed: Optional[bool],
    key_ver: Optional[int],
    counter: Optional[int],
    app_ver: str,
    os_name: str,
) -> None:
    db.execute(
        """
        INSERT INTO BLE_OPEN_LOG
            (REQ_ID, RETRY_OF, USER_ID, BLEID, ROOM, CMD, ISSUE, SIGNED, KEY_VER, CNT, APP_VER, OS, ISSUE_DATE)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """,
        [
            req_id,
            retry_of,
            user_id,
            bleid,
            room,
            "open",
            "Y" if issued else "N",
            None if signed is None else ("Y" if signed else "N"),
            key_ver,
            counter,
            app_ver or None,
            os_name or None,
        ],
    )


def update_result_log(
    db: Db,
    *,
    req_id: str,
    user_id: str,
    result: str,
    stage: Optional[str],
    door_resp: Optional[str],
    elapsed_ms: Optional[int],
) -> bool:
    """본인이 발급받은 요청에 한 번만 결과를 채운다. 갱신됐으면 True."""
    affected = db.execute(
        """
        UPDATE BLE_OPEN_LOG
        SET RESULT = %s, STAGE = %s, DOOR_RESP = %s, ELAPSED_MS = %s, RESULT_DATE = NOW()
        WHERE REQ_ID = %s AND USER_ID = %s AND ISSUE = 'Y' AND RESULT IS NULL
        """,
        [result, stage, door_resp, elapsed_ms, req_id, user_id],
    )
    return affected > 0
