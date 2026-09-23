# Skill: API Design

## Nguyên tắc

Thiết kế contract theo domain và use case, không theo cấu trúc database. Không bịa endpoint hoặc hành vi framework; nếu cần cú pháp/version cụ thể, kiểm tra tài liệu chính thức.

## Checklist contract

- Resource/action, method và semantics rõ; thao tác safe/idempotent được xác định.
- Request/response schema có type, required, constraint, example và validation.
- Error model ổn định: machine-readable code, message an toàn, correlation ID; không lộ stack/secret.
- Authentication và authorization theo resource/action/tenant.
- Pagination có stable ordering/cursor; filter/sort có allowlist.
- Idempotency key cho create/payment/job phù hợp; định nghĩa scope, TTL và replay response.
- Concurrency control bằng version/ETag/conditional update khi cần.
- Rate limit/quota và phản hồi overload rõ.
- Timeout, retry semantics và async job/webhook/event flow rõ.
- Versioning và backward compatibility; deprecation có timeline/telemetry.
- PII classification, retention, audit và redaction.

## Event/Webhook

Định nghĩa event name, producer, consumer, schema, event ID, occurred-at, ordering key, delivery guarantee, duplicate handling, retry, dead-letter, signature verification, replay protection và schema evolution.

## Review flow

1. Map use case → operation.
2. Kiểm tra invariant và authorization.
3. Kiểm tra happy/negative/boundary/concurrency.
4. Kiểm tra compatibility và migration.
5. Sinh contract test và example.

## Anti-pattern

HTTP 200 cho mọi lỗi; offset pagination trên tập dữ liệu biến động lớn mà không cảnh báo; client tự quyết định tenant/user ID; retry POST không idempotency; breaking change âm thầm; trả dữ liệu thừa.
