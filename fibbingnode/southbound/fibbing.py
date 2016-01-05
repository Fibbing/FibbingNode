from ConfigParser import DEFAULTSECT
from collections import OrderedDict
from itertools import groupby
from operator import itemgetter
import subprocess
from threading import Thread
from fibbingnode import log, CFG
from link import Link, PhysicalLink
from entities import Router, RootRouter, Bridge
from ipaddress import ip_network, ip_interface, ip_address
from fibbingnode.misc.sjmp import SJMPServer
from interface import FakeNodeProxy


def gen_physical_ports(port_list):
    """
    Find all enabled physical interfaces of this
    :param port_list: The list of all physical ports that should be analyzed
    :return: A list of Tuple (interface name, ip address)
            for each active physical interface
    """
    ports = []
    for port_name in port_list:
        try:
            out = subprocess.check_output(['ip', 'a', 'show', port_name])
            for line in out.splitlines():
                if 'inet ' in line:
                    line = line.strip(' \t\n')
                    # inet 130.104.228.87/25 brd 130.104.228.127 \
                    #                                 scope global dynamic eno1
                    port_addr = ip_interface(line.split(' ')[1])
                    log.debug('Added physical port %s@%s',
                              port_name, port_addr)
                    ports.append((port_name, port_addr))
                    break
                    # TODO support multiple IP/interface?
        except subprocess.CalledProcessError as e:
            log.exception(e)
    return ports


