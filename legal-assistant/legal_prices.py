"""Preços do Legal: o arquivo é do pack, o mecanismo de custo é do harness (`harness.pricing`)."""

from pathlib import Path

from harness.pricing import PriceTable, load_prices

PRICES_PATH = Path(__file__).parent / "prices.json"


def load_legal_prices() -> PriceTable:
    """Lê o arquivo a cada execução do job (sem cache global): um processo longo pega o preço novo na seguinte."""
    return load_prices(PRICES_PATH)
