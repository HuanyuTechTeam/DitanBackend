"""环境配置模块"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类"""

    # 数据库配置
    DATABASE_HOST: str
    DATABASE_PORT: int = 5432
    DATABASE_USER: str
    DATABASE_PASSWORD: str
    DATABASE_NAME: str

    # 应用配置
    APP_NAME: str = "DitanBackend"
    APP_VERSION: str = "3.0.0"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_DEBUG: bool = False

    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"

    # AI模型配置
    AI_API_KEY: str
    AI_BASE_URL: str
    AI_MODEL_NAME: str = "deepseek-chat"

    # JWT认证配置
    JWT_SECRET_KEY: str = "your-secret-key-change-this-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Apkio 统一认证配置
    APKIO_AUTH_ENABLED: bool = False
    APKIO_JWT_SECRET_KEY: Optional[str] = None
    APKIO_JWT_ALGORITHM: str = "HS256"
    APKIO_ORG_TOKEN_AUDIENCE: str = "org"
    APKIO_REQUIRED_PERMISSION: str = "ditan.access"
    APKIO_AUTO_CREATE_DOCTOR: bool = True

    MEDICAL_UPLOAD_AUTH_REQUIRED: bool = True
    APKIO_BASE_URL: str = ""
    APKIO_ALLOW_LOOPBACK_HTTP: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """生成数据库连接 URL"""
        return (
            f"postgresql+asyncpg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()  # type: ignore[call-arg]
