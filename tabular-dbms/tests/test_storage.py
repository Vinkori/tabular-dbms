"""Файлові перевірки виконуються тільки в тимчасових папках pytest."""

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest

import backend.repository as repository_module
from backend.domain.colors import Color, ColorInterval
from backend.domain.data_types import get_data_type
from backend.domain.errors import DomainConflictError, DomainNotFoundError, DomainValidationError
from backend.domain.models import Column, Database, Table
from backend.repository import JsonDatabaseRepository, StorageError


@pytest.fixture
def repo(tmp_path):
    return JsonDatabaseRepository(tmp_path / "storage")


@pytest.fixture
def database():
    db = Database("Навчальна база")
    schema = [
        ("number", "integer"), ("score", "real"), ("mark", "char"),
        ("title", "string"), ("shade", "color"), ("range", "colorInvl"),
    ]
    table = Table("Приклади", [Column(name, get_data_type(kind)) for name, kind in schema])
    db.add_table(table)
    values = {
        "number": 1, "score": 95.5, "mark": "Ї", "title": " Анна ",
        "shade": {"red": 255, "green": 0, "blue": 0},
        "range": {
            "start": {"red": 0, "green": 0, "blue": 0},
            "end": {"red": 100, "green": 150, "blue": 200},
        },
    }
    table.add_row(values)
    table.add_row({**values, "number": 2, "mark": " ", "title": ""})
    table.add_row(values)
    db.add_table(Table("Порожня", [Column("id", get_data_type("string"))]))
    return db


def test_disk_round_trip_preserves_everything(repo, database):
    expected = repo.to_document(database)
    repo.save(database)
    path = repo.storage_dir / f"{database.id}.json"
    text = path.read_text(encoding="utf-8")
    assert "Навчальна база" in text
    assert json.loads(text) == expected
    restored = JsonDatabaseRepository(repo.storage_dir).load(database.id)
    assert repo.to_document(restored) == expected
    assert restored is not database
    assert list(restored.tables) == list(database.tables)
    table = next(iter(restored.tables.values()))
    row = table.get_rows()[0]
    assert type(row.get_value("number")) is int
    assert type(row.get_value("score")) is float
    assert isinstance(row.get_value("shade"), Color)
    assert isinstance(row.get_value("range"), ColorInterval)
    assert row.get_value("title") == " Анна "
    assert [type(c.data_type) for c in table.columns] == [
        type(c.data_type) for c in next(iter(database.tables.values())).columns
    ]
    assert len(table.get_rows()) == 3


def test_empty_database_and_missing_database(repo):
    assert repo.list_databases() == []
    db = Database("Empty")
    repo.save(db)
    assert repo.load(db.id).tables == {}
    with pytest.raises(DomainNotFoundError):
        repo.load(uuid4())


def test_list_and_export(repo, database):
    repo.save(database)
    other = Database(database.name)
    repo.save(other)
    (repo.storage_dir / "ignored.tmp").write_text("unfinished", encoding="utf-8")
    records = repo.list_databases()
    assert {item["id"] for item in records} == {str(database.id), str(other.id)}
    assert all(item["name"] == database.name for item in records)
    assert repo.export_database(database.id) == repo.to_document(database)


def test_import_creates_new_database_and_preserves_source(repo, database):
    repo.save(database)
    source_path = repo.storage_dir / f"{database.id}.json"
    before_bytes = source_path.read_bytes()
    document = repo.export_database(database.id)
    unchanged_document = deepcopy(document)
    imported = repo.import_database(document)
    assert imported.id != database.id
    assert imported.name == database.name
    assert list(imported.tables) == list(database.tables)
    assert all(table._database_id == imported.id for table in imported.tables.values())
    expected = deepcopy(document)
    expected["id"] = str(imported.id)
    assert repo.export_database(imported.id) == expected
    assert source_path.read_bytes() == before_bytes
    assert document == unchanged_document
    assert len(repo.list_databases()) == 2


