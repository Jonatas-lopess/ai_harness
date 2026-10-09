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

## Passo 5: validador de números
- Princípio 2: todo número do texto precisa vir de um resultado de tool. O LLM pode errar dígito, arredondar ou inventar prazo, e o texto continua fluente: relatório normal com número falso. O validador roda depois do modelo, em código: extrai os números do texto, extrai os dos `ToolCallRecord.result` e reprova o que não tem origem.
- Número é token **isolado**. Dígito colado em letra (`A12`, `B07`) é identificador, não número (`(?<![A-Za-z0-9_])`). Sem isso, o `12` do SKU passa a "originar" um `12 dias` inventado: falso negativo, o pior tipo. Separador só entra se seguido de dígito, então o ponto final da frase fica de fora.
- Compara **valor** (`Decimal`), não string: `250` = `250.0`, e `1.250` = `1250`. Float erra (`0.1 + 0.2`), `Decimal` não. `1.250` é ambíguo (1250 em pt-BR, 1,25 em en): passa se **alguma** leitura bater com um valor das tools. Com a tool dando `250` reprova, com `1250` aprova. Aceitar qualquer leitura só afrouxa quando o texto é realmente ambíguo.
- Origem lida do `model_dump(mode="json")`: `int`/`float` entram pelo valor, `bool` fica de fora (`True` não é o número 1), texto passa pelo mesmo extrator do texto gerado.
- **Cálculo derivado é do código.** Pedi "some o total" e o modelo escreveu `250 + 240 = 490`: o validador reprovou, embora a conta estivesse certa. A correção não é afrouxar o validador para aceitar somas (aceitaria `500` com a mesma facilidade, e não há como separar soma certa de errada sem refazer a conta). A tool devolve o total pronto: `total_suggested_qty`, soma de **todos** os sinalizados, não só dos `items` truncados. Com isso o `490` tem origem. Duas chamadas reais depois: `stray=[]`.
- A função só devolve a lista de números órfãos (`[]` = aprovado). Quem decide o que fazer (retry com feedback, recusar, marcar) é quem chama; ligar isso ao job é do passo seguinte.
- Python: `Decimal` ~ `big.js`/`decimal.js` (JS só tem `number` float). `set_a & set_b` é interseção e `set_a - set_b` diferença, como operadores. `isinstance(x, (int, float))` aceita tupla de tipos.
- Limites abertos:
  - Números da pergunta e dos argumentos das tools ("últimos 30 dias") reprovam, porque só os resultados são origem. Vai dar falso alarme no texto real do job.
  - Datas (`2026-10-06`) viram três números soltos e só passam porque o mesmo extrator roda dos dois lados.
  - Não olha unidade nem associação: `250` citado para o produto errado passa. Conferir número **ligado ao item** é fidelidade (fase 3).

## Passo 6: job de reposição
- Job noturno é **workflow**, não agente: o código decide os passos (detectar, calcular, pedir texto, validar) e o LLM só escreve no fim. Sem tool calling aqui. O loop do passo 4 fica para pergunta sob demanda.
- O schema de saída do modelo (`Rationale`) tem só `rationale`. Sem `suggested_qty` no schema, ele não tem onde escrever a quantidade: a garantia é estrutural, não uma conferência depois. O que sobra de risco é o modelo citar número errado **no texto**, e é isso que o validador cobre. `RefillSuggestion` junta os campos do código com o texto do modelo.
- Os fatos do prompt (`RefillFacts`) são o **contrato do que o modelo pode citar**. Previsão confirmada: sem `lead_time` nos fatos, "o fornecedor leva 12 dias" reprova (12 inventado). Quer o prazo na explicação? Ele entra nos fatos. Mesma regra para `window_days`: a correção do falso alarme de "30 dias" é mandar o valor nos fatos, não aceitar números dos argumentos ou da pergunta (argumento é escolha do modelo, não é origem confiável).
- **Um item por chamada**, com os fatos daquele item como única origem. Ganho: o `240` de outro produto reprova no texto do produto errado (no lote a origem seria a união dos fatos e esse furo voltaria); retry com feedback reenvia só o item que falhou; isolamento de falha. Custo: N chamadas e o system prompt reenviado N vezes. Lote exigiria tipar entrada e saída e casar cada resposta ao item pelo `product_id` (o modelo pode omitir, duplicar ou reordenar). Com centenas de itens o certo é lote pequeno de tamanho fixo, não o job inteiro numa chamada.
- Falha de um item **degrada**, não derruba o job: depois de `max_attempts` reprovações (ou truncamento/recusa), `rationale=None` e `rationale_error` preenchido; a quantidade, que vem do código, continua valendo. Alternativas rejeitadas: (a) falhar o job inteiro perde todos os itens por causa de um; (c) emitir o texto reprovado mesmo assim leva ao erro, e é o único caso crítico. `None` explícito, nunca string vazia que pareça normal.
- Critério para degradar ou subir: "o problema é deste item?". `TruncatedOutputError` e `RefusedError` são do item e retry repetiria igual: degrada sem retry. `ProviderUnavailableError` é infraestrutura: tentar os outros itens só martelaria um provedor fora do ar. Sobe, com o `usage` acumulado (`exc.usage`), e o job pode rodar de novo (idempotência: fase 7).
- Texto em branco vira `InvalidOutputError` e entra no retry. A checagem é no código, não no schema (`minLength`), porque o modo strict do provedor pode não aceitar esse campo do JSON Schema.
- Prioridade (maior `suggested_qty` primeiro) decidida em código, como na tool `low_stock`. `RefillReport` guarda `prompt_version` e `model`: princípio 5, todo resultado diz com qual prompt e modelo foi gerado.
- Refatoração pequena no que já existia: `parse_completion[T: BaseModel](completion, model)` generaliza o `_parse` (que só conhecia `StockMessage`), e `with_feedback` virou público porque o job reaproveita o mesmo texto de feedback. `ungrounded_in(text, facts)` é o validador do passo 5 com os fatos como origem.
- Teste do job com banco usa cliente falso (`_Echo`, `_Chain`) e o Postgres do seed: prova que a quantidade vem do código e que um item ruim não derruba os demais. Chamada real (`gpt-oss-120b`): 2 itens, 542 tokens de entrada e 215 de saída, sem retry, textos citando estoque e ponto de reposição.
- Python: `def parse_completion[T: BaseModel](..., model: type[T]) -> T` ~ `<T extends BaseModel>(model: new () => T): T`: o tipo devolvido acompanha a classe passada. `class RefillSuggestion(RefillFacts)` herda os campos do Pydantic e acrescenta os seus.
- Limites abertos:
  - Sem `summary` geral do `RefillReport` do guia: precisa de fatos agregados próprios.
  - N chamadas por job sem teto de custo por execução: orçamento na fase 8; custo registrado como piso, fase 4.
  - Fatos sem `lead_time` nem janela de vendas: o modelo não pode explicar "a venda dobrou".
  - Número ligado ao item errado dentro do mesmo item (ex.: trocar `on_hand` por `reorder_point`) passa: fidelidade, fase 3.

