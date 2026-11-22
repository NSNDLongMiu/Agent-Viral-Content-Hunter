# Giới hạn kỹ thuật còn tồn tại, chức năng MVP đã xong và giai đoạn tiếp theo

## A. Giới hạn đã biết (mới nhất: 22/11/2026)

### Nguồn dữ liệu
1. **Douyin và TikTok không săn được** bằng nguồn miễn phí, hợp lệ, không đăng nhập. Chỉ có TikTok oEmbed cho một URL đã biết (không có khám phá, thời gian đăng hay tương tác). Đây là giới hạn của nền tảng, không phải lỗi mã. Vì vậy tính năng "săn nội dung viral trên Douyin/TikTok" chưa làm được.
2. Reddit (`robots.txt` cấm), Weibo (chuyển hướng vào cổng đăng nhập), YouTube (feed bị `robots.txt` cấm, feed PubSubHubbub cần địa chỉ công khai): không có connector. Không né các cơ chế này.
3. Nguồn đang dùng cho tín hiệu chủ đề, không phải creator hay công thức video: Hacker News (điểm, bình luận), Google Trends VN (nhãn lượng tìm kiếm gần đúng), Wikimedia (lượt xem theo ngày, tiếng Anh).

### Chất lượng brief
4. Hầu hết brief chỉ dựa trên **metadata** (tiêu đề, lượt xem); hệ thống chưa tải toàn văn hay xem video, và phải ghi rõ điều này (đã làm).
5. Trình soạn brief còn xu hướng dùng từ tăng trưởng ("đột biến", "bùng nổ") khi chỉ có một ảnh chụp. Hiện chỉ việc duyệt của Claude chặn được; cần thêm quy tắc cấm trực tiếp vào prompt.
6. Nhãn xác minh `unverified (single source news/event claim)` được gán cho cả nội dung không phải tuyên bố (ví dụ trang Wikipedia). Quá thô, và vì cổng cảnh báo P1 từ chối nhãn `unverified*` nên các hồ sơ đó không bao giờ được cảnh báo P1.
7. Ngưỡng bộ lọc `draft_min_relevance = 45` đúng bằng điểm trung tính của mục không khớp chủ đề nào, nên thực tế chỉ lọc theo virality; Wikipedia chiếm 8/12 brief. Cần chỉnh ngưỡng (ví dụ cao hơn 45) sau khi có phản hồi thật.
8. Hai mục cùng chủ đề từ hai nguồn (Wikipedia "Riemann hypothesis" và tuyên bố của Levent Alpöge trên Hacker News) chưa được tự gom thành một Trend Cluster, nên nhãn "đối chiếu nhiều nguồn" không xuất hiện. Gom cụm hiện dựa trên URL chung và độ giống tiêu đề.
9. Mục bị bộ lọc bỏ qua sẽ bị chống trùng ở các lượt quét sau, nên nếu chỉ số của nó tăng mạnh về sau, hệ thống không đánh giá lại. Phát hiện viral sớm bằng hai ảnh chụp chưa làm.
10. Tóm tắt và phân tích do AI viết; đã đối chiếu thủ công trong lần thử nhưng không thể bảo đảm 100%. Việc duyệt của Claude là chốt chặn.

