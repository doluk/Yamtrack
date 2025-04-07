"""Django settings for Yamtrack project."""

import json
import warnings
import zoneinfo
from pathlib import Path
from urllib.parse import urlparse

from decouple import Csv, config
from django.core.cache import CacheKeyWarning

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/stable/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config("SECRET", default="secret")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=False, cast=bool)

INTERNAL_IPS = ["127.0.0.1"]

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*", cast=Csv())

if ALLOWED_HOSTS != ["*"]:
    if "localhost" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append("localhost")
    if "127.0.0.1" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append("127.0.0.1")


CSRF_TRUSTED_ORIGINS = config("CSRF", default="", cast=Csv())

URLS = config("URLS", default="", cast=Csv())

for url in URLS:
    CSRF_TRUSTED_ORIGINS.append(url)
    ALLOWED_HOSTS.append(urlparse(url).hostname)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Application definition

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app",
    "events",
    "integrations",
    "lists",
    "users",
    "debug_toolbar",
    "django_celery_beat",
    "django_celery_results",
    "django_select2",
    "simple_history",
    "widget_tweaks",
    "health_check",
    "health_check.db",
    "health_check.cache",
    "health_check.storage",
    "health_check.contrib.migrations",
    "health_check.contrib.celery_ping",
    "health_check.contrib.redis",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
]

MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.media",
                "app.context_processors.export_vars",
                "django.template.context_processors.request",
            ],
        },
    },
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

WSGI_APPLICATION = "config.wsgi.application"

# Database
# https://docs.djangoproject.com/en/stable/ref/settings/#databases

# create db folder if it doesn't exist
Path(BASE_DIR / "db").mkdir(parents=True, exist_ok=True)

if config("DB_HOST", default=None):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": config("DB_HOST"),
            "NAME": config("DB_NAME"),
            "USER": config("DB_USER"),
            "PASSWORD": config("DB_PASSWORD"),
            "PORT": config("DB_PORT"),
        },
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db" / "db.sqlite3",
        },
    }


# Cache
# https://docs.djangoproject.com/en/stable/topics/cache/
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": 18000,  # 5 hours,
        "VERSION": 6,
    },
}

# not using Memcached, ignore CacheKeyWarning
# https://docs.djangoproject.com/en/stable/topics/cache/#cache-key-warnings
warnings.simplefilter("ignore", CacheKeyWarning)


# Password validation
# https://docs.djangoproject.com/en/stable/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
]

# Logging
# https://docs.djangoproject.com/en/stable/topics/logging/
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {
        "requests_ratelimiter": {
            "level": "DEBUG" if DEBUG else "INFO",
        },
        "psycopg": {
            "level": "DEBUG" if DEBUG else "INFO",
        },
        "urllib3": {
            "level": "DEBUG" if DEBUG else "INFO",
        },
    },
    "formatters": {
        "verbose": {
            # format consistent with gunicorn's
            "format": "[{asctime}] [{process}] [{levelname}] {message}",
            "datefmt": "%Y-%m-%d %H:%M:%S %z",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "level": "DEBUG" if DEBUG else "INFO",
        },
    },
    "root": {"handlers": ["console"], "level": "DEBUG" if DEBUG else "INFO"},
}

# Internationalization
# https://docs.djangoproject.com/en/stable/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = config("TZ", default="UTC")

USE_I18N = True

USE_TZ = True

# Sentinel datetime value for unknown times (11:59:59.999999 AM UTC)
# Falls in the middle of the day in UTC,
# which helps avoid date boundary issues in various timezones
SENTINEL_TIME_HOUR = 11
SENTINEL_TIME_MINUTE = 59
SENTINEL_TIME_SECOND = 59
SENTINEL_TIME_MICROSECOND = 999999

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/stable/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [BASE_DIR / "static"]

# Default primary key field type
# https://docs.djangoproject.com/en/stable/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Auth settings

LOGIN_URL = "account_login"

LOGIN_REDIRECT_URL = "home"

AUTH_USER_MODEL = "users.User"

# Yamtrack settings

TZ = zoneinfo.ZoneInfo(TIME_ZONE)

IMG_NONE = "https://www.themoviedb.org/assets/2/v4/glyphicons/basic/glyphicons-basic-38-picture-grey-c2ebdbb057f2a7614185931650f8cee23fa137b93812ccb132b9df511df1cfac.svg"

REQUEST_TIMEOUT = 120  # seconds

TMDB_API = config("TMDB_API", default="61572be02f0a068658828f6396aacf60")
TMDB_NSFW = config("TMDB_NSFW", default=False, cast=bool)
TMDB_LANG = config("TMDB_LANG", default="en")

