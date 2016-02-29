#!/usr/bin/env python
# -*- coding: utf-8 -*-
import unittest

import networkx as nx

import fibbingnode.algorithms.cross_optimizer as crossopt
import fibbingnode.algorithms.merger as merger
import fibbingnode.algorithms.utils as ssu
import fibbingnode as fibbing

from test_merger import MergerTestCase

log = fibbing.log
fibbing.log_to_file('test_crossopt.log', 'w')

#
# Useful tip to selectively disable test: @unittest.skip('reason')
#


def check_fwd_dags(fwd_req, topo, lsas, solver):
    correct = True
    topo = topo.copy()
    # Check that the topology/dag contain the destinations, otherwise add it
    for dest, dag in fwd_req.iteritems():
        dest_in_dag = dest in dag
        dest_in_graph = dest in topo
        if not dest_in_dag or not dest_in_graph:
            if not dest_in_dag:
                sinks = ssu.find_sink(dag)
            else:
                sinks = dag.predecessors(dest)
            for s in sinks:
                if not dest_in_dag:
                    dag.add_edge(s, dest)
                if not dest_in_graph:
                    topo.add_edge(s, dest,
                                  metric=solver.solver.new_edge_metric)
    fake_nodes = {}
    local_fake_nodes = {}
    f_ids = set()
    for lsa in lsas:
        for route in lsa.routes:
            if route.cost > 0:
                f_id = '__f_%s_%s_%s' % (lsa.node, lsa.nh, route.dest)
                f_ids.add(f_id)
                fake_nodes[(lsa.node, f_id, route.dest)] = lsa.nh
                cost = topo[lsa.node][lsa.nh]['metric']
                topo.add_edge(lsa.node, f_id, metric=cost)
                topo.add_edge(f_id, route.dest, metric=route.cost - cost)
                log.debug('Added a globally-visible fake node: '
                          '%s - %s - %s - %s - %s [-> %s]',
                          lsa.node, cost, f_id, route.cost - cost,
                          route.dest, lsa.nh)
            else:
                local_fake_nodes[(lsa.node, route.dest)] = lsa.nh
                log.debug('Added a locally-visible fake node: %s -> %s',
                          lsa.node, lsa.nh)

    spt = ssu.all_shortest_paths(topo, metric='metric')
    for dest, req_dag in fwd_req.iteritems():
        log.info('Validating requirements for dest %s', dest)
        dag = nx.DiGraph()
        for n in filter(lambda n: n not in fwd_req, topo):
            if n in f_ids:
                continue
            log.debug('Checking paths of %s', n)
            for p in spt[n][0][dest]:
                log.debug('Reported path: %s', p)
                for u, v in zip(p[:-1], p[1:]):
                    try:  # Are we using a globally-visible fake node?
                        nh = fake_nodes[(u, v, dest)]
                        log.debug('%s uses the globally-visible fake node %s '
                                  'to get to %s', u, v, nh)
                        dag.add_edge(u, nh)  # Replace by correct next-hop
                        break
                    except KeyError:
                        try:  # Are we using a locally-visible one?
                            nh = local_fake_nodes[(u, dest)]
                            log.debug('%s uses a locally-visible fake node '
                                      'to get to %s', u, nh)
                            dag.add_edge(u, nh)  # Replace by true nh
                            break
                        except KeyError:
                            dag.add_edge(u, v)  # Otherwise follow the SP
        # Now that we have the current fwing dag, compare to the requirements
        for n in req_dag:
            successors = set(dag.successors(n))
            req_succ = set(req_dag.successors(n))
            if successors ^ req_succ:
                log.error('The successor sets for node %s differ, '
                          'REQ: %s, CURRENT: %s', n, req_succ, successors)
                correct = False
            predecessors = set(dag.predecessors(n))
            req_pred = set(req_dag.predecessors(n))
            # Also requires to have a non-null successor sets to take into
            # account the fact that the destination will have new adjacencies
            # through fake nodes
            if predecessors ^ req_pred and successors:
                log.error('The predecessors sets for %s differ, '
                          'REQ: %s, CURRENT: %s', n, req_pred, predecessors)
                correct = False
    if correct:
        log.info('All forwarding requirements are enforced!')
    return correct


class CrossOptimizerTestCase(MergerTestCase):

    def _test(self, igp_topo, fwd_dags, expected_lsa_count):
        solver = crossopt.CrossOptimizer(solver=merger.PartialECMPMerger())
        # Duplicating dag to show the effect of cross optimization
        for d, dag in fwd_dags.items():
            fwd_dags['%s_copy' % d] = dag.copy()
        lsas = solver.solve(igp_topo, fwd_dags)
        self.assertTrue(check_fwd_dags(fwd_dags, igp_topo, lsas, solver))
        self.assertTrue(len(lsas) == expected_lsa_count)


if __name__ == '__main__':
    unittest.main()
