import pytest
import ipaddress


@pytest.mark.parametrize('address', [
    '::/0', '0.0.0.0/0', '1.2.3.0/24', '2001:db8:1234::/48'
])
def test_nested_ip_networks(address):
    """This test ensures that we can build an IPvXNetwork from another one.
    If this breaks, need to grep through for ip_network calls as I removed the
    checks when instantiating these ...
    Test passing with py2-ipaddress (3.4.1)"""
    _N = ipaddress.ip_network
    n1 = _N(address)  # Build an IPvXNetwork
    n2 = _N(n1)  # Build a new one from the previous one
    assert (n1 == n2 and
            n1.with_prefixlen == address and
            n2.with_prefixlen == address and
            n1.max_prefixlen == n2.max_prefixlen)
