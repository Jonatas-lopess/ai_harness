from pathlib import Path

from pydantic import ValidationError
from pytest import MonkeyPatch, raises

from settings import get_settings


def test_env_steps_invalid(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_STEPS", "abc")

    with raises(ValidationError):
        _ = get_settings()

def test_env_url_missing(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with raises(ValidationError):
        _ = get_settings()

def test_env_url_empty(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")

    with raises(ValidationError):
        _ = get_settings()

def test_env_url_valid(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://")

    settings = get_settings()
    assert settings.database_url.get_secret_value() == "postgresql://"
