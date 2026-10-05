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

## Backoff (erro transitório)
- Dois retries, duas camadas. Saída inválida: o prompt muda (feedback), sem espera, quem faz é `extract_with_retry`. Transitório (429, 408, 409, 5xx, conexão, timeout): mesma requisição, **com espera**, quem faz é o SDK.
- Backoff exponencial: 0,5s, 1s, 2s... até 8s (`INITIAL_RETRY_DELAY`, `MAX_RETRY_DELAY`). Cresce para não martelar servidor já sobrecarregado. Jitter encurta a espera por sorteio (×0,75 a 1) para clientes que falharam juntos não voltarem juntos. `Retry-After` do servidor (0 < valor <= 60s) vence a conta.
- O SDK já faz tudo isso (`max_retries=2`, `timeout=60s` por padrão). Não reimplementamos: só fixamos `max_retries` e `timeout` no `GroqClient` (via `Settings`: `groq_max_retries`, `groq_timeout_seconds`).
- Esgotados os retries, o SDK levanta `RateLimitError`, `InternalServerError`, `APIConnectionError` (`APITimeoutError` é subclasse). O adaptador traduz tudo em `ProviderUnavailableError` (herda `ExtractionError`), para `extract.py` não conhecer o SDK. Cai no `except ExtractionError` existente: não reenvia e o `usage` acumulado sobe junto (custo piso).
- 429 não é cobrado (rejeitado antes de gerar). Timeout pode ter sido cobrado: custo desconhecido, sem `usage`. O retry interno do SDK é invisível para nós (não sabemos quantas requisições rolaram).
- Ordem dos `except` só importa quando uma classe herda da outra (`APITimeoutError` dentro de `APIConnectionError`). `BadRequestError` (400), `RateLimitError` (429) e `InternalServerError` (5xx) são irmãs sob `APIStatusError`: a separação "erro nosso x erro do provedor" vem do tipo capturado, não da ordem.
- Pior caso de requisições HTTP: `(max_attempts - 1) + (1 + max_retries)` = 2 tentativas inválidas (1 requisição cada, SDK não retenta 400) + 1 tentativa com 3 requisições transitórias = 5. Os limites multiplicam parcialmente.

## async/await
- `async def` devolve **coroutine**, que só roda com `await` ou agendada. Diferente de JS: `Promise` começa na criação. `f()` sem `await` não faz nada (`coroutine was never awaited`).
- `await` cede o event loop enquanto espera I/O. Uma thread só, concorrência cooperativa. Ponto de entrada: `asyncio.run(main())`. `asyncio.gather` ~ `Promise.all` (devolve lista na ordem).
- Armadilha: chamada síncrona dentro de `async def` (`Groq`, `time.sleep`) trava o loop. 10 chamadas de 1s com `AsyncGroq` + `gather` levam ~1s; com o cliente síncrono, ~10s (~ `readFileSync` no Node).
- `AsyncLLMClient` (Protocol) e `AsyncGroqClient` espelham o sync. `aextract_with_retry` repete o laço do sync com `await`: duplicação assumida; mudou a regra de retry, mudar nos dois.
- `gather` sem teto dispara tudo junto: 500 SKUs viram 429 em massa, e os retries do SDK **amplificam** a carga. O limite vem de `asyncio.Semaphore` (`max_concurrency` em `extract_many`), não dos retries.
- `extract_many` devolve `list[ExtractionResult | ExtractionError]`: falha de um item vira valor, não derruba o lote, e o custo de todos fica registrado. `except ExtractionError` dentro do `one()`, em vez de `gather(return_exceptions=True)`, porque este também engoliria bug nosso (`TypeError`) como se fosse resultado.
- `@contextmanager` com `with` comum funciona dentro de `await` (`_translate_errors`), então sync e async compartilham a tradução de erros.
- Testes async: `asyncio.run(...)` dentro de teste síncrono, sem `pytest-asyncio`. Pico de concorrência medido com contador `in_flight` no cliente falso.

