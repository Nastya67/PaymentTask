"""Adapter for the external payment provider. The provider itself is mocked."""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.models import Money


class ProviderUnavailable(Exception):
    """The provider did not answer, so it is unknown whether the charge started."""


class InvalidSignature(Exception):
    pass


class InvalidWebhook(Exception):
    pass


@dataclass(frozen=True)
class PaymentResult:
    """The final outcome of a payment, as reported by the provider."""

    payment_id: uuid.UUID
    succeeded: bool
    total: Money
    provider_payment_id: str | None
    failure_reason: str | None


def create_payment(token: str, total: Money, reference: str) -> None:
    """Mock: asks the provider to charge the card; the result arrives by webhook.

    reference is our payment id. The provider uses it as the idempotency key and
    sends it back in the webhook. A token containing "unavailable" raises
    ProviderUnavailable.
    """
    if "unavailable" in token:
        raise ProviderUnavailable


def cancel_payment(reference: str) -> PaymentResult | None:
    """Mock: cancels the payment with our reference.

    Returns None if nothing was charged: the payment is cancelled, or the
    provider never received it. Returns the final outcome if the payment
    completed first.
    """
    return None


def sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def parse_webhook(body: bytes, signature: str | None, secret: str) -> PaymentResult:
    if not signature or not hmac.compare_digest(sign(body, secret), signature):
        raise InvalidSignature("Invalid webhook signature")
    try:
        event = json.loads(body)
        succeeded = {"payment.succeeded": True, "payment.failed": False}[event["type"]]
        result = PaymentResult(
            payment_id=uuid.UUID(event["payment_id"]),
            succeeded=succeeded,
            total=Money(Decimal(event["amount"]), event["currency"]),
            provider_payment_id=event.get("provider_payment_id"),
            failure_reason=event.get("failure_reason"),
        )
    except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as e:
        raise InvalidWebhook("Malformed webhook payload") from e
    if result.succeeded and not result.provider_payment_id:
        raise InvalidWebhook("A succeeded payment needs provider_payment_id")
    return result
