from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from . import telegram_login
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.decorators import display
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .forms import AccountForm, CodeForm, PasswordForm, PhoneForm, ProviderConfigForm
from .models import Account, Chat, ContactContext, GlobalSettings, MessageLog, ProviderConfig
from .tasks import rebootstrap_chat, start_bootstrap, summarize_chat


@admin.register(GlobalSettings)
class GlobalSettingsAdmin(ModelAdmin):
    list_display = ("__str__", "kill_switch", "default_provider", "updated_at")
    fieldsets = (
        ("Safety", {"fields": ("kill_switch", "burst_window_seconds", "reply_delay_min_seconds",
                               "reply_delay_max_seconds", "min_seconds_between_replies", "max_replies_per_hour")}),
        ("AI", {"fields": ("default_provider", "reply_max_tokens", "recent_messages_count", "max_images_in_reply")}),
        ("Context maintenance", {"fields": ("resummarize_every_n_messages", "context_refresh_hours",
                                            "summary_chunk_size", "summary_max_messages")}),
        ("Bootstrap", {"fields": ("bootstrap_dialog_limit", "bootstrap_messages_per_dialog")}),
    )

    def has_add_permission(self, request):
        return not GlobalSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = GlobalSettings.load()
        return redirect(reverse("admin:core_globalsettings_change", args=[obj.pk]))


@admin.register(ProviderConfig)
class ProviderConfigAdmin(ModelAdmin):
    form = ProviderConfigForm
    list_display = ("provider", "masked_key", "model_name", "enabled", "updated_at")
    readonly_fields = ("masked_key",)

    @admin.display(description="API key")
    def masked_key(self, obj):
        return obj.masked_api_key or "-"

    @admin.display(description="Model")
    def model_name(self, obj):
        return obj.effective_model


class ChatInline(TabularInline):
    model = Chat
    extra = 0
    fields = ("title", "username", "chat_type", "auto_reply_enabled", "list_status", "messages_since_summary")
    readonly_fields = ("title", "username", "chat_type", "messages_since_summary")
    show_change_link = True
    max_num = 0


@admin.register(Account)
class AccountAdmin(ModelAdmin):
    form = AccountForm
    list_display = ("name", "phone", "status_badge", "auto_reply_enabled", "provider_label", "bootstrap_badge",
                    "connect_link")
    list_filter = ("status", "auto_reply_enabled", "provider")
    readonly_fields = ("masked_hash", "status", "telegram_user_id", "telegram_username", "bootstrap_status",
                       "bootstrapped_at", "last_error", "connect_link")
    actions = ["pause_auto_reply", "resume_auto_reply", "run_bootstrap", "disconnect"]
    inlines = [ChatInline]

    def get_fieldsets(self, request, obj=None):
        base = [
            ("Telegram API", {"fields": ["name", "phone", "api_id", "api_hash"] + (["masked_hash"] if obj else [])}),
            ("Auto-reply", {"fields": ["auto_reply_enabled", "chat_filter_mode", "allow_groups"]}),
            ("AI", {"fields": ["provider", "model_override", "persona_prompt"]}),
        ]
        if obj:
            base.append(("Status", {"fields": ["status", "connect_link", "telegram_user_id", "telegram_username",
                                               "bootstrap_status", "bootstrapped_at", "last_error"]}))
        return base

    @display(description="Status", label={
        Account.Status.CONNECTED: "success",
        Account.Status.CODE_SENT: "warning",
        Account.Status.PASSWORD_NEEDED: "warning",
        Account.Status.ERROR: "danger",
        Account.Status.DISCONNECTED: "danger",
    })
    def status_badge(self, obj):
        return obj.status, obj.get_status_display()

    @display(description="Bootstrap", label=True)
    def bootstrap_badge(self, obj):
        return obj.get_bootstrap_status_display()

    @admin.display(description="API hash")
    def masked_hash(self, obj):
        return obj.masked_api_hash or "-"

    @admin.display(description="Provider")
    def provider_label(self, obj):
        return obj.get_provider_display() if obj.provider else "global default"

    @admin.display(description="Connection")
    def connect_link(self, obj):
        if not obj.pk:
            return "-"
        label = "Reconnect" if obj.status == Account.Status.CONNECTED else "Connect"
        return format_html(
            '<a class="bg-primary-600 text-white font-medium px-3 py-1.5 rounded-default inline-block" href="{}">{}</a>',
            reverse("admin:core_account_connect", args=[obj.pk]),
            label,
        )

    def get_urls(self):
        custom = [
            path("<int:pk>/connect/", self.admin_site.admin_view(self.connect_view), name="core_account_connect"),
        ]
        return custom + super().get_urls()

    def connect_view(self, request, pk):
        account = get_object_or_404(Account, pk=pk)
        step = {
            Account.Status.CODE_SENT: "code",
            Account.Status.PASSWORD_NEEDED: "password",
        }.get(account.status, "phone")
        if request.GET.get("restart"):
            step = "phone"
        form_class = {"phone": PhoneForm, "code": CodeForm, "password": PasswordForm}[step]
        initial = {"phone": account.phone} if step == "phone" else None
        form = form_class(request.POST or None, initial=initial)
        if request.method == "POST" and form.is_valid():
            try:
                if step == "phone":
                    account.phone = form.cleaned_data["phone"].strip()
                    telegram_login.send_code(account)
                    messages.info(request, "Code sent. Enter the code from Telegram.")
                elif step == "code":
                    telegram_login.submit_code(account, form.cleaned_data["code"])
                else:
                    telegram_login.submit_password(account, form.cleaned_data["password"])
            except telegram_login.LoginError as exc:
                messages.error(request, f"Login failed: {exc}")
                return redirect(request.path)
            account.refresh_from_db()
            if account.status == Account.Status.CONNECTED:
                messages.success(request, "Account connected. Bootstrap of existing dialogs has started.")
                return redirect(reverse("admin:core_account_change", args=[account.pk]))
            return redirect(request.path)
        context = {
            **self.admin_site.each_context(request),
            "title": f"Connect {account}",
            "account": account,
            "form": form,
            "step": step,
            "opts": self.model._meta,
        }
        return render(request, "admin/core/account/connect.html", context)

    @admin.action(description="Pause auto-reply")
    def pause_auto_reply(self, request, queryset):
        queryset.update(auto_reply_enabled=False)

    @admin.action(description="Resume auto-reply")
    def resume_auto_reply(self, request, queryset):
        queryset.update(auto_reply_enabled=True)

    @admin.action(description="Run bootstrap of existing dialogs")
    def run_bootstrap(self, request, queryset):
        for account in queryset:
            start_bootstrap.delay(account.pk)
        self.message_user(request, "Bootstrap requested")

    @admin.action(description="Disconnect (stop listener session)")
    def disconnect(self, request, queryset):
        queryset.update(status=Account.Status.DISCONNECTED)


