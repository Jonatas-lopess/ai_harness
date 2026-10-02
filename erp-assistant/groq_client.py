from typing import Any

from groq import BadRequestError, Groq

from extract import Completion, InvalidOutputError, Usage

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


class GroqClient:
    """Adaptador: traduz a resposta do SDK do Groq para o `Completion` do harness."""

    def __init__(self, api_key: str) -> None:
        self._client: Groq = Groq(api_key=api_key)

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        response_schema: dict[str, Any],  # pyright: ignore[reportExplicitAny]
        max_completion_tokens: int,
    ) -> Completion:
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                reasoning_effort="low",
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "output", "strict": True, "schema": response_schema},
                },
                max_completion_tokens=max_completion_tokens,
                temperature=0,
            )
        except BadRequestError as exc:
            # No modo strict o servidor rejeita (HTTP 400) saída truncada ou fora do schema.
            # Sem `usage`: erro HTTP não traz contagem de tokens.
            if _error_code(exc) == JSON_VALIDATE_FAILED:
                raise InvalidOutputError("provider rejected output (truncated or invalid JSON)") from exc
            raise

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
