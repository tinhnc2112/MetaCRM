# Active HTTP and WebSocket contract

Source: `backend/app/main.py` and registered routers at this revision. This is
the implemented API; `docs/14_API_CONTRACT.md` is a future product plan.

All paths are fixed in code. `API_V1_PREFIX` was never a routing switch.
The following table inventories every registered application route.

| Method | Path | Group |
|---|---|---|
| GET | `/api/v1/system/health` | system |
| GET | `/api/v1/system/health/database` | system |
| GET | `/api/v1/system/version` | system |
| POST | `/api/v1/auth/login` | authentication |
| POST | `/api/v1/auth/refresh` | authentication |
| POST | `/api/v1/auth/logout` | authentication |
| GET | `/api/v1/auth/me` | authentication |
| GET | `/api/v1/facebook/auth/url` | facebook |
| GET | `/api/v1/facebook/auth/callback` | facebook |
| GET | `/api/v1/facebook/debug/subscribed-apps/{page_id}` | facebook |
| GET | `/api/v1/facebook/debug/token-scopes` | facebook |
| GET | `/api/v1/facebook/debug/page-permissions/{page_id}` | facebook |
| GET | `/api/v1/facebook/debug/page-info/{page_id}` | facebook |
| GET | `/api/v1/facebook/debug/app-mode` | facebook |
| GET | `/api/v1/facebook/debug/app-info` | facebook |
| GET | `/api/v1/facebook/debug/webhook-subscriptions` | facebook |
| GET | `/api/v1/facebook/debug/messenger-diagnostics` | facebook |
| GET | `/api/v1/facebook/debug/page-token/{page_id}` | facebook |
| POST | `/api/v1/facebook/debug/resubscribe/{page_id}` | facebook |
| GET | `/api/v1/facebook/debug/webhook-health` | facebook |
| POST | `/api/v1/facebook/debug/webhook-selftest` | facebook |
| POST | `/api/v1/facebook/pages/sync` | facebook |
| GET | `/api/v1/facebook/pages` | facebook |
| GET | `/api/v1/facebook/pages/current` | facebook |
| POST | `/api/v1/facebook/pages/{page_id}/select` | facebook |
| GET | `/api/v1/facebook/carriers/providers` | carriers |
| GET | `/api/v1/facebook/carrier-accounts` | carriers |
| POST | `/api/v1/facebook/carrier-accounts` | carriers |
| GET | `/api/v1/facebook/carrier-accounts/{account_uuid}` | carriers |
| PATCH | `/api/v1/facebook/carrier-accounts/{account_uuid}` | carriers |
| PUT | `/api/v1/facebook/carrier-accounts/{account_uuid}/credentials` | carriers |
| POST | `/api/v1/facebook/carrier-accounts/{account_uuid}/deactivate` | carriers |
| GET | `/api/v1/facebook/customer-tags` | customer-tags |
| POST | `/api/v1/facebook/customer-tags` | customer-tags |
| PATCH | `/api/v1/facebook/customer-tags/{tag_id}` | customer-tags |
| DELETE | `/api/v1/facebook/customer-tags/{tag_id}` | customer-tags |
| GET | `/api/v1/facebook/customer-tags/{tag_id}/customers` | customer-tags |
| GET | `/api/v1/facebook/segments` | customer-segments |
| POST | `/api/v1/facebook/segments/preview` | customer-segments |
| POST | `/api/v1/facebook/segments` | customer-segments |
| GET | `/api/v1/facebook/segments/{segment_id}` | customer-segments |
| PUT | `/api/v1/facebook/segments/{segment_id}` | customer-segments |
| DELETE | `/api/v1/facebook/segments/{segment_id}` | customer-segments |
| GET | `/api/v1/facebook/segments/{segment_id}/customers` | customer-segments |
| POST | `/api/v1/facebook/segments/{segment_id}/preview` | customer-segments |
| GET | `/api/v1/facebook/customers` | customers |
| GET | `/api/v1/facebook/customers/duplicates` | customers |
| POST | `/api/v1/facebook/customers/{primary_customer_id}/merge` | customers |
| GET | `/api/v1/facebook/customers/{customer_id}` | customers |
| PATCH | `/api/v1/facebook/customers/{customer_id}` | customers |
| POST | `/api/v1/facebook/customers/{conversation_id}/notes` | customers |
| PATCH | `/api/v1/facebook/customers/notes/{note_id}` | customers |
| DELETE | `/api/v1/facebook/customers/notes/{note_id}` | customers |
| GET | `/api/v1/facebook/customers/{conversation_id}/tags` | customers |
| POST | `/api/v1/facebook/customers/{conversation_id}/tags/{tag_id}` | customers |
| DELETE | `/api/v1/facebook/customers/{conversation_id}/tags/{tag_id}` | customers |
| GET | `/api/v1/facebook/customers/{customer_uuid}/orders/summary` | orders |
| GET | `/api/v1/facebook/orders` | orders |
| GET | `/api/v1/facebook/orders/operational-summary` | orders |
| GET | `/api/v1/facebook/orders/{order_id}` | orders |
| GET | `/api/v1/facebook/orders/{order_id}/timeline` | orders |
| POST | `/api/v1/facebook/orders` | orders |
| PATCH | `/api/v1/facebook/orders/{order_id}/shipping-address` | orders |
| PATCH | `/api/v1/facebook/orders/{order_id}` | orders |
| GET | `/api/v1/facebook/customers/{customer_uuid}/orders` | orders |
| GET | `/api/v1/facebook/products` | products |
| GET | `/api/v1/facebook/products/{product_uuid}` | products |
| POST | `/api/v1/facebook/products` | products |
| PATCH | `/api/v1/facebook/products/{product_uuid}` | products |
| DELETE | `/api/v1/facebook/products/{product_uuid}` | products |
| GET | `/api/v1/facebook/products/{product_uuid}/inventory` | inventory |
| POST | `/api/v1/facebook/products/{product_uuid}/inventory/enable` | inventory |
| POST | `/api/v1/facebook/products/{product_uuid}/inventory/disable` | inventory |
| POST | `/api/v1/facebook/products/{product_uuid}/inventory/adjustments` | inventory |
| GET | `/api/v1/facebook/products/{product_uuid}/inventory/movements` | inventory |
| POST | `/api/v1/facebook/orders/{order_id}/shipments` | shipments |
| GET | `/api/v1/facebook/orders/{order_id}/shipments` | shipments |
| GET | `/api/v1/facebook/shipments/{shipment_id}` | shipments |
| PATCH | `/api/v1/facebook/shipments/{shipment_id}/status` | shipments |
| PATCH | `/api/v1/facebook/shipments/{shipment_id}/tracking` | shipments |
| GET | `/api/v1/facebook/shipments/{shipment_id}/waybill` | shipments |
| GET | `/api/v1/facebook/shipments/{shipment_id}/carrier-operations` | shipments |
| GET | `/api/v1/facebook/webhook` | webhook |
| POST | `/api/v1/facebook/webhook` | webhook |
| GET | `/api/v1/facebook/conversations` | conversations |
| GET | `/api/v1/facebook/conversations/{conversation_id}/messages` | conversations |
| POST | `/api/v1/facebook/conversations/{conversation_id}/read` | conversations |
| POST | `/api/v1/facebook/conversations/{conversation_id}/messages` | conversations |
| GET | `/api/v1/facebook/conversations/{conversation_id}/outbound-sends/{operation_id}` | conversations |
| POST | `/api/v1/facebook/conversations/{conversation_id}/outbound-sends/{operation_id}/reconcile` | conversations |
| WS | `/api/v1/ws` | websocket |
| GET | `/version` | version |

