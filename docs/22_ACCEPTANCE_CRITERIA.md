# Acceptance Criteria

Customer:
- multiple channel identities per customer
- conversations linked to customer
- atomic auditable merge

Catalog:
- 100g/200g variants
- unique SKU
- historical snapshots

Inventory:
- physical/reserved/available correct
- no oversell
- every mutation audited

Order:
- one model/service for Facebook and POS
- server-side totals
- confirm reserves
- cancel releases
- lifecycle validated
- historical cost preserved

J&T:
- mock returns tracking number
- adapter boundary
- retry is idempotent

RBAC:
- staff can sell/care
- staff cannot see COGS/profit
- admin can manage staff/reports

Facebook:
- duplicate webhooks harmless
- Messenger reply works
- comment reply works

Reports:
- recognized revenue and COGS reproducible

UX:
- order can be created from open conversation without leaving Inbox
- POS can complete sale directly
