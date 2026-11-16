"""Перевірене JSON-сховище: один файл на базу даних."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from backend.domain.data_types import TYPE_REGISTRY, get_data_type
from backend.domain.errors import (
    DomainConflictError,
    DomainNotFoundError,
    DomainValidationError,
)
from backend.domain.models import Column, Database, Row, Table


class StorageError(OSError):
    """Не вдалося прочитати або записати файлове сховище."""


def _object(data: object, keys: set[str], label: str) -> dict:
    if not isinstance(data, dict) or set(data) != keys:
        raise DomainValidationError(f"Некоректні поля об'єкта: {label}")
    return data


def _array(data: object, label: str) -> list:
    if not isinstance(data, list):
        raise DomainValidationError(f"Очікується список: {label}")
    return data


def _parse_uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise DomainValidationError("UUID у JSON має бути рядком")
    try:
        return UUID(value)
    except ValueError as error:
        raise DomainValidationError("Некоректний UUID у JSON") from error


def _uuid_text(value: UUID) -> str:
    if not isinstance(value, UUID):
        raise DomainValidationError("У домені очікується об'єкт UUID")
    return str(value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DomainValidationError(f"Повторний ключ у JSON: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise DomainValidationError(f"Недопустима числова константа JSON: {value}")


class JsonDatabaseRepository:
    SCHEMA_VERSION = 1

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        default_dir = Path(__file__).resolve().parent.parent / "storage"
        try:
            self.storage_dir = Path(storage_dir).resolve() if storage_dir is not None else default_dir
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StorageError(f"Не вдалося підготувати папку сховища: {error}") from error

    def _path(self, db_id: UUID) -> Path:
        return self.storage_dir / f"{_uuid_text(db_id)}.json"

    def from_document(self, data: object) -> Database:
        """Перевірити документ і відновити доменні об'єкти без запису на диск."""
        document = _object(data, {"schema_version", "id", "name", "tables"}, "база")
        version = document["schema_version"]
        if type(version) is not int or version != self.SCHEMA_VERSION:
            raise DomainValidationError("Непідтримувана версія формату БД")
        database = Database(name=document["name"], id=_parse_uuid(document["id"]))
        try:
            for raw_table in _array(document["tables"], "tables"):
                item = _object(raw_table, {"id", "name", "columns", "rows"}, "таблиця")
                columns = []
                for raw_column in _array(item["columns"], "columns"):
                    column = _object(raw_column, {"id", "name", "type"}, "колонка")
                    columns.append(Column(
                        name=column["name"],
                        data_type=get_data_type(column["type"]),
                        id=_parse_uuid(column["id"]),
                    ))
                rows = []
                names = {column.name for column in columns}
                for raw_row in _array(item["rows"], "rows"):
                    row = _object(raw_row, {"id", "values"}, "рядок")
                    raw_values = _object(row["values"], names, "значення рядка")
                    values = {
                        column.name: column.data_type.from_json(raw_values[column.name])
                        for column in columns
                    }
                    rows.append(Row(values=values, id=_parse_uuid(row["id"])))
                restored = Table(
                    name=item["name"], columns=columns, rows=rows, id=_parse_uuid(item["id"])
                )
                database.add_table(restored)
        except DomainConflictError as error:
            raise DomainValidationError(f"Конфлікт у документі БД: {error.message}") from error
        return database

    def _table_document(self, table: Table) -> dict:
        if not isinstance(table, Table):
            raise DomainValidationError("Очікується об'єкт Table")
        table.validate_schema()
        type_names = {type_class: name for name, type_class in TYPE_REGISTRY.items()}
        columns = [
            {"id": _uuid_text(column.id), "name": column.name,
             "type": type_names[type(column.data_type)]}
            for column in table.columns
        ]
        rows = []
        names = {column.name for column in table.columns}
        for row in _array(table.rows, "rows"):
            if not isinstance(row, Row):
                raise DomainValidationError("Очікується об'єкт Row")
            _object(row.values, names, "значення рядка")
            values = {
                column.name: column.data_type.to_json(row.values[column.name])
                for column in table.columns
            }
            rows.append({"id": _uuid_text(row.id), "values": values})
        return {"id": _uuid_text(table.id), "name": table.name, "columns": columns, "rows": rows}

    def to_document(self, database: Database) -> dict:
        """Отримати JSON-сумісний словник зі збереженням UUID та порядку."""
        if not isinstance(database, Database) or not isinstance(database.tables, dict):
            raise DomainValidationError("Очікується коректний об'єкт Database")
        tables = []
        for table_id, table in database.tables.items():
            if not isinstance(table, Table) or table_id != table.id:
                raise DomainValidationError("Ключ таблиці не відповідає її UUID")
            tables.append(self._table_document(table))
        document = {
            "schema_version": self.SCHEMA_VERSION,
            "id": _uuid_text(database.id), "name": database.name, "tables": tables,
        }
        self.from_document(document)
        return document

    def parse_document(self, text: str) -> Database:
        """Прочитати JSON-текст, відхилити повторні ключі та NaN/Infinity."""
        if not isinstance(text, str):
            raise DomainValidationError("Очікується JSON-текст")
        try:
            data = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except DomainValidationError:
            raise
        except (ValueError, RecursionError) as error:
            raise DomainValidationError("Некоректний JSON-текст") from error
        return self.from_document(data)

    def load(self, db_id: UUID) -> Database:
        path = self._path(db_id)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise DomainNotFoundError(f"Базу даних не знайдено: {path.name}") from error
        except (OSError, UnicodeError) as error:
            raise StorageError(f"Не вдалося прочитати {path.name}: {error}") from error
        try:
            database = self.parse_document(text)
            if database.id != db_id:
                raise DomainValidationError("UUID у документі не відповідає імені файла")
        except DomainValidationError as error:
            raise StorageError(f"Пошкоджена база {path.name}: {error.message}") from error
        return database

    def save(self, database: Database) -> None:
        document = self.to_document(database)
        path = self._path(database.id)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.storage_dir,
                prefix=f".{database.id}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(document, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except (OSError, ValueError, TypeError) as error:
            failure = StorageError(f"Не вдалося зберегти {path.name}: {error}")
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    failure.add_note(f"Не вдалося прибрати {temporary.name}: {cleanup_error}")
            raise failure from error

    def list_databases(self) -> list[dict[str, str]]:
        """Повернути id/name; пошкоджені файли не пропускати мовчки."""
        result = []
        try:
            paths = sorted(path for path in self.storage_dir.iterdir() if path.suffix == ".json")
        except OSError as error:
            raise StorageError(f"Не вдалося прочитати список баз: {error}") from error
        for path in paths:
            try:
                db_id = _parse_uuid(path.stem)
                if path.name != f"{db_id}.json":
                    raise DomainValidationError("Ім'я файла має містити стандартний UUID")
            except DomainValidationError as error:
                raise StorageError(f"Некоректне ім'я файла БД: {path.name}") from error
            database = self.load(db_id)
            result.append({"id": str(database.id), "name": database.name})
        return result

    def export_database(self, db_id: UUID) -> dict:
        return self.to_document(self.load(db_id))

    def import_database(self, data: object) -> Database:
        """Перевірити snapshot, зберегти нову БД; не змінювати вхідний документ."""
        source = self.from_document(data)
        imported = Database(name=source.name)
        if self._path(imported.id).exists():
            raise DomainConflictError("Згенерований UUID бази вже існує")
        for table in list(source.tables.values()):
            source.remove_table(table.id)
            imported.add_table(table)
        self.save(imported)
        return imported
