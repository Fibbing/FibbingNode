"""
Base interfaces for the communication between the fibbing node itself and
the algorithmic part.
Each proxy class exposes the methods available to the other side
of the socket, e.g. via a call to an SJMPClient instance execute method.
See tests/sjmptest.py for examples.
"""
from abc import abstractmethod, ABCMeta
import fibbingnode


class FakeNodeProxy(object):
    """The interface that a southbound controller implements"""

    __metaclass__ = ABCMeta

    @abstractmethod
    def add(self, points):
        """
        Add a fibbing route
        :param points: a list of 4-tuple (source, fwd, metric, prefix)
                * source: The link source from which the forwarding address is
                            defined, can be None
                * fwd: The forwarding address to use, either the loopback of
                        that node if source is null, or the address
                        of the interface on that node of the link source--fwd
                * metric: the metric associated with the route. If the metric
                          is < 0, the controller will install a locally
                          visible lie using abs(metric) to choose which private
                          IP to use.
                * prefix: the network prefix corresponding to this route
            source and fwd are OSPF router id.
        """

    @abstractmethod
    def remove(self, points):
        """
        Remove (parts of) a fibbing route
        :param points: a list of 3-tuple (source, fwd, prefix)
                * source: The link source from which the forwarding address is
                            defined, can be None
                * fwd: The forwarding address to use, either the loopback of
                        that node if source is null, or the address
                        of the interface on that node of the link source--fwd
                * prefix: the network prefix corresponding to this route
        """

    @staticmethod
    def exit():
        """Kill the Southbound controller"""
        fibbingnode.EXIT.set()


class ShapeshifterProxy(object):
    """The interface that a Northbound controller application must implement"""

    __metaclass__ = ABCMeta

    @abstractmethod
    def add_edge(self, source, destination, properties={'metric': 1}):
        """
        Add a new directed edge to the network graph
        :param source: The source node for that edge
                        (possibly a new node altogether)
        :param destination: The destination node for that edge
        :param properties: The properties of that edge,
                             e.g. metric for SPT computations
        """

    @abstractmethod
    def remove_edge(self, source, destination):
        """
        Remove a directed edge from the network graph
        :param source: The source node of the edge
        :param destination: The destination of the edge
        """

    @abstractmethod
    def update_node_properties(self, **properties):
        """
        Update the properties of nodes in the graph
        :param properties: a set of key-values where the keys are the node
                            names and the values their property set.
        """

    @abstractmethod
    def commit(self):
        """Signals that all updates have been pushed and that no more
        add_edge/remove_edge calls will happen"""

    @abstractmethod
    def bootstrap_graph(self, graph, node_properties):
        """
        Instantiate an initial graph
        :param graph: a list of edges for that graph (router-id and/or
                        prefixes) + associated properties
        :param node_properties: a dict of node: properties
        """