## Fase 2: fechamento
- Critério de pronto: "toda quantidade do texto bate com o cálculo; ferramentas somente leitura". Cumprido: a quantidade nunca passa pelo modelo, o texto passa pelo validador, e a leitura somente é garantida no banco (`default_transaction_read_only=on`).
- Pendências para a fase 3: golden set com falso alarme, fidelidade e recusa; `summary`; falso alarme de números de pergunta/argumento; fidelidade número-item.

# Fase 3: validadores e evals

## Passo 1: golden set de detecção
- Golden set = **dados** (`Case`: entrada + esperado), não um `test_x` por cenário. Caso novo é uma linha; o runner dá score por grupo (`detection` 13/13, `false_alarm` 11/11) e esse número é o que se guarda e compara depois. `python -m evals.detection` imprime o score e sai com código 1 se algum caso falha.
- Previsão: A (60+45 = ponto 105, não sinaliza) certa; B sinaliza certo, mas a quantidade era **200**, não 300 (alvo 255, falta 151, `ceil(151/50)` = 4 caixas). Erro típico: usar as vendas (300) no lugar do alvo.
- Esperados calculados **à mão**, nunca pela função testada: se `suggested_qty` tivesse bug, um esperado derivado dela repetiria o bug e o eval passaria. Resposta do autor à revisão: certa em essência (circularidade).
- `group` é propriedade derivada de `expected_flagged`, sem campo próprio: dado redundante poderia contradizer.
- `passed` exige flag **e** quantidade. Acertar a quantidade sinalizando errado não conta.
- Refatoração: `position_from_row(row, window_days, cover_days)` extraída de `stock_positions`; `PositionRow` público. O eval roda a mesma composição que o SQL usa. SQL só agrega, a regra é Python puro.
- Eval tem que **saber falhar**: três testes provam que quantidade errada, flag errada e contagem por grupo reprovam.
- Mutação `<` -> `<=` em `needs_refill` reprova 7 casos, todos com estoque+pedido = ponto: `exactly-at-point-with-po`, `exactly-at-point-no-po`, `po-covers-all`, `zero-stock-zero-demand`, `no-sales-safety-met`, `ceil-boundary-at-point`, `fast-supplier-at-point`. `false_alarm` cai a 4/11. As bordas valem justamente por isso. Autor pulou esta pergunta.
- `zero-stock-zero-demand` (ponto 0): pega também a regra ingênua "estoque 0 = sinaliza"; com `<=` sinaliza com qtd 0 (alerta sem nada a pedir). `no-sales-safety-met` (ponto vem só da segurança): pega `<=` quando a demanda é zero. O que importa não é "quantidade sem histórico", é **alerta falso com quantidade 0**. O erro de somar segurança de menos é pego pelo caso `safety-stock-only` (grupo `detection`), não por esses dois.
- Sem chamada ao provedor neste passo (tudo determinístico); a verificação real é o Postgres do seed (testes de `replenishment` e `refill_job_db` seguem verdes).
- Pendente nos próximos passos: fidelidade (número certo no campo/item errado), recusa, resumo de fechamento, trajetória, score+custo guardados, juiz calibrado, CI.

## Passo 2: fidelidade (número no campo certo)
- Previsão: "estoque 40, ponto de 3" (valores trocados) **passa** o `ungrounded_in`: ele só pergunta "esse número existe nos fatos?", não "ligado a quê?". Certa. Regra proposta pelo autor: usar a estrutura da frase ("x é y") para casar campo e valor. Caminho certo; implementado como versão pragmática: palavras-rótulo por campo, em vez de gramática.
- `mislabeled_numbers(text, values, aliases)`: por oração, rótulo mais próximo **antes** do número (se nenhum, o mais próximo depois) define o campo afirmado; o número tem que ser o valor dele. Só julga número que bate com algum fato (o resto é do `ungrounded_in`, sem relato duplicado). Oração cortada em pontuação + espaço, para "1.250" não quebrar. Ligado ao `explain`: texto trocado volta ao modelo com feedback e conta nas tentativas.
- Alternativa de design não escolhida: o modelo devolver `claims: [{campo, valor}]` e o código conferir cada claim. Fecharia a lacuna sem heurística (resposta do autor, certa), mas muda o schema decidido na fase 2 (só `rationale`) e ainda exigiria cruzar claims com o texto. Fica para quando a heurística não bastar.
- Limite assumido, com teste: número sem rótulo na própria oração não é julgado ("Há 40 itens, abaixo do ponto." passa). Também não pega nome de outro produto no texto. O juiz (passo 5) cobre o resto.
- **A chamada real achou um bug que o simulado não achou.** Primeira versão: rótulo mais próximo em qualquer direção. Em "…ponto de reposição de 105 e não há pedidos em aberto…", `pedidos` (10 caracteres depois) ganhou de `ponto` (17 antes); o item 1 gastava 2 tentativas sempre (uso 854/287 vs 542/215 da fase 2 foi a pista). Correção: rótulo anterior tem prioridade; nomes de campo (`open_po_qty`) também são rótulo, pois o modelo cita as chaves do JSON. Depois: 6 chamadas, 1 tentativa cada.
- Lição (resposta do autor: "golden set insuficiente"; refinada): os casos simulados são frases que **eu imaginei**; o cliente falso só repete o que escrevi. O modelo real gera construções não previstas. Remédio: colher texto real para dentro do golden set (`real-groq-open-po-sentence`). Simulado em todo commit, real antes de mesclar, e o real alimenta o golden.
- Golden `evals/fidelity.py`: 17 casos (8 fiéis, 9 infiéis) pelo `explain` de produção com `_FixedClient`. Mutação: sem o validador de rótulo, 6 infiéis passam (10/16). `python -m evals.fidelity` sai com 1 se algum falha.
- Python: `before or after` devolve a primeira lista não vazia (lista vazia é falsy) ≈ `before.length ? before : after`. `min()` em lista de tuplas compara tupla a tupla. `dataclasses.replace` só serve para dataclass; Pydantic usa `model_copy(update=...)`.

