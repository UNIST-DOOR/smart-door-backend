from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from auth.decorators import token_required
from django.db import connection
from datetime import datetime
import logging
import traceback

logger = logging.getLogger(__name__)


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
@api_view(["GET"])
@token_required
def room_info(request):
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
                AND MAST_STCO NOT IN ('0', '2', '5')
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

    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
        logger.info(f"Request headers: {dict(request.headers)}")
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
                AND MAST_STCO NOT IN ('0', '2', '5')
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
