import heapq
import sys
import functools
import collections
from fibbingnode import log as log
from fibbingnode.misc.utils import extend_paths_list, is_container
import networkx as nx


def find_sink(dag):
    """Find all sinks in a given DAG
    :type dag: DiGraph
    :return: list of nodes whose out degree is 0 aka sinks"""
    for n, deg in dag.out_degree_iter():
        if deg == 0:
            yield n


def add_separate_destination_to_sinks(destination, input_topo, dag, cost=1):
    if destination in input_topo:
        destination = "Dest_" + destination
    for node in find_sink(dag):
        log.debug("Connecting %s to %s with cost %d",
                  destination, node, cost)
        input_topo.add_edge(node, destination, metric=cost)
        dag.add_edge(node, destination)
    return destination


def all_shortest_paths(g, metric='metric'):
    """Return all shortest paths for all pairs of node in the graph
    :type g: DiGraph"""
    return {n: single_source_all_sp(g, n, metric=metric) for n in g}


def single_source_all_sp(g, source, metric='metric'):
    """Return the list of all shortest paths originatig from src,
    and their associated costs.

    :type g: DiGraph
    :return: {dst: [[x y z], [a b c], ...]}, {dst: cost}

    Adapted from single_source_dijkstra in networkx.
    # Copyright (C) 2004-2010 by
    #    Aric Hagberg <hagberg@lanl.gov>
    #    Dan Schult <dschult@colgate.edu>
    #    Pieter Swart <swart@lanl.gov>
    #    All rights reserved.
    #    BSD license.
    """
    dist = {}  # dictionary of final distances
    paths = {source: [[source]]}  # dictionary of list of paths
    seen = {source: 0}
    fringe = []  # use heapq with (distance,label) tuples
    heapq.heappush(fringe, (0, source))
    while fringe:
        (d, v) = heapq.heappop(fringe)
        if v in dist:
            continue  # already searched this node.
        dist[v] = d
        for w, edgedata in g[v].items():
            vw_dist = d + edgedata.get(metric, 1)
            seen_w = seen.get(w, sys.maxint)
            if vw_dist < dist.get(w, 0):
                raise ValueError('Contradictory paths found: '
                                 'negative "%s"?' % metric)
            elif vw_dist < seen_w:  # vw is better than the old path
                seen[w] = vw_dist
                heapq.heappush(fringe, (vw_dist, w))
                paths[w] = list(extend_paths_list(paths[v], w))
            elif vw_dist == seen_w:  # vw is ECMP
                paths[w].extend(extend_paths_list(paths[v], w))
    return paths, dist


def dag_paths_from_leaves(dag, target):
    paths = []
    for leaf, _ in filter(lambda x: x[1] == 0, dag.in_degree_iter()):
        paths.extend(nx.all_simple_paths(dag, leaf, target))
    return paths


class MaxHeap(object):
    def __init__(self, initial_elem=()):
        self.pq = map(_ReverseCompare, initial_elem)
        heapq.heapify(self.pq)

    def push(self, *item):
        for i in item:
            heapq.heappush(self.pq, _ReverseCompare(i))

    def pop(self):
        return heapq.heappop(self.pq).obj

    def is_empty(self):
        return len(self.pq) == 0

    def __repr__(self):
        return ', '.join(str(item) for item in self.pq)


# http://stackoverflow.com/questions/12681772
# CC BY-SA 3.0
@functools.total_ordering
class _ReverseCompare(object):
    def __init__(self, obj):
        self.obj = obj

    def __eq__(self, other):
        return self.obj == other.obj

    def __le__(self, other):
        return self.obj >= other.obj

    def __repr__(self):
        return repr(self.obj)


"""A tuple whose fields can be accessed by their names representing a LSA"""
LSA = collections.namedtuple('LSA', 'node nh cost dest')


def LocalLie(prefix, edge_src, edge_dst, ipindex=1):
    return LSA(edge_src, edge_dst, -ipindex, prefix)


def GlobalLie(dest, cost, nh, node=None):
    return LSA(node, nh, cost, dest)


class ExtendedLSA(object):
    def __init__(self, node, nh, routes):
        self.node = node
        self.nh = nh
        self.routes = routes

    def __repr__(self):
        return 'EXTLSA(node=%s, nh=%s, routes=%s)' % (self.node,
                                                      self.nh,
                                                      self.routes)


ExtLSARoute = collections.namedtuple('ExtLSARoute', 'dest cost')


def _add_fake_route(g, n, d, **kw):
    """Wrapper around IGPGraph.add_fake_route in case we have a normal
    DiGraph"""
    try:
        g.add_fake_route(n, d, **kw)
    except AttributeError:
        g.add_edge(n, d, **kw)


def _is_fake_dest(g, d):
    """Test whether d is reachable through at least one non-fake link"""
    try:
        for p in g.predecessors_iter(d):
            if g.is_real_route(p, d):
                return False
    except AttributeError:
        return False
    return True


