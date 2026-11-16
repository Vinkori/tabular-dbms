"""Перевірки схеми, таблиць і атомарних змін рядків."""

from uuid import UUID, uuid4

import pytest

from backend.domain.colors import Color, ColorInterval
from backend.domain.data_types import get_data_type
from backend.domain.errors import (
    DomainConflictError,
    DomainNotFoundError,
    DomainValidationError,
)
from backend.domain.models import Column, Database, Row, Table


def make_table(name="Samples", **kwargs):
    schema = [
        ("number", "integer"), ("score", "real"), ("mark", "char"),
        ("title", "string"), ("shade", "color"), ("range", "colorInvl"),
    ]
    return Table(
        name=name,
        columns=[Column(name, get_data_type(kind)) for name, kind in schema],
        **kwargs,
    )


@pytest.fixture
def values():
    return {
        "number": "1", "score": "95.5", "mark": "A", "title": " Anna ",
        "shade": {"red": 255, "green": 0, "blue": 0},
        "range": {
            "start": {"red": 0, "green": 0, "blue": 0},
            "end": {"red": 100, "green": 150, "blue": 200},
        },
    }


@pytest.mark.parametrize("bad", ["", " \t\n", None, 123, True])
@pytest.mark.parametrize("kind", ["database", "table", "column"])
def test_invalid_names(kind, bad):
    with pytest.raises(DomainValidationError):
        if kind == "database":
            Database(bad)
        elif kind == "table":
            make_table(bad)
        else:
            Column(bad, get_data_type("string"))


def test_names_are_trimmed_and_case_sensitive():
    db = Database(" Demo ")
    first = Table(" People ", [Column(" name ", get_data_type("string"))])
    second = Table("people", [Column("Name", get_data_type("string"))])
    db.add_table(first)
    db.add_table(second)
    assert db.name == "Demo"
    assert first.name == "People"
    assert first.columns[0].name == "name"
    assert len(db.tables) == 2
    first.add_row({"name": " Anna "})
    assert first.get_rows()[0].get_value("name") == " Anna "
    assert Database("Demo").id != db.id
    Table("Case", [Column("A", get_data_type("string")), Column("a", get_data_type("string"))])


def test_invalid_schema_and_registered_type():
    with pytest.raises(DomainValidationError):
        Table("Empty", [])
    with pytest.raises(DomainValidationError):
        Table("Wrong", ["name"])
    with pytest.raises(DomainValidationError):
        Column("x", "integer")
    with pytest.raises(DomainValidationError):
        Column("x", object())
    with pytest.raises(DomainValidationError):
        Table("Duplicate", [Column("x", get_data_type("integer")), Column(" x ", get_data_type("real"))])
    first = Column("x", get_data_type("integer"))
    with pytest.raises(DomainValidationError):
        Table("Duplicate UUID", [first, Column("y", get_data_type("integer"), id=first.id)])


def test_column_delegates_and_reports_column_name():
    column = Column("shade", get_data_type("color"))
    assert column.validate({"red": 0, "green": 1, "blue": 2})
    value = column.normalize({"red": 0, "green": 1, "blue": 2})
    assert column.canonicalize(value) == (0, 1, 2)
    with pytest.raises(DomainValidationError) as error:
        column.normalize({"red": 256, "green": 1, "blue": 2})
    assert error.value.field == "shade"


def test_add_column_only_during_construction():
    table = Table("Draft", [Column("a", get_data_type("string"))])
    table.add_column(Column("b", get_data_type("integer")))
    before = table.columns.copy()
    with pytest.raises(DomainValidationError):
        table.add_column(Column(" a ", get_data_type("string")))
    assert table.columns == before
    Database("Demo").add_table(table)
    with pytest.raises(DomainValidationError):
        table.add_column(Column("c", get_data_type("string")))
    assert table.columns == before


def test_first_successful_row_locks_schema():
    table = Table("Draft", [Column("a", get_data_type("integer"))])
    with pytest.raises(DomainValidationError):
        table.add_row({"a": "bad"})
    table.add_column(Column("b", get_data_type("string")))
    table.add_row({"a": 1, "b": ""})
    with pytest.raises(DomainValidationError):
        table.add_column(Column("c", get_data_type("string")))


def test_database_add_find_remove_and_conflicts():
    db = Database("Demo")
    first, second = make_table("First"), make_table("Second")
    db.add_table(first)
    db.add_table(second)
    assert db.find_table(first.id) is first
    assert list(db.tables) == [first.id, second.id]
    for conflicting in [first, make_table(" First "), make_table("Other", id=first.id)]:
        with pytest.raises(DomainConflictError):
            db.add_table(conflicting)
        assert list(db.tables) == [first.id, second.id]
    other_db = Database("Other")
    with pytest.raises(DomainConflictError):
        other_db.add_table(first)
    assert other_db.tables == {}
    db.remove_table(first.id)
    assert list(db.tables) == [second.id]
    with pytest.raises(DomainNotFoundError):
        db.find_table(first.id)
    with pytest.raises(DomainNotFoundError):
        db.remove_table(first.id)
    with pytest.raises(DomainValidationError):
        db.add_table("table")


def test_add_read_normalizes_all_types_and_keeps_order(values):
    table = make_table()
    assert table.get_rows() == []
    first = table.add_row(values)
    second = table.add_row(values)
    assert isinstance(first.id, UUID)
    assert first.id != second.id
    assert [row.id for row in table.get_rows()] == [first.id, second.id]
    assert first.values == {
        "number": 1, "score": 95.5, "mark": "A", "title": " Anna ",
        "shade": Color(255, 0, 0),
        "range": ColorInterval(Color(0, 0, 0), Color(100, 150, 200)),
    }
    assert type(first.get_value("score")) is float
    assert list(first.values) == [column.name for column in table.columns]
    with pytest.raises(DomainNotFoundError):
        first.get_value("missing")


