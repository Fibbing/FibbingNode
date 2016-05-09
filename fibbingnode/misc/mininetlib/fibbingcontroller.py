import signal
import os
import subprocess

import ConfigParser as cparser

import mininet.node as _node

from fibbingnode.misc.mininetlib import get_logger, CFG_KEY, otherIntf,\
                                        L3Router
from fibbingnode.misc.utils import del_file, force


log = get_logger()


class FibbingController(_node.Host, L3Router):

    instance_count = 0

    def __init__(self, name, cfg_path=None, quiet=False, *args, **kwargs):
        super(FibbingController, self).__init__(name, *args, **kwargs)
        self.config_params = kwargs.get(CFG_KEY, {})
        self.socket_path = "/tmp/%s.socket" % self.name
        self.cfg_path = "%s.cfg" % self.name if not cfg_path else cfg_path
        self.instance_number = FibbingController.instance_count
        self.quiet = quiet
        FibbingController.instance_count += 1

    def start(self):
        self.cmd('ip', 'link', 'set', 'dev', 'lo', 'up')
        itfs = self.dump_cfg_info()
        log.info('Starting southbound controller for ', self.name, '\n')
        args = ['python', '-m', 'fibbingnode',  # '--nocli',
                '--cfg', self.cfg_path]
        args.extend(itfs)
        serr = sout = (None if not self.quiet else open(os.devnull, 'wb'))
        self.process = self.popen(args,
                                  stdin=subprocess.PIPE,
                                  stderr=serr,
                                  stdout=sout)

    def stop(self, *args, **kwargs):
        def _timeout(sig, frame):
            if not self.process.returncode:
                raise Exception

        # TODO figure out why calling process.send_signal(signal.SIGINT)
        # was not working properly ... (in conjunction with --nocli)
        signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(2)
        force(self.process.communicate, 'exit\n')
        signal.alarm(0)
        super(FibbingController, self).stop(*args, **kwargs)

    def terminate(self, *args, **kwargs):
        force(self.process.terminate)
        del_file(self.socket_path)
        super(FibbingController, self).terminate(*args, **kwargs)

    def dump_cfg_info(self):
        cfg = cparser.ConfigParser()
        for key, val in self.config_params.iteritems():
            cfg.set(cparser.DEFAULTSECT, key, val)
        cfg.set(cparser.DEFAULTSECT,
                'json_hostname', 'unix://%s' % self.socket_path)
        cfg.set(cparser.DEFAULTSECT,
                'controller_instance_number',
                self.instance_number)
        connected_intfs = [itf
                           for itf in self.intfList()
                           if L3Router.is_l3router_intf(otherIntf(itf)) and
                           itf.name != 'lo']
        for itf in connected_intfs:
            cfg.add_section(itf.name)
            n = otherIntf(itf).node
            cfg.set(itf.name, 'hello_interval', n.hello_interval)
            cfg.set(itf.name, 'dead_interval', n.dead_interval)
        with open(self.cfg_path, 'w') as f:
            cfg.write(f)
        return (itf.name for itf in connected_intfs)
