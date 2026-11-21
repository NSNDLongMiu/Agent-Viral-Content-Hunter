# Cẩm nang Xử lý Sự cố (Troubleshooting)

Tài liệu này tổng hợp các tình huống lỗi thực tế có thể xảy ra trong quá trình vận hành hệ thống **Viral Content Hunter** trên Windows 11 và hướng dẫn chi tiết cách xử lý từng trường hợp.

---

## Mục lục Sự cố

1. [Hết hạn mức AI (AI Quota Exhausted)](#1-hết-hạn-mức-ai-ai-quota-exhausted)
2. [Mất phiên xác thực CLI (Auth Lost / Session Expired)](#2-mất-phiên-xác-thực-cli-auth-lost--session-expired)
3. [Lớp bảo vệ phản hồi rỗng của Antigravity CLI (`agy` Empty-Response Guard)](#3-lớp-bảo-vệ-phản-hồi-rỗng-của-antigravity-cli-agy-empty-response-guard)
4. [Nguồn thu thập bị chặn chính sách (Connector BLOCKED / Robots.txt)](#4-nguồn-thu-thập-bị-chặn-chính-sách-connector-blocked--robotstxt)
5. [Cổng mạng 8000 bị chiếm dụng (Port 8000 in use)](#5-cổng-mạng-8000-bị-chiếm-dụng-port-8000-in-use)
6. [Lỗi Dashboard 404 hoặc không tìm thấy `/api`](#6-lỗi-dashboard-404-hoặc-không-tìm-thấy-api)
7. [Lỗi phân quyền thư mục tạm thời trên Windows (PermissionError trong Temp)](#7-lỗi-phân-quyền-thư-mục-tạm-thời-trên-windows-permissionerror-trong-temp)
8. [Tin nhắn Telegram đã gửi nhưng không có xác nhận (Telegram Not Acknowledging)](#8-tin-nhắn-telegram-đã-gửi-nhưng-không-có-xác-nhận-telegram-not-acknowledging)

---

## 1. Hết hạn mức AI (AI Quota Exhausted)

### Dấu hiệu nhận biết
- Trên màn hình **AI & System Monitor** (`/monitor`), trạng thái của AI (Codex, Claude hoặc Gemini) chuyển sang nhãn màu cam: `QUOTA_EXHAUSTED`.
- Trong file log (`logs/hunter-*.log`), xuất hiện thông báo dạng:
  ```text
  You've hit your usage limit ... try again at <thời_gian>
  ```

### Nguyên nhân
- Gói đăng ký AI của bạn (ChatGPT Plus/Team, Claude Pro/Team, Antigravity) đã đạt giới hạn số lượng tin nhắn trong khung giờ quy định.

### Cách xử lý (Tuân thủ Quy tắc 0 Đồng)
- **Tuyệt đối không mua thêm token hoặc bấm Upgrade gói cước**: Quy tắc của dự án là không bao giờ phát sinh chi phí ngoài các gói người dùng đã thanh toán trước.
- **Hệ thống tự động bảo vệ**: Khi phát hiện lỗi hết hạn mức, hệ thống sẽ tạm dừng lấy các công việc mới cho AI đó, giữ nguyên toàn bộ các tác vụ đang chờ trong SQLite persistent queue mà không làm mất dữ liệu.
- **Hành động cần làm**: Chờ đợi đến thời điểm hạn mức được làm mới (theo mốc thời gian hiển thị trong log hoặc ứng dụng AI). Khi AI khả dụng trở lại, hệ thống sẽ tự động tiếp tục xử lý các công việc tồn đọng.

---

## 2. Mất phiên xác thực CLI (Auth Lost / Session Expired)

### Dấu hiệu nhận biết
- Màn hình Monitor báo `AUTH_LOST`.
- File log ghi nhận thông báo lỗi:
  ```text
  Your access token could not be refreshed because you have since logged out or signed in to another account
  ```

### Nguyên nhân
- Phiên đăng nhập trên CLI bị hết hạn, token bị thu hồi hoặc người dùng vừa đổi tài khoản trên trình duyệt.
- Đặc biệt với **Codex**: Tiến trình trung gian (`app-server-broker.mjs`) đôi khi vẫn lưu giữ mã token cũ ngay cả sau khi bạn đã đăng nhập lại.

### Cách xử lý
1. Mở cửa sổ dòng lệnh và thực hiện đăng nhập lại vào công cụ CLI tương ứng:
   - Với Claude Code: chạy `claude` và hoàn tất đăng nhập.
   - Với Codex: chạy công cụ companion và đăng nhập lại tài khoản.
2. Với lỗi broker của Codex: Đóng tiến trình broker cũ:
   ```powershell
   Get-Process -Name "node" | Where-Object { $_.CommandLine -like "*app-server-broker*" } | Stop-Process -Force
   ```
3. Khởi động lại hệ thống Hunter:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\windows\stop-hunter.ps1
   powershell -ExecutionPolicy Bypass -File .\scripts\windows\start-hunter.ps1 -Background
   ```

---

## 3. Lớp bảo vệ phản hồi rỗng của Antigravity CLI (`agy` Empty-Response Guard)

### Dấu hiệu nhận biết
- Hồ sơ tóm tắt tiếng Việt hoặc kết quả phân tích của Gemini bị rỗng dù tiến trình báo thành công.

### Nguyên nhân
- Thực nghiệm E1 (`docs/FEASIBILITY.md`) đã ghi nhận một hành vi đặc thù của `agy.exe`: Khi chạy ở chế độ headless (`--output-format json`), nếu một thao tác bị từ chối quyền (denied tool action), `agy` vẫn trả về mã trạng thái `status: "SUCCESS"` nhưng trường `response` trả về chuỗi rỗng `""`.

### Cách hệ thống xử lý
- Adapter tích hợp Gemini của hệ thống đã được lập trình sẵn lớp bảo vệ:
  - Bắt buộc kiểm tra `response` không được rỗng.
  - Bắt buộc kiểm tra danh sách `denied_actions` phải rỗng.
- Nếu phát hiện phản hồi rỗng vi phạm quy tắc trên, hệ thống sẽ từ chối kết quả giả mạo này, ghi nhận lỗi an toàn và đưa công việc vào danh sách thử lại sau.

---

## 4. Nguồn thu thập bị chặn chính sách (Connector BLOCKED / Robots.txt)

### Dấu hiệu nhận biết
- Tại trang **Source Manager** (`/sources`), một số connector hiển thị trạng thái `BLOCKED` (ví dụ: YouTube, Reddit, Weibo, Douyin).

### Nguyên nhân và Sự thật Kỹ thuật
- **YouTube**: Tệp tin `youtube.com/robots.txt` chính thức cấm (`Disallow`) toàn bộ công cụ tự động truy cập vào luồng tin video `/feeds/videos.xml`. Việc cố tình truy cập sẽ vi phạm điều khoản nền tảng.
- **Reddit & Weibo**: Reddit chặn các yêu cầu `.json` trực tiếp từ IP lạ; Weibo chuyển hướng mã HTTP 302 sang trang kiểm tra xác thực danh tính.
- **Douyin**: Trang web công khai không thể phân tích dữ liệu nếu không có phiên đăng nhập trình duyệt đầy đủ.

### Cách giải quyết
- Dự án tuân thủ nghiêm ngặt nguyên tắc **Trung thực (Honesty) và Không vi phạm chính sách nền tảng**:
  - Không sử dụng các dịch vụ proxy có phí hoặc công cụ bẻ khóa CAPTCHA.
  - Các connector bị cấm bởi robots.txt sẽ được giữ ở trạng thái vô hiệu hóa.
  - Hệ thống tập trung săn tin từ các nguồn hoàn toàn mở và hợp lệ: **Hacker News**, **Google Trends Việt Nam RSS**, **Wikimedia Pageviews**, và làm giàu thông tin cho các URL TikTok đã biết thông qua **TikTok oEmbed API**.

---

## 5. Cổng mạng 8000 bị chiếm dụng (Port 8000 in use)

### Dấu hiệu nhận biết
- Khi chạy `start-hunter.ps1`, script báo lỗi và dừng lại:
  ```text
  Port 8000 is already in use on 127.0.0.1. Refusing to start.
  ```

### Cách xử lý
Tìm tiến trình đang chiếm dụng cổng 8000 và dừng tiến trình đó:

```powershell
# 1. Tìm tiến trình đang lắng nghe cổng 8000
$conn = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 -State Listen
$conn | Select-Object LocalAddress, LocalPort, OwningProcess

# 2. Xem tên chương trình đang giữ cổng (thay PID bằng số thực tế)
Get-Process -Id $conn.OwningProcess

# 3. Nếu là một tiến trình cũ của Hunter bị treo, hãy tắt nó:
Stop-Process -Id $conn.OwningProcess -Force
```

Sau khi giải phóng cổng, chạy lại `start-hunter.ps1`.

### File PID cũ sau sự cố hoặc nâng cấp

Thông báo `STALE PID file` cho biết `stop-hunter.ps1` đã dọn file có thông tin tiến trình không còn khớp hoặc file định dạng cũ chỉ chứa số PID. Thao tác dọn file không gửi tín hiệu dừng tới tiến trình ghi trong file đó. Nếu phiên Hunter cũ vẫn chạy, đóng phiên PowerShell đã khởi động Hunter hoặc xác minh tiến trình giữ cổng 8000 trước khi dừng thủ công.

---

## 6. Lỗi Dashboard 404 hoặc không tìm thấy `/api`

### Dấu hiệu nhận biết
- Khi truy cập `http://127.0.0.1:8000/`, trình duyệt hiển thị màn hình trắng hoặc lỗi `404 Not Found`.
- Trình duyệt báo lỗi không thể gọi các endpoint như `/briefs/inbox`.

### Nguyên nhân
1. Thư mục `dashboard/dist` chưa được biên dịch.
2. Người dùng hoặc công cụ bên ngoài gửi request trực tiếp vào `/health` thay vì đường dẫn đúng là `/api/health`.

### Cách xử lý
1. Kiểm tra và biên dịch lại giao diện Dashboard:
   ```powershell
   cd "D:\Agent Viral Content Hunter\dashboard"
   npm install --ignore-scripts
   npm run build
   cd ..
   ```
2. Đảm bảo toàn bộ các lời gọi API từ bên ngoài đều đi qua tiền tố `/api` (ví dụ: `http://127.0.0.1:8000/api/health`, `http://127.0.0.1:8000/api/auth/login`). Giao diện Dashboard được phân phối tại gốc `/` và API được gắn tại `/api`.

---

## 7. Lỗi phân quyền thư mục tạm thời trên Windows (PermissionError trong Temp)

### Dấu hiệu nhận biết
- Lỗi xuất hiện trong log khi ứng dụng cố gắng tạo tệp tin tạm:
  ```text
  PermissionError: [WinError 5] Access is denied: 'C:\\Users\\...\\AppData\\Local\\Temp\\...'
  ```

### Nguyên nhân
- Quyền truy cập thư mục tạm thời (`%TEMP%`) của Windows bị khóa bởi phần mềm diệt virus hoặc tài khoản người dùng bị hạn chế quyền ghi.

### Cách xử lý
1. Mở PowerShell và kiểm tra khả năng ghi vào thư mục Temp:
   ```powershell
   $testFile = [System.IO.Path]::GetTempFileName()
   Remove-Item $testFile
   ```
2. Nếu gặp lỗi `Access is denied`, hãy khởi động lại máy tính hoặc cấu hình loại trừ (whitelist) thư mục dự án `D:\Agent Viral Content Hunter` khỏi danh sách quét chủ động của phần mềm diệt virus (Windows Defender).

---

## 8. Tin nhắn Telegram đã gửi nhưng không có xác nhận (Telegram Not Acknowledging)

### Dấu hiệu nhận biết
- Trên **Handoff Board**, bản tin hiển thị trạng thái `SENT` nhiều giờ liền nhưng không chuyển sang `ACKNOWLEDGED`.

### Nguyên nhân
- Hệ thống đã gửi tin nhắn thành công tới Telegram và nhận được mã biên nhận (`delivery receipt`). Tuy nhiên, người nhận (đội sản xuất) chỉ xem tin nhắn mà chưa nhấn vào nút bấm tương tác **"Xác nhận tiếp nhận"** (Inline Button) đính kèm trong tin nhắn Telegram.

### Cách xử lý
- **Không bấm gửi lại liên tục**: Hệ thống có cơ chế bảo vệ chống gửi trùng lặp (`deduplication key`). Nếu bấm gửi lại khi trạng thái chưa dứt khoát là thất bại, hệ thống sẽ chỉ tra cứu lại biên nhận cũ mà không phát tin nhắn mới nhằm tránh làm phiền nhóm chat.
- **Thao tác kiểm tra**:
  - Nhắc thành viên đội sản xuất nhấn nút xác nhận trên Telegram.
  - Trên Dashboard, bấm nút **"Kiểm tra xác nhận (Check Ack)"** để hệ thống gọi API cập nhật trạng thái mới nhất từ Telegram Bot.
