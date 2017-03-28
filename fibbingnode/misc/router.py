import os
import subprocess
import time
from contextlib import closing
from threading import Lock, Timer
from mako import exceptions
from mako.template import Template

import fibbingnode
from fibbingnode.misc.utils import read_pid, del_file, ConfigDict

log = fibbingnode.log
BIN = fibbingnode.BIN

OSPF_CFG_TEMPLATE = fibbingnode.get_template_path('ospf.mako')
ZEBRA_CFG_TEMPLATE = fibbingnode.get_template_path('zebra.mako')

ZEBRA_EXEC = os.path.join(BIN, 'sbin/zebra')
OSPFD_EXEC = os.path.join(BIN, 'sbin/ospfd')

OSPFD_PORT = 2604
OSPFD_PASSWORD = 'zebra'


class QuaggaRouter(object):
    """
    A wrapper around Quagga to start and configure an OSPF router
    """
    ID = 0

    def __init__(self,
                 name=None,
                 ospf_priority=1,
                 working_dir='.'):
        """
        :param name: The router hostname, used for the temp files
        :param ospf_priority: The priority to apply to the interfaces for the
                                DR elections.
        :param working_dir: The directory where all temp files should go. Must
                            be rw for quagga/quagga!
        """
        if not name:
            name = 'r%d' % QuaggaRouter.ID
            QuaggaRouter.ID += 1
        self.id = name
        self.ospf_priority = ospf_priority
        self.working_dir = working_dir
        self.zebra_pid = self._temp_path('zebra', 'pid')
        self.zebra_api = self._temp_path('zserv', 'api')
        self.ospfd_pid = self._temp_path('ospf', 'pid')
        self.ospf_cfg = self._temp_path('ospf', 'conf')
        self.zebra_cfg = self._temp_path('zebra', 'conf')
        self.vtysh = VTYSH('localhost', OSPFD_PORT, node=self)

    def _temp_path(self, name, ext):
        return '%s/%s_%s.%s' % (self.working_dir, name, self.id, ext)

    def delete(self):
        """
        Delete this node and its associate resources
        """
        self.call('sysctl', '-w', 'net.ipv4.ip_forward=0')
        self.call('sysctl', '-w', 'net.ipv4.icmp_errors_use_inbound_ifaddr=0')
        # Stop ospfd
        pid = read_pid(self.ospfd_pid)
        if pid:
            log.debug('Killing ospfd')
            self.call('kill', '-9', pid)
        del_file(self.ospf_cfg)
        del_file(self.ospfd_pid)
        # Stop zebra
        pid = read_pid(self.zebra_pid)
        if pid:
            log.debug('Killing zebra')
            self.call('kill', '-9', pid)
        del_file(self.zebra_cfg)
        del_file(self.zebra_pid)
        del_file(self.zebra_api)

    def start(self, *extra_args):
        """
        Startup this router processes
        """
        # Create a configuration node for this router
        cfg_node = self.get_config_node()
        # Generate ospf/zebra conf
        self.create_ospf_conf(cfg_node)
        self.create_zebra_conf(cfg_node)
        # Enable ipv4 forwarding
        self.call('sysctl', '-w', 'net.ipv4.ip_forward=1')
        self.call('sysctl', '-w', 'net.ipv4.icmp_errors_use_inbound_ifaddr=1')
        # Start zebra/ospf
        self.call(ZEBRA_EXEC, '-f', self.zebra_cfg, '-i', self.zebra_pid,
                  '-z', self.zebra_api, '-d', '-k')
        time.sleep(.5)  # Required to let zebra create its API socket ...
        self.call(OSPFD_EXEC, '-f', self.ospf_cfg, '-i', self.ospfd_pid,
                  '-z', self.zebra_api, '-d', *extra_args)

    def get_config_node(self):
        return RouterConfigDict(self)

    def create_zebra_conf(self, confignode):
        self.render(ZEBRA_CFG_TEMPLATE, self.zebra_cfg, node=confignode)

    def create_ospf_conf(self, confignode):
        self.render(OSPF_CFG_TEMPLATE, self.ospf_cfg, node=confignode)

    @staticmethod
    def call(*args, **kwargs):
        return subprocess.call(args, **kwargs)

    @staticmethod
    def pipe(*args, **kwargs):
        return subprocess.Popen(args,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                **kwargs)

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
        # We don't want the expiration timer to mess with us
        with self.lock:
            # Do we have a session already open?
            if not self.session:
                # create one otherwise
                self._open()
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


class RouterConfigDict(ConfigDict):
    def __init__(self, router, debug_ospf=(), debug_zebra=(), *args, **kwargs):
        super(RouterConfigDict, self).__init__(*args, **kwargs)
        self.hostname = router.name
        self.password = OSPFD_PASSWORD
        self.redistribute = ConfigDict()
        self.ospf = self.build_ospf(router)
        self.zebra = self.build_zebra(router)
        self.ospf.logfile = '/tmp/ospfd_%s.log' % router.name
        self.ospf.debug = debug_ospf
        self.zebra.logfile = '/tmp/zebra_%s.log' % router.name
        self.zebra.debug = debug_zebra

    def build_ospf(self, router, cfg=None):
        if not cfg:
            cfg = ConfigDict()
        if not cfg.redistribute:
            cfg.redistribute = ConfigDict()
        if not cfg.interfaces:
            cfg.interfaces = []
        if not cfg.networks:
            cfg.networks = []
        if not cfg.passive_interfaces:
            cfg.passive_interfaces = []
        return cfg

    def build_zebra(self, router, cfg=None):
        if not cfg:
            cfg = ConfigDict()
        if not cfg.routemaps:
            cfg.routemaps = []
        if not cfg.static_routes:
            cfg.static_routes = []
        if not cfg.prefixlists:
            cfg.prefixlists = []
        return cfg
