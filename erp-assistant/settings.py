from functools import lru_cache
from typing import ClassVar

from pydantic import field_validator
from pydantic.types import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    debug: bool = False
    max_steps: int = 10

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value() == "":
            raise ValueError("database_url must not be empty")
        return value

@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
