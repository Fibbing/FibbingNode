import logging
import os
import ConfigParser
import threading

EXIT = threading.Event()

# Path to the templates directory
RES = os.path.join(os.path.dirname(__file__), 'res')
TEMPLATES = os.path.join(RES, 'templates')


def get_template_path(name):
    return os.path.realpath(os.path.join(TEMPLATES, name))

CFG = ConfigParser.ConfigParser()
with open(os.path.join(RES, 'default.cfg'), 'r') as f:
    CFG.readfp(f)

# Path to the directory containing the Quagga-Fibbing installation
BIN = CFG.get(ConfigParser.DEFAULTSECT, 'quagga_path')

# Warnings are orange
logging.addLevelName(logging.WARNING, "\033[1;43m%s\033[1;0m" %
                                      logging.getLevelName(logging.WARNING))
# Errors are red
logging.addLevelName(logging.ERROR, "\033[1;41m%s\033[1;0m" %
                                    logging.getLevelName(logging.ERROR))
# Debug is green
logging.addLevelName(logging.DEBUG, "\033[1;42m%s\033[1;0m" %
                                    logging.getLevelName(logging.DEBUG))
# Information messages are blue
logging.addLevelName(logging.INFO, "\033[1;44m%s\033[1;0m" %
                                   logging.getLevelName(logging.INFO))
# Critical messages are violet
logging.addLevelName(logging.CRITICAL, "\033[1;45m%s\033[1;0m" %
                                       logging.getLevelName(logging.CRITICAL))

log = logging.getLogger(__name__)
fmt = logging.Formatter('%(asctime)s [%(levelname)20s] %(funcName)s: %(message)s')
handler = logging.StreamHandler()
handler.setFormatter(fmt)
log.addHandler(handler)


def log_to_file(filename, mode='a'):
    import datetime
    handler = logging.FileHandler(filename, mode)
    handler.setFormatter(fmt)
    log.addHandler(handler)
    now = datetime.datetime.now()
    log.info('==== Session start: %s', now.isoformat())