## Tipagem (basedpyright)
- `**dict[str, Any]` na chamada do SDK gerou 80 warnings (`reportAny`, um por parâmetro de `create`). Corrigido com helpers tipados pelos tipos do SDK (`ChatCompletionMessageParam`, `ResponseFormatResponseFormatJsonSchema`).
- `@contextmanager` com `-> Iterator[None]` é deprecated: usar `Generator[None]`.
- `uv run basedpyright`: 0 erros, 0 warnings.

## Fase 1: pendências adiadas
- Streaming: pouco útil nos jobs batch (saída é JSON validado só no fim). Fica fora.
- Custo continua piso em: 400 `json_validate_failed`, `ProviderUnavailableError`, provedor sem `usage`. Marcar como "estimado" e guardar a geração que falhou: fase 4 (tracing).
- Feedback de retry corrigindo uma resposta real: fase 3 (evals).

# Fase 2: detecção determinística

## Passo 1: ponto de reposição
- Código calcula, LLM explica. Detecção é SQL + função pura; nenhum LLM nesse passo.
- `reorder_point = demanda_diaria * lead_time + safety_stock`. `posição = on_hand + open_po_qty`. Sinaliza se `posição < reorder_point` (igual ao ponto não sinaliza).
- Comparar só `on_hand` gera falso alarme: pedido aberto já cobre e repor de novo duplica compra.
- `lead_time` entra porque a reposição só chega depois do prazo do fornecedor. Prazo maior sobe o ponto e sinaliza mais cedo; prazo menor sinaliza tarde. Prazo errado = ruptura ou capital parado.
- Janela de vendas é parâmetro (`window_days`). Janela de 1 dia: pico vira demanda falsa, ponto infla, compra em excesso. Janela longa demais: reage devagar à mudança real.
- Detecção só sinaliza. Abrir pedido é ação: vira rascunho que humano aprova (princípio 3, assistente só lê).
- Só pedido `status = 'open'` entra em `open_po_qty`. Recebido já está em `products.stock` (contaria duas vezes). Cancelado nunca chega. `safety_stock` é outra coisa: colchão fixo do produto, não tem relação com pedidos.
- Janela de vendas é semiaberta `[as_of - N, as_of)`. Dá exatamente N dias (o código divide por `window_days`; incluir o `as_of` seriam N+1 dias e demanda inflada), evita dia parcial subestimando a demanda e evita sobreposição entre janelas consecutivas.
- `as_of` é parâmetro, o job não lê o relógio: teste determinístico. Seed com datas fixas pelo mesmo motivo.
- SQL só agrega (vendas somadas, pedidos abertos, estoque, prazo); a regra fica em Python puro e testa sem banco. Subconsultas em vez de dois `JOIN`: JOIN com vendas e pedidos multiplica linhas e infla as somas.
- Inteiros primeiro, dividir por último. `(31 / 30) * 30` dá `31.000000000000004` e o `ceil` devolveria 32. `-(-(vendas * prazo) // janela)` é teto com divisão inteira exata (`//` ~ `Math.floor(a / b)`, mas exato em inteiro).
- `class_row(dataclass)` monta cada linha do SQL por nome de coluna e dá tipo (antes: 16 warnings de `Any`). `@dataclass(frozen=True)` ~ interface com campos `readonly` que já gera construtor. `_PositionRow` com underscore é privado só por convenção.
- Seed com 4 cenários: ruptura, coberto por pedido aberto, falso alarme, pedido recebido (não conta). Mais ruído: venda fora da janela e pedido cancelado, que não podem mudar o resultado.
- Initdb só roda em volume novo: mudou schema ou seed, `docker compose down -v` e `up -d --wait`. Logo após o `up`, o WSL pode recusar conexão por alguns segundos.