@pytest.mark.parametrize("bad", [None, [], {}, {"number": 1}])
def test_invalid_row_shape(bad):
    table = make_table()
    with pytest.raises(DomainValidationError):
        table.add_row(bad)
    assert table.get_rows() == []


def test_extra_field_rejected(values):
    table = make_table()
    values["extra"] = "value"
    with pytest.raises(DomainValidationError):
        table.add_row(values)
    assert table.get_rows() == []


@pytest.mark.parametrize("field_name,bad", [
    ("number", True), ("score", "NaN"), ("mark", "AB"), ("title", 12),
    ("shade", {"red": -1, "green": 0, "blue": 0}),
    ("range", {"start": {"red": 2, "green": 0, "blue": 0},
               "end": {"red": 1, "green": 0, "blue": 0}}),
] + [(name, None) for name in ["number", "score", "mark", "title", "shade", "range"]])
def test_bad_values_do_not_change_table(values, field_name, bad):
    table = make_table()
    original = table.add_row(values)
    before = table.get_rows()
    with pytest.raises(DomainValidationError):
        table.add_row({**values, field_name: bad})
    with pytest.raises(DomainValidationError):
        table.update_row(original.id, {"title": "Changed", field_name: bad})
    assert table.get_rows() == before


def test_partial_update_preserves_uuid_position_and_other_fields(values):
    table = make_table()
    first, second = table.add_row(values), table.add_row(values)
    updates = {"number": " +002 ", "title": "", "mark": " "}
    updated = table.update_row(first.id, updates)
    assert updated.id == first.id
    assert updated.values == {**first.values, "number": 2, "title": "", "mark": " "}
    assert [row.id for row in table.get_rows()] == [first.id, second.id]
    assert table.get_rows()[1] == second
    assert updates["number"] == " +002 "
    assert first.get_value("number") == 1


@pytest.mark.parametrize("updates", [{}, None, [], {"missing": 1}])
def test_invalid_updates_leave_row_unchanged(values, updates):
    table = make_table()
    row = table.add_row(values)
    with pytest.raises(DomainValidationError):
        table.update_row(row.id, updates)
    assert table.get_rows() == [row]


def test_unknown_row_and_uuid_validation(values):
    table = make_table()
    row = table.add_row(values)
    with pytest.raises(DomainNotFoundError):
        table.update_row(uuid4(), {"title": "Changed"})
    with pytest.raises(DomainValidationError):
        table.update_row(str(row.id), {"title": "Changed"})
    with pytest.raises(DomainValidationError):
        Database("Demo").find_table("invalid")
    assert table.get_rows() == [row]


def test_copies_prevent_accidental_changes(values):
    table = make_table()
    row = table.add_row(values)
    values["shade"]["red"] = 0
    row.values["title"] = "Changed outside"
    snapshot = table.get_rows()
    snapshot[0].values["number"] = 999
    snapshot.clear()
    assert table.get_rows()[0].get_value("title") == " Anna "
    assert table.get_rows()[0].get_value("number") == 1
    assert table.get_rows()[0].get_value("shade") == Color(255, 0, 0)
    updated = table.update_row(row.id, {"title": "Bob"})
    updated.values["title"] = "Outside again"
    assert table.get_rows()[0].get_value("title") == "Bob"


def test_constructor_restores_rows_and_copies_collections(values):
    row = Row(values, id=uuid4())
    rows = [row]
    columns = make_table().columns
    table = Table("Restored", columns, rows=rows)
    rows.clear()
    columns.clear()
    row.values["number"] = "wrong"
    assert len(table.columns) == 6
    assert table.get_rows()[0].id == row.id
    assert table.get_rows()[0].get_value("number") == 1
    with pytest.raises(DomainValidationError):
        table.add_column(Column("x", get_data_type("string")))


def test_constructor_rejects_invalid_or_duplicate_rows(values):
    row = Row(values)
    for rows in [None, ["bad"], [row, row], [Row({"number": 1})]]:
        with pytest.raises(DomainValidationError):
            make_table(rows=rows)
    with pytest.raises(DomainValidationError):
        Row([])
    with pytest.raises(DomainValidationError):
        Row({1: "bad"})


@pytest.mark.parametrize("kind", ["database", "table", "column", "row"])
def test_constructor_rejects_string_uuid(kind):
    invalid_id = str(uuid4())
    with pytest.raises(DomainValidationError):
        if kind == "database":
            Database("Demo", id=invalid_id)
        elif kind == "table":
            make_table(id=invalid_id)
        elif kind == "column":
            Column("x", get_data_type("integer"), id=invalid_id)
        else:
            Row({"x": 1}, id=invalid_id)


def test_user_column_named_id_is_not_internal_uuid():
    table = Table("IDs", [Column("id", get_data_type("string"))])
    row = table.add_row({"id": "user-id"})
    updated = table.update_row(row.id, {"id": "new-user-id"})
    assert updated.id == row.id
    assert updated.get_value("id") == "new-user-id"


def test_default_collections_are_independent():
    first_db, second_db = Database("Same"), Database("Same")
    first, second = make_table(), make_table()
    first_db.add_table(first)
    assert second_db.tables == {}
    assert first.rows is not second.rows