INVALID_CHANGES = [
    (("schema_version",), value) for value in [0, 2, True, 1.0, "1", None]
] + [
    (("name",), " "), (("tables",), {}),
    (("tables", 0, "columns"), []),
    (("tables", 0, "columns", 0, "type"), "unknown"),
    (("tables", 0, "rows"), {}),
    (("tables", 0, "rows", 0, "values"), {}),
    (("tables", 0, "rows", 0, "values", "number"), True),
    (("tables", 0, "rows", 0, "values", "score"), "NaN"),
    (("tables", 0, "rows", 0, "values", "mark"), "AB"),
    (("tables", 0, "rows", 0, "values", "title"), None),
    (("tables", 0, "rows", 0, "values", "shade", "red"), 256),
    (("tables", 0, "rows", 0, "values", "range", "start", "red"), 101),
] + [
    (path, bad)
    for path in [("id",), ("tables", 0, "id"), ("tables", 0, "columns", 0, "id"),
                 ("tables", 0, "rows", 0, "id")]
    for bad in ["../outside", None, 1]
]


@pytest.mark.parametrize("path,bad", INVALID_CHANGES)
def test_invalid_import_leaves_storage_unchanged(repo, database, path, bad):
    repo.save(database)
    source = repo.storage_dir / f"{database.id}.json"
    original_bytes = source.read_bytes()
    document = repo.to_document(database)
    parent = document
    for part in path[:-1]:
        parent = parent[part]
    parent[path[-1]] = bad
    with pytest.raises(DomainValidationError):
        repo.import_database(document)
    assert source.read_bytes() == original_bytes
    assert list(repo.storage_dir.iterdir()) == [source]


@pytest.mark.parametrize("collection", ["tables", "columns", "rows"])
def test_duplicate_ids_are_rejected(repo, database, collection):
    document = repo.to_document(database)
    items = document["tables"] if collection == "tables" else document["tables"][0][collection]
    duplicate = deepcopy(items[0])
    if collection != "rows":
        duplicate["name"] = "Інша назва"
    items.append(duplicate)
    with pytest.raises(DomainValidationError):
        repo.from_document(document)


@pytest.mark.parametrize("collection", ["tables", "columns"])
def test_duplicate_names_are_rejected(repo, database, collection):
    document = repo.to_document(database)
    items = document["tables"] if collection == "tables" else document["tables"][0][collection]
    duplicate = deepcopy(items[0])
    duplicate["id"] = str(uuid4())
    items.append(duplicate)
    with pytest.raises(DomainValidationError):
        repo.from_document(document)


@pytest.mark.parametrize("level", ["database", "table", "column", "row", "values"])
def test_extra_fields_are_rejected(repo, database, level):
    document = repo.to_document(database)
    table = document["tables"][0]
    targets = {"database": document, "table": table, "column": table["columns"][0],
               "row": table["rows"][0], "values": table["rows"][0]["values"]}
    targets[level]["extra"] = 1
    with pytest.raises(DomainValidationError):
        repo.from_document(document)


@pytest.mark.parametrize("text", ["{", "[]", "null", '{"x": 1, "x": 2}',
                                  '{"x": NaN}', '{"x": Infinity}', '{"x": -Infinity}'])
def test_invalid_json_text(repo, text):
    with pytest.raises(DomainValidationError):
        repo.parse_document(text)


@pytest.mark.parametrize("content", [b"{", b"\xff", b"{}"])
def test_corrupt_file_is_reported_and_not_rewritten(repo, content):
    db_id = uuid4()
    path = repo.storage_dir / f"{db_id}.json"
    path.write_bytes(content)
    for operation in (lambda: repo.load(db_id), repo.list_databases):
        with pytest.raises(StorageError) as error:
            operation()
        assert path.name in str(error.value)
        assert path.read_bytes() == content


def test_document_uuid_must_match_filename(repo, database):
    path = repo.storage_dir / f"{uuid4()}.json"
    path.write_text(json.dumps(repo.to_document(database)), encoding="utf-8")
    with pytest.raises(StorageError, match="UUID"):
        repo.list_databases()


def test_invalid_filename_and_path_input(repo):
    (repo.storage_dir / "wrong.json").write_text("{}", encoding="utf-8")
    with pytest.raises(StorageError, match="wrong.json"):
        repo.list_databases()
    with pytest.raises(DomainValidationError):
        repo.load("../outside")


