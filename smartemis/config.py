from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Runtime
    env: Literal["local", "draft", "staging", "production"] = Field("local", alias="SMARTEMIS_ENV")
    log_level: str = Field("INFO", alias="SMARTEMIS_LOG_LEVEL")

    # Data source
    source: Literal["csv", "qlik"] = Field("csv", alias="SMARTEMIS_SOURCE")
    csv_path: Path = Field(
        Path("./synthetic_data/out/smartemis_lineitems.csv"), alias="SMARTEMIS_CSV_PATH"
    )

    # Database
    db_url: str = Field("sqlite:///./smartemis.db", alias="SMARTEMIS_DB_URL")

    # Bedrock / LLM
    aws_region: str = Field("eu-central-1", alias="AWS_REGION")
    bedrock_model_id: str = Field(
        "eu.anthropic.claude-sonnet-4-6", alias="SMARTEMIS_BEDROCK_MODEL_ID"
    )

    # Pseudonymization
    pseudo_salt: str = Field("change-me-locally", alias="SMARTEMIS_PSEUDO_SALT")

    # Qlik (placeholder)
    qlik_base_url: str | None = Field(None, alias="QLIK_BASE_URL")
    qlik_api_key: str | None = Field(None, alias="QLIK_API_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
