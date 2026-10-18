import argparse
import csv
import math
from pathlib import Path
import shutil
import sys
from time import perf_counter

from docplex.cp.model import CpoModel
from docplex.cp.utils import CpoException
from sudoku_sat import read_grid, validate_grid, verify_solution


COLUMNS = [
    'Instance', 'Size_NxN', 'Solver', 'Num_Vars', 'Num_Constraints',
    'Modeling_Time_s', 'Solving_Time_s', 'Engine_Solve_Time_s', 'Total_Time_s',
    'Status', 'CP_Status', 'Stop_Cause', 'Is_Valid', 'Threads', 'Timeout_s', 'Error'
]


def find_cpoptimizer(explicit_path=None):
    if explicit_path:
        return str(Path(explicit_path).resolve())
    executable = shutil.which('cpoptimizer')
    if executable:
        return executable
    name = 'cpoptimizer.exe' if sys.platform == 'win32' else 'cpoptimizer'
    candidate = Path(sys.executable).parent / name
    return str(candidate) if candidate.is_file() else None


def solve_cplex_cp(grid, timeout=300, cpoptimizer=None):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout phải là số dương hữu hạn.')
    n, k = validate_grid(grid)
    total_start = perf_counter()
    row = dict.fromkeys(COLUMNS, '')
    row.update(Size_NxN=f'{n}x{n}', Solver='cplex_cp', Status='ERROR',
               Threads=1, Timeout_s=timeout)
    solution = None
    executable = find_cpoptimizer(cpoptimizer)
    if executable is None:
        row.update(Status='UNAVAILABLE', Error='Không tìm thấy cpoptimizer. Dùng --cpoptimizer với đường dẫn đầy đủ.')
        row['Total_Time_s'] = perf_counter() - total_start
        return None, row
    try:
        model_start = perf_counter()
        model = CpoModel(name='sudoku')
        cells = [[model.integer_var(1, n, f'x_{i}_{j}')
                  for j in range(n)] for i in range(n)]

        # Một biến nguyên/ô đã bảo đảm mỗi ô mang đúng một giá trị.
        for i in range(n):
            model.add(model.all_diff(cells[i]))
        for j in range(n):
            model.add(model.all_diff([cells[i][j] for i in range(n)]))
        for top in range(0, n, k):
            for left in range(0, n, k):
                block = [cells[i][j]
                         for i in range(top, top + k)
                         for j in range(left, left + k)]
                model.add(model.all_diff(block))
        for i in range(n):
            for j in range(n):
                if grid[i][j]:
                    model.add(cells[i][j] == grid[i][j])

        statistics = model.get_statistics()
        row['Num_Vars'] = statistics.nb_integer_vars
        row['Num_Constraints'] = statistics.nb_constraints
        row['Modeling_Time_s'] = perf_counter() - model_start

        solve_start = perf_counter()
        try:
            result = model.solve(agent='local', execfile=executable,
                                 TimeLimit=timeout, TimeMode='ElapsedTime',
                                 Workers=1, RandomSeed=42, LogVerbosity='Quiet',
                                 log_output=None)
        finally:
            row['Solving_Time_s'] = perf_counter() - solve_start

        row['Engine_Solve_Time_s'] = result.get_solve_time()
        row['CP_Status'] = str(result.get_solve_status())
        row['Stop_Cause'] = str(result.get_stop_cause())
        if result.is_solution():
            solution = [[result[cells[i][j]] for j in range(n)] for i in range(n)]
            row['Is_Valid'] = verify_solution(grid, solution)
            row['Status'] = 'SAT' if row['Is_Valid'] else 'INVALID_MODEL'
        elif row['CP_Status'] == 'Infeasible':
            row['Status'] = 'UNSAT'
        else:
            # Stop_Cause có thể là SearchStoppedByLimit.
            # khi chưa có chứng minh vô nghiệm hoặc chưa tìm được nghiệm.
            row['Status'] = 'UNKNOWN'
    except (CpoException, OSError) as error:
        message = str(error)
        lower = message.lower()
        if 'problem size limit exceeded' in lower or 'community edition solves' in lower:
            row['Status'] = 'LICENSE_LIMIT'
        elif 'executable file' in lower or isinstance(error, FileNotFoundError):
            row['Status'] = 'UNAVAILABLE'
        elif 'license' in lower:
            row['Status'] = 'LICENSE_ERROR'
        else:
            row['Status'] = 'ERROR'
        row['CP_Status'] = 'ERROR'
        row['Error'] = message
    row['Total_Time_s'] = perf_counter() - total_start
    return solution, row


def save_result(row, filename):
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    has_data = path.exists() and path.stat().st_size > 0
    if has_data:
        with path.open(encoding='utf-8-sig', newline='') as file:
            if next(csv.reader(file), None) != COLUMNS:
                raise ValueError('CSV khác mẫu. Hãy chọn --output-csv khác.')
    exported = row.copy()
    for name in ('Modeling_Time_s', 'Solving_Time_s', 'Engine_Solve_Time_s', 'Total_Time_s'):
        if isinstance(row[name], (int, float)):
            exported[name] = f'{row[name]:.9f}'
    with path.open('a', encoding='utf-8' if has_data else 'utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        if not has_data:
            writer.writeheader()
        writer.writerow(exported)


def main():
    parser = argparse.ArgumentParser(description='Giải Sudoku bằng CPLEX CP Optimizer')
    parser.add_argument('--input', required=True)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--output-csv', default='cplex_cp_results.csv')
    parser.add_argument('--cpoptimizer', help='Đường dẫn cpoptimizer.exe nếu không có trong PATH')
    args = parser.parse_args()
    try:
        grid = read_grid(args.input)
        solution, row = solve_cplex_cp(grid, args.timeout, args.cpoptimizer)
        row['Instance'] = Path(args.input).name
        if solution is not None:
            width = len(str(len(grid)))
            for values in solution:
                print(' '.join(f'{value:>{width}}' for value in values))
        for name, value in row.items():
            print(f'{name}: {value:.9f}' if isinstance(value, float)
                  else f'{name}: {value if value != "" else "N/A"}')
        save_result(row, args.output_csv)
        print('CSV:', Path(args.output_csv).resolve())
        if row['Status'] == 'UNKNOWN':
            print('Chưa kết luận có nghiệm hay vô nghiệm. Xem CP_Status và Stop_Cause.')
        elif row['Status'] == 'LICENSE_LIMIT':
            print('Vượt giới hạn giấy phép CP Optimizer; đây không phải UNSAT.')
        return 0 if row['Status'] in ('SAT', 'UNSAT') else 124 if row['Status'] == 'UNKNOWN' else 2
    except (OSError, ValueError, RuntimeError) as error:
        print('Lỗi:', error)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
