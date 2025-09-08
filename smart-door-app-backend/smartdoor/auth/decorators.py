from functools import wraps
from rest_framework import exceptions
from .token import verify_jwt


def token_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise exceptions.AuthenticationFailed("Token is required")

        token = auth_header.split(" ")[1]
        try:
            user_info = verify_jwt(token)
            request._user = user_info
        except Exception as e:
            raise exceptions.AuthenticationFailed(str(e))

        return view_func(request, *args, **kwargs)

    return _wrapped_view
