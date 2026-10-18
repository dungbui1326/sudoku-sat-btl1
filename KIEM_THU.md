# Kiểm thử mã nguồn SAT Terminal

Môi trường: Linux, Python 3.12, python-sat 1.9.dev16, pycryptosat 5.17.0.

Lệnh: `python -m unittest -v test_sudoku_sat.py`

Kết quả: **8 nhóm kiểm thử đạt**, thời gian lần chạy đầy đủ khoảng 7,8 giây.

1. Exhaustive Exactly-One: cả 5 encoding, nhóm 1/2/3/4/5/9/10 biến; duyệt toàn bộ cách gán biến gốc và kiểm tra khả năng tồn tại biến phụ. Nhóm 10 kiểm tra đệ quy Commander.
2. Ánh xạ ID 1..N³ không đụng biến phụ, kiểm tra nghiệm và số biến/mệnh đề chuẩn.
3. Hai đề UNSAT (có/không trùng số trực tiếp) cho mọi encoding.
4. Đọc TXT/CSV/semicolon/tab/BOM, từ chối dữ liệu sai và kiểm tra verifier.
5. 4 solver (CaDiCaL 1.5.3, Glucose4, MiniSat22, CryptoMiniSat5) × 5 encoding = 20 cấu hình SAT trên đề 9×9; mọi lời giải đều được kiểm tra độc lập.
6. Kích thước 1×1, 4×4, 16×16, 25×25, 36×36 với Product/CaDiCaL.
7. UNSAT, lỗi tên solver, append CSV chỉ ghi một header và từ chối schema không khớp.
8. Timeout thực trên bài toán pigeonhole 18 lỗ, ngân sách 0,02 giây, thử cả 4 solver. Tất cả trả TIMEOUT, không nhầm UNSAT. Glucose/MiniSat dùng interrupt; CaDiCaL/CryptoMiniSat bị dừng qua tiến trình.

Đã kiểm tra CLI đọc ví dụ CSV 9×9, demo 25×25 với Glucose4/Binary, UNSAT không trùng trực tiếp với MiniSat22/Commander, và từ chối `--timeout nan`.

Các lần chạy này nhằm xác nhận chương trình hoạt động, **không phải bộ benchmark hoặc số liệu so sánh chính thức cho báo cáo**. Chưa kiểm thử trực tiếp trên Windows; mã dùng multiprocessing spawn và có main guard/freeze_support để hỗ trợ Windows.
