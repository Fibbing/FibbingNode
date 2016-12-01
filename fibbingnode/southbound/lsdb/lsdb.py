from Queue import Queue, Empty
from collections import defaultdict
from itertools import chain
import json
from ConfigParser import DEFAULTSECT
from operator import methodcaller

from ipaddress import ip_address, ip_network

from fibbingnode import log, CFG
from fibbingnode.southbound.interface import ShapeshifterProxy
from fibbingnode.misc.sjmp import ProxyCloner
from fibbingnode.misc.igp_graph import IGPGraph
from fibbingnode.misc.utils import is_container, start_daemon_thread

from .lsa import (RouterLSA, NetworkLSA, ASExtLSA, is_newer_seqnum,
                  is_expired_lsa, parse_lsa)


SEP_ACTION = '|'

ADD = 'ADD'
REM = 'REM'
BEGIN = 'BEGIN'
COMMIT = 'COMMIT'


class LSDB(object):

    def __init__(self):
        self.BASE_NET = ip_network(CFG.get(DEFAULTSECT, 'base_net'))
        self.private_addresses = PrivateAddressStore(CFG.get(DEFAULTSECT,
                                                             'private_ips'))
        self.last_line = ''
        self.leader_watchdog = None
        self.transaction = False
        self.uncommitted_changes = 0
        self.graph = IGPGraph()
        self._lsdb = {NetworkLSA.TYPE: {},
                      RouterLSA.TYPE: {},
                      ASExtLSA.TYPE: {}}
        self.controllers = defaultdict(list)  # controller nr : ip_list
        self.listener = {}
        self.keep_running = True
        self.queue = Queue()
        self.processing_thread = start_daemon_thread(
                target=self.process_lsa, name='lsa processing thread')

    @property
    def routers(self):
        return self._lsdb[RouterLSA.TYPE]

    @property
    def networks(self):
        return self._lsdb[NetworkLSA.TYPE]

    @property
    def ext_networks(self):
        return self._lsdb[ASExtLSA.TYPE]

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
        return self._lsdb.get(lsa.TYPE, None)

    def register_change_listener(self, listener):
        try:
            del self.listener[listener]
            log.info('Shapeshifter disconnected.')
        except KeyError:
            log.info('Shapeshifter connected.')
            l = ProxyCloner(ShapeshifterProxy, listener)
            self.listener[listener] = l
            l.bootstrap_graph(graph=[(u, v, d)
                                     for u, v, d in self.graph.export_edges()
                                     ],
                              node_properties={n: data for n, data in
                                               self.graph.nodes_iter(data=True)
                                               })

    def commit_change(self, line):
        # Check that this is not a duplicate of a previous update ...
        if self.last_line == line or not line:
            return
        self.queue.put(line)

    def forwarding_address_of(self, src, dst):
        """
        Return the forwarding address for a src, dst pair.
        If src is specified, return the private 'link-local' address of
        the src-dst link, otherwise return a 'public' IP belonging to dst
        :param src: the source node of the link towards the FA, possibly null
        :param dst: the node owning the forwarding address
        :return: forwarding address (str)
                or None if no compatible address was found
        """
        # If we have a src address, we want the set of private IPs
        # Otherwise we want any IP of dst
        if src:
            try:
                return self.graph[src][dst]['dst_address']
            except KeyError as e:
                log.error("Couldn't resolve local forwarding of %s-%s, missing"
                          " key %s", src, dst, e)
        else:
            try:
                data = filter(lambda v: v is not None,
                              (self.graph[dst][succ].get('src_address', None)
                               for succ in self.graph.successors_iter(dst)))
                if data:
                    return min(data)
                log.error("Cannot use %s as nexthop as it has no physical "
                          "link to other routers!", dst)
            except KeyError:
                log.error("Couldn't find nexthop %s when resolving global "
                          "forwarding address", dst)
        return None

    def remove_lsa(self, lsa):
        lsdb = self.lsdb(lsa)
        try:
            del lsdb[lsa.key()]
        except (KeyError, TypeError):  # LSA not found, lsdb is None
            pass

    def add_lsa(self, lsa):
        lsdb = self.lsdb(lsa)
        try:
            lsdb[lsa.key()] = lsa
        except TypeError:  # LSDB is None
            pass

    def get_current_seq_number(self, lsa):
        try:
            return self.lsdb(lsa)[lsa.key()].seqnum
        except (KeyError, TypeError):  # LSA not found, LSDB is None
            return None

    def is_old_seqnum(self, lsa):
        """Return whether the lsa is older than the copy in the lsdb is any"""
        c_seqnum = self.get_current_seq_number(lsa)
        new_seqnum = lsa.seqnum
        return (c_seqnum and  # LSA already present in the LSDB
                not is_newer_seqnum(new_seqnum, c_seqnum) and
                # We allow duplicate as they are used to flush LSAs
                new_seqnum != c_seqnum)

    def handle_lsa_line(self, line):
        """We received a line describing an lsa, handle it"""
        action, lsa_info = line.split(SEP_ACTION)
        if action == BEGIN:
            self.start_transaction()
        elif action == COMMIT:
            self.reset_transaction()
        else:  # ADD/REM LSA messages
            lsa = parse_lsa(lsa_info)
            log.debug('Parsed %s: %s [%d]', action, lsa, lsa.seqnum)
            # Sanity checks
            if self.is_old_seqnum(lsa):
                log.debug("OLD seqnum for LSA, ignoring it...")
                action = None

            # Perform the update if it is still applicable
            if action == REM:
                self.remove_lsa(lsa)
                self.uncommitted_changes += 1
            elif action == ADD:
                self.add_lsa(lsa)
                self.uncommitted_changes += 1

    def process_lsa(self):
        """Parse new LSAs, and update the graph if needed"""
        while self.keep_running:
            try:
                line = self.queue.get(timeout=5)
                self.queue.task_done()
                if not line:
                    continue
                self.handle_lsa_line(line)
            except Empty:
                self.reset_transaction()
            if (self.queue.empty() and  # Try to empty the queue before update
                    not self.transaction and self.uncommitted_changes):
                self.commit()

    def reset_transaction(self):
        """Reset the transaction"""
        self.transaction = False

    def start_transaction(self):
        """Record a new LSA transaction"""
        self.transaction = True

    def commit(self):
        """Updates have been made on the LSDB, update the graph"""
        # Update graph accordingly
        new_graph = self.build_graph()
        # Compute graph difference and update it
        self.update_graph(new_graph)
        self.uncommitted_changes = 0

    def __str__(self):
        strs = [str(lsa) for lsa in chain(self.routers.values(),
                                          self.networks.values(),
                                          self.ext_networks.values())]
        strs.insert(0, '* LSDB Content [%d]:' % len(strs))
        return '\n'.join(strs)

    def build_graph(self):
        self.controllers.clear()
        new_graph = IGPGraph()
        # Rebuild the graph from the LSDB
        for lsa in chain(self.routers.itervalues(),
                         self.networks.itervalues(),
                         self.ext_networks.itervalues()):

            if is_expired_lsa(lsa):
                log.debug("LSA %s is too old (%d) ignoring it!",
                          lsa, lsa.age)
            else:
                lsa.apply(new_graph, self)
        # Contract all IPs to their respective router-id
        for rlsa in self.routers.itervalues():
            rlsa.contract_graph(new_graph,
                                self.private_addresses
                                .addresses_of(rlsa.routerid))
        # Figure out the controllers layout
        controller_prefix = CFG.getint(DEFAULTSECT, 'controller_prefixlen')
        # Group by controller and log them
        for ip in new_graph.nodes_iter():
            try:
                addr = ip_address(ip)
            except ValueError:
                continue  # Have a prefix
            if addr in self.BASE_NET:
                """1. Compute address diff to remove base_net
                   2. Right shift to remove host bits
                   3. Mask with controller mask"""
                cid = (((int(addr) - int(self.BASE_NET.network_address)) >>
                        self.BASE_NET.max_prefixlen - controller_prefix) &
                       ((1 << controller_prefix) - 1))
                self.controllers[cid].append(ip)
        # Contract them on the graph
        for id, ips in self.controllers.iteritems():
            cname = 'C_%s' % id
            new_graph.add_controller(cname)
            new_graph.contract(cname, ips)
        # Remove generated self loops
        new_graph.remove_edges_from(new_graph.selfloop_edges())
        self.apply_secondary_addresses(new_graph)
        return new_graph

    def update_graph(self, new_graph):
        self.leader_watchdog.check_leader(self.get_leader())
        added_edges = new_graph.difference(self.graph)
        removed_edges = self.graph.difference(new_graph)
        node_prop_diff = {n: data
                          for n, data in new_graph.nodes_iter(data=True)
                          if n not in self.graph or
                          (data.viewitems() - self.graph.node[n].viewitems())}
        # Propagate differences
        if added_edges or removed_edges or node_prop_diff:
            log.debug('Pushing changes')
            for u, v in added_edges:
                self.for_all_listeners('add_edge', u, v,
                                       new_graph.export_edge_data(u, v))
            for u, v in removed_edges:
                self.for_all_listeners('remove_edge', u, v)
            if node_prop_diff:
                self.for_all_listeners('update_node_properties',
                                       **node_prop_diff)
            if CFG.getboolean(DEFAULTSECT, 'draw_graph'):
                new_graph.draw(CFG.get(DEFAULTSECT, 'graph_loc'))
            self.graph = new_graph
            log.info('LSA update yielded +%d -%d edges changes, '
                      '%d node property changes', len(added_edges),
                      len(removed_edges), len(node_prop_diff))
            self.for_all_listeners('commit')

    def for_all_listeners(self, funcname, *args, **kwargs):
        """Apply funcname to all listeners"""
        f = methodcaller(funcname, *args, **kwargs)
        map(f, self.listener.itervalues())

    def apply_secondary_addresses(self, graph):
        for src, dst in graph.router_links:
            try:
                graph[src][dst]['dst_address'] = self.private_addresses\
                                                .addresses_of(dst, src)
            except KeyError:
                log.debug('%(src)-%(dst)s does not yet exists on the graph'
                          ', ignoring private addresses.', locals())
                pass


