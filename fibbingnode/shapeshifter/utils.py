import heapq
import sys
import functools
import collections
from fibbingnode import log as log
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
        input_topo.add_edge(node, destination, weight=cost)
        dag.add_edge(node, destination)
    return destination


def all_shortest_paths(g, weight='weight'):
    """Return all shortest paths for all pairs of node in the graph
    :type g: DiGraph"""
    return {n: single_source_all_sp(g, n, weight=weight) for n in g}


def single_source_all_sp(g, source, weight='weight'):
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
            vw_dist = d + edgedata.get(weight, 1)
            seen_w = seen.get(w, sys.maxint)
            if vw_dist < dist.get(w, 0):
                raise ValueError('Contradictory paths found: '
                                 'negative weights?')
            elif vw_dist < seen_w:  # vw is better than the old path
                seen[w] = vw_dist
                heapq.heappush(fringe, (vw_dist, w))
                paths[w] = list(extend_paths_list(paths[v], w))
            elif vw_dist == seen_w:  # vw is ECMP
                paths[w].extend(extend_paths_list(paths[v], w))
    return paths, dist


def extend_paths_list(paths, n):
    """Return and iterator on a new set of paths,
    built by copying the original paths
    and appending a new node at the end of it"""
    for p in paths:
        x = p[:]
        x.append(n)
        yield x


def dag_paths_from_leaves(dag, target):
    paths = []
    for leaf, _ in filter(lambda x: x[1] == 0, dag.in_degree_iter()):
        paths.extend(nx.all_simple_paths(dag, leaf, target))
    return paths


class MaxHeap(object):
    def __init__(self, initial_elem=()):
        self.pq = map(_ReverseCompare, initial_elem)
        heapq.heapify(self.pq)

    def push(self, item):
        heapq.heappush(self.pq, _ReverseCompare(item))

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
