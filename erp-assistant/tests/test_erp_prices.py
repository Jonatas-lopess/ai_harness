from decimal import Decimal

from erp_prices import PRICES_PATH, load_erp_prices


def test_the_prices_file_sits_next_to_the_pack_and_has_the_groq_model() -> None:
    table = load_erp_prices()

    assert PRICES_PATH.is_file()
    assert table.currency == "USD"
    assert table.models["openai/gpt-oss-120b"].input_per_mtok == Decimal("0.15")


def test_each_call_reads_the_file_again() -> None:
    first = load_erp_prices()

    assert load_erp_prices() is not first
