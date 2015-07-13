# -*- coding: utf-8 -*-
"""
Shortest path algorithms for weighed graphs.
"""
__author__ = """\n""".join(['Aric Hagberg <hagberg@lanl.gov>',
                            'Loïc Séguin-C. <loicseguin@gmail.com>'])
# Copyright (C) 2004-2010 by
#    Aric Hagberg <hagberg@lanl.gov>
#    Dan Schult <dschult@colgate.edu>
#    Pieter Swart <swart@lanl.gov>
#    All rights reserved.
#    BSD license.

import heapq
import networkx as nx


def dijkstra_path(G, source, target, weight='weight'):
    """Returns the shortest path from source to target in a weighted graph G.

    Parameters
    ----------
    G : NetworkX graph

    source : node
       Starting node

    target : node
       Ending node

    weight: string, optional
       Edge data key corresponding to the edge weight

    Returns
    -------
    path : list
       List of nodes in a shortest path.

    Examples
    --------
    >>> G=nx.path_graph(5)
    >>> print(nx.dijkstra_path(G,0,4))
    [0, 1, 2, 3, 4]

    Notes
    ------
    Uses a bidirectional version of Dijkstra's algorithm.
    Edge weight attributes must be numerical.

    See Also
    --------
    bidirectional_dijkstra()
    """
    #    (length,path)=bidirectional_dijkstra(G,source,target) # faster, needs test
    #     return path
    (length, path) = single_source_dijkstra(G, source, weight=weight)
    try:
        return path[target]
    except KeyError:
        raise nx.NetworkXError("node %s not reachable from %s" % (source, target))


def single_source_dijkstra_ecmp_paths(G, source, weight='weight'):
    """Compute shortest path between source and all other reachable nodes for a weighted graph.

    Parameters
    ----------
    G : NetworkX graph

    source : node
       Starting node for path.

    weight: string, optional
       Edge data key corresponding to the edge weight

    Returns
    -------
    paths : dictionary
       Dictionary of shortest path lengths keyed by target.

    Examples
    --------
    >>> G=nx.path_graph(5)
    >>> path=nx.single_source_dijkstra_path(G,0)
    >>> path[4]
    [0, 1, 2, 3, 4]

    Notes
    -----
    Edge weight attributes must be numerical.

    See Also
    --------
    single_source_dijkstra()

    """
    (length, path) = single_source_dijkstra(G, source, weight=weight)
    return path


def single_source_dijkstra(G, source, target=None, cutoff=None, weight='weight'):
    """Compute shortest paths and lengths in a weighted graph G.

    Uses Dijkstra's algorithm for shortest paths.

    Parameters
    ----------
    G : NetworkX graph

    source : node label
       Starting node for path

    target : node label, optional
       Ending node for path

    cutoff : integer or float, optional
       Depth to stop the search. Only paths of length <= cutoff are returned.

    Returns
    -------
    distance,path : dictionaries
       Returns a tuple of two dictionaries keyed by node.
       The first dictionary stores distance from the source.
       The second stores the path from the source to that node.


    Examples
    --------
    >>> G=nx.path_graph(5)
    >>> length,path=nx.single_source_dijkstra(G,0)
    >>> print(length[4])
    4
    >>> print(length)
    {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}
    >>> path[4]
    [0, 1, 2, 3, 4]

    Notes
    ---------
    Distances are calculated as sums of weighted edges traversed.
    Edges must hold numerical values for Graph and DiGraphs.

    Based on the Python cookbook recipe (119466) at
    http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/119466

    This algorithm is not guaranteed to work if edge weights
    are negative or are floating point numbers
    (overflows and roundoff errors can cause problems).

    See Also
    --------
    single_source_dijkstra_path()
    single_source_dijkstra_path_length()

    """
    if source == target: return (0, [source])
    dist = {}  # dictionary of final distances
    paths = {source: [source]}  # dictionary of paths
    seen = {source: 0}
    fringe = []  # use heapq with (distance,label) tuples
    heapq.heappush(fringe, (0, source))
    while fringe:
        (d, v) = heapq.heappop(fringe)
        if v in dist: continue  # already searched this node.
        dist[v] = d
        if v == target: break
        if G.is_multigraph():
            edata = []
            for w, keydata in list(G[v].items()):
                minweight = min((dd.get(weight, 1)
                                 for k, dd in keydata.items()))
                edata.append((w, {weight: minweight}))
        else:
            edata = iter(G[v].items())

        for w, edgedata in edata:
            vw_dist = dist[v] + edgedata.get(weight, 1)
            if cutoff is not None:
                if vw_dist > cutoff:
                    continue
            if w in dist:
                if vw_dist < dist[w]:
                    raise ValueError("Contradictory paths found: negative weights?")
            elif w not in seen or vw_dist < seen[w]:
                seen[w] = vw_dist
                heapq.heappush(fringe, (vw_dist, w))
                paths[w] = ['%s %s' % (p, w) for p in paths[v]]
            elif vw_dist == seen[w]:
                paths[w].extend(['%s %s' % (p, w) for p in paths[v]])
    return dist, paths


def all_pairs_dijkstra_ecmp_path(G, weight='weight'):
    """ Compute shortest paths between all nodes in a weighted graph.

    Parameters
    ----------
    G : NetworkX graph

    weight: string, optional
       Edge data key corresponding to the edge weight

    Returns
    -------
    distance : dictionary
       Dictionary, keyed by source and target, of shortest paths.

    Examples
    --------
    >>> G=nx.path_graph(5)
    >>> path=nx.all_pairs_dijkstra_path(G)
    >>> print(path[0][4])
    [0, 1, 2, 3, 4]

    See Also
    --------
    floyd_warshall()

    """
    paths = {}
    for n in G:
        paths[n] = single_source_dijkstra_ecmp_paths(G, n, weight=weight)
    return paths
