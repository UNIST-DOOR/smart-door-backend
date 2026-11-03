"""문 열기 패킷 생성과 서명 (앱 서버 전용).

계산 규칙은 commn 서버 module/BleAuth.js, 모듈 검증 코드(app_auth.c)와 같아야 한다.
같은 문을 두 서버가 번갈아 열어도 서로 막지 않으려면 같은 테이블을 같은 방식으로 써야 한다.

패킷 형식:
    [원본 패킷 최대 40B][counter 6B big-endian][tag 16B][0xA5][전체 길이 1B]
    tag = HMAC-SHA256(key, 원본 패킷 || counter)[:16]
    전체 길이 = 원본 + 24, 64 이하

이 모듈은 표준 라이브러리만 쓴다. DB는 아래 Db 프로토콜(query/execute)을 구현한 객체를 받는다.
키 값은 로그와 예외 메시지에 절대 넣지 않는다.
"""
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol, Sequence

KST = timezone(timedelta(hours=9))

MAX_FRAME_LEN = 40
MAX_PACKET_LEN = 64
TRAILER_LEN = 24  # counter 6 + tag 16 + 표시 1 + 전체 길이 1
SIGN_MARK = 0xA5

_DELIM = 0x2F
_END_MARK = 0x0D
_OPEN_CMD = 0x01
_DOOR_KEY_FIELD = 0x01  # 비우면 모듈 응답이 앱이 아니라 브릿지로 간다

_KEY_LEN_VER0 = 32  # 키 ver 0: hex 64자
_KEY_LEN_VER1_UP = 16  # 키 ver 1 이상: hex 32자


class DoorPacketError(Exception):
    """패킷 생성 실패. 메시지에 키 값을 넣지 않는다."""


class KeyConfigError(DoorPacketError):
    """키 조회/형식 오류."""


class Db(Protocol):
    def query(self, sql: str, params: Sequence = ()) -> list:
        """SELECT 결과 행 목록(튜플)."""

    def execute(self, sql: str, params: Sequence = ()) -> int:
        """INSERT/UPDATE 실행, 영향받은 행 수."""


@dataclass
class DoorPacket:
    packet: bytes
    signed: bool
    bleid: str
    key_ver: Optional[int] = None
    counter: Optional[int] = None

    @property
    def packet_hex(self) -> str:
        return self.packet.hex()


def digits_only(value) -> str:
    return "".join(ch for ch in str(value or "") if ch in "0123456789")


def build_open_frame(bleid: str, now: Optional[datetime] = None) -> bytes:
    """기존 앱(DoorService.ts)의 문 열기 패킷과 같은 원본 패킷.

    [헤더 10B: CC 01 00*7 체크섬][2F][bleid 한 자리=1바이트][2F][YYYYMMDD 한 자리=1바이트][2F][01][2F][0D]
    """
    digits = digits_only(bleid)
    if not digits:
        raise DoorPacketError("bleid 없음")

    when = (now or datetime.now(KST)).astimezone(KST)
    date = when.strftime("%Y%m%d")

    head = bytearray([0xCC, _OPEN_CMD, 0, 0, 0, 0, 0, 0, 0])
    head.append(sum(head) & 0xFF)

    frame = bytearray(head)
    frame.append(_DELIM)
    frame.extend(int(ch) for ch in digits)
    frame.append(_DELIM)
    frame.extend(int(ch) for ch in date)
    frame.append(_DELIM)
    frame.append(_DOOR_KEY_FIELD)
    frame.append(_DELIM)
    frame.append(_END_MARK)

    if len(frame) > MAX_FRAME_LEN:
        raise DoorPacketError(f"원본 패킷 길이 초과 {len(frame)}")
    return bytes(frame)


def bleid_of(frame: bytes) -> Optional[str]:
    """패킷 안의 bleid: 첫 번째 0x2F 와 두 번째 0x2F 사이 (0x1D 명령은 13번째 바이트부터)."""
    start = 13 if len(frame) > 1 and frame[1] == 0x1D else 0
    d0 = d1 = -1
    for i in range(start, len(frame)):
        if frame[i] == _DELIM:
            if d0 < 0:
                d0 = i
            else:
                d1 = i
                break
    if d0 < 0 or d1 - d0 <= 1:
        return None
    return "".join(format(frame[i], "X") for i in range(d0 + 1, d1))