MAL_API = config("MAL_API", default="25b5581dafd15b3e7d583bb79e9a1691")
MAL_NSFW = config("MAL_NSFW", default=False, cast=bool)

MU_NSFW = config("MU_NSFW", default=False, cast=bool)

IGDB_ID = config("IGDB_ID", default="8wqmm7x1n2xxtnz94lb8mthadhtgrt")
IGDB_SECRET = config("IGDB_SECRET", default="ovbq0hwscv58hu46yxn50hovt4j8kj")
IGDB_NSFW = config("IGDB_NSFW", default=False, cast=bool)

COMICVINE_API = config(
    "COMICVINE_API",
    default="cdab0706269e4bca03a096fbc39920dadf7e4992",
)

SIMKL_ID = config(
    "SIMKL_ID",
    default="f1df351ddbace7e2c52f0010efdeb1fd59d379d9cdfb88e9a847c68af410db0e",
)
SIMKL_SECRET = config(
    "SIMKL_SECRET",
    default="9bb254894a598894bee14f61eafdcdca47622ab346632f951ed7220a3de289b5",
)

TESTING = False

# Third party settings

DEBUG_TOOLBAR_CONFIG = {
    "SKIP_TEMPLATE_PREFIXES": (
        "django/forms/widgets/",
        "admin/widgets/",
        "app/components/",
    ),
    "ROOT_TAG_EXTRA_ATTRS": "hx-preserve",
}

SELECT2_CACHE_BACKEND = "default"
SELECT2_JS = [
    "https://cdn.jsdelivr.net/npm/jquery@3.5.1/dist/jquery.min.js",
    "https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/js/select2.min.js",
]
SELECT2_I18N_PATH = "js/i18n"
SELECT2_CSS = [
    "https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/css/select2.min.css",
]
SELECT2_THEME = "tailwindcss-4"

# Celery settings

CELERY_BROKER_URL = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE

CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_WORKER_CONCURRENCY = 1
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SYNC_EVERY = 1

CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 60 * 6  # 6 hours

CELERY_RESULT_EXTENDED = True
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "default"
CELERY_RESULT_EXPIRES = 60 * 60 * 24 * 7  # 7 days

# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-serializer
CELERY_TASK_SERIALIZER = "pickle"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std-setting-accept_content
CELERY_ACCEPT_CONTENT = ["application/json", "application/x-python-serialize"]

CELERY_BEAT_SCHEDULE = {
    "reload_calendar": {
        "task": "Reload calendar",
        "schedule": 60 * 60 * 12,  # every 12 hours
    },
    "send-recent-release-notifications": {
        "task": "Send release notifications",
        "schedule": 60 * 30,  # every 30 minutes
    },
}

# Allauth settings
if CSRF_TRUSTED_ORIGINS:
    # Check if all origins start with http:// or https://
    all_http = all(
        origin.startswith("http://") for origin in CSRF_TRUSTED_ORIGINS if origin
    )
    all_https = all(
        origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS if origin
    )

    if all_http:
        ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http"
    elif all_https:
        ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"
    else:
        # Mixed protocols or invalid formats, use config value
        ACCOUNT_DEFAULT_HTTP_PROTOCOL = config(
            "ACCOUNT_DEFAULT_HTTP_PROTOCOL",
            default="https",
        )
else:
    # Empty CSRF_TRUSTED_ORIGINS, default to http
    ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http"

ACCOUNT_LOGOUT_REDIRECT_URL = "/accounts/login/?loggedout=1"
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_USER_MODEL_EMAIL_FIELD = None
ACCOUNT_FORMS = {
    "login": "users.forms.CustomLoginForm",
    "signup": "users.forms.CustomSignupForm",
}
SOCIALACCOUNT_LOGIN_ON_GET = True

SOCIAL_PROVIDERS = config("SOCIAL_PROVIDERS", default="", cast=Csv())
INSTALLED_APPS += SOCIAL_PROVIDERS

SOCIALACCOUNT_PROVIDERS = config(
    "SOCIALACCOUNT_PROVIDERS",
    default="{}",
    cast=json.loads,
)

SOCIALACCOUNT_ONLY = config("SOCIALACCOUNT_ONLY", default=False, cast=bool)
if SOCIALACCOUNT_ONLY:
    ACCOUNT_EMAIL_VERIFICATION = "none"
else:
    # only works if SOCIALACCOUNT_ONLY is False
    INSTALLED_APPS += ["allauth.mfa"]

REGISTRATION = config("REGISTRATION", default=True, cast=bool)
if not REGISTRATION:
    ACCOUNT_ADAPTER = "users.account_adapter.NoNewUsersAccountAdapter"

REDIRECT_LOGIN_TO_SSO = config("REDIRECT_LOGIN_TO_SSO", default=False, cast=bool)
