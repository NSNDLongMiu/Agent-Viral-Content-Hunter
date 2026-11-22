# Báo cáo kiểm thử MVP (ngày 22/11/2026)

Báo cáo này ghi những gì **đã được chạy thật** và kết quả thật, kể cả phần chưa đạt. Không có dữ liệu giả: mọi mục thu thập, URL, số liệu trong lần chạy thử đều lấy từ nguồn công khai thật và được đối chiếu lại với nguồn.

## 1. Môi trường
Windows 11, Python 3.12, Node 24, máy cá nhân (10 lõi, 32 GB RAM). Gemini qua Antigravity CLI (`agy`), Codex qua đăng nhập gói ChatGPT, Claude Code làm Leader duyệt hồ sơ. Không có API key, không dịch vụ trả phí.

## 2. Kiểm thử tự động
`python -m pytest -q` (đặt `--basetemp` vào thư mục riêng vì `%TEMP%\pytest-of-<user>` có thể bị từ chối quyền): **300 test, 299-300 qua tùy lần chạy** (sau khi bỏ đăng nhập dashboard; trước đó ghi 299 qua), 37 subtest. Một test về lease của worker chập chờn, kể cả trên bản trước thay đổi (xem `docs/LIMITATIONS.md` mục 21). Script Windows có bài tự kiểm thử riêng `scripts/windows/selftest.ps1`: 4/4 PASS bằng tiến trình giả (không đụng tiến trình thật).

## 3. Chạy thử đầu-cuối trên dữ liệu thật
Một tiến trình duy nhất (API + dashboard + bộ lập lịch + orchestrator + poller Telegram), cơ sở dữ liệu mới, ba nguồn thật.

| Bước | Kết quả thật |
|---|---|
| Thu thập | 110 mục: Hacker News 50, Wikipedia 50, Google Trends VN 10. 3 job thành công, 0 chết |
| Chống trùng | Trong lần trial: 300 fingerprint cho 110 mục, không có URL trùng. Thu thập lần hai được chạy ở kiểm thử ingest riêng với dữ liệu thật: 0 mục mới, 60/60 trùng (chưa lặp lại ở lần trial này) |
| Bộ lọc soạn brief | 12/110 mục được chọn (tối đa 8 mỗi nguồn) |
| Gemini soạn brief | 12 brief tiếng Việt; 19 lượt soạn gồm 7 lượt sửa; tóm tắt 66-99 từ |
| Claude duyệt (qua khóa dịch vụ riêng) | Vòng 1: 2 duyệt, 3 từ chối, 7 yêu cầu sửa. Vòng 2: 5 duyệt, 2 từ chối. Cuối: 7 vào Inbox (1 P2, 6 P3), 5 từ chối, 0 `REVIEW_FAILED` |
| Vòng sửa tự động | Bộ lập lịch tự mở vòng 1, gửi nguyên văn lý do của Claude cho Gemini, hồ sơ trở lại hàng chờ |
| Quy tắc cứng | Hồ sơ bị từ chối: chi tiết và xuất file trả 404; xuất file chỉ cho hồ sơ đã duyệt và cần đăng nhập (401 nếu không); token admin không dùng được `/api/review/*` |
| Truy cập file ngoài thư mục | 5 kiểu tấn công đường dẫn vào phần phục vụ dashboard: đều 404, không lộ file |
| Cảnh báo P1 | 0 hồ sơ P1 nên không gửi cảnh báo (đúng quy tắc). Sổ cái Telegram không có tin nào ngoài tin bàn giao |
| Bàn giao | Chọn → gửi → `SENT` có biên nhận; chọn lại trả về cùng dòng; gọi gửi hai lần chỉ có **1** tin trong sổ cái; `check-ack` trước khi bấm nút vẫn là `SENT` (đã gửi khác đã xác nhận) |
| Báo cáo gửi Telegram | Đã gửi 1 tin báo cáo tổng hợp tới đúng chat chủ dự án |

### Những gì việc duyệt của Claude đã chặn được
- 6 brief nói "đột biến", "bùng nổ", "tăng vọt" khi chỉ có **một** ảnh chụp lượt xem (không có mốc so sánh). Quy tắc của hệ thống cấm nói tốc độ tăng khi chưa có hai ảnh chụp.
- 1 brief về tuyên bố chứng minh Giả thuyết Riemann Tổng quát (Hacker News) dùng "tranh luận khoa học lớn nhất thời điểm hiện tại". Sau khi sửa phải ghi rõ đây là tuyên bố chưa được kiểm chứng.
- Từ chối hẳn: 2 tin tỷ số bóng đá trực tiếp (hết hạn nhanh, chi tiết chỉ từ tiêu đề), 1 trang danh sách người qua đời (nhạy cảm, không khai thác được), 1 hồ sơ mà chính tóm tắt thừa nhận không có thông tin, 1 hồ sơ trùng chủ đề.
- Đối chiếu nguồn thật: HN API (số bình luận, điểm), bài Guardian (tiêu đề xác nhận "ngày giao dịch thứ hai của Anthropic"), 3 trang Wikipedia (HTTP 200).

