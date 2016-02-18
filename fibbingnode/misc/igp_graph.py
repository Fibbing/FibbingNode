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
    def draw_graph(*_):
        """Can't draw without matplotlib"""
        pass
else:
    def draw_graph(graph, output):
        """If matplotlib is available, draw the given graph to output file"""
        try:
            layout = nx.spring_layout(graph)
            metrics = {
                (src, dst): data['metric']
                for src, dst, data in graph.edges_iter(data=True)
            }
            nx.draw_networkx_edge_labels(graph, layout, edge_labels=metrics)
            nx.draw(graph, layout, node_size=20)
            nx.draw_networkx_labels(graph, layout,
                                    labels={n: n for n in graph})
            if os.path.exists(output):
                os.unlink(output)
            plt.savefig(output)
            plt.close()
            log.debug('Graph of %d nodes saved in %s', len(graph), output)
        except:
            pass


METRIC = 'metric'
FAKE = 'fake'
LOCAL = 'local'


class IGPGraph(nx.DiGraph):
    """This class represents an IGP graph, and defines a few useful bindings"""

    EXPORT_KEYS = (METRIC, LOCAL, FAKE)

    def __init__(self, *args, **kwargs):
        super(IGPGraph, self).__init__(*args, **kwargs)

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

    def add_route(self, router, prefix, **kw):
        """Add routes to the graph"""
        self._add_node(prefix, prefix=True)
        self.add_edge(router, prefix, **kw)

    def add_fake_route(self, router, prefix, **kw):
        """Add a fake prefix node to the graph"""
        self.add_route(router, prefix, fake=True, **kw)

    def add_local_route(self, router, prefix, targets, **kw):
        """Add a fake local route available for specified targets"""
        if not is_container(targets):
            targets = [targets]
        self.add_fake_route(router, prefix, local=True, target=targets, **kw)

    def _is_x(self, n, x, val=True):
        try:
            return self.node[n][x] == val
        except KeyError:
            return False

    def _edge_is_x(self, u, v, x, val=True):
        try:
            return self[u][v][x] == val
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

    def is_route(self, _, v):
        """Return whether edge _,v is a route"""
        return self._is_x(v, 'prefix')

    def is_real_route(self, u, v):
        """Return whether u,v is an edge mapping to a real LSA"""
        return self.is_route(u, v) and not self._edge_is_x(u, v, 'fake')

    def is_fake_route(self, u, v):
        """Return whether edge u,v is a route from a fake LSA"""
        return self.is_route(u, v) and self._edge_is_x(u, v, 'fake')

    def is_global_lie(self, u, v):
        """Return wether u,v is a global lie"""
        return self.is_fake_route(u, v) and not self._edge_is_x(u, v, 'target')

    def is_local_lie(self, u, v, target=None):
        """Return wether u,v is a local lie, optionally check if it applies to
        the given target(s)"""
        isfake = self.is_fake_route(u, v)
        targets = self[u][v].get('target', False)
        return isfake and targets and (not target or target in targets)

    def local_lie_target(self, n):
        """Return the target node(s) as a list for that local lies"""
        try:
            return self.node[n]['target']
        except KeyError:
            raise ValueError('%s is not a local lie!' % n)

    def _get_all(self, predicate):
        for n in self.nodes_iter():
            if predicate(n):
                yield n

    def _get_all_edges(self, predicate):
        for u, v in self.edges_iter():
            if predicate(u, v):
                yield u, v

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
    def prefixes(self):
        """Returns a generator over all prefixes in the graph"""
        return self._get_all(self.is_prefix)

    @property
    def all_routes(self):
        """Returns a generator over all routes in the graph"""
        return self._get_all_edges(self.is_route)

    @property
    def real_routes(self):
        """Returns a generator over all real routes in the graph"""
        return self._get_all_edges(self.is_real_route)

    @property
    def fake_routes(self):
        """Returns a generator over all fake routes in the graph"""
        return self._get_all_edges(self.is_fake_route)

    @property
    def local_lies(self, target=False):
        """Returns a generator over all local lies in the graph, possibly
        return the target neighbours of it."""
        for n in self._get_all_edges(self.is_local_lie):
            yield n if not target else (n, self.local_lie_target(n))

    @property
    def global_lies(self):
        """Returns a generator over all global lies in the graph"""
        return self._get_all_edges(self.is_global_lie)

    def metric(self, u, v, m=None):
        """Return the link metric for link u->v, or set it if m is not None"""
        if m:
            self[u][v][METRIC] = m
        else:
            return self[u][v].get(METRIC, 1)

    def contract(self, into, nbunch):
        """Contract nodes from nbunch into a single node named into"""
        self.add_edges_from(((into, v, data) for _, v, data
                             in self.edges_iter(nbunch, data=True)))
        self.remove_nodes_from(nbunch)

    def _filter_edge_data(self, data):
        return {n: data.get(n, False) for n in self.EXPORT_KEYS}

    def export_edge_data(self, u, v):
        """Return the exportable properties of an edge"""
        return self._filter_edge_data(self[u][v])

    def export_edges(self):
        """Return a generator yielding a 3-tuple for all edges:
        src, dst, exportable properties"""
        for u, v, d in self.edges_iter(data=True):
            export_data = self._filter_edge_data(d)
            yield u, v, export_data
