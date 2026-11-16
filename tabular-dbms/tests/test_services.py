"""Перевірки сервісів, повного блокування операцій і відсутності кешу БД."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, get_ident
from uuid import UUID

import pytest

from backend.domain.errors import DomainValidationError
from backend.repository import JsonDatabaseRepository, StorageError
from backend.services import DatabaseService, TableService


class CheckedLock:
    """Тестовий lock виявляє повторне захоплення тим самим потоком."""

    def __init__(self):
        self.actual = Lock()
        self.owner = None

    def __enter__(self):
        assert self.owner != get_ident(), "Вкладене захоплення lock"
        self.actual.acquire()
        self.owner = get_ident()
        return self

    def __exit__(self, *args):
        self.owner = None
        self.actual.release()


@pytest.fixture
def services(tmp_path, monkeypatch):
    repository = JsonDatabaseRepository(tmp_path / "storage")
    lock = CheckedLock()
    for name in ("load", "save", "list_databases", "import_database", "export_database"):
        original = getattr(repository, name)

        def checked(*args, _original=original, **kwargs):
            assert lock.owner == get_ident(), "Операція сховища поза спільним lock"
            return _original(*args, **kwargs)

        monkeypatch.setattr(repository, name, checked)
    return DatabaseService(repository, lock), TableService(repository, lock)


def prepare(services):
    databases, tables = services
    db_id = UUID(databases.create_database(" Demo ")["id"])
    result = tables.create_table(db_id, "People", [
        {"name": "name", "type": "string"}, {"name": "age", "type": "integer"},
    ])
    return db_id, UUID(result["id"])


def test_services_use_one_lock_for_every_operation(services):
    databases, tables = services
    assert databases.lock is tables.lock
    assert databases.repository is tables.repository
    db_id, table_id = prepare(services)
    assert databases.get_database(db_id)["name"] == "Demo"
    assert databases.list_databases() == [{"id": str(db_id), "name": "Demo"}]
    first = tables.add_row(db_id, table_id, {"name": "Anna", "age": "20"})
    tables.add_row(db_id, table_id, {"name": "Anna", "age": 20})
    assert tables.remove_duplicates(db_id, table_id) == {"removed": 1, "remaining_rows": 1}
    edited = tables.update_row(db_id, table_id, UUID(first["id"]), {"age": "21"})
    assert edited["id"] == first["id"]
    assert edited["values"] == {"name": "Anna", "age": 21}
    assert tables.get_table(db_id, table_id)["rows"] == [edited]
    imported = databases.import_database(databases.export_database(db_id))
    assert imported["id"] != str(db_id)
    tables.delete_table(db_id, table_id)
    assert databases.get_database(db_id)["tables"] == []
    assert databases.lock.owner is None


def test_invalid_edit_preserves_file_and_releases_lock(services):
    databases, tables = services
    db_id, table_id = prepare(services)
    row = tables.add_row(db_id, table_id, {"name": "Anna", "age": 20})
    path = databases.repository.storage_dir / f"{db_id}.json"
    before = path.read_bytes()
    with pytest.raises(DomainValidationError):
        tables.update_row(db_id, table_id, UUID(row["id"]), {"name": "Bob", "age": "wrong"})
    assert path.read_bytes() == before
    assert tables.get_table(db_id, table_id)["rows"] == [row]
    assert databases.lock.owner is None


@pytest.mark.parametrize("action", ["create_table", "delete_table", "add_row", "update_row", "deduplicate"])
def test_save_failure_does_not_leave_modified_cache(services, monkeypatch, action):
    databases, tables = services
    db_id, table_id = prepare(services)
    row = tables.add_row(db_id, table_id, {"name": "Anna", "age": 20})
    tables.add_row(db_id, table_id, {"name": "Anna", "age": 20})
    before = tables.get_table(db_id, table_id)
    path = databases.repository.storage_dir / f"{db_id}.json"
    before_bytes = path.read_bytes()

    def fail(database):
        assert databases.lock.owner == get_ident()
        raise StorageError("Імітація помилки збереження")

    monkeypatch.setattr(databases.repository, "save", fail)
    operations = {
        "create_table": lambda: tables.create_table(db_id, "Other", [{"name": "x", "type": "integer"}]),
        "delete_table": lambda: tables.delete_table(db_id, table_id),
        "add_row": lambda: tables.add_row(db_id, table_id, {"name": "Bob", "age": 30}),
        "update_row": lambda: tables.update_row(db_id, table_id, UUID(row["id"]), {"age": 30}),
        "deduplicate": lambda: tables.remove_duplicates(db_id, table_id),
    }
    with pytest.raises(StorageError):
        operations[action]()
    assert path.read_bytes() == before_bytes
    assert tables.get_table(db_id, table_id) == before
    assert databases.get_database(db_id)["tables"] == [{"id": str(table_id), "name": "People"}]
    assert databases.lock.owner is None


def test_service_reads_fresh_database_each_time(services):
    databases, tables = services
    db_id, table_id = prepare(services)
    external = JsonDatabaseRepository(databases.repository.storage_dir)
    database = external.load(db_id)
    database.find_table(table_id).add_row({"name": "From disk", "age": 40})
    external.save(database)
    assert tables.get_table(db_id, table_id)["rows"][0]["values"]["name"] == "From disk"


def test_two_simultaneous_additions_are_both_saved(services, monkeypatch):
    databases, tables = services
    db_id, table_id = prepare(services)
    from backend.domain.models import Table
    original = Table.add_row

    def checked_add(table, values):
        assert databases.lock.owner == get_ident(), "Доменна зміна поза lock"
        return original(table, values)

    monkeypatch.setattr(Table, "add_row", checked_add)
    start = Barrier(2)

    def add(index):
        start.wait(timeout=10)
        return tables.add_row(db_id, table_id, {"name": str(index), "age": index})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(add, index) for index in (1, 2)]
        results = [future.result(timeout=10) for future in futures]
    saved = tables.get_table(db_id, table_id)["rows"]
    assert {row["id"] for row in saved} == {row["id"] for row in results}
    assert len(saved) == 2
