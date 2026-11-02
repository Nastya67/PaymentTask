"""Business rule violations. The API layer maps them to HTTP responses."""


class DomainError(Exception):
    pass


class CartNotFound(DomainError):
    pass


class CartNotPayable(DomainError):
    pass


class CartEmpty(DomainError):
    pass


class PaymentMethodNotFound(DomainError):
    pass


class OutOfStock(DomainError):
    pass


class InvalidCartTotal(DomainError):
    pass
