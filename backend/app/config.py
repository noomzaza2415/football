"""Application settings, loaded from environment variables only.

No credential or API key is ever written into the source tree. Copy
``.env.example`` to ``.env`` and fill it in locally; in production the same
names are supplied by the deployment environment.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- application -------------------------------------------------------
    app_name: str = "Football Over/Under Analytics"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # --- database ----------------------------------------------------------
    # Example: postgresql+psycopg://ou_user:secret@localhost:5432/football_ou
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/football_ou"
    )
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_connect_timeout_seconds: int = 5

    # --- external data providers ------------------------------------------
    # "football-data" uses football-data.org, "api-football" uses API-Football
    # on RapidAPI. Only the key for the selected provider needs to be set.
    data_provider: Literal["football-data", "api-football", "football-data-uk"] = (
        "football-data-uk"
    )
    football_data_api_key: str | None = None
    football_data_base_url: str = "https://api.football-data.org/v4"
    api_football_api_key: str | None = None
    api_football_base_url: str = "https://v3.football.api-sports.io"
    # Public CSV archive; no account or key of any kind.
    football_data_uk_base_url: str = "https://www.football-data.co.uk"

    # Competition codes to ingest, comma separated in the environment.
    # football-data.org uses codes like PL, BL1, SA, PD, FL1.
    competitions: str = "E0"
    seasons_back: int = 2
    request_timeout_seconds: float = 20.0
    rate_limit_sleep_seconds: float = 6.0

    # --- model -------------------------------------------------------------
    model_last_n_matches: int = 20
    model_max_goals: int = 6
    # Dixon-Coles rho. 0.0 disables the low-score correction; -0.05 to -0.15
    # is the usual fitted range for European league football.
    model_rho: float = -0.05
    model_lines: str = "1.5,2.5,3.5"
    # Pull team strengths toward league average when the evidence is thin.
    # "auto" derives the constant from the data, "off" uses the raw ratios, a
    # number sets the constant directly in matches.
    model_shrinkage: str = "auto"

    # --- google sheets -----------------------------------------------------
    # A service account JSON key file, and the long id from the sheet's URL.
    # The sheet must be shared with the service account's email as Editor.
    # Route A, Apps Script: no Google Cloud project needed. A script bound to
    # the sheet is deployed as a web app and this machine pushes to it.
    google_apps_script_url: str | None = None
    google_apps_script_token: str | None = None

    # Route B, service account: needs a Google Cloud project and a key file.
    google_service_account_file: str | None = None
    google_sheet_id: str | None = None

    # --- news --------------------------------------------------------------
    # Headlines are shown as reading context and never reach the model.
    news_enabled: bool = True
    news_cache_seconds: int = 300

    # --- api ---------------------------------------------------------------
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:3000"

    @field_validator("database_url")
    @classmethod
    def _require_supported_driver(cls, value: str) -> str:
        if not value.startswith(("postgresql+psycopg://", "postgresql://", "sqlite://")):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL (sqlite is allowed for tests)"
            )
        return value

    @property
    def competition_list(self) -> list[str]:
        return [code.strip() for code in self.competitions.split(",") if code.strip()]

    @property
    def line_list(self) -> list[float]:
        return [float(line) for line in self.model_lines.split(",") if line.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def shrinkage(self) -> float | str | None:
        """Parsed MODEL_SHRINKAGE, in the form compute_team_strengths expects."""
        value = self.model_shrinkage.strip().lower()
        if value in {"off", "none", ""}:
            return None
        if value == "auto":
            return "auto"
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(
                f"MODEL_SHRINKAGE must be 'auto', 'off' or a number, got {self.model_shrinkage!r}"
            ) from exc

    @property
    def requires_api_key(self) -> bool:
        return self.data_provider != "football-data-uk"

    @property
    def active_provider_key(self) -> str | None:
        if self.data_provider == "football-data":
            return self.football_data_api_key
        if self.data_provider == "api-football":
            return self.api_football_api_key
        return None


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Use this everywhere instead of re-reading env."""
    return Settings()
