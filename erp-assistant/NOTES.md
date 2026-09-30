# Fase 0: Fundação (notas)

## Aprendido
- `pyproject.toml` declara deps em faixas (`>=`); `uv.lock` fixa versões exatas. Reprodutibilidade vem do lock (commitar).
- `.venv/` é local à máquina, nunca vai pro git.
- `uv sync` instala o que o lock manda; só `uv lock --upgrade` sobe versões. No CI: `uv sync --locked`.
- `.python-version` + `requires-python` fixam o Python; `uv` baixa a versão sozinho, sem tocar no Python do sistema.
- `uv add --dev` põe dep no grupo `dev` (ex.: pytest).
- pytest descobre `test_*.py` e funções `test_*`, usa `assert` puro. `testpaths` fixa onde procurar.
- Sem `[build-system]` o projeto não é instalável como pacote. Necessário na fase 5 (extração do `ai-harness`).

## O que quebrou
- `uv init` dentro de um repo git não gera `.gitignore`; `.venv/` ficou exposto até criarmos um (incluindo `.env`).
- basedpyright não achou `pydantic`: editor aberto na raiz do repo, venv em `erp-assistant/.venv`. Corrigido com `[tool.basedpyright]` (`venvPath`, `venv`) no `pyproject.toml`.
- `pytest` sem testes sai com exit 5 (falharia o CI). Corrigido com teste smoke real.
- Teste smoke original fixava `pydantic.__version__ == "2.13.5"`: frágil, quebra em qualquer upgrade sem bug real. Trocar por checagem de import.

## Setup em máquina nova
Requer `uv` (Docker nas próximas etapas). Depois: `uv sync` e `uv run pytest`.

## Pendente na fase 0
- Pydantic Settings
- Docker Compose com Postgres seed
- Tipagem (type hints) e checagem
