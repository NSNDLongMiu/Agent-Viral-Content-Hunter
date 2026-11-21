# Dashboard API Reconciliation Report (T5b)

Tài liệu này ghi nhận kết quả đối soát toàn diện giữa giao diện Admin Dashboard (`dashboard/`) và tài liệu đặc tả API thực tế của hệ thống (`docs/openapi.json`, `docs/API.md`, `docs/ARCHITECTURE.md`).

Tất cả 40+ dự đoán `// TODO(reconcile with docs/openapi.json)` trước đây đã được chuẩn hóa hoặc chuyển đổi thành trạng thái trung thực không giả lập dữ liệu (no fake data, zero extra cost).

---

## 1. Cơ chế Xác thực & Phiên làm việc (Auth & Bearer Session)

- **Cơ chế**: Backend FastAPI sử dụng phiên đăng nhập Bearer session dạng token mờ (opaque token) lưu trong bộ nhớ tiến trình API (`POST /auth/login` nhận `{"password": "..."}` và trả về `access_token`, `token_type: "bearer"`, `expires_in`).
- **Lưu trữ**: Token được lưu trong bộ nhớ ứng dụng (`inMemoryToken`) và đồng bộ cùng tab qua `sessionStorage` (tuyệt đối không sử dụng `localStorage`).
- **Gửi kèm**: Mọi request được gắn header `Authorization: Bearer <token>`.
- **Xử lý 401 & Khởi động lại API**: Khi backend khởi động lại, các session trong bộ nhớ của backend bị hủy. Client bắt HTTP 401, tự động xóa token trong bộ nhớ và `sessionStorage`, sau đó chuyển hướng về trang `/login` với thông báo thân thiện.
- **Không có `GET /auth/me`**: Backend không có endpoint `GET /auth/me`. Tính hợp lệ của phiên đăng nhập khi tải lại trang được kiểm tra bằng request bảo vệ `GET /settings`.

---

## 2. Bảng đối chiếu Khoảng cách API (API Gaps: Màn hình → Nhu cầu → Endpoint gần nhất)

| Màn hình | Nhu cầu chức năng | Endpoint gần nhất hiện có | Trạng thái xử lý trên Dashboard |
| :--- | :--- | :--- | :--- |
| **Tổng quan (`OverviewPage`)** | Endpoint tổng hợp số liệu một lần (`GET /monitor/overview`), bao gồm số tin thô mới cào (`new_items_count`). | Ghép từ `GET /monitor/briefs`, `GET /briefs/inbox`, `GET /handoffs`, `GET /sources`, `GET /monitor/ai`, `GET /monitor/queues`, `GET /monitor/errors`. | Adapter tổng hợp từ các endpoint có sẵn. `new_items_count` hiển thị số hồ sơ trạng thái `COLLECTED` (do bảng tin thô `raw_items` là nội bộ backend). |
| **Hộp thư khám phá (`InboxPage`)** | Xem chi tiết Cụm xu hướng (`GET /briefs/clusters/{cluster_id}`). | Không có trong OpenAPI T1. Thuộc phạm vi gói T4 (`backend/hunter/{briefs,scoring}`). | Hiển thị modal thông báo trung thực: Tính năng đang phát triển bởi gói T4, chưa có API endpoint công bố. |
| **Hộp thư khám phá (`InboxPage`)** | Xem chi tiết Series Brief phim ngắn (`GET /briefs/series/{series_id}`). | Không có trong OpenAPI T1. Thuộc phạm vi gói T4 (`backend/hunter/{briefs,scoring}`). | Hiển thị modal thông báo trung thực: Tính năng đang phát triển bởi gói T4, chưa có API endpoint công bố. |
| **Hộp thư khám phá (`InboxPage`)** | Lọc theo chủ đề (`topic`). | `GET /briefs/inbox` chỉ nhận `search`, `platform`, `priority`, `content_type`, `discovered_after`. | Map giá trị `topic` vào tham số `search` khi trường tìm kiếm rỗng. |
| **Chi tiết hồ sơ (`ContentDetailPage`)** | Xuất hồ sơ ra định dạng Markdown & JSON. | `GET /briefs/{brief_id}/export/{format}` (`md` hoặc `json`). | Endpoint hiện trả về `501 Not Implemented` (chờ T4). Giao diện bắt lỗi 501 và thông báo rõ cho người dùng. |
| **Chi tiết hồ sơ & Bàn giao (`Handoff`)** | Gửi cảnh báo Telegram và kiểm tra người nhận bấm xác nhận. | `POST /handoffs/{handoff_id}/send` và `POST /handoffs/{handoff_id}/check-ack`. | Endpoint trả về `501 Not Implemented` (chờ T6 cài adapter Telegram). Giao diện thông báo rõ trạng thái chờ T6. |
| **Quản lý nguồn (`SourcesPage`)** | Lịch sử lỗi chi tiết từng lần quét của connector. | `GET /sources/health` trả về `last_error`, `status`, `last_success_at` của từng connector. | Modal chẩn đoán hiển thị trực tiếp `last_error` và thời gian thành công gần nhất từ `ConnectorHealth`. |
| **Cài đặt (`SettingsPage`)** | Lưu Bot Token và Chat ID của Telegram vào cấu hình database. | `PUT /settings/{key}` chỉ hỗ trợ khóa `telegram_enabled`. | Tuân thủ kiến trúc bảo mật: Token bot được quản lý qua biến môi trường máy chủ (`HUNTER_TELEGRAM__BOT_TOKEN`). Giao diện chỉ cho phép bật/tắt tính năng `telegram_enabled`. |
| **Cài đặt (`SettingsPage`)** | Thay đổi chính sách ngân sách (`budget_policy`). | `GET /settings` trả về `budget.allow_paid_api: false` (const). | Chính sách ngân sách 0 VNĐ được hiển thị ở chế độ **CHỈ ĐỌC (READ-ONLY)**, không bao giờ gửi thay đổi budget lên API. |

