from pathlib import Path
from typing import Optional, List, Union
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def mask_token(token: Optional[str]) -> str:
    """Safely masks sensitive tokens for logging and debug output."""
    if not token:
        return "<none>"
    t = str(token).strip()
    if len(t) <= 8:
        return "***"
    return f"{t[:4]}...{t[-4:]}"


class Settings(BaseSettings):
    PROJECT_NAME: str = "TradeZen"
    PROJECT_ROOT: Path = PROJECT_ROOT
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # PostgreSQL Database URL
    DATABASE_URL: str = Field(
        ...,
        validation_alias=AliasChoices("DATABASE_URL", "database_url")
    )
    DATA_DIR: str = "Data"
    DEFAULT_USER_ID: int = 1

    # Security & Tokens
    JWT_SECRET: str = Field(
        default="tradezen_secret_jwt_key_secure_2026",
        validation_alias=AliasChoices("JWT_SECRET", "jwt_secret")
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Upstox Analytics / Live Mode Tokens
    UPSTOX_ACCESS_TOKEN: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("UPSTOX_ACCESS_TOKEN", "UPSTOX_ANALYTICS_TOKEN", "upstox_access_token")
    )
    UPSTOX_ANALYTICS_TOKEN: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("UPSTOX_ANALYTICS_TOKEN", "UPSTOX_ACCESS_TOKEN")
    )
    UPSTOX_API_VERSION: str = "3.0"

    # API & Network
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    API_BASE_URL: str = "/api/v1"
    ALLOWED_ORIGINS: Union[str, List[str]] = ["*"]

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def data_path(self) -> Path:
        p = Path(self.DATA_DIR)
        if not p.is_absolute():
            root = PROJECT_ROOT
            candidate_orig = root / p
            if candidate_orig.exists():
                return candidate_orig
            candidate_lower = root / self.DATA_DIR.lower()
            if candidate_lower.exists():
                return candidate_lower
            return candidate_orig
        return p


settings = Settings()
