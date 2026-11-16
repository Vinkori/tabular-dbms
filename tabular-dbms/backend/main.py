"""Створення FastAPI-застосунку, спільних сервісів і обробників помилок."""

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from backend.api import router
from backend.domain.errors import DomainConflictError, DomainNotFoundError, DomainValidationError
from backend.repository import JsonDatabaseRepository, StorageError
from backend.services import DatabaseService, TableService


logger = logging.getLogger(__name__)


def _error(status: int, code: str, message: str, field: str | None = None, headers=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "field": field}},
        headers=headers,
    )


def create_app(storage_dir: str | Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        repository = JsonDatabaseRepository(storage_dir)
        lock = Lock()
        application.state.repository = repository
        application.state.lock = lock
        application.state.database_service = DatabaseService(repository, lock)
        application.state.table_service = TableService(repository, lock)
        yield

    application = FastAPI(
        title="Таблична СУБД", version="0.8.0", lifespan=lifespan,
        description="Створення баз і таблиць, редагування рядків та вилучення повторів.",
    )

    @application.exception_handler(DomainConflictError)
    async def conflict_handler(request: Request, error: DomainConflictError):
        return _error(409, "CONFLICT", error.message, error.field)

    @application.exception_handler(DomainValidationError)
    async def validation_handler(request: Request, error: DomainValidationError):
        return _error(422, "VALIDATION_ERROR", error.message, error.field)

    @application.exception_handler(DomainNotFoundError)
    async def not_found_handler(request: Request, error: DomainNotFoundError):
        return _error(404, "NOT_FOUND", error.message)

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, error: RequestValidationError):
        first = error.errors()[0]
        location = [str(part) for part in first.get("loc", ()) if part not in ("body", "path", "query")]
        field = ".".join(location) or None
        messages = {
            "missing": "Обов'язкове поле відсутнє",
            "string_type": "Очікується текст",
            "dict_type": "Очікується JSON-об'єкт",
            "list_type": "Очікується список",
            "literal_error": "Неприпустиме значення поля",
            "extra_forbidden": "Зайве поле запиту",
            "too_short": "Поле містить недостатньо елементів",
            "uuid_parsing": "Некоректний UUID",
            "uuid_type": "Некоректний тип UUID",
            "json_invalid": "Некоректний JSON",
        }
        message = messages.get(first["type"], "Некоректні дані запиту")
        return _error(422, "VALIDATION_ERROR", message, field)

    @application.exception_handler(StorageError)
    async def storage_handler(request: Request, error: StorageError):
        logger.error("Помилка сховища", exc_info=(type(error), error, error.__traceback__))
        return _error(500, "STORAGE_ERROR", str(error))

    @application.exception_handler(HTTPException)
    async def http_handler(request: Request, error: HTTPException):
        if error.status_code == 404:
            return _error(404, "NOT_FOUND", "Маршрут не знайдено", headers=error.headers)
        if error.status_code == 405:
            return _error(405, "METHOD_NOT_ALLOWED", "HTTP-метод не підтримується", headers=error.headers)
        return _error(error.status_code, "HTTP_ERROR", "Не вдалося виконати HTTP-запит", headers=error.headers)

    @application.exception_handler(Exception)
    async def unexpected_handler(request: Request, error: Exception):
        logger.error("Непередбачена помилка сервера", exc_info=(type(error), error, error.__traceback__))
        return _error(500, "INTERNAL_ERROR", "Внутрішня помилка сервера. Перевірте журнал сервера.")

    application.include_router(router)
    web_dir = Path(__file__).resolve().parent / "web"
    application.mount("/static", StaticFiles(directory=web_dir), name="static")

    @application.get("/", response_class=FileResponse, include_in_schema=False)
    def index():
        return FileResponse(web_dir / "index.html", headers={"Cache-Control": "no-cache"})

    return application


app = create_app()
