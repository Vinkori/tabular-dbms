"""База, таблиця, колонка і рядок; без мережі та файлового сховища."""

from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from backend.domain.data_types import DataType, TYPE_REGISTRY
from backend.domain.errors import (
    DomainConflictError,
    DomainNotFoundError,
    DomainValidationError,
)


def _normalize_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError("Назва має бути непорожнім текстом", "name")
    return value.strip()


def _check_uuid(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise DomainValidationError("Ідентифікатор має бути об'єктом UUID", "id")


@dataclass(frozen=True)
class Column:
    name: str
    data_type: DataType
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_name(self.name))
        _check_uuid(self.id)
        if type(self.data_type) not in TYPE_REGISTRY.values():
            raise DomainValidationError("Тип колонки відсутній у реєстрі", self.name)

    def validate(self, raw_value: Any) -> bool:
        return self.data_type.validate(raw_value)

    def normalize(self, raw_value: Any) -> Any:
        try:
            return self.data_type.normalize(raw_value)
        except DomainValidationError as error:
            raise DomainValidationError(
                f"Колонка «{self.name}»: {error.message}", self.name
            ) from error

    def canonicalize(self, value: Any) -> Hashable:
        return self.data_type.canonicalize(value)


@dataclass(frozen=True)
class Row:
    values: dict[str, Any]
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _check_uuid(self.id)
        if not isinstance(self.values, dict):
            raise DomainValidationError("Значення рядка мають бути словником")
        if any(not isinstance(key, str) for key in self.values):
            raise DomainValidationError("Ключі рядка мають бути назвами колонок")
        object.__setattr__(self, "values", self.values.copy())

    def get_value(self, column_name: str) -> Any:
        if column_name not in self.values:
            raise DomainNotFoundError("Поле рядка не знайдено")
        return self.values[column_name]

    def canonical_key(self, columns: list[Column]) -> tuple:
        """Ключ нормалізованих значень у порядку схеми, без внутрішнього UUID."""
        return tuple(
            column.canonicalize(self.get_value(column.name))
            for column in columns
        )


def _check_columns(columns: list[Column]) -> None:
    if not isinstance(columns, list) or not columns:
        raise DomainValidationError("Таблиця повинна містити хоча б одну колонку")
    names: set[str] = set()
    ids: set[UUID] = set()
    for column in columns:
        if not isinstance(column, Column):
            raise DomainValidationError("Схема має містити об'єкти Column")
        if column.name in names:
            raise DomainValidationError("Назви колонок мають бути унікальними", column.name)
        if column.id in ids:
            raise DomainValidationError("UUID колонок мають бути унікальними")
        names.add(column.name)
        ids.add(column.id)


@dataclass
class Table:
    name: str
    columns: list[Column]
    rows: list[Row] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    _schema_locked: bool = field(default=False, init=False, repr=False, compare=False)
    _database_id: UUID | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.name = _normalize_name(self.name)
        _check_uuid(self.id)
        self.validate_schema()
        self.columns = self.columns.copy()
        if not isinstance(self.rows, list):
            raise DomainValidationError("Рядки таблиці мають бути списком")
        restored: list[Row] = []
        ids: set[UUID] = set()
        for row in self.rows:
            if not isinstance(row, Row):
                raise DomainValidationError("Очікується об'єкт Row")
            if row.id in ids:
                raise DomainValidationError("UUID рядків мають бути унікальними")
            restored.append(Row(values=self._normalize_values(row.values), id=row.id))
            ids.add(row.id)
        self.rows = restored
        self._schema_locked = bool(restored)

    def validate_schema(self) -> None:
        _check_columns(self.columns)

    def add_column(self, column: Column) -> None:
        if self._schema_locked or self.rows:
            raise DomainValidationError("Схему готової таблиці змінювати не можна")
        _check_columns([*self.columns, column])
        self.columns.append(column)

    def _normalize_values(self, values: dict[str, Any]) -> dict[str, Any]:
        self.validate_schema()
        if not isinstance(values, dict):
            raise DomainValidationError("Значення рядка мають бути словником")
        expected = {column.name for column in self.columns}
        if set(values) != expected:
            raise DomainValidationError("Потрібні всі колонки таблиці без зайвих полів")
        return {column.name: column.normalize(values[column.name]) for column in self.columns}

    def add_row(self, values: dict[str, Any]) -> Row:
        normalized = self._normalize_values(values)
        row = Row(values=normalized)
        self.rows.append(row)
        self._schema_locked = True
        return Row(values=row.values, id=row.id)

    def update_row(self, row_id: UUID, updates: dict[str, Any]) -> Row:
        _check_uuid(row_id)
        if not isinstance(updates, dict) or not updates:
            raise DomainValidationError("Потрібен непорожній словник змін")
        names = {column.name for column in self.columns}
        if not set(updates).issubset(names):
            raise DomainValidationError("Зміни містять невідомі колонки")
        for index, row in enumerate(self.rows):
            if row.id == row_id:
                candidate = row.values.copy()
                candidate.update(updates)
                normalized = self._normalize_values(candidate)
                replacement = Row(values=normalized, id=row.id)
                self.rows[index] = replacement
                return Row(values=replacement.values, id=replacement.id)
        raise DomainNotFoundError("Рядок не знайдено")

    def get_rows(self) -> list[Row]:
        return [Row(values=row.values, id=row.id) for row in self.rows]

    def remove_duplicates(self) -> int:
        """Залишити перші входження рядків і повернути кількість вилучених."""
        self.validate_schema()
        seen: set[tuple] = set()
        unique_rows: list[Row] = []
        for row in self.rows:
            key = row.canonical_key(self.columns)
            if key not in seen:
                seen.add(key)
                unique_rows.append(row)
        removed = len(self.rows) - len(unique_rows)
        self.rows = unique_rows
        return removed


@dataclass
class Database:
    name: str
    id: UUID = field(default_factory=uuid4)
    tables: dict[UUID, Table] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.name = _normalize_name(self.name)
        _check_uuid(self.id)

    def add_table(self, table: Table) -> None:
        if not isinstance(table, Table):
            raise DomainValidationError("Очікується об'єкт Table")
        if table._database_id is not None:
            raise DomainConflictError("Таблиця вже належить базі даних")
        if table.id in self.tables:
            raise DomainConflictError("Таблиця з таким UUID уже існує")
        if any(existing.name == table.name for existing in self.tables.values()):
            raise DomainConflictError("Таблиця з такою назвою вже існує", "name")
        table.validate_schema()
        self.tables[table.id] = table
        table._database_id = self.id
        table._schema_locked = True

    def find_table(self, table_id: UUID) -> Table:
        _check_uuid(table_id)
        if table_id not in self.tables:
            raise DomainNotFoundError("Таблицю не знайдено")
        return self.tables[table_id]

    def remove_table(self, table_id: UUID) -> None:
        table = self.find_table(table_id)
        del self.tables[table_id]
        table._database_id = None
