from pathlib import Path

from pydantic import ValidationError
from pytest import MonkeyPatch, fixture, raises

from settings import get_settings


@fixture(autouse=True)
def clean_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Ambiente conhecido: sem `.env` (o cwd é vazio) e só as variáveis obrigatórias, válidas.

    Sem isso o teste passa ou falha conforme o `.env` da máquina (no CI não existe).
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")


def test_env_steps_invalid(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_STEPS", "abc")

    with raises(ValidationError, match="max_steps"):
        _ = get_settings()


def test_env_url_missing(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")

    with raises(ValidationError, match="database_url"):
        _ = get_settings()


def test_env_url_empty(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")

    with raises(ValidationError, match="database_url"):
        _ = get_settings()


def test_env_url_valid() -> None:
    settings = get_settings()
    assert settings.database_url.get_secret_value() == "postgresql://"


def test_env_groq_key_missing(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY")

    with raises(ValidationError, match="groq_api_key"):
        _ = get_settings()


def test_env_groq_key_wrong_prefix(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "sk-wrong")

    with raises(ValidationError, match="gsk_"):
        _ = get_settings()
