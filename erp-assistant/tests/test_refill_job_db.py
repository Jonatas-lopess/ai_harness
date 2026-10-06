import json
from datetime import date
from typing import cast, final

from pytest import mark

from extract import Completion, Usage
from refill_job import PROMPT_VERSION, run_refill_job
from settings import get_settings
from tests.test_refill_job import ScriptedClient
from tools import connect_readonly

AS_OF = date(2026, 1, 31)
USAGE = Usage(prompt_tokens=10, completion_tokens=5)

pytestmark = mark.integration


class _Echo:
    """Escreve uma justificativa válida para qualquer item: cita só o `suggested_qty` dos fatos."""

    def complete(self, **kwargs: object) -> Completion:
        facts = cast(dict[str, int], json.loads(str(kwargs["user"]).split("\n")[0]))
        return Completion(
            json.dumps({"rationale": f"Repor {facts['suggested_qty']} un."}), "stop", usage=USAGE
        )


@final
class _Chain:
    """Usa o primeiro cliente enquanto ele tiver respostas; depois o segundo."""

    def __init__(self, first: ScriptedClient, then: _Echo) -> None:
        self.first: ScriptedClient = first
        self.then: _Echo = then

    def complete(self, **kwargs: object) -> Completion:
        if self.first.completions:
            return self.first.complete(**kwargs)
        return self.then.complete(**kwargs)


def test_job_attaches_code_quantities_and_orders_by_priority() -> None:
    with connect_readonly(get_settings().database_url.get_secret_value()) as conn:
        report = run_refill_job(_Echo(), conn, AS_OF, model="m")

    assert [i.suggested_qty for i in report.items] == sorted(
        (i.suggested_qty for i in report.items), reverse=True
    )
    assert {i.suggested_qty for i in report.items} >= {250, 240}
    assert all(i.rationale == f"Repor {i.suggested_qty} un." for i in report.items)
    assert report.prompt_version == PROMPT_VERSION
    assert report.usage == Usage(10 * len(report.items), 5 * len(report.items))


def test_one_bad_item_does_not_sink_the_others() -> None:
    bad = Completion('{"rationale": "Repor 9999."}', "stop", usage=USAGE)
    with connect_readonly(get_settings().database_url.get_secret_value()) as conn:
        first = ScriptedClient(bad, bad, bad)  # primeiro item reprova nas 3 tentativas
        report = run_refill_job(_Chain(first, _Echo()), conn, AS_OF, model="m")

    assert report.items[0].rationale is None
    assert report.items[0].rationale_error is not None
    assert report.items[0].suggested_qty > 0  # quantidade do código segue valendo
    assert all(i.rationale is not None for i in report.items[1:])
