import subprocess
import sys
from fibbingnode import log, CFG


class Port(object):
    """
    A port on a node and its associated properties
    """
    def __init__(self, node, link, id=None, cost=CFG.get('fake', 'cost'), dead_int=CFG.get('fake', 'dead_interval'),
                 hello_int=CFG.get('fake', 'hello_interval'), area=CFG.get('fake', 'area')):
        """
        :param node: The node owning this port
        :param link: The link in which this port belongs
        :param id: The id of this port, otherwise infer it from the node next available port number
        :param cost: The OSPF cost of that interface
        :param dead_int: The OSPF dead interval for that interface
        :param hello_int: The OSPF Hello interval
        """
        self.node = node
        self.link = link
        self.id = '%s-eth%s' % (node.id, node.get_next_port()) if not id else id
        self.ip_interface = None
        self.ospf_area = area
        self.ospf_cost = cost
        self.ospf_dead_int = dead_int
        self.ospf_hello_int = hello_int

    def move_in_namespace(self):
        """
        Move this port into its node's namespace
        """
        self.node.add_port(self)
        self.node.call('ip', 'link', 'set', self.id, 'up')

    def set_ip(self, ip):
        """
        Set this port's IP address
        :param ip: an IPV4Address
        """
        if self.ip_interface:
            # Remove the previous address if any
            self.del_ip(self.ip_interface)
        self.ip_interface = ip
        log.debug('Assigning %s to %s', ip, self.id)
        self.node.call('ip', 'addr', 'add', ip.with_prefixlen, 'dev', self.id)

    def del_ip(self, ip):
        """
        Remove an IP address from this port
        :param ip: an IPV4Address
        """
        log.debug('Removing %s from %s ip''s', ip, self.id)
        self.node.call('ip', 'addr', 'delete', ip.with_prefixlen)

    def __str__(self):
        return '%s%s' % (
            self.id, '' if not self.ip_interface
            else ('@%s' % self.ip_interface.with_prefixlen))

    def delete(self):
        self.node.del_port(self)


class Link(object):
    """
    A Link between two nodes, virtual.
    """
    def __init__(self, src, dst):
        """
        :param src: source Node
        :param dst: destination Node
        """
        # Create the port
        self.src = Port(src, self)
        self.dst = Port(dst, self)
        # Use their newly-made id to create the link
        self.create_link()
        # Move them into their node's namespace
        self.src.move_in_namespace()
        self.dst.move_in_namespace()

    def create_link(self):
        """
        Create a veth link between the source and the destination ports
        """
        cmd = ['ip', 'link', 'add', self.src.id, 'type', 'veth', 'peer', 'name', self.dst.id]
        log.debug('Creating link: %s', cmd)
        err = subprocess.call(cmd)
        if err != 0:
            log.error('Failed to create veth link: %s', cmd)
            sys.exit(1)

    def delete(self):
        """
        Delete this link and its associate ports
        """
        self.src.delete()
        self.dst.delete()
        # veth links are deleted as soon as one of their port is deleted
        subprocess.call(['ip', 'link', 'del', self.src.id])

    def __str__(self):
        return 'Link %s--%s' % (self.src, self.dst)


class PhysicalLink(object):
    """
    A link to 'the outside world'. Has a single port associated to it
    """
    def __init__(self, node, port_name, port_ip):
        """
        :param node: The node owning this link
        :param port_name: The name of the only port visible on this link
        :param port_ip: The IPV4Address of that link
        """
        section = port_name if CFG.has_section(port_name) else 'physical'
        self.src = Port(node, self, port_name, hello_int=CFG.get(section, 'hello_interval'),
                        dead_int=CFG.get(section, 'dead_interval'), area=CFG.get(section, 'area'),
                        cost=CFG.get(section, 'cost'))
        self.src.move_in_namespace()
        self.src.set_ip(port_ip)
        self.node = node
        self.name = port_name

    def move_to_root(self):
        self.node.call('ip', 'link', 'set', 'dev', self.name, 'netns', '1')

    def __str__(self):
        return 'Physical Link from %s' % self.src

    def delete(self):
        self.src.delete()