def add_dest_to_graph(dest, graph, edges_src=None, spt=None,
                      node_data_gen=None, **kw):
    """Add dest to the graph, possibly updating the shortest paths object

    :param dest: The destination node, will be set as a prefix
    :param graph: The graph to which dest must be added if not present
    :param edges_src: The source of edges to add in order to add dest,
                    if None, defaults to the sinks in the graph,
                    otherwise it is a function returning a list of edges
                    and taking dest as argument
    :param spt: The ShortestPath object to update to account for the new node
                if applicable
    :param node_data_gen: A function that will generate data for the new node
                         if needed
    :param kw: Extra parameters for the edges if any"""
    added = None
    if dest in graph and not _is_fake_dest(graph, dest):
        # Unless dest was only announced through fake links, we don't touch it
        log.debug('%s is already in the graph', dest)
        in_dag = True
    else:
        in_dag = False
        if not edges_src:
            added = []
            sinks = find_sink(graph)
            if not sinks:
                log.info('No sinks found in the graph!')
            for node in sinks:
                if node == dest:
                    continue
                log.info('Connected %s to %s in the graph', node, dest)
                _add_fake_route(graph, node, dest, **kw)
                added.append(node)
        else:
            added = edges_src(dest)
            log.info('Connecting edges sources %s to the graph to %s',
                     dest, added)
            for s in added:
                _add_fake_route(graph, s, dest, **kw)
            graph.add_edges_from((s, dest) for s in added, **kw)
    ndata = {} if not node_data_gen else node_data_gen()
    # Only update the dest node if explicitely requested
    if node_data_gen or not in_dag:
        graph.add_node(dest, prefix=True, **ndata)
    if added and spt:
        log.info('Updating SPT')
        _update_paths_towards(spt, graph, dest, added)


def _update_paths_towards(spt, g, dest, added_edges):
    """Update the shortest paths by adding some new edges towards a
    destination
    ! The destination should not be in the already existing SPT!
    :param g: The graph
    :param dest: The added destination
    :param added_edges: The source of the added edges"""
    __update_default_paths(spt, g, dest, added_edges)
    __update_fibbed_paths(spt, g, dest, added_edges)


def __update_default_paths(spt, g, dest, added):
    spt._default_paths[dest] = {dest: [[dest]]}
    spt._default_dist[dest] = {dest: 0}
    for n in g.routers:
        paths = []
        cost = sys.maxint
        for s in added:
            try:
                c = spt.default_cost(n, s) + g.metric(s, dest)
            except KeyError:  # No path from n to s, skip
                continue
            p = spt.default_path(n, s)
            if c < cost:  # new spt towards s is n-p-s
                paths = list(extend_paths_list(p, dest))
                cost = c
            elif c == cost:  # ecmp
                paths.extend(extend_paths_list(p, dest))
        if paths:
            log.debug('Adding paths (cost: %s): %s', cost, paths)
            spt._default_paths[n][dest] = paths
            spt._default_dist[n][dest] = cost


def __update_fibbed_paths(spt, g, dest, added):
    pass


def complete_dag(dag, graph, dest, paths, skip=()):
    """Complete the DAG with all SPT from the graph towards
    destinations that are not yet in the dag

    :param dag: the dag to complete
    :param graph: the graph to explore
    :param dest: the destination to consider
    :param paths: a ShortestPath object
    :param skip: nodes that must not be considered"""
    for n in filter(lambda r: (r not in dag and r not in skip and
                               graph.successors(r)),
                    graph.routers):
        for p in paths.default_path(n, dest):
            for u, v in zip(p[:-1], p[1:]):
                v_in_dag = v in dag
                dag.add_edge(u, v)
                if v_in_dag:  # we connected u to the new SPT
                    break


def solvable(dag, graph):
    """Check that the given DAG can be embedded in the graph"""
    for u, v in dag.edges_iter():
        try:
            graph[u][v]
        except KeyError:
            log.error('Cannot satisfy the DAG '
                      ' as (%s, %s) is not in the IGP graph',
                      u, v)
            log.error('Available edges: %s', graph.edges())
            log.error('DAG: %s', dag.edges())
            return False
    return True


def DFS(generator, consumer, generate_from=None, *elems):
    """Perform a Depth First Search (DFS).

    :param generator: The function that will generate the next set of
                     element to examinate from the current one
    :param consumer: The function that will consume one element.
                     If it returns a single iterable, feed them to the
                     generator
                     If it returns a 2-tuple (x, y), feed x to the generator
                     and yield y
    :param generate_from: A starting element to feed to the generator
    :param elems: Elements to add in the original set to visit"""
    visited = set()
    to_visit = set(elems)
    if generate_from:
        to_visit |= set(generator(generate_from))
    while to_visit:
        n = to_visit.pop()
        if n in visited:
            continue
        visited.add(n)
        ret = consumer(n)
        try:
            remains, to_yield = ret
            if to_yield:
                yield to_yield
        except TypeError:
            remains = ret
        if remains:
            if not is_container(remains):
                remains = (remains,)
            to_visit |= set(*map(generator, remains))
