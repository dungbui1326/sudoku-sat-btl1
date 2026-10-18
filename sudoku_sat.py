from __future__ import annotations

import argparse
import csv
import math
import multiprocessing as mp
from pathlib import Path
import random
import re
import sys
import tempfile
from threading import Event, Timer
from time import perf_counter
from typing import Any

try:
    from pysat.card import CardEnc, EncType
    from pysat.formula import CNF, IDPool
    from pysat.solvers import Solver, SolverNames
except ImportError as error:
    raise SystemExit("Chưa cài PySAT. Chạy: python -m pip install python-sat") from error


ENCODINGS = ("pairwise", "seqcounter", "commander", "product", "binary")
CSV_COLUMNS = [
    "Instance", "Size_NxN", "Solver", "Encoding", "Num_Vars", "Num_Clauses",
    "Encoding_Time_s", "Solving_Time_s", "Total_Time_s", "Status", "Is_Valid",
]
SAMPLE_9 = [
    [5,3,0,0,7,0,0,0,0], [6,0,0,1,9,5,0,0,0],
    [0,9,8,0,0,0,0,6,0], [8,0,0,0,6,0,0,0,3],
    [4,0,0,8,0,3,0,0,1], [7,0,0,0,2,0,0,0,6],
    [0,6,0,0,0,0,2,8,0], [0,0,0,4,1,9,0,0,5],
    [0,0,0,0,8,0,0,7,9],
]


def validate_grid(grid: list[list[int]]) -> tuple[int, int]:
    """Kiểm tra hình dạng/miền giá trị; số trùng vẫn được đưa cho SAT giải."""
    n = len(grid)
    k = math.isqrt(n)
    if n == 0 or k*k != n:
        raise ValueError("N phải là số chính phương dương: 1, 4, 9, 16, 25, 36, ...")
    if any(len(row) != n for row in grid):
        raise ValueError(f"Đề phải có {n} hàng và mỗi hàng đúng {n} giá trị.")
    if any(type(v) is not int or v < 0 or v > n for row in grid for v in row):
        raise ValueError(f"Mỗi ô phải là số nguyên từ 0 đến {n}.")
    return n, k


def read_grid(path: str | Path) -> list[list[int]]:
    """Đọc UTF-8/BOM; ngăn cách bằng khoảng trắng, tab, dấu phẩy hoặc ;."""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    grid = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        tokens = re.split(r"[\s,;]+", line.strip())
        try:
            grid.append([int(token) for token in tokens])
        except ValueError as error:
            raise ValueError(f"Dòng {line_number}: cần các số nguyên, ô trống là 0.") from error
    validate_grid(grid)
    return grid


def sudoku_groups(n: int):
    """Sinh từng hàng, cột và khối; mỗi nhóm có đúng N tọa độ."""
    k = math.isqrt(n)
    for i in range(n):
        yield [(i, j) for j in range(n)]
    for j in range(n):
        yield [(i, j) for i in range(n)]
    for top in range(0, n, k):
        for left in range(0, n, k):
            yield [(i, j) for i in range(top, top+k) for j in range(left, left+k)]


def _pairwise_amo(literals: list[int], cnf: CNF, vpool: IDPool) -> None:
    cnf.extend(CardEnc.atmost(lits=literals, bound=1, vpool=vpool,
                            encoding=EncType.pairwise).clauses)


def _commander_amo(literals: list[int], cnf: CNF, vpool: IDPool) -> None:
    """Commander đệ quy, nhóm 3 biến. Mỗi commander tương đương OR của nhóm."""
    if len(literals) <= 3:
        _pairwise_amo(literals, cnf, vpool)
        return
    commanders = []
    for start in range(0, len(literals), 3):
        group = literals[start:start+3]
        commander = vpool.id()  # ID mới, luôn nằm sau các biến Sudoku gốc.
        commanders.append(commander)
        _pairwise_amo(group, cnf, vpool)
        for literal in group:
            cnf.append([-literal, commander])  # x -> commander.
        cnf.append([-commander] + group)       # commander -> OR(group).
    _commander_amo(commanders, cnf, vpool)


