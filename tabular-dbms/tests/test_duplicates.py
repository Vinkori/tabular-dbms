"""Перевірки індивідуальної операції вилучення повторюваних рядків."""

import math

import pytest

from backend.domain.data_types import get_data_type
from backend.domain.errors import DomainNotFoundError
from backend.domain.models import Column, Database, Table


def make_single_column(kind):
    return Table("Values", [Column("value", get_data_type(kind))])


@pytest.fixture
def samples():
    schema = [
        ("number", "integer"), ("score", "real"), ("mark", "char"),
        ("title", "string"), ("shade", "color"), ("range", "colorInvl"),
    ]
    table = Table("Samples", [Column(name, get_data_type(kind)) for name, kind in schema])
    values = {
        "number": 1, "score": 95.5, "mark": "A", "title": "Anna",
        "shade": {"red": 255, "green": 0, "blue": 0},
        "range": {
            "start": {"red": 0, "green": 0, "blue": 0},
            "end": {"red": 100, "green": 150, "blue": 200},
        },
    }
    return table, values


def test_all_types_key_and_first_uuid(samples):
    table, values = samples
    first = table.add_row(values)
    second = table.add_row({**values, "title": "Bob"})
    duplicate = table.add_row(values)
    stored_first = table.rows[0]
    assert first.id != duplicate.id
    assert first.canonical_key(table.columns) == (
        1, 95.5, "A", "Anna", (255, 0, 0), ((0, 0, 0), (100, 150, 200))
    )
    assert first.canonical_key(table.columns) == duplicate.canonical_key(table.columns)
    assert table.remove_duplicates() == 1
    assert table.get_rows() == [first, second]
    assert table.rows[0] is stored_first
    assert table.remove_duplicates() == 0
    assert table.get_rows() == [first, second]


@pytest.mark.parametrize("kind,first_raw,second_raw", [
    ("integer", " +001 ", 1),
    ("real", "1e0", 1),
    ("char", " ", " "),
    ("string", "", ""),
    ("color", {"red": 1, "green": 2, "blue": 3},
     {"blue": 3, "red": 1, "green": 2}),
    ("colorInvl",
     {"start": {"red": 1, "green": 2, "blue": 3},
      "end": {"red": 1, "green": 2, "blue": 3}},
     {"end": {"blue": 3, "green": 2, "red": 1},
      "start": {"blue": 3, "green": 2, "red": 1}}),
])
def test_duplicates_after_normalization(kind, first_raw, second_raw):
    table = make_single_column(kind)
    first = table.add_row({"value": first_raw})
    table.add_row({"value": second_raw})
    assert table.remove_duplicates() == 1
    assert table.get_rows() == [first]


@pytest.mark.parametrize("field_name,different", [
    ("number", 2), ("score", 95.6), ("mark", "B"), ("title", "anna"),
    ("shade", {"red": 254, "green": 0, "blue": 0}),
    ("range", {"start": {"red": 0, "green": 0, "blue": 0},
               "end": {"red": 100, "green": 150, "blue": 201}}),
])
def test_difference_in_any_column_keeps_both(samples, field_name, different):
    table, values = samples
    first = table.add_row(values)
    second = table.add_row({**values, field_name: different})
    assert table.remove_duplicates() == 0
    assert table.get_rows() == [first, second]


@pytest.mark.parametrize("items,remaining", [
    ([], []),
    ([7], [7]),
    ([3, 1, 2], [3, 1, 2]),
    ([7, 7, 7, 7], [7]),
    ([3, 1, 3, 2, 1, 2], [3, 1, 2]),
])
def test_counts_order_and_repeated_execution(items, remaining):
    table = make_single_column("integer")
    first_ids = {}
    for value in items:
        row = table.add_row({"value": value})
        first_ids.setdefault(value, row.id)
    assert table.remove_duplicates() == len(items) - len(remaining)
    rows = table.get_rows()
    assert [row.get_value("value") for row in rows] == remaining
    assert [row.id for row in rows] == [first_ids[value] for value in remaining]
    assert table.remove_duplicates() == 0
    assert table.get_rows() == rows


def test_key_uses_schema_order_not_dictionary_order():
    table = Table("Order", [
        Column("b", get_data_type("string")),
        Column("a", get_data_type("string")),
    ])
    first = table.add_row({"a": "A", "b": "B"})
    table.add_row({"b": "B", "a": "A"})
    snapshot = table.get_rows()[0]
    snapshot.values.clear()
    snapshot.values.update({"a": "A", "b": "B"})
    assert snapshot.canonical_key(table.columns) == ("B", "A")
    assert table.remove_duplicates() == 1
    assert table.get_rows() == [first]


def test_user_id_column_participates_in_comparison():
    table = Table("User IDs", [
        Column("id", get_data_type("integer")),
        Column("name", get_data_type("string")),
    ])
    first = table.add_row({"id": 1, "name": "Anna"})
    second = table.add_row({"id": 2, "name": "Anna"})
    table.add_row({"id": "1", "name": "Anna"})
    assert table.remove_duplicates() == 1
    assert table.get_rows() == [first, second]


def test_strings_preserve_case_and_spaces():
    table = make_single_column("string")
    expected = [table.add_row({"value": value}) for value in ["Anna", "anna", "Anna "]]
    table.add_row({"value": "Anna"})
    assert table.remove_duplicates() == 1
    assert table.get_rows() == expected


def test_real_comparison_is_exact_and_signed_zero_is_equal():
    table = make_single_column("real")
    first = table.add_row({"value": -0.0})
    table.add_row({"value": 0.0})
    second = table.add_row({"value": 0.1 + 0.2})
    third = table.add_row({"value": 0.3})
    table.add_row({"value": "0.3"})
    assert table.remove_duplicates() == 2
    assert table.get_rows() == [first, second, third]
    assert math.copysign(1.0, table.get_rows()[0].get_value("value")) == -1.0


def test_hash_collision_does_not_remove_different_values():
    table = make_single_column("integer")
    first = table.add_row({"value": -1})
    second = table.add_row({"value": -2})
    table.add_row({"value": -1})
    first_key = first.canonical_key(table.columns)
    second_key = second.canonical_key(table.columns)
    assert hash(first_key) == hash(second_key)
    assert first_key != second_key
    assert table.remove_duplicates() == 1
    assert table.get_rows() == [first, second]


def test_editing_can_create_duplicate_and_removed_uuid_is_not_found():
    table = make_single_column("string")
    first = table.add_row({"value": "Anna"})
    second = table.add_row({"value": "Bob"})
    table.update_row(second.id, {"value": "Anna"})
    assert table.remove_duplicates() == 1
    assert table.get_rows() == [first]
    with pytest.raises(DomainNotFoundError):
        table.update_row(second.id, {"value": "Bob"})
    table.add_row({"value": "Anna"})
    assert table.remove_duplicates() == 1
    assert table.get_rows() == [first]


def test_operation_changes_only_selected_table():
    db = Database("Demo")
    first = make_single_column("integer")
    second = Table("Other", [Column("value", get_data_type("integer"))])
    db.add_table(first)
    db.add_table(second)
    for table in (first, second):
        table.add_row({"value": 1})
        table.add_row({"value": 1})
    columns_before = first.columns.copy()
    other_before = second.get_rows()
    assert db.find_table(first.id).remove_duplicates() == 1
    assert first.columns == columns_before
    assert second.get_rows() == other_before
    assert list(db.tables) == [first.id, second.id]
