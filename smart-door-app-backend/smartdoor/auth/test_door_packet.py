"""문 열기 패킷/권한 단위 테스트 (Django 불필요).

실행: smartdoor 폴더에서  python -m unittest auth.test_door_packet -v
"""
import hashlib
import hmac
import unittest
from datetime import datetime

from auth import door_access
from auth.door_packet import (
    KST,
    DoorPacketError,
    KeyConfigError,
    bleid_of,
    build_door_packet,
    build_open_frame,
    next_counter,
    sign_frame,
)

# 문서의 테스트 벡터 (가짜 키)
VEC_KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
VEC_FRAME = bytes.fromhex("cc2101020000000000002f0300010200012f002f002f0d")
VEC_COUNTER = 1793590000000
VEC_PACKET_HEX = (
    "cc2101020000000000002f0300010200012f002f002f0d"
    "01a19a4b79804969525c95f1330076955f662002c5f2a52f"
)


class FakeDb:
    """SQL 문장 일부로 결과를 돌려주는 가짜 DB. 실행된 문장을 calls 에 남긴다."""

    def __init__(self, auth_doors=(), door_keys=None, auth_keys=None, counter_rows=None):
        self.auth_doors = set(auth_doors)
        self.door_keys = door_keys or {}  # bleid -> key_ver
        self.auth_keys = auth_keys or {}  # key_ver -> key_hex
        self.counters = dict(counter_rows or {})  # bleid -> last_cnt
        self.last_insert_id = 0
        self.calls = []

    def query(self, sql, params=()):
        self.calls.append(("query", " ".join(sql.split()), list(params)))
        if "FROM BLE_AUTH_DOOR" in sql:
            return [(1,)] if params[0] in self.auth_doors else []
        if "FROM BLE_DOOR_KEY" in sql:
            return [(self.door_keys[params[0]],)] if params[0] in self.door_keys else []
        if "FROM BLE_AUTH_KEY" in sql:
            return [(self.auth_keys[params[0]],)] if params[0] in self.auth_keys else []
        if "LAST_INSERT_ID()" in sql:
            return [(self.last_insert_id,)]
        raise AssertionError("예상하지 못한 query: " + sql)

    def execute(self, sql, params=()):
        self.calls.append(("execute", " ".join(sql.split()), list(params)))
        if "INSERT INTO BLE_DOOR_CNT" in sql:
            bleid, now = params
            if bleid in self.counters:
                self.counters[bleid] = max(self.counters[bleid] + 1, now)
                self.last_insert_id = self.counters[bleid]
                return 2  # 기존 행 갱신
            self.counters[bleid] = now
            return 1  # 새 행
        raise AssertionError("예상하지 못한 execute: " + sql)


class SignFrameTest(unittest.TestCase):
    def test_document_vector(self):
        packet = sign_frame(VEC_FRAME, VEC_COUNTER, VEC_KEY)
        self.assertEqual(packet.hex(), VEC_PACKET_HEX)
        self.assertEqual(len(packet), 47)

    def test_trailer_structure(self):
        packet = sign_frame(VEC_FRAME, 5, VEC_KEY)
        self.assertEqual(packet[:23], VEC_FRAME)
        self.assertEqual(packet[23:29], (5).to_bytes(6, "big"))
        self.assertEqual(packet[29:45], hmac.new(VEC_KEY, VEC_FRAME + packet[23:29], hashlib.sha256).digest()[:16])
        self.assertEqual(packet[45], 0xA5)
        self.assertEqual(packet[46], len(packet))

    def test_total_over_64_rejected(self):
        with self.assertRaises(DoorPacketError):
            sign_frame(bytes(41), 1, VEC_KEY)

    def test_counter_out_of_range(self):
        with self.assertRaises(DoorPacketError):
            sign_frame(VEC_FRAME, 2**48, VEC_KEY)


