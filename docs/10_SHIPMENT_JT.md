# Shipment / J&T

## Provider interface
create_shipment
cancel_shipment
get_tracking
parse_event
verify_event

JTAdapter implements it.
MockJTAdapter is required for development/E2E before real credentials/API access.

## Shipment
order_id, provider, tracking_number, provider_shipment_id, status, cod_amount, receiver snapshot, timestamps.

## Normalized statuses
CREATED
WAITING_PICKUP
SHIPPED
DELIVERING
DELIVERED
DELIVERY_FAILED
RETURNING
RETURNED
CANCELLED

Provider status codes remain raw metadata and are mapped to normalized states.

## Idempotency
Retrying shipment creation must not create a second parcel.

## Webhook
verify -> deduplicate -> persist raw event -> map -> transition -> ShipmentEvent -> notify UI.

Do not invent undocumented J&T API fields.
