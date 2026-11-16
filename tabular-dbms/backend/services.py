"""Операції застосунку під одним спільним блокуванням."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from backend.domain.data_types import TYPE_REGISTRY, get_data_type
from backend.domain.errors import DomainValidationError
from backend.domain.models import Column, Database, Row, Table
from backend.repository import JsonDatabaseRepository


def _database_view(database: Database) -> dict:
    return {
        "id": str(database.id), "name": database.name,
        "tables": [{"id": str(table.id), "name": table.name} for table in database.tables.values()],
    }


def _row_view(table: Table, row: Row) -> dict:
    return {
        "id": str(row.id),
        "values": {
            column.name: column.data_type.to_json(row.get_value(column.name))
            for column in table.columns
        },
    }


def _table_view(table: Table) -> dict:
    type_names = {type_class: name for name, type_class in TYPE_REGISTRY.items()}
    return {
        "id": str(table.id), "name": table.name,
        "columns": [
            {"id": str(column.id), "name": column.name, "type": type_names[type(column.data_type)]}
            for column in table.columns
        ],
        "rows": [_row_view(table, row) for row in table.rows],
    }


class DatabaseService:
    def __init__(self, repository: JsonDatabaseRepository, lock) -> None:
        self.repository = repository
        self.lock = lock

    def list_databases(self) -> list[dict[str, str]]:
        with self.lock:
            return self.repository.list_databases()

    def create_database(self, name: str) -> dict:
        with self.lock:
            database = Database(name=name)
            self.repository.save(database)
            return _database_view(database)

    def get_database(self, db_id: UUID) -> dict:
        with self.lock:
            return _database_view(self.repository.load(db_id))

    def export_database(self, db_id: UUID) -> dict:
        with self.lock:
            return self.repository.export_database(db_id)

    def import_database(self, document: object) -> dict:
        with self.lock:
            return _database_view(self.repository.import_database(document))


class TableService:
    def __init__(self, repository: JsonDatabaseRepository, lock) -> None:
        self.repository = repository
        self.lock = lock

    def create_table(self, db_id: UUID, name: str, columns: list[dict[str, str]]) -> dict:
        with self.lock:
            database = self.repository.load(db_id)
            if not isinstance(columns, list):
                raise DomainValidationError("Очікується список описів колонок")
            schema = []
            for item in columns:
                if not isinstance(item, dict) or set(item) != {"name", "type"}:
                    raise DomainValidationError("Опис колонки має містити name та type")
                schema.append(Column(name=item["name"], data_type=get_data_type(item["type"])))
            table = Table(name=name, columns=schema)
            database.add_table(table)
            self.repository.save(database)
            return _table_view(table)

    def get_table(self, db_id: UUID, table_id: UUID) -> dict:
        with self.lock:
            database = self.repository.load(db_id)
            return _table_view(database.find_table(table_id))

    def delete_table(self, db_id: UUID, table_id: UUID) -> None:
        with self.lock:
            database = self.repository.load(db_id)
            database.remove_table(table_id)
            self.repository.save(database)

    def _change_table(self, db_id: UUID, table_id: UUID, operation: Callable[[Table], dict]) -> dict:
        with self.lock:
            database = self.repository.load(db_id)
            table = database.find_table(table_id)
            result = operation(table)
            self.repository.save(database)
            return result

    def add_row(self, db_id: UUID, table_id: UUID, values: dict[str, Any]) -> dict:
        return self._change_table(
            db_id, table_id, lambda table: _row_view(table, table.add_row(values))
        )

    def update_row(self, db_id: UUID, table_id: UUID, row_id: UUID, updates: dict[str, Any]) -> dict:
        return self._change_table(
            db_id, table_id, lambda table: _row_view(table, table.update_row(row_id, updates))
        )

    def remove_duplicates(self, db_id: UUID, table_id: UUID) -> dict:
        def operation(table: Table) -> dict:
            removed = table.remove_duplicates()
            return {"removed": removed, "remaining_rows": len(table.rows)}

        return self._change_table(db_id, table_id, operation)
