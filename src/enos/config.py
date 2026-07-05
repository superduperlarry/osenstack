from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENOS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://enos:enos@localhost:5432/enos"
    broker_url: str = "amqp://guest:guest@localhost:5672//"
    result_backend: str = "redis://localhost:6379/0"

    # Provider adapters resolved by name via enos.providers.registry.
    # Never referenced anywhere else in the codebase.
    card_issuer: str = "sandbox"
    banking_partner: str = "sandbox"
    routing_provider: str = "sandbox"

    environment: str = "test"  # token env segment: ok_test_/ac_test_ vs ok_live_/ac_live_
    quote_ttl_minutes: int = 30
    idempotency_window_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
