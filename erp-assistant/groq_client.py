from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Any

from groq import (
    APIConnectionError,
    AsyncGroq,
    BadRequestError,
    Groq,
    InternalServerError,
    RateLimitError,
)
from groq.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from groq.types.chat.completion_create_params import (
    ResponseFormatResponseFormatJsonSchema,
)

from agent import (
    AssistantMessage,
    ChatResponse,
    Message,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from extract import Completion, InvalidOutputError, ProviderUnavailableError, Usage
from tools import ToolSchema

JSON_VALIDATE_FAILED = "json_validate_failed"


def _error_code(exc: BadRequestError) -> str | None:
    """Extrai `error.code` do corpo do 400, que o SDK entrega como `object | None`."""
    body = exc.body
    if not isinstance(body, dict):
        return None
    error = body.get("error")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(error, dict):
        return None
    code = error.get("code")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return code if isinstance(code, str) else None


def _messages(system: str, user: str) -> list[ChatCompletionMessageParam]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _chat_messages(system: str, messages: Sequence[Message]) -> list[ChatCompletionMessageParam]:
    params: list[ChatCompletionMessageParam] = [{"role": "system", "content": system}]
    for message in messages:
        match message:
            case UserMessage():
                params.append({"role": "user", "content": message.content})
            case AssistantMessage():
                params.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {"name": c.name, "arguments": c.arguments},
                            }
                            for c in message.tool_calls
                        ],
                    }
                )
            case ToolMessage():
                params.append({"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content})
    return params


def _tool_params(tools: Sequence[ToolSchema]) -> list[ChatCompletionToolParam]:
    return [
        {
            "type": "function",
            "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]},
        }
        for t in tools
    ]


def _to_chat_response(response: ChatCompletion) -> ChatResponse:
    choice = response.choices[0]
    usage = (
        Usage(response.usage.prompt_tokens, response.usage.completion_tokens)
        if response.usage is not None
        else None
    )
    calls = tuple(
        ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments)
        for c in choice.message.tool_calls or []
    )
    return ChatResponse(AssistantMessage(choice.message.content, calls), choice.finish_reason, usage)


def _response_format(
    schema: dict[str, Any],  # pyright: ignore[reportExplicitAny]
) -> ResponseFormatResponseFormatJsonSchema:
    return {"type": "json_schema", "json_schema": {"name": "output", "strict": True, "schema": schema}}


@contextmanager
def _translate_errors() -> Generator[None]:
    """Traduz erros do SDK para os do harness. Serve em código síncrono e em `await`."""
    try:
        yield
    except BadRequestError as exc:
        # No modo strict o servidor rejeita (HTTP 400) saída truncada ou fora do schema.
        # Sem `usage`: erro HTTP não traz contagem de tokens.
        if _error_code(exc) == JSON_VALIDATE_FAILED:
            raise InvalidOutputError("provider rejected output (truncated or invalid JSON)") from exc
        raise
    except (RateLimitError, InternalServerError, APIConnectionError) as exc:
        # Chegou aqui = retries do SDK esgotados. `APITimeoutError` é subclasse de `APIConnectionError`.
        # Sem `usage`: o custo desta chamada é desconhecido (timeout pode ter sido cobrado).
        raise ProviderUnavailableError(f"provider unavailable: {type(exc).__name__}") from exc


def _to_completion(response: ChatCompletion) -> Completion:
    choice = response.choices[0]
    usage = (
        Usage(response.usage.prompt_tokens, response.usage.completion_tokens)
        if response.usage is not None
        else None
    )
    # O SDK do Groq não expõe `refusal` na mensagem: aqui nunca há recusa explícita.
    return Completion(
        content=choice.message.content,
        finish_reason=choice.finish_reason,
        usage=usage,
    )


class GroqClient:
    """Adaptador: traduz a resposta do SDK do Groq para o `Completion` do harness."""

    def __init__(self, api_key: str, *, max_retries: int = 2, timeout: float = 60.0) -> None:
        # O SDK faz backoff exponencial com jitter (e honra `Retry-After`) em 408/409/429/5xx,
        # falha de conexão e timeout. Aqui só fixamos os limites; não reimplementamos o backoff.
        self._client: Groq = Groq(api_key=api_key, max_retries=max_retries, timeout=timeout)

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        response_schema: dict[str, Any],  # pyright: ignore[reportExplicitAny]
        max_completion_tokens: int,
    ) -> Completion:
        with _translate_errors():
            response = self._client.chat.completions.create(
                model=model,
                messages=_messages(system, user),
                reasoning_effort="low",
                response_format=_response_format(response_schema),
                max_completion_tokens=max_completion_tokens,
                temperature=0,
            )
        return _to_completion(response)

    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_completion_tokens: int,
    ) -> ChatResponse:
        with _translate_errors():
            response = self._client.chat.completions.create(
                model=model,
                messages=_chat_messages(system, messages),
                tools=_tool_params(tools),
                reasoning_effort="low",
                max_completion_tokens=max_completion_tokens,
                temperature=0,
            )
        return _to_chat_response(response)


class AsyncGroqClient:
    """Mesmo adaptador, com `AsyncGroq`: `await` cede o event loop em vez de travá-lo."""

    def __init__(self, api_key: str, *, max_retries: int = 2, timeout: float = 60.0) -> None:
        self._client: AsyncGroq = AsyncGroq(api_key=api_key, max_retries=max_retries, timeout=timeout)

    async def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        response_schema: dict[str, Any],  # pyright: ignore[reportExplicitAny]
        max_completion_tokens: int,
    ) -> Completion:
        with _translate_errors():
            response = await self._client.chat.completions.create(
                model=model,
                messages=_messages(system, user),
                reasoning_effort="low",
                response_format=_response_format(response_schema),
                max_completion_tokens=max_completion_tokens,
                temperature=0,
            )
        return _to_completion(response)
