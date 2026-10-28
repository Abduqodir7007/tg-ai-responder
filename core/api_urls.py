from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api import AccountViewSet, ChatViewSet, MessageLogViewSet, kill_switch

router = DefaultRouter()
router.register("accounts", AccountViewSet)
router.register("chats", ChatViewSet)
router.register("messages", MessageLogViewSet)

urlpatterns = [
    path("kill-switch/", kill_switch, name="kill-switch"),
    path("", include(router.urls)),
]