class PrivateAddressStore(object):
    """A wrapper to serve as database to help cope with the private addresses
    madness"""

    def __init__(self, filename):
        (self._address_bindings,
         self._bdomains) = self.__read_private_ips(filename)

    def __read_private_ips(self, filename):
        router_private_address = defaultdict(dict)
        ip_to_bd = defaultdict(list)
        try:
            with open(filename, 'r') as f:
                private_address_binding = json.load(f)
                for subnets in private_address_binding.itervalues():
                    # Log router id in broadcast domain
                    sub = subnets.keys()
                    for rid, ip in subnets.iteritems():
                        # Enable single private address as string
                        if not is_container(ip):
                            ip = [ip]
                        # Log private addresses adjacencies
                        other = sub[:]
                        other.remove(rid)
                        for s in other:
                            router_private_address[rid][s] = ip
                        for i in ip:
                            # Register the broadcast domain for each ip
                            ip_to_bd[i] = other
        except ValueError as e:
            log.error('Incorrect private IP addresses binding file')
            log.error(str(e))
            ip_to_bd.clear()
            router_private_address.clear()
        except IOError as e:
            log.warning('Cannot read private address file')
            ip_to_bd.clear()
            router_private_address.clear()
        return router_private_address, ip_to_bd

    def addresses_of(self, rid, f=None):
        """Return the list of private ip addresses for router id if f is None,
        else the list of forwarding addresses from f to rid"""
        try:
            return ([i for l in self._address_bindings[rid].itervalues()
                     for i in l]
                    if not f
                    else self._address_bindings[rid][f])
        except KeyError:
            log.debug('No private address for %s from %s', rid, f)

    def targets_for(self, ip):
        """Return the list of router ids able to reach the given private ip"""
        try:
            return self._bdomains[ip]
        except KeyError:
            raise ValueError('No such private IP %s' % ip)

    def __repr__(self):
        return 'bindings: %s\nbdomains: %s' %\
               (self._address_bindings, self._bdomains)
