from harness.agent import ToolCallRecord
from erp_tools import LowStockItem, LowStockOutput
from erp_numbers import ERP_NUMBERS
from harness.validators import ungrounded_numbers


def _low_stock(*items: tuple[int, str, int]) -> ToolCallRecord:
    return ToolCallRecord(
        name="low_stock",
        arguments="{}",
        result=LowStockOutput(
            items=[
                LowStockItem(
                    product_id=pid,
                    name=name,
                    on_hand=3,
                    open_po_qty=0,
                    reorder_point=40,
                    suggested_qty=qty,
                )
                for pid, name, qty in items
            ],
            total=len(items),
            total_suggested_qty=sum(q for _, _, q in items),
            truncated=False,
        ),
    )


# SKUs "A12"/"B07" têm dígitos de propósito: não podem servir de origem para "12" ou "07".
RECORDS = [_low_stock((1, "A12", 250), (2, "B07", 240))]


def test_text_with_only_tool_numbers_passes() -> None:
    assert ungrounded_numbers("Repor 250 un. de A12 e 240 un. de B07.", RECORDS, ERP_NUMBERS) == []


def test_wrong_digit_is_flagged() -> None:
    assert ungrounded_numbers("Repor 250 un. de A12 e 245 un. de B07.", RECORDS, ERP_NUMBERS) == ["245"]


def test_total_computed_by_tool_passes() -> None:
    assert ungrounded_numbers("Repor 490 un. no total.", RECORDS, ERP_NUMBERS) == []


def test_total_computed_by_model_is_flagged() -> None:
    assert ungrounded_numbers("Repor 500 un. no total.", RECORDS, ERP_NUMBERS) == ["500"]


def test_digits_inside_identifier_are_not_numbers() -> None:
    assert ungrounded_numbers("Repor A12 e B07.", RECORDS, ERP_NUMBERS) == []


def test_identifier_digits_do_not_ground_a_made_up_number() -> None:
    # "12" vem do SKU A12, não de um número da tool: inventar "12 dias" tem que reprovar.
    assert ungrounded_numbers("Chega em 12 dias.", RECORDS, ERP_NUMBERS) == ["12"]


def test_thousands_separator_matches_value() -> None:
    records = [_low_stock((1, "A12", 1250))]
    assert ungrounded_numbers("Repor 1.250 un. de A12.", records, ERP_NUMBERS) == []
    assert ungrounded_numbers("Repor 1250 un. de A12.", records, ERP_NUMBERS) == []
    assert ungrounded_numbers("Repor 1,250 un. de A12.", records, ERP_NUMBERS) == []


def test_thousands_separator_does_not_match_other_value() -> None:
    assert ungrounded_numbers("Repor 1.250 un. de A12.", RECORDS, ERP_NUMBERS) == ["1.250"]


def test_decimal_comma_matches_decimal_value() -> None:
    records = [_low_stock((1, "A12", 250))]
    assert ungrounded_numbers("Margem de 250,0.", records, ERP_NUMBERS) == []


def test_sentence_period_is_not_part_of_number() -> None:
    assert ungrounded_numbers("Total: 250.", RECORDS, ERP_NUMBERS) == []


def test_numbers_from_several_tool_calls_are_all_allowed() -> None:
    records = [*RECORDS, _low_stock((3, "C99", 77))]
    assert ungrounded_numbers("Repor 77 un. de C99 e 250 un. de A12.", records, ERP_NUMBERS) == []


def test_no_tool_calls_means_any_number_is_flagged() -> None:
    assert ungrounded_numbers("Repor 250 un.", [], ERP_NUMBERS) == ["250"]


def test_text_without_numbers_passes() -> None:
    assert ungrounded_numbers("Nada a repor hoje.", RECORDS, ERP_NUMBERS) == []