### Vận hành
11. **Claude duyệt thủ công trong một phiên Claude Code** bằng `python -m hunter.leader`. Adapter Claude chạy không giao diện bị tắt mặc định vì chưa xác minh được gói Team có bật "usage credits" tính phí hay không. Khi không có phiên Claude đang chạy, brief ở lại `PENDING_CLAUDE_REVIEW` (đúng thiết kế, nhưng nghĩa là chưa tự động hoàn toàn).
12. Cảnh báo P1 mới chỉ kiểm thử bằng giả lập: chưa có hồ sơ P1 thật nào vì dữ liệu thật hiện chỉ cho P2/P3.
13. Dashboard **chưa được mở bằng trình duyệt để kiểm tra bằng mắt** trong đợt này (build được, phục vụ đúng, API đã chạy thật). Chưa trau chuốt giao diện.
14. Bộ lập lịch thích ứng và việc xóa dữ liệu sau 90 ngày: được kiểm thử bằng đơn vị với đồng hồ giả; chưa chạy dài ngày.
15. Chưa kiểm thử tắt máy hoặc mất điện thật, và tắt giữa lúc đang gọi AI.
16. Script tự khởi động Windows mới chạy ở chế độ dry-run; **chưa đăng ký** vào máy. Người dùng cần chạy `register-autostart.ps1 -Apply` khi muốn.
17. Xác nhận bằng nút Telegram chỉ được ghi khi có poller chạy. Nếu máy chủ tắt, Telegram giữ cú bấm tối đa 24 giờ và hệ thống ghi nhận khi chạy lại.
18. Không có mô hình AI cục bộ (chưa cài runtime); phần xử lý nhẹ dùng quy tắc.
19. Hệ thống phụ thuộc đăng nhập gói của Gemini (`agy`) và Codex. Hết quota thì dừng việc đó và chờ, không chuyển sang đường trả phí. Cách `agy` báo hết quota hoặc mất đăng nhập chưa được quan sát thật.
20. Kịch bản chạy thử đầu-cuối nằm ngoài repo (thư mục tạm); số liệu và kết quả đã ghi trong `docs/TEST-REPORT.md`.
21. **Một test chập chờn**: `backend/tests/test_orchestrator_worker.py::test_result_from_lost_lease_is_discarded` fail khoảng một nửa số lần khi chạy riêng lẻ trên máy này, kể cả trên bản trước khi bỏ đăng nhập (đã kiểm tra bằng worktree ở `HEAD` gốc). Test dùng nhịp heartbeat 25 ms nên nhạy với thời gian; chưa điều tra được đây chỉ là test quá nhạy hay có race thật khi worker mất lease. Cần điều tra trước khi tin con số "tất cả test qua".
22. **Dashboard không còn đăng nhập hay phân quyền admin** (theo yêu cầu của chủ dự án, 22/11/2026). An toàn dựa vào việc server chỉ lắng nghe `127.0.0.1` và `local_guard` (từ chối `Host` không phải máy này và request ghi có `Origin` lạ). Ai dùng được máy này đều thao tác được dashboard (chọn bàn giao, gửi Telegram, đổi cài đặt). Chỉ `/review/*` còn khóa bằng token của Claude Leader để giữ quy tắc "Claude duyệt 100%". Không được bind server ra `0.0.0.0` hay mở cổng ra mạng LAN/Internet.
23. **Nguồn phim ngắn, micro-drama còn mỏng (đo ngày 22/11/2026, 211 mục thật)**: sau khi thêm báo giải trí VnExpress, Tuổi Trẻ, Thanh Niên và tìm kiếm Hacker News theo chủ đề, nhãn `giai_tri` có 37 mục nhưng `phim_ngan` và `micro_drama` có **0 mục**, `ai_san_xuat` có 1 mục (đã 6 ngày tuổi). Các nguồn miễn phí hợp lệ chỉ cho **tin tức và xu hướng**, không cho các clip phim ngắn đang viral trên TikTok, Douyin, YouTube. Cách hợp lệ còn lại: quản trị dán link clip, hệ thống lấy tiêu đề và tác giả qua oEmbed rồi soạn brief (chưa làm).
24. **Tin giải trí đa số là tin người nổi tiếng**, khả năng làm bằng AI thường chỉ ở mức Thấp (dính người thật, bản quyền). Brief vẫn có mục "Khả năng làm bằng AI" và bộ lọc Inbox để chọn các hồ sơ mức Cao. Hệ thống dùng quota Gemini để soạn cả những hồ sơ sẽ ra mức Thấp; việc ưu tiên trước các mục dễ làm bằng AI chưa có.
25. **Lỗi schema của Gemini không được nhắc sửa ngay trong lần gọi**: `pipeline/handlers.py` (`_DraftWorker.run`) biến mọi kết quả AI khác OK thành lỗi job, nên JSON sai schema (ví dụ thiếu `ai_production`) làm hàng đợi thử lại cả job (tối đa 3 lần) thay vì để trình soạn thử lại có phản hồi. Chỉ tốn thêm quota khi gặp lỗi đó.
26. **Nhãn nhóm nội dung dựa trên từ khóa** nên vẫn gắn nhầm ở mức nhẹ (ví dụ tin diễu hành di sản bị gắn `giai_tri` vì mô tả có từ "nghệ sĩ"). Việc duyệt của Claude là chốt chặn; chưa có học từ phản hồi.
27. **Độ tin cậy từng bị tính sai** (mọi hồ sơ trước 22/11 đều 35 điểm "không rõ" vì tra bảng theo ID nguồn thay vì tên nền tảng): đã sửa trong T9e. Các hồ sơ đã soạn trước đó (kể cả lần chạy thử đầu) mang điểm cũ.
28. **Trong lần chạy thật thứ hai, 17/25 brief bị từ chối** (chủ yếu tin người nổi tiếng với khả năng làm bằng AI Thấp). Hệ thống đã dùng quota Gemini để soạn các hồ sơ này; chưa có bước loại sớm trước khi soạn.
29. **Khả năng làm bằng AI do Gemini tự đánh giá nên khá rộng tay**: sau khi được hướng dẫn cụ thể, cả 8 hồ sơ vào Inbox đều ở mức Cao. Mức này là gợi ý, chưa được kiểm chứng bằng việc thực sự sản xuất; việc duyệt của Claude kiểm tra tính hợp lý, bản quyền và người thật, không kiểm tra chất lượng sản phẩm cuối.
30. **Điểm độ tin cậy cao làm nhiều hồ sơ lên P2** (ví dụ từ khóa Google Trends "lịch âm", lượt xem trang Wikipedia). P2 hiện nghĩa là "nguồn uy tín và số liệu đủ", không nghĩa là nội dung đáng chú ý hơn. Chưa có P1 thật.
31. Lần chạy thật thứ hai dùng cơ sở dữ liệu riêng và **không gửi Telegram**: nút "✅ Đã nhận" của tin bàn giao từ lần thử đầu vẫn thuộc cơ sở dữ liệu cũ.

