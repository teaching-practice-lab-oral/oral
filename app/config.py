from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
from urllib.parse import urlparse


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    # Database
    DATABASE_URL: str = ""

    # JWT
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 8
    ADMIN_TOKEN_EXPIRE_HOURS: int = 24
    # Throttle the per-request active-session write: only refresh last_seen_at/
    # expires_at once per this many seconds, avoiding a commit+fsync every request.
    SESSION_TOUCH_SECONDS: int = 60
    STUDENT_ONLINE_LIMIT: int = 200
    STUDENT_PRESENCE_TTL_SECONDS: int = 300

    # Database pool. Keep the total across all gunicorn workers below Postgres
    # max_connections (100 in docker-compose*.yml by default).
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 10
    DB_POOL_RECYCLE: int = 1800
    # Advisory-lock connections use a separate small pool so long AI/audio
    # operations cannot consume the ordinary ORM pool while waiting for a lock.
    OPERATION_LOCK_POOL_SIZE: int = 2
    OPERATION_LOCK_POOL_TIMEOUT: int = 1

    # OpenAI
    OPENAI_API_KEY: str = ""

    # Azure Speech

    # Oracle Object Storage
    OCI_ENDPOINT_URL: str = ""
    OCI_ACCESS_KEY_ID: str = ""
    OCI_SECRET_ACCESS_KEY: str = ""
    OCI_BUCKET_NAME: str = ""
    OCI_REGION: str = ""
    OBJECT_STORAGE_NAMESPACE: str = ""
    RESULT_PACKAGE_EXPIRE_DAYS: int = 14
    RESULT_DOWNLOAD_REDIRECT_SECONDS: int = 300

    # Email
    MAIL_USER: str = ""
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = ""
    MAIL_FROM_NAME: str = ""
    MAIL_REPLY_TO: str = ""
    MAIL_REPLY_TO_NAME: str = ""
    PASSWORD_RESET_ADMIN_EMAIL: str = ""
    MAIL_SIGNATURE_HTML: str = ""
    REMINDER_EXCLUDED_EMAILS: str = ""
    MAIL_HOST: str = ""
    MAIL_SERVER: str = ""
    MAIL_PORT: int = 587
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False

    # App
    APP_ENV: str = "development"
    PUBLIC_BASE_URL: str = ""
    CORS_ORIGINS: str = ""
    TRUSTED_HOSTS: str = ""
    TRUSTED_PROXY_IPS: str = "127.0.0.1,::1"
    # Must be slightly above the largest accepted 50 MiB audio file to allow
    # for multipart framing, while still protecting form parsing globally.
    MAX_REQUEST_BODY_BYTES: int = 56 * 1024 * 1024

    # Cloudflare Turnstile
    TURNSTILE_SECRET_KEY: str = ""
    TURNSTILE_SITE_KEY: str = ""

    # OpenAI model names
    OPENAI_CHAT_MODEL: str = "gpt-5.4-mini"
    OPENAI_WHISPER_MODEL: str = "whisper-1"
    OPENAI_TTS_MODEL: str = "gpt-4o-mini-tts"

    # Protected master admin account (cannot be deleted, deactivated, or demoted)
    PROTECTED_ADMIN_STUDENT_ID: str = ""

    # Rate limiting
    STAGE_HOURLY_LIMIT: int = 20
    DAILY_API_LIMIT: int = 50
    MAX_AUDIO_SECONDS: int = 300
    STAGE3_MAX_RESPONSE_CHARS: int = 15000
    AUDIO_UPLOAD_WINDOW_MINUTES: int = 15
    AUDIO_UPLOAD_WINDOW_LIMIT: int = 30
    PHOTO_UPLOAD_HOURLY_LIMIT: int = 10
    PHOTO_UPLOAD_DAILY_BYTES: int = 50 * 1024 * 1024
    STUDENT_EXPORT_RESOURCE_WINDOW_MINUTES: int = 10
    STUDENT_EXPORT_RESOURCE_WINDOW_LIMIT: int = 3
    STUDENT_EXPORT_HOURLY_LIMIT: int = 10
    STUDENT_EXPORT_MAX_CONCURRENCY: int = 2
    COSTLY_ACTION_RETENTION_DAYS: int = 2

    # External-API concurrency
    OPENAI_MAX_CONCURRENCY: int = 15
    TTS_MAX_CONCURRENCY: int = 10
    AUDIO_PROCESSING_MAX_CONCURRENCY: int = 20

    # Login throttling (per source IP, independent of per-account lockout)
    LOGIN_IP_WINDOW_MINUTES: int = 15
    LOGIN_IP_MAX_FAILURES: int = 30
    PASSWORD_RESET_EXPIRE_HOURS: int = 72
    PASSWORD_RESET_USER_DAILY_LIMIT: int = 3
    PASSWORD_RESET_IP_HOURLY_LIMIT: int = 10

    # Retention policy for operational/audit logs. Set a value <= 0 to disable
    # pruning for that table.
    LOGIN_EVENT_RETENTION_DAYS: int = 180
    ADMIN_AUDIT_RETENTION_DAYS: int = 365
    API_USAGE_RETENTION_DAYS: int = 90
    PROCTOR_EVENT_RETENTION_DAYS: int = 365
    MAINTENANCE_CLEANUP_INTERVAL_SECONDS: int = 86400

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def trusted_proxy_ips_list(self) -> List[str]:
        return [o.strip() for o in self.TRUSTED_PROXY_IPS.split(",") if o.strip()]

    @property
    def trusted_hosts_list(self) -> List[str]:
        configured = [host.strip() for host in self.TRUSTED_HOSTS.split(",") if host.strip()]
        hosts = list(dict.fromkeys(configured))
        if not hosts:
            # CORS origins describe which browser origins may call the API; they
            # are not an authorization list for HTTP Host headers.  Only fall
            # back to the application's own public hostname.
            public_hostname = urlparse(self.PUBLIC_BASE_URL).hostname
            if public_hostname:
                hosts.append(public_hostname)
        if self.APP_ENV != "production":
            hosts.extend(host for host in ("localhost", "127.0.0.1", "testserver") if host not in hosts)
        return hosts

    @property
    def reminder_excluded_emails_set(self) -> set[str]:
        return {
            address.strip().casefold()
            for address in self.REMINDER_EXCLUDED_EMAILS.split(",")
            if address.strip()
        }

    @model_validator(mode="after")
    def validate_production_settings(self):
        if self.ALGORITHM != "HS256":
            raise ValueError("ALGORITHM must be HS256")
        placeholder_markers = ("your-secret", "change-me", "changeme", "replace-with")
        stripped_secret = self.SECRET_KEY.strip()
        normalized_secret = stripped_secret.casefold()
        if len(stripped_secret) < 32 or any(marker in normalized_secret for marker in placeholder_markers):
            raise ValueError(
                "SECRET_KEY must be an explicit random value of at least 32 characters"
            )
        if self.APP_ENV == "production":
            required = (
                "DATABASE_URL",
                "SECRET_KEY",
                "TURNSTILE_SECRET_KEY",
                "TURNSTILE_SITE_KEY",
                "PUBLIC_BASE_URL",
                "OBJECT_STORAGE_NAMESPACE",
            )
            missing = [name for name in required if not str(getattr(self, name, "")).strip()]
            if missing:
                raise ValueError(f"Missing required production settings: {', '.join(missing)}")
            public_base_url = self.PUBLIC_BASE_URL.strip()
            parsed_public_url = urlparse(public_base_url)
            try:
                parsed_port = parsed_public_url.port
            except ValueError as exc:
                raise ValueError("PUBLIC_BASE_URL must be a valid HTTPS origin") from exc
            if (
                parsed_public_url.scheme != "https"
                or not parsed_public_url.hostname
                or parsed_public_url.username is not None
                or parsed_public_url.password is not None
                or parsed_public_url.params
                or parsed_public_url.query
                or parsed_public_url.fragment
                or parsed_public_url.path not in ("", "/")
                or (parsed_port is not None and not 1 <= parsed_port <= 65535)
            ):
                raise ValueError("PUBLIC_BASE_URL must be a valid HTTPS origin")
            if "*" in self.cors_origins_list:
                raise ValueError("CORS_ORIGINS must not contain '*' in production")
            if "*" in self.trusted_proxy_ips_list:
                raise ValueError("TRUSTED_PROXY_IPS must not contain '*' in production")
            if not self.trusted_hosts_list or "*" in self.trusted_hosts_list:
                raise ValueError("TRUSTED_HOSTS must list explicit production host names")
        namespace = self.OBJECT_STORAGE_NAMESPACE.strip()
        if namespace and (
            len(namespace) < 8
            or len(namespace) > 64
            or not all(
                character.isascii() and (character.isalnum() or character in "._-")
                for character in namespace
            )
        ):
            raise ValueError(
                "OBJECT_STORAGE_NAMESPACE must be 8-64 letters, numbers, dots, underscores, or hyphens"
            )
        if self.RESULT_PACKAGE_EXPIRE_DAYS < 1:
            raise ValueError("RESULT_PACKAGE_EXPIRE_DAYS must be positive")
        if not 60 <= self.RESULT_DOWNLOAD_REDIRECT_SECONDS <= 900:
            raise ValueError("RESULT_DOWNLOAD_REDIRECT_SECONDS must be between 60 and 900")
        if self.MAX_REQUEST_BODY_BYTES < 1024 * 1024:
            raise ValueError("MAX_REQUEST_BODY_BYTES must be at least 1 MiB")
        if self.MAX_AUDIO_SECONDS < 1:
            raise ValueError("MAX_AUDIO_SECONDS must be positive")
        positive_cost_limits = (
            self.AUDIO_UPLOAD_WINDOW_MINUTES,
            self.AUDIO_UPLOAD_WINDOW_LIMIT,
            self.PHOTO_UPLOAD_HOURLY_LIMIT,
            self.PHOTO_UPLOAD_DAILY_BYTES,
            self.STUDENT_EXPORT_RESOURCE_WINDOW_MINUTES,
            self.STUDENT_EXPORT_RESOURCE_WINDOW_LIMIT,
            self.STUDENT_EXPORT_HOURLY_LIMIT,
            self.STUDENT_EXPORT_MAX_CONCURRENCY,
            self.COSTLY_ACTION_RETENTION_DAYS,
        )
        if any(value < 1 for value in positive_cost_limits):
            raise ValueError("costly-action limits must be positive")
        if self.OPERATION_LOCK_POOL_SIZE < 1 or self.OPERATION_LOCK_POOL_TIMEOUT < 1:
            raise ValueError("operation lock pool settings must be positive")
        return self


settings = Settings()
