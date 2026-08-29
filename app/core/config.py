from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RAG_",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "Production RAG Knowledge Platform"
    app_version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: PostgresDsn
    database_connect_timeout_seconds: Annotated[int, Field(ge=1, le=30)] = 5
    jwt_secret: Annotated[SecretStr, Field(min_length=32)]
    access_token_expire_minutes: Annotated[int, Field(ge=1, le=60)] = 15
    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: Annotated[int, Field(ge=1, le=100 * 1024 * 1024)] = 10 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings.model_validate({})
