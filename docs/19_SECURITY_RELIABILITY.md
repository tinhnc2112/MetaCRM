# Security & Reliability

Secrets:
- backend-only
- encrypted at rest
- never log tokens
- redact secrets

Auth:
- secure password hashing
- session/token revocation
- protected endpoints

Authorization:
server-side on every command.

Webhooks:
signature verification, idempotency, replay protection where supported, payload limits.

Reliability:
structured logs, request IDs, provider retries with backoff, failed-event records, backups.

Data integrity:
Decimal/Numeric money, transactions, row locks, append-only event histories.
