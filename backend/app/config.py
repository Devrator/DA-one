"""Application configuration with Pydantic settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="QueryPilot AI")
    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = Field(default="change-me-to-a-random-secret-key")
    app_debug: bool = True
    app_log_level: str = "INFO"
    app_cors_origins: str = "http://localhost:5173"

    # Application Database
    app_database_url: str = Field(
        default="postgresql+psycopg://querypilot:querypilot_dev@localhost:5433/querypilot_app"
    )

    # Default Target Database
    target_db_host: str = "localhost"
    target_db_port: int = 5433
    target_db_name: str = "querypilot_target"
    target_db_user: str = "target_readonly"
    target_db_password: str = "target_readonly_dev"

    # LLM / Inference
    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5-coder:7b"
    llm_base_url: str = "http://localhost:11434"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048
    llm_request_timeout: int = 120

    # Query Safety
    sql_max_rows: int = 1000
    sql_statement_timeout_ms: int = 30000
    sql_max_query_length: int = 4096

    # Auth
    auth_enabled: bool = False
    auth_default_user: str = "demo"
    auth_jwt_secret: str = "change-me-jwt-secret"
    auth_jwt_expiry_hours: int = 24

    # Proactive Discovery (Phase 2: Discover & Early Warnings)
    discovery_enabled: bool = True
    discovery_schedule_enabled: bool = True
    discovery_interval_minutes: int = 60
    discovery_initial_delay_seconds: int = 20
    discovery_run_role: str = "executive"
    discovery_min_periods: int = 3
    discovery_mom_threshold_pct: float = 18.0
    discovery_anomaly_z_threshold: float = 1.8
    discovery_concentration_threshold_pct: float = 40.0
    discovery_underperform_z_threshold: float = 1.0
    discovery_top_n_dimensions: int = 5

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",") if o.strip()]

    @property
    def target_db_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.target_db_user}:{self.target_db_password}"
            f"@{self.target_db_host}:{self.target_db_port}/{self.target_db_name}"
        )

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