class BuildOpenFrameTest(unittest.TestCase):
    def test_matches_existing_app_packet(self):
        # 기존 앱(DoorService.ts) 문 열기 패킷: bleid 306301, 2026-11-02
        frame = build_open_frame("306301", datetime(2026, 11, 2, 9, 0, tzinfo=KST))
        header = "cc01" + "00" * 7 + "cd"  # 체크섬 = (0xCC + 0x01) & 0xFF
        self.assertEqual(
            frame.hex(),
            header
            + "2f" + "030006030001"  # bleid 한 자리 = 1바이트
            + "2f" + "0200020601010002"  # 20261102
            + "2f" + "01"  # key 필드
            + "2f" + "0d",
        )
        self.assertEqual(len(frame), 30)

    def test_bleid_roundtrip(self):
        frame = build_open_frame("306301")
        self.assertEqual(bleid_of(frame), "306301")

    def test_non_digits_removed(self):
        self.assertEqual(bleid_of(build_open_frame("unist_306301")), "306301")

    def test_empty_bleid_rejected(self):
        with self.assertRaises(DoorPacketError):
            build_open_frame("")

    def test_too_long_bleid_rejected(self):
        with self.assertRaises(DoorPacketError):
            build_open_frame("1" * 17)

    def test_date_uses_kst(self):
        # UTC 로는 11/1 16:00 이지만 KST 로는 11/2 01:00
        from datetime import timezone

        frame = build_open_frame("1", datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc))
        date_bytes = frame[10 + 1 + 1 + 1: 10 + 1 + 1 + 1 + 8]
        self.assertEqual("".join(str(b) for b in date_bytes), "20261102")

    def test_bleid_of_document_vector(self):
        self.assertEqual(bleid_of(VEC_FRAME), "301201")


class NextCounterTest(unittest.TestCase):
    def test_new_row_uses_inserted_value(self):
        db = FakeDb()
        self.assertEqual(next_counter(db, "306301", now_ms=1000), 1000)

    def test_existing_row_increments(self):
        db = FakeDb(counter_rows={"306301": 1000})
        self.assertEqual(next_counter(db, "306301", now_ms=500), 1001)
        self.assertEqual(next_counter(db, "306301", now_ms=500), 1002)

    def test_clock_ahead_wins(self):
        db = FakeDb(counter_rows={"306301": 1000})
        self.assertEqual(next_counter(db, "306301", now_ms=5000), 5000)


class BuildDoorPacketTest(unittest.TestCase):
    def setUp(self):
        self.frame = build_open_frame("306301", datetime(2026, 11, 2, 9, 0, tzinfo=KST))

    def test_unsigned_door_returns_original_without_counter(self):
        db = FakeDb()
        result = build_door_packet(db, self.frame)
        self.assertFalse(result.signed)
        self.assertEqual(result.packet, self.frame)
        self.assertFalse(any("BLE_DOOR_CNT" in c[1] for c in db.calls))

    def test_signed_default_key_ver0(self):
        db = FakeDb(auth_doors=["306301"], auth_keys={0: VEC_KEY.hex()})
        result = build_door_packet(db, self.frame, now_ms=VEC_COUNTER)
        self.assertTrue(result.signed)
        self.assertEqual(result.key_ver, 0)
        self.assertEqual(result.counter, VEC_COUNTER)
        self.assertEqual(result.packet, sign_frame(self.frame, VEC_COUNTER, VEC_KEY))
        self.assertEqual(len(result.packet), len(self.frame) + 24)

    def test_signed_key_ver1_uses_16_byte_key(self):
        key16 = bytes(range(16))
        db = FakeDb(auth_doors=["306301"], door_keys={"306301": 1}, auth_keys={1: key16.hex()})
        result = build_door_packet(db, self.frame, now_ms=7)
        self.assertEqual(result.key_ver, 1)
        self.assertEqual(result.packet, sign_frame(self.frame, 7, key16))

    def test_key_length_mismatch_rejected(self):
        db = FakeDb(auth_doors=["306301"], door_keys={"306301": 1}, auth_keys={1: VEC_KEY.hex()})  # ver1 인데 32바이트
        with self.assertRaises(KeyConfigError):
            build_door_packet(db, self.frame)

    def test_missing_key_rejected(self):
        db = FakeDb(auth_doors=["306301"])
        with self.assertRaises(KeyConfigError):
            build_door_packet(db, self.frame)

    def test_bad_hex_rejected_without_leaking_key(self):
        db = FakeDb(auth_doors=["306301"], auth_keys={0: "zz-secret-zz"})
        with self.assertRaises(KeyConfigError) as ctx:
            build_door_packet(db, self.frame)
        self.assertNotIn("secret", str(ctx.exception))

    def test_counter_not_consumed_when_key_invalid(self):
        db = FakeDb(auth_doors=["306301"], auth_keys={0: "00"})
        with self.assertRaises(KeyConfigError):
            build_door_packet(db, self.frame)
        self.assertEqual(db.counters, {})

    def test_same_packet_never_reissued(self):
        db = FakeDb(auth_doors=["306301"], auth_keys={0: VEC_KEY.hex()})
        a = build_door_packet(db, self.frame, now_ms=1000)
        b = build_door_packet(db, self.frame, now_ms=1000)
        self.assertNotEqual(a.packet, b.packet)
        self.assertEqual((a.counter, b.counter), (1000, 1001))


