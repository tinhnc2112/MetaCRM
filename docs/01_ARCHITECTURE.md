# Architecture

Electron + React
        |
        v
FastAPI
        |
  CRM / Commerce / Inventory / Shipment / Reports
        |
    PostgreSQL

External adapters:
Facebook <-> FacebookAdapter
J&T <-> JTAdapter

## Keep existing stack
FastAPI, SQLAlchemy, Alembic, PostgreSQL, React/Vite, Electron, React Query, Zustand, WebSocket.

## Layers
API -> Application Services -> Domain/Data -> Integration Adapters.

Core services cannot import provider SDK objects or provider DTOs.

## Main services
CustomerService
ConversationService
MessageService
OrderService
InventoryService
ProductService
ShipmentService
PaymentService
ReportService
AutomationService

## Transaction rule
Commands changing order + inventory must run atomically where possible.