class FibbingManager(object):
    def __init__(self, instance_number):
        """
        :param instance_number: the controller instance number
        :param net: the subnet allocated for the fibbing nodes
        """
        self.leader = False
        self.instance = instance_number
        self.name = 'c%s' % instance_number
        self.nodes = {}
        self.bridge = Bridge('br0', self.name)
        self.root = None
        net = ip_network(CFG.get(DEFAULTSECT, 'base_net'))
        controller_prefix = CFG.getint(DEFAULTSECT, 'controller_prefixlen')
        host_prefix = net.max_prefixlen - controller_prefix
        controller_base = (int(net.network_address) +
                           (instance_number << host_prefix))
        controller_net = ip_address(controller_base)
        self.net = ip_network('%s/%s' % (controller_net, controller_prefix))
        self.graph_thread = Thread(target=self.infer_graph,
                                   name="Graph inference thread")
        self.graph_thread.setDaemon(True)
        self.json_proxy = SJMPServer(hostname=CFG.get(DEFAULTSECT,
                                                      'json_hostname'),
                                     port=CFG.getint(DEFAULTSECT,
                                                     'json_port'),
                                     invoke=self.proxy_connected,
                                     target=FakeNodeProxyImplem(self))
        self.json_thread = Thread(target=self.json_proxy.communicate)
        self.json_thread.setDaemon(True)
        # Used to assign unique router-id to each node
        self.next_id = 1
        self.links = []
        # The fibbing routes
        self.routes = {}
        self.route_mappings = {}

    def start(self, phys_ports, nodecount=None):
        """
        Start the fibbing network
        :param nodecount: Pre-allocate nodecount fibbing nodes
        """
        # Create root node
        self.root = self.add_node(id='root', cls=RootRouter, start=False)
        self.root.lsdb.set_leader_watchdog(self)
        del self.nodes[self.root.id]  # The root node should not originate LSA
        self.graph_thread.start()
        self.json_thread.start()
        # And map all physical ports to it
        ports = gen_physical_ports(phys_ports)
        for name, addr in ports:
            link = PhysicalLink(self.root, name, addr)
            self.root.add_physical_link(link)
        self.root.start()
        # Create additional nodes if requested
        if nodecount is None:
            nodecount = CFG.getint(DEFAULTSECT, 'initial_node_count')
        while nodecount > 0:
            self.add_node()
            nodecount -= 1

    def add_node(self, id=None, cls=Router, start=True):
        """
        Add a new fibbing node to the network and start it
        :param id: The name of the new node
        :param cls: The class to use to instantiate it
        :param start: Automatically start the node
        :return: The new node instance
        """
        # Create a node
        n = self.create_node(id, cls)
        # Link it to the bridge
        l = self.link(self.bridge, n)
        # Generate unique ip for its interface that's connected to the bridge
        router_ip = ip_interface('%s/%s' % (self.net[self.next_id],
                                            self.net.prefixlen))
        self.next_id += 1
        l.dst.set_ip(router_ip)
        if start:
            n.start()
        return n

    def create_node(self, id=None, cls=Router):
        """
        Create a new node
        :param id: The name of the new node
        :param cls: The class to use to instantiate it
        """
        n = cls(id=id, prefix=self.name, namespaced=True)
        self.nodes[n.id] = n
        log.info('Created node %s', n.id)
        return n

    def __getitem__(self, item):
        try:
            return self.nodes[item]
        except KeyError as e:
            if item == 'root':
                return self.root
            else:
                raise e

    def link(self, src, dst):
        """
        Create a veth Link between two nodes
        :param src: The source node of the link
        :param dst: The destination node of the link
        """
        log.debug('Linking %s to %s', src.id, dst.id)
        l = Link(src, dst)
        # Register the new link
        self.links.append(l)
        return l

    def print_net(self):
        """
        Log a representation of the fibbing network state
        """
        log.info('----------------------')
        log.info('Network of %s nodes', len(self.nodes))
        log.info('----------------------')
        log.info('')
        r_info = str(self.root)
        for l in r_info.split('\n'):
            log.info(l)
        log.info('|')
        bid_str = '%s --+' % self.bridge.id
        prefix = ' ' * (len(bid_str) - 1)
        log.info(bid_str)
        for n in self.nodes.values():
            if n == self.root:
                continue
            log.info('%s|', prefix)
            log.info('%s+--- %s', prefix, n)

    def print_routes(self):
        """
        Log all fibbing routes that are installed in the network
        """
        log.info('----------------------')
        log.info('%s fibbing routes', len(self.routes))
        log.info('----------------------')
        for route in self.routes.values():
            log.info(route)

    def cleanup(self):
        """
        Cleanup all namespaces/links/...
        """
        self.json_proxy.stop()
        for link in self.links:
            link.delete()
        self.root.delete()
        for node in self.nodes.values():
            node.delete()
        self.bridge.delete()

    def install_route(self, network, points, advertize):
        """
        Install and advertize a fibbing route
        :param network: the network prefix to attract
        :param points: a list of (address, metric) of points
        """
        net = ip_network(network)
        # Retrieve existing route if any
        try:
            route = self.routes[net]
        except KeyError:
            route = FibbingRoute(net, [])
            self.routes[net] = route
            self.route_mappings[net] = set()
        # Get used nodes mapping for this prefix
        mappings = self.route_mappings[net]
        # Increase node count if needed
        size = len(route) + len(points)
        while size > len(self.nodes):
            self.add_node()
        # Get available node list for this prefix
        nodes = [n for n in self.nodes.values() if n not in mappings]
        # Generate attraction points
        attraction_points = [AttractionPoint(addr, metric, nodes.pop())
                             for addr, metric in points if addr]
        # Update used nodes mapping
        for p in attraction_points:
            mappings.add(p.node)
        # Advertize them
        route.append(attraction_points, advertize)

    def remove_route(self, network):
        """
        Remove a route
        :param network: The prefix to remove
        """
        net = ip_network(network)
        try:
            route = self.routes[net]
            self.remove_route_part(net, *[p for p in route])
        except KeyError:
            log.debug('No route for network %s', net)

    def remove_route_part(self, network, advertize, *elems):
        """
        Remove elements of a route
        :param network: The prefix of the route
        :param elems: The list of forwarding address to remove
        """
        log.debug('Removing route for prefix %s, elements: %s', network, elems)
        net = ip_network(network)
        try:
            route = self.routes[net]
            for e in elems:
                node = route.retract(e, advertize)
                if node:
                    self.route_mappings[net].remove(node)
            if len(route) == 0:
                self.route_mappings.pop(net)
                self.routes.pop(net)
        except KeyError:
            log.debug('No route for network %s', network)

    def infer_graph(self):
        self.root.parse_lsdblog()

    def _get_proxy_routes(self, points):
        for prefix, parts in groupby(sorted(points, key=itemgetter(3)),
                                     key=itemgetter(3)):
            route = []
            for p in parts:
                src, dst, cost = p[0], p[1], p[2]
                if cost >= 0:
                    src = None
                fwd_addr = self.root.get_fwd_address(src, dst)
                # Can have multiple private addresses per interface, handle
                # here the selection ...
                if isinstance(fwd_addr, list):
                    try:
                        fwd_addr = fwd_addr[cost]
                    except ValueError:
                        log.warning('Required private forwarding address index'
                                    'is out of bounds. Wanted: %s - Have %s',
                                    abs(cost), len(fwd_addr))
                        fwd_addr = fwd_addr[0]
                    cost = 1
                route.append((fwd_addr, str(cost)))
            yield prefix, route

    def proxy_add(self, points):
        """
        :param points: (source, fwd, cost, prefix)*
        """
        log.info('Shapeshifter added attraction points: %s', points)
        for prefix, route in self._get_proxy_routes(points):
            self.install_route(prefix, route, self.leader)

    def proxy_remove(self, points):
        """
        :param points: (source, fwd, cost, prefix)*
        """
        log.info('Shapeshifter removed attraction points: %s', points)
        for prefix, route in self._get_proxy_routes(points):
            # We don't need the cost
            self.remove_route_part(prefix, self.leader, *(r[0] for r in route))

    def proxy_connected(self, session):
        self.root.send_lsdblog_to(session)

    @property
    def lsdb(self):
        return self.root.lsdb

    def check_leader(self, instance):
        was_leader = self.leader
        self.leader = self.instance == self.lsdb.get_leader()
        if self.leader and not was_leader:  # We are the new leader
            log.info('Elected as leader')
            for route in self.routes.values():
                route.advertize()
        elif was_leader and not self.leader:
            log.info('No longer leader')
            # Let the LSA decay
            # TODO is-it safe ?


