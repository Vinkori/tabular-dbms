"""Помилки перевірки даних предметної області."""


class DomainValidationError(ValueError):
    """Некоректне значення; field може вказувати на проблемне поле."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


class DomainNotFoundError(LookupError):
    """Запитаний об'єкт не знайдений."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DomainConflictError(DomainValidationError):
    """Конфлікт назви, ідентифікатора або власника об'єкта."""
