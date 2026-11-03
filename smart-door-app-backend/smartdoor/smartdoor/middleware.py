from django.utils.deprecation import MiddlewareMixin


class SetRemoteAddrFromForwardedFor(MiddlewareMixin):
    def process_request(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            request.META["REMOTE_ADDR"] = x_forwarded_for.split(",")[0].strip()


class MinBuildVersionMiddleware(MiddlewareMixin):
    """Reject requests from Android app builds older than MIN_ANDROID_BUILD.

    Client must send headers:
      - X-App-Platform: android
      - X-App-Build: <integer versionCode>
    """

    def process_request(self, request):
        try:
            platform = request.headers.get("X-App-Platform", "").lower()
            if platform not in {"android", "ios"}:
                return None

            build_header = request.headers.get("X-App-Build")
            if not build_header:
                return None

            try:
                build_code = int(build_header)
            except Exception:
                return None

            from django.conf import settings

            min_required = {
                "android": int(getattr(settings, "MIN_ANDROID_BUILD", 1)),
                "ios": int(getattr(settings, "MIN_IOS_BUILD", 1)),
            }.get(platform, 1)

            if build_code < min_required:
                from django.http import JsonResponse

                return JsonResponse(
                    {
                        "ok": False,
                        "error": "upgrade_required",
                        "message": "새 버전이 필요합니다. 스토어에서 업데이트해 주세요.",
                        "platform": platform,
                        "minBuild": min_required,
                        "yourBuild": build_code,
                    },
                    status=426,  # Upgrade Required
                )
        except Exception:
            # 미들웨어 오류로 서비스 영향 주지 않음
            return None
        return None


class DbConnectionHealthMiddleware(MiddlewareMixin):
    """요청을 처리하기 전에 DB 연결이 살아 있는지 확인하고, 죽어 있으면 닫아서 새로 연결하게 한다.

    DB 서버나 중간 네트워크 장비가 쉬는 연결을 끊으면, 오래 쉰 뒤의 첫 요청이 죽은 연결로 쿼리를 보내
    2013(Lost connection) 오류가 난다. 앱은 이 오류를 로그인 실패로 받아들이므로 요청마다 미리 점검한다.
    점검 중 오류가 나도 요청 처리는 막지 않는다.
    """

    def process_request(self, request):
        try:
            from auth.door_db import close_dead_connection

            close_dead_connection()
        except Exception:
            pass
        return None
