# WebSocket Events

Events:
conversation.created
conversation.updated
message.created
message.sent
comment.created
assignment.updated
customer.updated
order.created
order.updated
inventory.updated
shipment.updated
notification.created

Envelope:
event_id
event_type
occurred_at
entity_type
entity_id
payload

Client must tolerate duplicates and reconnect.
Database remains source of truth.
