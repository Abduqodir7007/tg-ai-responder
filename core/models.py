from django.conf import settings
from django.db import models
from django.utils import timezone

from .crypto import decrypt, encrypt, mask


class Provider(models.TextChoices):
    CLAUDE = "claude", "Claude (Anthropic)"
    GEMINI = "gemini", "Gemini (Google)"


class GlobalSettings(models.Model):
    kill_switch = models.BooleanField(default=False)
    default_provider = models.CharField(max_length=16, choices=Provider.choices, default=Provider.CLAUDE)
    burst_window_seconds = models.PositiveIntegerField(default=20)
    reply_delay_min_seconds = models.PositiveIntegerField(default=4)
    reply_delay_max_seconds = models.PositiveIntegerField(default=15)
    min_seconds_between_replies = models.PositiveIntegerField(default=30)
    max_replies_per_hour = models.PositiveIntegerField(default=20)
    recent_messages_count = models.PositiveIntegerField(default=8)
    max_images_in_reply = models.PositiveIntegerField(default=3)
    resummarize_every_n_messages = models.PositiveIntegerField(default=20)
    context_refresh_hours = models.PositiveIntegerField(default=24)
    summary_chunk_size = models.PositiveIntegerField(default=60)
    summary_max_messages = models.PositiveIntegerField(default=300)
    bootstrap_dialog_limit = models.PositiveIntegerField(default=50)
    bootstrap_messages_per_dialog = models.PositiveIntegerField(default=200)
    reply_max_tokens = models.PositiveIntegerField(default=800)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Global settings"
        verbose_name_plural = "Global settings"

    def __str__(self):
        return "Global settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ProviderConfig(models.Model):
    provider = models.CharField(max_length=16, choices=Provider.choices, unique=True)
    api_key_encrypted = models.TextField(blank=True, default="")
    model = models.CharField(max_length=100, blank=True, default="")
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.get_provider_display()

    def set_api_key(self, value: str):
        self.api_key_encrypted = encrypt(value)

    def get_api_key(self) -> str:
        return decrypt(self.api_key_encrypted)

    @property
    def masked_api_key(self) -> str:
        return mask(self.get_api_key()) if self.api_key_encrypted else ""

    @property
    def effective_model(self) -> str:
        return self.model or settings.DEFAULT_MODELS[self.provider]


class Account(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CODE_SENT = "code_sent", "Code sent"
        PASSWORD_NEEDED = "password_needed", "2FA password needed"
        CONNECTED = "connected", "Connected"
        DISCONNECTED = "disconnected", "Disconnected"
        ERROR = "error", "Error"

    class FilterMode(models.TextChoices):
        ALL = "all", "All private chats"
        WHITELIST = "whitelist", "Only whitelisted chats"
        BLACKLIST = "blacklist", "All except blacklisted chats"

    class BootstrapStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=32, blank=True, default="")
    api_id = models.PositiveIntegerField()
    api_hash_encrypted = models.TextField(blank=True, default="")
    session_encrypted = models.TextField(blank=True, default="")
    phone_code_hash = models.CharField(max_length=255, blank=True, default="")
    telegram_user_id = models.BigIntegerField(null=True, blank=True)
    telegram_username = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    last_error = models.TextField(blank=True, default="")
    auto_reply_enabled = models.BooleanField(default=False)
    provider = models.CharField(max_length=16, choices=Provider.choices, blank=True, default="")
    model_override = models.CharField(max_length=100, blank=True, default="")
    persona_prompt = models.TextField(blank=True, default="")
    chat_filter_mode = models.CharField(max_length=16, choices=FilterMode.choices, default=FilterMode.ALL)
    allow_groups = models.BooleanField(default=False)
    bootstrap_status = models.CharField(
        max_length=16, choices=BootstrapStatus.choices, default=BootstrapStatus.PENDING
    )
    bootstrapped_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.phone or self.telegram_username or self.pk})"

    def set_api_hash(self, value: str):
        self.api_hash_encrypted = encrypt(value)

    def get_api_hash(self) -> str:
        return decrypt(self.api_hash_encrypted)

    def set_session(self, value: str):
        self.session_encrypted = encrypt(value)

    def get_session(self) -> str:
        return decrypt(self.session_encrypted)

    @property
    def masked_api_hash(self) -> str:
        return mask(self.get_api_hash()) if self.api_hash_encrypted else ""

    @property
    def is_connected(self) -> bool:
        return self.status == self.Status.CONNECTED and bool(self.session_encrypted)


