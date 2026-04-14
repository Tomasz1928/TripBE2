"""
Production settings for Render deployment.
Imports everything from base settings and overrides what's needed.
"""
from .settings import *  # noqa: F401,F403
import dj_database_url
import os

# ── Security ─────────────────────────────────────────────────
DEBUG = False

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is required in production!")

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")
# Render gives you a .onrender.com domain — add it here or via env var

# CSRF trusted origins (needed for POST requests from your frontend)
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

# ── Database (PostgreSQL on Render) ──────────────────────────
DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL"),
        conn_max_age=600,
        conn_health_checks=True,
        ssl_require=True,
    ),
}

# ── Static files (WhiteNoise) ────────────────────────────────
STATIC_ROOT = BASE_DIR / "staticfiles"

MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ── Channels layer ───────────────────────────────────────────
# For production with multiple workers you'd want Redis,
# but InMemoryChannelLayer works for a single Daphne process on Render.
# If you add a Redis instance later, switch to:
#   pip install channels-redis
#   CHANNEL_LAYERS = {
#       "default": {
#           "BACKEND": "channels_redis.core.RedisChannelLayer",
#           "CONFIG": {"hosts": [os.environ.get("REDIS_URL")]},
#       }
#   }

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

# ── Security headers ────────────────────────────────────────
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True") == "True"

# ── Logging ──────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "render": {
            "format": "[{asctime}] {levelname} {name} | {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "render",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "TripApp": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}