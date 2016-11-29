import traceback
import cStringIO as StringIO
import sys
import os
import json
import socket
import select
import inspect
import logging
from urlparse import urlparse

from .utils import start_daemon_thread

log = logging.getLogger(__name__)


def sock_readline(s):
    buf = ''
    data = True
    while data:
        data = s.recv(1)
        if data == '\n':
            yield buf
            buf = ''
        else:
            buf += data

ARG_LIST = 'arg_list'
ARG_DICT = 'arg_dict'
CMD = 'cmd'
CMD_ARG = 'cmd_arg'
DISPLAY = 'display'
EXEC = 'exec'
EXCEPTION = 'exception'
INFO = 'info'
METHOD = 'method'
PING = 'ping'
PONG = 'pong'
RESULT = 'result'


class SimpleJSONMessagePassing(object):
    def __init__(self, socket, target=None, name='Unnamed JSON agent'):
        """
        :param socket: A connected socket
        :param target: The object on which the commands should be executed
                        (or self if None)
        :param name: The name of the JSON agent
        """
        self.name = name
        self.s = socket
        self.stopped = True
        self.target = target if target else self
        self.hooks = {
            DISPLAY: self._json_display,
            EXEC: self._json_exec,
            EXCEPTION: self._json_exception,
            INFO: self._json_info,
            PING: self._json_ping,
            RESULT: self._json_result
        }

    def alive(self):
        return not self.stopped

    def communicate(self, timeout=5.0):
        """
        Listen (until stop() is called) for incoming messages and execute the
        corresponding actions
        :param timeout: How long should we block at most before checking if we
                        should stop listening
        """
        self.stopped = False
        while not self.stopped:
            # Enforce read time out with select
            try:
                r, _, _ = select.select([self.s], [], [], timeout)
            except select.error:
                break
            else:
                if not r:
                    # keepalive
                    self._json_send(PING, {})
                    continue
                try:
                    line = next(sock_readline(self.s))
                except:
                    log.debug('Socket is no longer readable, '
                              'stopping communicate()')
                    break
                else:
                    try:
                        decoded = json.loads(line, encoding='utf-8')
                    except ValueError:
                        log.debug('Malformed JSON message [%s] -- ignoring',
                                  line)
                        # TODO - is it safe?
                        continue
                    else:
                        for key, f in self.hooks.items():
                            if key == decoded[CMD]:
                                f(decoded[CMD_ARG])

    def stop(self):
        """
        Stop listening for incoming messages
        """
        log.debug('Stopped JSONMP agent %s', self.name)
        self.stopped = True

    def execute(self, method, *args, **kwargs):
        """
        Execute a method on the remote end
        :param method: The method name
        :param args: the non-keywords arguments for that method
        :param kwargs: the keywords arguments for that method
        """
        self._json_send(EXEC, {
            METHOD: method,
            ARG_LIST: args,
            ARG_DICT: kwargs
        })

    def ask_info(self):
        """
        Actively request the remote end to send us the descriptions
        of its exposed methods
        """
        self._json_send(INFO, {})

    def _json_exec(self, cmd_arg):
        """
        Remote execute call
        """
        try:
            method = getattr(self.target, cmd_arg[METHOD])
            result = method(*cmd_arg.get(ARG_LIST, []),
                            **cmd_arg.get(ARG_DICT, {}))
        except KeyError as e:
            self._send_exception(e, cmd_arg)
        except Exception as e:
            log.exception(e)
            self._send_exception(e, cmd_arg)
        else:
            # Send back command result if any
            if result:
                self._json_send(RESULT, result)

    @staticmethod
    def _json_exception(cmd_arg):
        """
        Log remote exceptions
        """
        log.error('%s generated a remote exception:\n\t%s',
                  cmd_arg[CMD_ARG], cmd_arg[EXCEPTION])

    @staticmethod
    def _json_result(cmd_arg):
        log.info('Remote result: %s', cmd_arg)

    @staticmethod
    def _json_display(cmd_arg):
        strs = []
        for name, other in cmd_arg.items():
            strs.append('\n%s: %s'
                        % (name, ' '.join(filter(lambda x: not x == 'self',
                                                 other['args']))))
            if other['doc']:
                strs.append('%s' % other['doc'])
        log.info('%s', ''.join(strs))

    def _json_info(self, cmd_arg):
        self._json_send(DISPLAY, {
            name: {'doc': m.__doc__, 'args': inspect.getargspec(m)[0]}
            for name, m in inspect.getmembers(self.target.__class__,
                                              predicate=inspect.ismethod)
        })

    def _json_ping(self, cmd_arg):
        self._json_send(PONG, {})

    def _send_exception(self, e, args):
        s = StringIO.StringIO()
        traceback.print_tb(sys.exc_info()[2], file=s)
        self._json_send(EXCEPTION, {
            CMD_ARG: args,
            EXCEPTION: '%s\n%s' % (str(e), s.getvalue())
        })
        s.close()

    def _json_send(self, cmd_name, cmd_dict):
        s = json.dumps({
            CMD: cmd_name,
            CMD_ARG: cmd_dict
        }, encoding='utf-8')
        try:
            self.s.send(s)
            self.s.send('\n')
        except Exception as e:
            log.debug('Failed to send JSON data -- is the socket still alive? '
                      '(%s)', e)


