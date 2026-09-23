# Domain Model

## CRM
Customer
CustomerIdentity
ChannelAccount
Conversation
Message
Comment
Tag
CustomerTag
Assignment
CustomerNote
CustomerTimeline

## Commerce
Product
ProductVariant
Warehouse
InventoryBalance
InventoryMovement
InventoryReservation
Order
OrderItem
Payment
Promotion
Shipment
ShipmentEvent
OrderEvent

## Key relationships
Customer 1:N Identity
Customer 1:N Conversation
Customer 1:N Order
Conversation 1:N Message
Product 1:N Variant
Variant 1:N InventoryBalance
Order 1:N OrderItem
Order 1:N Reservation
Order 0:1 Payment
Order 0:1 Shipment
Shipment 1:N ShipmentEvent

## Channel model
Channel = FACEBOOK | INSTAGRAM | TIKTOK | ZALO.
CustomerIdentity maps channel + external_id to Customer.