## 4. Khôi phục sau khi bị dừng giữa chừng (tiêu chí 10)
Thí nghiệm thật trên toàn hệ thống (cơ sở dữ liệu riêng, cổng riêng): giết cây tiến trình máy chủ bằng `taskkill /T /F` khi 2 job thu thập đang chạy và 1 job còn xếp hàng; khởi động lại trên cùng DB.
- Cả 13 job kết thúc `succeeded`; 2 job bị giết có lần thử 1 `expired` và lần thử 2 `succeeded`; 0 job chết.
- 110 mục, 0 fingerprint URL trùng; 5 brief, 0 mục có hai brief.
Chưa kiểm thử: tắt máy/mất điện thật, và tắt giữa lúc đang gọi AI.

## 5. Đánh giá theo tiêu chí nghiệm thu (`idead.md` §20)

| # | Tiêu chí | Kết quả |
|---|---|---|
| 1 | Dữ liệu thật từ ít nhất một connector, báo cáo khả năng/hạn chế Douyin/TikTok | **Đạt**: Hacker News, Google Trends VN, Wikimedia. Douyin/TikTok: không có đường miễn phí hợp lệ (xem LIMITATIONS) |
| 2 | URL gốc và metadata kiểm tra được | **Đạt**: đối chiếu trực tiếp với nguồn |
| 3 | Codex và Gemini thực thi tác vụ được phân công | **Một phần**: Gemini soạn brief thật. Adapter Codex chạy thật (`smoke` OK) nhưng pipeline sản phẩm chưa giao việc nào cho Codex (việc kiểm tra dữ liệu do code quy tắc làm). Codex được dùng để xây hệ thống |
| 4 | Claude duyệt trước khi lên Inbox | **Đạt**: chỉ khóa dịch vụ của Claude mới duyệt được |
| 5 | Brief tiếng Việt, tóm tắt 50-100 từ | **Đạt**: các brief đã duyệt 73-95 từ |
| 6 | Phân loại P1/P2/P3 có lý do | **Đạt phần phân loại và giải thích**. Chưa có hồ sơ P1 thật nào |
| 7 | Kiểm tra trùng | **Đạt** với trùng chính xác. Gom cụm theo chủ đề còn yếu (xem LIMITATIONS) |
| 8 | Dashboard xem, duyệt, bàn giao | **Một phần**: dashboard build được và được phục vụ cùng tiến trình, mọi luồng đã chạy thật qua API. **Chưa mở giao diện bằng trình duyệt để kiểm tra bằng mắt** |
| 9 | Telegram cảnh báo P1 và bàn giao đúng quy tắc | **Một phần**: bàn giao chạy thật; xác nhận bằng nút chạy thật ở thử nghiệm trước. Cảnh báo P1 mới kiểm thử bằng giả lập |
| 10 | Khởi động lại/dừng tiến trình không mất job | **Đạt** (mục 4), trừ tắt máy thật |
| 11 | Không dùng dịch vụ trả phí | **Đạt**: không API key, biến môi trường được gỡ khỏi tiến trình con (có test), cờ `allow_paid_api` khóa `false` |
| 12 | Ghi nhận trung thực lỗi và hạn chế | **Đạt**: tài liệu này và `docs/LIMITATIONS.md` |

## 6. Lỗi chỉ lộ ra khi chạy thật, đã sửa
Test với giả lập đều qua trong mọi trường hợp dưới đây; chỉ chạy thật mới thấy:
1. Sandbox của Codex không có mạng, không có thư mục home, chặn `taskkill`: báo cáo spike ban đầu sai (cả 8 nguồn "BLOCKED"). Chạy lại ngoài sandbox cho kết quả thật.
2. `agy -p ""` không đọc prompt từ stdin; trường `response` có thể chứa hai JSON nối nhau, phải dùng `structured_output`; lệnh bị từ chối vẫn trả `SUCCESS` với phản hồi rỗng.
3. Soạn một brief mất 145 giây với `flash-high` trong khi giới hạn là 60 giây: mọi job soạn brief chết vì timeout. Đổi sang `flash-low` (17 giây), giới hạn 180 giây/lượt.
4. Feed YouTube không có video (chỉ là mô tả PubSubHubbub) và feed thật bị `robots.txt` cấm: gỡ connector.
5. Proxy `/api` của Vite giữ tiền tố trong khi backend phục vụ ở gốc: mọi lời gọi của dashboard sẽ 404. Sửa bằng cách gắn API dưới `/api` và phục vụ dashboard cùng tiến trình.
6. Hệ thống soạn brief bằng AI cho **mọi** mục (108 job trong 20 giây): thêm bộ lọc trước khi soạn.
7. Rà soát phản biện độc lập tìm ra 7 lỗi thật, đã sửa: tệp `config/hunter.env` không nằm trong `.gitignore`; cổng cảnh báo P1 từ chối mọi nhãn xác minh nên không thể gửi cảnh báo P1; tạm dừng vì hết quota không bao giờ kết thúc; một lỗi khóa SQLite làm chết mọi worker; nhấn nút Telegram sau khi mất phản hồi gửi không được ghi nhận; script dừng có thể giết nhầm tiến trình do PID tái sử dụng (đã suýt xảy ra với Chrome của người dùng); chạy nền truyền khóa API cho tiến trình con trước khi lọc.
8. Một lần commit thiếu file do bỏ qua thông báo lỗi của `git add`: đã commit bù, thông điệp commit ghi rõ.


