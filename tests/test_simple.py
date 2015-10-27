import unittest
import test_merger
import fibbingnode.algorithms.ospf_simple as smpl


class TestSimple(test_merger.MergerTestCase):
    def __init__(self, *args, **kwargs):
        super(TestSimple, self).__init__(*args, **kwargs)
        self.solver_provider = smpl.OSPFSimple

    def _test(self, igp_topo, fwd_dags, expected_lsa_count):
        solver = self.solver_provider()
        lsas = solver.solve(igp_topo, fwd_dags)
        self.assertTrue(test_merger.check_fwd_dags(fwd_dags,
                                                   igp_topo,
                                                   lsas,
                                                   solver))

if __name__ == '__main__':
    unittest.main()