## Passo 3: resumo de fechamento (fidelidade com total conhecido)
- Previsão do autor errada, e instrutiva: "faturamento R$ 1.500,00, deve crescer 10%" **não** passa. O `10` não existe nos resultados e `ungrounded_in` reprova; os aliases não entram (servem para número que existe em OUTRO campo). O furo real é "deve crescer no próximo mês" **sem número**: validador numérico não vê. É grupo recusa (passo 4), não fidelidade.
- `closing.py`: SQL agrega, Python monta `ClosingFacts` (dia, faturamento, unidades, produto de maior faturamento). Dia sem venda -> `None`: o código decide que não há o que narrar e o LLM nem é chamado. Preço = `products.price` atual (schema não guarda o preço da venda).
- `revenue` é `Decimal`, nunca `float` (pergunta 1, respondida pela IA a pedido do autor): float binário não representa centavos (`0.1+0.2`); o JSON dos fatos levaria `0.30000000000000004` e o texto fiel ("exatamente como está") ou ficaria feio ou reprovaria. Com `Decimal` o JSON leva `"10950.00"`, que passa no mesmo extrator do texto; `Decimal("10950.00") == Decimal("10950.0")`, então "R$ 10.950" sem centavos também vale.
- `narrate.py`: o laço retry+validação saiu do `explain` e virou `narrate(client, facts, system=, values=, aliases=, ...)`. `explain` (reposição) e `narrate_closing` são wrappers finos: o segundo consumidor mostra o que é genérico (laço, validadores) e o que é do job (prompt, fatos, rótulos). Candidato a harness na fase 5. Refatoração coberta pelos 117 testes anteriores, sem mudar assertivas.
- `mislabeled_numbers` de novo: rótulo só vale **entre o número e o vizinho**. Em "faturamento de R$ 10.950,00 com 465 unidades" o rótulo anterior mais próximo de 465 era `R$`, que é do outro número. Previsto ANTES da chamada real desta vez; teste `test_label_belongs_to_the_neighbouring_number_only`.
- Golden `evals/closing.py`: 17 casos (9 fiéis, 8 infiéis) com total conhecido (R$ 10.950,00 / 465 un.), formatos pt-BR, `10950.00`, número antes do rótulo, campos trocados, total/unidades errados, arredondado ("R$ 11 mil"), crescimento e projeção inventados. Um caso é texto real do Groq (copia o valor literal sem formatar). Chamada real: 6 chamadas, 1 tentativa cada.
- Dia 20 no golden e não 10: o dia 10 coloca o número `10` nos fatos (a data), então "10% acima" inventado **passa** como fundamentado (idem `1`, o mês). Lacuna documentada em `test_known_gap_percent_equal_to_a_date_part_is_grounded`. Remédio sem juiz (autor não respondeu; sugestão): data nos fatos como texto formatado, fora do conjunto de números válidos, ou validador que só aceite partes de data em padrão de data.
- Segunda lacuna documentada (`test_known_gap_forecast_without_numbers_is_accepted`): projeção sem número passa. Passo 4.
- Bug achado e corrigido: `test_readonly_connection_rejects_writes` falhava desde a fase 2. `with raises(X) and conn_mgr` usa só o último operando do `and`, então `raises` nunca entrava. Correto: `with connect_readonly(url) as conn, raises(X):`. Um teste que nunca rodou verde passou despercebido porque a suíte integration não era rodada inteira.
- Autor marcou perguntas 2 e 3 como "já visto".

## Passo 4: recusa
- Previsão do autor: o campo `status` "garante apenas que a LLM entenda que pode recusar". Certa e é o ponto: o campo dá ao modelo uma saída legítima e ao código algo em que ramificar; **não** garante que o modelo escolha certo. Quem decide se ele recusa é o modelo; o código só confere o que dá para conferir sem LLM.
- `answers.py`: resposta final `STATUS: answered|insufficient_data` na primeira linha, texto depois; `judge()` aplica regras de código:
  - cabeçalho ausente, status desconhecido, texto vazio -> `rejected`;
  - número no texto, em qualquer status, tem que vir de tool (recusa com "chuto 500" reprova);
  - `answered` exige ao menos uma tool **bem-sucedida** (`ToolError` não conta): afirmação sem evidência é rejeitada. Fecha "deve crescer no mês que vem" quando o modelo nem consultou nada.
  - `rejected` nunca expõe o texto (`text=None`), só o motivo.
- **A chamada real quebrou a primeira versão.** Pedir "responda SOMENTE com um objeto JSON" com tools ligadas fez o gpt-oss emitir o JSON como tool call chamada `json`/`JSON`, e o Groq respondeu HTTP 400 `tool_use_failed` (4/4 falharam). Roteiro simulado nunca veria isso. Correção: cabeçalho de texto (`STATUS:`) sem a palavra JSON no prompt; validação continua local. Real depois: 4/4 em 3 rodadas (previsão e preço de concorrente recusados; reposição e prazo respondidos com tool).
- `evals/refusal.py`: 12 casos (roteiros do modelo: tool calls + resposta final) julgados pelas regras. Cobre recusa correta, recusa depois de consultar, resposta com tool, e erros do modelo que o código tem que pegar (sem tool, número inventado, palpite na recusa, número errado, só tool falha, sem cabeçalho, status desconhecido, texto vazio).
- Autor, pergunta 3: "simulado não prova o modelo real". Complemento: simulado prova as **regras do código** (determinístico, grátis, todo commit); real prova o **comportamento do modelo** e acha o que ninguém imaginou (o 400 acima), ao custo de cota e não determinismo.
- Lacuna documentada (`test_known_gap_forecast_prose_after_a_real_tool_call_is_accepted`): com tool bem-sucedida e texto "Foram 300 e deve crescer no mês que vem" passa. Só juiz de fidelidade (passo 5).
- Suíte completa: `test_real_extract_many_async` (fase 1, Groq real) falhou uma vez em 3 rodadas completas e passou nas outras; instável, sem relação com o passo.
- Perguntas 1 e 2 marcadas "já visto" pelo autor.

## Passo 5: runner único de evals + CI
- Previsão do autor certa: sem o validador de rótulo, **os dois** falham (testes unitários e golden). Medido: `swapped = []` em `narrate.py` -> fidelity 11/17, closing 15/17, `python -m evals` sai 1, pytest falha em `test_number_on_the_wrong_field_is_retried_with_feedback`. Dois níveis de rede: teste unitário protege a regra; golden protege o comportamento do conjunto de casos.
- Pergunta 2 (CI sem `integration`): cota, mas também não determinismo (a suíte real já falhou 1 em 3 sozinha) e secret `GROQ_API_KEY` no CI. CI vermelho por flake ensina a ignorar CI. Real roda à mão antes de mesclar.
- `evals/__main__.py`: `python -m evals` roda as 4 suítes (detection, fidelity, closing, refusal), imprime `nome: ok/total`, `FAIL suite/caso` e total; sai 1 se qualquer caso falha. `__main__.py` é o arquivo que o Python executa em `python -m pacote` (≈ `bin` de um package.json). `Scored` é um `Protocol` (tipagem estrutural ≈ interface TS): qualquer resultado com `.case.name` e `.passed` serve, sem herança.
- `.github/workflows/ci.yml` (raiz do repo, o GitHub só lê de lá): `uv sync --locked`, `pytest -m "not integration"`, `python -m evals`, `basedpyright`. Sem Docker, sem Groq. `--locked` falha se `uv.lock` diverge do `pyproject.toml`.
- Não verificado: o workflow nunca rodou no GitHub (sem push neste passo). Comandos conferidos localmente um a um.
- Falta para fechar a fase 3: trajetória (tools certas, ordem, orçamento), score + custo por execução, LLM-as-judge calibrado (fecha as lacunas "projeção sem número").
- Perguntas de revisão do autor: (1) `Protocol` evita acoplamento: pack não precisa importar base do harness só para tipar resultado; (2) `--locked` não é o que trava versões (o `uv.lock` trava): ele faz o CI falhar se lock e `pyproject.toml` divergem, em vez de resolver versões novas em silêncio; (3) "já visto".

