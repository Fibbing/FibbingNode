from Queue import Queue, Empty
from abc import abstractmethod
from collections import defaultdict
from itertools import chain
from threading import Thread
import json
from networkx import DiGraph, draw_networkx_labels
import os
from fibbingnode import log, CFG
from interface import ShapeshifterProxy
from ipaddress import ip_interface, ip_address, ip_network
from ConfigParser import DEFAULTSECT
from fibbingnode.misc.sjmp import ProxyCloner


ADD = 'ADD'
FWD_ADDR = 'fwd_addr'
LINK_DATA = 'link_data'
LINKID = 'link_id'
LINK_TYPE = 'link_type'
LSA_TYPE = 'lsa_type'
MASK = 'link_mask'
METRIC = 'link_metric'
METRICTYPE = 'link_metrictype'
OPAQUE = 'opaque_data'
REM = 'REM'
RID = 'rid'
BEGIN = 'BEGIN'
COMMIT = 'COMMIT'

SEP_ACTION = '|'
SEP_GROUP = ' '
SEP_INTRA_FIELD = ':'
SEP_INTER_FIELD = ';'
# Unused because we currently implicitly rely on it by doing
# for line in ... in parse_lsdblog()
SEP_LSA = '\n'


def graph_diff(a, b):
    diff = []
    for u, v in a.edges_iter():
        try:
            d = b[u][v]
        except:
            diff.append((u, v))
    return diff


def draw_graph(graph):
    try:
        layout = spring_layout(graph)
        metrics = {
            (src, dst): data['metric']
            for src, dst, data in graph.edges_iter(data=True)
        }
        draw_networkx_edge_labels(graph, layout, edge_labels=metrics)
        draw(graph, layout, node_size=20)
        draw_networkx_labels(graph, layout, labels={n: n for n in graph})
        output = CFG.get(DEFAULTSECT, 'graph_loc')
        if os.path.exists(output):
            os.unlink(output)
        plt.savefig(output)
        plt.close()
        log.debug('Graph of %d nodes saved in %s', len(graph), output)
    except:
        pass

# The draw_graph call will be remapped to 'nothing' if matplotlib (aka extra
# packages) is not available
try:
    from networkx import spring_layout, draw_networkx_edge_labels, draw
    import matplotlib.pyplot as plt
except ImportError as e:
    log.warning('Missing packages to draw the network, disabling the fonction')
    draw_graph = lambda x: True


def contract_graph(graph, nodes, into):
    """
    Contract the graph
    :param graph: The graph to contract
    :param nodes: The set of nodes to contract into one
    :param into: The (new) node that should be the contraction
    """
    edges = graph.edges(nodes, data=True)
    graph.add_edges_from(map(lambda x: (into, x[1], x[2]), edges))
    graph.remove_nodes_from(nodes)


class Link(object):
    TYPE = '0'

    def __init__(self, address=None, metric=0):
        self.address = address
        self.metric = metric

    @staticmethod
    def parse(lsa_prop):
        for subcls in Link.__subclasses__():
            if subcls.TYPE == lsa_prop[LINK_TYPE]:
                return subcls(lsa_prop[LINKID],
                              lsa_prop[LINK_DATA],
                              lsa_prop[METRIC])
        log.error('Couldn''t parse the link %s', lsa_prop)
        return None

    @abstractmethod
    def endpoints(self, lsdb):
        """
        Give the list of endpoint IPS/router-id for that link
        :param graph: A DiGraph of the network
        :param lsdb: an LSDB instance in order to resolve
                    e.g. routerid or interface IPs
        :return: list of IPs or router-id
        """

    def __str__(self):
        return '%s:%s' % (self.address, self.metric)


class P2PLink(Link):
    TYPE = '1'

    def __init__(self, linkid, link_data, metric):
        super(P2PLink, self).__init__(address=link_data, metric=metric)
        self.other_routerid = linkid

    def endpoints(self, lsdb):
        return [self.other_routerid]


class TransitLink(Link):
    TYPE = '2'

    def __init__(self, linkid, link_data, metric):
        super(TransitLink, self).__init__(address=link_data, metric=metric)
        self.dr_ip = linkid

    def endpoints(self, lsdb):
        other_routers = []
        netdb = lsdb.lsdb(NetworkLSA)
        try:
            netlsa = netdb[self.dr_ip]
        except KeyError:
            log.debug('Cannot resolve network lsa for %s yet', self.dr_ip)
        else:
            other_routers.extend(netlsa.attached_routers)
        return other_routers


class StubLink(Link):
    TYPE = '3'

    def __init__(self, linkid, link_data, metric):
        super(StubLink, self).__init__(address=linkid, metric=metric)
        self.mask = link_data

    @property
    def prefix(self):
        return ip_interface('%s/%s' % (self.address, self.mask)).with_prefixlen

    def endpoints(self, lsdb):
        # return [self.prefix]
        #  We don't want stub links on the graph
        log.debug('Ignoring stub link to %s', self.prefix)
        return []


