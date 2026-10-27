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

    # Personalized Executive Briefings (Feature 4)
    briefings_enabled: bool = True
    briefing_schedule_enabled: bool = False        # off by default; enable for real cadence
    briefing_interval_minutes: int = 1440          # daily cadence default
    briefing_initial_delay_seconds: int = 30
    briefing_max_items: int = 8                     # top-N ranked findings per briefing
    briefing_stale_after_hours: int = 48            # suppress findings older than this as stale
    briefing_low_value_score: float = 5.0           # rank-score floor for 'low-value' suppression

    # Cross-System Intelligence (Feature 5)
    cross_source_enabled: bool = True
    cross_source_max_rows_per_source: int = 2000     # hard bound per source before app-side join
    cross_source_statement_timeout_ms: int = 15000   # per-source read timeout
    cross_source_max_joined_rows: int = 1000         # bound on returned joined rows
    # Bootstrap secondary source so the two-source demo works out of the box.
    # Admins can also register additional sources via the Connections registry.
    cross_source_secondary_enabled: bool = True
    cross_source_secondary_name: str = "Inventory (Warehouse Stock)"
    cross_source_secondary_host: str = "localhost"
    cross_source_secondary_port: int = 5433
    cross_source_secondary_db: str = "querypilot_inventory"
    cross_source_secondary_user: str = "inventory_readonly"
    cross_source_secondary_password: str = "inventory_readonly_dev"
    cross_source_secondary_schema: str = "inventory"

    # Credential encryption at rest (Feature: SAP connector + Connection registry)
    # A Fernet key (urlsafe base64, 32 bytes). If empty it is DERIVED from
    # app_secret_key so development works out of the box; production should set
    # CREDENTIAL_ENCRYPTION_KEY explicitly and keep the key OUTSIDE the database.
    credential_encryption_key: str = Field(default="")
    # Comma-separated older Fernet keys kept only for decrypt during rotation.
    credential_encryption_key_previous: str = Field(default="")

    # SAP S/4HANA connector (read-only OData analytics)
    sap_enabled: bool = True
    sap_default_timeout_seconds: float = 20.0
    sap_max_timeout_seconds: float = 120.0
    sap_max_records_fetched: int = 5000        # absolute cap for a single fetch
    sap_default_page_size: int = 500           # bounded $top per round-trip
    sap_max_response_bytes: int = 8_000_000    # per-response size limit
    sap_max_retries: int = 3
    sap_backoff_base_seconds: float = 0.5
    sap_backoff_max_seconds: float = 20.0
    sap_metadata_cache_seconds: int = 900
    # Administrator-approved SAP hosts (comma-separated exact hostnames or
    # *.suffix wildcards). Empty means only loopback test hosts are allowed and
    # every external host must be explicitly approved (fail-closed SSRF guard).
    sap_allowed_hosts: str = Field(default="")

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
