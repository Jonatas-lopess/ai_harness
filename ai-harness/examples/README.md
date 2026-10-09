# examples

`toy_pack/pack.py` is a complete minimal domain pack (a helpdesk) that uses the harness through `harness.*` only.
Read it top to bottom to see what a new pack has to provide: a context type, tools, a `NumberReader`, a prompt that
includes `STATUS_PROTOCOL`, a price table, a job that composes `answer_question` + `narrate` inside `costed_span`,
and eval suites for the runner.

It is not shipped in the wheel. `tests/test_toy_pack.py` runs it and shows what happens when a pack forgets a piece.
