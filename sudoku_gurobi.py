import argparse
import csv
import math
from pathlib import Path
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB
from sudoku_sat import read_grid, validate_grid, verify_solution


COLUMNS = [
    'Instance', 'Size_NxN', 'Solver', 'Num_Vars', 'Num_Constraints',
    'Modeling_Time_s', 'Solving_Time_s', 'Total_Time_s', 'Status',
    'Gurobi_Status', 'Is_Valid', 'Threads', 'Timeout_s', 'Error'
]


def solve_gurobi(grid, timeout=300):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout phải là số dương hữu hạn.')
    n, k = validate_grid(grid)
    total_start = perf_counter()
    row = dict.fromkeys(COLUMNS, '')
    row.update(Size_NxN=f'{n}x{n}', Solver='gurobi', Status='ERROR',
               Threads=1, Timeout_s=timeout)
    solution = None
    try:
        with gp.Env(empty=True) as env:
            env.setParam('OutputFlag', 0)
            env.start()
            model_start = perf_counter()
            with gp.Model('sudoku', env=env) as model:
                model.Params.Threads = 1
                model.Params.TimeLimit = timeout
                model.Params.Seed = 42
                x = model.addVars(n, n, n, vtype=GRB.BINARY, name='x')

                # 1. Mỗi ô chứa đúng một giá trị.
                for i in range(n):
                    for j in range(n):
                        model.addConstr(gp.quicksum(x[i, j, v] for v in range(n)) == 1)

                # 2. Mỗi giá trị xuất hiện đúng một lần trong mỗi hàng.
                for i in range(n):
                    for v in range(n):
                        model.addConstr(gp.quicksum(x[i, j, v] for j in range(n)) == 1)

                # 3. Mỗi giá trị xuất hiện đúng một lần trong mỗi cột.
                for j in range(n):
                    for v in range(n):
                        model.addConstr(gp.quicksum(x[i, j, v] for i in range(n)) == 1)

                # 4. Mỗi giá trị xuất hiện đúng một lần trong mỗi khối.
                for top in range(0, n, k):
                    for left in range(0, n, k):
                        for v in range(n):
                            model.addConstr(gp.quicksum(
                                x[i, j, v] for i in range(top, top + k)
                                for j in range(left, left + k)) == 1)

                # 5. Cố định các ô đề bài bằng đẳng thức tuyến tính.
                for i in range(n):
                    for j in range(n):
                        if grid[i][j]:
                            model.addConstr(x[i, j, grid[i][j] - 1] == 1)

                model.setObjective(0, GRB.MINIMIZE)
                model.update()
                row['Modeling_Time_s'] = perf_counter() - model_start
                row['Num_Vars'] = model.NumVars
                row['Num_Constraints'] = model.NumConstrs

                solve_start = perf_counter()
                try:
                    model.optimize()
                finally:
                    row['Solving_Time_s'] = perf_counter() - solve_start

                names = {GRB.OPTIMAL: 'OPTIMAL', GRB.INFEASIBLE: 'INFEASIBLE',
                         GRB.INF_OR_UNBD: 'INF_OR_UNBD', GRB.TIME_LIMIT: 'TIME_LIMIT',
                         GRB.INTERRUPTED: 'INTERRUPTED'}
                row['Gurobi_Status'] = names.get(model.Status, str(model.Status))
                if model.SolCount > 0:
                    values = model.getAttr('X', x)
                    solution = [[0] * n for _ in range(n)]
                    for i in range(n):
                        for j in range(n):
                            chosen = [v + 1 for v in range(n) if values[i, j, v] > 0.5]
                            if len(chosen) == 1:
                                solution[i][j] = chosen[0]
                    row['Is_Valid'] = verify_solution(grid, solution)
                    row['Status'] = 'SAT' if row['Is_Valid'] else 'INVALID_MODEL'
                elif model.Status == GRB.INFEASIBLE:
                    row['Status'] = 'UNSAT'
                elif model.Status == GRB.TIME_LIMIT:
                    row['Status'] = 'TIMEOUT'
                else:
                    row['Status'] = 'UNKNOWN'
    except gp.GurobiError as error:
        # Phân biệt lỗi giấy phép với đề vô nghiệm hoặc hết thời gian.
        if error.errno == GRB.Error.SIZE_LIMIT_EXCEEDED:
            row['Status'] = 'LICENSE_LIMIT'
        elif error.errno == GRB.Error.NO_LICENSE:
            row['Status'] = 'LICENSE_ERROR'
        else:
            row['Status'] = 'ERROR'
        row['Gurobi_Status'] = f'ERROR_{error.errno}'
        row['Error'] = str(error)
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
    parser = argparse.ArgumentParser(description='Giải Sudoku bằng Gurobi MIP')
    parser.add_argument('--input', required=True)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--output-csv', default='gurobi_results.csv')
    args = parser.parse_args()
    try:
        grid = read_grid(args.input)
        solution, row = solve_gurobi(grid, args.timeout)
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
