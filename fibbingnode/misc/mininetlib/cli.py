from ipaddress import ip_address
from mininet.cli import CLI


class FibbingCLI(CLI):
    def do_route(self, line=""):
        """route destination: Print all the routes towards that destination
        for every router in the network"""
        for r in self.mn.routers:
            self.default('%s ip route get %s' % (r.name, line))

    def do_ip(self, line):
        """ip IP: return the node associated to IP"""
        try:
            print self.mn.node_for_ip(line)
        except KeyError:
            print 'No matching for for ip', line

    def do_traceroute(self, line):
        """traceroute SRC DEST: show the traceroute from SRC towards DEST
        SRC is a node name
        DEST is a node or an IP address"""
        try:
            src, dst = line.split(' ')
            s = self.mn[src]
            try:
                d = self.mn[dst].defaultIntf().ip
            except KeyError:
                d = ip_address(dst)
            result = s.cmd('traceroute', '-4n', '-w1', '-q1', str(d))
            ips = ['%s (%s)' % (self.mn.ip_allocs.get(ip, 'Unknown'), ip)
                   for ip in _parse_traceroute(result)]
            print '*** %s to %s (%s):\n%s' % (src, dst, d, '\n'.join(ips))
        except (ValueError, KeyError) as e:
            print 'Missing argument(s): SRC DST [error was: %s]' % str(e)


def _parse_traceroute(res):
    """Return an iterator over all hops in a traceroute result string"""
    for line in res.splitlines()[1:]:
        _, rest = _part_strip_split(line, ' ')
        hop, _ = _part_strip_split(rest, ' ')
        yield hop


def _part_strip_split(line, sep):
    """Return the two members resulting from stripping both ends of the line
    from blank chars and then splitting at the first occurance of the
    separator"""
    return line.strip(' \r\n\t').split(sep, 1)
