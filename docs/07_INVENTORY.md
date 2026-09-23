# Inventory

One warehouse in MVP; warehouse_id remains in schema.

InventoryBalance:
physical_quantity
reserved_quantity
available = physical - reserved

InventoryMovement:
RECEIVE
SALE
RETURN
ADJUSTMENT
DAMAGE

InventoryReservation:
ACTIVE
RELEASED
CONSUMED

## Lifecycle
DRAFT: no stock effect.
CONFIRMED: reserve.
CANCELLED before shipment: release.
SHIPPED: consume reservation and decrement physical stock.
RETURNED: explicit return receipt -> RETURN movement.

## Concurrency
Lock InventoryBalance rows during mutations.
All stock changes transactional.
No overselling.
