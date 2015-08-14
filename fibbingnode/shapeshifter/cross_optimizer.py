import collections
import fibbingnode
import utils as _u


log = fibbingnode.log


class CrossOptimizer(object):
    def __init__(self, solver):
        self.solver = solver

    def solve(self, graph, requirements):
        lsas = self.solver.solve(graph, requirements)
        grouped_lsas = collections.defaultdict(list)
        # Group the LSAs by fakenodes
        for lsa in lsas:
            grouped_lsas[(lsa.node, lsa.nh)].append((lsa.cost, lsa.dest))
        # Build and aggregate LSA from these groups
        reduced_lsas = [_u.ExtendedLSA(node, nh,
                                       [_u.ExtLSARoute(dest=d, cost=c)
                                        for c, d in dests])
                        for (node, nh), dests in grouped_lsas.iteritems()]
        log.info('CrossOptimizer reduced the LSA count to %s (from %s)',
                  len(reduced_lsas), len(lsas))
        log.debug(reduced_lsas)
        return reduced_lsas
