# API Specification Checklist

## Context

- [ ] Use case, actor, owner và non-goal rõ
- [ ] Base URL/environment không chứa secret
- [ ] Contract/version và compatibility policy rõ

## Operations

- [ ] Resource/action và HTTP semantics phù hợp
- [ ] Safe/idempotent behavior được định nghĩa
- [ ] Path/query/header/body có type, required, constraint, example
- [ ] Validation và canonicalization rõ
- [ ] Response status/schema nhất quán
- [ ] Error có stable code, safe message, correlation ID

## Collection và concurrency

- [ ] Pagination có stable ordering/cursor
- [ ] Filter/sort/search có allowlist và limit
- [ ] Idempotency key có scope, TTL, conflict/replay behavior
- [ ] Concurrent update có ETag/version/transaction strategy

## Security & Privacy

- [ ] Authentication mechanism được xác minh
- [ ] Authorization theo action/resource/tenant, deny by default
- [ ] Không tin user/tenant ID do client cung cấp nếu có thể suy ra từ identity
- [ ] Rate limit/quota/abuse protection rõ
- [ ] PII/secret được tối thiểu hóa, redaction và retention rõ
- [ ] CORS/CSRF/webhook signature/replay được xét khi liên quan

## Reliability

- [ ] Timeout và retry semantics rõ
- [ ] Async operation có status/cancel/callback hoặc polling contract
- [ ] Webhook/event có duplicate, ordering, retry, DLQ/replay strategy
- [ ] Dependency failure và overload response rõ

## Evolution & Operations

- [ ] Backward compatibility và deprecation plan
- [ ] Schema examples khớp contract
- [ ] Contract/integration/negative/authz test
- [ ] Metric/log/trace không lộ dữ liệu nhạy cảm
- [ ] Rollout, monitoring và rollback criteria
- [ ] Mọi API/package/version được kiểm chứng từ nguồn chính thức
