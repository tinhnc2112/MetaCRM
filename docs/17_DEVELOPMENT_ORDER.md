# DEVELOPMENT ORDER — FINAL

The order below is mandatory because each phase depends on the previous domain.

## Phase 0 — Repository audit
- inspect current structure
- identify existing models/services/routes/UI
- run existing tests/build
- map current features to this spec
- do not modify yet except fixes needed to establish baseline

Gate: baseline tests/build documented.

## Phase 1 — M19 Customer Core
CustomerIdentity, customer_id, backfill, tags/notes ownership, merge, compatibility.

Why first:
All future orders must point to stable channel-independent customers.

Gate:
existing Messenger CRM works and customer migration passes.

## Phase 2 — M20 Product
Product/Variant, SKU, selling price, cost price, UI.

Gate:
variants can be searched and edited.

## Phase 3 — M21 Inventory
Warehouse, balances, movement ledger, reservations, receive/adjust.

Gate:
concurrent reservations cannot oversell.

## Phase 4 — M22 Order
Order, OrderItem snapshots, Payment, OrderEvent, state machine.

Gate:
Facebook/POS can use the same OrderService in tests.

## Phase 5 — M23 Facebook Commerce
Create order from Messenger, address capture, confirm, order drawer.

Gate:
complete Messenger -> confirmed order -> reserved stock.

## Phase 6 — M24 POS
POS on shared OrderService.

Gate:
POS sale creates exactly the same Order/Inventory structures.

## Phase 7 — M25 J&T Adapter
Provider interface, mock, real API contract.

Gate:
mock can create/retry/cancel shipment idempotently.

## Phase 8 — M26 Shipment
Tracking UI, webhook ingestion, normalized lifecycle, returns.

Gate:
mock webhook can drive shipment state and COD collection.

## Phase 9 — M27 RBAC
Staff/admin permissions and audit.

Gate:
staff cannot access cost/profit or staff administration.

## Phase 10 — M28 Reports
Revenue, COGS, profit, sales/product reports.

Gate:
reports reconcile against order/payment/inventory fixtures.

## Phase 11 — M29 Comments
Comment ingestion/reply/customer linking/order shortcut.

Gate:
duplicate comment webhook is harmless.

## Phase 12 — M30 Automation
Rule engine, keyword replies, tags, assignment, order draft.

Gate:
no reply loops; duplicate events do not duplicate actions.

## Phase 13 — M31 Production hardening
E2E, security, concurrency, backup/restore, logging, release.

## Dependency graph
Customer
  ↓
Product
  ↓
Inventory
  ↓
Order
  ├──→ Facebook Commerce
  └──→ POS
          ↓
       Shipment
          ↓
        J&T
          ↓
       Reports

Comments and Automation depend on CRM + Facebook.
RBAC should be progressively enforced, but full staff management follows core domains.
