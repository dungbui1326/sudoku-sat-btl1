import argparse
import csv
import math
from pathlib import Path
from time import perf_counter

from cplex.exceptions import CplexError
from docplex.mp.model import Model
from docplex.mp.utils import DOcplexException, DOcplexLimitsExceeded
from sudoku_sat import read_grid, validate_grid, verify_solution


COLUMNS = [
    'Instance', 'Size_NxN', 'Solver', 'Num_Vars', 'Num_Constraints',
    'Modeling_Time_s', 'Solving_Time_s', 'Total_Time_s', 'Status',
    'CPLEX_Status', 'Is_Valid', 'Threads', 'Timeout_s', 'Error'
]


def solve_cplex_mip(grid, timeout=300):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout phải là số dương hữu hạn.')
    n, k = validate_grid(grid)
    total_start = perf_counter()
    row = dict.fromkeys(COLUMNS, '')
    row.update(Size_NxN=f'{n}x{n}', Solver='cplex_mip', Status='ERROR',
               Threads=1, Timeout_s=timeout)
    solution = None
    try:
        model_start = perf_counter()
        with Model(name='sudoku', log_output=False) as model:
            model.parameters.threads = 1
            model.parameters.timelimit = timeout
            model.parameters.randomseed = 42
            x = model.binary_var_cube(n, n, n, name='x')

            # 1. Mỗi ô chứa đúng một giá trị.
            for i in range(n):
                for j in range(n):
                    model.add_constraint(model.sum(x[i, j, v] for v in range(n)) == 1)

            # 2. Mỗi giá trị xuất hiện đúng một lần trong mỗi hàng.
            for i in range(n):
                for v in range(n):
                    model.add_constraint(model.sum(x[i, j, v] for j in range(n)) == 1)

            # 3. Mỗi giá trị xuất hiện đúng một lần trong mỗi cột.
            for j in range(n):
                for v in range(n):
                    model.add_constraint(model.sum(x[i, j, v] for i in range(n)) == 1)

            # 4. Mỗi giá trị xuất hiện đúng một lần trong mỗi khối k x k.
            for top in range(0, n, k):
                for left in range(0, n, k):
                    for v in range(n):
                        model.add_constraint(model.sum(
                            x[i, j, v] for i in range(top, top + k)
                            for j in range(left, left + k)) == 1)

            # 5. Giữ nguyên các số đã có trong đề bài.
            for i in range(n):
                for j in range(n):
                    if grid[i][j]:
                        model.add_constraint(x[i, j, grid[i][j] - 1] == 1)

            model.minimize(0)
            codes = model.get_cplex().solution.status
            row['Modeling_Time_s'] = perf_counter() - model_start
            row['Num_Vars'] = model.number_of_variables
            row['Num_Constraints'] = model.number_of_constraints

            solve_start = perf_counter()
            try:
                result = model.solve(log_output=False)
            finally:
                row['Solving_Time_s'] = perf_counter() - solve_start

            details = model.solve_details
            row['CPLEX_Status'] = f'{details.status} ({details.status_code})'
            if result is not None:
                solution = [[0] * n for _ in range(n)]
                values = result.get_value_dict(x, keep_zeros=False)
                for i in range(n):
                    for j in range(n):
                        chosen = [v + 1 for v in range(n)
                                  if values.get((i, j, v), 0) > 0.5]
                        if len(chosen) == 1:
                            solution[i][j] = chosen[0]
                row['Is_Valid'] = verify_solution(grid, solution)
                row['Status'] = 'SAT' if row['Is_Valid'] else 'INVALID_MODEL'
            elif details.status_code == codes.MIP_infeasible:
                row['Status'] = 'UNSAT'
            elif details.status_code in (codes.MIP_time_limit_feasible,
                                          codes.MIP_time_limit_infeasible):
                row['Status'] = 'TIMEOUT'
            else:
                row['Status'] = 'UNKNOWN'
    except DOcplexLimitsExceeded as error:
        row.update(Status='LICENSE_LIMIT', CPLEX_Status='LIMIT_EXCEEDED', Error=str(error))
    except (DOcplexException, CplexError) as error:
        message = str(error)
        if '1016' in message and 'license' in message.lower():
            row['Status'] = 'LICENSE_LIMIT'
        elif 'no cplex runtime' in message.lower():
            row['Status'] = 'UNAVAILABLE'
        elif 'license' in message.lower():
            row['Status'] = 'LICENSE_ERROR'
        else:
            row['Status'] = 'ERROR'
        row['CPLEX_Status'] = 'ERROR'
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
    for name in ('Modeling_Time_s', 'Solving_Time_s', 'Total_Time_s'):
        if isinstance(row[name], (int, float)):
            exported[name] = f'{row[name]:.9f}'
    with path.open('a', encoding='utf-8' if has_data else 'utf-8-sig',
                   newline='') as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        if not has_data:
            writer.writeheader()
        writer.writerow(exported)


def main():
    parser = argparse.ArgumentParser(description='Giải Sudoku bằng CPLEX MIP')
    parser.add_argument('--input', required=True)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--output-csv', default='cplex_mip_results.csv')
    args = parser.parse_args()
    try:
        grid = read_grid(args.input)
        solution, row = solve_cplex_mip(grid, args.timeout)
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
        if row['Status'] in ('TIMEOUT', 'UNKNOWN'):
            print('Chưa kết luận có nghiệm hay vô nghiệm.')
        elif row['Status'] == 'LICENSE_LIMIT':
            print('Giấy phép hiện tại giới hạn kích thước mô hình; đây không phải UNSAT.')
        return 0 if row['Status'] in ('SAT', 'UNSAT') else 124 if row['Status'] in ('TIMEOUT', 'UNKNOWN') else 2
    except (OSError, ValueError, RuntimeError) as error:
        print('Lỗi:', error)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