class FakeNodeProxyImplem(FakeNodeProxy):
    def __init__(self, mngr):
        self.mngr = mngr

    def add(self, points):
        self.mngr.proxy_add(self._get_point_list(points, 4))

    def remove(self, points):
        self.mngr.proxy_remove(self._get_point_list(points, 4))

    def _get_point_list(self, points, tuple_len):
        if not type(points) == list:
            raise Exception('points must be a list!')
        if not type(points[0]) == list:
            if len(points) == tuple_len:
                return [points]
            else:
                raise Exception('Incomplete parameters, tuples should '
                                'have length of %s' % tuple_len)
        if len(points[0]) == tuple_len:
            return points
        raise Exception('Incomplete parameters, tuples should have '
                        'length of %s' % tuple_len)


class FibbingRoute(object):
    def __init__(self, prefix, attraction_points, advertize=False):
        """
        :param prefix: The network prefix to fake
        :param attraction_points: a list of AttractionPoint
        :return:
        """
        self.prefix = prefix
        self.attraction_points = OrderedDict()
        self.append(attraction_points, advertize)

    def __str__(self):
        return '%s: %s' % (self.prefix.with_prefixlen,
                           ' and '.join([str(p)
                                         for p in self.attraction_points]))

    def __len__(self):
        return len(self.attraction_points)

    def __iter__(self):
        return iter(self.attraction_points)

    def append(self, points, advertize):
        for p in points:
            if advertize:
                p.advertize(self.prefix)
            self.attraction_points[p.address] = p

    def retract(self, address, advertize):
        try:
            point = self.attraction_points.pop(address)
            if advertize:
                point.retract(self.prefix)
            return point.node
        except KeyError:
            log.debug('Unkown attraction point %s for prefix %s',
                      address, self.prefix)
            return None

    def advertize(self):
        for p in self.attraction_points.itervalues():
            p.advertize(self.prefix)


class AttractionPoint(object):
    """
    An attraction point for a fibbing route
    """

    def __init__(self, address, metric, node):
        """
        :param address: The forwarding address to specify
                        for this attraction point
        :param metric: The metric of this attraction point
        :param node: The node advertizing this
        :return:
        """
        try:
            self.address = str(ip_interface(address).ip)
        except ValueError:
            self.address = address
        self.metric = metric
        self.node = node
        self.advertized = False

    def __str__(self):
        return '%s[%s] via %s' % (self.address, self.metric, self.node.id)

    def advertize(self, prefix):
        """
        Advertize this fibbing point
        """
        log.debug('%s advertizes %s via %s',
                  self.node.id, prefix, self.address)
        self.node.advertize(prefix.with_prefixlen,
                            via=self.address, metric=self.metric)
        self.advertized = True

    def retract(self, prefix):
        log.debug('%s retracts %s', self.node.id, prefix)
        self.node.retract(prefix.with_prefixlen)
        self.advertized = False