## Passo 6: trajetória + score/custo por execução
- Previsão do autor, 1: trajetória errada com resposta certa = **inflação de custo** (chamada repetida, tool inútil); os evals antigos só testam o resultado. Certa. 2: o autor escolheu igualdade exata, mas apontou o desenho melhor por conta própria: tools certas em **quantidade aceitável**, pois há mais de um caminho igualmente certo. Foi o que implementei. Igualdade exata reprova caminho válido (flake de falso alarme); subconjunto deixa passar o custo inflado.
- `evals/trajectory.py`: `Bounds(min, max)` por tool; tool fora da tabela é **proibida**; ordem **não** conferida (decisão: os dois caminhos `optional-tool-first/last` são válidos). `violations()` devolve códigos `forbidden:t`, `missing:t`, `too_many:t`, `over_budget`. O caso declara as violações esperadas (vazio = limpo), como o golden de recusa: o eval também prova que o código PEGA o caminho ruim. 10 casos, usando o `run_agent` de produção com `ScriptedChat`.
- `BudgetExceededError` vira violação `over_budget`, não crash do eval: a exceção já carrega as `tool_calls` (decisão da fase 2 que pagou aqui). Caso `budget-blown-and-wasteful` junta duas violações.
- Limite: ordem só importaria se uma tool dependesse do resultado de outra (ex.: buscar SKU antes de ler estoque). Quando existir esse caso, é restrição à parte; não inventei antes.
- Runner: 5 suítes, 80 casos. `python -m evals --record` acrescenta uma linha em `evals/history.jsonl` (data, commit, `mode`, score por suíte, `cost_usd`). Sem a flag nada é escrito, para o CI e o uso diário não sujarem a árvore. `cost_usd` é 0.0 por construção no simulado (`Usage(0, 0)`); passo 7 (real) preenche. Honesto: o campo existe, o custo real ainda não.
- Mutação: `elif counts[tool] > bounds.max` desligado reprova `repeated-call-inflates-cost` e `optional-tool-too-many`; pytest também falha.
- Python: `Mapping` é covariante no valor, `dict` não (`dict[str, list[X]]` não vira `dict[str, Sequence[X]]`); parâmetro somente leitura deve ser `Mapping`/`Sequence` ≈ `Readonly<Record<...>>`/`readonly T[]` em TS. `_ = f.write(...)`: descarte explícito do retorno exigido pelo basedpyright.
- Falta na fase 3: LLM-as-judge calibrado (lacunas "projeção sem número" e "% igual a parte de data"), passo 7.
- Perguntas de revisão do autor: (1) violações se acumulam e cada uma é identificável; complemento: só funciona porque `BudgetExceededError` carrega `tool_calls`; (2) "bloat de informação"; complemento: no CI o checkout é descartável (linha perdida ou commit de volta) e o histórico só vale com execuções deliberadas e comparáveis; (3) sem resposta (ordem de tools dependentes fica em aberto).

## Passo 7: LLM-as-judge calibrado (Groq)
- Previsão do autor, 1: "modelo é parcial" = viés de autopreferência. Mitigação aplicada: juiz de outra família. Único modelo de chat não-OpenAI no Groq em 2026-10-08 (`/models`): `qwen/qwen3.8-27b`. 2: o que decide são os 10% que erram, não o total: **falso "fiel"** (juiz aprova o que humano reprovou) é o perigoso; falso "infiel" só custa retry/revisão. O gate é `false_faithful_rate <= 10%`, não a concordância.
- Jev (modelo novo da TypeSafe AI, P(sim/não) em vez de texto) pesquisado: bom encaixe como juiz (probabilidade permite escolher o limiar), mas o autor não tem acesso. Não testado. `Judge` é um `Protocol`: plugar o Jev depois é uma classe nova, sem mexer no resto. Números de velocidade/custo dele são da própria empresa.
- `judge.py`: `LLMJudge(client, model)` sobre o `LLMClient` existente; uma chamada, sem retry; saída `{reason, verdict}` com `reason` primeiro. `JUDGE_PROMPT_VERSION = "judge-v1"`. O texto avaliado é dado, não instrução (injeção).
- **Prompt fraco falhou na sonda**: com instrução vaga o Qwen escreveu em `reason` "não é sustentada pelos fatos" e devolveu `verdict: faithful`. Contradição interna. O v1 define o que é `unfaithful` e exige que veredito concorde com a razão.
- `evals/judge_calibration.py`: 47 exemplos rotulados: 34 `golden` (rótulo herdado: aceito pelo código = fiel) + 13 `gap` (o que o código não vê: previsão sem número, causa/comparação/tendência/recomendação inventada, número de unidades atribuído ao produto, "10%" igual à parte da data). Os `gap` foram rotulados pela **IA** e esperam revisão do autor. Teste garante que todo `gap` infiel é **aceito** pelo código de produção (senão não é lacuna).
- Resultado real (3 rodadas): concordância 94% (3 a 4 desacordos em 47), 0 erros de saída, **13/13 `gap` corretos**, falso "fiel" 8% (2 casos), falso "infiel" 5% (1). Dá 12k tokens de prompt e 2.6k de completion por rodada. Custo em dinheiro `n/d`: não há preço do Qwen em `prices.json` e não inventei.
- Os desacordos são sobre o RÓTULO, não só o juiz:
  - `derived-sum` (40+30=70): o golden diz infiel e está CERTO: política do projeto é que valor derivado tem que vir como retorno da tool (autor, pergunta 1). O erro foi do juiz: o prompt v1 listava "arredondado" mas não dizia que conta correta também reprova. (Minha primeira nota chamou isso de "rótulo discutível": errada.)
  - `rounded-total` ("cerca de R$ 11 mil"): política diz infiel; juiz aprovou **apesar** do prompt listar "arredondado". Erro real do juiz (falso "fiel").
  - `real-groq-verbatim`: juiz reprovou porque o JSON dos fatos traz `top_product` sem dizer que é "por faturamento". O juiz vê só o JSON, sem a descrição do campo que o gerador recebe no prompt. Lição: juiz precisa do mesmo contexto semântico que o gerador.
  - `thousands-swapped` apareceu em 1 de 3 rodadas: mesmo com `temperature=0` o juiz **não é determinístico**.
- Limites: 47 exemplos é pouco (o guia pede "algumas dezenas" rotuladas por você); 13 `gap` rotulados pela IA; 8% sobre 25 infiéis = 2 casos, intervalo de confiança enorme. O número só ganha valor com mais exemplos e rótulo humano. O juiz NÃO está ligado ao `narrate` nem ao CI: é eval offline para rodar antes de mesclar (cota, não determinismo).
- Erro de processo meu: lancei a calibração em loop (4 execuções em vez de 2) e gastei cota à toa.
- `python -m evals.judge_calibration` (real, sai 1 se falso "fiel" > 10%); `tests/test_judge*.py` simulados (14 testes, no CI); `tests/test_judge_integration.py` com 2 casos reais.
- Prompt `judge-v2` (acrescenta: número que não aparece nos fatos reprova mesmo sendo conta correta). 1 rodada: concordância 94%, falso "fiel" 4% (1: `rounded-total`, o juiz justificou "11.000 é arredondamento válido"), falso "infiel" 10% (2: `real-groq-verbatim` e `open-po`, este novo). `derived-sum` passou a certo, `open-po` passou a errado: 1 caso por 1 caso, dentro do ruído de 47 exemplos e de um juiz não determinístico. Aperto no prompt troca falso "fiel" por falso "infiel": o sentido seguro, mas custa revisão. Mantido o v2.
- Autor, perguntas de revisão do passo 7: (1) derivado só se vier da tool (política já fixada); (2) rotular `gap` pela IA enfraquece a calibração (complemento: rotulador e juiz são o mesmo tipo de sistema, erros correlacionam, concordância sai inflada; rótulo que vale é o humano); (3) CI não chama LLM (complemento: determinismo, custo zero, sem secret).
- Pendente do autor: revisar os 13 rótulos `gap` em `evals/judge_calibration.py`.
- Decisão do autor: `faithful-refill-no-numbers` e o golden `fidelity/no-numbers` ficam como estão (texto sem número pode ser fiel). Troca por exemplo numérico foi feita e revertida. Demais `gap` sem objeção até aqui.