## Authentication and errors

`POST /api/v1/auth/login` accepts a username/email and password; refresh and
logout accept a refresh token. An access bearer is required for business routes
and `GET /api/v1/auth/me`. M2 stores refresh-session state, consumes rotated
refresh credentials once and durably revokes the submitted credential on logout.
Access JWTs remain valid until expiry. Missing/invalid access credentials yield
401; authenticated accounts lacking an active admin/staff/employee role or a
required admin action yield 403. Page ownership and missing resources have
separate checks (often 404). M6's staff role is the employee role; `manager`
is not granted business access. See [security model](security-model.md) for
operation-specific permissions. The current error envelope is FastAPI's
`{"detail": ...}`; `detail` can be text or structured conflict data, so clients
should use HTTP status and endpoint-specific contract rather than assuming
all 409 payloads have the same shape.

## Public and provider operations

Both `/version` and `/api/v1/system/version` are public and return the same
name, version and environment fields; root `/health` is not registered.
`/api/v1/system/health` is public process liveness and does not probe MySQL;
`/api/v1/system/health/database` is public readiness and returns 503 on a
failed database probe. `/api/v1/facebook/webhook` GET verifies a configured
challenge token; POST verifies the raw-body Meta signature before processing.
Neither uses a staff bearer. The Facebook OAuth callback validates one-time
state, rechecks admin rights and redirects; it is not a bearer-authenticated
staff route. Facebook `/debug/*` endpoints require admin, including the
selftest and resubscription mutation. No J&T webhook or automatic live carrier
provider exists in the active API.

