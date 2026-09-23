# Test Strategy

## Unit
order totals, state transitions, stock availability, reservation, customer merge, permissions, automation, J&T status mapping.

## Integration
migrations, order+inventory transaction, merge, Facebook idempotency, J&T adapter, shipment updates, WebSocket.

## Golden E2E
Facebook message -> customer -> reply -> order -> address -> confirm -> reserve -> J&T mock shipment -> tracking -> delivered -> COD collected -> stock sold -> reports updated.

## Failure
duplicate webhook, duplicate shipment retry, insufficient stock, cancel after shipment, delivery failure/return, concurrent last-stock orders, unauthorized reports, duplicate merge.
