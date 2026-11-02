"""HTTP API."""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from app import errors, payment_service, provider
from app.models import Payment

bp = Blueprint("api", __name__)

ERROR_STATUS = {
    errors.CartNotFound: HTTPStatus.NOT_FOUND,
    errors.PaymentNotFound: HTTPStatus.NOT_FOUND,
    errors.CartNotPayable: HTTPStatus.CONFLICT,
    errors.PaymentInProgress: HTTPStatus.CONFLICT,
    errors.OutOfStock: HTTPStatus.CONFLICT,
    errors.CartEmpty: HTTPStatus.UNPROCESSABLE_ENTITY,
    errors.PaymentMethodNotFound: HTTPStatus.UNPROCESSABLE_ENTITY,
    errors.InvalidCartTotal: HTTPStatus.UNPROCESSABLE_ENTITY,
    errors.PaymentMismatch: HTTPStatus.UNPROCESSABLE_ENTITY,
}


class InvalidRequest(Exception):
    pass


@dataclass(frozen=True)
class PaymentResponse:
    id: uuid.UUID
    cart_id: uuid.UUID
    status: str
    amount: Decimal
    currency: str

    @classmethod
    def from_payment(cls, payment: Payment) -> "PaymentResponse":
        return cls(
            id=payment.id,
            cart_id=payment.cart_id,
            status=payment.status,
            amount=payment.amount,
            currency=payment.currency,
        )


@bp.errorhandler(errors.DomainError)
def handle_domain_error(error: errors.DomainError):
    return {"error": str(error)}, ERROR_STATUS[type(error)]


@bp.errorhandler(InvalidRequest)
def handle_invalid_request(error: InvalidRequest):
    return {"error": str(error)}, HTTPStatus.UNPROCESSABLE_ENTITY


@bp.errorhandler(provider.InvalidSignature)
def handle_invalid_signature(error: provider.InvalidSignature):
    return {"error": str(error)}, HTTPStatus.UNAUTHORIZED


@bp.errorhandler(provider.InvalidWebhook)
def handle_invalid_webhook(error: provider.InvalidWebhook):
    return {"error": str(error)}, HTTPStatus.BAD_REQUEST


@bp.post("/carts/<uuid:cart_id>/payments")
@login_required
def start_payment(cart_id: uuid.UUID):
    payment = payment_service.start_payment(
        current_user.id, cart_id, _parse_payment_method_id()
    )
    return jsonify(PaymentResponse.from_payment(payment)), HTTPStatus.ACCEPTED


@bp.post("/webhooks/payment-result")
def payment_result_webhook():
    result = provider.parse_webhook(
        request.get_data(),
        request.headers.get("X-Signature"),
        current_app.config["PAYMENT_WEBHOOK_SECRET"],
    )
    payment_service.complete_payment(result)
    return "", HTTPStatus.NO_CONTENT


def _parse_payment_method_id() -> uuid.UUID | None:
    body = request.get_json(silent=True)
    if body is None:
        return None
    if not isinstance(body, dict):
        raise InvalidRequest("Request body must be a JSON object")
    value = body.get("payment_method_id")
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise InvalidRequest("payment_method_id must be a UUID")
