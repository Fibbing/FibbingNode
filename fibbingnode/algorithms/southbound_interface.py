#!/usr/bin/env python
# encoding: utf-8

from fibbingnode.southbound.interface import FakeNodeProxy, ShapeshifterProxy
from fibbingnode.algorithms.ospf_simple import OSPFSimple
from fibbingnode.misc.sjmp import SJMPClient, ProxyCloner
from fibbingnode import CFG
from fibbingnode import log
from ConfigParser import DEFAULTSECT

import abc
import networkx as nx


class SouthboundController(ShapeshifterProxy):
    def __init__(self, *args, **kwargs):
        super(SouthboundController, self).__init__(*args, **kwargs)
        self.igp_graph = nx.DiGraph()
        self.dirty = False
        self.advertized_lsa = set()
        self.json_proxy = SJMPClient(hostname=CFG.get(DEFAULTSECT,
                                                      'json_hostname'),
                                     port=CFG.getint(DEFAULTSECT, 'json_port'),
                                     target=self)
        self.quagga_manager = ProxyCloner(FakeNodeProxy, self.json_proxy)

    def run(self):
        log.info('Connecting to server ...')
        self.json_proxy.communicate()

    def stop(self):
        self.remove_lsa(*self.advertized_lsa)
        self.json_proxy.stop()

    def boostrap_graph(self, graph):
        self.igp_graph.clear()
        for u, v, metric in graph:
            self.igp_graph.add_edge(u, v, weight=int(metric))
        log.debug('Bootstrapped graph with edges: %s',
                  self.igp_graph.edges(data=True))
        self.received_initial_graph()
        self._refresh_lsas()

    def received_initial_graph(self):
        pass

    def add_edge(self, source, destination, metric):
        self.igp_graph.add_edge(source, destination, weight=int(metric))
        log.debug('Added edge: %s-%s@%s', source, destination, metric)
        try:
            self.igp_graph[destination][source]
        except KeyError:
            # Only trigger an update if the link is bidirectional
            pass
        else:
            self.dirty = True

    def commit(self):
        if self.dirty:
            self.dirty = False
            self.graph_changed()

    @abc.abstractmethod
    def refresh_augmented_topo(self):
        """The IGP graph has changed, return the _set_ of LSAs that need to be
        advertized in the network (possibly just the previous one)"""

    def graph_changed(self):
        self.refresh_lsas()
        """Called when there has been a change in the IGP topology"""

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
            # earlier
            pass
        else:
            self.dirty = True

    def advertize_lsa(self, *lsas):
        lsas = list(lsas)
        if lsas:
            self.quagga_manager.add(lsas)
            self.advertized_lsa.update(lsas)
        else:
            log.warning('Tried to advertize an empty list of LSA')

    def remove_lsa(self, *lsas):
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
        self.current_lsas = new_lsas
        return to_add, to_rem

    def refresh_lsas(self):
        (to_add, to_rem) = self._get_diff_lsas()
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
        return self.demands

    def add_lie(self, *lies):
        """Add lies (LSA) to send in the network"""
        self.demands.update(lies)
        self.refresh_lsas()

    def remove_lie(self, *lies):
        """Remove lies (LSA) to send in the network"""
        self.demands.difference_update(lies)
        self.refresh_lsas()


class SouthboundManager(SouthboundController):
    def __init__(self,
                 fwd_dags=None,
                 optimizer=None,
                 additional_routes=None,
                 *args, **kwargs):
        self.additional_routes = additional_routes
        self.current_lsas = set([])
        self.optimizer = optimizer if optimizer else OSPFSimple()
        self.fwd_dags = fwd_dags if fwd_dags else {}
        super(SouthboundManager, self).__init__(*args, **kwargs)

    def refresh_augmented_topo(self):
        log.info('Solving topologies')
        try:
            self.optimizer.solve(self.igp_graph,
                                 self.fwd_dags)
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
        self.fwd_dags[prefix] = nx.DiGraph([(s, d) for s, d in zip(path[:-1],
                                                                   path[1:])])

    def received_initial_graph(self):
        log.debug('Sending initial lsa''s')
        if self.additional_routes:
            self.advertize_lsa(*self.additional_routes)
