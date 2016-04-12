"""
As this module has an hard dependency against mininet and on the availability
of some commands, perform the import at the top-level in order to make the
relevant checks once, at import time.
Furthermore, all these classes will be import anyway at some point when
instantiating a Fibbing lab ...
"""
try:
    import mininet  # noqa
except ImportError as e:
    from fibbingnode import log
    import sys
    log.error('Failed to import mininet!')
    log.error('Using the mininetlib module requires mininet to be '
              'installed.\n'
              'Visit www.mininet.org to learn how to do so.\n')
    sys.exit(1)


PRIVATE_IP_KEY = '__fibbing_private_ips'
CFG_KEY = '__fibbing_controller_config_key'
BDOMAIN_KEY = '__fibbing_broadcast_domains'
FIBBING_MIN_COST = 2
FIBBING_DEFAULT_AREA = '0.0.0.0'
DEBUG_FLAG = False


def get_logger():
    import mininet.log as l
    l.setLogLevel('info')
    return l.lg


def otherIntf(intf):
    """"Get the interface on the other of a link"""
    l = intf.link
    return (l.intf1 if l.intf2 == intf else l.intf2) if l else None


class L3Router(object):
    """Dumb class to enable for easy detection of node types through
    isinstance"""
    @staticmethod
    def is_l3router_intf(itf):
        """Returns whether an interface belongs to an L3Router
        (in the Mininet meaning: an intf with an associated node)"""
        return isinstance(itf.node, L3Router)


def routers_in_bd(bd, cls=None):
    return list(filter(L3Router.is_l3router_intf if not cls else
                       cls.is_l3router_intf,
                bd))
