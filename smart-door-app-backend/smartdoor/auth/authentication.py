from rest_framework import exceptions
from .token import verify_jwt
import logging

log = logging.getLogger(__name__)

class AuthenticatedUser:
    def __init__(self, user_info):
        self.user_info = user_info
        self.is_authenticated = True
        
    def __getattr__(self, name):
        if name in self.user_info:
            return self.user_info[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def __getitem__(self, key):
        return self.user_info[key]

    def get(self, key, default=None):
        return self.user_info.get(key, default)

class TokenRequiredMixin:
    def initial(self, request, *args, **kwargs):
        try:
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                raise exceptions.AuthenticationFailed("Token is required")
 
            token = auth_header.split(" ")[1]
            try:
                user_info = verify_jwt(token)
                request._user = AuthenticatedUser(user_info)
            except Exception as e:
                raise exceptions.AuthenticationFailed(str(e))
 
            super().initial(request, *args, **kwargs)
        except Exception as exc:
            log.error(f"Authentication error: {exc}", exc_info=True)
            self.exc = exc
            raise