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

## Tipagem
- Type hints não são checados em runtime, nem em TS (tipos apagados). Checker separado (basedpyright ~ `tsc`). Pydantic lê as hints em runtime e valida por conta própria.
- `X | None` é o estilo preferido (3.10+); `Optional[X]` é legado e não torna parâmetro opcional.
- `list` é invariante (função poderia dar `append` de tipo pai). Parâmetro só de leitura: `Sequence` (covariante, ~ `ReadonlyArray`). Que escreve: `list`.
- `ClassVar` marca atributo da classe (~ `static`), não campo da instância. No pydantic, `model_config` não é campo nem lido do env.

## Docker Compose + Postgres
- Imagem `postgres` só entende `POSTGRES_USER/DB/PASSWORD` (outros nomes são ignorados; sem senha o container não sobe). Ela já cria usuário e banco: `CREATE DATABASE/USER` no seed falha.
- Scripts de `/docker-entrypoint-initdb.d` (mount `:ro`) rodam em ordem alfabética (prefixo `01_`, `02_`) e **só com o volume de dados vazio**. Quem decide é o volume, não o cache da imagem.
- Mudou o `.sql`: `docker compose down -v` (apaga volume) e `up` de novo. `down` sem `-v` mantém o seed antigo. `-v` destrói dados; ok aqui, só dado sintético.
- Volume nomeado precisa ser declarado em `volumes:` na raiz do `compose.yaml` (bind mount não). Erro: `refers to undefined volume`.
- `$$VAR` no healthcheck: `$$` escapa a interpolação do Compose, o shell do container expande.
- `docker compose up -d` volta quando o container iniciou, não quando o Postgres aceita conexão. `healthcheck` (`pg_isready`) + `up -d --wait` evita falha espúria (flaky) no teste.
- `${VAR}` no `compose.yaml` vem do `.env` do projeto. `env_file` ficou redundante e mandava `DATABASE_URL` com senha pro container; removido.
- Mapeamento `host:container` (`5432:5432`): conflito se a porta do host estiver em uso; mudar só o lado esquerdo e ajustar `DATABASE_URL`.
- Sem Dockerfile nem `requirements.txt` agora: `pyproject.toml` + `uv.lock` cumprem o papel, e o Postgres usa imagem pronta. Dockerfile do app fica para a fase 7.
- SQL: vírgula sobrando antes de `)` é erro (diferente de JS). `sales.product_id` com FK para o banco garantir integridade.

## psycopg e teste de integração
- `cur.execute()` devolve o próprio cursor, não linhas. Linhas vêm de `fetchone()` (tupla, mesmo com uma coluna: `row[0]`).
- `with psycopg.connect(...) as conn` fecha a conexão ao sair (~ `try/finally`, `using` do TS).
- `@mark.integration` (registrado em `[tool.pytest]` `markers`) separa testes que precisam de Docker. Unit rápido: `pytest -m "not integration"`.
- Sem DB, o teste falha com `psycopg.OperationalError: connection failed ... Connection refused`.
- Assert acoplado ao seed (`== 3`) quebra quando o seed crescer; usado `>= 1`.
- `test_smoke.py` removido: `test_env.py` e o teste de integração cumprem o papel.

## Settings x Compose
- `POSTGRES_PASSWORD` no `.env` quebrou `Settings` (`extra_forbidden`): `BaseSettings` rejeita chave de `.env` que não é campo.
- Solução: `extra="ignore"`. Custo: typo em chave do `.env` passa em silêncio. Alternativa futura: `.env` separado para o Compose.

## Setup em máquina nova (atualizado)
`cp .env.example .env`, `docker compose up -d --wait`, `uv sync`, `uv run pytest`.

## Opcional na fase 0
- `uv add --dev basedpyright` para checar tipos no terminal/CI.

# Fase 1: Chamada ao modelo (notas)

