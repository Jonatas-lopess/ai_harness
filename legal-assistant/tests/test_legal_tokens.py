from harness.validators import ungrounded_in
from pydantic import BaseModel

from legal_tokens import LEGAL_TOKENS, DateReader

CASE = "0001234-56.2024.8.26.0100"
SENTENCE = f"O prazo de contestação vence em 13/03/2026, no processo {CASE}."


class _Facts(BaseModel):
    kind: str
    due_date: str  # ISO, como a tool devolve
    case_number: str


FACTS = _Facts(kind="contestação", due_date="2026-03-13", case_number=CASE)


def test_a_date_and_a_case_number_are_one_token_each_not_their_pieces() -> None:
    assert [t.text for t in LEGAL_TOKENS.find(SENTENCE)] == ["13/03/2026", CASE]


def test_the_sentence_with_the_record_values_is_grounded() -> None:
    assert ungrounded_in(SENTENCE, FACTS, LEGAL_TOKENS) == []


def test_the_iso_form_in_the_text_is_the_same_date() -> None:
    assert ungrounded_in("Vence em 2026-03-13.", FACTS, LEGAL_TOKENS) == []


def test_another_date_is_rejected() -> None:
    assert ungrounded_in(SENTENCE.replace("13/03", "14/03"), FACTS, LEGAL_TOKENS) == ["14/03/2026"]


def test_day_and_month_swapped_is_rejected_and_does_not_crash() -> None:
    swapped = SENTENCE.replace("13/03/2026", "03/13/2026")

    assert ungrounded_in(swapped, FACTS, LEGAL_TOKENS) == ["03/13/2026"]


def test_an_impossible_date_has_no_value() -> None:
    (token,) = DateReader().find("Vence em 31/02/2026.")

    assert token.values == frozenset()


def test_a_case_number_with_one_wrong_digit_is_rejected() -> None:
    wrong = SENTENCE.replace("0100", "0101")

    assert ungrounded_in(wrong, FACTS, LEGAL_TOKENS) == [CASE.replace("0100", "0101")]


def test_a_number_the_model_derived_is_rejected() -> None:
    # A tool não devolveu "faltam 3 dias": quem calcula é o código, e o texto não pode inventar.
    text = SENTENCE + " Faltam 3 dias."

    assert ungrounded_in(text, FACTS, LEGAL_TOKENS) == ["3"]


def test_a_quantity_never_grounds_a_date() -> None:
    class _Quantity(BaseModel):
        total: int

    assert ungrounded_in("Vence em 13/03/2026.", _Quantity(total=20260313), LEGAL_TOKENS) == ["13/03/2026"]


def test_a_date_without_year_is_not_silently_accepted() -> None:
    # "13/03" não é data completa: os dois inteiros soltos não estão nos fatos.
    assert ungrounded_in("Vence em 13/03.", FACTS, LEGAL_TOKENS) == ["13", "03"]


def test_a_quantity_never_grounds_a_case_number() -> None:
    class _Quantity(BaseModel):
        total: int

    digits = int(CASE.replace("-", "").replace(".", ""))

    assert ungrounded_in(f"Processo {CASE}.", _Quantity(total=digits), LEGAL_TOKENS) == [CASE]
