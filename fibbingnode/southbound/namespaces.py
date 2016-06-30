import subprocess
import inspect
import os
from time import sleep
from fibbingnode import log
from fibbingnode.misc.utils import need_root

NSDIR = '/var/run/netns'

# Cannot play with net namespaces if we're not root
need_root()


def _netns(*args, **kwargs):
    cmd = ['ip', 'netns']
    cmd.extend(args)
    log.debug(str(cmd))
    return subprocess.call(cmd, **kwargs)


class NetworkNamespace(object):
    ID = -1

    def __init__(self):
        NetworkNamespace.ID += 1
        self.id = NetworkNamespace.ID
        self.name = 'ns%d' % self.id
        self.create_ns()

    def create_ns(self):
        if os.path.exists(NSDIR) and ' %s ' % self.name in os.listdir(NSDIR):
            self.delete()
        err = _netns('add', self.name)
        if err != 0:
            log.error('Failed to create namespace %s', self.name)
        else:
            log.debug('Created namespace %s', self.name)

    def call(self, *args, **kwargs):
        return _netns('exec', self.name, *args, **kwargs)

    def pipe(self, *args, **kwargs):
        cmd = ['ip', 'netns', 'exec', self.name]
        cmd.extend(args)
        log.debug(str(cmd))
        if 'stdin' not in kwargs:
            kwargs['stdin'] = subprocess.PIPE
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.PIPE
        if 'stderr' not in kwargs:
            kwargs['stderr'] = subprocess.STDOUT
        return subprocess.Popen(cmd, **kwargs)

    def capture_port(self, port):
        log.debug('Moving port %s into namespace %s', port, self.name)
        return subprocess.call(
                ['ip', 'link', 'set', port.id, 'netns', self.name])

    def delete(self):
        sleep(.2)
        log.debug('Removing namespace %s', self.name)
        _netns('delete', self.name)


class RootNamespace(object):
    def __init__(self):
        self.name = 'root'
        # This namespace does nothing special
        for attr, _ in inspect.getmembers(NetworkNamespace,
                                          predicate=inspect.ismethod):
            setattr(self, attr, self._proxy)
        # Except the standard calls ...
        setattr(self, 'call', self._call)
        setattr(self, 'pipe', self._pipe)

    def _call(self, *args, **kwargs):
        log.debug('%s NS call data: %s // %s', self.name, args, kwargs)
        return subprocess.call(args, *kwargs)

    def _pipe(self, *args, **kwargs):
        if 'stdin' not in kwargs:
            kwargs['stdin'] = subprocess.PIPE
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.PIPE
        if 'stderr' not in kwargs:
            kwargs['stderr'] = subprocess.STDOUT
        return subprocess.Popen(args, **kwargs)

    def _proxy(*args, **kwargs):
        pass
