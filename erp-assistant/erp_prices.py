"""Preços do ERP: o arquivo é do pack, o mecanismo de custo é do harness (`harness.pricing`)."""

from pathlib import Path

from harness.pricing import PriceTable, load_prices

PRICES_PATH = Path(__file__).parent / "prices.json"


def load_erp_prices() -> PriceTable:
    """Lê o arquivo a cada chamada, de propósito: o job carrega uma vez por execução e um processo
    longo pega o preço novo na execução seguinte (um cache global seguiria cobrando o antigo)."""
    return load_prices(PRICES_PATH)
