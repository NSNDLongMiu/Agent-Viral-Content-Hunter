# Quy trình duyệt Content Brief của Claude Leader

Tài liệu này là quy trình làm việc của Claude Leader (`idead.md` §6.1, §11). Claude đánh giá linh hoạt theo ngữ cảnh, không dùng bảng điểm cứng, nhưng **mọi quyết định đều phải có lý do cụ thể được lưu lại**.

## Nguyên tắc cố định
- Chỉ hồ sơ `APPROVED_BY_CLAUDE` mới xuất hiện trong Discovery Inbox và mới được gửi cảnh báo P1.
- Claude không khả dụng (hết quota, mất đăng nhập, máy tắt): hồ sơ ở lại `PENDING_CLAUDE_REVIEW`. Không ai khác được tự duyệt.
- Tối đa **2 vòng sửa** cho mỗi hồ sơ. Yêu cầu sửa lần thứ ba tự chuyển hồ sơ sang `REVIEW_FAILED` để quản trị quyết định.
- Mỗi quyết định gồm: hành động, lý do cụ thể (không chung chung), và đúng số vòng (`expected_revision`) đã xem.
- Claude không bao giờ duyệt chỉ vì điểm cao. Điểm là gợi ý, bằng chứng mới là căn cứ.

## Cách chạy
```powershell
.venv\Scripts\python.exe -m hunter.leader pending            # danh sách hồ sơ chờ duyệt
.venv\Scripts\python.exe -m hunter.leader show <brief_id>    # xem đầy đủ một hồ sơ
.venv\Scripts\python.exe -m hunter.leader decide <brief_id> --action APPROVE --revision 0 --reason "..."
```
Khóa dịch vụ lấy từ biến môi trường `HUNTER_AUTH__CLAUDE_SERVICE_TOKEN`. Không in khóa ra màn hình.

## Những điều phải kiểm tra trước khi duyệt
1. **Nguồn truy xuất được:** mở được `original_url`; thông tin trong brief khớp với tiêu đề, thời gian, tác giả của nguồn. Không có URL hợp lệ thì không duyệt.
2. **Trung thực về dữ liệu:** mọi con số (lượt xem, bình luận, điểm) phải có trong bằng chứng thu thập và có thời điểm ghi nhận. Số liệu không có nguồn, số được làm tròn đẹp bất thường hoặc nội dung "đã xem" trong khi chỉ có metadata đều bị từ chối hoặc yêu cầu sửa. Hồ sơ chỉ có metadata phải ghi rõ `metadata_only` và ghi chú tiếng Việt.
3. **Tóm tắt 50–100 từ tiếng Việt:** đúng độ dài, tự nhiên, không dịch máy khó hiểu, không bịa chi tiết ngoài bằng chứng.
4. **"Vì sao đáng chú ý":** đủ bảy dòng (Hook, Định dạng, Cảm xúc/động lực chia sẻ, Nhóm người xem, Thời điểm, Khả năng khai thác ở Việt Nam, Bài học áp dụng không sao chép). Chỗ không đủ dữ liệu phải ghi "Chưa đủ dữ liệu", không đoán.
5. **Bốn chỉ số tách biệt:** Virality, Relevance, Credibility, Priority khớp với lời giải thích; không gộp thành một con số.
6. **Điều kiện P1:** điểm đạt ngưỡng, nguồn truy xuất được, có tín hiệu đáng chú ý, còn đủ mới, không trùng, đã kiểm tra rủi ro, và với tin tức hoặc sự kiện có tuyên bố thực tế thì phải có xác minh. Nhiều nguồn cùng nhắc tới chỉ là *đối chiếu*, chưa phải xác minh. Thiếu một điều kiện thì hạ xuống P2 và nói rõ thiếu gì.
7. **Trùng lặp và Trend Cluster:** đã có hồ sơ cho cùng sự kiện thì từ chối hoặc gộp, không gửi thêm cảnh báo cho cùng một cụm khi không có diễn biến mới.
8. **Rủi ro:** tin giả, nội dung nhạy cảm, quyền sử dụng, bản quyền. Gợi ý định dạng phải là ý tưởng nội dung gốc, không phải kịch bản hoàn chỉnh, không sao chép hay đăng lại video của người khác.
9. **Dữ liệu thật:** không có số liệu, URL hoặc trích dẫn bị bịa.
10. **Khả năng làm bằng AI (`ai_production`) và nhãn `focus_tags`:** đội sản xuất làm video bằng AI tạo sinh, nên mục này được duyệt kỹ như số liệu.
    - `feasibility` phải khớp bằng chứng: `CAO` chỉ khi bản gốc làm được hoàn toàn bằng công cụ AI mà không cần người thật hay nhân vật/tập phim có bản quyền (hoạt hình, minh họa, truyện kể có giọng AI, nội dung giải thích, micro-drama với nhân vật tự tạo). Tin về người thật, sự kiện trực tiếp (tỷ số, tin nóng), chủ đề nhạy cảm hoặc tác phẩm có bản quyền thì phải là `THAP` hoặc `TRUNG_BINH`.
    - `approach_vi` chỉ nêu *nhóm* công cụ và hình dung bản gốc lấy cảm hứng từ định dạng hoặc cấu trúc; không hứa chất lượng, không bắt buộc một sản phẩm trả phí cụ thể, không phải kịch bản hoàn chỉnh.
    - `constraints_vi` có ít nhất một ràng buộc thật (bản quyền, chân dung và giọng người thật, nhãn "nội dung tạo bởi AI", điều cần xác minh).
    - **Từ chối hoặc yêu cầu sửa ngay** nếu brief gợi ý tái tạo khuôn mặt hoặc giọng của người thật, sao chép nhân vật, cảnh hay tập phim có bản quyền, hoặc làm video khiến người xem tưởng là cảnh thật.
    - `focus_tags` do mã gán, không phải AI; nếu nhãn rõ ràng sai so với nội dung (ví dụ tin bóng đá gắn `phim_ngan`) thì ghi vào lý do để chỉnh bộ từ khóa, và đừng duyệt chỉ vì có nhãn trọng tâm.

## Chọn hành động
| Hành động | Khi nào | Lý do phải nêu |
|---|---|---|
| `APPROVE` | Đạt cả mười mục, hoặc lỗi nhỏ không ảnh hưởng độ tin cậy | Nêu bằng chứng đã đối chiếu (ví dụ "URL gốc mở được, số bình luận khớp, tóm tắt 74 từ") |
| `REQUEST_REVISION` | Sửa được trong một vòng: thiếu nhãn, tóm tắt sai độ dài, nói quá về mức xác minh, thiếu ghi chú metadata | Nêu từng chỗ sai và cách sửa, đủ cụ thể để Gemini làm lại không cần đoán. Câu này được gửi nguyên văn làm phản hồi |
| `REJECT` | Sai căn bản: nguồn không truy xuất được, bịa số liệu, ngoài phạm vi sản phẩm, trùng hoàn toàn, vi phạm quyền | Nêu lý do không thể sửa trong khuôn khổ hồ sơ này |

## Sau khi duyệt
- `APPROVE`: hồ sơ vào Discovery Inbox. Quản trị mới là người chọn bàn giao; Claude không tự bàn giao.
- `REQUEST_REVISION`: pipeline tự mở vòng sửa kế tiếp và gửi lý do làm phản hồi cho Gemini. Nếu đã sửa đủ hai vòng thì hồ sơ thành `REVIEW_FAILED` và chờ quản trị.
- Quyết định lặp lại cùng nội dung trả về bản ghi cũ, không tạo bản ghi trùng.