## CI: primeira execução real (falhou) e correção
- O workflow rodou no GitHub e reprovou `tests/test_env.py::test_env_url_valid`: `groq_api_key Field required`. O teste definia só `DATABASE_URL`; a chave vinha do `.env` local, que não existe no runner. Passava na máquina do autor e falhava no CI: o CI serviu ao propósito.
- Pior, achado ao investigar: `test_env_steps_invalid` e `test_env_url_empty` passavam no CI **pelo motivo errado** (campo ausente também lança `ValidationError`). Teste que passa sem testar o que diz é o mesmo problema do `raises(...) and ...` da fase 3.
- Correção: fixture `autouse` deixa o ambiente conhecido (cwd vazio = sem `.env`; só as duas variáveis obrigatórias, válidas) e cada teste muda uma coisa; `raises(..., match="campo")` confere QUE campo falhou. +2 testes da chave Groq (ausente, prefixo errado), que não tinham cobertura. Verificado localmente sem `.env` e com `env -u DATABASE_URL -u GROQ_API_KEY`: 159 passam, evals 80/80.
- Regra: teste de unidade não pode depender de arquivo da máquina. Reproduzir o CI localmente = apagar `.env` e as variáveis do ambiente.
- CI verde no GitHub depois da correção. **Fase 3 concluída**: golden set (80 casos, 5 suítes) + CI (pytest, evals, basedpyright) + trajetória + histórico de score + juiz calibrado (preliminar: 47 exemplos, rótulos `gap` só parcialmente revisados).
- Dívidas conhecidas, adiadas de propósito: mais rótulos humanos para o juiz; custo em dinheiro do Qwen (sem preço em `prices.json`); ordem de tools dependentes (trajetória); `test_real_extract_many_async` instável (fase 1, real).

# Fase 4: observabilidade

Plano (passos): 1 span/trace/request ID; 2 instrumentar o loop do agente e o `narrate` (prompt, usage, custo, latência); 3 custo por job + `prompt_version` + `model`; 4 mascarar dado sensível antes de gravar; 5 comando que reconstrói a história de um `request_id`; 6 chamada real + notas. Decisão: tracer próprio mínimo com formato parecido com OpenTelemetry (trace_id, span_id, parent_id), sem Langfuse por ora; trocar depois é um sink novo, não reescrita.

## Passo 1: span + trace + request ID
- Previsão do autor, 1: span com erro registrado. Certa; o erro é a causa que o trace precisa mostrar (sem ele, "lento e sem resposta"). Circuit breaker fica fora do escopo. 2: "contextmanager com `with as`". Metade: isso é como abre e fecha, não como acha o pai sem parâmetro. A resposta é `contextvars.ContextVar` (≈ `AsyncLocalStorage` do Node).
- `tracing.py`: `trace(name, sink, request_id=...)` abre a raiz e grava no `finally`; `span(name, **attrs)` abre filho do span ativo. `Span` (ids, início ISO, `duration_ms`, `status`, `error`, `attributes`), `Trace` (= `request_id` + lista de spans), `TraceSink` é `Protocol` (`MemorySink` nos testes, `JsonlSink` com uma linha por trace).
- Decisões: trace gravado uma vez no fim (um crash do processo perde o trace em andamento: troca por simplicidade); `span()` sem trace ativo roda e não grava nada (código instrumentado não quebra sem tracer); `clock` injetável para teste de duração determinístico; `default=str` no JSON (Decimal/date não derrubam a gravação); erro registra `Tipo: mensagem` e é relançado, inclusive `CancelledError`.
- `RequestContext` (tenant, usuário, papel) ainda não existe; `request_id` entra como parâmetro opcional.
- Mutação: `ContextVar` trocado por variável global deixa `test_concurrent_traces_do_not_mix_parents` vermelho. Sem o `await asyncio.sleep(0)` no teste ele passaria mesmo com o global: sem `await` o `gather` roda um job inteiro e depois o outro, nada se intercala.
- Não verificado: nenhuma chamada real (o passo não toca o LLM; entra no passo 2).
- Riscos conhecidos: esquecer de abrir o `trace` faz o `span` sumir em silêncio; trace só no fim perde execução interrompida.
- Perguntas de revisão do autor: (1) "que uma chamada await foi feita"; incompleto: o `sleep(0)` cede o loop e **intercala** os jobs, é isso que o teste precisa para provar o isolamento; (2) crash no meio não salva dado; certo para o risco de gravar no fim, faltou a vantagem (linha completa) e o risco do `span` silencioso fora de trace; (3) vazamento de informação; certo, tratado no passo 4 (mascarar antes de gravar).

## Passo 2: instrumentar o loop do agente e o `narrate`
- Previsão do autor, 1: não guardar o prompt completo em cada `llm_call`; guardar a `Message` correspondente (o delta). Certa: com N voltas o histórico reenviado cresce quadraticamente se copiado a cada volta; guardando só o que saiu, cresce linear, e o enviado em qualquer volta = `user` + as saídas anteriores. `system`/`user` entram uma vez, no span `agent`. 2: `ToolError` -> span `ok`, "não é exceção". Certa; motivo de debug acrescentado: atributo `tool_error=True` para achar essas tools sem sujar o `status`.
- Estrutura: `agent` (model, system, user, max_steps, steps, tokens) > `llm_call` (step, tokens, `finish_reason`, `content`, `tool_calls`) e `tool` (name, arguments, result, `tool_error`). `narrate` (facts, system, outcome, attempts) > `llm_call` (attempt, tokens, content, `retry_feedback`) + `validate` por tentativa. Chamada ok e texto reprovado são coisas diferentes: a rejeição fica no `validate` com o motivo no `error`.
- Decisão do autor (pergunta 2): `validate` fica `error` quando reprova e `tool` com `ToolError` fica `ok`: `status` = o resultado do que aquela etapa faz (checar / executar). Complemento: `validate` vermelho não é job falho; o veredito está no pai (`outcome` no `narrate`).
- **Dois problemas achados pelos testes, em código meu:** (1) `span("tool", name=...)` quebrava (`got multiple values for argument 'name'`): atributo colidia com o parâmetro; bug de design do passo 1, corrigido com `name`/`sink` posicionais-somente (`/`). (2) Ao reindentar o loop do agente, o `raise BudgetExceededError` ficou fora do `with span("agent")` e o orçamento estourado saía `ok`; `test_budget_exhaustion_shows_in_the_agent_span` pegou.
- Mutação: `tool_error=False` fixo deixa `test_tool_error_is_flagged_but_the_span_stays_ok` vermelho. Suíte 176 passam (também sem `.env` e sem as variáveis); evals 80/80; basedpyright 0/0.
- **Chamada real** (`openai/gpt-oss-120b`, Postgres do compose): 2 voltas, tool `low_stock`, 1809 ms. `test_real_agent_trace_explains_the_run` grava JSONL e confere que o trace bate com o `AgentResult` (soma de `prompt_tokens` = `usage`, nomes das tools, `content` do último `llm_call` = texto final). Não coberto por chamada real: a instrumentação do `narrate` (só simulado; o passo 3 liga o job inteiro).
- Lacunas do trace para reproduzir o que o modelo viu (abertas): `user` da retentativa do `narrate` (só o booleano; reconstrói-se de fatos + erro do `validate`, se `with_feedback` for determinístico), tool schemas enviados, `max_completion_tokens`/`temperature`/`reasoning_effort` (vivem em `groq_client.py`), `prompt_version` (passo 3).
- Passo 4 vai ter que decidir o que mascarar sem quebrar a verificação: o trace guarda `result` completo da tool e `facts`. Regra: mascarar dado do cliente (nome, documento, texto livre da pergunta), **não** mascarar o que a checagem de fundamento precisa (números, ids, SKU).
- Perguntas de revisão do autor: (1) mascara informação do cliente e não mascara dados de produto; direção certa, faltava a restrição (não mascarar o que a verificação precisa); (2) consistente, ver acima; (3) "UserMessages"; o `user` do agente já está no span `agent`; a lacuna real é o `user` da retentativa do `narrate`, mais schemas, parâmetros e `prompt_version`.

