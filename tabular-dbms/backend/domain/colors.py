"""Незмінні RGB-кольори та включні поканальні інтервали."""

from dataclasses import dataclass

from backend.domain.errors import DomainValidationError


@dataclass(frozen=True)
class Color:
    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        for name in ("red", "green", "blue"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise DomainValidationError("Канал RGB має бути цілим числом", name)
            if not 0 <= value <= 255:
                raise DomainValidationError("Канал RGB має бути в межах 0..255", name)

    def as_tuple(self) -> tuple[int, int, int]:
        return self.red, self.green, self.blue


@dataclass(frozen=True)
class ColorInterval:
    start: Color
    end: Color

    def __post_init__(self) -> None:
        if not isinstance(self.start, Color) or not isinstance(self.end, Color):
            raise DomainValidationError("Межі інтервалу мають бути об'єктами Color")
        for name in ("red", "green", "blue"):
            if getattr(self.start, name) > getattr(self.end, name):
                raise DomainValidationError(
                    "Початковий канал не може перевищувати кінцевий", name
                )

    def as_tuple(self) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        return self.start.as_tuple(), self.end.as_tuple()
