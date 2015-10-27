"""
Base interfaces for the communication between the fibbing node itself and the algorithmic
part.
Each proxy class exposes the methods available to the other side of the socket, e.g. via a call
to an SJMPClient instance execute method.
See tests/sjmptest.py for examples.
"""
from abc import abstractmethod


class FakeNodeProxy(object):

    @abstractmethod
    def add(self, points):
        """
        Add a fibbing route
        :param points: a list of 4-tuple (source, fwd, metric, prefix)
                * source: The link source from which the forwarding address is defined, can be None
                * fwd: The forwarding address to use, either the loopback of that node if source is null, or the address
                            of the interface on that node of the link source--fwd
                * metric: the metric associated with the route
                * prefix: the network prefix corresponding to this route
        """

    @abstractmethod
    def remove(self, points):
        """
        Remove (parts of) a fibbing route
        :param points: a list of 3-tuple (source, fwd, prefix)
                * source: The link source from which the forwarding address is defined, can be None
                * fwd: The forwarding address to use, either the loopback of that node if source is null, or the address
                            of the interface on that node of the link source--fwd
                * prefix: the network prefix corresponding to this route
        """


class ShapeshifterProxy(object):

    @abstractmethod
    def add_edge(self, source, destination, metric):
        """
        Add a new directed edge to the network graph
        :param source: The source node for that edge (possibly a new node altogether)
        :param destination: The destination node for that edge
        :param metric: The metric of that edge, e.g. for SPT computations
        """

    @abstractmethod
    def remove_edge(self, source, destination):
        """
        Remove a directed edge from the network graph
        :param source: The source node of the edge
        :param destination: The destination of the edge
        """

    @abstractmethod
    def boostrap_graph(self, graph):
        """
        Instantiate an initial graph
        :param graph: a list of edges for that graph (router-id and/or prefixes) + associated metric
        """