def _product_amo(literals: list[int], cnf: CNF, vpool: IDPool) -> None:
    """Two-product AMO: đặt biến vào lưới p x q, dùng biến phụ hàng/cột.

    Nếu hai biến gốc cùng đúng, chúng phải có cùng hàng phụ và cùng cột phụ,
    tức phải ở cùng một vị trí. Hai biến gốc khác nhau không thể cùng đúng.
    """
    m = len(literals)
    if m <= 3:
        _pairwise_amo(literals, cnf, vpool)
        return
    p = math.isqrt(m)
    if p*p < m:
        p += 1
    q = (m+p-1)//p
    rows = [vpool.id() for _ in range(p)]
    columns = [vpool.id() for _ in range(q)]
    for index, literal in enumerate(literals):
        cnf.append([-literal, rows[index//q]])
        cnf.append([-literal, columns[index%q]])
    _pairwise_amo(rows, cnf, vpool)
    _pairwise_amo(columns, cnf, vpool)


def exactly_one(literals: list[int], cnf: CNF, vpool: IDPool, encoding: str) -> None:
    """Exactly-One = ALO AND AMO; tất cả CardEnc dùng chung một IDPool."""
    # Với bound=1, ALO là một mệnh đề OR gồm tất cả các biến trong nhóm.
    cnf.extend(CardEnc.atleast(lits=literals, bound=1, vpool=vpool,
                             encoding=EncType.seqcounter).clauses)
    native = {"pairwise": EncType.pairwise, "seqcounter": EncType.seqcounter,
              "binary": EncType.bitwise}
    if encoding in native:
        # vpool ngăn trùng ID giữa biến phụ của các nhóm ràng buộc khác nhau.
        amo = CardEnc.atmost(lits=literals, bound=1, vpool=vpool,
                            encoding=native[encoding])
        cnf.extend(amo.clauses)
    elif encoding == "commander":
        _commander_amo(literals, cnf, vpool)
    elif encoding == "product":
        _product_amo(literals, cnf, vpool)
    else:
        raise ValueError(f"Encoding không hợp lệ: {encoding}")


def encode_sudoku(grid: list[list[int]], encoding: str = "seqcounter") -> tuple[CNF, IDPool]:
    n, _ = validate_grid(grid)
    if encoding not in ENCODINGS:
        raise ValueError(f"Encoding phải thuộc {ENCODINGS}.")
    cnf, vpool = CNF(), IDPool(start_from=1)

    for i in range(n):
        for j in range(n):
            for v in range(1, n+1):
                vpool.id((i, j, v))
    assert vpool.top == n**3

    def x(i: int, j: int, v: int) -> int:
        return vpool.id((i, j, v))

    # 1. Mỗi ô chứa đúng một giá trị.
    for i in range(n):
        for j in range(n):
            exactly_one([x(i, j, v) for v in range(1, n+1)], cnf, vpool, encoding)

    # 2, 3, 4. Mỗi giá trị xuất hiện đúng một lần trong mỗi hàng/cột/khối.
    for group in sudoku_groups(n):
        for v in range(1, n+1):
            exactly_one([x(i, j, v) for i, j in group], cnf, vpool, encoding)

    # 5. Số đã cho trở thành mệnh đề đơn buộc biến tương ứng bằng True.
    for i in range(n):
        for j in range(n):
            if grid[i][j] != 0:
                cnf.append([x(i, j, grid[i][j])])
    return cnf, vpool


def verify_solution(initial_grid: list[list[int]], solved_grid: Any) -> bool:
    """Kiểm tra độc lập: hình dạng, kiểu, miền, hàng, cột, khối và số gốc."""
    try:
        n, _ = validate_grid(initial_grid)
        if not isinstance(solved_grid, list) or len(solved_grid) != n:
            return False
        if any(not isinstance(row, list) or len(row) != n for row in solved_grid):
            return False
        if any(type(v) is not int or not 1 <= v <= n for row in solved_grid for v in row):
            return False
        expected = set(range(1, n+1))
        if any({solved_grid[i][j] for i, j in group} != expected for group in sudoku_groups(n)):
            return False
        return all(initial_grid[i][j] == 0 or initial_grid[i][j] == solved_grid[i][j]
                   for i in range(n) for j in range(n))
    except (ValueError, TypeError, IndexError):
        return False


def _interruptible(solver_name: str) -> bool:
    # Danh sách đã kiểm tra API; backend khác vẫn chạy bằng bảo vệ tiến trình.
    aliases = SolverNames.glucose3 + SolverNames.glucose4 + SolverNames.minisat22
    return solver_name.lower() in aliases


def _solver_worker(connection, cnf_path: str, solver_name: str, timeout: float,
                   primary_variables: int) -> None:
    """Hàm ở cấp module để multiprocessing 'spawn' hoạt động trên Windows."""
    try:
        formula = CNF(from_file=cnf_path)
        with Solver(name=solver_name, bootstrap_with=formula.clauses) as solver:
            del formula
            supported = _interruptible(solver_name)
            connection.send(("READY", supported))
            if connection.recv() != "GO":
                return

            expired = Event()
            timer = None
            interrupt_error = []

            def interrupt_search():
                expired.set()
                try:
                    solver.interrupt()
                except Exception as error:
                    interrupt_error.append(str(error))

            start = perf_counter()
            if supported:
                timer = Timer(timeout, interrupt_search)
                timer.daemon = True
                timer.start()
            try:
                
                answer = (solver.solve_limited(expect_interrupt=True)
                          if supported else solver.solve())
                solving_time = perf_counter()-start
            finally:
                
                if timer is not None:
                    timer.cancel()
                    timer.join()

            if expired.is_set() or solving_time > timeout:
                status, model = "TIMEOUT", None
            elif answer is True:
                status = "SAT"
                model = [lit for lit in solver.get_model() if 0 < lit <= primary_variables]
            elif answer is False:
                status, model = "UNSAT", None
            else:
                status, model = "UNKNOWN", None
            connection.send(("RESULT", {"status": status, "model": model,
                                       "solving_time": solving_time,
                                       "interrupt_error": interrupt_error}))
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        if solver_name.lower() in SolverNames.cryptosat:
            message += " | CryptoMiniSat cần pycryptosat tương thích: python -m pip install pycryptosat"
        try:
            connection.send(("ERROR", message))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def solve_cnf(cnf: CNF, solver_name: str, timeout: float,
              primary_variables: int) -> dict[str, Any]:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout phải là số giây hữu hạn, lớn hơn 0.")
    context = mp.get_context("spawn")
    expired = Event()
    timer = None
    process = None
    solve_start = None
    with tempfile.TemporaryDirectory(prefix="sudoku_sat_") as directory:
        cnf_path = str(Path(directory)/"formula.cnf")
        cnf.to_file(cnf_path)
        parent, child = context.Pipe(duplex=True)
        try:
            process = context.Process(target=_solver_worker,
                                      args=(child, cnf_path, solver_name, timeout, primary_variables))
            process.start()
            child.close()
            preparation_deadline = perf_counter()+300
            while True:
                if parent.poll(0.01):
                    try:
                        kind, payload = parent.recv()
                    except EOFError as error:
                        raise RuntimeError(f"Solver dừng bất thường (exitcode={process.exitcode}).") from error
                    if kind == "ERROR":
                        raise RuntimeError(payload)
                    if kind == "READY":
                        grace = 0.25 if payload else 0.0
                        timer = Timer(timeout+grace, expired.set)
                        timer.daemon = True
                        solve_start = perf_counter()
                        timer.start()
                        parent.send("GO")
                    elif kind == "RESULT":
                        return payload
                if expired.is_set():
                    return {"status": "TIMEOUT", "model": None,
                            "solving_time": perf_counter()-solve_start,
                            "interrupt_error": []}
                if solve_start is None and perf_counter() > preparation_deadline:
                    raise RuntimeError("Khởi tạo/nạp solver quá 300 giây; chưa bắt đầu tìm nghiệm.")
                if not process.is_alive() and not parent.poll(0.02):
                    raise RuntimeError(f"Solver kết thúc mà chưa trả kết quả (exitcode={process.exitcode}).")
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            if process is not None and process.pid is not None:
                process.join(timeout=0.1)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            parent.close()
            child.close()


def solve_sudoku(grid: list[list[int]], solver: str = "cadical153",
                 encoding: str = "seqcounter", timeout: float = 300.0,
                 instance: str = "in_memory") -> tuple[list[list[int]] | None, dict[str, Any]]:
    
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout phải hữu hạn và lớn hơn 0.")
    n, _ = validate_grid(grid)
    row = dict.fromkeys(CSV_COLUMNS, "")
    row.update(Instance=instance, Size_NxN=f"{n}x{n}", Solver=solver.lower(),
               Encoding=encoding, Status="ERROR")
    total_start = perf_counter()
    solution = None
    try:
        encoding_start = perf_counter()
        cnf, vpool = encode_sudoku(grid, encoding)
        row["Encoding_Time_s"] = perf_counter()-encoding_start
        row["Num_Vars"] = cnf.nv
        row["Num_Clauses"] = len(cnf.clauses)

        del vpool
        result = solve_cnf(cnf, solver.lower(), timeout, n**3)
        row["Solving_Time_s"] = result["solving_time"]
        row["Status"] = result["status"]
        if result["status"] == "SAT":
            solution = [[0]*n for _ in range(n)]
            for literal in result["model"]:
                cell, value0 = divmod(literal-1, n)
                i, j = divmod(cell, n)
                if solution[i][j] != 0:
                    raise RuntimeError("Model chứa nhiều giá trị cho cùng một ô.")
                solution[i][j] = value0+1
            row["Is_Valid"] = verify_solution(grid, solution)
            if not row["Is_Valid"]:
                row["Status"] = "INVALID_MODEL"
    except Exception as error:
        row["Status"] = "ERROR"
        row["Error"] = f"{type(error).__name__}: {error}"
    row["Total_Time_s"] = perf_counter()-total_start
    return solution, row


def append_results(row: dict[str, Any], path: str | Path = "sat_results.csv") -> None:
    
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    has_data = path.exists() and path.stat().st_size > 0
    if has_data:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            if next(csv.reader(stream), None) != CSV_COLUMNS:
                raise ValueError(f"Header {path} không đúng mẫu; hãy chọn --output-csv khác.")
    export = {name: row.get(name, "") for name in CSV_COLUMNS}
    for name in ("Encoding_Time_s", "Solving_Time_s", "Total_Time_s"):
        if isinstance(export[name], (int, float)):
            export[name] = f"{export[name]:.9f}"
    with path.open("a", encoding="utf-8" if has_data else "utf-8-sig"
    , newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        if not has_data:
            writer.writeheader()
        writer.writerow(export)


def print_result(solution, row) -> None:
    print(f"\nInstance: {row['Instance']} | Size: {row['Size_NxN']}")
    print(f"Solver: {row['Solver']} | Encoding: {row['Encoding']}")
    print(f"Status: {row['Status']}")
    if solution is not None and row["Status"] in ("SAT", "INVALID_MODEL"):
        width = len(str(len(solution)))
        for values in solution:
            print(" ".join(f"{v:>{width}}" for v in values))
        print(f"Valid: {row['Is_Valid']}")
    elif row["Status"] == "UNSAT":
        print("Không tồn tại lời giải. Valid: N/A")
    elif row["Status"] in ("TIMEOUT", "UNKNOWN"):
        print("Chưa kết luận có nghiệm hay vô nghiệm. Valid: N/A")
    if row.get("Error"):
        print(f"Error: {row['Error']}")
    for key in ("Num_Vars", "Num_Clauses", "Encoding_Time_s", "Solving_Time_s", "Total_Time_s"):
        value = row.get(key, "")
        print(f"{key}: {value:.9f}" if isinstance(value, float) else f"{key}: {value}")


def make_demo_grid(n: int, seed: int = 42) -> list[list[int]]:
    
    if n == 9:
        return [row[:] for row in SAMPLE_9]
    if n <= 0 or math.isqrt(n)**2 != n:
        raise ValueError("Kích thước mẫu phải là số chính phương dương.")
    k, rng = math.isqrt(n), random.Random(seed)
    digits = rng.sample(range(1, n+1), n)
    rows = [band*k+r for band in rng.sample(range(k), k) for r in rng.sample(range(k), k)]
    cols = [stack*k+c for stack in rng.sample(range(k), k) for c in rng.sample(range(k), k)]
    return [[digits[(i*k+i//k+j)%n] if rng.random() < 0.55 else 0
             for j in cols] for i in rows]


def run_demo(solver: str = "cadical153", encoding: str = "seqcounter",
             timeout: float = 300, n: int = 9, csv_path: str | Path = "sat_results.csv"):
    
    grid = make_demo_grid(n)
    solution, row = solve_sudoku(grid, solver, encoding, timeout, f"demo_{n}x{n}")
    print_result(solution, row)
    append_results(row, csv_path)
    return solution, row


def positive_seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Timeout phải là số giây.") from error
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("Timeout phải hữu hạn và lớn hơn 0.")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="File TXT/CSV chứa ma trận, 0 là ô trống.")
    source.add_argument("--demo", action="store_true", help="Chạy đề mẫu có sẵn.")
    parser.add_argument("--size", type=int, default=9, help="Kích thước dùng với --demo (mặc định 9).")
    parser.add_argument("--solver", default="cadical153", help="Tên/alias solver PySAT.")
    parser.add_argument("--encoding", choices=ENCODINGS, default="seqcounter")
    parser.add_argument("--timeout", type=positive_seconds, default=300.0)
    parser.add_argument("--output-csv", type=Path, default=Path("sat_results.csv"))
    args = parser.parse_args(argv)
    try:
        if args.demo:
            _, row = run_demo(args.solver, args.encoding, args.timeout, args.size, args.output_csv)
        else:
            
            grid = read_grid(args.input)
            solution, row = solve_sudoku(grid, args.solver, args.encoding,
                                         args.timeout, args.input.name)
            print_result(solution, row)
            append_results(row, args.output_csv)
        print(f"CSV: {args.output_csv.resolve()}")
        return {"SAT": 0, "UNSAT": 0, "TIMEOUT": 124, "UNKNOWN": 124,
                "INVALID_MODEL": 3, "ERROR": 2}.get(row["Status"], 2)
    except (ValueError, OSError) as error:
        print(f"Lỗi dữ liệu / file: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
