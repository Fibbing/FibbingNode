import shape_shifter_utils as ssu
import networkx as nx
import modified_dijkstra as md
from fibbingnode import log as logger


class OspfNaiveLadder(object):

    def get_new_fake_node(self, nh):
        new_fake_node = "f" + str(self.vnode_id_counter)
        self.vnode_id_counter += 1
        self.vnode_ids.add(new_fake_node)
        return new_fake_node

    def add_dest_to_graphs(self, dest, dag):
        if dest not in dag:
            for node in ssu.find_sink(dag):
                logger.info('Connected %s to %s in the DAG', node, dest)
                dag.add_edge(node, dest)
            return True
        return False

    def remove_added_dest(self, added_edges):
        node_to_rem = list(self.vnode_ids)
        added_edges.extend(self.igp_graph.in_edges(node_to_rem, data=True))
        self.igp_graph.remove_nodes_from(node_to_rem)
        self.vnode_ids.clear()

    def get_fake_lsas(self):
        return self.fake_ospf_lsas

    def nhs_for(self, node, dag, dest):
        req_nhs = dag.successors(node)
        # compute the originals next-hops of the current node
        try:
            original_nhs = [p.split(' ')[1]
                            for p in self.igp_paths[node][dest]]
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

    def solve(self, topo, requirement_dags):
        self.vnode_id_counter = 0
        self.vnode_ids = set()
        # a list of tuples with info on the node to be attracted,
        # the forwarding address, the cost to be set in the fake LSA,
        # and the respective destinations
        self.fake_ospf_lsas = []
        added_edges = []
        self.igp_graph = topo
        # process input forwarding DAGs, one at the time
        for dest, dag in requirement_dags.iteritems():
            logger.debug('Solving DAG for dest %s', dest)
            self.dest, self.dag = dest, dag
            # Add temporarily the destination to the igp graph and/or req dags
            if not self.solvable(dest, dag):
                continue
            added = self.add_dest_to_graphs(dest, dag)
            self.igp_paths = md.all_pairs_dijkstra_ecmp_path(self.igp_graph)
            for node in nx.topological_sort(dag, reverse=True)[1:]:
                nhs, original_nhs = self.nhs_for(node, dag, dest)
                if not self.require_fake_node(nhs, original_nhs):
                    logger.debug('%s does not require a fake node', node)
                    continue
                for req_nh in nhs:
                    logger.debug('Placing a fake node for nh %s', req_nh)
                    new_fake_node = self.get_new_fake_node(req_nh)
                    self.fake_ospf_lsas.append((node, req_nh, -1, dest))
                    self.igp_graph.add_edges_from(
                        [(node, new_fake_node, {'weight': -1}),
                         (new_fake_node, dest, {'weight': -1})])
            # Remove The destination from the graph otherwise
            # it could be used as a router node in the next iteration
            if added:
                dag.remove_nodes_from([dest])
            self.remove_added_dest(added_edges)
        return self.igp_graph