## Writes, retries and notifications

`GET /api/v1/facebook/customers/{customer_id}` and customer lists now include
`default_shipping_address` (nullable) beside name, phone and email. An active
employee or admin with the Customer in their selected Page can `PATCH
/api/v1/facebook/customers/{customer_id}` by canonical Customer UUID; unknown,
merged, deleted and inaccessible Customers return 404. The PATCH body may
include any of `name`, `phone`, `email`, or `default_shipping_address`.
Omitted fields remain unchanged, explicit null clears a contact field or the
entire address, and a supplied address object replaces that one current
address. Empty existing Customers remain loadable. No provider callback writes
these staff-entered fields.

At Order creation, absent `shipping_destination` copies current Customer
recipient name, phone and structured default address. A provided destination
uses the explicit order values; it does not update Customer. Name/phone/email
and delivery destination persist on the Order as historical snapshots. Later
Customer edits or merges leave those snapshots unchanged. Existing orders do
not require backfill.

Orders accept the optional `Idempotency-Key` request header on `POST
/api/v1/facebook/orders`: the key is Page/creator-scoped; replay with a
changed payload conflicts (409). Inventory adjustments use the
`idempotency_key` request field and return 409 for mismatched replay or stock
state conflicts. `POST .../messages` accepts a UUID `Idempotency-Key`; when
present, the outbound send is reserved durably before Graph I/O. An uncertain
outcome is not sent again by the same key; use the operation-status and
reconcile routes, and only reconcile with a matching Page echo. Without a key,
a retry is a new send attempt. No response shape was changed for successful
legacy sends.

The WebSocket `/api/v1/ws?page_id=<owned Page ID>` requires subprotocols
`metacrm` and `bearer.<access JWT>`; tokens in URLs are rejected. It sends
small Page-scoped notifications after database commits. The database/API is
authoritative: clients must fetch state again on reconnect, missed notification
or application reload. The connection manager is in-process only; it provides
no delivery guarantee across multiple backend workers. See [realtime behavior](realtime-contract.md) for desktop fallback and the
extension's health-only status.

## Development and migration

Use [reproducible baseline](reproducible-baseline.md) for Python 3.13, the
pinned requirements, disposable MySQL, Alembic head, Ruff baseline and client
build commands. `APP_ENV` controls security validation, not route prefixes.
No API v2 or compatibility route was added by M7.
