# API Contract

Auth:
POST /api/auth/login
POST /api/auth/logout
GET /api/auth/me

Customers:
GET /api/customers
GET /api/customers/{id}
PATCH /api/customers/{id}
GET /api/customers/{id}/timeline
POST /api/customers/{id}/merge

Conversations:
GET /api/conversations
GET /api/conversations/{id}
POST /api/conversations/{id}/assign
POST /api/conversations/{id}/read

Messages:
GET /api/conversations/{id}/messages
POST /api/conversations/{id}/messages

Comments:
GET /api/comments
POST /api/comments/{id}/reply

Products:
GET /api/products
POST /api/products
PATCH /api/products/{id}
POST /api/products/{id}/variants
PATCH /api/variants/{id}

Inventory:
GET /api/inventory
POST /api/inventory/receive
POST /api/inventory/adjust
GET /api/inventory/movements

Orders:
GET /api/orders
POST /api/orders
GET /api/orders/{id}
POST /api/orders/{id}/confirm
POST /api/orders/{id}/cancel
POST /api/orders/{id}/shipment

Shipments:
GET /api/shipments
GET /api/shipments/{id}
POST /api/shipments/{id}/retry

Reports:
GET /api/reports/summary
GET /api/reports/sales
GET /api/reports/products

Integrations:
GET/POST /api/integrations/facebook/*
GET/POST /api/integrations/jt/*

Webhooks:
POST /api/webhooks/facebook
POST /api/webhooks/jt

Provider payloads never become core API contracts.
