# Facebook / Messenger

## MVP
- Connect Page
- receive/send Messenger messages
- unread/read
- conversation assignment
- customer linking
- customer profile
- order creation from conversation
- comments
- comment replies
- post context

## Flow
Meta webhook
-> verify
-> idempotency
-> persist/queue
-> normalize
-> core command
-> DB
-> WebSocket
-> desktop

Provider credentials are backend-only and encrypted.
Core receives normalized commands, never Meta SDK objects.