## Passo 2: quantidade sugerida
- Detecção diz **que** repor; `suggested_qty` diz **quanto**. Calculado em código, nunca pelo LLM.
- `alvo = reorder_point + demanda de cover_days`; `falta = alvo - (on_hand + open_po_qty)`; `suggested_qty = falta` arredondado **para cima** ao `order_multiple` do fornecedor. Sem falta, 0.
- Subtrair a posição (não só `on_hand`): senão pede de novo o que já está a caminho.
- Arredondar para cima: sobra limitada a `multiple - 1`; para baixo ou ao mais próximo arrisca ruptura.
- Alvo acima do `reorder_point` (`cover_days`): pedir só até o ponto faria o estoque chegar rente a ele e o job sinalizaria de novo no dia seguinte (pedidos pequenos e frequentes, sem folga para pico). `cover_days` define o ciclo: maior = pedidos maiores e raros, ao custo de capital parado, encalhe e vencimento.
- `cover_days` (política) e `window_days` (histórico para medir demanda) são parâmetros diferentes. `cover_days` não muda o ponto de reposição, só o alvo.
- Quem decide se há pedido é `needs_refill` (posição < ponto), não o alvo. `covered-by-po` fica abaixo do alvo mas não é sinalizado: quantidade 0. Sem esse portão, todo produto abaixo do alvo viraria pedido.
- `suggested_qty` é função pura de números e devolve 0 se não falta nada; `stock_positions` junta as duas regras.
- `_ceil_div` compartilhado: o teto inteiro do passo 1 serve para ponto, alvo e múltiplo.
- `pytest` sem `-m` roda os testes `integration`, inclusive chamadas reais ao Groq (cota do free-tier). Para mudanças sem provedor: `uv run pytest -m "not integration"`, ou os arquivos de Postgres explícitos (`tests/test_replenishment.py tests/test_db_con.py`).

## Passo 3: tools somente leitura
- LLM é função `texto → texto`, sem acesso ao mundo e sem estado. Tool calling: o modelo só **pede** ("quero chamar X com args Y"); **o nosso código executa** e devolve o resultado como mensagem. Agente = esse ciclo num loop com limite de passos (passo 4). Harness = tudo ao redor do modelo (loop, tools, permissão, orçamento, validação, tracing).
- O modelo vê só `name`, `description` e o JSON Schema dos parâmetros. A descrição da tool é prompt. Argumentos do modelo são input não confiável (como request HTTP externo).
- Até a fase 1 foi LLM "crua": a Groq é endpoint de inferência (sem estado, sem loop, sem executar função nossa). Retry do SDK e saída restrita por schema vêm do provedor; validação, retry com feedback, custo e concorrência são harness nosso. Chamada sem harness faz sentido em tarefa fechada de baixo risco (classificar, extrair, embeddings, juiz em evals, protótipo); o harness cresce com autonomia e risco.
- Como cada peça mapeia ao mercado: `ToolInput`/Pydantic = schema de entrada; `make_tool` = o que `@tool` faz; `ToolRegistry.schemas()` = array `tools=[...]` do request; `ToolContext` = injeção de dependências (`RunContext`); `ToolError` = erro como resultado; `connect_readonly` = menor privilégio. Nossas tools têm a forma do MCP (nome, descrição, schema).
- Tools estreitas e determinísticas em vez de `run_sql(query)`: no `run_sql` o modelo escreve a query inteira (qualquer tabela/tenant, varredura pesada, impossível testar ou auditar tudo). Nas nossas, a superfície é finita, queries parametrizadas (`%s`) e o log é nome da tool + argumentos. Custo: pergunta nova exige tool nova. Job noturno é workflow (código decide os passos, LLM escreve no fim); agente real só para pergunta sob demanda.
- Somente leitura garantida no banco: `-c default_transaction_read_only=on` faz o Postgres recusar escrita mesmo que uma tool tenha bug ou receba SQL indevido. Defesa em profundidade; em produção, também uma role sem INSERT/UPDATE/DELETE.
- `as_of` vem do harness (`ToolContext`), nunca do modelo: modelo escolhendo a data tornaria a execução não reproduzível, quebraria a idempotência (fase 7) e deixaria injeção de prompt esconder item sinalizado. `window_days` e `cover_days` também não são argumentos (política).
- Erro esperado vira dado (`ToolError`): critério é "o modelo conserta mudando a próxima chamada?". `days=500`, produto inexistente, argumento inventado (`extra="forbid"`), tool desconhecida. Falha que o modelo não conserta (banco fora, bug nosso) sobe como exceção. Engolir exceção como resultado faria o modelo tratar como "sem dados" e escrever "nada a repor" (falso negativo com cara de relatório normal) e esconderia o bug do trace.
- Saída pequena e agregada: `recent_sales` soma por dia, `days <= 90`; `low_stock` limita a 50 itens e informa `total` e `truncated`. Dado cru estoura contexto, custa mais e aumenta a chance de o modelo citar número errado. Prioridade (ordem por `suggested_qty`) decidida em código.
- `recent_sales` em vez de `stock_movements`: só existem saídas; o nome não promete entradas que o schema não tem.
- Python: `def make_tool[InputT: BaseModel]` (sintaxe de 3.12) ~ `<T extends BaseModel>`; `Callable[[A, B], R]` ~ `(a: A, b: B) => R`; `Field(ge=1, le=90)` valida e entra no JSON Schema.
- Editor: Zed abre a raiz do repo e não achava o `[tool.basedpyright]` de `erp-assistant/pyproject.toml`; usava o `python3` do sistema (3.10) e acusava a sintaxe de 3.12. `pyrightconfig.json` na raiz aponta para o venv. CLI dentro de `erp-assistant/` segue lendo o `pyproject.toml`: mudou uma config, lembrar da outra.