class Chat(models.Model):
    class ChatType(models.TextChoices):
        PRIVATE = "private", "Private"
        GROUP = "group", "Group"
        CHANNEL = "channel", "Channel"

    class ListStatus(models.TextChoices):
        NONE = "none", "Not listed"
        WHITELISTED = "whitelisted", "Whitelisted"
        BLACKLISTED = "blacklisted", "Blacklisted"

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="chats")
    telegram_chat_id = models.BigIntegerField()
    title = models.CharField(max_length=255, blank=True, default="")
    username = models.CharField(max_length=64, blank=True, default="")
    chat_type = models.CharField(max_length=16, choices=ChatType.choices, default=ChatType.PRIVATE)
    is_bot = models.BooleanField(default=False)
    auto_reply_enabled = models.BooleanField(default=True)
    list_status = models.CharField(max_length=16, choices=ListStatus.choices, default=ListStatus.NONE)
    messages_since_summary = models.PositiveIntegerField(default=0)
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "telegram_chat_id"], name="uniq_account_chat"),
        ]

    def __str__(self):
        return self.title or self.username or str(self.telegram_chat_id)


class ContactContext(models.Model):
    FIELDS = ("name", "relationship", "language", "tone", "topics", "summary", "facts", "open_tasks", "open_questions")

    chat = models.OneToOneField(Chat, on_delete=models.CASCADE, related_name="context")
    name = models.CharField(max_length=255, blank=True, default="")
    relationship = models.CharField(max_length=255, blank=True, default="")
    language = models.CharField(max_length=64, blank=True, default="")
    tone = models.CharField(max_length=255, blank=True, default="")
    topics = models.JSONField(default=list, blank=True)
    summary = models.TextField(blank=True, default="")
    facts = models.JSONField(default=dict, blank=True)
    open_tasks = models.JSONField(default=list, blank=True)
    open_questions = models.JSONField(default=list, blank=True)
    last_summarized_msg_id = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Context: {self.chat}"

    def as_dict(self) -> dict:
        return {field: getattr(self, field) for field in self.FIELDS}

    def apply(self, data: dict):
        for field in self.FIELDS:
            value = data.get(field)
            if value is not None:
                setattr(self, field, value)


class MessageLog(models.Model):
    class Direction(models.TextChoices):
        IN = "in", "Incoming"
        OUT = "out", "Outgoing"

    class MediaType(models.TextChoices):
        TEXT = "text", "Text"
        PHOTO = "photo", "Photo"
        VIDEO = "video", "Video"
        VIDEO_NOTE = "video_note", "Video note"
        VOICE = "voice", "Voice"
        AUDIO = "audio", "Audio"
        DOCUMENT = "document", "Document"
        STICKER = "sticker", "Sticker"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        QUEUED = "queued", "Queued for reply"
        REPLIED = "replied", "Replied"
        SKIPPED = "skipped", "Skipped"
        PENDING_SEND = "pending_send", "Pending send"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        TELEGRAM = "telegram", "Contact"
        OWNER = "owner", "Owner (manual)"
        AI = "ai", "AI"
        BOOTSTRAP = "bootstrap", "Bootstrap history"

    TRANSCRIBABLE = {MediaType.VIDEO, MediaType.VIDEO_NOTE, MediaType.VOICE, MediaType.AUDIO}

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="messages")
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    telegram_msg_id = models.BigIntegerField(null=True, blank=True)
    direction = models.CharField(max_length=4, choices=Direction.choices)
    media_type = models.CharField(max_length=16, choices=MediaType.choices, default=MediaType.TEXT)
    text = models.TextField(blank=True, default="")
    transcript = models.TextField(blank=True, default="")
    media_path = models.CharField(max_length=500, blank=True, default="")
    media_mime = models.CharField(max_length=100, blank=True, default="")
    provider = models.CharField(max_length=16, blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.TELEGRAM)
    reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replies")
    error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["chat", "telegram_msg_id"],
                condition=models.Q(telegram_msg_id__isnull=False),
                name="uniq_chat_msg",
            ),
        ]
        indexes = [models.Index(fields=["chat", "direction", "created_at"])]

    def __str__(self):
        return f"{self.get_direction_display()} {self.media_type} #{self.telegram_msg_id or self.pk}"

    @property
    def needs_transcript(self) -> bool:
        return self.media_type in self.TRANSCRIBABLE and bool(self.media_path) and not self.transcript

    def as_text(self) -> str:
        parts = []
        if self.media_type != self.MediaType.TEXT:
            parts.append(f"[{self.media_type}]")
        if self.transcript:
            parts.append(self.transcript)
        if self.text:
            parts.append(self.text)
        return " ".join(parts).strip()
