# Dashboard API Reconciliation Report (T5b)

Tài liệu này ghi nhận kết quả đối soát toàn diện giữa giao diện Admin Dashboard (`dashboard/`) và tài liệu đặc tả API thực tế của hệ thống (`docs/openapi.json`, `docs/API.md`, `docs/ARCHITECTURE.md`).

Tất cả 40+ dự đoán `// TODO(reconcile with docs/openapi.json)` trước đây đã được chuẩn hóa hoặc chuyển đổi thành trạng thái trung thực không giả lập dữ liệu (no fake data, zero extra cost).

---

## 1. Xác thực (đã bỏ đăng nhập)

- **Hiện tại**: Dashboard không có đăng nhập, phiên hay phân quyền admin (theo yêu cầu của chủ dự án, 22/11/2026). Đã xóa `POST /auth/login`, `POST /auth/logout`, trang `/login`, `AuthContext` và toàn bộ xử lý token/401 ở client.
- **Thay thế**: server chỉ trả lời máy này. `backend/hunter/api/local_guard.py` từ chối request có `Host` không phải `127.0.0.1`/`localhost`/`::1`, và request ghi (POST/PUT/...) có `Origin` từ trang web lạ. Nhờ đó trang web khác đang mở trong trình duyệt không điều khiển được API.
- **Giữ nguyên**: `/review/*` vẫn cần token dịch vụ riêng của Claude Leader (quy tắc "Claude duyệt 100%" của `idead.md`). Dashboard không gọi các route này.
- *(Nội dung cũ về Bearer session đã bị gỡ bỏ cùng với mã.)*

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

---

## 4. Bổ sung hợp đồng Sản xuất bằng AI & Thẻ tiêu điểm (T9d - 22/11/2026)

Đối soát và đồng bộ giao diện theo đặc tả T9d phục vụ đội ngũ sản xuất video AI:
1. **Model DTO (`ContentBrief`, `BriefDetail`)**:
   - Thêm trường `focus_tags: FocusTag[]` ("phim_ngan", "micro_drama", "giai_tri", "ai_san_xuat"). Mặc định `[]` với hồ sơ cũ.
   - Thêm trường `ai_production: AIProduction | null` gồm `feasibility` ("CAO" | "TRUNG_BINH" | "THAP"), `approach_vi: string`, `constraints_vi: string[]`. Mặc định `null` với hồ sơ cũ.
2. **Bộ lọc Discovery Inbox (`GET /briefs/inbox`)**:
   - Bổ sung 2 tham số truy vấn tùy chọn: `ai_feasibility` và `focus_tag` (tự động loại bỏ khi rỗng/all).
   - Thêm 2 select lọc trên giao diện `InboxPage`: "Khả năng làm bằng AI" và "Nhóm nội dung", đồng bộ trực tiếp vào `react-query` cache key.
   - Hiển thị nhãn thẻ tag tiêu điểm dạng chip (`FocusTagChip`) và huy hiệu khả năng AI (`FeasibilityBadge`) trên từng hồ sơ.
3. **Chi tiết hồ sơ (`ContentDetailPage`)**:
   - Hiển thị thẻ nhóm nội dung dạng chip dưới tiêu đề bài viết.
   - Bổ sung thẻ thông tin "Khả năng làm bằng AI" (sau khối "Mức độ xác minh & Rủi ro"): hiển thị huy hiệu, phương án tiếp cận và danh sách "Ràng buộc cần lưu ý". Xử lý phòng vệ khi `ai_production` là `null` ("Chưa đánh giá khả năng làm bằng AI (hồ sơ cũ).").
   - Sửa lỗi nút bấm bàn giao Telegram: Chỉ hiển thị nút khi trạng thái là `NOT_HANDED_OFF`, `SELECTED`, `SEND_FAILED`. Khi đã `SENT` hoặc `ACKNOWLEDGED`, chỉ hiển thị trạng thái văn bản.
