# smartdoor/smartdoor/urls.py
from django.urls import path
from auth import views as auth_views

urlpatterns = [
    path("api/db-health/", auth_views.db_health),
    path("api/me/", auth_views.me),
    path("api/room-info/", auth_views.room_info),
    path("api/door/log/", auth_views.door_log),
]