#!/usr/bin/env python
# encoding: utf-8

from fibbingnode.southbound.interface import FakeNodeProxy, ShapeshifterProxy
from fibbingnode.misc.sjmp import SJMPClient, ProxyCloner
from fibbingnode import CFG
from fibbingnode import log
import logging
from ConfigParser import DEFAULTSECT
import networkx as nx


log.setLevel(logging.DEBUG)


class SouthboundManager(ShapeshifterProxy):
    def __init__(self, fwd_dags, optimizer, additional_routes=None):
        self.igp_graph = nx.DiGraph()
        self.dirty = False
        self.additional_routes = additional_routes
        self.optimizer = optimizer
        self.fwd_dags = fwd_dags
        self.current_lsas = set([])
        self.json_proxy = SJMPClient(hostname=CFG.get(DEFAULTSECT,
                                                      'json_hostname'),
                                     port=CFG.getint(DEFAULTSECT, 'json_port'),
                                     target=self)
        self.quagga_manager = ProxyCloner(FakeNodeProxy, self.json_proxy)

    def run(self):
        log.info('Connecting to server ...')
        self.json_proxy.communicate()

    def stop(self):
        self.quagga_manager.remove(list(self.current_lsas))
        self.json_proxy.stop()

    # Helper functions
    def _refresh_augmented_topo(self):
        log.info('Solving topologies')
        self.optimizer.solve(self.igp_graph,
                             self.fwd_dags)

    def _get_diff_lsas(self):
        self._refresh_augmented_topo()
        new_lsas = set(self.optimizer.get_fake_lsas())
        log.info('New LSA set: %s', new_lsas)
        to_add = new_lsas.difference(self.current_lsas)
        to_rem = self.current_lsas.difference(new_lsas)
        log.info('Removing LSA set: %s', to_rem)
        self.current_lsas = new_lsas
        return to_add, to_rem

    def _refresh_lsas(self):
        (to_add, to_rem) = self._get_diff_lsas()
        if to_rem:
            self.quagga_manager.remove(list(to_rem))
        if to_add:
            self.quagga_manager.add(list(to_add))

    # Interface functions
    def boostrap_graph(self, graph):
        self.igp_graph.clear()
        for u, v, metric in graph:
            self.igp_graph.add_edge(u, v, weight=int(metric))
        log.debug('Bootstrapped graph with edges: %s', self.igp_graph.edges())
        log.debug('Sending initial lsa''s')
        if self.additional_routes:
            self.quagga_manager.add_static(self.additional_routes)
        self._refresh_lsas()

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
            self._refresh_lsas()
            self.dirty = False

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
