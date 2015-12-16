import utils as ssu
import networkx as nx
from fibbingnode import log as logger
import sys

class OSPFSimple(object):
    def __init__(self):
        self.new_edge_weight = 10e4

    def add_dest_to_graphs(self, dest, dag):
        if dest not in dag:
            for node in ssu.find_sink(dag):
                logger.info('Connected %s to %s in the DAG', node, dest)
                dag.add_edge(node, dest)

    def get_fake_lsas(self):
        return self.fake_ospf_lsas

    def nhs_for(self, node, dag, dest):
        req_nhs = dag.successors(node)
        # compute the originals next-hops of the current node
        try:
            original_nhs = [p[1]
                            for p in self.igp_paths[node][0][dest]]
        except KeyError:
            original_nhs = []
        return req_nhs, original_nhs

    @staticmethod
    def require_fake_node(req_nhs, original_nhs):
        return len(req_nhs) > 1 or\
               len(original_nhs) > 1 or\
               set(req_nhs).symmetric_difference(original_nhs)

    def solvable(self, dest, dag):
        for u, v in dag.edges_iter():
            try:
                self.igp_graph[u][v]
            except:
                logger.error('Cannot satisfy the DAG for dest %s '
                             ' as (%s, %s) is not in the IGP graph',
                             dest, u, v)
                logger.error('Available edges: %s', self.igp_graph.edges())
                logger.error('DAG: %s', dag.edges())
                return False
        return True

    def complete_dag(self):
        """Complete the DAG so that missing nodes have their old (or part of)
        SPT in it"""
        for n in self.igp_graph:
            if n in self.dag or n in self.reqs or\
                    not self.igp_graph.successors(n):
                continue  # n has its SPT instructions or is a destination node
            for p in self.igp_paths[n][0][self.dest]:
                for u, v in zip(p[:-1], p[1:]):
                    v_in_dag = v in self.dag
                    self.dag.add_edge(u, v)
                    if v_in_dag:  # we connected u to the new SPT
                        break

    def solve(self, topo, requirement_dags):
        # a list of tuples with info on the node to be attracted,
        # the forwarding address, the cost to be set in the fake LSA,
        # and the respective destinations
        self.fake_ospf_lsas = []
        self.reqs = requirement_dags
        self.igp_graph = topo
        self.igp_paths = ssu.all_shortest_paths(self.igp_graph)
        # process input forwarding DAGs, one at the time
        for dest, dag in requirement_dags.iteritems():
            logger.debug('Solving DAG for dest %s', dest)
            self.dest, self.dag = dest, dag
            self.add_dest_to_graphs(dest, dag)
            if dest not in topo:
                sinks = dag.predecessors(dest)
                for s in sinks:
                    logger.info('Adding edge (%s, %s) in the graph',
                                s, self.dest)
                    topo.add_edge(s, dest, weight=self.new_edge_weight)
                for n in topo.nodes_iter():
                    if n == dest:  # dest is a path in itself
                        self.igp_paths[n] = ([[n]], 0)
                        continue
                    paths = []
                    cost = sys.maxint
                    for s in sinks:
                        if s not in self.igp_paths[n][0]:  # no path to sink
                            continue
                        c = self.igp_paths[n][1][s]
                        p = self.igp_paths[n][0][s]
                        if c < cost:  # new spt
                            paths = list(ssu.extend_paths_list(p, dest))
                            cost = c
                        if c == cost:  # ecmp
                            paths.extend(ssu.extend_paths_list(p, dest))
                    if paths:
                        _t = self.igp_paths[n]
                        _t[0][dest] = paths
                        _t[1][dest] = cost
            self.complete_dag()
            # Add temporarily the destination to the igp graph and/or req dags
            if not self.solvable(dest, dag):
                continue
            for node in nx.topological_sort(dag, reverse=True)[1:]:
                nhs, original_nhs = self.nhs_for(node, dag, dest)
                if not self.require_fake_node(nhs, original_nhs):
                    logger.debug('%s does not require a fake node (%s - %s)',
                                 node, nhs, original_nhs)
                    continue
                for req_nh in nhs:
                    logger.debug('Placing a fake node for nh %s', req_nh)
                    self.fake_ospf_lsas.append(ssu.LSA(node=node,
                                                       nh=req_nh,
                                                       cost=-1,
                                                       dest=dest))
        return self.fake_ospf_lsas
