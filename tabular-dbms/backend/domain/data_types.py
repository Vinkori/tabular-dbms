"""Шість доменних типів без залежностей від сервера або інтерфейсу."""

from abc import ABC, abstractmethod
from collections.abc import Hashable
import math
import re
from typing import Any

from backend.domain.colors import Color, ColorInterval
from backend.domain.errors import DomainValidationError


class DataType(ABC):
    def validate(self, raw: Any) -> bool:
        try:
            self.normalize(raw)
        except DomainValidationError:
            return False
        return True

    @abstractmethod
    def normalize(self, raw: Any) -> Any:
        """Повернути типізоване значення або підняти DomainValidationError."""

    def canonicalize(self, value: Any) -> Hashable:
        """Отримати ключ уже нормалізованого простого значення."""
        return value

    def to_json(self, value: Any) -> object:
        """Отримати перевірене значення, яке підтримує json.dumps."""
        return self.normalize(value)

    def from_json(self, data: object) -> Any:
        return self.normalize(data)


class IntegerType(DataType):
    def normalize(self, raw: Any) -> int:
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and re.fullmatch(r"[+-]?[0-9]+", raw.strip()):
            try:
                return int(raw.strip())
            except ValueError as error:
                raise DomainValidationError(
                    "Не вдалося перетворити текст на ціле число"
                ) from error
        raise DomainValidationError("Очікується ціле число або його текстовий запис")


class RealType(DataType):
    def normalize(self, raw: Any) -> float:
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise DomainValidationError("Очікується дійсне число")
        if isinstance(raw, str):
            raw = raw.strip()
            pattern = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
            if not re.fullmatch(pattern, raw):
                raise DomainValidationError("Очікується число з крапкою або експонентою")
        try:
            value = float(raw)
        except (ValueError, OverflowError) as error:
            raise DomainValidationError("Не вдалося отримати скінченне число") from error
        if not math.isfinite(value):
            raise DomainValidationError("NaN та нескінченність не підтримуються")
        return value


class CharType(DataType):
    def normalize(self, raw: Any) -> str:
        if not isinstance(raw, str) or len(raw) != 1:
            raise DomainValidationError("Очікується рівно один символ")
        return raw


class StringType(DataType):
    def normalize(self, raw: Any) -> str:
        if not isinstance(raw, str):
            raise DomainValidationError("Очікується рядок тексту")
        return raw


class ColorType(DataType):
    def normalize(self, raw: Any) -> Color:
        if isinstance(raw, Color):
            return raw
        if not isinstance(raw, dict) or set(raw) != {"red", "green", "blue"}:
            raise DomainValidationError("Колір має містити лише red, green, blue")
        return Color(raw["red"], raw["green"], raw["blue"])

    def canonicalize(self, value: Color) -> Hashable:
        return value.as_tuple()

    def to_json(self, value: Any) -> object:
        color = self.normalize(value)
        return {"red": color.red, "green": color.green, "blue": color.blue}


class ColorIntervalType(DataType):
    def normalize(self, raw: Any) -> ColorInterval:
        if isinstance(raw, ColorInterval):
            return raw
        if not isinstance(raw, dict) or set(raw) != {"start", "end"}:
            raise DomainValidationError("Інтервал має містити лише start та end")
        color_type = ColorType()
        return ColorInterval(
            color_type.normalize(raw["start"]),
            color_type.normalize(raw["end"]),
        )

    def canonicalize(self, value: ColorInterval) -> Hashable:
        return value.as_tuple()

    def to_json(self, value: Any) -> object:
        interval = self.normalize(value)
        color_type = ColorType()
        return {
            "start": color_type.to_json(interval.start),
            "end": color_type.to_json(interval.end),
        }


TYPE_REGISTRY: dict[str, type[DataType]] = {
    "integer": IntegerType,
    "real": RealType,
    "char": CharType,
    "string": StringType,
    "color": ColorType,
    "colorInvl": ColorIntervalType,
}


def get_data_type(name: str) -> DataType:
    if not isinstance(name, str) or name not in TYPE_REGISTRY:
        raise DomainValidationError("Невідомий тип даних")
    return TYPE_REGISTRY[name]()
