from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from auth.decorators import token_required
from django.db import OperationalError, connection
from datetime import datetime
import logging
import traceback
import uuid

from auth import door_access
from auth.door_db import DjangoDb, is_lost_connection, retry_on_lost_connection
from auth.door_packet import KST, DoorPacketError, build_door_packet, build_open_frame

logger = logging.getLogger(__name__)

# 로그에 남겨도 되는 요청 헤더. 허용 목록 방식이라 Authorization(로그인 토큰), Cookie 등은 절대 남지 않는다.
_LOGGABLE_HEADERS = ("X-App-Platform", "X-App-Build", "Content-Type", "User-Agent")


def _headers_for_log(request):
    return {name: request.headers.get(name) for name in _LOGGABLE_HEADERS if request.headers.get(name) is not None}


# 현재 사용자 정보 반환
@api_view(["GET"])
@token_required
def me(request):
    try:
        user_info = getattr(request, "_user", {}) or {}
        return Response({
            "ok": True,
            "upn": user_info.get("upn"),
            "sub": user_info.get("sub"),
            "name": user_info.get("name"),
            "tid": user_info.get("tid"),
            "scopes": user_info.get("scp") or user_info.get("roles"),
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
def db_health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
        return Response({"ok": True, "result": row[0] if row else None}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# UPN으로 학번/방/동/BLEID 조회
def _room_info_impl(request):
    try:
        user_info = getattr(request, "_user", {}) or {}
        upn = (
            user_info.get("upn")
            or user_info.get("preferred_username")
            or user_info.get("email")
            or ""
        ).strip()
        if not upn:
            return Response({"ok": False, "error": "UPN not found in token"}, status=status.HTTP_400_BAD_REQUEST)

        # 1) umcs_mast 에서 UPN 매칭으로 학번(MAST_IDNO) 조회
        with connection.cursor() as cursor:
            cursor.execute(
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
            row = cursor.fetchone()

        if not row:
            payload = {"ok": False, "found": False, "reason": "UPN not mapped in umcs_mast"}
            if settings.DEBUG and request.GET.get("debug"):
                debug_candidates = []
                try:
                    user_part = upn.split('@')[0]
                    domain_part = upn.split('@')[1] if '@' in upn else ''
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT MAST_IDNO, MAST_MAIL
                            FROM umcs_mast
                            WHERE LOWER(TRIM(MAST_MAIL)) LIKE LOWER(CONCAT(TRIM(%s), '%'))
                               OR LOWER(TRIM(MAST_MAIL)) LIKE LOWER(CONCAT('%@', TRIM(%s)))
                            LIMIT 5
                            """,
                            [user_part, domain_part],
                        )
                        debug_candidates = cursor.fetchall() or []
                except Exception:
                    pass
                payload["_debug"] = {"candidates": debug_candidates}
            return Response(payload, status=status.HTTP_200_OK)

        mast_idno = str(row[0])

        # 2) fo_door_tran 에서 학번(STNO)으로 최신 ROOM 키 및 입/퇴실 일시 조회
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DOOR_TRAN_ROOM,
                       DOOR_TRAN_IDATE,
                       DOOR_TRAN_ITIME,
                       DOOR_TRAN_ODATE,
                       DOOR_TRAN_OTIME
                FROM fo_door_tran
                WHERE (CAST(DOOR_TRAN_STNO AS CHAR) = %s OR CAST(DOOR_TRAN_STNO AS UNSIGNED) = CAST(%s AS UNSIGNED))
                ORDER BY DOOR_TRAN_FDATE DESC, DOOR_TRAN_LDATE DESC, DOOR_TRAN_IDATE DESC, DOOR_TRAN_SEQ DESC
                LIMIT 1
                """,
                [mast_idno, mast_idno],
            )
            room_row = cursor.fetchone()

        if not room_row:
            payload = {"ok": False, "found": False, "reason": "No room mapped for student id"}
            if settings.DEBUG and request.GET.get("debug"):
                debug_info = {}
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT COUNT(*)
                            FROM fo_door_tran
                            WHERE (CAST(DOOR_TRAN_STNO AS CHAR) = %s OR CAST(DOOR_TRAN_STNO AS UNSIGNED) = CAST(%s AS UNSIGNED))
                            """,
                            [mast_idno, mast_idno],
                        )
                        cnt = cursor.fetchone()
                        debug_info["fo_door_tran_count_for_stno"] = cnt[0] if cnt else 0
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT DOOR_TRAN_BS, DOOR_TRAN_ROOM, DOOR_TRAN_SEQ, DOOR_TRAN_STNO,
                                   DOOR_TRAN_IDATE, DOOR_TRAN_ITIME, DOOR_TRAN_ODATE, DOOR_TRAN_OTIME, DOOR_TRAN_FDATE
                            FROM fo_door_tran
                            WHERE (CAST(DOOR_TRAN_STNO AS CHAR) = %s OR CAST(DOOR_TRAN_STNO AS UNSIGNED) = CAST(%s AS UNSIGNED))
                            ORDER BY DOOR_TRAN_FDATE DESC, DOOR_TRAN_LDATE DESC, DOOR_TRAN_IDATE DESC, DOOR_TRAN_SEQ DESC
                            LIMIT 3
                            """,
                            [mast_idno, mast_idno],
                        )
                        debug_info["fo_door_tran_samples"] = cursor.fetchall() or []
                except Exception:
                    pass
                payload["_debug"] = debug_info
            return Response(payload, status=status.HTTP_200_OK)

        room_key = str(room_row[0])
        tran_idate = str(room_row[1]) if room_row[1] is not None else None
        tran_itime = str(room_row[2]) if room_row[2] is not None else None
        tran_odate = str(room_row[3]) if room_row[3] is not None else None
        tran_otime = str(room_row[4]) if room_row[4] is not None else None
        
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ROOM_CODE_NUM, ROOM_CODE_FLOOR, ROOM_CODE_BLEID
                FROM fo_room_code
                WHERE ROOM_CODE_KEY = %s
                LIMIT 1
                """,
                [room_key],
            )
            info_row = cursor.fetchone()

        if not info_row:
            payload = {"ok": False, "found": False, "reason": "Room key not found in fo_room_code"}
            if settings.DEBUG and request.GET.get("debug"):
                debug_info = {"room_key": room_key}
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT COUNT(*)
                            FROM fo_room_code
                            WHERE ROOM_CODE_KEY = %s
                            """,
                            [room_key],
                        )
                        cnt = cursor.fetchone()
                        debug_info["fo_room_code_count_for_key"] = cnt[0] if cnt else 0
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT ROOM_CODE_KEY, ROOM_CODE_NUM, ROOM_CODE_FLOOR, ROOM_CODE_BLEID
                            FROM fo_room_code
                            WHERE ROOM_CODE_KEY = %s
                            LIMIT 3
                            """,
                            [room_key],
                        )
                        debug_info["fo_room_code_samples"] = cursor.fetchall() or []
                except Exception:
                    pass
                payload["_debug"] = debug_info
            return Response(payload, status=status.HTTP_200_OK)

        room_num = str(info_row[0])
        floor = str(info_row[1])
        ble_id = str(info_row[2])

        # 모바일에 넘길 필드 통일: building(동)과 room(호), bleId
        debug = settings.DEBUG and bool(request.GET.get("debug"))
        payload = {
            "ok": True,
            "found": True,
            "upn": upn,
            "studentId": mast_idno,
            "roomKey": room_key,
            "building": floor,  # FLOOR = 동
            "room": room_num,   # NUM = 호
            "bleId": ble_id,
            # fo_door_tran의 최근 입/퇴실 일시(원본 컬럼 그대로 반환)
            "checkInDate": tran_idate,
            "checkInTime": tran_itime,
            "checkOutDate": tran_odate,
            "checkOutTime": tran_otime,
        }
        if debug:
            payload["_debug"] = {
                "mail_match": upn,
                "queries": {
                    "umcs_mast_by_mail_ci": True,
                    "fo_door_tran_match_numeric_or_text": True,
                },
            }
        return Response(payload, status=status.HTTP_200_OK)

    except OperationalError as e:
        if is_lost_connection(e):
            raise  # 바깥의 retry_on_lost_connection 이 새로 연결해서 다시 실행한다
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# 조회만 하므로, DB 연결이 끊겨서 실패하면 연결을 새로 맺어 한 번 다시 시도한다.
# 그래도 안 되면 503(잠시 후 재시도 가능)으로 알린다. 앱이 이를 "방 정보 없음"이나 로그아웃으로 오해하지 않게 하기 위함이다.
_room_info_with_retry = retry_on_lost_connection(_room_info_impl)


@api_view(["GET"])
@token_required
def room_info(request):
    try:
        return _room_info_with_retry(request)
    except OperationalError as e:
        logger.error("방 정보 조회: DB 연결 복구 실패 (%s)", e)
        return Response({"ok": False, "error": "db_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(["POST"])
@token_required
def door_log(request):
    """
    문 열림 이벤트 로깅
    
    Headers:
        Authorization: Bearer <azure_ad_token>
    
    Request Body:
        {
            "platform": "android" or "ios",
            "doorType": "door" or "relay"
        }
    
    Response:
        200 OK:
            {
                "ok": true,
                "message": "Door log saved successfully",
                "logId": 102480
            }
        400 Bad Request: 잘못된 요청 파라미터
        401 Unauthorized: 토큰 없음 또는 유효하지 않음
        500 Internal Server Error: 서버 오류
    """
    try:
        logger.info("=== Door log API called ===")
        logger.info(f"Request data: {request.data}")
        logger.info(f"Request headers: {_headers_for_log(request)}")
        # 1. 요청 데이터 검증
        platform = request.data.get("platform", "").lower()
        door_type = request.data.get("doorType", "").lower()
        
        if platform not in ["android", "ios"]:
            return Response({
                "ok": False,
                "error": "Invalid platform. Must be 'android' or 'ios'"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if door_type not in ["door", "relay"]:
            return Response({
                "ok": False,
                "error": "Invalid doorType. Must be 'door' or 'relay'"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 플랫폼 코드 변환
        platform_code = "0x01" if platform == "android" else "0x02"
        
        # 2. 토큰에서 UPN 추출
        user_info = getattr(request, "_user", {}) or {}
        upn = (
            user_info.get("upn")
            or user_info.get("preferred_username")
            or user_info.get("email")
            or ""
        ).strip()
        
        if not upn:
            return Response({
                "ok": False,
                "error": "UPN not found in token"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 3. UPN으로 학번 조회
        with connection.cursor() as cursor:
            cursor.execute(
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
            row = cursor.fetchone()
        
        if not row:
            return Response({
                "ok": False,
                "error": "User not found in system"
            }, status=status.HTTP_404_NOT_FOUND)
        
        student_id = str(row[0])
        
        # 4. 학번으로 방 정보 조회 (fo_door_tran → fo_room_code)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DOOR_TRAN_ROOM
                FROM fo_door_tran
                WHERE (CAST(DOOR_TRAN_STNO AS CHAR) = %s OR CAST(DOOR_TRAN_STNO AS UNSIGNED) = CAST(%s AS UNSIGNED))
                ORDER BY DOOR_TRAN_FDATE DESC, DOOR_TRAN_LDATE DESC, DOOR_TRAN_IDATE DESC, DOOR_TRAN_SEQ DESC
                LIMIT 1
                """,
                [student_id, student_id],
            )
            room_row = cursor.fetchone()
        
        if not room_row:
            return Response({
                "ok": False,
                "error": "Room not assigned to student"
            }, status=status.HTTP_404_NOT_FOUND)
        
        room_key = str(room_row[0])
        
        # 5. 방 키로 방번호와 BridgeID 조회
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ROOM_CODE_NUM, ROOM_CODE_BRIDGEID
                FROM fo_room_code
                WHERE ROOM_CODE_KEY = %s
                LIMIT 1
                """,
                [room_key],
            )
            room_info = cursor.fetchone()
        
        if not room_info:
            return Response({
                "ok": False,
                "error": "Room information not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        room_number = str(room_info[0])
        bridge_id = str(room_info[1])
        
        # 6. 현재 시간 (MySQL datetime 포맷: 24시간 형식)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 7. mqtt_cmd_log 테이블에 INSERT
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO mqtt_cmd_log (
                    LOG_CMD_BS,
                    LOG_CMD_NUM,
                    LOG_CMD_TIME,
                    LOG_CMD_TYPE,
                    LOG_CMD_MC,
                    LOG_CMD_SERIAL,
                    LOG_CMD_0,
                    LOG_CMD_1,
                    LOG_CMD_2,
                    LOG_CMD_3,
                    LOG_CMD_4,
                    LOG_CMD_5,
                    LOG_CMD_6,
                    LOG_CMD_7,
                    LOG_CMD_8,
                    LOG_CMD_9,
                    LOG_CMD_10,
                    LOG_CMD_11,
                    LOG_CMD_OPEN,
                    LOG_CMD_USER,
                    LOG_CMD_ACTION
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [
                    "0020001",  # LOG_CMD_BS (고정)
                    room_number,  # LOG_CMD_NUM (방번호)
                    current_time,  # LOG_CMD_TIME
                    "rec",  # LOG_CMD_TYPE (고정)
                    door_type,  # LOG_CMD_MC (door or relay)
                    bridge_id,  # LOG_CMD_SERIAL (BridgeID)
                    '"0":"0xcc","1":"0x81","2":"0x05","3":"0x0b","4":"0x00","5":"0x00","6":"0x00","7":"0x00","8":"0x00","9":"0x5c"',  # LOG_CMD_0 (고정)
                    "0x81",  # LOG_CMD_1 (고정)
                    "0x05",  # LOG_CMD_2 (고정)
                    platform_code,  # LOG_CMD_3 (플랫폼: 0x01=Android, 0x02=iOS)
                    "0x00",  # LOG_CMD_4 (고정)
                    "0x00",  # LOG_CMD_5 (고정)
                    "0x00",  # LOG_CMD_6 (고정)
                    "0x00",  # LOG_CMD_7 (고정)
                    "0x00",  # LOG_CMD_8 (고정)
                    "0x00",  # LOG_CMD_9 (고정)
                    "0x00",  # LOG_CMD_10 (고정)
                    "0x00",  # LOG_CMD_11 (고정)
                    "0110003",  # LOG_CMD_OPEN (고정)
                    student_id,  # LOG_CMD_USER (학번)
                    None,  # LOG_CMD_ACTION (NULL)
                ],
            )
            log_id = cursor.lastrowid
        
        return Response({
            "ok": True,
            "message": "Door log saved successfully",
            "data": {
                "logId": log_id,
                "studentId": student_id,
                "roomNumber": room_number,
                "doorType": door_type,
                "platform": platform,
                "timestamp": current_time
            }
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error("=== Door log API ERROR ===")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return Response({
            "ok": False,
            "error": str(e),
            "error_type": type(e).__name__
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── 앱 BLE 서명 문열기 ─────────────────────────────────────────
# 앱은 키를 갖지 않는다. 서버가 권한 확인, 키 조회, 패킷 생성과 서명을 맡고
# 앱은 받은 바이트를 도어락 모듈에 그대로 쓴 뒤 결과를 보고한다.

def _upn_from_request(request):
    user_info = getattr(request, "_user", {}) or {}
    return (
        user_info.get("upn")
        or user_info.get("preferred_username")
        or user_info.get("email")
        or ""
    ).strip()


def _text_field(data, name, max_len):
    value = data.get(name) if isinstance(data, dict) else None
    return value.strip()[:max_len] if isinstance(value, str) else None


@api_view(["POST"])
@token_required
def open_packet(request):
    """
    문 열기 패킷 발급 (서명 대상 문이면 서명 패킷, 아니면 원본 패킷)

    Request Body:
        { "bleid": "306301" (선택, 서버가 찾은 값과 다르면 403), "retryOf": "<requestId>" (선택, 재시도) }
    Response 200:
        { "ok": true, "requestId", "packetHex", "signed", "keyVer", "counter", "bleid" }
    403 권한 없음 / 429 요청 과다 / 426 구버전(미들웨어) / 500 패킷 생성 실패
    """
    upn = _upn_from_request(request)
    if not upn:
        return Response({"ok": False, "error": "UPN not found in token"}, status=status.HTTP_400_BAD_REQUEST)

    data = request.data if isinstance(request.data, dict) else {}
    requested_bleid = _text_field(data, "bleid", 16)
    retry_of = _text_field(data, "retryOf", 36)
    app_ver = (request.headers.get("X-App-Build") or "")[:20]
    os_name = (request.headers.get("X-App-Platform") or "").lower()[:20]

    db = DjangoDb()
    req_id = str(uuid.uuid4())
    now = datetime.now(KST)

    try:
        student_id = door_access.find_student_id(db, upn)
        user_id = student_id or upn[:50]

        # 패킷을 대량으로 받아 두는 것을 막는다 (사용자당 분당 10회). 모든 워커가 공유하도록 DB 로그로 센다.
        if door_access.count_recent_requests(db, user_id) >= door_access.RATE_LIMIT_PER_MINUTE:
            return Response({"ok": False, "error": "rate_limited"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        if retry_of and not door_access.retry_of_is_valid(db, user_id, retry_of):
            retry_of = None

        try:
            assignment = door_access.check_access(db, student_id, requested_bleid, now)
        except door_access.AccessDenied as denied:
            door_access.insert_issue_log(
                db, req_id=req_id, retry_of=retry_of, user_id=user_id,
                bleid=door_access.digits_only(requested_bleid), room=None, issued=False,
                signed=None, key_ver=None, counter=None, app_ver=app_ver, os_name=os_name,
            )
            return Response({"ok": False, "error": "forbidden", "reason": denied.reason},
                            status=status.HTTP_403_FORBIDDEN)

        frame = build_open_frame(assignment.bleid, now)
        packet = build_door_packet(db, frame)

        # 발급 로그는 응답 직전에 남긴다. 로그 실패가 문 열기를 막지는 않게 한다.
        try:
            door_access.insert_issue_log(
                db, req_id=req_id, retry_of=retry_of, user_id=user_id,
                bleid=assignment.bleid, room=assignment.room_num, issued=True,
                signed=packet.signed, key_ver=packet.key_ver, counter=packet.counter,
                app_ver=app_ver, os_name=os_name,
            )
        except Exception:
            logger.exception("BLE_OPEN_LOG 발급 로그 기록 실패 (req=%s)", req_id)

        return Response({
            "ok": True,
            "requestId": req_id,
            "packetHex": packet.packet_hex,
            "signed": packet.signed,
            "keyVer": packet.key_ver,
            "counter": packet.counter,
            "bleid": assignment.bleid,
        }, status=status.HTTP_200_OK)

    except DoorPacketError as e:
        # DoorPacketError 메시지에는 키 값이 들어가지 않는다.
        logger.error("open_packet 패킷 생성 실패: %s", e)
    except Exception:
        logger.exception("open_packet 실패")
    return Response({"ok": False, "error": "packet_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@token_required
def open_result(request):
    """
    문 열기 결과 보고 (참고용. 문이 실제로 열렸다는 증거는 아니다)

    Request Body:
        { "requestId", "result": "OK|NO_RESPONSE|BLE_FAIL|DOOR_FAIL", "stage", "doorResponseHex", "elapsedMs" }
    본인이 발급받은 requestId 에 한 번만 기록할 수 있다.
    """
    upn = _upn_from_request(request)
    if not upn:
        return Response({"ok": False, "error": "UPN not found in token"}, status=status.HTTP_400_BAD_REQUEST)

    data = request.data if isinstance(request.data, dict) else {}
    req_id = _text_field(data, "requestId", 36)
    result = _text_field(data, "result", 12)
    if not req_id or result not in door_access.RESULT_CODES:
        return Response({"ok": False, "error": "invalid_request"}, status=status.HTTP_400_BAD_REQUEST)

    elapsed = data.get("elapsedMs")
    elapsed_ms = elapsed if isinstance(elapsed, int) and not isinstance(elapsed, bool) and 0 <= elapsed <= 2**31 - 1 else None

    try:
        db = DjangoDb()
        user_id = door_access.find_student_id(db, upn) or upn[:50]
        updated = door_access.update_result_log(
            db, req_id=req_id, user_id=user_id, result=result,
            stage=_text_field(data, "stage", 20),
            door_resp=_text_field(data, "doorResponseHex", 80),
            elapsed_ms=elapsed_ms,
        )
    except Exception:
        logger.exception("open_result 실패")
        return Response({"ok": False, "error": "result_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if not updated:
        return Response({"ok": False, "error": "request_not_found"}, status=status.HTTP_404_NOT_FOUND)
    return Response({"ok": True}, status=status.HTTP_200_OK)
