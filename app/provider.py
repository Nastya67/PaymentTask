"""Adapter for the external payment provider. The provider itself is mocked."""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum


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
    amount: Decimal
    currency: str
    provider_payment_id: str | None
    failure_reason: str | None


class NoResult(StrEnum):
    """Why the provider has no final outcome for a payment."""

    NOT_FOUND = "not_found"  # the request never reached the provider
    PROCESSING = "processing"
    CANCELLED = "cancelled"


def create_payment(token: str, amount: Decimal, currency: str, reference: str) -> None:
    """Mock: asks the provider to charge the card; the result arrives by webhook.

    reference is our payment id. The provider uses it as the idempotency key and
    sends it back in the webhook. A token containing "unavailable" raises
    ProviderUnavailable.
    """
    if not token:
        raise ProviderUnavailable


def get_payment(reference: str) -> PaymentResult | NoResult:
    """Mock: the provider never saw the payment, as its webhook never arrives."""
    return NoResult.NOT_FOUND


def cancel_payment(reference: str) -> PaymentResult | NoResult:
    """Mock: cancels a processing payment.

    Returns CANCELLED, or the final outcome if the payment completed first.
    """
    return NoResult.CANCELLED


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
            amount=Decimal(event["amount"]),
            currency=event["currency"],
            provider_payment_id=event.get("provider_payment_id"),
            failure_reason=event.get("failure_reason"),
        )
    except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as e:
        raise InvalidWebhook("Malformed webhook payload") from e
    if result.succeeded and not result.provider_payment_id:
        raise InvalidWebhook("A succeeded payment needs provider_payment_id")
    return result