class VirtualLink(Link):
    TYPE = '4'

    def __init__(self, *args, **kwargs):
        log.debug('Ignoring virtual links')
        super(VirtualLink, self).__init__()

    def endpoints(self, lsdb):
        return []


class LSAHeader(object):
    def __init__(self, routerid, linkid, lsa_type, mask):
        self.routerid = routerid
        self.linkid = linkid
        self.lsa_type = lsa_type
        self.mask = mask

    @staticmethod
    def parse(prop_dict):
        try:
            mask = prop_dict[MASK]
        except KeyError:
            mask = None
        return LSAHeader(prop_dict[RID],
                         prop_dict[LINKID],
                         prop_dict[LSA_TYPE],
                         mask)


class LSA(object):
    TYPE = '0'

    @staticmethod
    def parse(lsa_header, lsa_prop):
        """
        Create a new LSA based on the property dicts given
        :param lsa_header: an LSAHeader instance
        :param lsa_prop: a property dictionary
        :return: a new LSA instance
        """
        for subcls in LSA.__subclasses__():
            if subcls.TYPE == lsa_header.lsa_type:
                return subcls.parse(lsa_header, lsa_prop)
        log.error('Couldn''t parse the LSA type %S [%s]',
                  lsa_header.lsa_type,
                  lsa_prop)
        return None

    @abstractmethod
    def key(self):
        """
        What is the unique key identifying this LSA among
        all other LSA of that type
        :return: key
        """

    @abstractmethod
    def apply(self, graph, lsdb):
        """
        Apply this lsa on the graph, thus adding links/node as needed
        :param graph: The graph to manipulate
        :param lsdb: The LSDB instance that can be used
                     to retrieve information from other LSAs
        """

    @staticmethod
    def push_update_on_remove():
        """
        Whether the removal of this LSA implies a topological change
        :return: bool
        """
        return False


class RouterLSA(LSA):
    TYPE = '1'

    def __init__(self, routerid, links):
        self.links = links
        self.routerid = routerid

    def key(self):
        return self.routerid

    @staticmethod
    def parse(lsa_header, lsa_prop):
        return RouterLSA(lsa_header.routerid,
                         [Link.parse(part) for part in lsa_prop])

    def apply(self, graph, lsdb):
        for link in self.links:
            for endpoint in link.endpoints(lsdb):
                graph.add_edge(self.routerid,
                               endpoint,
                               metric=link.metric,
                               src_address=link.address)

    def contract_graph(self, graph, private_ips):
        ips = [link.address for link in self.links
               if not link.address == self.routerid]
        ips.extend(private_ips)
        contract_graph(graph, ips, self.routerid)

    def __str__(self):
        return '[R]<%s: %s>' % (self.routerid,
                                ', '.join([str(link) for link in self.links]))


class NetworkLSA(LSA):
    TYPE = '2'

    def __init__(self, dr_ip, mask, attached_routers):
        self.mask = mask
        self.dr_ip = dr_ip
        self.attached_routers = attached_routers

    def key(self):
        return self.dr_ip

    @staticmethod
    def parse(lsa_header, lsa_prop):
        return NetworkLSA(dr_ip=lsa_header.linkid, mask=lsa_header.mask,
                          attached_routers=[part[RID] for part in lsa_prop])

    def apply(self, graph, lsdb):
        # Unused as the RouterLSA should have done the resolution for us
        pass

    def __str__(self):
        return '[N]<%s: %s>' % (self.dr_ip, ', '.join(self.attached_routers))


class ASExtRoute(object):
    def __init__(self, metric, fwd_addr):
        self.metric = metric
        self.fwd_addr = fwd_addr


class ASExtLSA(LSA):
    TYPE = '5'

    def __init__(self, routerid, address, mask, routes):
        self.routerid = routerid
        self.address = address
        self.mask = mask
        self.routes = routes
        self.interface = ip_interface('%s/%s' % (self.address, self.mask))

    @property
    def prefix(self):
        return self.interface.with_prefixlen

    def key(self):
        return self.routerid, self.prefix

    @staticmethod
    def parse(lsa_header, lsa_prop):
        return ASExtLSA(lsa_header.routerid,
                        address=lsa_header.linkid,
                        mask=lsa_header.mask,
                        routes=[ASExtRoute(part[METRIC], part[FWD_ADDR])
                                for part in lsa_prop])

    def apply(self, graph, lsdb):
        # TODO figure out if we actually need to filter these out or not
        # if ip_address(self.routerid) in lsdb.exclude_net and \
        #    CFG.getboolean(DEFAULTSECT, 'exclude_fake_lsa'):
        #     log.debug('Skipping AS-external Fake LSA %s via %s',
        #               self.address, [self.resolve_fwd_addr(r.fwd_addr)
        #                              for r in self.routes])
        #     return
        for route in self.routes:
            graph.add_edge(self.resolve_fwd_addr(route.fwd_addr), self.prefix,
                           metric=route.metric)

    def resolve_fwd_addr(self, fwd_addr):
        return self.routerid if fwd_addr == '0.0.0.0' else fwd_addr

    def __str__(self):
        return '[E]<%s: %s>' % \
               (self.prefix,
                ', '.join(['(%s, %s)' % (self.resolve_fwd_addr(route.fwd_addr),
                                         route.metric)
                           for route in self.routes]))

    @staticmethod
    def push_update_on_remove():
        return True