def sign_frame(frame: bytes, counter: int, key: bytes) -> bytes:
    """원본 패킷 뒤에 트레일러 24바이트를 붙인다."""
    total = len(frame) + TRAILER_LEN
    if total > MAX_PACKET_LEN:
        raise DoorPacketError(f"패킷 길이 초과 {total}")
    try:
        cnt = counter.to_bytes(6, "big")
    except OverflowError:
        raise DoorPacketError("counter 범위 초과") from None
    tag = hmac.new(key, frame + cnt, hashlib.sha256).digest()[:16]
    return frame + cnt + tag + bytes([SIGN_MARK, total])


_COUNTER_SQL = (
    "INSERT INTO BLE_DOOR_CNT (BLEID, LAST_CNT, UPD_DATE) VALUES (%s, %s, NOW()) "
    "ON DUPLICATE KEY UPDATE "
    "LAST_CNT = LAST_INSERT_ID(GREATEST(LAST_CNT + 1, VALUES(LAST_CNT))), "
    "UPD_DATE = NOW()"
)


def next_counter(db: Db, bleid: str, now_ms: Optional[int] = None) -> int:
    """commn 과 같은 테이블을 한 문장으로 증가시켜 값을 받는다 (같은 DB 연결에서 실행).

    새 행이면 LAST_INSERT_ID() 가 갱신되지 않으므로 넣은 값을 그대로 쓴다.
    """
    now = int(time.time() * 1000) if now_ms is None else now_ms
    affected = db.execute(_COUNTER_SQL, [bleid, now])
    if affected == 1:
        return now
    rows = db.query("SELECT LAST_INSERT_ID()")
    return int(rows[0][0])


def _load_key(db: Db, key_ver: int) -> bytes:
    rows = db.query("SELECT KEY_HEX FROM BLE_AUTH_KEY WHERE KEY_VER = %s", [key_ver])
    if not rows:
        raise KeyConfigError(f"키 ver {key_ver} 없음")
    try:
        key = bytes.fromhex(str(rows[0][0]).strip())
    except ValueError:
        raise KeyConfigError(f"키 ver {key_ver} 형식 오류") from None
    expected = _KEY_LEN_VER0 if key_ver == 0 else _KEY_LEN_VER1_UP
    if len(key) != expected:
        raise KeyConfigError(f"키 ver {key_ver} 길이 오류")
    return key


def build_door_packet(db: Db, frame: bytes, now_ms: Optional[int] = None) -> DoorPacket:
    """서명 대상 문이면 서명 패킷, 아니면 원본 그대로(구 펌웨어 문)."""
    frame = bytes(frame)
    bleid = bleid_of(frame)
    if not bleid:
        raise DoorPacketError("패킷에 bleid 없음")

    # 1) 서명 대상인지
    if not db.query("SELECT 1 AS Y FROM BLE_AUTH_DOOR WHERE BLEID = %s", [bleid]):
        return DoorPacket(packet=frame, signed=False, bleid=bleid)

    # 2) 문의 키 버전(없으면 0) -> 키. 키는 원격으로 바뀌므로 매번 조회한다.
    rows = db.query("SELECT KEY_VER FROM BLE_DOOR_KEY WHERE BLEID = %s", [bleid])
    key_ver = int(rows[0][0]) if rows else 0
    key = _load_key(db, key_ver)

    # 3) 길이를 먼저 확인해 counter 를 낭비하지 않는다
    if len(frame) + TRAILER_LEN > MAX_PACKET_LEN:
        raise DoorPacketError(f"패킷 길이 초과 {len(frame) + TRAILER_LEN}")

    # 4) counter 받기, 트레일러 붙이기
    counter = next_counter(db, bleid, now_ms)
    packet = sign_frame(frame, counter, key)
    return DoorPacket(packet=packet, signed=True, bleid=bleid, key_ver=key_ver, counter=counter)
