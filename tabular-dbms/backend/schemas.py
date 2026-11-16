"""Форми HTTP-запитів і відповідей; правила значень лишаються в домені."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr


TypeName = Literal["integer", "real", "char", "string", "color", "colorInvl"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseCreate(InputModel):
    name: StrictStr


class ColumnCreate(InputModel):
    name: StrictStr
    type: TypeName


class TableCreate(InputModel):
    name: StrictStr
    columns: list[ColumnCreate] = Field(min_length=1)


class RowCreate(InputModel):
    values: dict[str, Any]


class RowUpdate(InputModel):
    updates: dict[str, Any] = Field(min_length=1)


class TableSummary(BaseModel):
    id: UUID
    name: str


class DatabaseSummary(BaseModel):
    id: UUID
    name: str


class DatabaseView(DatabaseSummary):
    tables: list[TableSummary]


class ColumnView(BaseModel):
    id: UUID
    name: str
    type: TypeName


class RowView(BaseModel):
    id: UUID
    values: dict[str, Any]


class TableView(TableSummary):
    columns: list[ColumnView]
    rows: list[RowView]


class DuplicateResult(BaseModel):
    removed: int
    remaining_rows: int


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
