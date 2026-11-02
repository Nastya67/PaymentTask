"""Payment rule violations."""

from app.errors import DomainError


class PaymentInProgress(DomainError):
    pass


class PaymentNotFound(DomainError):
    pass
