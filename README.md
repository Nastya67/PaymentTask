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
- Settings: `DB_PORT` (default `5434`), `APP_PORT` (default `8000`),
  `PAYMENT_WEBHOOK_SECRET` (default `dev-webhook-secret`).

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

`X-Signature` is the hex HMAC-SHA256 of the raw body, keyed with
`PAYMENT_WEBHOOK_SECRET`.

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
| 204 | Processed, or ignored because the payment is already resolved |
| 400 | Malformed payload |
| 401 | Invalid signature |
| 404 | Unknown payment |
| 422 | Amount or currency differs from the payment |

Sending a signed webhook by hand:

```sh
body='{"type":"payment.succeeded","payment_id":"<id>","amount":"70.00","currency":"USD","provider_payment_id":"ch_1"}'
sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac dev-webhook-secret | awk '{print $NF}')
curl -X POST localhost:8000/webhooks/payment-result -H "X-Signature: $sig" -d "$body"
```

## Database schema

Alembic migrations are in `migrations/versions`:

- `0001_base_schema.py`: the base schema given by the task.
- `0002_payments.py`: the `payments` table.
- `0003_index_pending_payments.py`: index for finding stuck `pending` payments.

To print the payments schema as SQL:

```sh
DATABASE_URL=postgresql+psycopg://x@localhost/x uv run alembic upgrade 0001:0002 --sql
```

Rules the database enforces:

- At most one `pending` or `succeeded` payment per cart (partial unique index).
  This blocks double charges even under concurrent requests.
- A `succeeded` payment must have a `provider_payment_id`.
- `amount > 0`.

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

## Stale payments

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
(e.g. a Kubernetes CronJob). A late webhook is safe: resolving a payment locks it
and skips it if it is already resolved.

## Authentication

The API does not authenticate users itself. It trusts the `X-User-Id` header
and assumes an upstream API gateway:

- authenticates the user (session, OAuth, JWT, …),
- removes any `X-User-Id` header sent by the client and sets it itself,
- is the only way to reach the service.

**Risk:** if the service can be reached without that gateway, anyone can send
any user id and start payments with that user's saved cards. User ids are not
secrets. The local Docker setup publishes the port directly, so this
assumption only holds behind such a gateway.

**For production:** verify a signed token in the service, e.g. a JWT in
`Authorization: Bearer …` with the identity provider's public key, and take
the user id from its `sub` claim. Only `load_user_from_request` in
`app/auth.py` needs to change.

Authorization is enforced in the service: a user can only pay their own carts
with their own payment methods.

The webhook is authenticated separately with the HMAC signature.

## Assumptions

- The total calculation service is mocked as the sum of the cart items. A cart
  holds products in one currency only.
- The payment provider is mocked (`app/provider.py`). It accepts every request,
  except for card tokens containing `unavailable`, where it does not answer.
  The result arrives only by webhook. It cancels every payment it is asked to,
  so locally every payment without a webhook is failed and its stock released
  after 24 hours.
- Stock is reserved when the payment starts and released if it fails.
- Products cannot be added to or removed from a cart while its payment is
  `pending`. The cart service (outside this project) has to enforce that.
- Webhook signatures have no timestamp. A replayed webhook does no harm,
  because a resolved payment ignores further events.

## Out of scope

- **Refunds:** a `succeeded` webhook for a payment that already `failed` is
  logged as an error, because it needs a refund.
