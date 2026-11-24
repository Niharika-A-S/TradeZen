import logging
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Base chatbot package directory
PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_KNOWLEDGE_DIR = PACKAGE_DIR / "knowledge"
BACKEND_DIR = PACKAGE_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent
DEFAULT_SQLITE_PATH = BACKEND_DIR / "chatbot.db"


class ChatbotConfig(BaseSettings):
    """Chatbot module configuration."""
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_CHAT_MODEL: str = "gemini-3.8-flash"
    GEMINI_EMBED_MODEL: str = "gemini-embedding-001"
    EMBED_DIMENSIONS: int = 768
    RAG_TOP_K: int = 4
    RAG_MIN_SIMILARITY: float = 0.55
    LLM_TIMEOUT_SECONDS: int = 20
    LLM_TIMEOUT_PERSONALISED_SECONDS: int = 30
    LLM_THINKING_BUDGET: int = 0
    CHAT_GENERAL_ANSWERS: bool = True
    CHAT_RATE_LIMIT_PER_MIN: int = 20
    CHAT_MAX_MESSAGE_CHARS: int = 1000
    HELPLINE_NUMBER: str = "14416"
    DATABASE_URL: Optional[str] = None

    # Coach Personalisation Settings & Thresholds
    COACH_TRADE_WINDOW_N: int = 20
    COACH_MIN_SAMPLE_SIZE: int = 5
    COACH_STATEMENT_TIMEOUT_MS: int = 3000
    COACH_LOCK_TIMEOUT_SECONDS: float = 4.0
    COACH_SIZE_FACTOR_THRESHOLD: float = 1.3
    COACH_LOSS_FACTOR_THRESHOLD: float = 1.2
    COACH_HOLD_FACTOR_THRESHOLD: float = 1.3
    COACH_QUICK_REENTRY_MINS: int = 15
    SCENARIO_SOURCE_CONNECTED: bool = True

    model_config = SettingsConfigDict(
        env_file=(
            PROJECT_DIR / ".env",
            BACKEND_DIR / ".env",
            Path(".env")
        ),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def knowledge_dir(self) -> Path:
        """Returns the absolute Path to the knowledge files directory."""
        return DEFAULT_KNOWLEDGE_DIR

    @property
    def has_gemini_key(self) -> bool:
        """Exposes whether GEMINI_API_KEY is present and not empty."""
        return bool(self.GEMINI_API_KEY and self.GEMINI_API_KEY.strip())

    @property
    def effective_database_url(self) -> str:
        """Returns PostgreSQL connection string or falls back to local SQLite."""
        try:
            from app.config import settings
            if getattr(settings, "DATABASE_URL", None):
                url = settings.DATABASE_URL.strip()
                if url.startswith("postgresql://"):
                    url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
                return url
        except Exception:
            pass

        if self.DATABASE_URL and self.DATABASE_URL.strip():
            url = self.DATABASE_URL.strip()
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
        # SQLite fallback default for Layout 2 testing/dev_app
        return f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


def get_chatbot_config() -> ChatbotConfig:
    """Safe getter falling back to defaults with warnings on invalid values."""
    try:
        return ChatbotConfig()
    except Exception as exc:
        logger.warning("Error loading chatbot configuration from environment: %s. Using default settings.", exc)
        return ChatbotConfig(_env_file=None)


cfg = get_chatbot_config()
