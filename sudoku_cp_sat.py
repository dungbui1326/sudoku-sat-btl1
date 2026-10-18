import argparse
import csv
import math
from pathlib import Path
from time import perf_counter

from ortools.sat.python import cp_model
from sudoku_sat import read_grid, validate_grid, verify_solution


COLUMNS = [
    'Instance', 'Size_NxN', 'Solver', 'Num_Vars', 'Num_Constraints',
    'Modeling_Time_s', 'Solving_Time_s', 'Total_Time_s',
    'Status', 'CP_Status', 'Is_Valid', 'Threads', 'Timeout_s'
]


def solve_cp_sat(grid, timeout=300):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout phải là số dương hữu hạn.')
    n, k = validate_grid(grid)
    total_start = perf_counter()
    model_start = perf_counter()
    model = cp_model.CpModel()

    # Mỗi ô là một biến nguyên từ 1 đến N.
    cells = [[model.new_int_var(1, n, f'x_{i}_{j}')
              for j in range(n)] for i in range(n)]

    for i in range(n):
        model.add_all_different(cells[i])
    for j in range(n):
        model.add_all_different([cells[i][j] for i in range(n)])
    for top in range(0, n, k):
        for left in range(0, n, k):
            block = [cells[i][j]
                     for i in range(top, top + k)
                     for j in range(left, left + k)]
            model.add_all_different(block)

    for i in range(n):
        for j in range(n):
            if grid[i][j] != 0:
                model.add(cells[i][j] == grid[i][j])

    modeling_time = perf_counter() - model_start
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42

    solve_start = perf_counter()
    result = solver.solve(model)
    solving_time = perf_counter() - solve_start

    solution = None
    valid = ''
    if result in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solution = [[solver.value(cells[i][j]) for j in range(n)]
                    for i in range(n)]
        valid = verify_solution(grid, solution)
        status = 'SAT' if valid else 'INVALID_MODEL'
    elif result == cp_model.INFEASIBLE:
        status = 'UNSAT'
    elif result == cp_model.MODEL_INVALID:
        status = 'MODEL_INVALID'
    else:
        # Hết giờ mà chưa tìm thấy nghiệm không đồng nghĩa với vô nghiệm.
        status = 'UNKNOWN'

    row = dict(
        Instance='', Size_NxN=f'{n}x{n}', Solver='cp_sat',
        Num_Vars=len(model.proto.variables),
        Num_Constraints=len(model.proto.constraints),
        Modeling_Time_s=modeling_time, Solving_Time_s=solving_time,
        Total_Time_s=perf_counter() - total_start, Status=status,
        CP_Status=solver.status_name(result), Is_Valid=valid,
        Threads=1, Timeout_s=timeout
    )
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
        exported[name] = f'{row[name]:.9f}'
    with path.open('a', encoding='utf-8' if has_data else 'utf-8-sig',
                   newline='') as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        if not has_data:
            writer.writeheader()
        writer.writerow(exported)


def main():
    parser = argparse.ArgumentParser(description='Giải Sudoku bằng CP-SAT')
    parser.add_argument('--input', required=True)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--output-csv', default='cp_sat_results.csv')
    args = parser.parse_args()
    try:
        grid = read_grid(args.input)
        solution, row = solve_cp_sat(grid, args.timeout)
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
            print('Chưa kết luận có nghiệm hay vô nghiệm.')
        return 0 if row['Status'] in ('SAT', 'UNSAT') else 124 if row['Status'] == 'UNKNOWN' else 2
    except (OSError, ValueError, RuntimeError) as error:
        print('Lỗi:', error)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
