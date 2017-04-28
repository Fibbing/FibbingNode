"""This file defines Northbound application controller classes."""

import abc
import copy
from ConfigParser import DEFAULTSECT

import networkx as nx

from fibbingnode.southbound.interface import FakeNodeProxy, ShapeshifterProxy
from fibbingnode.algorithms.ospf_simple import OSPFSimple
from fibbingnode.misc.sjmp import SJMPClient, ProxyCloner
from fibbingnode.misc.igp_graph import IGPGraph
from fibbingnode import CFG
from fibbingnode import log


def sanitize_edge_data(d):
    """Because json.decode() does not set all types back ..."""
    try:
        d['metric'] = int(d['metric'])
    except KeyError:
        pass
    return d


class SouthboundListener(ShapeshifterProxy):
    """This basic controller maintains a structure describing the IGP topology
    and listens for changes."""

    def __init__(self, *args, **kwargs):
        super(SouthboundListener, self).__init__(*args, **kwargs)
        self.igp_graph = IGPGraph()
        self.dirty = False
        self.json_proxy = SJMPClient(hostname=CFG.get(DEFAULTSECT,
                                                      'json_hostname'),
                                     port=CFG.getint(DEFAULTSECT, 'json_port'),
                                     target=self)
        self.quagga_manager = ProxyCloner(FakeNodeProxy, self.json_proxy)

    def run(self):
        """Connect the the southbound controller. This call will not return
        unless the connection is halted."""
        log.info('Connecting to server ...')
        self.json_proxy.communicate()

    def stop(self):
        """Stop the connection to the southbound controller"""
        self.json_proxy.stop()

    def bootstrap_graph(self, graph, node_properties):
        self.igp_graph.clear()
        self.igp_graph.add_edges_from(graph)
        for _, _, d in self.igp_graph.edges_iter(data=True):
            sanitize_edge_data(d)
        self.update_node_properties(**node_properties)
        log.debug('Bootstrapped graph with edges: %s and properties: %s',
                  self.igp_graph.edges(data=True), node_properties)
        self.received_initial_graph()
        self.graph_changed()

    def received_initial_graph(self):
        """Called when the initial graph has been bootstrapped, before
        calling graph_changed"""
        pass

    def add_edge(self, source, destination, properties={'metric': 1}):
        properties = sanitize_edge_data(properties)
        # metric is added twice to support backward-compat.
        self.igp_graph.add_edge(source, destination, properties)
        log.debug('Added edge: %s-%s@%s', source, destination, properties)
        # Only trigger an update if the link is bidirectional
        self.dirty = self.igp_graph.has_edge(destination, source)

    def commit(self):
        log.debug('End of graph update')
        if self.dirty:
            self.dirty = False
            self.graph_changed()

    @abc.abstractmethod
    def graph_changed(self):
        """Called when the IGP graph has changed."""

    def remove_edge(self, source, destination):
        # TODO: pay attention to re-add the symmetric edge if only one way
        # crashed
        try:
            self.igp_graph.remove_edge(source, destination)
            log.debug('Removed edge %s-%s', source, destination)
            self.igp_graph.remove_edge(destination, source)
            log.debug('Removed edge %s-%s', destination, source)
        except nx.NetworkXError:
            # This means that we had already removed both side of the edge
            # earlier or that the adjacency was not fully established before
            # going down
            pass
        else:
            self.dirty = True

    def update_node_properties(self, **properties):
        log.debug('Updating node propeties: %s', properties)
        for node, data in properties.iteritems():
            self.igp_graph.node[node].update(data)
        self.dirty = self.dirty or properties


