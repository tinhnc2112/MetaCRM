# MetaCRM Milestone Log

This file tracks MetaCRM development milestones and verification status.

Status values:

- PENDING
- IN PROGRESS
- PASS
- FAIL
- NEEDS FIX
- NEEDS MANUAL UI VERIFICATION
- NEEDS MORE LOGS

---

## Current Focus

M24 — Product / Inventory Foundation Audit

Status: PENDING

Goal:

Audit the current product and inventory foundation in MetaCRM before implementing new product, stock, SKU, and inventory workflows.

---

## Completed Milestones

### M23.7 — Order Edit / Cancel UI Result

Status: PASS

Live UI: NOT VERIFIED

Reason:

No controllable browser or Electron UI surface was available.

Implemented:

- Status edit UI: Inline order-status selector inside expanded order details.
- Payment status edit: Supports unpaid, partial, paid, and refunded.
- Shipping status edit: Supports pending, packed, shipped, delivered, and cancelled.
- Cancel action: Sends only `{ "status": "cancelled" }`.
- Confirmation: Clearly warns that cancellation cannot be reversed and does not alter payment status.
- Cache invalidation: Refreshes originating customer history and summary.

Notes:

- Manual UI verification still recommended.
- Keep this result as the baseline before starting M24.

---

## Active Milestones

### M24 — Product / Inventory Foundation Audit

Status: PENDING

Objective:

Audit current product, SKU, stock, inventory, order item, and pricing foundation.

Expected output:

- Existing product/inventory files identified.
- Existing backend models/routes/services identified.
- Existing frontend product/order dependencies identified.
- Database tables and migrations related to products/inventory identified.
- Gaps listed.
- Recommended next implementation tasks proposed.

Human verification required:

```bash
git status
git diff --stat
git diff