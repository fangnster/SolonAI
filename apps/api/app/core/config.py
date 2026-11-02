from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # 项目信息
    PROJECT_NAME: str = "Solon AI API"
    VERSION: str = "0.1.0"

    # API配置
    API_V1_PREFIX: str = "/api/v1"

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://*.vercel.app",
    ]

    # 数据库配置（使用 SQLite 本地测试）
    DATABASE_URL: str = "sqlite+aiosqlite:///./solon_ai.db"
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379"
    CACHE_TTL_ASSETS: int = 60
    REPORT_READ_TIMEOUT_SECONDS: float = 20.0
    CACHE_TTL_CHAT_SESSIONS: int = 120
    CACHE_TTL_CHAT_MESSAGES: int = 120
    CACHE_TTL_STRATEGY: int = 300
    CACHE_TTL_RISK: int = 180
    DEFI_REFRESH_INTERVAL_SECONDS: int = 120

    # JWT配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Solana配置
    SOLANA_RPC_URL: str = "https://api.devnet.solana.com"
    ALCHEMY_API_KEY: str = ""

    # AI模型配置
    DOUBAO_API_KEY: str = ""
    DOUBAO_API_URL: str = "https://api.minimaxi.com/v1"
    PINECONE_API_KEY: str = ""
    PINECONE_ENVIRONMENT: str = ""

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        # Keep `.env` developer-friendly while ensuring async SQLAlchemy uses the
        # installed driver.
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value


settings = Settings()
