# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (judge replay, không cần API key). FAIL là lớp dương: việc của judge là **tìm ra** reply lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** | **dùng** (chỉ cho giọng văn, không chặn release một mình) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (κ và R dưới sàn) | **loại** |

Ma trận nhầm lẫn:
- tone_ok: `tp 24 · fp 4 · fn 6 · tn 66`. Tỉ lệ FAIL judge quan sát 0.28 → hiệu chỉnh Rogan-Gladen **0.30** (gần tỉ lệ FAIL của người, 30/100).
- helpful: `tp 9 · fp 0 · fn 21 · tn 70`. Tỉ lệ FAIL quan sát 0.09 → hiệu chỉnh **0.30**. Judge báo thấp hơn thực tế hơn 3 lần.

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã với khách khiếu nại. Rubric thêm: *bắt buộc xưng "LogiX" / "anh/chị", cấm "em", "bạn", "nha", "nhé"*. |
| 2 | tone H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ thấy "Dạ, vui lòng" nên cho qua, bỏ sót giọng ra lệnh. Rubric thêm ví dụ FAIL: *câu mệnh lệnh chặn khách liên hệ*. |
| 3 | tone H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Từ "refund" được chính sách CS LogiX cho phép. Rubric ghi rõ: *thuật ngữ trong danh sách cho phép (refund, ship, COD) không bị phạt*. |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". Rubric sửa: *xin lỗi không bắt buộc khi yêu cầu đã được giải quyết; ngắn mà đủ ý là PASS*. |
| 5 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Ghi chú gốc: người đọc nhầm ticket. Sửa **nhãn người** thành FAIL, không sửa rubric; thêm bước người thứ hai duyệt nhãn ở các ca bất đồng. |
| 6 | tone H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Rubric thêm: *không dùng emoji trong ngữ cảnh khiếu nại*. |
| 7 | tone H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | Người | Rubric thêm: *reply tiếng Việt phải có dấu đầy đủ*. |
| 8 | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | Người | Judge không thấy ledger nên không thể biết số tiền sai. Không sửa được bằng rubric. Việc này chuyển cho grader code `reply_amount_matches_ledger` (FM-08). |
| 9 | helpful HL-016 / HL-028 (xin lỗi lặp 2–3 lần, số tiền sai) | PASS | FAIL | Người | Judge bị câu xin lỗi dài "đánh lừa", chấm có ích dù số tiền sai. Đây là verbosity bias. |
| 10 | helpful HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả, không nói số tiền, sai xưng hô. Thuộc về tiêu chí tone, không phải helpful. |

## Kết luận

- **Loại judge `helpful`.** Recall 0.30 nghĩa là judge bỏ sót 21/30 reply có lỗi. κ = 0.375 dưới sàn 0.6. Precision 1.0 chỉ nói rằng khi judge dám nói FAIL thì đúng, chứ không cứu được việc nó gần như không bao giờ nói FAIL. 18/21 ca bỏ sót có `human_failure = "sai tiền"`: judge chỉ đọc chữ, không có ledger, nên **về cấu trúc không thể** chấm đúng số tiền. Nếu dùng nó làm gate, khoảng 70% reply sai tiền sẽ lọt. Theo quy tắc của lab, tiền và approval luôn chấm bằng code, nên phần "sai tiền" giao cho `reply_amount_matches_ledger`; tiêu chí helpful phải viết lại (bỏ phần tiền, chỉ giữ "có trả lời đúng câu hỏi không") rồi calibrate lại trên nhãn mới.
- **Giữ judge `tone_ok`** cho giọng văn, nhưng chỉ ở mức cảnh báo, không chặn release một mình. 6/10 bất đồng là judge bỏ sót lỗi (FN: xưng hô, giọng ra lệnh, emoji, mất dấu, hứa ngoài kết quả hệ thống ở H-063), nên áp dụng 5 sửa đổi rubric ở trên rồi calibrate lại.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí). Cần nhãn người mới, do 2 người gán độc lập, để có held-out thật. Một nhãn người cũng đã sai (H-081), nên nhãn "vàng" cũng cần được kiểm.
