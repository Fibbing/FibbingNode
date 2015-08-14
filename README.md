# FibbingNode
This repository contains the code to run a fibbing controller
that is able to control unmodified OSPF router to setup arbitrary paths in the network.

The controller is currently compatible only with python 2.

The controller code is split into 3 main parts:

1. The [Quagga](https://github.com/Fibbing/Quagga) directory, that contains a modified version of quagga that is able to craft
and flood arbitrary Type-5 LSA which are used to inject the lies in the network.
2. The Southbound controller, the [fibbingnode](https://github.com/Fibbing/FibbingNode/tree/master/fibbingnode) python module, that will control the quagga ospfd instances
and trigger the injection/removal of these LSAs, as well as infer the current network topology
and decide whether the current instance of the controller is the 'master' one in case multiple controllers are
present in the network. A critical file to tune is the config file, whose defaults are specified in [fibbingnode/res/default.cfg](https://github.com/Fibbing/FibbingNode/blob/master/fibbingnode/res/default.cfg).It can then be run via 
```bash
python2 -m fibbingnode
```
3. The Northbound controller, [fibbingnode/shapeshifter](https://github.com/Fibbing/FibbingNode/tree/master/fibbingnode/shapeshifter)
which implements the algorithms to compute the augmented topology and then communicates to the
southern part through a json insterface. An example use of it is available in [tests/demo.py](https://github.com/Fibbing/FibbingNode/blob/master/tests/demo.py)

# Basic installation

```bash
git clone --recursive https://github.com/Fibbing/FibbingNode.git
./setup.sh
```

This will install the quagga distribution under /opt/fibbing/ and the fibbingnode python module
