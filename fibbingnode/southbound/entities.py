from collections import OrderedDict
import subprocess
import sys
import os
from contextlib import closing
from threading import Lock, Timer
from mako import exceptions
from mako.template import Template

import fibbingnode
from lsdb import LSDB
from fibbingnode.misc.utils import require_cmd, force
from namespaces import NetworkNamespace, RootNamespace

log = fibbingnode.log
BIN = fibbingnode.BIN

OSPF_CFG_TEMPLATE = fibbingnode.get_template_path('ospf.mako')
ZEBRA_CFG_TEMPLATE = fibbingnode.get_template_path('zebra.mako')

ZEBRA_EXEC = os.path.join(BIN, 'sbin/zebra')
OSPFD_EXEC = os.path.join(BIN, 'sbin/ospfd')

OSPFD_PORT = 2604
OSPFD_PASSWORD = 'zebra'

# Ensures that we have a temp directory to store all configs, ...
RUN = '/run/quagga'

LSDB_LOG_PATH = os.path.join(RUN, 'lsdb.log')

if not os.path.exists(RUN):
    import grp
    import pwd

    os.mkdir(RUN)
    os.chown(RUN, pwd.getpwnam('quagga').pw_uid, grp.getgrnam('quagga').gr_gid)


def read_pid(n):
    """
    Extract a pid from a file
    :param n: path to a file
    :return: pid as a string
    """
    try:
        with open(n, 'r') as f:
            return str(f.read()).strip(' \n\t')
    except:
        return None


def del_file(f):
    force(os.remove, f)


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
            raise Exception('Namespaced nodes require a prefix!')
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


class VTYSH(object):
    """Proxy class to maintain a telnet session with a quagga daemon"""
    # How long should we keep the session open after inactivity?
    VTYSH_TIMEOUT = 5
    SHELL_INVITE = '>'
    ENABLED = '#'

    def __init__(self, hostname, port, node):
        """
        :param hname: the hostname of the daemon
        :param port: the port number of the daemon
        :param id: the identifier to use for this vtysh in the logs
        """
        self.hname = hostname
        self.port = port
        self.node = node
        self.id = node.id
        self.enabled_invite = '%s%s' % (self.id, self.ENABLED)
        self.shell_invite = '%s%s' % (self.id, self.SHELL_INVITE)
        # We currently don't connect to the daemon
        self.session = None
        # Handle synchronisation with expiration timer
        self.lock = Lock()

    def _open(self):
        self._debug('Opening VTYSH session')
        self.session = self.node.pipe('telnet', self.hname, str(self.port))
        # First Quagga will ask us for the password
        self._read_until('Password:')
        self._enter(OSPFD_PASSWORD)
        self._read_until(self.shell_invite)
        # Enter privileged mode
        self._enter('enable')
        self._read_until(self.enabled_invite)
        # Start up the expiration timer for that session instance
        self._restart_timer()

    def __call__(self, *args, **kwargs):
        """
        Execute a vtysh command on the corresponding daemon
        :param configure: Execute the command in a
                            'configure terminal' 'exit' block
        :param *args: list of command elements
        """
        configure = kwargs.pop('configure', False)
        # Do we have a session already open?
        if not self.session:
            # create one otherwise
            self._open()
        # We don't want the expiration timer to mess with us
        with self.lock:
            # Cancel exp. timer
            self.reset_timer.cancel()
            if configure:
                self._enter('configure terminal')
            # Assemble and execute the command
            cmd_str = ' '.join(args)
            self._enter(cmd_str)
            if configure:
                self._enter('exit')
            out = self._read_until(self.enabled_invite)
            # Now that the session is idle again, restart the exp. timer
            self._restart_timer()
        return out[len(cmd_str) + 2:]

    def _enter(self, cmd):
        self._debug(cmd)
        self.session.stdin.write(cmd + '\n')

    def _restart_timer(self):
        self.reset_timer = Timer(interval=self.VTYSH_TIMEOUT,
                                 function=self._expire)
        self.reset_timer.start()

    def _read_until(self, delimiter):
        """Read and return the ouput of the shell until reaching
        the given delimiter (not included)"""
        # TODO optimize ...
        l = len(delimiter)
        b = self.session.stdout.read(l)
        while b[-l:] != delimiter:
            b += self.session.stdout.read(1)
        return b[:-l]

    def _expire(self):
        # If we don't own the lock this means the timer will be restarted
        if self.lock.acquire(True):
            self._debug('Closing VTYSH session')
            self._enter('exit')
            self.session.terminate()
            self.session = None
            self.lock.release()

    def _debug(self, message):
        log.debug('vtysh[%s]: %s', self.id, message)


