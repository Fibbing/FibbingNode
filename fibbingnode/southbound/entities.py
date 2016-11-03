from collections import OrderedDict
import subprocess
import sys
import os

import fibbingnode
from lsdb import LSDB
from fibbingnode.misc.utils import require_cmd, force, ConfigDict
from fibbingnode.misc.router import QuaggaRouter, RouterConfigDict
from namespaces import NetworkNamespace, RootNamespace

log = fibbingnode.log

# Ensures that we have a temp directory to store all configs, ...
RUN = '/run/quagga'

LSDB_LOG_PATH = os.path.join(RUN, 'lsdb.log')

if not os.path.exists(RUN):
    import grp
    import pwd

    os.mkdir(RUN)
    os.chown(RUN, pwd.getpwnam('quagga').pw_uid, grp.getgrnam('quagga').gr_gid)


class Node(object):
    """
    Base network nodes: a dict of ports
    """

    def __init__(self, id, prefix):
        """
        :param id: The identifier for this node
        :param prefix: The namespace prefix
        """
        if not prefix:
            raise Exception('Controller nodes require a prefix!')
        self.id = '%s_%s' % (prefix, id)
        self.next_port = -1
        self.interfaces = OrderedDict()

    def get_next_port(self):
        """
        :return: the next available port number on this node
        """
        self.next_port += 1
        return self.next_port

    def add_port(self, port):
        """
        Associate the given port to this node
        :param port: The Port object to register
        """
        self.interfaces[port] = port

    def del_port(self, port):
        """
        Remove the given port from this device
        :param port: a Port object
        """
        del self.interfaces[port]

    def call(self, *args, **kwargs):
        """
        Execute a command on this node
        """
        return subprocess.call(args, **kwargs)

    def pipe(self, *args, **kwargs):
        """
        Execute a command on this node and return an object that
        has communicate() available for use with stdin/stdout
        """
        return subprocess.Popen(args,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                **kwargs)

    def start(self):
        self.call('ip', 'link', 'set', 'lo', 'up')


class Bridge(Node):
    """
    A Layer-2 hub
    """

    def __init__(self, id='br0', *args, **kwargs):
        require_cmd('brctl',
                    'Look for package bridge-utils in your package manager')
        super(Bridge, self).__init__(id, *args, **kwargs)
        # Check that this bridge id is available
        if self.id in subprocess.check_output(['brctl', 'show']):
            # Otherwise destroy it
            self.delete()
        # Create the bridge
        self.brctl('addbr')
        self.call('ip', 'link', 'set', self.id, 'up')

    def brctl(self, cmd, *args):
        """
        Wrapper around the brctl command
        """
        cmd = ['brctl', cmd, self.id]
        cmd.extend(args)
        log.debug('Bridge command: %s', cmd)
        err = self.call(*cmd)
        if err != 0:
            log.error('%s has failed!', ' '.join(cmd))
            sys.exit(1)

    def add_port(self, port):
        super(Bridge, self).add_port(port)
        log.debug('Adding interface %s to %s', port.id, self.id)
        return self.brctl('addif', port.id)

    def del_port(self, port):
        super(Bridge, self).del_port(port)
        log.debug('Removing interface %s from %s', port.id, self.id)
        return self.brctl('delif', port.id)

    def delete(self):
        """
        Disable and delete this bridge
        """
        self.call('ip', 'link', 'set', self.id, 'down')
        self.brctl('delbr')


class FibbingRouter(QuaggaRouter):
    def __init__(self, node, *args, **kwargs):
        super(FibbingRouter, self).__init__(name=node.id,
                                            working_dir=RUN,
                                            *args, **kwargs)
        self.fibbingnode = node

    def call(self, *args, **kwargs):
        return self.fibbingnode.call(*args, **kwargs)

    def pipe(self, *args, **kwargs):
        return self.fibbingnode.pipe(*args, **kwargs)

    def get_config_node(self):
        return FibbingConfigNode(self.fibbingnode)


