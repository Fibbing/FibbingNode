from mininet.topo import Topo


class IPTopo(Topo):
    def __init__(self, *args, **kwargs):
        super(IPTopo, self).__init__(*args, **kwargs)

    def addController(self, name, **kwargs):
        return self.addNode(name, isController=True, **kwargs)

    def __isNodeType(self, n, x):
        try:
            return self.g.node[n].get(x, False)
        except KeyError:
            return False

    def isController(self, n):
        return self.__isNodeType(n, 'isController')

    def addRouter(self, name, **kwargs):
        return self.addNode(name, isRouter=True, **kwargs)

    def isRouter(self, n):
        return self.__isNodeType(n, 'isRouter')

    def hosts(self, sort=True):
        return [h for h in super(IPTopo, self).hosts(sort)
                if not (self.isRouter(h) or self.isController(h))]

    def routers(self, sort=True):
        return [r for r in self.nodes(sort) if self.isRouter(r)]

    def controllers(self, sort=True):
        return [c for c in self.nodes(sort) if self.isController(c)]
