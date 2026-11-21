# Hướng dẫn Vận hành Hệ thống Viral Content Hunter

Tài liệu này hướng dẫn cách vận hành hàng ngày, giám sát hệ thống, quy trình phê duyệt nội dung của Claude Leader, quản lý bàn giao và bảo trì dữ liệu trên máy tính Windows 11.

---

## 1. Quy trình Vận hành Hàng ngày

### 1.1. Khởi động và Dừng Hệ thống

- **Khởi động chạy nền**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\windows\start-hunter.ps1 -Background
  ```
- **Kiểm tra trạng thái**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\windows\status.ps1
  ```
  Script `status.ps1` sẽ kiểm tra:
  - Tiến trình giám sát (Supervisor) và tiến trình API uvicorn có đang chạy hay không (PID, RAM sử dụng).
  - Trạng thái phản hồi của cổng mạng và endpoint kiểm tra sức khỏe `http://127.0.0.1:8000/api/health`.
  - Dung lượng file cơ sở dữ liệu SQLite (`backend/data/hunter.sqlite3`).
  - 15 dòng nhật ký (log) mới nhất.

- **Dừng hệ thống an toàn**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\windows\stop-hunter.ps1
  ```
  Script sẽ gửi tín hiệu dừng nhẹ nhàng (graceful shutdown), chờ tiến trình con lưu trữ trạng thái hàng đợi và đóng kết nối cơ sở dữ liệu. Sau 8 giây nếu tiến trình chưa dừng hẳn mới cưỡng chế dừng (`force kill`) và dọn sạch file PID.

- **Theo dõi nhật ký trực tiếp**:
  ```powershell
  Get-Content -Path .\logs\hunter-*.log -Wait -Tail 30
  ```

---

## 2. Cơ chế Kiểm duyệt Nội dung của Claude Leader

Theo quy định tại `idead.md` (§1 và §11), **Claude đóng vai trò Tech Lead và Quality Reviewer**, chịu trách nhiệm kiểm duyệt 100% hồ sơ Content Brief trước khi tin tức được phép xuất hiện tại Discovery Inbox trên Dashboard.

### 2.1. Vòng đời Trạng thái của Content Brief

```text
[Thu thập dữ liệu]
       │
       ▼
   COLLECTED  ──►  PREPROCESSED  ──►  PROCESSING  ──►  PENDING_CLAUDE_REVIEW
                                                               │
                                  ┌────────────────────────────┼───────────────────────────┐
                                  ▼                            ▼                           ▼
                         APPROVED_BY_CLAUDE            REVISION_REQUIRED           REJECTED_BY_CLAUDE
                                  │                            │
                                  ▼                            ▼
                           [Discovery Inbox]            PROCESSING (Sửa tối đa 2 vòng)
                                                               │
                                                               ▼ (Nếu vẫn không đạt)
                                                          REVIEW_FAILED
```

- **COLLECTED**: Bản tin thô vừa được quét từ nguồn công khai.
- **PREPROCESSED**: Dữ liệu đã được chuẩn hóa, trích xuất metadata và loại bỏ tin trùng lặp bằng dấu vân tay (fingerprint).
- **PROCESSING**: AI Worker (Codex / Gemini) phân tích nội dung, chấm điểm và tạo bản tóm tắt tiếng Việt 50–100 từ.
- **PENDING_CLAUDE_REVIEW**: Nộp bản thảo hồ sơ lên hàng đợi chờ Claude Leader xem xét.
- **Quyết định của Claude**:
  - `APPROVED_BY_CLAUDE`: Đạt chuẩn chất lượng. Hồ sơ lập tức hiển thị trên **Discovery Inbox** để Quản trị viên theo dõi.
  - `REVISION_REQUIRED`: Chưa đạt yêu cầu (ví dụ: tóm tắt chưa đủ thông tin, thiếu căn cứ). Claude gửi nhận xét yêu cầu sửa. Mỗi hồ sơ được sửa tối đa 2 vòng.
  - `REJECTED_BY_CLAUDE`: Bị từ chối (nội dung rác, sai sự thật hoặc không có giá trị khai thác).
  - `REVIEW_FAILED`: Sau 2 vòng sửa đổi nhưng vẫn không đạt tiêu chuẩn. Hồ sơ này chỉ hiển thị tại màn hình giám sát để Quản trị viên rà soát thủ công nếu cần.

### 2.2. Kiểm duyệt Thủ công qua CLI (Khi Cần thiết)

Ngoài chế độ chạy tự động, khi Claude hoạt động trong phiên làm việc của Leader, bạn có thể thực hiện kiểm duyệt trực tiếp từ dòng lệnh:

1. **Xem danh sách các hồ sơ đang chờ duyệt**:
   ```powershell
   .\.venv\Scripts\python.exe -m hunter.leader pending
   ```
2. **Thực hiện đánh giá và đưa ra quyết định**:
   ```powershell
   .\.venv\Scripts\python.exe -m hunter.leader decide
   ```

---

## 3. Quy trình Bàn giao Nội dung sang Đội Sản xuất (Handoff)

Hệ thống săn tin tự động dừng lại ở việc cung cấp Content Brief hoàn chỉnh, có nguồn gốc và căn cứ xác thực. Việc bàn giao sang đội sản xuất video được thực hiện thông qua Dashboard và Telegram:

1. **Chọn bài trên Discovery Inbox**: Quản trị viên duyệt các bài đã được Claude chấp thuận (`APPROVED_BY_CLAUDE`), xem chi tiết điểm số (Virality, Relevance, Credibility) và bấm **Chọn bàn giao**.
2. **Theo dõi trên Handoff Board**:
   - `SELECTED`: Đã chọn, chuẩn bị gửi đi.
   - `SENT`: Đã phát tin nhắn sang nhóm Telegram của đội sản xuất (kèm link Dashboard và mã biên nhận `delivery receipt`).
   - `ACKNOWLEDGED`: Thành viên đội sản xuất đã bấm nút xác nhận tiếp nhận trực tiếp trên Telegram. Trạng thái này sẽ đồng bộ ngược về Dashboard.
   - `SEND_FAILED`: Gửi thất bại do mạng hoặc lỗi Telegram; hệ thống cho phép bấm gửi lại an toàn nhờ khóa chống gửi trùng lặp (`deduplication key`).

---

## 4. Cơ chế Sao lưu và Chính sách Lưu trữ 90 Ngày (Retention)

### 4.1. Tự động Thanh lọc sau 90 Ngày
Theo quy tắc tại `idead.md` §18:
- Mỗi khi hệ thống khởi động và định kỳ **mỗi 24 giờ**, tác vụ ngầm `RetentionService.purge()` sẽ tự động xóa các bản ghi cũ hơn **90 ngày** (hồ sơ brief, dữ liệu thô, dấu vân tay chống trùng, lịch sử kiểm duyệt và phản hồi).
- Việc thanh lọc diễn ra hoàn toàn tự động, giúp cơ sở dữ liệu SQLite luôn nhỏ gọn và hoạt động nhanh trên máy tính cá nhân.

### 4.2. Sao lưu Cơ sở Dữ liệu Cục bộ (Backups)
Cơ sở dữ liệu của hệ thống được lưu tại file duy nhất: `backend/data/hunter.sqlite3`.
Vì SQLite chạy ở chế độ **WAL (Write-Ahead Logging)**, việc sao chép file trực tiếp bằng Windows Explorer khi ứng dụng đang chạy có thể tạo ra bản sao lưu không toàn vẹn. Hãy sử dụng lệnh sao lưu an toàn sau:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; src = sqlite3.connect('backend/data/hunter.sqlite3'); dst = sqlite3.connect('backend/data/hunter_backup_' + import_time if False else 'backend/data/backup.sqlite3'); src.backup(dst); dst.close(); src.close(); print('Backup completed successfully.')"
```

