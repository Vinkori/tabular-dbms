"""Контракт HTTP API, помилки, збереження і паралельні запити."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.repository import StorageError


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "storage"), raise_server_exceptions=False) as active:
        yield active


def prepare(client, columns=None):
    result = client.post("/api/databases", json={"name": "Demo"})
    assert result.status_code == 201
    db_id = result.json()["id"]
    result = client.post(f"/api/databases/{db_id}/tables", json={
        "name": "People", "columns": columns or [{"name": "name", "type": "string"},
                                                  {"name": "age", "type": "integer"}],
    })
    assert result.status_code == 201
    table_id = result.json()["id"]
    return db_id, table_id, f"/api/databases/{db_id}/tables/{table_id}"


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "field"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]
    assert body["error"]["field"] is None or isinstance(body["error"]["field"], str)
    return body["error"]


def test_complete_workflow_with_all_six_types(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/databases").json() == []
    schema = [{"name": name, "type": kind} for name, kind in [
        ("number", "integer"), ("score", "real"), ("mark", "char"),
        ("title", "string"), ("shade", "color"), ("range", "colorInvl"),
    ]]
    db_id, table_id, url = prepare(client, schema)
    assert client.get(f"/api/databases/{db_id}").json()["tables"] == [{"id": table_id, "name": "People"}]
    values = {
        "number": "1", "score": "95.5", "mark": "Ї", "title": " Анна ",
        "shade": {"red": 255, "green": 0, "blue": 0},
        "range": {"start": {"red": 0, "green": 0, "blue": 0},
                  "end": {"red": 100, "green": 150, "blue": 200}},
    }
    rows = []
    for data in [values, {**values, "title": "Bob"}, values]:
        response = client.post(url + "/rows", json={"values": data})
        assert response.status_code == 201
        rows.append(response.json())
    assert rows[0]["id"] != rows[2]["id"]
    assert rows[0]["values"]["number"] == 1
    assert rows[0]["values"]["score"] == 95.5
    assert rows[0]["values"]["shade"] == values["shade"]
    assert rows[0]["values"]["range"] == values["range"]
    before = client.get(url).json()
    response = client.patch(url + "/rows/" + rows[0]["id"], json={"updates": {"title": "Changed", "score": "bad"}})
    error = assert_error(response, 422, "VALIDATION_ERROR")
    assert error["field"] == "score"
    assert client.get(url).json() == before
    assert client.post(url + "/remove-duplicates").json() == {"removed": 1, "remaining_rows": 2}
    assert client.get(url).json()["rows"] == rows[:2]
    assert client.post(url + "/remove-duplicates").json() == {"removed": 0, "remaining_rows": 2}
    edited = client.patch(url + "/rows/" + rows[0]["id"], json={"updates": {"score": 97.5}})
    assert edited.status_code == 200
    assert edited.json()["id"] == rows[0]["id"]
    assert edited.json()["values"]["title"] == " Анна "
    export = client.get(f"/api/databases/{db_id}/export")
    assert export.status_code == 200
    assert export.headers["content-disposition"] == f'attachment; filename="{db_id}.json"'
    assert export.json()["schema_version"] == 1
    assert export.json()["tables"][0]["rows"][0]["values"]["score"] == 97.5
    imported = client.post("/api/databases/import", json=export.json())
    assert imported.status_code == 201
    copied_id = imported.json()["id"]
    assert copied_id != db_id
    assert client.get(f"/api/databases/{copied_id}/tables/{table_id}").json() == client.get(url).json()
    assert len(client.get("/api/databases").json()) == 2
    deleted = client.delete(url)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(f"/api/databases/{db_id}").json()["tables"] == []
    assert_error(client.get(url), 404, "NOT_FOUND")
    assert_error(client.delete(url), 404, "NOT_FOUND")
    assert client.get(f"/api/databases/{copied_id}/tables/{table_id}").status_code == 200


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "  "}, {"name": 123},
                                  {"name": None}, {"name": "Demo", "extra": 1}, []])
def test_bad_database_request(client, body):
    assert_error(client.post("/api/databases", json=body), 422, "VALIDATION_ERROR")
    assert client.get("/api/databases").json() == []


@pytest.mark.parametrize("columns", [[], [{"name": "x", "type": "unknown"}],
    [{"name": "x"}], [{"name": "x", "type": "integer", "extra": 1}],
    [{"name": "x", "type": "integer"}, {"name": " x ", "type": "real"}],
])
def test_invalid_table_schema(client, columns):
    db_id = client.post("/api/databases", json={"name": "Demo"}).json()["id"]
    assert_error(client.post(f"/api/databases/{db_id}/tables", json={"name": "Bad", "columns": columns}),
                 422, "VALIDATION_ERROR")
    assert client.get(f"/api/databases/{db_id}").json()["tables"] == []


def test_duplicate_table_name_is_409_but_database_names_can_repeat(client):
    db_id, table_id, url = prepare(client)
    assert client.post("/api/databases", json={"name": "Demo"}).status_code == 201
    response = client.post(f"/api/databases/{db_id}/tables", json={
        "name": " People ", "columns": [{"name": "x", "type": "string"}],
    })
    assert_error(response, 409, "CONFLICT")
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("body", [{}, {"values": None}, {"values": {}},
    {"values": {"name": "Anna", "age": True}}, {"values": {"name": "Anna", "age": None}},
    {"values": {"name": "Anna", "age": "3.5"}},
    {"values": {"name": "Anna", "age": 20, "extra": 1}},
    {"values": {"name": "Anna", "age": 20}, "schema_version": 1},
])
def test_bad_row_does_not_change_table(client, body):
    db_id, table_id, url = prepare(client)
    assert_error(client.post(url + "/rows", json=body), 422, "VALIDATION_ERROR")
    assert client.get(url).json()["rows"] == []


@pytest.mark.parametrize("body", [{}, {"updates": {}}, {"updates": None}, {"updates": {"unknown": 1}},
                                  {"updates": {"name": "Bob", "age": "bad"}}])
def test_bad_patch_is_atomic(client, body):
    db_id, table_id, url = prepare(client)
    row = client.post(url + "/rows", json={"values": {"name": "Anna", "age": 20}}).json()
    assert_error(client.patch(url + "/rows/" + row["id"], json=body), 422, "VALIDATION_ERROR")
    assert client.get(url).json()["rows"] == [row]


def test_missing_objects_and_malformed_uuids(client):
    db_id, table_id, url = prepare(client)
    assert_error(client.get(f"/api/databases/{uuid4()}"), 404, "NOT_FOUND")
    assert_error(client.get(f"/api/databases/{db_id}/tables/{uuid4()}"), 404, "NOT_FOUND")
    assert_error(client.patch(url + f"/rows/{uuid4()}", json={"updates": {"age": 21}}), 404, "NOT_FOUND")
    for path in ["/api/databases/not-uuid", f"/api/databases/{db_id}/tables/not-uuid"]:
        assert_error(client.get(path), 422, "VALIDATION_ERROR")
    assert_error(client.patch(url + "/rows/not-uuid", json={"updates": {"age": 21}}), 422, "VALIDATION_ERROR")


def test_invalid_json_and_wrong_method_have_uniform_errors(client):
    response = client.post("/api/databases", content="{", headers={"content-type": "application/json"})
    assert_error(response, 422, "VALIDATION_ERROR")
    assert_error(client.get("/not-a-route"), 404, "NOT_FOUND")
    assert_error(client.put("/api/databases", json={}), 405, "METHOD_NOT_ALLOWED")


@pytest.mark.parametrize("document", [{}, [], {"schema_version": 2, "id": str(uuid4()), "name": "Bad", "tables": []}])
def test_invalid_import_does_not_create_database(client, document):
    assert_error(client.post("/api/databases/import", json=document), 422, "VALIDATION_ERROR")
    assert client.get("/api/databases").json() == []


def test_save_failure_returns_500_and_is_logged(client, monkeypatch, caplog):
    db_id, table_id, url = prepare(client)
    path = client.app.state.repository.storage_dir / f"{db_id}.json"
    before = path.read_bytes()

    def fail(database):
        raise StorageError("Імітація помилки диска")

    monkeypatch.setattr(client.app.state.repository, "save", fail)
    assert_error(client.post(url + "/rows", json={"values": {"name": "Anna", "age": 20}}), 500, "STORAGE_ERROR")
    assert_error(client.delete(url), 500, "STORAGE_ERROR")
    assert_error(client.post("/api/databases", json={"name": "New"}), 500, "STORAGE_ERROR")
    assert path.read_bytes() == before
    assert len(client.get("/api/databases").json()) == 1
    assert "Імітація помилки диска" in caplog.text


def test_corrupt_database_is_not_returned_as_empty(client):
    db_id, table_id, url = prepare(client)
    path = client.app.state.repository.storage_dir / f"{db_id}.json"
    path.write_text("{", encoding="utf-8")
    response = client.get(f"/api/databases/{db_id}")
    assert_error(response, 500, "STORAGE_ERROR")
    assert path.name in response.json()["error"]["message"]
    assert path.read_text(encoding="utf-8") == "{"


def test_unexpected_error_is_logged_without_traceback_in_response(client, monkeypatch, caplog):
    def fail():
        raise RuntimeError("Технічна причина для журналу")

    monkeypatch.setattr(client.app.state.database_service, "list_databases", fail)
    response = client.get("/api/databases")
    assert_error(response, 500, "INTERNAL_ERROR")
    assert "Технічна причина" not in response.text
    assert "Traceback" not in response.text
    assert "Технічна причина" in caplog.text


def test_restart_and_test_storage_isolation(tmp_path):
    directory = tmp_path / "first"
    app = create_app(directory)
    assert not directory.exists()
    with TestClient(app) as first:
        db_id, table_id, url = prepare(first)
        assert app.state.lock is app.state.database_service.lock is app.state.table_service.lock
        assert app.state.repository is app.state.database_service.repository is app.state.table_service.repository
        first.post(url + "/rows", json={"values": {"name": "Anna", "age": 20}})
        expected = first.get(url).json()
    with TestClient(create_app(directory)) as restarted:
        assert restarted.get(url).json() == expected
    with TestClient(create_app(tmp_path / "second")) as isolated:
        assert isolated.get("/api/databases").json() == []


def test_two_parallel_http_additions_survive(client):
    db_id, table_id, url = prepare(client)
    start = Barrier(2)

    def add(index):
        start.wait(timeout=10)
        return client.post(url + "/rows", json={"values": {"name": str(index), "age": index}})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(add, index) for index in (1, 2)]
        responses = [future.result(timeout=10) for future in futures]
    assert all(response.status_code == 201 for response in responses)
    rows = client.get(url).json()["rows"]
    assert len(rows) == 2
    assert {row["values"]["age"] for row in rows} == {1, 2}


def test_docs_and_openapi_describe_api(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/api/databases/import"]
    assert "patch" in paths["/api/databases/{db_id}/tables/{table_id}/rows/{row_id}"]
    assert "content" not in paths["/api/databases/{db_id}/tables/{table_id}"]["delete"]["responses"]["204"]