## Passo 3: custo por job, `model` e `prompt_version` no trace
- Previsão do autor, 1: custo gravado **ao gravar** o span; pergunta lateral "afeta o tempo?". Certa: congela o preço vigente (recalcular na leitura reescreveria o custo histórico com o preço novo). Tempo: desprezível (uma multiplicação de `Decimal` contra centenas de ms de LLM); o custo real é o write síncrono do JSONL ao fechar o trace, que num loop asyncio bloqueia por um instante (aceitável nesta escala, limite anotado). 2: soma dos conhecidos, "pode ou não ser explicitado". Soma certa; **explicitar é obrigatório**: total parcial sem aviso é um número sem origem confiável. Grava-se `cost_complete` e `calls_without_cost` ao lado.
- `pricing.py`: `usage_attributes(usage, model)` (tokens, `cost`, `currency`, `prices_as_of` por chamada, usado em `agent.py` e `narrate.py`), `job_cost(spans)` (soma só `llm_call` com preço; conta o resto), `costed_span(name, **attrs)` (span de job que, no `finally`, soma os `llm_call` **descendentes** e grava `cost`, `cost_complete`, `llm_calls`, `calls_without_cost`, tokens). `tracing.py` ganhou `current_trace()` e `descendants()`. `refill_job` e `closing_job` rodam dentro de `costed_span(..., model=, prompt_version=)`.
- Soma no `finally`: falha também gasta. Um job que quebra na chamada 3 não perde o custo das duas primeiras (teste `..._even_when_the_job_fails`, vermelho sem o `finally`).
- Escopo por descendentes: dois jobs no mesmo trace não se somam (`job_b` não inclui `job_a`).
- Mutação: `complete=True` fixo -> vermelho; cálculo fora do `finally` -> vermelho.
- Bug de tipagem achado no caminho: `span(name, **attributes: object)` com `clock` como keyword fazia o basedpyright reclamar (`object` não é `() -> float`). Tirei `clock` de `span()`; só `trace()` o mantém (usado no teste de duração).
- **Chamada real** (Groq, `refill_job`, `request_id=real-2`): 2 chamadas, 542 tokens de entrada, 233 de saída, `cost=0.00022110`, `cost_complete=True`. Conferido à mão: 542*0,15 + 233*0,60 = 221,1 por milhão. `prompt_tokens` do trace = `report.usage`.
- Decisão minha / dívida: `agent.py` e `narrate.py` usam `default_prices()` (tabela global em cache de `prices.json`), sem passar a tabela por parâmetro. Acoplamento escondido; a correção é injetar na borda (parâmetro do job, default `None`, resolvido uma vez por execução). Morde quando um processo longo (scheduler, fase 7) edita o `prices.json` e segue cobrando o preço antigo até reiniciar; `prices_as_of` no span deixa isso detectável.
- Limite do teste "trace x relatório": os dois caminhos partem do mesmo `Usage`, então não pega `Usage` errado/`None` do provedor, preço errado no `prices.json` (coerente nos dois), nem chamada ao modelo fora de qualquer span.
- Pergunta em aberto: estimar o custo das chamadas sem preço por média seria um campo à parte, rotulado como estimativa; nunca dentro de `cost`.
- Perguntas de revisão do autor: (1) o contador diz a distância até o valor real e permite projetar por média; certo, a estimativa fica em campo separado; (2) "valor coerente; chamadas sem custo"; vago: prova que as duas contagens batem; não pega `Usage`/preço errados na origem; (3) "stale cache"; certo, cenário e correção acima.

## Passo 4: mascarar dado sensível antes de gravar
- Previsão do autor, 1: "já visto" (válido). Allowlist falha **fechado** (atributo novo aparece mascarado: perda barata e visível); denylist falha **aberto** (vaza em silêncio). Escolhida: allowlist. 2: `"***"` impossibilita ver erro de correlação (certo); pseudônimo "traz a necessidade de gravar referência" (errado: hash com chave é de mão única, não guarda tabela). O risco real do pseudônimo: continua sendo dado pessoal pela LGPD (pseudonimizado não é anonimizado), CPF tem ~10⁹ valores (força bruta se a chave vaza ou não há chave), e traz gestão de chave. Decisão: placeholder **com o tipo** (`[masked:str]`, `[cpf]`), sem pseudônimo; perda de correlação aceita.
- `masking.py`: `MaskingSink(inner, policy)` embrulha qualquer `TraceSink` e entrega um trace mascarado (o original não é alterado). Três níveis por chave de atributo: `keep_keys` (passa: números, ids, `model`, `cost`...), `scrub_keys` (texto mantido; troca `[cpf]`, `[cnpj]`, `[email]`, `[phone]`, inclusive dentro de listas/dicts) e o resto vira `[masked:<tipo>]`. `Span.error` também é limpo (mensagem de exceção pode trazer dado). `request_id` não é mascarado: é a chave para achar o trace.
- Restrição que vem do passo 2, provada em teste: mascarar não pode tirar o que a checagem de fundamento precisa. `RefillFacts`/`ClosingFacts` reais passam intactos pelo scrub e continuam passando em `ungrounded_in`. Números de 10 e 12 dígitos não são tratados como CPF/CNPJ.
- Allowlist falha fechado tem o risco oposto: esquecer de classificar um atributo novo apaga informação do trace sem erro. `test_every_attribute_the_code_emits_is_classified` roda agent + narrate + job e falha se algum atributo emitido virou `[masked:`.
- Mutações (todas vermelhas, restauradas): chave desconhecida passando (4 falhas), padrão de CPF desligado (6), `outcome` fora da allowlist (1).
- **Chamada real** (Groq): CPF sintético na pergunta; o modelo recebe a pergunta como está, o arquivo de trace tem `CPF [cpf]` e nenhum CPF em lugar algum; tokens/custo e o texto final seguem legíveis e batem com o `AgentResult`.
- Limites: padrão em texto é melhor esforço (nome de pessoa e telefone sem formatação passam); `MaskingSink` ainda não é usado por padrão em lugar nenhum (nenhum ponto de entrada monta o sink): quem monta o sink pode esquecer de embrulhar.
- Decisão do autor (pergunta 2 de revisão): a política deve ser indexada por origem + chave (`tool.name`, `llm_call.model`), para que reusar uma chave em outro contexto não herde a liberação. Não implementada: muda o formato da política; fica para o passo 5, quando o sink de produção for montado.
- Dívida (pergunta 3): dado pessoal dentro de `facts` (ex.: nome de fornecedor/cliente em campo de texto) passa pelo scrub, que só conhece CPF/CNPJ/e-mail/telefone formatados. Fechamento: cada `Facts` declara os campos seguros para o trace e o resto vira `[masked:...]`; passo 5 ou fase 8.
- Perguntas de revisão do autor: (1) sem resposta (lacuna); vantagem = ponto único, risco = quem monta o sink; (2) composição origem.chave, ver decisão acima; (3) "se algum dado vier dentro de facts": certo, cenário e fechamento acima.

