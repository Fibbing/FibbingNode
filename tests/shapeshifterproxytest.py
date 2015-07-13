from ConfigParser import DEFAULTSECT
from cmd import Cmd
import logging
from threading import Thread
from fibbingnode import CFG, log
from fibbingnode.sjmp import SJMPClient, ProxyCloner
from networkx import DiGraph
from fibbingnode.interface import ShapeshifterProxy, FakeNodeProxy


class ShapeshifterProxyTest(ShapeshifterProxy):
    def __init__(self):
        self.graph = DiGraph()

    def add_edge(self, source, destination, metric):
        log.info('Adding %s-%s @ %s', source, destination, metric)
        self.graph.add_edge(source, destination, cost=metric)

    def remove_edge(self, source, destination):
        log.info('Removing %s-%s', source, destination)
        self.graph.remove_edge(source, destination)

    def boostrap_graph(self, graph):
        log.info('Received graph: %s', graph)
        for u, v, m in graph:
            self.graph.add_edge(u, v, cost=m)


class TestCLI(Cmd):
    Cmd.prompt = '> '

    def __init__(self, client, *args, **kwargs):
        Cmd.__init__(self, *args, **kwargs)
        self.client = client

    def do_add(self, line=''):
        self.client.add(('192.168.14.1', '192.168.23.2', 1, '3.3.3.0/24'))
        self.client.add((None, '192.168.23.2', 1, '4.4.4.0/24'))
        self.client.add([(None, '192.168.23.2', 1, '5.5.5.0/24'),
                         (None, '192.168.14.1', 1, '5.5.5.0/24')])

    def do_remove(self, line=''):
        self.client.remove(('192.168.14.1', '192.168.23.2', '3.3.3.0/24'))
        self.client.remove((None, '192.168.23.2', '4.4.4.0/24'))
        self.client.remove([(None, '192.168.23.2', '5.5.5.0/24'),
                         (None, '192.168.14.1', '5.5.5.0/24')])

    def do_exit(self, line):
            return True

if __name__ == '__main__':
    log.setLevel(logging.DEBUG)
    shapeshifter = ShapeshifterProxyTest()
    c = SJMPClient("localhost", CFG.getint(DEFAULTSECT, "json_port"), target=shapeshifter)
    fakenode = ProxyCloner(FakeNodeProxy, c)
    Thread(target=c.communicate, name='client').start()
    TestCLI(fakenode).cmdloop()
    c.stop()
