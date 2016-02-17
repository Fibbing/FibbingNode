"""This module provides a structure to represent an IGP topology"""
import os
import networkx as nx

from fibbingnode import log

# The draw_graph call will be remapped to 'nothing' if matplotlib (aka extra
# packages) is not available
try:
    import matplotlib.pyplot as plt
except ImportError:
    log.warning('Missing packages to draw the network, disabling the fonction')
    def draw_graph(*_): pass
else:
    def draw_graph(graph, output):
        """If matplotlib is available, draw the given graph to output file"""
        try:
            layout = spring_layout(graph)
            metrics = {
                (src, dst): data['metric']
                for src, dst, data in graph.edges_iter(data=True)
            }
            nx.draw_networkx_edge_labels(graph, layout, edge_labels=metrics)
            nx.draw(graph, layout, node_size=20)
            nx.draw_networkx_labels(graph, layout, labels={n: n for n in graph})
            if os.path.exists(output):
                os.unlink(output)
            plt.savefig(output)
            plt.close()
            log.debug('Graph of %d nodes saved in %s', len(graph), output)
        except:
            pass


class IGPGraph(nx.DiGraph):
    """This class represents an IGP graph, and defines a few useful bindings"""
    def __init__(self, metric_key='metric',
                 *args, **kwargs):
        super(IGPGraph, self).__init__(*args, **kwargs)
        self.metric_key = metric_key

    def draw(self, dest):
        """Draw this graph to dest"""
        draw_graph(self, dest)

    def difference(self, other):
        """Return the list of edges that other does not have wrt. this graph"""
        return [(u, v) for u, v in self.edges_iter()
                if not other.has_edge(u, v)]

    def _add_node(self, *names, **kw):
        for n in names:
            self.add_node(n, **kw)

    def add_controller(self, *names, **kw):
        """Add a controller node to the graph"""
        self._add_node(*names, controller=True, **kw)

    def add_router(self, *names, **kw):
        """Add a router node to the graph"""
        self._add_node(*names, router=True, **kw)

    def add_prefix(self, *prefixes, **kw):
        """Add a prefix node to the graph"""
        self._add_node(*prefixes, prefix=True, **kw)

    def add_fake_prefix(self, *prefixes, **kw):
        """Add a fake prefix node to the graph"""
        self.add_prefix(*prefixes, fake=True, **kw)

    def _is_x(self, n, x, val=True):
        try:
            return self.node[n][x] == val
        except KeyError:
            return False

    def is_router(self, n):
        """Return whether n is a router or not"""
        return self._is_x(n, 'router')

    def is_controller(self, n):
        """Return whether n is a controller or not"""
        return self._is_x(n, 'controller')

    def is_prefix(self, n):
        """Return whether n is a prefix or not"""
        return self._is_x(n, 'prefix')

    def is_real_prefix(self, n):
        """Return whether n is a prefix from a real LSA"""
        return self._is_x(n, 'prefix') and not self._is_x(n, 'fake')

    def is_fake_prefix(self, n):
        """Return whether n is a prefix from a fake LSA"""
        return self._is_x(n, 'prefix') and self._is_x(n, 'fake')

    def _get_all(self, predicate):
        for n in self.nodes_iter():
            if predicate(n):
                yield n

    @property
    def routers(self):
        """Returns a generator over all routers in the graph
        Example: all_routers = list(graph.routers)
        """
        return self._get_all(self.is_router)

    @property
    def controllers(self):
        """Returns a generator over all controllers in the graph
        Example: all_controllers = list(graph.controllers)
        """
        return self._get_all(self.is_controller)

    @property
    def all_prefixes(self):
        """Returns a generator over all prefixes in the graph"""
        return self._get_all(self.is_prefix)

    @property
    def real_prefixes(self):
        """Returns a generator over all prefixes in the graph that are not
        announced by fake LSAs"""
        return self._get_all(self.is_real_prefix)

    @property
    def fake_prefixes(self):
        """Returns a generator over all prefixes in the graph that are
        announced by fake LSAs"""
        return self._get_all(self.is_fake_prefix)

    def metric(self, u, v, m=None):
        """Return the link metric for link u->v, or set it if m is not None"""
        if m:
            self[u][v][self.metric_key] = m
        else:
            return self[u][v].get(self.metric_key, 1)

    def contract(self, into, nbunch):
        """Contract nodes from nbunch into a single node named into"""
        self.add_edges_from(((into, v, data) for _, v, data
                             in self.edges_iter(nbunch, data=True)))
        self.remove_nodes_from(nbunch)