> **LƯU Ý QUAN TRỌNG VỀ BẢN SAO LƯU:**
> Các bản sao lưu do người dùng tự tạo cũng phải tuân thủ chính sách bảo mật và thời hạn lưu trữ 90 ngày. Không lưu trữ các bản backup quá hạn chứa thông tin dữ liệu đã bị thanh lọc.

---

## 5. Hành vi Khởi động lại và Khôi phục Hàng đợi (Crash Recovery)

Khi máy tính cá nhân bị tắt đột ngột, mất nguồn hoặc tiến trình bị dừng:
1. **Không mất tác vụ**: Toàn bộ trạng thái công việc được lưu bền vững trong cơ sở dữ liệu SQLite (`PersistentQueue`).
2. **Thu hồi lease tự động (`reclaim_expired`)**: Các công việc đang xử lý dở dang khi bị gián đoạn sẽ hết hạn giữ quyền (`lease_seconds`, mặc định 60s). Khi hệ thống bật lại, hàng đợi sẽ tự động thu hồi và xếp các tác vụ này vào danh sách sẵn sàng thực thi tiếp mà không tăng số lần thử sai.
3. **Giám sát tự phục hồi (Exponential Backoff)**:
   - Script `start-hunter.ps1` đóng vai trò là Supervisor. Nếu tiến trình backend gặp sự cố thoát bất ngờ, nó sẽ tự động khởi động lại sau một khoảng thời gian chờ tăng dần theo cấp số nhân (2s, 4s, 8s, 16s... tối đa 5 phút).
   - **Giới hạn an toàn (Circuit Breaker)**: Nếu tiến trình gặp lỗi crash liên tiếp 10 lần trong vòng 10 phút, Supervisor sẽ dừng hẳn và ghi lại thông điệp cảnh báo rõ ràng trong log để tránh lặp vòng vô tận làm đơ máy tính.

---

## 6. Hướng dẫn Đọc Màn hình Giám sát (Monitor)

Màn hình **AI & System Monitor** trên Dashboard cung cấp cái nhìn toàn diện về sức khỏe của hệ thống:

- **Monitor AI**:
  - `OK`: AI hoạt động bình thường, sẵn sàng nhận việc.
  - `QUOTA_EXHAUSTED`: AI đã chạm hạn mức sử dụng của gói đăng ký hiện tại. Hệ thống sẽ tạm dừng giao việc cho AI này và tự động phục hồi khi hạn mức được reset.
  - `AUTH_LOST`: Phiên đăng nhập CLI bị hết hạn hoặc bị đăng xuất. Cần đăng nhập lại trên dòng lệnh.
  - `UNAVAILABLE`: Không thể kết nối tới CLI hoặc công cụ bị gián đoạn.
- **Monitor Queues**:
  - `urgent`: Số lượng tác vụ ưu tiên cao (tin khẩn, duyệt lại).
  - `normal`: Số lượng tác vụ thu thập và xử lý định kỳ thông thường.
  - Các trạng thái: `queued` (đang chờ), `running` (đang chạy), `succeeded` (hoàn thành), `dead` (thất bại sau các lần thử).
- **Monitor Errors**: Danh sách chi tiết các lỗi xử lý mới nhất giúp bạn nhanh chóng phát hiện nguồn tin bị đổi cấu trúc hoặc mạng bị ngắt.
- **Monitor Briefs**: Theo dõi toàn bộ các hồ sơ đang nằm ở các bước tiền xử lý hoặc kiểm duyệt.
