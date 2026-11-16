"""HTTP-маршрути: отримати перевірений запит і викликати сервіс."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import JSONResponse

from backend.schemas import (
    DatabaseCreate, DatabaseSummary, DatabaseView, DuplicateResult,
    ErrorResponse, HealthResponse, RowCreate, RowUpdate, RowView, TableCreate, TableView,
)
from backend.services import DatabaseService, TableService


router = APIRouter(prefix="/api", responses={
    422: {"model": ErrorResponse, "description": "Некоректні дані"},
    404: {"model": ErrorResponse, "description": "Об'єкт не знайдено"},
    409: {"model": ErrorResponse, "description": "Конфлікт"},
    500: {"model": ErrorResponse, "description": "Помилка сервера або сховища"},
})


def get_database_service(request: Request) -> DatabaseService:
    return request.app.state.database_service


def get_table_service(request: Request) -> TableService:
    return request.app.state.table_service


DatabaseDependency = Annotated[DatabaseService, Depends(get_database_service)]
TableDependency = Annotated[TableService, Depends(get_table_service)]


@router.get("/health", response_model=HealthResponse, tags=["Стан"], summary="Перевірити сервер")
def health():
    return {"status": "ok"}


@router.get("/databases", response_model=list[DatabaseSummary], tags=["Бази"], summary="Список баз")
def list_databases(service: DatabaseDependency):
    return service.list_databases()


@router.post("/databases", status_code=201, response_model=DatabaseView,
             tags=["Бази"], summary="Створити базу")
def create_database(body: DatabaseCreate, service: DatabaseDependency):
    return service.create_database(body.name)


@router.post("/databases/import", status_code=201, response_model=DatabaseView,
             tags=["Бази"], summary="Імпортувати JSON як нову базу")
def import_database(service: DatabaseDependency, document: dict[str, Any] = Body(...)):
    return service.import_database(document)


@router.get("/databases/{db_id}/export", tags=["Бази"], summary="Експортувати базу у JSON")
def export_database(db_id: UUID, service: DatabaseDependency):
    return JSONResponse(
        content=service.export_database(db_id),
        headers={"Content-Disposition": f'attachment; filename="{db_id}.json"'},
    )


@router.get("/databases/{db_id}", response_model=DatabaseView, tags=["Бази"], summary="Відкрити базу")
def get_database(db_id: UUID, service: DatabaseDependency):
    return service.get_database(db_id)


@router.post("/databases/{db_id}/tables", status_code=201, response_model=TableView,
             tags=["Таблиці"], summary="Створити таблицю")
def create_table(db_id: UUID, body: TableCreate, service: TableDependency):
    return service.create_table(db_id, body.name, [column.model_dump() for column in body.columns])


@router.get("/databases/{db_id}/tables/{table_id}", response_model=TableView,
            tags=["Таблиці"], summary="Переглянути таблицю")
def get_table(db_id: UUID, table_id: UUID, service: TableDependency):
    return service.get_table(db_id, table_id)


@router.delete("/databases/{db_id}/tables/{table_id}", status_code=204, response_class=Response,
               tags=["Таблиці"], summary="Видалити таблицю")
def delete_table(db_id: UUID, table_id: UUID, service: TableDependency) -> Response:
    service.delete_table(db_id, table_id)
    return Response(status_code=204)


@router.post("/databases/{db_id}/tables/{table_id}/rows", status_code=201, response_model=RowView,
             tags=["Рядки"], summary="Додати рядок")
def add_row(db_id: UUID, table_id: UUID, body: RowCreate, service: TableDependency):
    return service.add_row(db_id, table_id, body.values)


@router.patch("/databases/{db_id}/tables/{table_id}/rows/{row_id}", response_model=RowView,
              tags=["Рядки"], summary="Редагувати рядок частково")
def update_row(db_id: UUID, table_id: UUID, row_id: UUID, body: RowUpdate, service: TableDependency):
    return service.update_row(db_id, table_id, row_id, body.updates)


@router.post("/databases/{db_id}/tables/{table_id}/remove-duplicates", response_model=DuplicateResult,
             tags=["Рядки"], summary="Вилучити повторювані рядки")
def remove_duplicates(db_id: UUID, table_id: UUID, service: TableDependency):
    return service.remove_duplicates(db_id, table_id)