## Passo 5: comando que reconstrói a história de um `request_id`
- Previsão do autor, 1: "a última com warning; idempotência". Certa em parte: a última é a execução efetiva e o aviso é obrigatório; faltava que **as duas gastaram**. O aviso lista as linhas (com horário) e soma o custo de todas, senão o gasto da primeira some. Risco para a fase 7: uma reexecução barrada por idempotência pode gravar um trace curto "pulado" que esconde o trace que gastou; o aviso com a lista cobre isso. 2: **(A)** linha cortada derruba a consulta toda. Decisão do autor, implementada: nunca mostra trace pela metade. Custo assumido: uma linha cortada trava a consulta de **qualquer** `request_id`, inclusive em incidente. Agravante não tratado: `JsonlSink` abre em `"a"`; se a gravação anterior morreu antes do `\n`, o próximo trace cola na linha cortada e se perde junto. A mensagem de erro dá `arquivo:linha` e diz que a linha pode ser o trace procurado.
- `trace_report.py` (`python -m trace_report <request_id> [--file] [--full]`): `find_traces` lê o JSONL e valida cada linha com `TypeAdapter(Trace)` (JSON inválido **e** JSON que não é trace dão `CorruptTraceLine`); `render` monta a árvore pelos `parent_id` (órfão aparece como raiz); cabeçalho com chamadas, tokens e custo, "completo" ou "parcial: N chamada(s) sem preço". Sem `--full`: nome, status, duração e os atributos-resumo. Com `--full`: prompt, argumentos e resultados (já mascarados). Saída: 0 ok, 1 não encontrado (diz quantos traces leu), 2 arquivo ausente ou linha inválida.
- O custo vem do JSONL como texto (`default=str` do passo 1); `_revive_costs` volta para `Decimal` para reusar `job_cost` em vez de somar de outro jeito. Texto que não é número (ex.: `[masked:str]`) fica fora da soma e marca "parcial".
- Dívida do passo 4 fechada em parte: `masking.production_sink(path)` = `MaskingSink(JsonlSink(path))`, caminho padrão `traces/traces.jsonl` (no `.gitignore`: mascarado ainda é dado de execução). Nenhum ponto de entrada de produção existe, então "ninguém esquece de embrulhar" vale só por convenção até a fase 7. **Não feito**: política por origem + chave (decisão do autor no passo 4); fica para a fase 8.
- Mutações (todas vermelhas, restauradas): "última" -> primeira; linha inválida ignorada (`continue`); "completo" fixo.
- Teste fim a fim sem rede: grava com `production_sink`, lê com `find_traces`, confere que o CPF no arquivo não existe e que a saída traz `[cpf]` e o custo.
- Erros meus no caminho: (1) no primeiro rascunho dos testes havia um `assert ... or True` (passa sempre) e uma montagem de string com `.replace` para "chegar" no valor esperado; troquei por asserts diretos antes de rodar contra a mutação. (2) A indentação de `--full` ficou com barra dupla (`│  │`); simplificada depois de ver a saída real.
- **Chamada real** (Groq, `refill_job`, `request_id=real-3`, `production_sink`): `python -m trace_report`-equivalente (`main([...,"--full"])`) mostrou 2 `narrate` com `facts`, `system`, `content` do modelo, tokens 542→233, `custo=0.00022110 (completo)`; teste confere modelo, `prompt_version`, tokens e que cada justificativa do relatório aparece na história.
- Limites: `find_traces` lê o arquivo inteiro a cada consulta (ok no estudo; com milhares de traces precisa de índice por `request_id` ou de um sink em banco); a saída em `--full` pode ficar enorme com `facts` grandes; o comando só lê, então traces de execuções que morreram antes do `finally` não existem (já anotado no passo 1).
- Mutação extra (vermelha, restaurada): `cost` de texto virando `Decimal(0)` deixa 4 testes vermelhos.
- Perguntas de revisão do autor: (1) "a própria função de leitura; busca indexada ou chunking"; direção certa com ajuste: a leitura já é por linha (memória não é o gargalo), o custo é tempo O(n) e a validação Pydantic de cada linha; chunking sozinho não reduz leitura, o que reduz é índice `request_id -> offset` gravado **na escrita** (ou sink em banco), e isso reabre a decisão (A) de validar todas as linhas. (2) respondeu "completo; mantém a fidelidade"; **errado**: `[masked:str]` não é `Decimal`, conta como chamada sem preço e o cabeçalho diz "parcial". Dizer "completo" seria total sem origem confiável (regra do passo 3). Esse caso não tinha teste; `test_masked_cost_counts_as_unknown_not_complete` cobre agora. (3) sem resposta (lacuna): o trace ainda não responde "que prompt exato o modelo viu na retentativa do `narrate`?", "quais tool schemas e `temperature`/`reasoning_effort` foram enviados?" (lacunas abertas do passo 2) nem "o preço estava vigente?" se `prices.json` mudou com o processo vivo.
- Pendente para fechar a fase 4 (passo 6): chamada real ponta a ponta do agente com `production_sink` e leitura por `trace_report`, e decidir quais lacunas do passo 2 entram no trace (tool schemas e parâmetros do provedor).

