from cmd import Cmd
import logging
import time
from threading import Thread
from fibbingnode import log
from fibbingnode.misc.sjmp import SJMPClient, SJMPServer, ProxyCloner

H = 'localhost'
P = 12345


class EchoProxy(object):
    def echo(self, str):
        return str

    def sum(self, a, b):
        """
        Docstring for the sum method
        :param a: Ideally an integer ...
        :param b: Same than a
        :return: a + b, might just crash as well if given garbage
        """
        return int(a) + int(b)

    def some_func(self, d):
        return 'some_func %s' % d


class TestCLI(Cmd):
    Cmd.prompt = '> '

    def __init__(self, client, *args, **kwargs):
        Cmd.__init__(self, *args, **kwargs)
        self.client = client

    def do_echo(self, line):
        self.client.execute('echo', line)

    def do_sum(self, line):
        a, b = line.split(' ')
        # Invoke a sum method on the remote end, with 2 parameters,
        # named and unnamed
        self.client.execute('sum', a, b=b)

    def do_exit(self, line):
        return True

    def do_info(self, line):
        # Query the remopte end for the supported methods/docs/args
        self.client.ask_info()

    def default(self, line):
        items = line.split(' ')
        self.client.execute(items[0], *items[1:])

if __name__ == '__main__':
    log.setLevel(logging.DEBUG)
    s = SJMPServer(H, P, target=EchoProxy())
    c = SJMPClient(H, P)
    a = ProxyCloner(EchoProxy, c)
    log.debug(dir(a))
    st = Thread(target=s.communicate, name='server')
    st.daemon = True
    st.start()
    log.debug('Started server')
    ct = Thread(target=c.communicate, name='client')
    ct.daemon = True
    ct.start()
    log.debug('Started client')
    a.echo('hello world')
    a.sum(1, 2)
    TestCLI(c).cmdloop()
    c.stop()
    s.stop()
