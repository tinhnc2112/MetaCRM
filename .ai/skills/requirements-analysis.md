# Skill: Requirements Analysis

## Mục tiêu

Chuyển yêu cầu mơ hồ thành phạm vi, tiêu chí chấp nhận và constraint có thể thiết kế/kiểm thử.

## Quy trình

1. Xác định problem statement, actor, outcome và success metric.
2. Tách functional requirements, NFR, business rule và constraint.
3. Xác định in-scope, out-of-scope, dependency và stakeholder.
4. Viết user journey/use case, happy path và exception path.
5. Chuyển từ ngữ mơ hồ thành metric đo được.
6. Ưu tiên Must/Should/Could; ghi rationale.
7. Viết acceptance criteria theo Given/When/Then khi phù hợp.
8. Lập assumption log, open questions và risk register.
9. Kiểm tra traceability: requirement → design → test → metric.

## Khi phải hỏi

Hỏi khi thiếu mục tiêu, actor, dữ liệu nhạy cảm, compliance, tải/SLO, hệ thống tích hợp hoặc quyền thực hiện thao tác khó hoàn tác. Nếu có thể tiến hành an toàn, nêu giả định và tác động nếu sai.

## Checklist

- [ ] Mục tiêu và non-goal rõ ràng
- [ ] Actor/quyền hạn được phân biệt
- [ ] Input/output và business invariant rõ
- [ ] Edge case, failure và abuse case được ghi nhận
- [ ] NFR có metric/điều kiện đo
- [ ] Acceptance criteria kiểm thử được
- [ ] Dependency, deadline, budget, stack constraint rõ
- [ ] Assumption và câu hỏi mở có owner/ưu tiên

## Anti-pattern

- Nhảy thẳng vào công nghệ.
- Dùng “nhanh”, “an toàn”, “scalable” không định lượng.
- Coi solution do stakeholder đề xuất là requirement.
- Bỏ qua out-of-scope và tiêu chí thành công.