---

## 3. Các thay đổi DTO / Model trọng yếu đã đồng bộ

1. **`ContentBrief`**:
   - `title_original` → `original_title`
   - `author` → `creator`
   - `notable_reason` → `why_notable`
   - `credibility_score` → `credibility`
   - `source_url` → `original_url`
   - `metrics_recorded_at` → `metrics_snapshot_at`
   - `is_metadata_only_summary` → `metadata_only` (kèm `metadata_note_vi`)
   - `scoring_reasons` → `score_explanation` (hiển thị riêng biệt 4 điểm số theo đúng yêu cầu)
   - `review_status` → `status` (`BriefStatus`)
   - `risks_and_notes` → kiểu `string[]` (mảng chuỗi)
   - `suggested_formats` → kiểu `string[]` (mảng chuỗi)
2. **`BriefDetail`**:
   - `GET /briefs/{id}` trả về cấu trúc `{ brief: ContentBrief, review_history: ReviewDecision[] }`.
3. **`Handoff`**:
   - Trạng thái gửi: `SENT_TELEGRAM` → `SENT` (OpenAPI enum: `NOT_HANDED_OFF`, `SELECTED`, `SENT`, `SEND_FAILED`, `ACKNOWLEDGED`).
   - Trường trạng thái: `status`, lỗi gần nhất: `last_error`.
   - Chọn bàn giao: `POST /handoffs` nhận `{"brief_id": "..."}`.
   - Gửi bàn giao: `POST /handoffs/{handoff_id}/send` nhận `{"message": "..."}`.
   - Kiểm tra xác nhận: `POST /handoffs/{handoff_id}/check-ack`.
4. **`Feedback`**:
   - Giá trị enum: `bad_source` → `'bad-source'` (kết nối chính xác với FastAPI enum).
5. **`Source`**:
   - Trường trạng thái kích hoạt: `is_active` → `enabled` (boolean).
   - Trường bị chặn: `is_blocked` → `blocked` (boolean).
   - Trường ưu tiên: `priority` (integer).
   - Cập nhật nguồn: `PUT /sources/{source_id}` nhận `{"reason": "...", "source": SourceInput}`.
6. **`Settings`**:
   - Lấy cài đặt: `GET /settings` trả về `PublicSettings` gồm 4 nhóm: `preferences` (DashboardSettings), `budget` (BudgetSettings), `queue` (QueueSettings), `retention` (RetentionSettings).
   - Cập nhật cài đặt: `PUT /settings/{key}` nhận `{"reason": "...", "value": ...}` với các khóa `SettingKey`: `p1_threshold`, `scan_intervals_minutes`, `priority_topics`, `excluded_topics`, `telegram_enabled`.
   - Nhật ký kiểm toán: `GET /settings/audit` và hoàn tác `POST /settings/audit/{record_id}/undo`.
