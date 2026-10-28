from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Account, Chat, GlobalSettings, MessageLog


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ["id", "name", "phone", "status", "auto_reply_enabled", "provider", "chat_filter_mode",
                  "allow_groups", "bootstrap_status", "bootstrapped_at", "telegram_username"]
        read_only_fields = ["status", "bootstrap_status", "bootstrapped_at", "telegram_username"]


class ChatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chat
        fields = ["id", "account", "telegram_chat_id", "title", "username", "chat_type", "auto_reply_enabled",
                  "list_status", "messages_since_summary", "last_message_at"]
        read_only_fields = ["account", "telegram_chat_id", "chat_type", "messages_since_summary", "last_message_at"]


class MessageLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageLog
        fields = ["id", "account", "chat", "telegram_msg_id", "direction", "media_type", "text", "transcript",
                  "provider", "input_tokens", "output_tokens", "status", "source", "error", "created_at", "sent_at"]


class AccountViewSet(viewsets.ModelViewSet):
    queryset = Account.objects.all().order_by("id")
    serializer_class = AccountSerializer
    http_method_names = ["get", "patch", "head", "options"]


class ChatViewSet(viewsets.ModelViewSet):
    queryset = Chat.objects.all().order_by("-last_message_at")
    serializer_class = ChatSerializer
    http_method_names = ["get", "patch", "head", "options"]


class MessageLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MessageLog.objects.all()
    serializer_class = MessageLogSerializer


@api_view(["GET", "POST"])
def kill_switch(request):
    gs = GlobalSettings.load()
    if request.method == "POST":
        gs.kill_switch = bool(request.data.get("enabled", True))
        gs.save(update_fields=["kill_switch", "updated_at"])
    return Response({"kill_switch": gs.kill_switch, "default_provider": gs.default_provider})
