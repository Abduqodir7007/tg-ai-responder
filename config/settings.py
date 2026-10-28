import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value else default


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

if env("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER", "postgres"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "postgres"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Asia/Tashkent")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAdminUser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
}

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_BEAT_SCHEDULE = {
    "maintain-contexts": {
        "task": "core.tasks.maintain_contexts",
        "schedule": float(env_int("CONTEXT_MAINTENANCE_INTERVAL_SECONDS", 1800)),
    },
}

FERNET_KEY = env("FERNET_KEY", "")
INTERNAL_SERVICE_TOKEN = env("INTERNAL_SERVICE_TOKEN", "dev-internal-token")
AI_SERVICE_URLS = {
    "claude": env("CLAUDE_SERVICE_URL", "http://claude-service:8000"),
    "gemini": env("GEMINI_SERVICE_URL", "http://gemini-service:8000"),
}
AI_SERVICE_TIMEOUT = float(env_int("AI_SERVICE_TIMEOUT", 180))
AI_RETRY_ATTEMPTS = int(env("AI_RETRY_ATTEMPTS", "2"))
AI_RETRY_DELAY_SECONDS = float(env("AI_RETRY_DELAY_SECONDS", "2"))
AI_FALLBACK_MODELS = {
    "gemini": [m.strip() for m in env("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-flash-latest").split(",") if m.strip()],
    "claude": [m.strip() for m in env("CLAUDE_FALLBACK_MODELS", "").split(",") if m.strip()],
}
DEFAULT_MODELS = {
    "claude": env("CLAUDE_DEFAULT_MODEL", "claude-sonnet-5-5"),
    "gemini": env("GEMINI_DEFAULT_MODEL", "gemini-3.6-flash"),
}
TELEGRAM_OUTBOX_KEY = env("TELEGRAM_OUTBOX_KEY", "tg:outbox")
LISTENER_ACCOUNT_SYNC_SECONDS = env_int("LISTENER_ACCOUNT_SYNC_SECONDS", 15)
MAX_MEDIA_BYTES = env_int("MAX_MEDIA_MB", 20) * 1024 * 1024

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}


UNFOLD = {
    "SITE_TITLE": "TG AI Responder",
    "SITE_HEADER": "TG AI Responder",
    "SITE_SYMBOL": "smart_toy",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "BORDER_RADIUS": "8px",
    "COLORS": {
        "primary": {
            "50": "oklch(97.7% .014 308.299)",
            "100": "oklch(94.6% .033 307.174)",
            "200": "oklch(90.2% .063 306.703)",
            "300": "oklch(82.7% .119 306.383)",
            "400": "oklch(71.4% .203 305.504)",
            "500": "oklch(62.7% .265 303.9)",
            "600": "oklch(55.8% .288 302.321)",
            "700": "oklch(49.6% .265 301.924)",
            "800": "oklch(43.8% .218 303.724)",
            "900": "oklch(38.1% .176 304.987)",
            "950": "oklch(29.1% .149 302.717)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Telegram",
                "separator": True,
                "items": [
                    {"title": "Akkauntlar", "icon": "account_circle", "link": "/admin/core/account/"},
                    {"title": "Chatlar", "icon": "forum", "link": "/admin/core/chat/"},
                    {"title": "Kontekstlar", "icon": "psychology", "link": "/admin/core/contactcontext/"},
                    {"title": "Xabarlar jurnali", "icon": "receipt_long", "link": "/admin/core/messagelog/"},
                ],
            },
            {
                "title": "Sozlamalar",
                "separator": True,
                "items": [
                    {"title": "AI provayderlar", "icon": "key", "link": "/admin/core/providerconfig/"},
                    {"title": "Umumiy sozlamalar", "icon": "tune", "link": "/admin/core/globalsettings/"},
                    {"title": "Foydalanuvchilar", "icon": "group", "link": "/admin/auth/user/"},
                ],
            },
        ],
    },
}
