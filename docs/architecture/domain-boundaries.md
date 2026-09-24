# Domain boundaries and ownership

The boundaries below follow current models and service calls; they are target ownership rules, not a proposal for separate processes.

| Boundary / classification | Authoritative data and current code | Permitted cross-boundary interaction |
|---|---|---|
| Identity/access · **REFACTOR** | `app.models.auth` users/roles; `dependencies.auth` access tokens. | Authorize every action/resource server-side; Page access in `services/facebook/pages.py` complements role checks. |
| Customer · **KEEP** | `models/customer_core.py` Customer and CustomerIdentity; `services/customer_identity.py`, `services/facebook/customer_duplicates.py` merge; contact PII. | Facebook supplies scoped `(page, PSID)` identity; Order stores stable customer FK plus sale-time contact snapshots. Merge must not silently rewrite historical order snapshots. |
| Facebook channel · **KEEP / REFACTOR** | `models/facebook.py`, `models/messenger.py`; OAuth, webhook and Graph client in `services/facebook/*`. | Convert verified remote events into conversation/identity data; never own order pricing or stock. Page-scoped identity cannot be inferred solely from PSID. |
| Catalog/Product · **KEEP** | `models/products.py`, `services/facebook/products.py` page-scoped SKU/product. | Order item snapshots preserve name, SKU and unit price even if catalog changes; inventory references product. |
| Inventory · **KEEP** | `models/inventory.py`, `services/facebook/inventory.py` balance and append-only movement, unique operation keys, nonnegative check. | Order calls consume/restore helpers in caller transaction; disable/enable/adjust are inventory-owned operations. Current model is per product, not multi-warehouse. |
| Order/Payment state · **KEEP / REFACTOR** | `models/orders.py`, `services/facebook/orders.py` totals, lifecycle, payment status and OrderEvent. | Status change invokes inventory and appends event atomically. `payment_status` is recorded state; no gateway settlement is implemented. |
| Shipment/Carrier · **KEEP** | `models/shipments.py`, `models/carriers.py`, `services/facebook/{shipments,waybills,carrier_accounts}.py`; `carriers/manual.py`. | Shipment freezes recipient/COD details from Order; carrier adapter may later call remote provider. Do not represent pending operation as a successful waybill. |
| Notifications · **REFACTOR** | `api/ws.py`, `websocket/manager.py` per-process page channels. | Notify only after durable commit; consumer refetches; no durable event ownership. |
| Desktop/Extension · **KEEP / REFACTOR** | `desktop/src/services`, `desktop/src/pages`, Electron IPC; `extension/src/background`, `content`, `sidepanel`. | Clients render and initiate requests; no independent business rules. Extension currently has no authenticated WS session and must not report a rejected socket as connected. |

Actual service layout places orders, products, inventory, customer and shipment operations under `services/facebook/` even when they are core concerns. Move import locations incrementally only when changing a boundary for a demonstrated reason; no wholesale rewrite. The current Page is selected via `user_page_contexts`; sharing customers across Pages is constrained by Page access and CustomerIdentity ownership. Validate cross-Page customer merges and orders in contract/integration tests before broadening tenant scope.

Not implemented in this baseline: a separate POS/payment processor, automated J&T provider, multi-warehouse stock, production AI sales agent. Legacy root `main.py` is a separate AI Sale BOT prototype; it does not establish the active backend domain contract.