## B. Chức năng MVP đã hoàn thành (đã chạy thật trừ khi ghi chú)
- Chạy trên Windows, một tiến trình, API dưới `/api`, dashboard cùng tiến trình.
- Connector độc lập có bật/tắt: Hacker News, Google Trends VN, Wikimedia; kiến trúc mở rộng.
- Chuẩn hóa, chống trùng chính xác (URL, id ngoài, tiêu đề), gom Trend Cluster cơ bản.
- Bộ lập lịch thích ứng, hàng đợi bền vững (khóa lease, thử lại tối đa 3 lần, hàng lỗi), khôi phục sau khi bị giết.
- Orchestrator với adapter Codex và Gemini chạy thật; Claude/Local tắt mặc định.
- Chấm điểm Virality, Relevance, Credibility, Priority tách biệt, có giải thích; phân loại P1/P2/P3.
- Content Brief tiếng Việt 50-100 từ, phân tích "vì sao đáng chú ý" có cấu trúc, xuất Markdown và JSON.
- Quy trình duyệt của Claude: tối đa 2 vòng sửa, lý do bắt buộc, chỉ hồ sơ đã duyệt lên Inbox.
- Bàn giao qua Telegram, chống gửi trùng, phân biệt đã gửi và đã xác nhận.
- Dashboard 8 màn hình (đã build; chưa kiểm tra bằng mắt).
- Kiểm soát chi phí 0 đồng, retention 90 ngày, script Windows và tài liệu.

## C. Giai đoạn tiếp theo
1. Chỉnh ngưỡng lọc và quy tắc prompt (mục 5, 7); nâng gom cụm theo thực thể/chủ đề (mục 8).
2. Phát hiện viral sớm bằng hai ảnh chụp, đánh giá lại mục bị bỏ qua.
3. Cross-Market Intelligence và Active Research (từ khóa do quản trị nhập, mở rộng đa ngôn ngữ).
4. Series Brief nâng cao; học từ phản hồi (bốn nút đánh giá đã có trên Dashboard, chưa nối vào trọng số).
5. Kiểm tra dashboard bằng trình duyệt và trau chuốt giao diện.
6. Chạy dài ngày để đo bộ lập lịch, retention và quota thật; đăng ký tự khởi động khi người dùng đồng ý.
7. Tìm đường hợp lệ cho Douyin/TikTok nếu có (ví dụ nguồn do quản trị chỉ định hoặc API chính thức miễn phí).