class ContactContextInline(StackedInline):
    model = ContactContext
    extra = 0


@admin.register(Chat)
class ChatAdmin(ModelAdmin):
    list_display = ("__str__", "account", "chat_type", "auto_reply_enabled", "list_status", "messages_since_summary",
                    "last_message_at")
    list_filter = ("account", "chat_type", "auto_reply_enabled", "list_status")
    search_fields = ("title", "username", "telegram_chat_id")
    list_editable = ("auto_reply_enabled", "list_status")
    readonly_fields = ("telegram_chat_id", "messages_since_summary", "last_message_at")
    inlines = [ContactContextInline]
    actions = ["enable_auto_reply", "disable_auto_reply", "whitelist", "blacklist", "unlist", "rebootstrap",
               "resummarize"]

    @admin.action(description="Enable auto-reply")
    def enable_auto_reply(self, request, queryset):
        queryset.update(auto_reply_enabled=True)

    @admin.action(description="Disable auto-reply")
    def disable_auto_reply(self, request, queryset):
        queryset.update(auto_reply_enabled=False)

    @admin.action(description="Add to whitelist")
    def whitelist(self, request, queryset):
        queryset.update(list_status=Chat.ListStatus.WHITELISTED)

    @admin.action(description="Add to blacklist")
    def blacklist(self, request, queryset):
        queryset.update(list_status=Chat.ListStatus.BLACKLISTED)

    @admin.action(description="Remove from lists")
    def unlist(self, request, queryset):
        queryset.update(list_status=Chat.ListStatus.NONE)

    @admin.action(description="Re-bootstrap chat (rebuild context from history)")
    def rebootstrap(self, request, queryset):
        for chat in queryset:
            rebootstrap_chat.delay(chat.pk)
        self.message_user(request, f"Re-bootstrap requested for {queryset.count()} chat(s)")

    @admin.action(description="Re-summarize now")
    def resummarize(self, request, queryset):
        for chat in queryset:
            summarize_chat.delay(chat.pk, "update")


@admin.register(ContactContext)
class ContactContextAdmin(ModelAdmin):
    list_display = ("chat", "name", "relationship", "language", "last_summarized_msg_id", "updated_at")
    search_fields = ("name", "summary", "chat__title", "chat__username")
    list_filter = ("chat__account",)


@admin.register(MessageLog)
class MessageLogAdmin(ModelAdmin):
    list_display = ("created_at", "chat", "direction_badge", "source", "media_type", "short_text", "status",
                    "provider", "input_tokens", "output_tokens")
    list_filter = ("account", "direction", "source", "status", "media_type", "provider")
    search_fields = ("text", "transcript", "chat__title", "chat__username")
    readonly_fields = [field.name for field in MessageLog._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    @display(description="Direction", label={"in": "info", "out": "success"})
    def direction_badge(self, obj):
        return obj.direction, obj.get_direction_display()

    @admin.display(description="Text")
    def short_text(self, obj):
        value = obj.as_text()
        return value if len(value) <= 80 else value[:77] + "..."


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass
