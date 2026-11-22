# Hướng dẫn Cài đặt Viral Content Hunter trên Windows 11

Tài liệu này hướng dẫn chi tiết cách cài đặt, cấu hình và khởi chạy hệ thống **Viral Content Hunter** từ con số 0 trên máy tính cá nhân sử dụng hệ điều hành Windows 11.

---

## 1. Nguyên tắc Chi phí 0 Đồng (Zero Extra Cost)

Dự án tuân thủ nghiêm ngặt yêu cầu của chủ máy:
- **Tuyệt đối không phát sinh thêm chi phí**: Không sử dụng các API trả phí theo lượt dùng (Anthropic API, OpenAI API, Gemini API qua Google AI Studio, Vertex AI).
- **Không sử dụng dịch vụ đám mây trả phí**: Không cần thuê VPS, cloud database hay dịch vụ proxy/giải CAPTCHA có phí.
- **Tận dụng các gói AI đã có sẵn**: Sử dụng AI thông qua các phiên đăng nhập sẵn có trên máy cá nhân bằng các công cụ dòng lệnh (CLI) chính thức (Claude Code, Codex companion, Antigravity `agy`).

---

## 2. Yêu cầu Hệ thống

Trước khi bắt đầu, hãy đảm bảo máy tính của bạn đã cài đặt các công cụ sau:

1. **Hệ điều hành**: Windows 11 (64-bit).
2. **Python**: Phiên bản **3.12** trở lên (Khuyến nghị Python 3.12).
   - *Lưu ý*: Trong quá trình cài đặt Python trên Windows, bắt buộc phải tích chọn ô **"Add python.exe to PATH"**.
3. **Node.js**: Phiên bản **20 LTS** trở lên (kèm `npm`).
4. **Git for Windows**: Để tải và cập nhật mã nguồn dự án.
5. **Trình duyệt web**: Microsoft Edge, Google Chrome, Brave hoặc Mozilla Firefox.

---

## 3. Quy trình Cài đặt Từng Bước

### Bước 1: Mở PowerShell tại Thư mục Dự án

Nhấn phím `Windows + S`, gõ `PowerShell`, chuột phải và chọn **Run as Administrator** (hoặc mở cửa sổ PowerShell thông thường). Sau đó di chuyển vào thư mục dự án:

```powershell
cd "D:\Agent Viral Content Hunter"
```

### Bước 2: Chạy Script Cài đặt Tự động

Chạy script cài đặt đã được chuẩn bị sẵn:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1
```

> **Script sẽ tự động thực hiện các tác vụ sau:**
> 1. Kiểm tra phiên bản Python (yêu cầu ≥ 3.12) và Node.js (yêu cầu ≥ 20).
> 2. Tạo môi trường ảo Python tại thư mục `.venv`.
> 3. Cài đặt toàn bộ thư viện backend ở chế độ editable (`pip install -e ".[test]"`).
> 4. Cài đặt các gói phụ thuộc và biên dịch giao diện Dashboard (`npm install` và `npm run build` trong thư mục `dashboard/`).
> 5. Khởi tạo file cấu hình cá nhân `config/settings.local.toml` từ file mẫu `config/settings.example.toml` (nếu chưa có).

---

## 4. Thiết lập Cấu hình và Xác thực

### Bước 3: Không cần mật khẩu cho Dashboard

Dashboard **không có đăng nhập**: máy chủ chỉ lắng nghe `127.0.0.1` và từ chối request từ tên máy khác hoặc từ trang web lạ. Bạn không phải tạo mật khẩu. Chỉ có token của Claude Leader (Bước 4) là bắt buộc để duyệt brief.

### Bước 4: Tạo Token Dịch vụ cho Claude Leader (Claude Service Token)

Claude Leader chịu trách nhiệm duyệt 100% Content Brief trước khi xuất bản lên Inbox. Để cấp quyền cho Claude Leader gửi quyết định kiểm duyệt, hãy tạo một chuỗi ngẫu nhiên tối thiểu 32 ký tự ASCII (chỉ gồm chữ cái, số và dấu gạch nối/dưới).

Ví dụ trong PowerShell:
```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Sao chép chuỗi sinh ra và điền vào `config/settings.local.toml`:
```toml
[auth]
claude_service_token = "chuoi_token_ngau_nhien_toi_thieu_32_ky_tu_o_day"
```

---

## 5. Cấu hình Telegram Bot (Thông báo P1 & Bàn giao Sản xuất)

Telegram giúp nhận cảnh báo tin tức khẩn cấp (P1) và đồng bộ trạng thái bàn giao với đội sản xuất video.

### 5.1. Tạo Bot trên Telegram
1. Mở ứng dụng Telegram, tìm tài khoản chính thức: `@BotFather`.
2. Gửi lệnh: `/newbot`.
3. Đặt tên hiển thị cho Bot (ví dụ: `Viral Content Hunter Alert`).
4. Đặt username cho Bot (phải kết thúc bằng chữ `bot`, ví dụ: `my_viral_hunter_bot`).
5. `@BotFather` sẽ cấp cho bạn một chuỗi token dạng: `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`. Đây chính là **`TELEGRAM_BOT_TOKEN`**.

### 5.2. Lấy Chat ID của Bạn hoặc Nhóm
1. Bấm **Start** trong cuộc trò chuyện với bot vừa tạo và gửi một tin nhắn thử nghiệm (ví dụ: `hello`).
2. Mở trình duyệt web và truy cập vào đường dẫn sau (thay `<TELEGRAM_BOT_TOKEN>` bằng mã token nhận được từ bước trên):
   ```text
   https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
   ```
3. Trình duyệt sẽ hiển thị nội dung JSON trả về:
   ```json
   {
     "ok": true,
     "result": [
       {
         "update_id": 123456789,
         "message": {
           "message_id": 1,
           "from": { "id": 987654321, "first_name": "Admin" },
           "chat": {
             "id": 987654321,
             "first_name": "Admin",
             "type": "private"
           },
           "date": 1700000000,
           "text": "hello"
         }
       }
     ]
   }
   ```
4. Tìm giá trị `"chat": {"id": 987654321, ...}`. Con số `987654321` chính là **`TELEGRAM_CHAT_ID`** của bạn.

### 5.3. Lưu Cấu hình vào File `config/hunter.env`
Tạo file `config/hunter.env` (file này đã nằm trong `.gitignore`, tuyệt đối an toàn và không bao giờ bị lộ lên git):

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=987654321
```

---

## 6. Khởi tạo Dữ liệu Ban đầu (Seed Sources)

Trước khi khởi chạy, hãy nạp danh mục các nguồn thu thập tin tức ban đầu (Hacker News, Google Trends Việt Nam, Wikimedia):

```powershell
.\.venv\Scripts\python.exe -m hunter.runtime seed-sources
```

Lệnh này sẽ khởi tạo cơ sở dữ liệu SQLite tại `backend/data/hunter.sqlite3` và nạp sẵn các nguồn hợp lệ.

---

## 7. Khởi chạy và Truy cập Dashboard

### 7.1. Chạy Trực tiếp (Foreground)
Để theo dõi log trực tiếp trong cửa sổ dòng lệnh:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\start-hunter.ps1
```

### 7.2. Chạy Nền (Background)
Nếu muốn hệ thống chạy ẩn trong nền để bạn rảnh tay làm việc khác:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\start-hunter.ps1 -Background
```

### 7.3. Truy cập Dashboard
Mở trình duyệt web và truy cập:
👉 **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

Dashboard mở thẳng, không cần đăng nhập.

---

## 8. Đăng ký Tự động Khởi động cùng Windows (Tùy chọn)

Nếu muốn hệ thống tự động khởi chạy mỗi khi bạn đăng nhập vào Windows:

1. Chạy thử nghiệm để kiểm tra thông số (Dry Run):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\windows\register-autostart.ps1
   ```
2. Áp dụng thay đổi vào hệ điều hành (không cần quyền Administrator):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\windows\register-autostart.ps1 -Apply
   ```

Khi cần hủy tự động khởi động:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\unregister-autostart.ps1 -Apply
```