class LSDB(object):
    def __init__(self):
        self.private_address_network = ip_network(CFG.get(DEFAULTSECT,
                                                  'private_net'))
        try:
            with open(CFG.get(DEFAULTSECT, 'private_ips'), 'r') as f:
                self.private_address_binding = json.load(f)
                self.router_private_address = {}
                for subnets in self.private_address_binding.itervalues():
                    for rid, ip in subnets.iteritems():
                        try:
                            iplist = self.router_private_address[rid]
                        except KeyError:
                            iplist = self.router_private_address[rid] = []
                        # Enable single private address as string
                        if isinstance(ip, string):
                            ip = [ip]
                        iplist.extend(ip)
        except Exception as e:
            log.warning('Incorrect private IP addresses binding file')
            log.warning(str(e))
            self.private_address_binding = {}
            self.router_private_address = {}
        self.last_line = ''
        self.leader_watchdog = None
        self.transaction = None
        self.graph = DiGraph()
        self.routers = {}  # router-id : lsa
        self.networks = {}  # DR IP : lsa
        self.ext_networks = {}  # (router-id, dest) : lsa
        self.controllers = defaultdict(list)  # controller nr : ip_list
        self.listener = {}
        self.keep_running = True
        self.queue = Queue()
        self.processing_thread = Thread(target=self.process_lsa,
                                        name="lsa_processing_thread")
        self.processing_thread.setDaemon(True)
        self.processing_thread.start()

    def set_leader_watchdog(self, wd):
        self.leader_watchdog = wd

    def get_leader(self):
        return min(self.controllers.iterkeys()) if self.controllers else None

    def stop(self):
        for l in self.listener.values():
            l.session.stop()
        self.keep_running = False
        self.queue.put('')

    def lsdb(self, lsa):
        if lsa.TYPE == RouterLSA.TYPE:
            return self.routers
        elif lsa.TYPE == NetworkLSA.TYPE:
            return self.networks
        elif lsa.TYPE == ASExtLSA.TYPE:
            return self.ext_networks

    def register_change_listener(self, listener):
        try:
            del self.listener[listener]
            log.info('Shapeshifter disconnected.')
        except KeyError:
            log.info('Shapeshifter connected.')
            l = ProxyCloner(ShapeshifterProxy, listener)
            self.listener[listener] = l
            l.boostrap_graph(graph=[(u, v, d.get('metric', -1))
                                    for u, v, d in self.graph.edges(data=True)])

    @staticmethod
    def extract_lsa_properties(lsa_part):
        d = {}
        for prop in lsa_part.split(SEP_INTER_FIELD):
            if not prop:
                continue
            key, val = prop.split(SEP_INTRA_FIELD)
            d[key] = val
        return d

    def commit_change(self, line):
        # Check that this is not a duplicate of a previous update ...
        if self.last_line == line:
            return
        self.queue.put(line)

    def forwarding_address_of(self, src, dst):
        """
        Return the forwarding address for a src, dst pair. If src is specified, return
        the private 'link-local' address of the src-dst link, otherwise return a 'public'
        IP belonging to dst
        :param src: the source node of the link towards the FA, possibly null
        :param dst: the node owning the forwarding address
        :return: forwarding address (str) or None if no compatible address was found
        """
        try:
            return self.graph[src][dst]['dst_address'] if src \
                else self.graph[dst][self.graph.neighbors(dst)[0]]['src_address']
        except KeyError:
            log.debug('%s-%s not found in graph', src, dst)
            return None

    def remove_lsa(self, lsa):
        lsdb = self.lsdb(lsa)
        try:
            del lsdb[lsa.key()]
        except KeyError:
            pass

    def add_lsa(self, lsa):
        lsdb = self.lsdb(lsa)
        lsdb[lsa.key()] = lsa

    def process_lsa(self):
        while self.keep_running:
            commit = False
            try:
                line = self.queue.get(timeout=5)
                if not line:
                    self.queue.task_done()
                    continue
                # Start parsing the LSA log
                action, lsa_info = line.split(SEP_ACTION)
                if action == BEGIN:
                    self.transaction = Transaction()
                elif action == COMMIT:
                    if self.transaction:
                        self.transaction.commit(self)
                        self.transaction = None
                        commit = True
                else:
                    lsa_parts = [self.extract_lsa_properties(part)
                                 for part in lsa_info.split(SEP_GROUP) if part]
                    lsa = LSA.parse(LSAHeader.parse(lsa_parts.pop(0)),
                                    lsa_parts)
                    log.debug('Parsed %s: %s', action, lsa)
                    if action == REM:
                        if not self.transaction:
                            self.remove_lsa(lsa)
                        else:
                            self.transaction.remove_lsa(lsa)
                    elif action == ADD:
                        if not self.transaction:
                            self.add_lsa(lsa)
                        else:
                            self.transaction.add_lsa(lsa)
                    if lsa.push_update_on_remove() or not action == REM:
                        commit = True
                self.queue.task_done()
            except Empty:
                if self.transaction:
                    log.debug('Splitting transaction due to timeout')
                    self.transaction.commit(self)
                    self.transaction = Transaction()
                    commit = True
            if commit:
                # Update graph accordingly
                new_graph = self.build_graph()
                # Compute graph difference and update it
                self.update_graph(new_graph)

    def __str__(self):
        strs = [str(lsa) for lsa in chain(self.routers.values(),
                                          self.networks.values(),
                                          self.ext_networks.values())]
        strs.insert(0, '* LSDB Content [%d]:' % len(strs))
        return '\n'.join(strs)

    def build_graph(self):
        new_graph = DiGraph()
        # Rebuild the graph from the LSDB
        for lsa in chain(self.routers.values(),
                         self.networks.values(),
                         self.ext_networks.values()):
            lsa.apply(new_graph, self)
        # Contract all IPs to their respective router-id
        for lsa in self.routers.values():
            lsa.contract_graph(new_graph, self.router_private_address.get(
                lsa.routerid, []))
        # Figure out the controllers layout
        base_net = ip_network(CFG.get(DEFAULTSECT, 'base_net'))
        controller_prefix = CFG.getint(DEFAULTSECT, 'controller_prefixlen')
        # Group by controller and log them
        for ip in new_graph.nodes_iter():
            try:
                addr = ip_address(ip)
            except ValueError:
                continue  # Have a prefix
            if addr in base_net:
                """1. Compute address diff to remove base_net
                   2. Right shift to remove host bits
                   3. Mask with controller mask
                """
                id = (((int(addr) - int(base_net.network_address)) >>
                       base_net.max_prefixlen - controller_prefix) &
                      ((1 << controller_prefix) - 1))
                self.controllers[id].append(ip)
        # Contract them on the graph
        for id, ips in self.controllers.iteritems():
            contract_graph(new_graph, ips, 'C_%s' % id)
        # Remove generated self loops
        new_graph.remove_edges_from(new_graph.selfloop_edges())
        self.apply_secondary_addresses(new_graph)
        return new_graph

    def update_graph(self, new_graph):
        self.leader_watchdog.check_leader(self.get_leader())
        added_edges = graph_diff(new_graph, self.graph)
        removed_edges = graph_diff(self.graph, new_graph)
        # Propagate differences
        if len(added_edges) > 0 or len(removed_edges) > 0:
            log.debug('Pushing changes')
            for u, v in added_edges:
                self.listener_add_edge(u, v, new_graph[u][v]['metric'])
            for u, v in removed_edges:
                self.listener_remove_edge(u, v)
            if CFG.getboolean(DEFAULTSECT, 'draw_graph'):
                draw_graph(new_graph)
            self.graph = new_graph
            log.info('LSA update yielded +%d -%d edges changes' %
                     (len(added_edges), len(removed_edges)))

    def listener_add_edge(self, *args):
        for l in self.listener.values():
            l.add_edge(*args)

    def listener_remove_edge(self, *args):
        for l in self.listener.values():
            l.remove_edge(*args)

    def apply_secondary_addresses(self, graph):
        for subnet in self.private_address_binding.itervalues():
            for dst, ip in subnet.iteritems():
                for src in subnet.iterkeys():
                    if src == dst:
                        continue
                    try:
                        graph[src][dst]['dst_address'] = ip
                    except KeyError:
                        pass


class Transaction(object):
    def __init__(self):
        log.debug('Initiating new LSA transaction')
        self.add = []
        self.rem = []

    def add_lsa(self, lsa):
        self.add.append(lsa)

    def remove_lsa(self, lsa):
        self.rem.append(lsa)

    def commit(self, lsdb):
        log.debug('Committing LSA transaction')
        for lsa in self.rem:
            lsdb.remove_lsa(lsa)
        for lsa in self.add:
            lsdb.add_lsa(lsa)
