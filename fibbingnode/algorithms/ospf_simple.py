import utils as ssu
from fibbingnode import log
from fibbingnode.misc.igp_graph import ShortestPath


def get_edge_multiplicity(dag, node, req_nh):
    try:
        return int(dag.get_edge_multiplicity(node, req_nh))
    except AttributeError:  # Not an IGPGraph
        return 1


def is_fake(g, u, v):
    try:
        return g.is_fake_route(u, v)
    except AttributeError:
        return False


class OSPFSimple(object):
    def __init__(self):
        self.new_edge_metric = int(10e4)

    def get_fake_lsas(self):
        return self.fake_ospf_lsas

    def nhs_for(self, node, dest, dag):
        req_nhs = dag.successors(node)
        if not req_nhs:
            log.debug('%s does not need a path towards %s', node, dest)
            return []
        # compute the originals next-hops of the current node
        try:
            original_nhs = [
                    p[1] for p in self.igp_paths.default_path(node, dest)]
        except KeyError:
            log.debug("%s had no NH towards %s", node, dest)
            original_nhs = []
        max_multiplicity = max(
                map(lambda v: get_edge_multiplicity(dag, node, v), req_nhs))
        if (not set(req_nhs).symmetric_difference(original_nhs) and
                max_multiplicity == 1):
            log.debug("Same NH sets and no multiplicity from %s to %s",
                      node, dest)
            return []
        log.debug('Max multiplicity: %d // '
                  'NHs sets: original(%s) - required(%s)',
                  max_multiplicity, original_nhs, req_nhs)
        return req_nhs

    def solve(self, topo, requirement_dags):
        # a list of tuples with info on the node to be attracted,
        # the forwarding address, the cost to be set in the fake LSA,
        # and the respective destinations
        self.fake_ospf_lsas = []
        self.reqs = requirement_dags
        self.igp_graph = topo
        self.igp_paths = ShortestPath(self.igp_graph)
        # process input forwarding DAGs, one at the time
        for dest, dag in requirement_dags.iteritems():
            log.info('Solving DAG for dest %s', dest)
            self.dest, self.dag = dest, dag
            log.debug('Checking dest in dag')
            ssu.add_dest_to_graph(dest, dag)
            log.debug('Checking dest in igp graph')
            ssu.add_dest_to_graph(dest, topo,
                                  edges_src=dag.predecessors,
                                  spt=self.igp_paths,
                                  metric=self.new_edge_metric)
            ssu.complete_dag(dag, topo, dest, self.igp_paths,
                             skip=self.reqs.keys())
            # Add temporarily the destination to the igp graph and/or req dags
            if not ssu.solvable(dag, topo):
                log.warning('Skipping requirement for dest: %s', dest)
                continue
            for node in dag:
                nhs = self.nhs_for(node, dest, dag)
                if not nhs:
                    continue
                for req_nh in nhs:
                    log.debug('Placing a fake node for %s->%s', node, req_nh)
                    for i in xrange(get_edge_multiplicity(dag, node, req_nh)):
                        self.fake_ospf_lsas.append(ssu.LSA(node=node,
                                                           nh=req_nh,
                                                           cost=(-1 - i),
                                                           dest=dest))
            # Check whether we need to include one more fake node to handle
            # the case where we create a new route from scratch.
            for p in dag.predecessors_iter(dest):
                if not is_fake(topo, p, dest):
                    continue
                log.debug('%s is a terminal node towards %s but had no prior '
                          'route to it! Adding a synthetic route', p, dest)
                self.fake_ospf_lsas.append(
                        ssu.GlobalLie(dest, self.new_edge_metric, p))
        return self.fake_ospf_lsas
