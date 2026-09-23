# Skill: Code Review

## Thứ tự ưu tiên

1. Correctness, data loss, security.
2. Reliability, concurrency, transaction và failure handling.
3. API/schema compatibility và migration.
4. Performance/cost có bằng chứng.
5. Maintainability, testability, readability.
6. Style chỉ khi ảnh hưởng chuẩn dự án hoặc tooling.

## Quy trình

- Đọc mục tiêu, diff, test và context; không review chỉ theo tên hàm.
- Theo dõi input → validation → authorization → side effect → output.
- Kiểm tra null/boundary/error, resource cleanup, timeout, retry, idempotency và race.
- Kiểm tra secret/PII/log, injection, access control và dependency.
- Kiểm tra compatibility, migration, feature flag, observability và rollback.
- Đối chiếu test với risk; tìm test thiếu, flaky hoặc assertion yếu.

## Format finding

```text
[Severity] Tiêu đề — file:line
Bằng chứng: ...
Tác động: ...
Đề xuất: ...
Cách kiểm chứng: ...
```

Severity: `Blocker`, `High`, `Medium`, `Low`, `Nit`. Chỉ dùng Blocker khi không nên merge/deploy. Nếu thiếu context, đặt câu hỏi thay vì kết luận.

## Kết luận

Nêu: quyết định (`Approve`, `Comment`, `Request changes`), blocker, rủi ro còn lại, test cần chạy và rollout/rollback nếu thay đổi có rủi ro.

## Anti-pattern

Nitpick lấn át bug; yêu cầu refactor ngoài scope không có lợi ích; khẳng định performance không benchmark; đề xuất package/API chưa kiểm chứng; viết lại toàn bộ thay vì patch nhỏ có thể review.
