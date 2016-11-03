"""This module provides a structure to represent an IGP topology"""
import os
import sys
import heapq
import networkx as nx
from itertools import count

from fibbingnode import log
import fibbingnode.algorithms.utils as ssu
from fibbingnode.misc.utils import extend_paths_list, is_container

# The draw_graph call will be remapped to 'nothing' if matplotlib (aka extra
# packages) is not available
try:
    import matplotlib
    matplotlib.use('PDF')
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
LOCAL = 'target'
MULTIPLICITY_KEY = 'multiplicity'


class IGPGraph(nx.DiGraph):
    """This class represents an IGP graph, and defines a few useful bindings"""

    def __init__(self, *args, **kwargs):
        super(IGPGraph, self).__init__(*args, **kwargs)
        self._export_keys = (METRIC, LOCAL, FAKE)

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
        self.add_fake_route(router, prefix, target=targets, **kw)

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

    def is_router_link(self, u, v):
        """Return wether a given edge is a link between two routers"""
        return self.is_router(u) and self.is_router(v) and v in self[u]

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

    @property
    def router_links(self):
        """Return a generator over all intra-router links"""
        return self._get_all_edges(self.is_router_link)

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
        return {n: data.get(n, False) for n in self._export_keys}

    def export_edge_data(self, u, v):
        """Return the exportable properties of an edge"""
        return self._filter_edge_data(self[u][v])

    def export_edges(self):
        """Return a generator yielding a 3-tuple for all edges:
        src, dst, exportable properties"""
        for u, v, d in self.edges_iter(data=True):
            export_data = self._filter_edge_data(d)
            yield u, v, export_data

    def real_neighbors(self, n):
        """List the real (non dest) nodes in this graph"""
        return filter(self.is_router, self.neighbors_iter(n))

    def set_edge_multiplicity(self, u, v, m):
        """Define the edge multiplicity, typically to encode splitting ratios
        in the graph.

        :param u, v: The edges end points
        :param m: The multiplicity value"""
        self[u][v][MULTIPLICITY_KEY] = m

    def get_edge_multiplicity(self, u, v):
        """Return the multiplicity of the edge u, v"""
        return self[u][v].get(MULTIPLICITY_KEY, 1)


class ShortestPath(object):
    """A class storing shortest-path trees"""
    def __init__(self, graph):
        self._default_paths = {}
        self._default_dist = {}
        # Calculate non-fibbed Dijkstra
        for n in graph.nodes_iter():
            (self._default_paths[n],
             self._default_dist[n]) = self.__default_spt_for_src(graph, n)
        # We do not Fib all destinations, re-use pre-computed ones
        fibbed_dst = set(v for _, v in graph.fake_routes)
        pure_dst = set(n for n in graph.nodes_iter()
                       if n not in fibbed_dst)
        self._paths = {n: [p[:] for p in self._default_paths[n]]
                       for n in pure_dst}
        self._dist = {n: self._default_dist[n]
                      for n in pure_dst}
        # Compute the Fibbed paths
        for n in fibbed_dst:
            (self._paths[n],
             self._dist[n]) = self.__fibbed_spt_for_src(graph, n)

    @staticmethod
    def __default_spt_for_src(g, source):
        # Adapted from single_source_dijkstra in networkx
        dist = {}  # dictionary of final distances
        paths = {source: [[source]]}  # dictionary of list of paths
        seen = {source: 0}
        fringe = []
        c = count()  # We want to skip comparing node labels
        heapq.heappush(fringe, (0, next(c), source))
        while fringe:
            (d, _, v) = heapq.heappop(fringe)
            if v in dist:
                continue  # already searched this node.
            dist[v] = d
            for w, edgedata in g[v].iteritems():
                if g.is_fake_route(v, w):
                    # Deal with fake edges at a later stage
                    continue
                vw_dist = d + edgedata.get(METRIC, 1)
                seen_w = seen.get(w, sys.maxint)
                if vw_dist < dist.get(w, 0):
                    raise ValueError('Contradictory paths found: '
                                     'negative metric?')
                elif vw_dist < seen_w:  # vw is better than the old path
                    seen[w] = vw_dist
                    heapq.heappush(fringe, (vw_dist, next(c), w))
                    paths[w] = list(extend_paths_list(paths[v], w))
                elif vw_dist == seen_w:  # vw is ECMP
                    paths[w].extend(extend_paths_list(paths[v], w))
                # else w is already pushed in the fringe and will pop later
        return paths, dist

    @staticmethod
    def __fibbed_spt_for_src(g, source):
        """Compute the actual used paths due to Fibbing.
        ! the router to which a fake edge is attached does not use it"""

        return None, None

    @staticmethod
    def _get(d, u, v=None):
        return d[u][v] if v else d[u]

    def fibbed_path(self, u, v=None):
        """Return the path, as seen by the routers, between u and v,
        or a dictionary of all shortest-paths starting at u if v is None"""
        return self._get(self._paths, u, v)

    def fibbed_cost(self, u, v=None):
        """Return the cost of the fibbed path between u and v,
        or a dict of cost of all shortest-paths starting at u"""
        return self._get(self._dist, u, v)

    def default_path(self, u, v=None):
        """Return the paths of the pure IGP shortest path if Fibbing was not in
        use on the current network, between u an v or a dict of paths if v is
        None"""
        try:
            return self._get(self._default_paths, u, v)
        except KeyError as e:
            log.debug('%s had no path to %s (lookup key: %s)', u, v, e)
            return []

    def default_cost(self, u, v=None):
        """Return the cost of the pure IGP shortest path if Fibbing was not in
        use on the current network, between u and v or a dict of cost if v
        is None"""
        try:
            return self._get(self._default_dist, u, v)
        except KeyError as e:
            log.debug('%s had no path to %s (lookup key: %s)', u, v, e)
            return sys.maxint

    def __repr__(self):
        return '\n'.join('%s -> %s: %s' % (src, dst, p)
                         for src, d in self._default_paths.iteritems()
                         for dst, paths in d.iteritems()
                         for p in paths)
