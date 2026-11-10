"""
Configuration management for KrishiVaani backend.
Safely reads settings from environment variables and .env file.
"""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory of the project (telangana-farmer-whatsapp/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """
    Application settings model.
    Values can be populated from environment variables or a .env file.
    External API credentials are optional at startup so the server can run
    cleanly during testing and local development.
    """
    # Application metadata
    PROJECT_NAME: str = "KrishiVaani"
    VERSION: str = "0.1.0"
    API_PREFIX: str = ""
    DESCRIPTION: str = "Backend API for KrishiVaani: A WhatsApp voice-to-voice agricultural assistant for Indian farmers."
    DEBUG: bool = False

    # Base directory and project paths
    BASE_DIR: Path = BASE_DIR
    DATABASE_PATH: Path = BASE_DIR / "data" / "krishivaani.db"
    USER_ID_HASH_SALT: Optional[str] = None

    # Gnani AI Speech Credentials (Prisma STT & Timbre TTS)
    GNANI_API_KEY: Optional[str] = None

    # Meta WhatsApp Cloud API (Phase 8.1 Integration)
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = None
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: Optional[str] = None
    WHATSAPP_GRAPH_API_VERSION: str = "v27.0"
    WHATSAPP_API_BASE_URL: str = "https://graph.facebook.com"
    WHATSAPP_REQUEST_TIMEOUT_SECONDS: float = 20.0

    # Backward-compatible Meta-prefixed aliases
    META_WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    META_PHONE_NUMBER_ID: Optional[str] = None
    META_APP_SECRET: Optional[str] = None
    META_WEBHOOK_VERIFY_TOKEN: Optional[str] = None
    META_GRAPH_API_VERSION: Optional[str] = None

    @property
    def whatsapp_access_token(self) -> Optional[str]:
        return self.WHATSAPP_ACCESS_TOKEN or self.META_WHATSAPP_ACCESS_TOKEN

    @property
    def whatsapp_phone_number_id(self) -> Optional[str]:
        return self.WHATSAPP_PHONE_NUMBER_ID or self.META_PHONE_NUMBER_ID

    @property
    def whatsapp_app_secret(self) -> Optional[str]:
        return self.WHATSAPP_APP_SECRET or self.META_APP_SECRET

    @property
    def whatsapp_webhook_verify_token(self) -> Optional[str]:
        return self.WHATSAPP_WEBHOOK_VERIFY_TOKEN or self.META_WEBHOOK_VERIFY_TOKEN

    @property
    def whatsapp_graph_api_version(self) -> str:
        return self.WHATSAPP_GRAPH_API_VERSION or self.META_GRAPH_API_VERSION or "v27.0"

    # Twilio WhatsApp Sandbox Integration (Phase 8.2)
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_WHATSAPP_FROM: Optional[str] = None
    TWILIO_WEBHOOK_PUBLIC_BASE_URL: Optional[str] = None
    TWILIO_ENABLED: bool = False
    TWILIO_REQUEST_TIMEOUT_SECONDS: float = 20.0
    TWILIO_MEDIA_DIR: Path = BASE_DIR / "data" / "twilio_media"

    @property
    def twilio_account_sid(self) -> Optional[str]:
        return self.TWILIO_ACCOUNT_SID

    @property
    def twilio_auth_token(self) -> Optional[str]:
        return self.TWILIO_AUTH_TOKEN

    @property
    def twilio_whatsapp_from(self) -> str:
        return self.TWILIO_WHATSAPP_FROM or "whatsapp:+14155238886"

    @property
    def twilio_webhook_public_base_url(self) -> Optional[str]:
        return self.TWILIO_WEBHOOK_PUBLIC_BASE_URL

    @property
    def twilio_enabled(self) -> bool:
        return self.TWILIO_ENABLED

    @property
    def twilio_media_dir(self) -> Path:
        return self.TWILIO_MEDIA_DIR

    @property
    def base_dir(self) -> Path:
        return self.BASE_DIR

    # Telegram Channel Integration (Phase 8.3)
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    @property
    def telegram_bot_token(self) -> Optional[str]:
        return self.TELEGRAM_BOT_TOKEN

    # Weather Services (Phase 6.1 Integration)
    WEATHERAPI_API_KEY: Optional[str] = None
    WEATHERAPI_BASE_URL: str = "https://api.weatherapi.com/v1"
    WEATHER_REQUEST_TIMEOUT_SECONDS: float = 10.0
    IMD_API_KEY: Optional[str] = None
    IMD_JWT_TOKEN: Optional[str] = None

    # LLM Reasoning Services (Phase 7.2 Groq Integration)
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL_ID: str = "openai/gpt-oss-120b"
    GROQ_REQUEST_TIMEOUT_SECONDS: float = 15.0
    GROQ_MAX_TOKENS: int = 1200
    GROQ_TEMPERATURE: float = 0.1
    GROQ_REASONING_EFFORT: str = "low"
    LLM_PROVIDER: str = "sarvam"
    SARVAM_API_KEY: Optional[str] = None
    SARVAM_MODEL: str = "sarvam-105b-conversations"
    SARVAM_MAX_TOKENS: int = 900
    SARVAM_LENGTH_RETRY_MULTIPLIER: float = 1.5

    # Only voices confirmed in the checked-in configuration are enabled.
    TTS_VOICE_MAP: dict[str, str] = {"te-IN": "Kaveri"}

    # PJTAU Agromet Advisories (Phase 6.3 Integration)
    PJTAU_ARCHIVE_URL: str = "https://pjtau.edu.in/agromet-advisories/"
    PJTAU_DATA_DIR: Path = BASE_DIR / "data" / "pjtau"
    PJTAU_MAX_PDF_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB
    PJTAU_REQUEST_TIMEOUT_SECONDS: float = 20.0

    # TGDPS Weather Reports (Phase 6.4 Integration)
    TGDPS_PORTAL_URL: str = "https://tgdps.telangana.gov.in/"
    TGDPS_DATA_DIR: Path = BASE_DIR / "data" / "tgdps"
    TGDPS_MAX_PDF_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB
    TGDPS_REQUEST_TIMEOUT_SECONDS: float = 20.0

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
