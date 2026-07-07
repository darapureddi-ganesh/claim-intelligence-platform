"""ClaimIQ application settings (loaded from environment)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://claimiq:claimiq_dev@localhost:5432/claimiq"
    database_sync_url: str = "postgresql+psycopg2://claimiq:claimiq_dev@localhost:5432/claimiq"
    redis_url: str = "redis://localhost:6379/0"
    policylens_url: str = "http://localhost:8001"
    secret_key: str = "dev-secret-key"
    log_level: str = "INFO"

    # Routing thresholds
    senior_adjuster_threshold: float = 0.65
    fraud_unit_threshold: float = 0.60
    fast_track_threshold: float = 0.25

    # Reserve suggestion multipliers (applied to claimed amount)
    reserve_multiplier_low: float = 0.70
    reserve_multiplier_medium: float = 0.85
    reserve_multiplier_high: float = 1.10

    class Config:
        env_file = ".env"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
