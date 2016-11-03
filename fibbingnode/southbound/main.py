from ConfigParser import DEFAULTSECT
from cmd import Cmd
import logging
import sys
import subprocess
import argparse
import datetime
from fibbing import FibbingManager
import fibbingnode
from fibbingnode.misc.utils import dump_threads
import signal

log = fibbingnode.log
CFG = fibbingnode.CFG


class FibbingCLI(Cmd):
    Cmd.prompt = '> '

    def __init__(self, mngr, *args, **kwargs):
        self.fibbing = mngr
        Cmd.__init__(self, *args, **kwargs)

    def do_add_node(self, line=''):
        """Add a new fibbing node"""
        self.fibbing.add_node()

    def do_show_lsdb(self, line=''):
        log.info(self.fibbing.root.lsdb)

    def do_draw_network(self, line):
        """Draw the network as pdf in the given file"""
        self.fibbing.root.lsdb.graph.draw(line)

    def do_print_graph(self, line=''):
        log.info('Current network graph: %s',
                 self.fibbing.root.lsdb.graph.edges(data=True))

    def do_print_net(self, line=''):
        """Print information about the fibbing network"""
        self.fibbing.print_net()

    def do_print_routes(self, line=''):
        """Print information about the fibbing routes"""
        self.fibbing.print_routes()

    def do_exit(self, line=''):
        """Exit the prompt"""
        return True

    def do_cfg(self, line=''):
        part = line.split(' ')
        val = part.pop()
        key = part.pop()
        sect = part.pop() if part else DEFAULTSECT
        CFG.set(sect, key, val)

    def do_call(self, line):
        """Execute a command on a node"""
        items = line.split(' ')
        try:
            node = self.fibbing[items[0]]
            node.call(*items[1:])
        except KeyError:
            log.error('Unknown node %s', items[0])

    def do_add_route(self, line=''):
        """Setup a fibbing route
        add_route network via1 metric1 via2 metric2 ..."""
        items = line.split(' ')
        if len(items) < 3:
            log.error('route only takes at least 3 arguments: '
                      'network via_address metric')
        else:
            points = []
            i = 2
            while i < len(items):
                points.append((items[i-1], items[i]))
                i += 2
            log.critical('Add route request at %s',
                         datetime.datetime.now().strftime('%H.%M.%S.%f'))
            self.fibbing.install_route(items[0], points, True)

    def do_rm_route(self, line):
        """Remove a route or parts of a route"""
        items = line.split(' ')
        if len(items) == 1:
            ans = raw_input('Remove the WHOLE fibbing route for %s ? (y/N)'
                            % line)
            if ans == 'y':
                self.fibbing.remove_route(line)
        else:
            self.fibbing.remove_route_part(items[0], *items[1:])

    def default(self, line):
        """Pass the command to the shell"""
        args = line.split(' ')
        if args[0] in self.fibbing.nodes:
            self.do_call(' '.join(args))
        else:
            try:
                log.info(subprocess.check_output(line, shell=True))
            except Exception as e:
                log.info('Command %s failed', line)
                log.info(e.message)

    def eval(self, line):
        """Interpret the given line ..."""
        self.eval(line)

    def do_ospfd(self, line):
        """Connect to the ospfd daemon of the given node"""
        try:
            self.fibbing[line].call('telnet', 'localhost', '2604')
        except KeyError:
            log.error('Unknown node %s', line)

    def do_vtysh(self, line):
        """Execute a vtysh command on a node"""
        items = line.split(' ')
        try:
            node = self.fibbing[items[0]]
            result = node.vtysh(*items[1:], configure=False)
            log.info(result)
        except KeyError:
            log.error('Unknown node %s', items[0])

    def do_configure(self, line):
        """Execute a vtysh configure command on a node"""
        items = line.split(' ')
        try:
            node = self.fibbing[items[0]]
            result = node.vtysh(*items[1:], configure=True)
            result = result.strip(' \n\t')
            if result:
                log.info(result)
        except KeyError:
            log.error('Unknown node %s', items[0])

    def do_traceroute(self, line, max_ttl=10):
        """
        Perform a simple traceroute between the source and an IP
        :param max_ttl: the maximal ttl to use
        """
        items = line.split(' ')
        try:
            node = self.fibbing[items[0]]
            node.call('traceroute', '-q', '1', '-I',
                      '-m', str(max_ttl), '-w', '.1', items[1])
        except KeyError:
            log.error('Unknown node %s', items[0])
        except ValueError:
            log.error('This command takes 2 arguments: '
                      'source node and destination IP')

    def do_dump(self, line=''):
        dump_threads()


def handle_args():
    parser = argparse.ArgumentParser(description='Starts a fibbing node.')
    parser.add_argument('ports', metavar='IF', type=str, nargs='*',
                        help='A physical interface to use')
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Debug (default: disabled)')
    parser.add_argument('--nocli', action='store_true', default=False,
                        help='Disable the CLI')
    parser.add_argument('--cfg', help='Use specified config file',
                        default=None)
    args = parser.parse_args()

    instance_count = CFG.getint(DEFAULTSECT, 'controller_instance_number')

    # Update default config
    if args.cfg:
        CFG.read(args.cfg)
        fibbingnode.BIN = CFG.get(DEFAULTSECT, 'quagga_path')
    # Check if we need to force debug mode
    if args.debug:
        CFG.set(DEFAULTSECT, 'debug', '1')
    if CFG.getboolean(DEFAULTSECT, 'debug'):
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)
    # Check for any specified physical port to use both in config file
    # or in args
    ports = set(p for p in CFG.sections()
                if not (p == 'fake' or p == 'physical' or p == DEFAULTSECT))
    ports.update(args.ports)
    if not ports:
        log.warning('The fibbing node will not be connected '
                    'to any physical ports!')
    else:
        log.info('Using the physical ports: %s', ports)
    return ports, instance_count, not args.nocli


def main(_CLI=FibbingCLI):
    phys_ports, name, cli = handle_args()
    if not cli:
        fibbingnode.log_to_file('%s.log' % name)
    mngr = FibbingManager(name)

    def sig_handler(sig, frame):
        mngr.cleanup()
        fibbingnode.EXIT.set()
        sys.exit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    try:
        mngr.start(phys_ports=phys_ports)
        if cli:
            cli = _CLI(mngr=mngr)
            cli.cmdloop()
            fibbingnode.EXIT.set()
    except Exception as e:
        log.exception(e)
        fibbingnode.EXIT.set()
    finally:
        fibbingnode.EXIT.wait()
        mngr.cleanup()


if __name__ == '__main__':
    main()
