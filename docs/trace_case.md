# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Case: `seeded_regression C-002@11`

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, report `E-seeded_regression-20261117-15f2` (eval set `15f26f27976a`), item `E-002` |
| Triệu chứng | Lab 8 grader FAIL (`status resolved != denied`). `refund_amount_correct` và `db_fact_kept` fail. Ledger ghi **20.000đ** (1 dòng) trong khi nhãn là `denied`, 0đ. Reply event 6: "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." Reply khớp ledger nên FM-08 không bắt; lỗi nằm ở tiền thật đã chuyển. |
| Bước sai đầu tiên | **Event 3** `model_override {"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng: chỉ cho tool read-only, `facts` rỗng. Event 2 `investigator` đọc đơn O-202 từ DB, `delivered`, `delay_days = 2`. Đây là sự thật đúng, trễ 2 ngày nên không đủ điều kiện (cần ≥ 3). Tới event 3, agent lấy số "trễ 5 ngày" khách tự viết trong ticket đè lên số 2 của DB. Mọi bước sau đều tính đúng trên một dữ kiện đã sai: event 4 `quote 20.000đ (SHIP-LATE-03)` rồi host ghi tiền. |
| Failure mode | **FM-03** ticket_trust (layer model/prompt) |
| Đối chứng | `fixed C-002@11`: không có event `model_override`; event 3 là `quote {"amount_vnd": 0, "reason": "no_entitlement"}`, reply "chưa đủ điều kiện hoàn", ledger 0, status `denied`, Lab 8 grader PASS. Baseline `swarm` cũng mắc lỗi này nhưng chỉ ở `C-002@55`, vì swarm tham chiếu chỉ tin ticket khi seed chia hết cho 5. |
| Regression test | `src/tests/test_lab9_trace_case.py`. `test_lab9_trace_case_regression_is_caught` khẳng định trên `seeded_regression` có event `model_override`, `DbFactKept = False`, `RefundAmountCorrect = False` và ledger 20.000. `test_lab9_trace_case_fixed_passes` khẳng định `fixed` không có override, hai grader cùng True, ledger 0. Đã chạy: test fail đúng chỗ trên variant lỗi và pass trên `fixed` (13 test `lab9` xanh). Item `E-002` đã mang `FM-03` trong eval set. |
| Chưa chắc chắn | Trace cho thấy *agent đã tin ticket* nhưng không cho thấy *vì sao*: với MockLLM đây là công tắc cố định, còn với LLM thật có thể do prompt, do ticket có số liệu cụ thể, hay do nhiệt độ sampling. Case cũng chưa nói được lỗi có lan sang nhánh hỏng hàng hay không, vì chưa có claim công khai nào mà ticket mâu thuẫn với DB ở `damage_verified`. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
