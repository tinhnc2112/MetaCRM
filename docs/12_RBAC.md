# RBAC

Roles:
ADMIN
STAFF

STAFF:
- Messenger view/reply
- comments view/reply
- assignment
- customer view/edit
- order view/create/edit/cancel

ADMIN additionally:
- products
- inventory receive/adjust
- shipment administration
- reports
- COGS/profit
- staff
- integrations/settings

Backend enforces permissions.
Frontend checks are UX only.

Audit actor for order cancellation, inventory adjustment, shipment manual override, customer merge and staff changes.