@pytest.mark.parametrize("failure_point", ["create", "write", "flush", "replace"])
@pytest.mark.parametrize("existing", [False, True])
def test_failed_save_preserves_previous_file(repo, database, monkeypatch, failure_point, existing):
    target = repo.storage_dir / f"{database.id}.json"
    if existing:
        repo.save(database)
    original = target.read_bytes() if existing else None
    database.name = "Змінена база"

    def fail(*args, **kwargs):
        raise OSError("Імітація помилки диска")

    def partial_write(document, stream, **kwargs):
        stream.write('{"unfinished":')
        raise OSError("Імітація неповного запису")

    if failure_point == "create":
        monkeypatch.setattr(repository_module, "NamedTemporaryFile", fail)
    elif failure_point == "write":
        monkeypatch.setattr(repository_module.json, "dump", partial_write)
    elif failure_point == "flush":
        monkeypatch.setattr(repository_module.os, "fsync", fail)
    else:
        monkeypatch.setattr(repository_module.os, "replace", fail)
    with pytest.raises(StorageError):
        repo.save(database)
    if existing:
        assert target.read_bytes() == original
        assert list(repo.storage_dir.iterdir()) == [target]
    else:
        assert list(repo.storage_dir.iterdir()) == []


def test_replace_happens_after_close_in_same_directory(repo, database, monkeypatch):
    create = repository_module.NamedTemporaryFile
    replace = repository_module.os.replace
    opened = []

    def capture(**kwargs):
        stream = create(**kwargs)
        opened.append(stream)
        return stream

    def checked_replace(source, destination):
        assert opened[0].closed
        assert Path(source).parent == repo.storage_dir
        assert Path(destination).parent == repo.storage_dir
        replace(source, destination)

    monkeypatch.setattr(repository_module, "NamedTemporaryFile", capture)
    monkeypatch.setattr(repository_module.os, "replace", checked_replace)
    repo.save(database)
    assert repo.load(database.id).name == database.name


def test_invalid_in_memory_data_does_not_overwrite_file(repo, database):
    repo.save(database)
    path = repo.storage_dir / f"{database.id}.json"
    original = path.read_bytes()
    next(iter(database.tables.values())).rows[0].values["score"] = float("nan")
    with pytest.raises(DomainValidationError):
        repo.save(database)
    assert path.read_bytes() == original
    assert list(repo.storage_dir.iterdir()) == [path]


def test_default_path_is_relative_to_module_not_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(repository_module, "__file__", str(tmp_path / "app" / "backend" / "repository.py"))
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    repo = JsonDatabaseRepository()
    assert repo.storage_dir == tmp_path / "app" / "storage"
    assert repo.storage_dir.is_dir()
    assert not (other / "storage").exists()


def test_directory_creation_failure(tmp_path):
    file_path = tmp_path / "file"
    file_path.write_text("data", encoding="utf-8")
    with pytest.raises(StorageError):
        JsonDatabaseRepository(file_path)


def test_deduplicate_save_and_reload(repo, database):
    repo.save(database)
    restored = repo.load(database.id)
    table = next(iter(restored.tables.values()))
    first_id = table.get_rows()[0].id
    assert table.remove_duplicates() == 1
    repo.save(restored)
    again = JsonDatabaseRepository(repo.storage_dir).load(database.id)
    rows = next(iter(again.tables.values())).get_rows()
    assert len(rows) == 2
    assert rows[0].id == first_id


def test_import_save_failure_leaves_source_and_no_new_file(repo, database, monkeypatch):
    repo.save(database)
    path = repo.storage_dir / f"{database.id}.json"
    before = path.read_bytes()
    document = repo.export_database(database.id)

    def fail_replace(*args):
        raise OSError("Імітація помилки заміни")

    monkeypatch.setattr(repository_module.os, "replace", fail_replace)
    with pytest.raises(StorageError):
        repo.import_database(document)
    assert path.read_bytes() == before
    assert list(repo.storage_dir.iterdir()) == [path]


def test_import_uuid_collision_does_not_overwrite_source(repo, database, monkeypatch):
    repo.save(database)
    path = repo.storage_dir / f"{database.id}.json"
    before = path.read_bytes()
    document = repo.export_database(database.id)

    def database_with_collision(name, **kwargs):
        return Database(name=name, id=kwargs.get("id", database.id))

    monkeypatch.setattr(repository_module, "Database", database_with_collision)
    with pytest.raises(DomainConflictError):
        repo.import_database(document)
    assert path.read_bytes() == before
    assert list(repo.storage_dir.iterdir()) == [path]


def test_missing_storage_directory_is_not_an_empty_database_list(repo):
    repo.storage_dir.rmdir()
    with pytest.raises(StorageError):
        repo.list_databases()