def _get_socket(hostname, port, unlink=False):
    url = urlparse(hostname)
    if url.scheme != 'unix':
        af = socket.AF_INET
        args = (hostname, port)
    else:
        af = socket.AF_UNIX
        args = url.path
        log.info('Listening on unix socket: %s', args)
        if unlink and os.path.exists(args):
            os.unlink(args)
    s = socket.socket(af, socket.SOCK_STREAM)
    return s, args


class SJMPServer():
    """
    Sample Server that will accept one client per call to communicate
    """
    def __init__(self, hostname, port,
                 invoke=None, target=None, max_clients=5):
        """
        :param hostname: Hostname on which to listen, '' to accept any origin
        :param port: The TCP port to listen on
        :param invoke: The method to call at a new client connection
        :param target: The object to expose, will fallback to self if None
        :param max_clients: The max number of concurrent connection
        """
        s, pathspec = _get_socket(hostname, port, unlink=True)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.bind(pathspec)
        self.server_socket = s
        s.listen(max_clients)
        self.invoke = invoke
        self.target = target
        self.client_count = 0

    """This call never returns!"""
    def communicate(self, timeout=5.0, *args, **kwargs):
        while True:
            def accept():
                r, _, _ = select.select([self.server_socket], [], [], timeout)
                if not r:
                    return False
                return self.server_socket.accept()[0]
            try:
                client = False
                while not client:
                    client = accept()
            except socket.error:
                return
            else:
                self.client_count += 1
                thread = start_daemon_thread(
                        target=_new_server_client,
                        args=(client, self.invoke, self.target),
                        name='SJMPClient%s' % self.client_count)

    def stop(self):
        self.server_socket.close()


def _new_server_client(sock, invoke, target):
    log.debug('New SJMP client')
    sjmp = SimpleJSONMessagePassing(sock, target=target)
    if invoke:
        invoke(sjmp)
    sjmp.communicate()
    sock.close()
    if invoke:
        invoke(sjmp)
    log.debug('Closed connection to an SJMP client')


class SJMPClient(SimpleJSONMessagePassing):
    """
    Sample Client that will connect to a server
    """
    def __init__(self, hostname, port, target=None):
        """
        :param hostname: The hostname of the server
        :param port: The TCP port it is listening on
        :param target: The object to expose, will fallback to self if None
        """
        s, pathspec = _get_socket(hostname, port)
        s.connect(pathspec)
        super(SJMPClient, self).__init__(s, target=target, name='SJMPClient')

    def stop(self):
        super(SJMPClient, self).stop()
        self.s.close()


class ProxyCloner(object):
    """
    Class that will mimic an object methods but in fact
    send the calls over the networks
    """
    def __init__(self, proxy_class, session):
        """
        :param proxy_class: The class to mimic
                            (e.g. one exposed in interface.py)
        :param session: An object who has an execute method
                        (ideally an SimpleJSONMessagePassing instance)
        """
        for name, _ in inspect.getmembers(proxy_class,
                                          predicate=inspect.ismethod):
            setattr(self, name, _ProxyMethod(name, session))
        self.session = session


class _ProxyMethod(object):
    def __init__(self, name, session):
        self.session = session
        self.name = name

    def __call__(self, *args, **kwargs):
        self.session.execute(self.name, *args, **kwargs)
