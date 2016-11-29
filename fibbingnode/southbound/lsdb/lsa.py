"""This modules defines the methods to extract LSAs from Quagga instances log
lines, as well the effect of these various LSAs on the network graph"""
from abc import abstractmethod
import functools

from ipaddress import ip_interface, ip_address

from fibbingnode import log

# Keys that are used by Quagga/ospfd/ospf_dump.c
FWD_ADDR = 'fwd_addr'
LINK_DATA = 'link_data'
LINKID = 'link_id'
LINK_TYPE = 'link_type'
LSAGE = "age"
LSA_SEQNUM = 'seq_num'
LSA_TYPE = 'lsa_type'
MASK = 'link_mask'
METRIC = 'link_metric'
METRICTYPE = 'link_metrictype'
OPAQUE = 'opaque_data'
RID = 'rid'

SEP_GROUP = ' '
SEP_INTRA_FIELD = ':'
SEP_INTER_FIELD = ';'

# Reference constant
MAX_LS_AGE = 3600  # one hour


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
        :param graph: A IGPGraph of the network
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
        #  We don't want stub links on the graph
        return []


class VirtualLink(Link):
    TYPE = '4'

    def __init__(self, *args, **kwargs):
        log.debug('Ignoring virtual links')
        super(VirtualLink, self).__init__()

    def endpoints(self, lsdb):
        return []


class LSAHeader(object):
    def __init__(self, prop_dict):
        self.routerid = prop_dict[RID]
        self.linkid = prop_dict[LINKID]
        self.lsa_type = prop_dict[LSA_TYPE]
        self.mask = prop_dict.get(MASK, None)  # Can be unset for some LSA
        self.age = int(prop_dict[LSAGE])
        self.lsa_seqnum = int(prop_dict[LSA_SEQNUM])


class LSA(object):
    TYPE = '0'

    def __init__(self, hdr):
        self.seqnum = hdr.lsa_seqnum
        self.age = hdr.age

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
                return subcls(lsa_header, lsa_prop)
        log.debug('Couldn''t parse the LSA type %s [%s]',
                  lsa_header.lsa_type,
                  lsa_prop)
        return UnusedLSA(lsa_header)

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


class UnusedLSA(LSA):
    def key(self):
        return None

    def apply(self, graph, lsdb):
        pass


class RouterLSA(LSA):
    TYPE = '1'

    def __init__(self, hdr, lsa_prop):
        super(RouterLSA, self).__init__(hdr)
        self.links = [Link.parse(part) for part in lsa_prop]
        self.routerid = hdr.routerid

    def key(self):
        return self.routerid

    def apply(self, graph, lsdb):
        graph.add_router(self.routerid)
        for link in self.links:
            # If the endpoints is not yet in the graph, its properties
            # will be set by later calls to add_xxx as inserting nodes
            # update their properties
            for endpoint in link.endpoints(lsdb):
                graph.add_edge(self.routerid,
                               endpoint,
                               metric=link.metric,
                               src_address=link.address)

    def contract_graph(self, graph, private_ips):
        ips = [link.address for link in self.links
               if link.address != self.routerid]
        ips.extend(private_ips)
        graph.contract(self.routerid, ips)

    def __str__(self):
        return '[R]<%s: %s>' % (self.routerid,
                                ', '.join([str(link) for link in self.links]))


class NetworkLSA(LSA):
    TYPE = '2'

    def __init__(self, hdr, lsa_prop):
        super(NetworkLSA, self).__init__(hdr)
        self.mask = hdr.mask
        self.dr_ip = hdr.linkid
        self.attached_routers = [part[RID] for part in lsa_prop]

    def key(self):
        return self.dr_ip

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

    def __init__(self, hdr, lsa_prop):
        super(ASExtLSA, self).__init__(hdr)
        self.routerid = hdr.routerid
        self.address = hdr.linkid
        self.mask = hdr.mask
        self.routes = [ASExtRoute(part[METRIC], part[FWD_ADDR])
                       for part in lsa_prop]
        self.interface = ip_interface('%s/%s' % (self.address, self.mask))

    @property
    def prefix(self):
        return self.interface.with_prefixlen

    def key(self):
        return self.routerid, self.prefix

    def apply(self, graph, lsdb):
        for route in self.routes:
            fwd_addr = self.resolve_fwd_addr(route.fwd_addr)
            if ip_address(self.routerid) in lsdb.BASE_NET:
                try:
                    targets = lsdb.private_addresses.targets_for(fwd_addr)
                    method = functools.partial(graph.add_local_route,
                                               targets=targets)
                except KeyError:
                    method = graph.add_fake_route
            else:
                method = graph.add_route
            method(fwd_addr, self.prefix, metric=route.metric)

    def resolve_fwd_addr(self, fwd_addr):
        return self.routerid if fwd_addr == '0.0.0.0' else fwd_addr

    def __str__(self):
        return '[E]<%s: %s>' % \
               (self.prefix,
                ', '.join(('(%s, %s)' % (self.resolve_fwd_addr(route.fwd_addr),
                                         route.metric)
                           for route in self.routes)))


def is_newer_seqnum(a, b):
    """
    As of OSPFv2, sequence numbers should simply be treated as signed
    integers ranging from the oldest sequence number possible 0x80000001
    (-N+1 in decimal) to the highest 0x7FFFFFFF (N-1 in decimal).
    """
    return a > b


def is_expired_lsa(lsa):
    """Return whether the LSA is too old to be considered valid"""
    return lsa.age >= MAX_LS_AGE


def _extract_lsa_properties(lsa_part):
    d = {}
    for prop in lsa_part.split(SEP_INTER_FIELD):
        if not prop:
            continue
        key, val = prop.split(SEP_INTRA_FIELD)
        d[key] = val
    return d


def parse_lsa(lsa_info):
    """Builds an lsa from the extracted lsa info"""
    lsa_parts = [_extract_lsa_properties(part)
                 for part in lsa_info.split(SEP_GROUP) if part]
    return LSA.parse(LSAHeader(lsa_parts.pop(0)), lsa_parts)