class Router(Node):
    """
    A fibbing router
    """
    ID = 0

    def __init__(self, ospf_priority=1, id=None, namespaced=True,
                 *args, **kwargs):
        """
        :param id: Router id, set automatically if None
        :param namespaced: Run the router in a new network namespace?
        """
        # Create new router id if needed
        if not id:
            Router.ID += 1
            id = 'r%d' % Router.ID
        super(Router, self).__init__(id, *args, **kwargs)
        # Basic routers have lowest priority
        self.ospf_priority = ospf_priority
        self.name = self.id
        self.ns = NetworkNamespace() if namespaced else RootNamespace()
        self.router = FibbingRouter(self)

    def delete(self):
        self.router.delete()
        self.ns.delete()

    def add_port(self, port):
        super(Router, self).add_port(port)
        # Move the port into our network namespace
        return self.ns.capture_port(port)

    def __str__(self):
        """
        :return: nsname: port | port | port
        """
        return '%s: %s' % (self.ns.name,
                           ' | '.join([str(port)
                                      for port in self.interfaces.values()]))

    def start(self, *extra_args):
        """
        Startup this router processes
        """
        super(Router, self).start()
        self.router.start(*extra_args)

    def call(self, *args, **kwargs):
        # Redirect the call to happen inside this namespace
        return self.ns.call(*args, **kwargs)

    def pipe(self, *args, **kwargs):
        return self.ns.pipe(*args, **kwargs)

    def _fibbing(self, *args, **kwargs):
        cmd = ['ip', 'ospf', 'fibbing']
        if kwargs.get('no', False):
            cmd.insert(0, 'no')
        cmd.extend(args)
        self.router.vtysh(*cmd, configure=True)

    def advertize(self, prefix, via, metric, ttl):
        self._fibbing(str(prefix), 'via', str(via), 'cost', str(metric),
                      'ttl', str(ttl))

    def retract(self, prefix):
        self._fibbing(prefix, no=True)

    def vtysh(self, *args, **kwargs):
        log.debug('vtysh call: %s', ' '.join(args))
        return self.router.vtysh(*args, **kwargs)


class RootRouter(Router):
    """
    The fibbing router that will interact with the real ones in the network
    """

    def __init__(self, **kwargs):
        super(RootRouter, self).__init__(ospf_priority=2, **kwargs)
        # Register the physical ports apart
        self.physical_links = []
        self.lsdb_log_file = None
        self.lsdb_log_file_name = '%s_%s' % (LSDB_LOG_PATH, self.id)
        if os.path.exists(self.lsdb_log_file_name):
            os.unlink(self.lsdb_log_file_name)
        os.mkfifo(self.lsdb_log_file_name)
        self.lsdb = LSDB()

    def add_physical_link(self, link):
        """
        Add physical ports to its assigned ports
        :param link: A PhysicalLink to 'the outside world'
        """
        self.physical_links.append(link)

    def __str__(self):
        top = ' | '.join([str(port) for port in self.physical_links])
        return '%s\n%s\n%s%s\n%s' %\
               (top,
                '-' * len(top),
                ' ' * ((len(top) - len(self.id)) / 2),
                self.id,
                ' | '.join([str(port)
                            for port in self.interfaces.values()
                            if port not in self.physical_links]))

    def start(self, *extra_args):
        super(RootRouter, self).start('--log_lsdb',
                                      self.lsdb_log_file_name,
                                      *extra_args)

    def delete(self):
        self.lsdb.stop()
        for p in self.physical_links:
            p.move_to_root()
        super(RootRouter, self).delete()
        if self.lsdb_log_file:
            force(self.lsdb_log_file.close)
        force(os.unlink, self.lsdb_log_file_name)

    def parse_lsdblog(self):
        def fifo_readline(f):
            buf = ''
            data = True
            while data:
                data = f.read(1)
                buf += data
                if data == '\n':
                    yield buf
                    buf = ''

        self.lsdb_log_file = open(self.lsdb_log_file_name, 'r')
        for line in fifo_readline(self.lsdb_log_file):
            try:
                self.lsdb.commit_change(line[:-1])
            except Exception as e:
                # We do not want to crash the whole node ...
                # rather log the error
                # And stop parsing the LSDB
                log.error('Failed to parse LSDB update %s [%s]', line, str(e))
                log.exception(e)
        log.debug('Stopped updating the LSDB')

    def send_lsdblog_to(self, listener):
        self.lsdb.register_change_listener(listener)

    def get_fwd_address(self, src, dst):
        """Return the list of forwarding address from src to dst"""
        fwd = self.lsdb.forwarding_address_of(src, dst)
        log.debug('fwding address of %s-%s is %s', src, dst, fwd)
        return fwd


class FibbingConfigNode(RouterConfigDict):
    """
    A router configuration node,
    Generates/extracts/formats the information needed by zebra/ospf from
    the router object
    """

    def __init__(self, router):
        """
        Create a configuration node reflecting the router
        :param router: The router object to analyze
        """
        super(FibbingConfigNode, self).__init__(router)
        self.ospf.redistribute.fibbing = True

    def build_ospf(self, router):
        interfaces = []
        networks = []
        for intf in router.interfaces.values():
            intf_dict = ConfigDict(name=intf.id, description=str(intf.link))
            intf_dict.ospf = ConfigDict(
                cost=intf.ospf_cost,
                priority=router.ospf_priority,
                dead_int=intf.ospf_dead_int,
                hello_int=intf.ospf_hello_int
            )
            interfaces.append(intf_dict)
            net_dict = ConfigDict(domain=intf.ip_interface
                                  .network.with_prefixlen,
                                  area=intf.ospf_area)
            networks.append(net_dict)
        return super(FibbingConfigNode,
                     self).build_ospf(router,
                                      ConfigDict(interfaces=interfaces,
                                                 # id is the first interface
                                                 router_id=str(router
                                                               .interfaces
                                                               .values()[0]
                                                               .ip_interface
                                                               .ip),
                                                 networks=networks))