class SouthboundController(SouthboundListener):
    """A simple northbound controller that monitors for changes in the IGP
    graph, and keeps track of advertized LSAs to remove them on exit"""
    def __init__(self, *args, **kwargs):
        super(SouthboundController, self).__init__(*args, **kwargs)
        self.advertized_lsa = set()

    def stop(self):
        self.remove_lsa(*self.advertized_lsa)
        super(SouthboundController, self).stop()

    @abc.abstractmethod
    def refresh_augmented_topo(self):
        """The IGP graph has changed, return the _set_ of LSAs that need to be
        advertized in the network (possibly just the previous one)"""

    def graph_changed(self):
        self.refresh_lsas()

    def advertize_lsa(self, *lsas):
        """Instructs the southbound controller to announce LSAs"""
        lsas = list(lsas)
        if lsas:
            self.quagga_manager.add(lsas)
            self.advertized_lsa.update(lsas)
        else:
            log.warning('Tried to advertize an empty list of LSA')

    def remove_lsa(self, *lsas):
        """Instructs the southbound controller to remove LSAs"""
        lsas = list(lsas)
        if lsas:
            self.quagga_manager.remove(lsas)
            self.advertized_lsa.difference_update(lsas)
        else:
            log.warning('Tried to remove an empty list of LSA')

    def _get_diff_lsas(self):
        new_lsas = self.refresh_augmented_topo()
        log.debug('New LSA set: %s', new_lsas)
        to_add = new_lsas.difference(self.advertized_lsa)
        to_rem = self.advertized_lsa.difference(new_lsas)
        log.debug('Removing LSA set: %s', to_rem)
        self.advertized_lsa = new_lsas
        return to_add, to_rem

    def refresh_lsas(self):
        """Refresh the set of LSAs that needs to be sent in the IGP,
        and instructs the southbound controller to update it if changed"""
        (to_add, to_rem) = self._get_diff_lsas()
        if not to_add and not to_rem:
            log.debug('Nothing to do for the current topology')
            return
        if to_rem:
            self.remove_lsa(*to_rem)
        if to_add:
            self.advertize_lsa(*to_add)


class StaticPathManager(SouthboundController):
    """Dumb controller that will simply enforce static lsas"""
    def __init__(self, *args, **kwargs):
        super(StaticPathManager, self).__init__(*args, **kwargs)
        self.demands = set()

    def refresh_augmented_topo(self):
        return set(self.demands)

    def add_lie(self, *lies):
        """Add lies (LSA) to send in the network"""
        self.demands.update(lies)
        self.refresh_lsas()

    def remove_lie(self, *lies):
        """Remove lies (LSA) to send in the network"""
        self.demands.difference_update(lies)
        self.refresh_lsas()


class SouthboundManager(SouthboundController):
    """A Northbound controller that will use a solver to implement path
    requirements expressed as forwarding DAGs"""
    def __init__(self,
                 fwd_dags=None,
                 optimizer=None,
                 additional_routes=None,
                 *args, **kwargs):
        self.additional_routes = additional_routes
        self.current_lsas = set([])
        self.optimizer = optimizer if optimizer else OSPFSimple()
        self.fwd_dags = fwd_dags if fwd_dags else {}
        self.has_initial_topo = False
        super(SouthboundManager, self).__init__(*args, **kwargs)

    def refresh_augmented_topo(self):
        log.info('Solving topologies')
        if not self.json_proxy.alive() or not self.has_initial_topo:
            log.debug('Skipping as we do not yet have a topology')
            return self.advertized_lsa
        try:
            self.optimizer.solve(self.igp_graph.copy(),
                                 {p: dag.copy()
                                  for p, dag in self.fwd_dags.iteritems()})
        except Exception as e:
            log.exception(e)
            return self.advertized_lsa
        else:
            return set(self.optimizer.get_fake_lsas())

    def simple_path_requirement(self, prefix, path):
        """Add a path requirement for the given prefix.

        :param path: The ordered list of routerid composing the path.
                     E.g. for path = [A, B, C], the following edges will be
                     used as requirements: [](A, B), (B, C), (C, D)]"""
        self.fwd_dags[prefix] = IGPGraph(
                [(s, d) for s, d in zip(path[:-1], path[1:])])
        self.refresh_lsas()

    def add_dag_requirement(self, prefix, dag):
        self.fwd_dags[prefix] = dag.copy()
        self.refresh_lsas()

    def add_dag_requirements_from(self, fw_dags):
        """
        Adds a bunch of fw dag requirements
        :param fw_dags: dictionary prefix -> dag
        """
        self.fwd_dags.update(copy.deepcopy(fw_dags))
        self.refresh_lsas()

    def remove_dag_requirement(self, prefix):
        if prefix in self.fwd_dags.keys():
            self.fwd_dags.pop(prefix)
            self.refresh_lsas()

    def remove_all_dag_requirements(self):
        self.fwd_dags.clear()
        self.refresh_lsas()

    def received_initial_graph(self):
        log.debug('Sending initial lsa''s')
        self.has_initial_topo = True
        if self.additional_routes:
            self.advertize_lsa(*self.additional_routes)
