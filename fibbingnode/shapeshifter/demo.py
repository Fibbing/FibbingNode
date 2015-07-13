#!/usr/bin/env python
# encoding: utf-8

from southbound_interface import SouthboundManager
import networkx as nx
from ladder import OspfNaiveLadder

R1 = '1.1.1.1'
R2 = '2.2.2.2'
R3 = '3.3.3.3'
R4 = '4.4.4.4'

requirements = {
        '5.0.3.0/24': nx.DiGraph([(R1, R4), (R4, R3)]),
        '5.0.1.0/24': nx.DiGraph([(R1, R2), (R2, R3)])
}

manager = SouthboundManager(requirements,
                            optimizer=OspfNaiveLadder())
try:
    manager.run()
except KeyboardInterrupt:
    manager.stop()
