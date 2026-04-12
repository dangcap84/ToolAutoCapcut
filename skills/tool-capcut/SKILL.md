---
name: tool-capcut
description: Dùng khi cần tự động xử lý CapCut project/media bằng bộ công cụ capcuttool (cli.py và các module timeline), với workflow xác nhận input-output, chạy ổn định, kiểm tra output, và báo cáo kết quả.
---

# Tool CapCut Skill

## Khi nào dùng
- User yêu cầu chạy Auto CapCut tool.
- Cần thao tác project/timeline/media theo batch hoặc theo script.
- Cần output rõ ràng để chuyển bước hậu kỳ.

## Runtime
- Base path: `capcuttool/`
- Entry chính: `capcuttool/cli.py`

## Workflow bắt buộc
1. Xác nhận input/output paths.
2. Kiểm tra dependencies tối thiểu (python/requirements).
3. Chạy command phù hợp trong `capcuttool`.
4. Validate output tồn tại và có dữ liệu.
5. Trả báo cáo ngắn gọn:
   - command đã chạy
   - input/output
   - kết quả thành công/thất bại
   - lỗi quan trọng (nếu có)

## Guardrails
- Không tự ý ghi đè output quan trọng.
- Không tự ý xóa project/media gốc.
- Nếu command không rõ, ưu tiên `python3 cli.py --help` để xác minh trước khi chạy.
