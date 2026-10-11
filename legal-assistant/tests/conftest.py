from pytest import fixture

from settings import get_settings


@fixture(autouse=True)
def clear_cache() -> None:
    get_settings.cache_clear()
