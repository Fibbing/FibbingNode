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
