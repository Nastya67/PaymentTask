# Payment endpoint

Starts a card payment for a shopping cart. The payment provider reports the
result later by webhook. Built with Flask, SQLAlchemy, Alembic and PostgreSQL.

## Run

Requires Docker.

```sh
docker compose up --build
```

This starts PostgreSQL (`localhost:5434`), runs the migrations, loads sample
data from `db/seed.sql`, starts the development server with auto reload on
`http://localhost:8000` and the job that [cancels stale payments](#stale-payments).

- Production-like run (gunicorn, no sample data):
  `docker compose -f docker-compose.yml up --build`
- Reset the database: `docker compose down -v`
- Settings: `DB_PORT` (default `5434`), `APP_PORT` (default `8000`)

## Tests

Requires the database container and [uv](https://docs.astral.sh/uv/).

```sh
docker compose up -d db
uv run pytest
```

The tests use their own database, `shop_test` on the same server. It is
created and migrated automatically and emptied before every test, so the
development data stays untouched. Set `TEST_DATABASE_URL` to use another one;
its name must end with `_test`.

## API

### Start a payment

`POST /carts/{cart_id}/payments`

| Header | |
|---|---|
| `X-User-Id` | Id of the calling user. See [Authentication](#authentication). |

Body (optional): `{"payment_method_id": "<uuid>"}`. Without it, the user's
default payment method is used.

Reserves the products, creates a `pending` payment and asks the provider to
charge the card. Response `202 Accepted`:

```json
{"id": "…", "cart_id": "…", "status": "pending", "amount": "70.00", "currency": "USD"}
```

| Status | Reason |
|---|---|
| 401 | Missing or invalid `X-User-Id` |
| 404 | Cart not found, or it belongs to another user |
| 409 | Cart is not active, a payment is already in progress, or products are out of stock |
| 422 | Invalid body, payment method not found, empty cart, or invalid total |

Example with the sample data:

```sh
curl -X POST localhost:8000/carts/c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1/payments \
  -H 'X-User-Id: 11111111-1111-1111-1111-111111111111'
```

### Provider webhook

`POST /webhooks/payment-result`

```json
{
  "type": "payment.succeeded",
  "payment_id": "<our payment id>",
  "amount": "70.00",
  "currency": "USD",
  "provider_payment_id": "ch_123"
}
```

`type` is `payment.succeeded` or `payment.failed` (with `failure_reason`).

| Status | Reason |
|---|---|
| 200 | Processed, or ignored because the payment is already resolved |
| 400 | Malformed payload |
| 404 | Unknown payment |

Example: confirm the payment started above.

```sh
curl -X POST localhost:8000/webhooks/payment-result -d '{
  "type": "payment.succeeded", "payment_id": "<id from the start response>",
  "amount": "70.00", "currency": "USD", "provider_payment_id": "ch_123"}'
```

## Database schema

Alembic migrations are in `migrations/versions`:

- `0001_base_schema.py`: the base schema given by the task.
- `0002_payments.py`: the `payments` table and its indexes.

## How a payment works

1. **Start** (one transaction): lock the cart, check that it can be paid,
   reserve the stock, get the total, insert the payment as `pending`, commit.
2. **Call the provider** outside any transaction, with the payment id as the
   reference. The provider uses it as the idempotency key and sends it back in
   the webhook. The payment is committed first, so a crash after the call
   still leaves a record.
3. **Webhook** (one transaction): lock the payment. On success, mark it
   `succeeded` and the cart `checked_out`. On failure, mark it `failed` and
   release the stock. The cart can then be paid again.

## Stale payments (creative impulse :)

A payment stays `pending` if its webhook never arrives, for example when the
provider was unavailable. Until it is resolved, its cart stays blocked and its
stock reserved. A missing webhook does not mean the payment failed: the card may
be charged.

The CLI command `cancel-stale-payments` asks the provider to cancel every
payment still `pending` after 24 hours, by our payment id:

```sh
docker compose exec app flask --app app:create_app cancel-stale-payments
```

| Provider answer | Action |
|---|---|
| cancelled, or never received | Failed, stock released |
| already succeeded / failed | Resolved like the webhook would |
| unavailable | Left pending, tried again on the next run |

So the stock is released only once the provider confirms that there is no
charge. The `cancel-stale-payments` service in Docker Compose runs the command
every hour. In production, schedule it with the platform's scheduler instead
(e.g. a Kubernetes CronJob). 

## Authentication

The API does not authenticate users itself. It trusts the `X-User-Id` header just for the 
test-task purpose.

The webhook is not authenticated either: anyone who can reach it can mark a
payment as paid. In production it must verify the provider's signature.

## Assumptions

- The total calculation service is mocked as the sum of the cart items. A cart
  holds products in one currency only.
- The payment provider is mocked (`app/payments/provider.py`). It accepts every request,
  except for card tokens containing `unavailable`, where it does not answer.
  The result arrives only by webhook. 
- Stock is reserved when the payment starts and released if it fails.
- Products cannot be added to or removed from a cart while its payment is
  `pending`. The cart service (outside this project) has to enforce that.
