from mininet.node import Node

from ipaddress import ip_interface

from fibbingnode.misc.mininetlib import get_logger, PRIVATE_IP_KEY,\
                                        FIBBING_MIN_COST, otherIntf,\
                                        BDOMAIN_KEY, L3Router, routers_in_bd
import fibbingnode.misc.router

log = get_logger()
fibbingnode.misc.router.log = log

from fibbingnode.misc.router import QuaggaRouter, RouterConfigDict
from fibbingnode.misc.utils import ConfigDict


class MininetRouter(QuaggaRouter):
    def __init__(self, node, *args, **kwargs):
        super(MininetRouter, self).__init__(name=node.name,
                                            working_dir='/tmp',
                                            *args, **kwargs)
        self.mnode = node

    def call(self, *args, **kwargs):
        return self.mnode.cmd(*args, **kwargs)

    def pipe(self, *args, **kwargs):
        return self.mnode.popen(*args, **kwargs)

    def get_config_node(self):
        return MininetRouterConfig(self.mnode)


class IPRouter(Node, L3Router):
    def __init__(self, name, private_net='10.0.0.0/8',
                 routerid=None, static_routes=(), **kwargs):
        """static_routes in the form of (prefix, via_node_id)*"""
        self.private_net = str(private_net)
        self.rid = routerid
        self.static_routes = static_routes
        self.hello_interval = '1'
        self.dead_interval = 'minimal hello-multiplier 5'
        super(IPRouter, self).__init__(name, **kwargs)
        self.router = MininetRouter(self)

    def start(self):
        self.cmd('ip', 'link', 'set', 'dev', 'lo', 'up')
        for itf in self.intfList():
            for ip in itf.params.get(PRIVATE_IP_KEY, ()):
                self.cmd('ip', 'address', 'add', ip,
                         'dev', itf.name, 'scope', 'link')
        neighbor_to_intf = {otherIntf(itf).name: itf
                            for itf in self.intfList()}
        self.static_routes = [(p, v if v not in neighbor_to_intf
                               else neighbor_to_intf[v])
                              for p, v in self.static_routes]
        self.router.start()

    def terminate(self):
        self.router.delete()
        super(IPRouter, self).terminate()

    @property
    def id(self):
        return self.rid if self.rid else self.intfList()[0].ip

    def ospf_interfaces(self):
        # We will only 'configure' the interfaces belonging to a broadcast
        # domain where there is another OSPF router.
        # We will advertize the others through redistribute.connected
        def include_func(itf):
            return list(filter(lambda x: x.node != self,
                               routers_in_bd(itf.params.get(BDOMAIN_KEY, ()))))

        return filter(include_func, self.intfList())


class MininetRouterConfig(RouterConfigDict):
    def __init__(self, router):
        super(MininetRouterConfig, self).__init__(router)
        self.ospf.redistribute.connected = 1000
        self.ospf.redistribute.static = 1000
        self.ospf.router_id = router.id

    def build_ospf(self, router):
        cfg = super(MininetRouterConfig, self).build_ospf(router)
        networks = []
        for itf in router.ospf_interfaces():
            c = itf.params.get('cost', FIBBING_MIN_COST)
            cfg.interfaces\
               .append(ConfigDict(name=itf.name,
                                  description=str(itf.link),
                                  ospf=ConfigDict(cost=c,
                                                  priority=10,
                                                  dead_int=router
                                                  .dead_interval,
                                                  hello_int=router
                                                  .hello_interval)))
            networks.append(ip_interface('%s/%s' % (itf.ip, itf.prefixLen))
                            .network)
            # TODO figure out the private config knob so that the private
            # addresses dont create redundant OSPF session over the same
            # interface ...
            try:
                networks.append(ip_interface(itf.params[PRIVATE_IP_KEY][0])
                                .network)
            except KeyError:
                pass  # No private ip on that interface
        for net in networks:
            cfg.networks.append(ConfigDict(domain=net.with_prefixlen,
                                           area='0.0.0.0'))
        return cfg

    def build_zebra(self, router):
        cfg = super(MininetRouterConfig, self).build_zebra(router)
        # Create route map to ignore 'private' addresses
        plen = int(router.private_net.split('/')[1])
        cfg.prefixlists = [ConfigDict(name='PRIVATE',
                                      action='permit',
                                      prefix=router.private_net,
                                      ge=plen + 1)]
                          # ConfigDict(name='PRIVATE',
                          #             action='deny',
                          #             prefix='any')]
        cfg.routemaps = [ConfigDict(name='IMPORT',
                                    action='deny',
                                    prio='10',
                                    prefix=['PRIVATE'],
                                    proto=[]),
                         ConfigDict(name='IMPORT',
                                    action='permit',
                                    prio='20',
                                    prefix=[],
                                    proto=['ospf'])]
        cfg.static_routes.extend(router.static_routes)
        return cfg
