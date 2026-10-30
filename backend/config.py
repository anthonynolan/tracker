"""Backend configuration. Secrets load from `.env`; never log them."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    model_api_key: SecretStr = Field(alias="MODEL_API_KEY")
    storage_backend: Literal["filesystem", "mongodb"] = "filesystem"
    # Full MongoDB URL override. When unset, built from MONGODB_* parts
    # (Atlas SRV when a host is set, else localhost).
    mongo_url: str | None = None
    mongo_database: str = "tracker"
    mongodb_user: str | None = Field(default=None, alias="MONGODB_USER")
    mongodb_password: SecretStr | None = Field(default=None,
                                               alias="MONGODB_PASSWORD")
    mongodb_host: str | None = Field(default=None, alias="MONGODB_HOST")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # populated from environment