class Router(Node):
    """
    A fibbing router
    """
    ID = 0

    def __init__(self, id=None, namespaced=True, *args, **kwargs):
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
        self.ospf_priority = 1
        self.ns = NetworkNamespace() if namespaced else RootNamespace()

        # Generate temp filepaths needed by Quagga
        def path(name, ext):
            return '%s/%s_%s.%s' % (RUN, name, self.id, ext)

        self.zebra_pid = path('zebra', 'pid')
        self.zebra_api = path('zserv', 'api')
        self.ospfd_pid = path('ospf', 'pid')
        self.ospf_cfg = path('ospf', 'conf')
        self.zebra_cfg = path('zebra', 'conf')
        self.vtysh = VTYSH('localhost', OSPFD_PORT, node=self)

    def delete(self):
        """
        Delete this node and its associate resources
        """
        self.ns.call('sysctl', '-w', 'net.ipv4.ip_forward=0')
        # Stop ospfd
        pid = read_pid(self.ospfd_pid)
        if pid:
            log.debug('Killing ospfd')
            self.ns.call('kill', '-9', pid)
        del_file(self.ospf_cfg)
        del_file(self.ospfd_pid)
        # Stop zebra
        pid = read_pid(self.zebra_pid)
        if pid:
            log.debug('Killing zebra')
            self.ns.call('kill', '-9', pid)
        del_file(self.zebra_cfg)
        del_file(self.zebra_pid)
        del_file(self.zebra_api)
        # Delete associated namespace
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
        # Create a configuration node for this router
        cfg_node = _ConfigNode(self)
        # Generate ospf/zebra conf
        self.create_ospf_conf(cfg_node)
        self.create_zebra_conf(cfg_node)
        # Enable ipv4 forwarding
        self.ns.call('sysctl', '-w', 'net.ipv4.ip_forward=1')
        # Start zebra/ospf
        self.ns.call(ZEBRA_EXEC, '-f', self.zebra_cfg, '-i', self.zebra_pid,
                     '-z', self.zebra_api, '-d', '-k')
        self.ns.call(OSPFD_EXEC, '-f', self.ospf_cfg, '-i', self.ospfd_pid,
                     '-z', self.zebra_api, '-d', *extra_args)

    def create_zebra_conf(self, confignode):
        self.render(ZEBRA_CFG_TEMPLATE, self.zebra_cfg, node=confignode)

    def create_ospf_conf(self, confignode):
        self.render(OSPF_CFG_TEMPLATE, self.ospf_cfg, node=confignode)

    def call(self, *args, **kwargs):
        # Redirect the call to happen inside this namespace
        return self.ns.call(*args, **kwargs)

    def pipe(self, *args, **kwargs):
        return self.ns.pipe(*args, **kwargs)

    @staticmethod
    def render(template, dest, **kwargs):
        """
        Render a Mako template passing it optional arguments
        """
        log.debug('Generating %s\n' % dest)
        try:
            text = Template(filename=template).render(**kwargs)
            with closing(open(dest, 'w')) as f:
                f.write(text)
        except:
            # Display template errors in a less cryptic way
            log.error('Couldn''t render a config file (%s)',
                      os.path.basename(template))
            log.error(exceptions.text_error_template().render())

    def _fibbing(self, *args, **kwargs):
        cmd = ['ip', 'ospf', 'fibbing']
        if 'no' in kwargs and kwargs['no']:
            cmd.insert(0, 'no')
        cmd.extend(args)
        self.vtysh(*cmd, configure=True)

    def advertize(self, prefix, via, metric):
        self._fibbing(prefix, 'via', via, 'cost', metric)

    def retract(self, prefix):
        self._fibbing(prefix, no=True)


class RootRouter(Router):
    """
    The fibbing router that will interact with the real ones in the network
    """

    def __init__(self, **kwargs):
        super(RootRouter, self).__init__(**kwargs)
        # ospf prio set to 2 to be the DR of all fibbing routers
        self.ospf_priority = 2
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
        super(RootRouter, self).delete()
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
        fwd = self.lsdb.forwarding_address_of(src, dst)
        log.debug('fwding address of %s-%s is %s', src, dst, fwd)
        return fwd


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
        subprocess.call(['ip', 'link', 'set', self.id, 'down'])
        self.brctl('delbr')


class _ConfigDict(dict):
    """
    A dictionary whose attributes are its keys
    """

    def __init__(self, **kwargs):
        super(_ConfigDict, self).__init__()
        for key, val in kwargs.iteritems():
            self[key] = val

    def __getattr__(self, item):
        # so that self.item == self[item]
        try:
            # But preserve i.e. methods
            return getattr(self, item)
        except:
            return self[item]

    def __setattr__(self, key, value):
        # so that self.key = value <==> self[key] = key
        self[key] = value


class _ConfigNode(_ConfigDict):
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
        super(_ConfigNode, self).__init__()
        self.hostname = router.id
        self.password = OSPFD_PASSWORD
        self.interfaces = {intf.id: _ConfigDict(name=intf.id,
                                                description=str(intf.link))
                           for intf in router.interfaces.values()}
        self.ospf = self.build_ospf(router)

    def build_ospf(self, router):
        interfaces = []
        networks = []
        for intf in router.interfaces.values():
            intf_dict = self.interfaces[intf.id]
            intf_dict.ospf = _ConfigDict(
                cost=intf.ospf_cost,
                priority=router.ospf_priority,
                dead_int=intf.ospf_dead_int,
                hello_int=intf.ospf_hello_int
            )
            interfaces.append(intf_dict)
            net_dict = _ConfigDict(domain=intf.ip_interface
                                   .network.with_prefixlen,
                                   area=intf.ospf_area)
            networks.append(net_dict)
        return _ConfigDict(interfaces=interfaces,
                           # Generate id from from first interface
                           router_id=str(router.interfaces.values()[0]
                                         .ip_interface.ip),
                           networks=networks)
