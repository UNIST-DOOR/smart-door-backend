from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from auth.decorators import token_required
from django.db import connection


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