## Passo 4: tool calling e loop do agente
- A API é sem estado: cada chamada reenvia tudo (system, pergunta, schemas das tools, todas as respostas e resultados anteriores). Tokens de entrada crescem a cada volta, então o custo cresce mais que linear; por isso existe orçamento de passos.
- Loop: chama o modelo; sem `tool_calls` = resposta final; com `tool_calls`, executa cada uma (nosso código, via `ToolRegistry`) e devolve `role: tool` com o `tool_call_id`. Toda `tool_call` precisa de resposta, inclusive quando vêm várias na mesma volta.
- `arguments` chega como **texto** JSON e o modelo nem sempre gera JSON válido (o próprio SDK avisa). JSON quebrado, que não é objeto, ou argumento errado viram `ToolError` (o modelo conserta na próxima volta). Texto vazio = `{}` (tool sem parâmetros).
- Teto é de chamadas ao modelo (`max_steps`). Estourou: `BudgetExceededError`, com `usage` e `tool_calls` já feitas. Não há "texto parcial": nas voltas com tool a mensagem é só pedido de tool, e devolvê-la como resposta faria relatório incompleto parecer completo. Não herda de `InvalidOutputError`: herdando, um retry de saída inválida reexecutaria o agente inteiro (até tentativas × `max_steps` chamadas) para falhar igual. Estourar orçamento não se resolve com retry.
- `usage` somado entre as voltas. Erro do provedor, truncamento e resposta vazia sobem com o acumulado. **Bug dentro de uma tool sobe como exceção crua e o `usage` acumulado se perde** (variável local do loop). Fase 4: registrar cada chamada ao modelo no instante em que acontece, não no fim.
- Os tipos de mensagem (`UserMessage`, `AssistantMessage`, `ToolMessage`, `ChatResponse`) são do harness; `groq_client.py` traduz de/para o SDK e segue sendo o único arquivo que o conhece. `ChatClient` é Protocol como `LLMClient`.
- `ToolCallRecord` guarda nome, argumentos e resultado de cada tool: o validador do passo 5 confere se todo número do texto veio de um desses resultados.
- Teste com cliente falso (`ScriptedChat`) guarda **cópia** do histórico de cada chamada: o loop faz `append` na mesma lista, e sem cópia todas as entradas apontariam para ela (viraria `[5, 5, 5]`).
- Chamada real (`openai/gpt-oss-120b`, Groq): 2 voltas, 907 tokens de entrada + 177 de saída; chamou `low_stock` com `{}` e o texto citou 250 e 240 (vieram da tool). Não provado ainda com modelo real: JSON de argumento quebrado, argumento errado, e o 400 do Groq para tool call malformada (hoje sobe como `BadRequestError` cru; traduzir quando aparecer). Nada garante que *todo* número do texto veio da tool: passo 5.
- `pytest -s` passa por filtro do `rtk` que esconde os prints; para ver a saída crua: `rtk proxy uv run pytest ... -s`.
- Python: `type Message = A | B | C` (3.12) ~ `type Message = A | B | C` em TS; `match message: case UserMessage():` ~ `switch` por tipo (união discriminada).