## 7. Lần chạy thật thứ hai: hướng phim ngắn, giải trí, làm bằng AI (22/11/2026)
Cơ sở dữ liệu mới, 5 nguồn thật (thêm báo giải trí VnExpress, Tuổi Trẻ, Thanh Niên và tìm kiếm Hacker News theo chủ đề), runtime bật, Gemini soạn, Claude duyệt, **không gửi Telegram**.

| Bước | Kết quả thật |
|---|---|
| Thu thập | 181 mục, 5 lần thu thập thành công. Đo riêng bằng bộ chấm điểm thật trên 211 mục: nhãn `giai_tri` 37 mục, `phim_ngan` 0, `micro_drama` 0, `ai_san_xuat` 1 |
| Cổng lọc | 25 mục được chọn để soạn (cổng áp dụng riêng cho từng nguồn: nhóm trọng tâm tối đa 10, nhóm chung tối đa 4 mỗi lượt quét) |
| Soạn brief | 25 brief trong khoảng 4 phút, 55 job thành công, 0 job chết |
| Duyệt vòng 1 | 1 duyệt, 17 từ chối, 7 yêu cầu sửa |
| Duyệt vòng 2 | 7 duyệt. Cuối cùng 8 hồ sơ vào Inbox, 17 bị từ chối, 0 `REVIEW_FAILED` |
| Bộ lọc Inbox | `ai_feasibility=CAO` trả 8, `focus_tag=giai_tri` trả 3, giá trị lạ trả 422; dashboard đã chụp màn hình bằng Edge chạy ẩn |

Tiêu chí duyệt dùng cho lần này (nêu rõ để quản trị đổi nếu muốn): từ chối tin về đời tư hoặc hoạt động của người thật mà Gemini tự đánh giá khả năng làm bằng AI là Thấp (9 hồ sơ người nổi tiếng, trong đó 1 hồ sơ về sức khỏe, nhạy cảm), tin thể thao trực tiếp, tin tài chính, hồ sơ trùng chủ đề (3 hồ sơ Giả thuyết Riemann trùng nhau), hồ sơ chỉ có lượt xem trang kèm từ nói về tốc độ tăng. Giữ lại và cho sửa các hồ sơ có ý tưởng GỐC làm được bằng AI (mascot hoạt hình hư cấu, minh họa sử thi thuộc phạm vi công cộng, bối cảnh giả tưởng nguyên bản).

### Lỗi chỉ lộ ra khi chạy thật lần này, đã sửa
1. **Nhãn "Giải trí" gắn cho 60/60 tin của feed giải trí** vì nhãn chuyên mục của feed bị tính như từ khóa nội dung (kể cả "Mốt trench coat", "Ẩm thực mẹ làm"). Sau sửa còn 33/60.
2. **Nhãn "Sản xuất bằng AI" gắn nhầm** cho AI voice agents, resume, bể cá. Sau sửa còn 1/21 (đúng).
3. **Độ tin cậy luôn 35 điểm** do tra bảng theo ID nguồn (UUID) thay vì tên nền tảng. Sau sửa: Wikipedia 90, Google Trends 85, Hacker News 80, báo Việt Nam 65. Hệ quả: nhiều hồ sơ lên P2 (ví dụ từ khóa "lịch âm"); độ tin cậy này đo uy tín của nguồn, không phải độ đúng của từng nội dung.
4. **`has_body_content` coi câu mô tả RSS là toàn văn**, nên brief từ báo mất dòng cảnh báo "chỉ dựa trên metadata". Đã sửa và có test hồi quy.
5. **Lời nhắc soạn chưa cấm từ tăng trưởng** khi chỉ có một ảnh chụp: gần hết brief Wikipedia viết "đột biến", "tăng vọt", "làn sóng"; có brief còn khẳng định GTA VI "chưa ra mắt" trong khi bằng chứng thu thập cùng ngày nói đã ra mắt. Đã thêm quy tắc 13 và 14 vào lời nhắc; các bản sửa đều hết lỗi này.
6. Điểm nội bộ lẫn vào tóm tắt ("bài viết ghi nhận mức độ phù hợp cao"): đã cấm trong lời nhắc, bản sửa không còn.
7. Test giả của `test_review_fixes_telegram.py` thiếu `ai_production`: đã sửa.

Test tự động sau các thay đổi: 395 test; trong ba lần chạy, hai lần qua hết, một lần chỉ fail test chập chờn `test_result_from_lost_lease_is_discarded` (`docs/LIMITATIONS.md` mục 21).