## Retry com limite
- Reenviar só `InvalidOutputError`. `Truncated` repetido com os mesmos parâmetros trunca de novo; `Refused` não muda.
- `temperature` controla a aleatoriedade da escolha do próximo token. Com `0` a saída é quase determinística: mesmo prompt, mesma resposta errada. Retry cego não ajuda.
- Para o retry valer, a entrada muda: o erro de validação vai anexado ao prompt (`_with_feedback`), sempre partindo do texto original, sem acumular feedback antigo.
- `max_attempts` é o teto. Esgotado, levanta `InvalidOutputError` com `from last_error` (~ `new Error(msg, { cause })`).
- `try` estreito: só as linhas que podem lançar o que tratamos (`_call`, `_parse`). O `return` fica fora, e `value` só é lido se a validação passou. Mesmo princípio do `with raises(...)` só na linha que falha.
- `except InvalidOutputError` vem antes de `except ExtractionError`: o Python usa o primeiro `except` que casa, então o mais específico vai primeiro.

## Custo (tokens)
- `ExtractionResult` devolve valor, `usage` somado e nº de tentativas.
- O `usage` soma todas as tentativas, inclusive as que falharam. Erro sem retry (ex.: `Truncated` depois de `Invalid`) sobe com o uso acumulado.
- O 400 `json_validate_failed` do Groq não traz `usage`: o custo reportado é um piso (real >= reportado). Limitação do provedor, não bug nosso.
- O 400 vem de truncamento (tokens de raciocínio também consomem `max_completion_tokens`) ou saída fora do schema. Com `temperature=0` é quase determinístico, não intermitente.
- Para depois: marcar custo como "estimado" quando faltar `usage`; ver se o corpo do 400 traz a geração que falhou (feedback melhor); guardar dados do request é a fase 4 (tracing).

## Testes
- Fake client não prova comportamento do provedor. `ScriptedClient` devolve uma resposta por chamada e prova a lógica do loop (tentativas, soma de uso, feedback no prompt).
- Chamada real forçando falha (`max_completion_tokens=5`, `max_attempts=2`) provou que o 400 do Groq entra no retry e que o loop desiste com a mensagem `after 2 attempts`.
- Não provado ainda: o feedback corrigindo uma resposta. Fica para as evals (fase 3).

## Custo em dinheiro
- Preço por 1M tokens, separado para entrada e saída. `custo = (prompt * preço_in + completion * preço_out) / 1_000_000`.
- Dinheiro em `Decimal`, nunca `float` (`0.1 + 0.2` dá `0.30000000000000004`). `Decimal("0.15")` (de string) é exato; `Decimal(0.15)` (de float) herda o erro binário. Inteiro em centavos não serve: preço por token é fração de centavo.
- Preços em `prices.json` versionado, com `source`, `effective_date` e `currency`. Não em `.env` (não versionado, diverge entre máquinas) nem hardcoded (mudar preço vira mudança de código).
- `PriceTable` é Pydantic com `extra="forbid"`: typo no arquivo falha na carga.
- `compute_cost(usage, price | None)` só faz a conta; quem busca o preço é outro. Testa sem arquivo, passando `Price` ou `None`.
- Modelo sem preço: `None` + warning no log, nunca 0 silencioso. O total passa a ser parcial (piso).
- Contabilidade: custo se **registra**, não se recalcula. Gravar custo e `prices_as_of` na execução; recalcular execução antiga com tabela nova dá valor errado, e atualizar só a data não corrige.
- Comparação de modelos: registrar também os **tokens**. Na comparação, recalcular os dois lados com uma única tabela de preços (único recálculo legítimo). Baseline guardado com modelo, versão do prompt, versão do golden set, score e tokens; só reroda se uma condição mudou ou para checar deriva do provedor.
- `extract.py` não importa `pricing`; `pricing` importa `extract`. Evita import circular e mantém dinheiro fora da extração.
- `logging.getLogger(__name__)` = logger por módulo. `caplog` captura logs nos testes.
- Chamada real: 201 tokens de entrada + 56 de saída = US$ 0,00006375, conferido à mão.
- O custo continua piso no 400 `json_validate_failed` (sem `usage`) e quando o provedor omite `usage`. Entrada em cache é mais barata (US$ 0,075 vs 0,15): ali o valor tende a ser teto.

## Falta na fase 1
- `async/await`, streaming, backoff para rate limit/timeout sem duplicar cobrança.
