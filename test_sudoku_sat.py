"""Kiểm thử: python -m unittest -v test_sudoku_sat.py"""
import csv
from itertools import product
from pathlib import Path
import tempfile
import time
import unittest

from pysat.examples.genhard import PHP
from pysat.formula import CNF, IDPool
from pysat.solvers import Solver

import sudoku_sat as app


class EncodingTests(unittest.TestCase):
    def test_exactly_one_exhaustive(self):
        # Mỗi cách gán biến gốc phải mở rộng được sang các biến phụ khi và
        # chỉ khi có ĐÚNG MỘT biến gốc True; kiểm tra cả nhóm lẻ và đệ quy.
        for encoding in app.ENCODINGS:
            for size in (1,2,3,4,5,9,10):
                cnf, pool = CNF(), IDPool()
                literals = [pool.id(('input',i)) for i in range(size)]
                app.exactly_one(literals,cnf,pool,encoding)
                with Solver(name='minisat22',bootstrap_with=cnf.clauses) as solver:
                    for values in product((False,True),repeat=size):
                        assumptions = [lit if val else -lit for lit,val in zip(literals,values)]
                        with self.subTest(encoding=encoding,size=size,values=values):
                            self.assertEqual(solver.solve(assumptions=assumptions),sum(values)==1)

    def test_mapping_counts_and_projection(self):
        for encoding in app.ENCODINGS:
            grid=app.make_demo_grid(4)
            cnf,pool=app.encode_sudoku(grid,encoding)
            for i in range(4):
                for j in range(4):
                    for v in range(1,5):
                        self.assertEqual(pool.id((i,j,v)),(i*4+j)*4+v)
            with Solver(name='glucose4',bootstrap_with=cnf.clauses) as solver:
                self.assertTrue(solver.solve())
                model={lit for lit in solver.get_model() if lit>0}
                solved=[[next(v for v in range(1,5) if pool.id((i,j,v)) in model)
                         for j in range(4)] for i in range(4)]
                self.assertTrue(app.verify_solution(grid,solved))
        cnf,_=app.encode_sudoku(app.SAMPLE_9,'pairwise')
        self.assertEqual((cnf.nv,len(cnf.clauses)),(729,12018))

    def test_unsat_for_every_encoding(self):
        for value in (5,1):  # 5: trùng trực tiếp; 1: không trùng nhưng vô nghiệm.
            grid=[row[:] for row in app.SAMPLE_9]
            grid[0][2]=value
            for encoding in app.ENCODINGS:
                cnf,_=app.encode_sudoku(grid,encoding)
                with Solver(name='minisat22',bootstrap_with=cnf.clauses) as solver:
                    self.assertFalse(solver.solve())

    def test_parser_and_verifier(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'de.csv'
            for sep in (' ',',',';','\t'):
                path.write_text('\ufeff'+'\n'.join(sep.join(map(str,row)) for row in app.SAMPLE_9),encoding='utf-8')
                self.assertEqual(app.read_grid(path),app.SAMPLE_9)
            for text in ('','1 2\n3 4','x y\nz a','1 2 3 4\n0 0 0 0'):
                path.write_text(text)
                with self.assertRaises(ValueError):app.read_grid(path)
        self.assertFalse(app.verify_solution(app.SAMPLE_9,None))
        self.assertFalse(app.verify_solution([[0]],[[True]]))
        self.assertTrue(app.verify_solution([[0]],[[1]]))


class EndToEndTests(unittest.TestCase):
    def test_four_solvers_five_encodings(self):
        for name in ('cadical153','glucose4','minisat22','cryptominisat5'):
            # CryptoMinisat là phụ thuộc tùy chọn. Báo skip riêng nếu chưa cài.
            if name=='cryptominisat5':
                try:import pycryptosat
                except ImportError:continue
            for encoding in app.ENCODINGS:
                with self.subTest(solver=name,encoding=encoding):
                    solution,row=app.solve_sudoku(app.SAMPLE_9,name,encoding,10)
                    self.assertEqual(row['Status'],'SAT',row.get('Error'))
                    self.assertTrue(row['Is_Valid'])
                    self.assertTrue(app.verify_solution(app.SAMPLE_9,solution))

    def test_general_sizes(self):
        for n in (1,4,16,25,36):
            with self.subTest(n=n):
                grid=app.make_demo_grid(n)
                solution,row=app.solve_sudoku(grid,'cadical153','product',15)
                self.assertEqual(row['Status'],'SAT',row.get('Error'))
                self.assertTrue(app.verify_solution(grid,solution))

    def test_unsat_error_and_csv_append(self):
        grid=[row[:] for row in app.SAMPLE_9];grid[0][2]=5
        solution,row=app.solve_sudoku(grid,timeout=5)
        self.assertEqual(row['Status'],'UNSAT')
        self.assertEqual(row['Is_Valid'],'')
        self.assertIsNone(solution)
        _,error=app.solve_sudoku([[0]],solver='not_a_solver',timeout=5)
        self.assertEqual(error['Status'],'ERROR')
        self.assertIn('Error',error)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sat_results.csv'
            app.append_results(row,path);app.append_results(error,path)
            with path.open(encoding='utf-8-sig',newline='') as stream:
                reader=csv.DictReader(stream)
                self.assertEqual(reader.fieldnames,app.CSV_COLUMNS)
                rows=list(reader)
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['Status'],'UNSAT')
            self.assertEqual(rows[0]['Is_Valid'],'')
            path.write_text('different,header\n')
            with self.assertRaises(ValueError):app.append_results(row,path)

    def test_real_timeout_both_mechanisms(self):
        # Pigeonhole không có nghiệm; đủ khó để không hoàn tất trong 0.02 s.
        # Không dùng Sudoku dễ để giả vờ kiểm tra việc ngắt solver.
        cnf=PHP(nof_holes=18)
        for solver in ('glucose4','minisat22','cadical153','cryptominisat5'):
            if solver=='cryptominisat5':
                try:import pycryptosat
                except ImportError:continue
            with self.subTest(solver=solver):
                started=time.perf_counter()
                result=app.solve_cnf(cnf,solver,.02,cnf.nv)
                self.assertEqual(result['status'],'TIMEOUT')
                self.assertLess(time.perf_counter()-started,10)


if __name__=='__main__':
    unittest.main()
