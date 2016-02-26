import os
import json
import pytest

from fibbingnode.southbound.lsdb import PrivateAddressStore


SIMPLE_TESTFILE = os.path.join(os.path.dirname(__file__),
                               'private_ipaddresses.json')


@pytest.fixture(scope="function")
def simple_address_file(request):
    d = {"10.127.255.252/30":
         {"192.168.239.254": ["10.127.255.254/30"],
          "192.168.251.254": ["10.127.255.253/30"]},
         "10.191.255.252/30":
         {"192.168.251.253": ["10.191.255.253/30"],
          "192.168.251.254": ["10.191.255.254/30"]},
         "10.223.255.252/30":
         {"192.168.239.254": ["10.223.255.254/30"],
          "192.168.255.253": ["10.223.255.253/30"]},
         "10.255.255.252/30":
         {"192.168.251.253": ["10.255.255.254/30"],
          "192.168.255.253": ["10.255.255.253/30"]}}
    with open(SIMPLE_TESTFILE, 'w') as f:
        json.dump(d, f)

    def __teardown():
        os.unlink(SIMPLE_TESTFILE)
    request.addfinalizer(__teardown)

    return PrivateAddressStore(SIMPLE_TESTFILE), d


def same_lists(x, y):
    return len(x) == len(y) and sorted(y) == sorted(x)


def test_simple(simple_address_file):
    store, d = simple_address_file
    # sample queries
    assert same_lists(store.targets_for('10.223.255.253/30'),
                      ['192.168.239.254'])
    assert same_lists(store.addresses_of('192.168.239.254'),
                      ['10.127.255.254/30', '10.223.255.254/30'])
