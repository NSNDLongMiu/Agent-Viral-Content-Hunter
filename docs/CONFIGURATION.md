# Hướng dẫn Cấu hình Hệ thống Viral Content Hunter

Tài liệu này cung cấp danh mục chi tiết toàn bộ các khóa cấu hình, biến môi trường và nguyên tắc áp dụng trong hệ thống **Viral Content Hunter**.

---

## 1. Cơ chế Phân tầng Cấu hình

Hệ thống nạp cấu hình theo thứ tự ưu tiên từ thấp đến cao:
1. **Giá trị mặc định** được định nghĩa trong mã nguồn (`backend/hunter/config.py`).
2. **File cấu hình tĩnh cá nhân**: `config/settings.local.toml` (được tạo ra từ bản mẫu `config/settings.example.toml`).
3. **Biến môi trường**: Đọc từ file `config/hunter.env` (dành cho các thông tin nhạy cảm) hoặc biến môi trường hệ thống Windows có tiền tố `HUNTER_`. Biến môi trường sẽ **ghi đè** giá trị tương ứng trong file TOML.

---

## 2. Nguyên tắc Bắt buộc: Zero Extra Cost (0 VNĐ/tháng)

Chính sách ngân sách được khóa cứng trong toàn bộ hệ thống:
- Khóa `budget.allow_paid_api` luôn bằng `false`.
- Bất kỳ cấu hình nào cố tình đặt giá trị khác `false` sẽ khiến hệ thống phát sinh lỗi `PaidAPIForbidden` và từ chối khởi động ngay lập tức.
- Trước khi thực thi các tiến trình con tích hợp AI, hệ thống tự động loại bỏ các biến môi trường nạp khóa API tính phí (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`).

---

## 3. Bảng Tra cứu Cấu hình Chi tiết

### 3.1. Cấu hình Chung và Cơ sở Dữ liệu

| Khóa trong TOML | Biến môi trường | Kiểu dữ liệu | Mặc định | Ý nghĩa và Hướng dẫn |
|---|---|---|---|---|
| `database_path` | `HUNTER_DATABASE_PATH` | Chuỗi (Đường dẫn) | `backend/data/hunter.sqlite3` | Đường dẫn tương đối hoặc tuyệt đối tới file cơ sở dữ liệu SQLite. |

---

### 3.2. Mục `[budget]` (Chính sách Ngân sách)

| Khóa trong TOML | Biến môi trường | Kiểu dữ liệu | Mặc định | Ý nghĩa và Hướng dẫn |
|---|---|---|---|---|
| `allow_paid_api` | `HUNTER_BUDGET__ALLOW_PAID_API` | Boolean | `false` | **Khóa cứng**. Bắt buộc là `false`. Tuyệt đối không hỗ trợ API tính phí theo token. |

---

### 3.3. Mục `[queue]` (Hàng đợi Tác vụ Bền vững)

| Khóa trong TOML | Biến môi trường | Kiểu dữ liệu | Mặc định | Ý nghĩa và Hướng dẫn |
|---|---|---|---|---|
| `lease_seconds` | `HUNTER_QUEUE__LEASE_SECONDS` | Số nguyên | `60` | Thời gian (giây) một worker giữ quyền xử lý một công việc. Nếu worker bị crash, sau thời gian này tác vụ sẽ tự động được thu hồi để worker khác thực thi. |
| `retry_base_seconds` | `HUNTER_QUEUE__RETRY_BASE_SECONDS` | Số nguyên | `5` | Thời gian cơ sở (giây) cho thuật toán Exponential Backoff khi thử lại tác vụ bị lỗi tạm thời (kèm 25% jitter). |
| `claude` | `HUNTER_QUEUE__CLAUDE` | Số nguyên | `1` | Số lượng tác vụ đồng thời dành cho Claude Reviewer. |
| `codex` | `HUNTER_QUEUE__CODEX` | Số nguyên | `2` | Số lượng tác vụ đồng thời dành cho Codex worker. |
| `gemini` | `HUNTER_QUEUE__GEMINI` | Số nguyên | `2` | Số lượng tác vụ đồng thời dành cho Gemini worker. |
| `collector` | `HUNTER_QUEUE__COLLECTOR` | Số nguyên | `2` | Số luồng thu thập dữ liệu công khai đồng thời từ các connector. |
| `local` | `HUNTER_QUEUE__LOCAL` | Số nguyên | `Tự động` | Số luồng xử lý cục bộ trên máy tính. Mặc định tự tính bằng: `Số nhân logic // 4` (tối thiểu là 1). |

---

### 3.4. Mục `[retention]` (Lưu trữ và Dọn dẹp)

| Khóa trong TOML | Biến môi trường | Kiểu dữ liệu | Mặc định | Ý nghĩa và Hướng dẫn |
|---|---|---|---|---|
| `days` | `HUNTER_RETENTION__DAYS` | Số nguyên | `90` | Số ngày lưu trữ hồ sơ. Các bản ghi, dữ liệu thô và fingerprint cũ hơn thời hạn này sẽ tự động bị xóa vĩnh viễn khỏi SQLite (phạm vi từ 1 đến 36500 ngày). |

---

### 3.5. Mục `[auth]` (Xác thực và Bảo mật)

| Khóa trong TOML | Biến môi trường | Kiểu dữ liệu | Mặc định | Ý nghĩa và Hướng dẫn |
|---|---|---|---|---|
| `admin_password_hash` | `HUNTER_AUTH__ADMIN_PASSWORD_HASH` | Chuỗi bí mật | `None` | Chuỗi băm mật khẩu quản trị định dạng scrypt: `scrypt$<salt_hex>$<digest_hex>`. Tạo bằng công cụ tương tác: `python -m hunter.api.auth`. |
| `claude_service_token` | `HUNTER_AUTH__CLAUDE_SERVICE_TOKEN` | Chuỗi bí mật | `None` | Mã bí mật dành riêng cho Claude Leader để gửi quyết định kiểm duyệt tại endpoint `/review/*`. Yêu cầu chuỗi ký tự ASCII ngẫu nhiên tối thiểu 32 ký tự. |
| `session_ttl_seconds` | `HUNTER_AUTH__SESSION_TTL_SECONDS` | Số nguyên | `28800` | Thời gian hiệu lực của phiên đăng nhập quản trị trên Dashboard (28800 giây = 8 giờ). |

---

### 3.6. Mục `[runtime]` (Tiến trình Chạy nền)

| Khóa trong TOML | Biến môi trường | Kiểu dữ liệu | Mặc định | Ý nghĩa và Hướng dẫn |
|---|---|---|---|---|
| `enabled` | `HUNTER_RUNTIME__ENABLED` | Boolean | `false` | Bật hoặc tắt việc tự động kích hoạt các worker quét tin và xử lý trong tiến trình nền uvicorn. |
| `draft_min_virality` | `HUNTER_RUNTIME__DRAFT_MIN_VIRALITY` | Float | `60.0` | Ngưỡng điểm lan truyền tối thiểu (0.0–100.0) để bài viết đủ điều kiện đưa vào luồng tạo brief AI. Tiết kiệm quota thuê bao AI và ưu tiên nội dung chất lượng cao. |
| `draft_min_relevance` | `HUNTER_RUNTIME__DRAFT_MIN_RELEVANCE` | Float | `45.0` | Ngưỡng điểm phù hợp tối thiểu (0.0–100.0) kết hợp với độ lan truyền để xét duyệt bài viết. |
| `max_drafts_per_scan` | `HUNTER_RUNTIME__MAX_DRAFTS_PER_SCAN` | Số nguyên | `8` | Số lượng bài viết tối đa được chọn để tạo brief AI trong mỗi lượt quét (tối thiểu 1). Giới hạn số lượng draft tránh dồn ứ hàng đợi và cạn kiệt quota. |

> [!IMPORTANT]
> **Cơ chế lọc bài Draft Gate (tiết kiệm quota AI):**
> Một bài viết bị bỏ qua (skipped) ở lượt quét hiện tại do không đủ điều kiện điểm số hoặc vượt quá trần số lượng (`max_drafts_per_scan`) sẽ được lưu trữ an toàn trong SQLite dưới dạng bằng chứng thô (`raw_items`) mà không tạo brief và không tiêu tốn lượt gọi AI Gemini. Do cơ chế chống trùng lặp (deduplication) tại tầng Ingest, các lượt quét sau sẽ coi bài viết này là trùng lặp và không đánh giá lại trong phiên bản MVP này (tính năng phát hiện xu hướng mới nổi - emerging-viral detection qua snapshot số liệu thứ hai sẽ được phát triển ở giai đoạn sau).

---

### 3.7. Cấu hình Telegram (Thông báo P1 & Bàn giao)

Các biến này được lưu trong file `config/hunter.env` và được nạp vào môi trường khi chạy script khởi động:

| Biến môi trường | Kiểu dữ liệu | Mặc định | Ý nghĩa và Hướng dẫn |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Chuỗi bí mật | `None` | Mã token do `@BotFather` cấp khi tạo Bot. |
| `TELEGRAM_CHAT_ID` | Chuỗi / Số | `None` | Chat ID của tài khoản cá nhân hoặc nhóm nhận thông báo. |

---

### 3.8. Biến Môi trường Chỉ định File Cấu hình Khác

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `HUNTER_CONFIG` | `config/settings.local.toml` | Đường dẫn tùy chọn tới file cấu hình TOML khác nếu không muốn dùng đường dẫn mặc định. |

---

## 4. Tùy chỉnh Động trên Giao diện Dashboard (Settings Page)

Bên cạnh file cấu hình tĩnh, người quản trị có thể thay đổi một số tùy chọn vận hành ngay trên trang **Settings** của Dashboard mà không cần khởi động lại ứng dụng:

- **`p1_threshold`**: Ngưỡng điểm số để xếp một bài viết vào diện Cảnh báo khẩn cấp P1 (Thang điểm 0–100, mặc định: 85).
- **`scan_intervals_minutes`**: Bản đồ chu kỳ quét của từng connector (tính bằng phút, ví dụ: Hacker News 15 phút, Google Trends 30 phút).
- **`priority_topics`**: Danh sách từ khóa hoặc chủ đề được ưu tiên săn tìm.
- **`excluded_topics`**: Danh sách từ khóa hoặc chủ đề bị loại trừ (hệ thống sẽ tự động bỏ qua nếu gặp).
- **`telegram_enabled`**: Bật hoặc tắt tính năng phát thông báo qua Telegram (`true` / `false`).

> **Tính năng Ghi nhật ký Kiểm toán (Audit Log) & Hoàn tác (Undo):**
> Mọi thay đổi thiết lập trên Dashboard đều được lưu vết chi tiết trong bảng `audit_log` kèm thời gian, người thực hiện và lý do thay đổi. Quản trị viên có thể bấm nút **Hoàn tác (Undo)** bất cứ lúc nào để quay lại trạng thái trước đó.
