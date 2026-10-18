# Giải Sudoku bằng SAT

Bài tập lớn số 1 – Các vấn đề hiện đại khoa học máy tính.

- Sinh viên: Bùi Tiến Dũng
- MSV: 24021423
- Trường Đại học Công nghệ – ĐHQGHN

## Chức năng

Giải Sudoku kích thước N × N, với N là số chính phương.
Chương trình mã hóa các quy tắc Sudoku thành CNF, gọi bộ giải
trong PySAT, kiểm tra nghiệm và lưu kết quả vào CSV.

## Cài thư viện

```bash
python -m pip install -r requirements.txt
```

## Chạy chương trình

```bash
python sudoku_sat.py --input examples/sudoku_9x9.txt --solver cadical153 --encoding seqcounter --timeout 30
```

Các mã hóa hỗ trợ: pairwise, seqcounter, binary, commander, product.

File đầu vào chứa ma trận số nguyên, dùng 0 cho ô trống.
Kết quả mặc định được ghi nối vào sat_results.csv.

## Thư mục và kết quả

- examples/: các đề Sudoku.
- Các file sudoku_*.py: mã nguồn giải bằng SAT, CP và MIP.
- Các file CSV: kết quả thực nghiệm.
- report/: báo cáo và hình minh họa.