class AccessTest(unittest.TestCase):
    def test_parse_datetime(self):
        self.assertEqual(
            door_access.parse_door_tran_datetime("2026-11-02", "10:30:00"),
            datetime(2026, 11, 2, 10, 30, tzinfo=KST),
        )
        self.assertEqual(
            door_access.parse_door_tran_datetime("20261102", "2400"),
            datetime(2026, 11, 2, 23, 59, tzinfo=KST),
        )
        self.assertEqual(
            door_access.parse_door_tran_datetime("20261102", None),
            datetime(2026, 11, 2, 0, 0, tzinfo=KST),
        )
        self.assertIsNone(door_access.parse_door_tran_datetime(None, "1000"))
        self.assertIsNone(door_access.parse_door_tran_datetime("2026", "1000"))
        self.assertIsNone(door_access.parse_door_tran_datetime("20261340", "1000"))

    def _assignment(self, odate, otime):
        return door_access.Assignment("2020", "K", "301", "306301", odate, otime)

    def test_expired_after_checkout(self):
        a = self._assignment("20261102", "1000")
        self.assertTrue(door_access.is_stay_expired(a, datetime(2026, 11, 2, 10, 1, tzinfo=KST)))
        self.assertFalse(door_access.is_stay_expired(a, datetime(2026, 11, 2, 10, 0, tzinfo=KST)))

    def test_no_checkout_info_not_blocked(self):
        self.assertFalse(door_access.is_stay_expired(self._assignment(None, None), datetime(2030, 1, 1, tzinfo=KST)))

    def test_check_access(self):
        class AssignDb:
            def __init__(self, odate="20991231", otime="2400", bleid="306301"):
                self.odate, self.otime, self.bleid = odate, otime, bleid

            def query(self, sql, params=()):
                if "FROM fo_door_tran" in sql:
                    return [("ROOMKEY", self.odate, self.otime)]
                if "FROM fo_room_code" in sql:
                    return [("301", self.bleid)]
                raise AssertionError(sql)

        now = datetime(2026, 11, 2, 12, 0, tzinfo=KST)
        ok = door_access.check_access(AssignDb(), "2020", None, now)
        self.assertEqual((ok.bleid, ok.room_num), ("306301", "301"))
        # 앱이 보낸 bleid 가 서버가 찾은 값과 같으면 통과, 다르면 403
        door_access.check_access(AssignDb(), "2020", "306301", now)
        with self.assertRaises(door_access.AccessDenied) as ctx:
            door_access.check_access(AssignDb(), "2020", "999999", now)
        self.assertEqual(ctx.exception.reason, "bleid_mismatch")
        with self.assertRaises(door_access.AccessDenied) as ctx:
            door_access.check_access(AssignDb(odate="20260101", otime="1000"), "2020", None, now)
        self.assertEqual(ctx.exception.reason, "stay_expired")
        with self.assertRaises(door_access.AccessDenied) as ctx:
            door_access.check_access(AssignDb(bleid=""), "2020", None, now)
        self.assertEqual(ctx.exception.reason, "room_not_found")
        with self.assertRaises(door_access.AccessDenied) as ctx:
            door_access.check_access(AssignDb(), None, None, now)
        self.assertEqual(ctx.exception.reason, "not_registered")


if __name__ == "__main__":
    unittest.main()
