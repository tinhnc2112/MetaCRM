# Order

## Sources
FACEBOOK and POS use one Order model/service.

## Status
DRAFT
CONFIRMED
WAITING_PICKUP
SHIPPED
DELIVERING
DELIVERED
CANCELLED
DELIVERY_FAILED
RETURNING
RETURNED

## Creation
Server validates actor, customer/address/items, loads current catalog, calculates totals and snapshots product/price/cost.

## Confirm
Validate -> lock stock -> check available -> reserve -> status CONFIRMED -> OrderEvent -> commit.

## Cancel
Validate -> release active reservation -> CANCELLED -> event -> commit.

## Total
subtotal - discount + shipping_fee.

Money calculations are server-side.
Delivered orders cannot be cancelled.
