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

## Pydantic Settings
- `BaseSettings` lê env vars e `.env`, converte tipos e valida na inicialização (falha rápida). Env real vence `.env`.
- `SecretStr` esconde o valor em repr/logs; ler com `.get_secret_value()`. Não tem `min_length`: validar vazio com `@field_validator`.
- `@field_validator` exige `@classmethod` embaixo (roda antes da instância existir). Erro: `cannot be applied to instance methods`.
- `get_settings()` com `@lru_cache` cria Settings uma vez. Nos testes, fixture `autouse` em `conftest.py` chama `cache_clear()` antes de cada teste, senão um teste vaza valor pro outro.
- `with raises(...)` envolve só a linha que deve falhar; construção de `Settings` é que levanta `ValidationError`.
- Fixtures do pytest entram por nome de parâmetro (anotar tipo: `MonkeyPatch`, `Path`). Usar `tmp_path` (Path), não `tmpdir` (legado). Isolar `.env` real com `monkeypatch.chdir(tmp_path)`.
- `pythonpath = ["."]` em `[tool.pytest]` para testes acharem `settings.py`; virar pacote fica para a fase 5.
- basedpyright estrito: falso positivo `reportCallIssue` em `Settings()` (campo vem do env); um único `# pyright: ignore` dentro de `get_settings()`.

## Pendente na fase 0
- Docker Compose com Postgres seed
- Tipagem (type hints) e checagem