## Passo 6: lacunas do trace fechadas + chamada real ponta a ponta (fecha a fase 4)
- Previsão do autor, 1: "groq/ desacoplamento". Lida como: quem grava os parâmetros do provedor é o `groq_client.py`, porque é o único que sabe quais são, e `agent`/`narrate` ficam sem conhecer `temperature` nem `reasoning_effort`. Direção certa. Mecanismo: `tracing.current_span()` (novo) + `groq_client._record_request(max_completion_tokens)` grava no span `llm_call` que quem chamou abriu; fora de um trace é no-op. Os valores viraram constantes (`REASONING_EFFORT`, `TEMPERATURE`) usadas **nos dois lados** (chamada ao SDK e trace): uma fonte só. Se a resposta quis dizer outra coisa, corrigir aqui. 2: "user entra; parâmetro no `llm_call`; schema uma vez no trace". Certo e igual à proposta; a pergunta sobre a máscara (campo novo esquecido) ficou sem resposta: ele vira `[masked:<tipo>]`, e `test_every_attribute_the_code_emits_is_classified` fica vermelho (agora também com os parâmetros do provedor).
- Mudanças: (1) `narrate`: o `llm_call` da retentativa guarda `user` (fatos + motivo da rejeição); na primeira tentativa não, porque são os fatos e já estão no span `narrate` (mesma regra de não copiar do passo 2). (2) `groq_client.py`: `temperature`, `reasoning_effort`, `max_completion_tokens` no `llm_call`, gravados **antes** da chamada (falha também foi enviada). (3) `agent`: `tools` (schemas) uma vez no span `agent`. (4) `masking`: `temperature`, `reasoning_effort`, `max_completion_tokens` em `keep_keys`; `tools` em `scrub_keys` (descrição fixa de código, legível).
- Testes: o do provedor compara o que o trace diz com os `kwargs` que o SDK realmente recebeu (fake em `chat.completions.create`), então constante errada num lado só fica vermelha; falha do provedor ainda registra os parâmetros; cliente sem trace ativo segue igual; `user` da retentativa == o que o `ScriptedClient` recebeu; schemas == o que `ScriptedChat` recebeu e não aparecem em `llm_call`.
- Mutações (todas vermelhas, restauradas): trace com `temperature=0.5` fixo; `temperature` fora da allowlist; `user` gravado sempre; `tools` fora do span `agent`; `_record_request` depois da chamada.
- **Chamada real** (Groq, agente com `low_stock`, `request_id=real-4`, `production_sink`, lido por `main([... "--full"])`): 2 chamadas, 915→151 tokens, `custo=0.00022785 (completo)`; saída traz `system`, `user`, os 3 schemas, `temperature: 0`, `reasoning_effort: low`, `max_completion_tokens: 1024` em cada `llm_call` e a tool `low_stock`. Primeira execução do teste falhou por expectativa minha (esperei `temperature=0` na linha-resumo; em `--full` é detalhe `temperature: 0`); a gravação estava certa, ajustei o teste.
- Suíte: 222 unitários (também sem `.env` e sem as variáveis), evals 80/80, basedpyright 0/0.
- **Fase 4 pronta?** Critério "explicar qualquer resposta a partir do trace": da resposta ao que o modelo recebeu (prompt, schemas, parâmetros, user da retentativa), à tool executada, ao tempo e ao custo, tudo por `request_id`. Não coberto: execução que morre antes do `finally` (trace só no fim), `narrate` com retentativa em chamada real (só simulado), `Usage` errado vindo do provedor, política de máscara por origem + chave, `facts` com dado pessoal em campo de texto (fase 8), índice por `request_id` (arquivo lido inteiro). O checkbox da fase 4 no guia é do autor.
- Limite novo: `--full` imprime os schemas inteiros (80 linhas só do `tools`); legível, mas ruidoso. Se incomodar, esconder `tools` atrás de `--tools`.
- Perguntas de revisão do autor: sem resposta ("segue"); lacuna registrada, não rebaixa o passo. Respostas de referência: (1) gravar antes preserva os parâmetros de uma chamada que falhou (timeout, 400, rate limit): é justo o run que se quer explicar; depois da chamada, só as bem-sucedidas teriam parâmetros. (2) Os fatos ficam uma vez no span `narrate`; os 3 textos enviados são `fatos` (tentativa 1, implícito) + o `user` de cada retentativa no seu `llm_call`; copiar os fatos em cada chamada repete o mesmo conteúdo N vezes sem informação nova (mesma regra do passo 2). (3) Exemplos: `prices.json` mudou com o processo vivo (só `prices_as_of`, que denuncia); o que o provedor fez por dentro (versão do modelo atrás do mesmo nome); `finish_reason=length` sem saber quanto do raciocínio consumiu o limite.

# Fase 5: extração do harness

## Passo 1: pacote `ai-harness`, `tracing` e `tools` (contexto genérico)
- Previsão do autor, 1: "visto" (válido). Cenário de referência: mover `tools.py` como estava faz o Legal herdar `psycopg` e uma `conn` que ele não tem; o harness passaria a exigir Postgres de quem só fala HTTP. 2: decidiu **conexão no contexto**, não em closure por tool: a tool não guarda dependência que não é dela. Lida como: o contexto é do pack (`ErpContext`) e o harness só o repassa. Correção: closure também é injeção de dependência (explícita); o custo real da escolha do autor é de **tipagem**: o registry precisa ser genérico no contexto (`ToolRegistry[C]`), senão a tool do ERP recebe um tipo sem `.conn`.
- Layout: `ai-harness/` (pacote `harness`, `src/` layout, `uv_build`) ao lado de `erp-assistant/`; o ERP depende por `[tool.uv.sources] ai-harness = { path = "../ai-harness", editable = true }`. Versionar por tag fica para o fim da fase, quando houver mais de um consumidor.
- Movido: `tracing.py` sem edição (já era folha pura) e `tools.py` com `Tool[C]`, `make_tool[C, InputT]`, `ToolRegistry[C]`. `ToolContext` e `connect_readonly` saíram para `erp-assistant/erp_context.py` (`ErpContext(conn, as_of)`). `run_agent` e `answer_question` ficaram genéricos em `C` (ainda no ERP; mudam de lugar num passo seguinte). Testes acompanharam: o teste de `tools` do harness usa um contexto sem banco (`_Ctx(tenant)`), que é a prova de que o harness aceita qualquer tipo; teste novo garante que a tool recebe o **mesmo objeto** de contexto.
- `tests/test_boundary.py` (harness): lê os imports (`ast`) de `src/harness` e falha se aparecer algo fora de stdlib, `pydantic` e `harness`. Mutação: `import psycopg` em `tools.py` deixa vermelho (`{'tools.py': ['psycopg']}`), restaurado.
- Erros meus no caminho: (1) o `basedpyright` do `ai-harness` varria o `erp-assistant`: o `pyrightconfig.json` da raiz (config de editor) vence o `pyproject`; resolvido com um `pyrightconfig.json` próprio no pacote, e a raiz passou a incluir os dois. (2) `uv_build` esperava o módulo `ai_harness`; precisou de `module-name = "harness"`. (3) A primeira tentativa de mutação não aplicou (o `sed` não casou) e a suíte ficou verde; só confiei no teste depois de ver a falha com a mensagem certa.
- Suíte: 204 unitários ERP + 20 harness (também sem `.env` e sem as variáveis), evals 80/80, basedpyright 0/0 nos dois pacotes. CI ganhou o job `ai-harness`.
- **Chamada real** (Groq + Postgres): `test_agent_integration.py`, `test_erp_tools.py`, `test_erp_context.py` passam (16) com `tools` e `tracing` vindos do pacote.
- Ainda no ERP e candidatos a mover: `pricing.py` (importa `extract.Usage`), `extract.py` (tem `StockMessage` de domínio junto do mecanismo de retry), `agent.py`, `narrate.py`, `validators.py`, `masking.py`, `trace_report.py`, `groq_client.py`. Vazamentos conhecidos: `extract.py` (schema `StockMessage`), caminho padrão `traces/traces.jsonl` em `masking`/`trace_report`, `ErpContext.as_of` (o Legal também vai precisar de "hoje"; decidir se vira campo do contexto do harness no passo do `RequestContext`).
- `RequestContext` (tenant, user, role, request_id) **não** entrou: o registry não precisa saber do contexto para funcionar, e o filtro por tenant é fase 8. Se entrar, é para o contexto do pack estender o do harness.
- Perguntas de revisão do autor: pendentes.
